"""Read-only validation of exact signed Tools files plus proven runtime products.

Run with the authenticated packaged CPython 3.13.16, isolated (-I -S -B).
The caller owns the disposable CI directory, verifies the signed update envelope,
and captures preferences immediately before invoking the actual old helper.
No cache is imported, executed, or unmarshalled. Only trusted source is compiled.
This BUILD-only proposal does not replace any existing acceptance/signature gate.
"""
from __future__ import annotations

import hashlib
import argparse
import ctypes
import hmac
import importlib.util
import json
import marshal
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import struct
import sys
import time
import types
import zipfile

SOURCE_COMMIT = 'ffb7307aa1368e411f386f166750ac2353cf8a2e'
SOURCE_ZIP_SHA256 = 'bde46ce3a1834353aa1107ff6f29241748e29121a5bf88cf659be1c117972ba1'
SOURCE_ZIP_BYTES = 7444893
INI_FACTORY_SOURCE_SHA256 = '2b6d16a1ec80403bfba281b4457f4fa01448598951a4dd7a2b00978506b19f46'
INI_DEFAULT_BYTES = b'[input]\r\nkeyboard=uhid\r\nmouse=uhid\r\n'
INI_DEFAULT_SHA256 = '85321301107c054874655bcde48dcb4ab6a47f1fc056fabe820320b23be8b321'
UPDATE_ZIP_SHA256 = '00c669e4952d67b2798989da2de21d59a43359cfd0d510da0c16312c8b2638d9'
UPDATE_ZIP_BYTES = 411769682
MANAGED_FILE_COUNT = 3905
INI = 'KIOControl.ini'
CANARY = 'bogo-ci-user-document.txt'
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_PYC_BYTES = 8 * 1024 * 1024
MAX_EXTRA_FILES = 512
MAGIC = bytes.fromhex('f30d0d0a')
CACHE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\.cpython-313(?:\.opt-([12]))?\.pyc\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


class Rejected(ValueError):
    pass


def require(value, message):
    if not value:
        raise Rejected(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def runtime_identity():
    require(sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 13, 16),
            'Exact packaged CPython 3.13.16 required')
    require(sys.implementation.cache_tag == 'cpython-313' and importlib.util.MAGIC_NUMBER == MAGIC
            and marshal.version == 4, 'CPython bytecode format differs')
    return {'implementation': 'cpython', 'version': '3.13.16', 'cacheTag': 'cpython-313',
            'magic': MAGIC.hex(), 'marshalVersion': 4}


def safe_relative(value):
    require(isinstance(value, str) and 0 < len(value) <= 512, 'Invalid relative path')
    require('\\' not in value and ':' not in value and not value.startswith('/'), 'Noncanonical relative path')
    parts = value.split('/')
    require(all(p not in ('', '.', '..') and not p.endswith((' ', '.'))
                and all(ord(c) >= 32 for c in p) for p in parts), 'Unsafe relative path')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)),
                *('LPT' + str(i) for i in range(1, 10))}
    require(all(p.split('.')[0].upper() not in reserved for p in parts), 'Windows reserved path')
    require(PurePosixPath(value).as_posix() == value, 'Relative path spelling differs')
    return value


def windows_filename(windows_root, relative):
    safe_relative(relative)
    require(isinstance(windows_root, str) and '\x00' not in windows_root and '/' not in windows_root,
            'Canonical Windows root required')
    require(len(windows_root) <= 32000, 'Windows root exceeds bound')
    root = PureWindowsPath(windows_root)
    require(bool(re.fullmatch(r'[A-Za-z]:', root.drive)) and root.is_absolute(), 'Local Windows drive root required')
    require(ntpath.normpath(windows_root) == windows_root and '..' not in windows_root.split('\\')
            and '.' not in windows_root.split('\\'), 'Noncanonical Windows root')
    require(all(ord(c) >= 32 for c in windows_root), 'Control character in Windows root')
    return ntpath.join(windows_root, *relative.split('/'))


