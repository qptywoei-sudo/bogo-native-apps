"""Read-only verification of the actual MSI Binary streams used by Bitmap controls.

No installer session, action, UI, COM automation, script, or executable is started.
Only five reviewed custom-art applications have this palette contract.
"""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import zlib

import bogo_native as bogo

CUSTOM_APPS = frozenset(('launcher', 'photo', 'ui', 'vector', 'light'))
MAX_BITMAP_BYTES = 2 * 1024 * 1024
MAX_CONTROL_ROWS = 128
MAX_REFERENCE_CHARS = 128
CHUNK = 65536
HEADER = (255, 243, 232)
BACKGROUND = (255, 250, 246)
ACCENT = (252, 117, 1)
REFERENCE = re.compile(r'[A-Za-z_][A-Za-z0-9_.]{0,127}')


def require(condition, message):
    if not condition:
        raise ValueError('MSI artwork verification: ' + message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            require(not item.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400), 'link/reparse path refused')


def runner_scope():
    require(sys.platform == 'win32' and os.environ.get('RUNNER_OS') == 'Windows' and os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'actual MSI readback requires the disposable hosted Windows runner')
    require(os.environ.get('GITHUB_REPOSITORY') == 'qptywoei-sudo/bogo-native-apps' and os.environ.get('GITHUB_REF') == 'refs/heads/codex/bogo-native-rebrand-20261026', 'unexpected repository/ref')
    root = Path(os.environ.get('RUNNER_TEMP', ''))
    require(root.is_absolute() and root.is_dir(), 'missing absolute runner temporary directory')
    no_links(root)
    return root.resolve()


def validated_input(msi_path, app, runner):
    lock = bogo.load_lock(app)
    path = Path(msi_path)
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'MSI must be an existing absolute regular file')
    no_links(path)
    path = path.resolve()
    base = bogo.full.artifact_base(lock, 'windows-x64')
    require(path.name == base + '.msi', 'MSI basename is not the exact Bogo candidate')
    workspace = bogo.ROOT.resolve()
    require(Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve() == workspace, 'workspace identity differs')
    native_dist = workspace / 'dist' / (app + '-windows-x64')
    in_candidate = path.parent.name == 'candidate' and path.parent.is_relative_to(runner)
    require(path.parent == native_dist or in_candidate, 'MSI is outside the fixed native dist or authenticated runner candidate')
    for suffix in ('-manifest.json', '-provenance.json', '-SHA256SUMS.txt'):
        metadata = path.parent / (base + suffix)
        require(metadata.is_file() and not metadata.is_symlink() and metadata.stat().st_size <= 16 * 1024 * 1024, 'missing/bounded native provenance')
    bogo.full.verify(path.parent, lock, 'windows-x64')
    provenance = json.loads((path.parent / (base + '-provenance.json')).read_text(encoding='utf-8'))
    require(provenance.get('schema') == 1 and provenance.get('app') == app and provenance.get('version') == lock['version'] and provenance.get('platform') == 'windows-x64', 'native provenance app/version/platform differs')
    inputs = provenance.get('inputs', {})
    require(inputs.get('lock') == lock and inputs.get('sourceTreeSha256') == lock['bogoOverlay']['sourceTreeSha256'] and inputs.get('bogoOverlay') == {'path': lock['bogoOverlay']['patch'], 'sha256': lock['bogoOverlay']['patchSha256']}, 'MSI source tree/overlay/lock differs')
    actual_sha = bogo.digest(path)
    if in_candidate:
        receipt = path.parent.parent / 'authenticated-build.json'
        require(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_size <= 16 * 1024 * 1024, 'authenticated CI artifact receipt is missing')
        binding = json.loads(receipt.read_text(encoding='utf-8'))
        require(binding.get('schema') == 'bogo.windows-artifact-input.v1' and binding.get('repository') == 'qptywoei-sudo/bogo-native-apps' and binding.get('app') == app and binding.get('status') == 'verified' and binding.get('harnessSha') == os.environ.get('GITHUB_SHA'), 'candidate artifact receipt differs')
        require(binding.get('sourceTreeSha256') == lock['bogoOverlay']['sourceTreeSha256'] and binding.get('overlaySha256') == lock['bogoOverlay']['patchSha256'], 'candidate source binding differs')
        records = [row for row in binding.get('files', []) if row.get('filename') == path.name]
        require(len(records) == 1 and records[0].get('sha256') == actual_sha and records[0].get('bytes') == path.stat().st_size, 'candidate MSI hash/size differs from authenticated artifact')
    return path, lock, actual_sha