def source_for_cache(cache_relative, runtime_optimize=0):
    safe_relative(cache_relative)
    require(type(runtime_optimize) is int and runtime_optimize in (0, 1, 2), 'Invalid actual optimize flag')
    parts = cache_relative.split('/')
    require(len(parts) >= 3 and parts[-2] == '__pycache__' and parts.count('__pycache__') == 1,
            'Only canonical PEP 3147 cache paths accepted')
    match = CACHE.fullmatch(parts[-1])
    require(match is not None, 'Wrong cache implementation/tag/filename')
    require(int(match[2] or 0) == runtime_optimize, 'Cache optimization differs from actual runtime')
    relative = '/'.join([*parts[:-2], match[1] + '.py'])
    safe_relative(relative)
    return relative


def _file_identity(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _require_same_file(before, after, message, relative, phase):
    # Diagnostic derivative ONLY. Keep every original identity comparison;
    # observe raw Windows lstat/fstat values before deciding any repair policy.
    if _file_identity(before) != _file_identity(after):
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_nlink','st_file_attributes')
        diagnostic={'phase':phase,'relativePath':safe_relative(relative)[:120],
                    'before':{key:getattr(before,key,None) for key in fields},
                    'after':{key:getattr(after,key,None) for key in fields},
                    'identityGateUnchanged':True}
        text=json.dumps(diagnostic,separators=(',',':'),sort_keys=True)
        require(len(text)<=1536,'File identity diagnostic bound exceeded')
        error=Rejected(message+'; rawFileIdentity='+text)
        error.file_identity_diagnostic=diagnostic
        raise error


class _FileBasicInfo(ctypes.Structure):
    _fields_=[('CreationTime',ctypes.c_int64),('LastAccessTime',ctypes.c_int64),
              ('LastWriteTime',ctypes.c_int64),('ChangeTime',ctypes.c_int64),('FileAttributes',ctypes.c_uint32)]


class _FileStandardInfo(ctypes.Structure):
    _fields_=[('AllocationSize',ctypes.c_int64),('EndOfFile',ctypes.c_int64),('NumberOfLinks',ctypes.c_uint32),
              ('DeletePending',ctypes.c_ubyte),('Directory',ctypes.c_ubyte)]


class _FileIdInfo(ctypes.Structure):
    _fields_=[('VolumeSerialNumber',ctypes.c_uint64),('FileId',ctypes.c_ubyte*16)]


def _validate_native_identity(value):
    keys={'volumeSerial','fileId128','creation100ns','write100ns','change100ns','attributes','size','links','deletePending','directory'}
    require(type(value)is dict and set(value)==keys,'Native file identity shape differs')
    require(type(value['volumeSerial'])is int and 0<value['volumeSerial']<2**64
            and isinstance(value['fileId128'],str) and re.fullmatch(r'[0-9a-f]{32}',value['fileId128'])is not None
            and int(value['fileId128'],16)!=0,'Native volume/128-bit file ID unavailable')
    require(all(type(value[k])is int and value[k]>0 for k in('creation100ns','write100ns','change100ns')),
            'Native creation/write/metadata-change time unavailable')
    require(type(value['attributes'])is int and 0<=value['attributes']<2**32
            and not(value['attributes']&0x400),'Native reparse point refused')
    require(type(value['size'])is int and value['size']>=0 and type(value['links'])is int and value['links']==1,
            'Native size/hardlink guard failed')
    require(value['deletePending']is False and value['directory']is False,'Native nonplain/delete-pending file refused')
    return value


class _WindowsFileAPI:
    """Read-only, same API identity domain; never close a borrowed CRT handle.

    Microsoft primary contracts: winbase/{FILE_ID_INFO, FILE_BASIC_INFO,
    FILE_STANDARD_INFO, GetFileInformationByHandleEx}; fileapi/CreateFileW.
    No SetFileInformation, write/delete access, privilege or ACL changes.
    """
    READ_ATTRIBUTES=0x80
    SHARE_READ_WRITE_DELETE=7
    OPEN_EXISTING=3
    OPEN_REPARSE_POINT=0x00200000

    def __init__(self,*,kernel=None,os_handle=None):
        if kernel is None:
            require(os.name=='nt','Windows native metadata API requires Windows')
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        if os_handle is None:
            import msvcrt
            os_handle=msvcrt.get_osfhandle
        self.kernel=kernel;self.os_handle=os_handle
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,
                                    ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle.restype=ctypes.c_int
        kernel.GetFileType.argtypes=[ctypes.c_void_p];kernel.GetFileType.restype=ctypes.c_uint32
        kernel.GetFileInformationByHandleEx.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
        kernel.GetFileInformationByHandleEx.restype=ctypes.c_int
        kernel.GetFinalPathNameByHandleW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32]
        kernel.GetFinalPathNameByHandleW.restype=ctypes.c_uint32
        require((ctypes.sizeof(_FileBasicInfo),ctypes.sizeof(_FileStandardInfo),ctypes.sizeof(_FileIdInfo))==(40,24,24),
                'Native metadata structure ABI differs')

    def checked(self,value,label):
        if not value:
            code=ctypes.get_last_error() if hasattr(ctypes,'get_last_error') else 0
            raise Rejected('Windows native '+label+' failed; errorCode='+str(code))
        return value

    def handle_snapshot(self,handle,path):
        require(type(handle)is int and 0<handle<2**(ctypes.sizeof(ctypes.c_void_p)*8)
                and handle!=ctypes.c_void_p(-1).value,'Native read handle invalid')
        require(self.kernel.GetFileType(handle)==1,'Native handle is not a disk file')
        basic=_FileBasicInfo();standard=_FileStandardInfo();ident=_FileIdInfo()
        for kind,record in((0,basic),(1,standard),(18,ident)):
            self.checked(self.kernel.GetFileInformationByHandleEx(handle,kind,ctypes.byref(record),ctypes.sizeof(record)),
                         'GetFileInformationByHandleEx/'+str(kind))
        buffer=ctypes.create_unicode_buffer(32768)
        length=self.checked(self.kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0),'GetFinalPathNameByHandleW')
        require(length<len(buffer),'Native final path exceeds bound')
        final=buffer.value
        require(final.startswith('\\\\?\\') and not final.startswith('\\\\?\\UNC\\'),'Native final path is not a local DOS path')
        require(ntpath.normcase(ntpath.normpath(final[4:]))==ntpath.normcase(ntpath.normpath(str(path))),
                'Native final path escaped the literal owned installation path')
        return _validate_native_identity({'volumeSerial':int(ident.VolumeSerialNumber),'fileId128':bytes(ident.FileId).hex(),
            'creation100ns':int(basic.CreationTime),'write100ns':int(basic.LastWriteTime),'change100ns':int(basic.ChangeTime),
            'attributes':int(basic.FileAttributes),'size':int(standard.EndOfFile),'links':int(standard.NumberOfLinks),
            'deletePending':bool(standard.DeletePending),'directory':bool(standard.Directory)})

    def path_snapshot(self,path):
        handle=self.kernel.CreateFileW(str(path),self.READ_ATTRIBUTES,self.SHARE_READ_WRITE_DELETE,None,
                                       self.OPEN_EXISTING,self.OPEN_REPARSE_POINT,None)
        self.checked(handle and handle!=ctypes.c_void_p(-1).value,'CreateFileW/readonly-attributes')
        try:return self.handle_snapshot(handle,path)
        finally:self.checked(self.kernel.CloseHandle(handle),'CloseHandle/owned-metadata-handle')

    def fd_snapshot(self,fd,path):
        return self.handle_snapshot(int(self.os_handle(fd)),path)


_WINDOWS_FILE_API=None


def _windows_file_api():
    # Cache API bindings only. Every path/handle metadata snapshot stays fresh.
    global _WINDOWS_FILE_API
    if _WINDOWS_FILE_API is None:_WINDOWS_FILE_API=_WindowsFileAPI()
    return _WINDOWS_FILE_API


def _require_same_native(before,after,message,relative,phase,python_before,python_after):
    _validate_native_identity(before);_validate_native_identity(after)
    if before!=after:
        fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_nlink','st_file_attributes')
        diagnostic={'phase':phase,'relativePath':safe_relative(relative)[:120],'api':'GetFileInformationByHandleEx',
                    'nativeBefore':before,'nativeAfter':after,'allNativeFieldsCompared':True,
                    'pythonBefore':{k:getattr(python_before,k,None)for k in fields},
                    'pythonAfter':{k:getattr(python_after,k,None)for k in fields}}
        text=json.dumps(diagnostic,separators=(',',':'),sort_keys=True)
        require(len(text)<=4096,'Native identity diagnostic exceeds bound')
        error=Rejected(message+'; nativeFileIdentity='+text);error.file_identity_diagnostic=diagnostic;raise error


def _read_windows_owned(path,relative,maximum,before,*,api=None):
    api=api if api is not None else _windows_file_api()
    native_before=_validate_native_identity(api.path_snapshot(path))
    require(native_before['size']==before.st_size and native_before['size']<=maximum,'Native source size/bound differs')
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
    with os.fdopen(os.open(path,flags),'rb')as stream:
        _require_same_native(native_before,api.fd_snapshot(stream.fileno(),path),'File changed while opening',relative,
                             'after-open-native-fd',before,os.fstat(stream.fileno()))
        data=stream.read(maximum+1);require(len(data)<=maximum,'File exceeds read bound')
        _require_same_native(native_before,api.fd_snapshot(stream.fileno(),path),'File changed during read',relative,
                             'after-read-native-fd',before,os.fstat(stream.fileno()))
        _require_same_native(native_before,api.path_snapshot(path),'File replaced during read',relative,
                             'after-read-native-path',before,_regular_unlinked(path))
        _require_same_native(native_before,api.fd_snapshot(stream.fileno(),path),'File changed after path read',relative,
                             'after-path-native-fd',before,os.fstat(stream.fileno()))
    after=_regular_unlinked(path)
    _require_same_native(native_before,api.path_snapshot(path),'File replaced after close',relative,
                         'after-close-native-path',before,after)
    return data,before