class _Database:
    """Only read-only MSI database/view/record APIs are bound."""
    def __init__(self, path, _api=None):
        if _api is None:
            require(sys.platform == 'win32', 'Windows MSI APIs are unavailable on this OS')
            _api = ctypes.WinDLL('msi', use_last_error=True)
        self.api = _api
        uint, dword = ctypes.c_uint32, ctypes.c_uint32
        signatures = {
            'MsiOpenDatabaseW': ([ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.POINTER(uint)], uint),
            'MsiDatabaseOpenViewW': ([uint, ctypes.c_wchar_p, ctypes.POINTER(uint)], uint),
            'MsiViewExecute': ([uint, uint], uint), 'MsiViewFetch': ([uint, ctypes.POINTER(uint)], uint),
            'MsiRecordGetStringW': ([uint, uint, ctypes.c_wchar_p, ctypes.POINTER(dword)], uint),
            'MsiRecordReadStream': ([uint, uint, ctypes.c_void_p, ctypes.POINTER(dword)], uint),
            'MsiViewClose': ([uint], uint), 'MsiCloseHandle': ([uint], uint),
        }
        for name, (args, result) in signatures.items():
            function = getattr(_api, name)
            function.argtypes, function.restype = args, result
        self.handle = uint()
        status = _api.MsiOpenDatabaseW(str(path), None, ctypes.byref(self.handle))
        if status != 0:
            if self.handle.value:
                _api.MsiCloseHandle(self.handle)
            raise ValueError('MSI artwork verification: read-only database open failed (' + str(status) + ')')
        self.allowed = set()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.handle.value:
            self.api.MsiCloseHandle(self.handle)
            self.handle.value = 0

    @contextmanager
    def view(self, query):
        handle = ctypes.c_uint32()
        status = self.api.MsiDatabaseOpenViewW(self.handle, query, ctypes.byref(handle))
        if status != 0:
            if handle.value:
                self.api.MsiCloseHandle(handle)
            require(False, 'read-only view failed')
        try:
            require(self.api.MsiViewExecute(handle, 0) == 0, 'read-only query failed')
            yield handle
        finally:
            self.api.MsiViewClose(handle)
            self.api.MsiCloseHandle(handle)

    def string(self, record, field):
        size = ctypes.c_uint32(0)
        status = self.api.MsiRecordGetStringW(record, field, None, ctypes.byref(size))
        require(status in (0, 234) and 0 < size.value <= MAX_REFERENCE_CHARS, 'Bitmap control string exceeds its bound')
        data = ctypes.create_unicode_buffer(size.value + 1)
        size = ctypes.c_uint32(len(data))
        require(self.api.MsiRecordGetStringW(record, field, data, ctypes.byref(size)) == 0 and size.value < len(data), 'Bitmap control string read failed')
        require(REFERENCE.fullmatch(data.value), 'Bitmap control/reference identifier is not static')
        return data.value

    def bitmap_controls(self):
        rows = []
        with self.view("SELECT `Dialog_`, `Control`, `Text` FROM `Control` WHERE `Type` = 'Bitmap'") as view:
            while True:
                record = ctypes.c_uint32()
                status = self.api.MsiViewFetch(view, ctypes.byref(record))
                if status == 259:
                    break
                if status != 0:
                    if record.value:
                        self.api.MsiCloseHandle(record)
                    require(False, 'Bitmap control fetch failed')
                require(record.value, 'Bitmap control handle is empty')
                try:
                    require(len(rows) < MAX_CONTROL_ROWS, 'too many Bitmap controls')
                    rows.append({'dialog': self.string(record, 1), 'control': self.string(record, 2), 'binary': self.string(record, 3)})
                finally:
                    self.api.MsiCloseHandle(record)
        self.allowed = {row['binary'] for row in rows}
        require(rows and len(self.allowed) == 2, 'exactly two Bitmap-referenced streams are required')
        require(len({(row['dialog'], row['control']) for row in rows}) == len(rows), 'duplicate Bitmap control binding')
        return rows

    def binary(self, name):
        require(name in self.allowed and REFERENCE.fullmatch(name), 'unreferenced/broad Binary stream request refused')
        with self.view("SELECT `Data` FROM `Binary` WHERE `Name` = '" + name + "'") as view:
            record = ctypes.c_uint32()
            status = self.api.MsiViewFetch(view, ctypes.byref(record))
            if status != 0 or not record.value:
                if record.value:
                    self.api.MsiCloseHandle(record)
                require(False, 'referenced Binary stream is missing')
            try:
                size = ctypes.c_uint32(0)
                require(self.api.MsiRecordReadStream(record, 1, None, ctypes.byref(size)) == 0 and 0 < size.value <= MAX_BITMAP_BYTES, 'referenced bitmap stream exceeds its bound')
                expected, chunks, total = size.value, [], 0
                while True:
                    buffer = ctypes.create_string_buffer(CHUNK)
                    count = ctypes.c_uint32(CHUNK)
                    require(self.api.MsiRecordReadStream(record, 1, buffer, ctypes.byref(count)) == 0 and count.value <= CHUNK, 'Binary stream read failed')
                    if not count.value:
                        break
                    total += count.value
                    require(total <= expected and total <= MAX_BITMAP_BYTES, 'Binary stream exceeded its declared bound')
                    chunks.append(buffer.raw[:count.value])
                require(total == expected, 'Binary stream was truncated')
                extra = ctypes.c_uint32()
                status = self.api.MsiViewFetch(view, ctypes.byref(extra))
                if extra.value:
                    self.api.MsiCloseHandle(extra)
                require(status == 259, 'duplicate Binary stream identity')
                return b''.join(chunks)
            finally:
                self.api.MsiCloseHandle(record)