def _regular_unlinked(path):
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)
            and not (getattr(st, 'st_file_attributes', 0) & 0x400), 'Linked/nonregular file refused')
    require(st.st_nlink == 1, 'Hardlinked file refused')
    return st


def read_owned(root, relative, maximum):
    """Bounded regular-file read; caller already fenced the owned CI root."""
    safe_relative(relative)
    root = Path(root)
    for ancestor in [*reversed(root.parents), root, *(root.joinpath(*relative.split('/')).parents)]:
        if ancestor == root or root in ancestor.parents or ancestor in root.parents:
            st = ancestor.lstat()
            require(not stat.S_ISLNK(st.st_mode) and not (getattr(st, 'st_file_attributes', 0) & 0x400),
                    'Linked/reparse ancestry refused')
    path = root.joinpath(*relative.split('/'))
    before = _regular_unlinked(path)
    require(before.st_size <= maximum, 'File exceeds read bound')
    if os.name=='nt':return _read_windows_owned(path,relative,maximum,before)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        _require_same_file(before,os.fstat(stream.fileno()),'File changed while opening',relative,'after-open-fstat')
        data = stream.read(maximum + 1)
        require(len(data) <= maximum, 'File exceeds read bound')
        _require_same_file(before,os.fstat(stream.fileno()),'File changed during read',relative,'after-read-fstat')
    _require_same_file(before,_regular_unlinked(path),'File replaced during read',relative,'after-read-lstat')
    return data, before


def _summary(code):
    """Only the trusted compiler's CodeObjects are traversed; never cache objects."""
    result = []
    def visit(value, depth):
        require(depth <= 128, 'Trusted code nesting exceeds bound')
        require(type(value) is types.CodeType, 'Expected trusted code object')
        result.append({'depth': depth, 'bytecodeSha256': sha256(value.co_code),
                       'filenameSha256': sha256(value.co_filename.encode('utf-8')),
                       'marshalSha256': sha256(marshal.dumps(value, 4))})
        for constant in value.co_consts:
            if type(constant) is types.CodeType:
                visit(constant, depth + 1)
    visit(code, 0)
    return result


def verify_pyc(cache_relative, cache_bytes, source_bytes, signed_source, windows_root,
               source_mtime, runtime_optimize=0):
    identity = runtime_identity()
    source_relative = source_for_cache(cache_relative, runtime_optimize)
    require(set(signed_source) == {'bytes', 'sha256'} and type(signed_source['bytes']) is int
            and SHA.fullmatch(signed_source['sha256']) is not None, 'Invalid authenticated source identity')
    require(type(source_bytes) is bytes and len(source_bytes) <= MAX_SOURCE_BYTES
            and len(source_bytes) == signed_source['bytes'] and sha256(source_bytes) == signed_source['sha256'],
            'Source differs from authenticated managed file')
    require(type(cache_bytes) is bytes and 16 < len(cache_bytes) <= MAX_PYC_BYTES, 'Invalid cache size')
    require(cache_bytes[:4] == MAGIC, 'Cache magic differs')
    flags, = struct.unpack('<I', cache_bytes[4:8])
    require(flags in (0, 1, 3), 'Invalid PEP 552 flags')
    if flags == 0:
        require(type(source_mtime) is int and 0 <= source_mtime < 2**64, 'Actual source mtime required')
        require(struct.unpack('<II', cache_bytes[8:16]) == (source_mtime & 0xffffffff, len(source_bytes) & 0xffffffff),
                'Timestamp/size header differs from actual signed source')
        header_kind = 'timestamp'
    else:
        require(cache_bytes[8:16] == importlib.util.source_hash(source_bytes), 'PEP 552 signed-source hash differs')
        header_kind = 'checked-hash' if flags == 3 else 'source-hash-independently-checked'
    expected_filename = windows_filename(windows_root, source_relative)
    # compile() parses only the already authenticated source. No import/exec occurs.
    expected_code = compile(source_bytes, expected_filename, 'exec', dont_inherit=True, optimize=runtime_optimize)
    expected_payload = marshal.dumps(expected_code, 4)
    require(hmac.compare_digest(cache_bytes[16:], expected_payload), 'Cache code is not the exact trusted compiler output')
    return {'path': cache_relative, 'bytes': len(cache_bytes), 'sha256': sha256(cache_bytes),
            'source': {'path': source_relative, **signed_source}, 'header': header_kind,
            'actualOptimize': runtime_optimize, 'compiler': identity,
            'canonicalFilenameSha256': sha256(expected_filename.encode('utf-8')),
            'marshalPayloadSha256': sha256(expected_payload), 'recursiveTrustedCodeObjects': _summary(expected_code),
            'untrustedCacheDeserialized': False, 'cacheExecuted': False}


def capture_preimage(root, windows_root, relative=INI, phase='before-old-helper'):
    require(relative in (INI, CANARY), 'Only exact preferences/canary preimage allowed')
    require(phase in ('before-old-helper','before-first-start'), 'Invalid preimage phase')
    root_binding = sha256(windows_filename(windows_root, relative).encode('utf-8'))
    path = Path(root).joinpath(relative)
    result = {'path': relative, 'phase': phase, 'capturedAtNs': time.time_ns(),
              'canonicalFilenameSha256': root_binding}
    try:
        data, _ = read_owned(root, relative, 65536)
    except FileNotFoundError:
        result['present'] = False
    else:
        result.update(present=True, bytes=len(data), sha256=sha256(data))
    return result


def verify_preimage(root, windows_root, preimage, relative=INI, phase='before-old-helper'):
    require(type(preimage) is dict and preimage.get('path') == relative
            and preimage.get('phase') == phase and type(preimage.get('present')) is bool
            and type(preimage.get('capturedAtNs')) is int and preimage['capturedAtNs'] > 0,
            'Actual before-old-helper preference/canary snapshot required')
    expected_keys = {'path', 'phase', 'capturedAtNs', 'canonicalFilenameSha256', 'present'}
    require(set(preimage) == expected_keys | ({'bytes', 'sha256'} if preimage['present'] else set()), 'Preimage shape differs')
    require(preimage['canonicalFilenameSha256'] == sha256(windows_filename(windows_root, relative).encode('utf-8')),
            'Preference/canary snapshot belongs to another installation')
    try:
        data, _ = read_owned(root, relative, 65536)
    except FileNotFoundError:
        require(not preimage['present'], 'Preexisting preferences/canary missing after upgrade')
        return {'path': relative, 'present': False, 'unchanged': True}
    require(preimage['present'], 'New preference/canary file has no captured preimage')
    require(type(preimage['bytes']) is int and len(data) == preimage['bytes']
            and SHA.fullmatch(preimage['sha256']) is not None and sha256(data) == preimage['sha256'],
            'Preexisting preference/canary bytes changed')
    return {'path': relative, 'present': True, 'bytes': len(data), 'sha256': sha256(data), 'unchanged': True}