def decode_bmp(data):
    require(isinstance(data, bytes) and 54 <= len(data) <= MAX_BITMAP_BYTES and data[:2] == b'BM', 'expected bounded original BMP bytes')
    size, reserved, offset = struct.unpack_from('<III', data, 2)
    header, width, signed_height, planes, bits, compression, image_size = struct.unpack_from('<IiiHHII', data, 14)
    height = abs(signed_height)
    require(size == len(data) and reserved == 0 and header in (40, 108, 124) and 14 + header <= offset <= 1024, 'BMP header/file bounds differ')
    require(width == 493 and height in (58, 312) and planes == 1 and bits == 24 and compression == 0, 'expected exact uncompressed 24-bit installer bitmap dimensions')
    stride = ((width * 3 + 3) // 4) * 4
    require(image_size in (0, stride * height) and offset + stride * height == len(data), 'BMP pixel range differs')
    rows = []
    for y in range(height):
        source_y = height - 1 - y if signed_height > 0 else y
        start = offset + source_y * stride
        row = bytearray(width * 3)
        for x in range(width):
            blue, green, red = data[start + x * 3:start + x * 3 + 3]
            row[x * 3:x * 3 + 3] = bytes((red, green, blue))
        rows.append(bytes(row))
    return width, height, rows


def expected_pixel(app, role, x, y):
    """Flat interiors only; approved icon/text boxes and antialiased edges are excluded."""
    if app == 'light':
        return HEADER if role == 'banner' or x < 164 else BACKGROUND
    height = 58 if role == 'banner' else 312
    if not (1 <= x < 492 and 1 <= y < height - 1):
        return None
    if role == 'banner':
        if app != 'launcher':
            return None if 437 <= x < 487 and 4 <= y < 54 else BACKGROUND
        if 429 <= x < 469 and 9 <= y < 49:
            return None
        if x < 403:
            return BACKGROUND
        if x == 406:
            return ACCENT
        return HEADER if x >= 409 else None
    if x >= 166:
        return BACKGROUND
    if app == 'launcher':
        if x == 163:
            return ACCENT
        if 14 <= x < 134 and 16 <= y < 302:
            return None
        return HEADER if x < 160 else None
    if x in (161, 162):
        return ACCENT
    if 16 <= x < 144 and 62 <= y < 190:
        return None
    return HEADER if x < 159 else None


def verify_palette(app, role, width, height, rows):
    counts, excluded = {}, 0
    for y in range(height):
        for x in range(width):
            expected = expected_pixel(app, role, x, y)
            if expected is None:
                excluded += 1
                continue
            actual = tuple(rows[y][x * 3:x * 3 + 3])
            require(actual == expected, app + ' ' + role + ' flat-pixel mismatch at ' + str(x) + ',' + str(y))
            colour = ''.join(f'{part:02X}' for part in expected)
            counts[colour] = counts.get(colour, 0) + 1
    require(sum(counts.values()) > 10000, 'insufficient checked flat backdrop area')
    return {'verifiedFlatPixels': sum(counts.values()), 'paletteCounts': counts, 'excludedIconTextAndEdgePixels': excluded}


def png_bytes(width, height, rows):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(b'\0' + row for row in rows))) + chunk(b'IEND', b'')