def pinned_update_inventory(archive):
    path = Path(archive)
    require(path.stat().st_size == UPDATE_ZIP_BYTES, 'Frozen update archive size differs')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    require(digest.hexdigest() == UPDATE_ZIP_SHA256, 'Frozen update archive SHA differs')
    result = {}
    with zipfile.ZipFile(path) as z:
        require(len(z.infolist()) == MANAGED_FILE_COUNT, 'Frozen managed file count differs')
        folded = set()
        for info in z.infolist():
            require(info.filename.startswith('KIO-Control-Windows/') and not info.is_dir(), 'Unexpected update ZIP member')
            relative = safe_relative(info.filename[len('KIO-Control-Windows/'):])
            require(relative.casefold() not in folded and not stat.S_ISLNK(info.external_attr >> 16), 'Duplicate/linked update member')
            folded.add(relative.casefold())
            digest = hashlib.sha256()
            with z.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            result[relative] = {'bytes': info.file_size, 'sha256': digest.hexdigest()}
    return result


def verify_installation(root, windows_root, signed_inventory, ini_before, *, runtime_optimize=0,
                        canary_before=None, fresh_factory=None):
    """All managed hashes stay mandatory; classify every additional regular file.

    signed_inventory must come from pinned_update_inventory or the caller's
    existing independently authenticated signed update archive. This is not an
    authenticator for arbitrary caller-provided maps. Full parent signature,
    old-helper, own-GUI, canary and signing-policy gates remain mandatory.
    """
    runtime_identity()
    root = Path(root)
    if os.name == 'nt':
        require(str(root.resolve()) == windows_root, 'Actual Windows installation root differs')
    require(len(signed_inventory) == MANAGED_FILE_COUNT, 'Original 3905 managed-file gate changed')
    require(INI not in signed_inventory and CANARY not in signed_inventory, 'Preferences unexpectedly became managed')
    folded = set()
    for relative, identity in signed_inventory.items():
        safe_relative(relative)
        require(relative.casefold() not in folded, 'Duplicate managed path')
        folded.add(relative.casefold())
        require(set(identity) == {'bytes', 'sha256'} and type(identity['bytes']) is int
                and 0 <= identity['bytes'] <= 1024**3 and SHA.fullmatch(identity['sha256']) is not None,
                'Invalid authenticated managed file')
    actual = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            p = Path(folder) / name
            st = p.lstat()
            require(not p.is_symlink() and not (getattr(st, 'st_file_attributes', 0) & 0x400), 'Linked directory refused')
        for name in files:
            relative = safe_relative((Path(folder) / name).relative_to(root).as_posix())
            require(relative.casefold() not in actual, 'Case-colliding actual path refused')
            actual[relative.casefold()] = relative
            require(len(actual) <= MANAGED_FILE_COUNT + MAX_EXTRA_FILES + 2, 'Actual tree exceeds file bound')
    require(all(actual.get(p.casefold()) == p for p in signed_inventory), 'Signed managed file missing/renamed')
    for relative, identity in signed_inventory.items():
        data, _ = read_owned(root, relative, identity['bytes'])
        require(len(data) == identity['bytes'] and sha256(data) == identity['sha256'], 'Signed managed bytes changed: ' + relative)
    extras = sorted(p for p in actual.values() if p not in signed_inventory)
    require(len(extras) <= MAX_EXTRA_FILES, 'Too many runtime products')
    preferences = verify_fresh_ini(root,windows_root,ini_before,fresh_factory) if fresh_factory is not None else verify_preimage(root, windows_root, ini_before)
    allowed_noncache = {INI}
    canary = None
    if canary_before is not None:
        canary = verify_preimage(root, windows_root, canary_before, CANARY, phase='before-first-start' if fresh_factory is not None else 'before-old-helper')
        allowed_noncache.add(CANARY)
    receipts = []
    for relative in extras:
        if relative in allowed_noncache:
            continue
        source_relative = source_for_cache(relative, runtime_optimize)
        require(source_relative in signed_inventory, 'Cache has no authenticated managed source')
        source, st = read_owned(root, source_relative, MAX_SOURCE_BYTES)
        cache, _ = read_owned(root, relative, MAX_PYC_BYTES)
        receipts.append(verify_pyc(relative, cache, source, signed_inventory[source_relative], windows_root,
                                   int(st.st_mtime), runtime_optimize))
    return {'managedFilesExact': len(signed_inventory), 'managedMissing': 0, 'managedChanged': 0,
            'runtimeCachesSourceVerified': len(receipts), 'runtimeProducts': receipts,
            'preferences': preferences, 'canary': canary, 'allAdditionalFilesClassified': True,
            'cacheImportedOrExecuted': False, 'signatureAndOsAcceptanceStillRequired': True}


def verify_fresh_ini(root,windows_root,preimage,factory):
    require(type(factory)is dict and factory.get('sourceCommit')==SOURCE_COMMIT
            and factory.get('sourceArchiveSha256')==SOURCE_ZIP_SHA256
            and factory.get('factorySourceSha256')==INI_FACTORY_SOURCE_SHA256
            and factory.get('rootAbsentBeforeFirstStart')is True,
            'Closed fresh-portable source factory proof required')
    require(type(preimage)is dict and set(preimage)=={'path','phase','capturedAtNs','canonicalFilenameSha256','present'}
            and preimage['path']==INI and preimage['phase']=='before-first-start'
            and preimage['present']is False and type(preimage['capturedAtNs'])is int and preimage['capturedAtNs']>0
            and preimage['canonicalFilenameSha256']==sha256(windows_filename(windows_root,INI).encode()),
            'Fresh factory requires actual absent-before-first-start INI preimage')
    try:data,_=read_owned(root,INI,65536)
    except FileNotFoundError:return {'path':INI,'present':False,'unchanged':True,'sourceFactoryUsed':False}
    require(data==INI_DEFAULT_BYTES and sha256(data)==INI_DEFAULT_SHA256,'Fresh-portable INI differs from exact approved source factory')
    return {'path':INI,'present':True,'beforePresent':False,'unchanged':False,'sourceFactoryUsed':True,
            'bytes':36,'sha256':INI_DEFAULT_SHA256,'factorySourceSha256':INI_FACTORY_SOURCE_SHA256}


def verified_fresh_factory(root,source_archive,executable,snapshot,inventory):
    require(snapshot['mode']=='fresh-portable' and snapshot['rootAbsentBeforeFirstStart']is True,
            'Fresh-portable root was not absent before first startup')
    archive=Path(source_archive)
    require(not archive.is_symlink() and archive.is_file() and archive.stat().st_size==SOURCE_ZIP_BYTES
            and sha256(archive.read_bytes())==SOURCE_ZIP_SHA256,'Exact r2 corresponding source archive required')
    with zipfile.ZipFile(archive)as z:
        require(len(z.namelist())==441 and z.namelist().count('windows/GalaxyControl.c')==1,'Exact r2 source members required')
        source=z.read('windows/GalaxyControl.c');manifest=json.loads(z.read('SOURCE-MANIFEST.json'))
        rows=[r for r in manifest['files']if r['path']=='windows/GalaxyControl.c']
        require(len(rows)==1 and rows[0]['sha256']==sha256(source)==INI_FACTORY_SOURCE_SHA256
                and rows[0]['bytes']==len(source),'Approved Windows preference factory source changed')
    exe=Path(executable);require(exe.resolve()==Path(root).resolve()/'KIOControl.exe','Fresh factory executable must be exact owned installed native path')
    expected=inventory.get('KIOControl.exe');require(expected is not None,'Authenticated native executable identity missing')
    data,_=read_owned(root,'KIOControl.exe',expected['bytes'])
    require(len(data)==expected['bytes'] and sha256(data)==expected['sha256'],'Actual native executable differs from signed candidate')
    return {'sourceCommit':SOURCE_COMMIT,'sourceArchiveSha256':SOURCE_ZIP_SHA256,
            'factorySourceSha256':INI_FACTORY_SOURCE_SHA256,'rootAbsentBeforeFirstStart':True,
            'nativeExecutableSha256':expected['sha256'],
            'actualSfxStartupPidPeHealthAndSignatureEvidenceRequiredFromParent':True}


def _json_file(path):
    p=Path(path);require(not p.is_symlink() and p.is_file() and p.stat().st_size<=1024*1024,'Bounded plain preimage JSON required')
    return json.loads(p.read_text(encoding='utf-8'))