def verify_msi_art(msi_path, app_id, output_directory):
    require(app_id in bogo.NAMES, 'unknown application')
    if app_id not in CUSTOM_APPS:
        return {'schemaVersion': 1, 'app': app_id, 'status': 'not-applicable', 'reason': 'reviewed installer uses stock OS artwork; no custom pale-orange backdrop is claimed', 'actualBinaryStreamsRead': 0, 'installerActionsExecuted': False}
    runner = runner_scope()
    output = Path(output_directory)
    require(output.is_absolute(), 'readback output must be absolute')
    no_links(output)
    output = output.resolve()
    require(output.is_relative_to(runner) and output != runner and not output.exists(), 'readback output must be a fresh runner-owned directory')
    path, lock, before = validated_input(msi_path, app_id, runner)
    output.mkdir(parents=True, mode=0o700)
    report = {'schemaVersion': 1, 'app': app_id, 'status': 'checking', 'method': 'read-only-msi-database-bitmap-streams', 'msiSha256': before, 'version': lock['version'], 'sourceTreeSha256': lock['bogoOverlay']['sourceTreeSha256'], 'overlaySha256': lock['bogoOverlay']['patchSha256'], 'installerActionsExecuted': False, 'bitmaps': []}
    try:
        roles = set()
        with _Database(path) as database:
            controls = database.bitmap_controls()
            report['bitmapControls'] = controls
            for index, reference in enumerate(sorted({row['binary'] for row in controls}), 1):
                data = database.binary(reference)
                raw_name = 'msi-bitmap-' + str(index) + '.bmp'
                with (output / raw_name).open('xb') as saved:
                    saved.write(data)
                item = {'binary': reference, 'originalBmp': raw_name, 'sha256': digest(data), 'bytes': len(data)}
                report['bitmaps'].append(item)
                width, height, rows = decode_bmp(data)
                role = 'banner' if height == 58 else 'dialog'
                require(role not in roles, 'duplicate/missing actual banner or dialog Binary stream')
                roles.add(role)
                preview = png_bytes(width, height, rows)
                png_name = 'msi-' + role + '.png'
                with (output / png_name).open('xb') as saved:
                    saved.write(preview)
                item.update(role=role, width=width, height=height, png=png_name, pngSha256=digest(preview), pngBytes=len(preview))
                item.update(verify_palette(app_id, role, width, height, rows))
        require(roles == {'banner', 'dialog'} and bogo.digest(path) == before, 'MSI file changed or expected referenced artwork is incomplete')
        report.update(status='passed', actualBinaryStreamsRead=2, msiUnchanged=True)
    except Exception as error:
        message = str(error)
        report.update(status='failed', errorType=type(error).__name__, error=message if message.startswith('MSI artwork verification:') else type(error).__name__)
        raise
    finally:
        (output / 'msi-art.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