def _write_output(path,value,installation):
    p=Path(path);require(p.is_absolute() and not p.exists() and not p.is_symlink(),'Fresh absolute output file required')
    require(not p.resolve().is_relative_to(Path(installation).resolve()),'Evidence output must be outside installation')
    require(p.parent.is_dir(),'Output parent must exist')
    for parent in [p.parent,*p.parent.parents]:
        st=parent.lstat();require(not stat.S_ISLNK(st.st_mode) and not(getattr(st,'st_file_attributes',0)&0x400),'Linked evidence parent refused')
    raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    with p.open('xb')as stream:stream.write(raw)


def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    for action in('capture','verify'):
        p=sub.add_parser(action);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
        p.add_argument('--fresh-portable',action='store_true')
        if action=='verify':
            p.add_argument('--archive',type=Path,required=True);p.add_argument('--preimage',type=Path,required=True)
            p.add_argument('--source',type=Path);p.add_argument('--exe',type=Path)
    args=parser.parse_args(argv)
    try:
        runtime_identity();root=args.root
        require(root.is_absolute() and str(root)==str(root.resolve()),'Canonical absolute owned installation root required')
        windows_root=str(root.resolve()) if os.name=='nt' else str(PureWindowsPath('D:/owned-fixture')/root.name)
        # POSIX operation is fixture-only. Actual acceptance must use Windows and its own-root/OS gates.
        mode='fresh-portable'if args.fresh_portable else'upgrade'
        if args.action=='capture':
            if args.fresh_portable:require(not root.exists() and not root.is_symlink(),'Fresh portable root must be absent before first normal startup')
            else:require(root.is_dir() and not root.is_symlink(),'Actual old installation root required')
            phase='before-first-start'if args.fresh_portable else'before-old-helper'
            result={'schemaVersion':1,'status':'captured','mode':mode,'rootAbsentBeforeFirstStart':args.fresh_portable,
                    'rootBindingSha256':sha256(windows_root.encode()),'ini':capture_preimage(root,windows_root,INI,phase),
                    'canary':capture_preimage(root,windows_root,CANARY,phase)}
        else:
            require((args.source is not None and args.exe is not None)if args.fresh_portable else(args.source is None and args.exe is None),
                    'Source/executable factory flags required only together in explicit fresh-portable mode')
            snapshot=_json_file(args.preimage)
            require(type(snapshot)is dict and set(snapshot)=={'schemaVersion','status','mode','rootAbsentBeforeFirstStart','rootBindingSha256','ini','canary'}
                    and snapshot['schemaVersion']==1 and snapshot['status']=='captured'and snapshot['mode']==mode
                    and snapshot['rootBindingSha256']==sha256(windows_root.encode()),'Actual matching-mode before-start/helper snapshot required')
            require(snapshot['rootAbsentBeforeFirstStart']is args.fresh_portable,'Fresh/upgrade preimage mode differs')
            inventory=pinned_update_inventory(args.archive)
            factory=verified_fresh_factory(root,args.source,args.exe,snapshot,inventory)if args.fresh_portable else None
            checks=verify_installation(root,windows_root,inventory,snapshot['ini'],canary_before=snapshot['canary'],fresh_factory=factory)
            result={'schemaVersion':1,'status':'passed','mode':mode,'checks':checks,'factory':factory,
                    'archiveSha256':UPDATE_ZIP_SHA256,'sourceCommit':SOURCE_COMMIT,'nativeOsExecutionPerformedByValidator':False}
        _write_output(args.output,result,root);print(json.dumps({'status':result['status'],'mode':mode}));return 0
    except Exception as error:
        message=str(error)[:400]if isinstance(error,Rejected)else'Filesystem/source validation failed'
        failure={'schemaVersion':1,'status':'failed','errorType':type(error).__name__,'message':message,
                 'nativeOsExecutionPerformedByValidator':False}
        if isinstance(error,Rejected) and hasattr(error,'file_identity_diagnostic'):
            failure['fileIdentityDiagnostic']=error.file_identity_diagnostic
        try:_write_output(args.output,failure,args.root)
        except Exception:pass
        print(json.dumps(failure));return 1


if __name__=='__main__':raise SystemExit(cli())
