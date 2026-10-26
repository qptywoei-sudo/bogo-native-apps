#!/usr/bin/env python3
"""Accept EXACT frozen Tools bytes on a fresh GitHub-hosted VM only.

No application rebuilding, HOME override, fake login, TCC alteration, DYLD hook,
production feed write, global process kill or compositor-image substitution.
The existing reviewed bogo_runtime_icons module supplies strict Windows HICON QA.
"""
from __future__ import annotations
import argparse, base64, ctypes, hashlib, io, json, os, platform, re, shutil
import stat, struct, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import uuid, zipfile
from pathlib import Path, PurePosixPath

VERSION = '4.6.23'
REPOSITORY = 'qptywoei-sudo/bogo-native-apps'
RELEASE_ID = 424585753
SOURCE_REPO = 'qptywoei-sudo/kio-tools-releases'
SOURCE_COMMIT = 'f328c97865951603f49dd06eb7960122e4035662'
MASTER_SHA = 'e3196a03cf3d259b5e3662c39206b36339b22986ac910b0e772fb84f7759957b'
ICO_SHA = '6fc46773734a521752d98e113d45ea9526ce475af5500efec32dab27ca19f72e'
ICNS_SHA = '83b8e147f108536a5e71745122dd6f57be3f2b52a2d59a57176228479dfe55cf'
EXE_SHA = {'windows': '4a73a4ae6052804e2bb14ffe1957c447bbedff92a24e6b11c1115cc7c7682ce5',
           'macos': '3719dff4c53deedb85db9e3c7691e856201f7b111c93fed1f7a24eac180a273a'}
EXE_BYTES = {'windows':1806336,'macos':3666928}
# The former e1afd... implementation checkpoint preceded final packaging and
# signing. Only the exact final executable members of the frozen ZIPs above
# are accepted here; historical/prepackaging hashes are never a fallback.
# Asset IDs, names, sizes and hashes were independently read back from this draft.
PINS = {
 'source': (678997933, 'Bogo-Tools-4.6.23-source.zip', 7431565, '4d632a284a12a41c2e3154058f7770658677380f945ccf796dddd4ae0729f8e2'),
 'windows': (678997931, 'Bogo-Tools-4.6.23-Windows-Portable.zip', 412298109, '8d893bb45045ae39d2f3ae5ae61c139d8ecbb0b60c4ce6cb67a3248654d146ab'),
 'macos': (678997927, 'Bogo-Tools-4.6.23-Mac-Portable.zip', 434306870, '3e61b3f23f816427a7b6b3ea82f001be4d23cdfd62b31ced54a02d53259e65c4'),
 'windows-update': (679005553, 'Bogo-Tools-4.6.23-Windows-Update.zip', 411750639, 'a5c1038c185e3d2da0c71f1e7a32fbe4c055934c0a9fba04f3bee3a32b74ad47'),
 'macos-update': (679005550, 'Bogo-Tools-4.6.23-Mac-Update.zip', 434610006, '3b5663edb6264c8778876f42df88e8c1f8ad0e2dbf312d4f1422327fc3083310'),
}
OLD_WINDOWS = ('https://github.com/qptywoei-sudo/kio-tools-releases/releases/download/tools-v4.6.21/KIO-Tools-4.6.21-Windows-Update.zip',
               414591430, 'c753337a986ef2abf4b1a38fbb99ff63ea4218f61e5ea009f3f7fc5dcc4f253b')
OLD_MACOS = ('https://github.com/qptywoei-sudo/kio-tools-releases/releases/download/tools-v4.6.21/KIO-Tools-4.6.21-Mac-Update.zip',
             437990335, 'c489d8ba1029155afcef587475fbb7336b8b40161fb1eb9a6b8664837f68884e')
# Root supplies a separately pinned QA-only envelope asset after local signing.
# Candidate URLs are held, not live; this harness never claims their availability.
ENVELOPE_PIN = (679016269, 'Bogo-Tools-4.6.23-candidate-update-envelope.json', 2374,
                'e7d424e0d6e5797b25f388a6322cf26f3e98d2bbc88cde53d474cc92520d4f48')
PUBLIC_KEY = 'JjeL9t/8GSrh2XZ25gawQyI475nXr/rU0li4CoEnfos='
MAC_SIGNER_LEAF_SHA1 = '72287f8a5048cd206db014ead6723c75cd459379'


def require(ok, message):
    if not ok: raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_json_utf8(path):
    # Source manifests and native/helper JSON are UTF-8 even when the Windows
    # host's default ANSI code page is CP1252/CP949. Accept a UTF-8 BOM as well.
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def executable_metadata(sha, size, target):
    expected_sha,expected_size=EXE_SHA[target],EXE_BYTES[target]
    require(sha==expected_sha and size==expected_size,
            f'Frozen executable mismatch: expected sha256={expected_sha} bytes={expected_size}; actual sha256={sha} bytes={size}')
    return {'sha256':sha,'bytes':size}


def verify_executable(path, target):
    path=Path(path);require(path.is_file() and not path.is_symlink(),'Executable is not a plain file')
    return executable_metadata(digest(path),path.stat().st_size,target)


def designated_requirement(returncode, stdout):
    # codesign -d -r- writes its requirement to stdout, while Executable= goes
    # to stderr. Match the actual stable source-policy requirement, not paths.
    require(returncode==0 and isinstance(stdout,str) and len(stdout)<=16384,'codesign requirement command failed or exceeded bound')
    lines=[line.strip() for line in stdout.splitlines() if line.strip().startswith('designated')]
    require(len(lines)==1,'Missing/ambiguous designated requirement stdout')
    match=re.fullmatch(r'designated\s*=>\s*identifier\s+"([^"\r\n]+)"\s+and\s+certificate\s+leaf\s*=\s*H"([a-fA-F0-9]{40})"',lines[0])
    require(match is not None and match.group(1)=='local.galaxycontrol.portable'
            and match.group(2).lower()==MAC_SIGNER_LEAF_SHA1,'Designated identifier or stable signing certificate differs')
    return {'identifier':match.group(1),'certificateLeafSha1':match.group(2).lower(),'sourceStream':'stdout'}


def macos_archive_executable_members(assets):
    """Bind the postpackaging pin to both exact frozen outer ZIPs before launch."""
    assets=Path(assets);rows=[]
    for key,member in [('macos','Bogo Tools.app/Contents/MacOS/KIOControl'),
                       ('macos-update','KIO-Control-Mac/Bogo Tools.app/Contents/MacOS/KIOControl')]:
        pin=PINS[key];archive=assets/pin[1]
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size==pin[2]
                and digest(archive)==pin[3],'Frozen Mac outer archive changed')
        with zipfile.ZipFile(archive) as z:
            require(z.namelist().count(member)==1,'Frozen Mac executable member is missing/duplicated')
            info=z.getinfo(member);require(not info.is_dir() and 0<info.file_size<=16*1024*1024,'Frozen Mac executable member exceeds bound')
            raw=z.read(info);metadata=executable_metadata(hashlib.sha256(raw).hexdigest(),len(raw),'macos')
        rows.append({'archive':pin[1],'archiveSha256':pin[3],'member':member,**metadata})
    require(rows[0]['sha256']==rows[1]['sha256'] and rows[0]['bytes']==rows[1]['bytes'],'Frozen Mac executable members differ')
    return {'bothFrozenOuterZipsVerified':True,'exactPostpackagingMembers':True,'members':rows}


def clean_environment(environment):
    # Keep the real fresh VM's ordinary HOME/user profile. Remove CI credentials.
    return {k: v for k, v in environment.items()
            if not (re.search(r'TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL|ACCESS_KEY|AUTH_SOCK', k, re.I)
                    or k.startswith(('GITHUB_', 'GH_', 'ACTIONS_', 'DYLD_', 'INPUT_', 'ENDPOINT_', 'VSTS_', 'AWS_', 'AZURE_')))}


def hosted_context(environment, system):
    require(environment.get('GITHUB_ACTIONS') == 'true', 'Refusing GUI: not GitHub Actions')
    require(environment.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'Refusing GUI: not a hosted ephemeral VM')
    require(environment.get('GITHUB_REPOSITORY') == REPOSITORY, 'Workflow must run in the draft asset repository')
    require(system in ('Windows', 'Darwin'), 'Only Windows/macOS hosted VMs are accepted')
    require(environment.get('RUNNER_OS') == ('Windows' if system == 'Windows' else 'macOS'), 'Runner OS identity mismatch')
    require(re.fullmatch(r'[0-9a-f]{40}', environment.get('GITHUB_SHA', '')) is not None, 'Missing workflow revision')
    temp = Path(environment.get('RUNNER_TEMP', ''))
    require(temp.is_absolute() and temp.is_dir() and not temp.is_symlink(), 'Invalid RUNNER_TEMP')
    return temp.resolve()


def owned_root(root, temp):
    root, temp = Path(root), Path(temp).resolve()
    require(root.is_absolute() and not root.is_symlink(), 'Evidence root must be absolute and plain')
    require(root.parent.resolve() == temp and root.name == 'bogo-tools-acceptance', 'Evidence root escaped RUNNER_TEMP')
    for p in [root, *root.parents]:
        require(not p.is_symlink(), 'Symlink in owned CI path')
        if p == temp: break
    return root


def require_phase(environment, expected):
    require(expected in ('fetch','gui') and environment.get('BOGO_ACCEPTANCE_PHASE')==expected,
            'Fetch-only and read-only GUI jobs must remain separate')


def workflow_identity(environment):
    run,attempt=environment.get('GITHUB_RUN_ID',''),environment.get('GITHUB_RUN_ATTEMPT','')
    require(re.fullmatch(r'[1-9][0-9]{0,19}',run) is not None and re.fullmatch(r'[1-9][0-9]{0,5}',attempt) is not None,
            'Missing same-workflow run/attempt identity')
    return {'workflowRunId':run,'workflowAttempt':attempt}


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urllib.parse.urlparse(newurl)
        require(url.scheme == 'https' and url.hostname in {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}, 'Unapproved asset redirect')
        request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if request is not None:
            request.remove_header('Authorization')
        return request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Loopback probe refused a redirect')


def safe_http_diagnostic(error, token=None):
    """Retain only bounded public GitHub JSON diagnostics, never headers/body dumps."""
    def safe(value):
        if not isinstance(value,str):return None
        if token:value=value.replace(token,'[redacted]')
        value=re.sub(r'(?i)Bearer\s+[^\s\"<>]+','Bearer [redacted]',value)
        return ''.join(c for c in value if c>=' ' or c=='\n')[:600]
    result={'status':int(error.code),'message':safe(str(error))}
    try:
        raw=error.read(8193);result['bodyTruncated']=len(raw)>8192
        if len(raw)<=8192:
            body=json.loads(raw)
            if isinstance(body,dict):
                message=safe(body.get('message'))
                if message:result['message']=message
                url=body.get('documentation_url');parsed=urllib.parse.urlparse(url) if isinstance(url,str) else None
                if parsed and parsed.scheme=='https' and parsed.hostname=='docs.github.com' and not parsed.username and not parsed.password:
                    result['documentationUrl']=urllib.parse.urlunparse((parsed.scheme,parsed.netloc,parsed.path,'','',''))
    except (OSError,ValueError,TypeError,AttributeError):pass
    finally:error.close()
    return result


def request_url(url, token=None, binary=False):
    parsed = urllib.parse.urlparse(url)
    require(parsed.scheme == 'https' and parsed.hostname in {'api.github.com', 'github.com'}, 'Unapproved initial URL')
    headers = {'User-Agent': 'bogo-tools-frozen-acceptance', 'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        allowed={f'/repos/{REPOSITORY}/releases/{RELEASE_ID}'}
        allowed.update(f'/repos/{REPOSITORY}/releases/assets/{pin[0]}' for pin in [*PINS.values(),ENVELOPE_PIN])
        require(parsed.hostname == 'api.github.com' and parsed.path in allowed and not parsed.query,
                'Credential cannot leave its exact frozen draft GET endpoints')
        headers['Authorization'] = 'Bearer ' + token
    try:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects()).open(urllib.request.Request(url, headers=headers,method='GET'), timeout=120)
    except urllib.error.HTTPError as error:
        error.bogo_diagnostic=safe_http_diagnostic(error,token)
        raise


def api(path, token=None):
    with request_url('https://api.github.com/' + path, token) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, 'API response bound exceeded')
    return json.loads(raw)


def validate_asset(asset, pin, release_id):
    ident, name, size, sha = pin
    require(asset.get('id') == ident and asset.get('name') == name and asset.get('size') == size, 'Draft asset identity/size mismatch: ' + name)
    require(asset.get('digest') == 'sha256:' + sha and asset.get('state') == 'uploaded', 'Draft API digest/state mismatch: ' + name)
    require(asset.get('url') == f'https://api.github.com/repos/{REPOSITORY}/releases/assets/{ident}', 'Draft asset API URL mismatch')
    return {'id': ident, 'name': name, 'bytes': size, 'sha256': sha, 'releaseId': release_id}


def download(url, destination, size, sha, token=None):
    destination = Path(destination)
    require(not destination.exists(), 'Download would overwrite a file')
    h, count = hashlib.sha256(), 0
    try:
        with request_url(url, token, binary=True) as response, destination.open('xb') as output:
            for chunk in iter(lambda: response.read(4 * 1024 * 1024), b''):
                count += len(chunk); require(count <= size, 'Downloaded file exceeds frozen size')
                h.update(chunk); output.write(chunk)
        require(count == size and h.hexdigest() == sha, 'Downloaded bytes/hash do not match frozen asset')
    except BaseException:
        destination.unlink(missing_ok=True); raise


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def source_binding(archive):
    commit = api(f'repos/{SOURCE_REPO}/git/commits/{SOURCE_COMMIT}')
    require(commit.get('sha') == SOURCE_COMMIT, 'Published source commit mismatch')
    tree = api(f'repos/{SOURCE_REPO}/git/trees/{commit["tree"]["sha"]}?recursive=1')
    require(tree.get('truncated') is False, 'Published source tree is truncated')
    blobs = {r['path']: r for r in tree['tree'] if r['type'] == 'blob'}
    require(len([p for p in blobs if p.startswith('source/')])==438,'Published source snapshot file count differs')
    with zipfile.ZipFile(archive) as z:
        require(len(z.infolist()) == 438, 'Frozen source entry count mismatch')
        for entry in z.infolist():
            row = blobs.get('source/' + entry.filename)
            require(row is not None and row.get('mode') in ('100644','100755') and row['sha'] == git_blob(z.read(entry)), 'Source ZIP differs from public source snapshot: ' + entry.filename)
    return {'repository': SOURCE_REPO, 'commit': SOURCE_COMMIT, 'byteExactFiles': 438}


def fetch(root, target):
    require_phase(os.environ,'fetch');identity=workflow_identity(os.environ)
    temp = hosted_context(os.environ, platform.system()); root = owned_root(root, temp)
    require(not root.exists(), 'CI evidence directory must be fresh')
    root.mkdir(mode=0o700); assets = root / 'assets'; assets.mkdir(); (root / 'output').mkdir()
    token = os.environ.pop('GH_TOKEN', None) or os.environ.pop('GITHUB_TOKEN', None)
    require(token is not None, 'Missing fetch-only own-repository ephemeral token for draft GETs')
    release = api(f'repos/{REPOSITORY}/releases/{RELEASE_ID}', token)
    require(release.get('id') == RELEASE_ID and release.get('draft') is True and release.get('prerelease') is True, 'Only the frozen private draft is eligible')
    rows = {a['id']: a for a in release['assets']}; got = {}
    keys = ('source', target, target + '-update', 'envelope')
    pins = dict(PINS)
    if ENVELOPE_PIN is not None: pins['envelope'] = ENVELOPE_PIN
    for key in keys:
        pin = pins[key]; row = rows.get(pin[0], {}); got[key] = validate_asset(row, pin, RELEASE_ID)
        download(row['url'], assets / pin[1], pin[2], pin[3], token)
    token = None
    got['sourceBinding'] = source_binding(assets / PINS['source'][1])
    url, size, sha = OLD_WINDOWS if target == 'windows' else OLD_MACOS
    download(url, assets / ('prior-' + target + '-update.zip'), size, sha)
    got['prior'] = {'bytes': size, 'sha256': sha, 'url': url, 'version': '4.6.21'}
    receipt={'repository': REPOSITORY, 'releaseId': RELEASE_ID, 'draft': True, 'platform': target,
        'workflowSha': os.environ['GITHUB_SHA'], 'assets': got, 'tokenPersisted': False,'fetchRole':'fetch-only',**identity}
    write_json(root/'receipt.json',receipt);write_json(root/'output/fetch-proof.json',receipt)


def member_path(name):
    require(isinstance(name, str) and name and '\\' not in name and '\0' not in name and not name.startswith('/'), 'Unsafe ZIP member')
    path = PurePosixPath(name)
    require(all(p not in ('', '.', '..') and ':' not in p for p in name.rstrip('/').split('/')), 'Unsafe ZIP path component')
    return path


def extract(archive, destination, expected_root=None):
    destination = Path(destination); require(not destination.is_symlink() and not destination.exists(), 'Extraction target is not fresh/plain')
    destination.mkdir(mode=0o700, parents=True); seen = set(); links = []
    with zipfile.ZipFile(archive) as z:
        require(len(z.infolist()) <= 60000, 'ZIP entry bound exceeded')
        total = 0
        link_keys = {str(member_path(i.filename)).casefold() for i in z.infolist() if stat.S_ISLNK(i.external_attr >> 16)}
        for info in z.infolist():
            p = member_path(info.filename); key = str(p).casefold()
            require(key not in seen, 'Duplicate ZIP member'); seen.add(key)
            require(not any(str(parent).casefold() in link_keys for parent in p.parents if str(parent) != '.'), 'ZIP entry below symlink')
            if expected_root: require(p.parts[0] == expected_root, 'Unexpected ZIP root')
            total += info.file_size; require(total <= 6 * 1024**3, 'Expanded ZIP bound exceeded')
            path = destination.joinpath(*p.parts); mode = info.external_attr >> 16
            if info.is_dir(): path.mkdir(parents=True, exist_ok=True); continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(mode):
                target = z.read(info).decode('utf-8')
                require(target and not Path(target).is_absolute() and '\\' not in target and '\0' not in target, 'Unsafe ZIP symlink')
                links.append((path, target)); continue
            for parent in path.parents:
                if parent==destination:break
                require(not parent.is_symlink(),'ZIP below symlink')
            else:raise ValueError('ZIP parent walk escaped extraction destination')
            with z.open(info) as source, path.open('xb') as output: shutil.copyfileobj(source, output)
            if mode: path.chmod(stat.S_IMODE(mode))
        for path, target in links:
            require((path.parent / target).resolve().is_relative_to(destination.resolve()), 'ZIP symlink escapes destination')
            require(not path.exists(), 'ZIP symlink collides'); path.symlink_to(target)
    return destination


def inventory(path):
    result = {}
    for p in Path(path).rglob('*'):
        if p.is_symlink(): result[str(p.relative_to(path))] = 'symlink:' + str(p.readlink())
        elif p.is_file(): result[str(p.relative_to(path))] = digest(p)
    return result


def tree_difference(expected, actual, expected_root, actual_root, limit=200):
    """Bounded code-only diagnostics. Never read or include profile/content data."""
    require(type(limit) is int and 1<=limit<=200,'Invalid tree diagnostic bound')
    def row(path, values, root, prefix):
        normalized=str(path).replace('\\','/');parts=member_path(normalized).parts
        file=Path(root).joinpath(*parts);value=values[path]
        sha=value if re.fullmatch(r'[0-9a-f]{64}',value) else hashlib.sha256(value.encode('utf-8')).hexdigest()
        size=file.lstat().st_size if file.exists() or file.is_symlink() else None
        return {'path':normalized,prefix+'Sha256':sha,prefix+'Bytes':size}
    missing=sorted(set(expected)-set(actual));added=sorted(set(actual)-set(expected))
    changed=[p for p in sorted(set(expected)&set(actual)) if expected[p]!=actual[p]]
    rows=[]
    for kind,paths in [('missing',missing),('added',added),('changed',changed)]:
        for path in paths:
            if len(rows)>=limit:break
            data={'kind':kind}
            if kind!='added':data.update(row(path,expected,expected_root,'expected'))
            if kind!='missing':data.update(row(path,actual,actual_root,'actual'))
            rows.append(data)
    def binding(values):return hashlib.sha256(json.dumps(sorted(values.items()),ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    return {'matches':expected==actual,'missingCount':len(missing),'addedCount':len(added),'changedCount':len(changed),
        'expectedFileCount':len(expected),'actualFileCount':len(actual),'expectedInventorySha256':binding(expected),
        'actualInventorySha256':binding(actual),'entryLimit':limit,'truncated':len(missing)+len(added)+len(changed)>len(rows),'differences':rows}


def pe_resources(path):
    data = Path(path).read_bytes(); u16 = lambda at: struct.unpack_from('<H', data, at)[0]; u32 = lambda at: struct.unpack_from('<I', data, at)[0]
    require(data[:2] == b'MZ', 'Not a PE file'); pe = u32(60); require(data[pe:pe+4] == b'PE\0\0', 'Not a PE signature')
    optional = pe + 24; directory = optional + (112 if u16(optional) == 0x20b else 96); rva, size = u32(directory+16), u32(directory+20)
    require(rva and size, 'PE resources absent'); sections = []
    for n in range(u16(pe+6)):
        at = optional + u16(pe+20) + n * 40; sections.append((u32(at+12), max(u32(at+8),u32(at+16)), u32(at+20)))
    def offset(value):
        for va, length, raw in sections:
            if va <= value < va + length: return raw + value - va
        raise ValueError('Resource RVA escaped sections')
    base, found = offset(rva), {}
    def visit(relative, names=()):
        require(relative + 16 <= size and len(names) <= 3, 'Invalid resource directory')
        at = base + relative
        for n in range(u16(at+12) + u16(at+14)):
            entry = at+16+n*8; ident, child = u32(entry), u32(entry+4)
            if ident & 0x80000000: continue
            if child & 0x80000000: visit(child & 0x7fffffff, (*names, ident))
            else:
                require(child + 16 <= size, 'Invalid resource descriptor'); desc = base+child; start, length = offset(u32(desc)),u32(desc+4)
                require(start+length <= len(data), 'Resource bytes escape PE'); found[(*names,ident)] = data[start:start+length]
    visit(0); return found


def embedded_icons(exe, ico):
    raw = Path(ico).read_bytes(); require(digest(ico) == ICO_SHA, 'Source ICO pin changed')
    reserved, kind, count = struct.unpack_from('<HHH',raw); require((reserved,kind,count) == (0,1,9), 'ICO geometry differs')
    chunks = {}
    for n in range(count):
        w,h,_,_,_,_,length,start = struct.unpack_from('<BBBBHHII',raw,6+16*n); chunks[w or 256] = raw[start:start+length]
    resources = pe_resources(exe); groups = [(k,v) for k,v in resources.items() if k[:2] == (14,1)]; require(len(groups)==1,'Ambiguous embedded ICO group')
    key, group = groups[0]; require(struct.unpack_from('<HHH',group)==(0,1,9),'Embedded ICO count changed')
    sizes=[]
    for n in range(9):
        w,h,_,_,_,bits,length,ident = struct.unpack_from('<BBBBHHIH',group,6+14*n); actual=resources[(3,ident,key[2])]
        require(bits==32 and length==len(actual) and actual==chunks[w or 256],'Actual PE icon differs from frozen ICO'); sizes.append(w or 256)
    return {'resourceGroup':1,'exactFrames':sorted(sizes),'icoSha256':ICO_SHA}


def portable_payload(launcher, output, expected_size, expected_sha):
    size = Path(launcher).stat().st_size; require(size>16,'Portable EXE too small')
    with Path(launcher).open('rb') as f:
        f.seek(-16,2); length,magic=struct.unpack('<Q8s',f.read(16));require(magic==b'KIOTOOLS' and 1000<=length<size-16,'Invalid portable trailer')
        require(length==expected_size,'Embedded update ZIP size changed');f.seek(size-16-length)
        with Path(output).open('xb') as target:
            remaining=length
            while remaining:
                chunk=f.read(min(4*1024*1024,remaining));require(chunk,'Truncated portable payload');target.write(chunk);remaining-=len(chunk)
    require(digest(output)==expected_sha,'Embedded portable payload hash changed')
    return {'bytes':length,'sha256':expected_sha}


def state_root(target):
    if target=='windows': return Path(os.environ['LOCALAPPDATA'])/'GalaxyControl/Agent'
    return Path.home()/'Library/Application Support/GalaxyControl/Agent'


def health(state, pid, version, timeout=120):
    deadline=time.monotonic()+timeout; last='waiting for own backend'
    while time.monotonic()<deadline:
        try:
            path=state/'desktop-session.json';require(path.is_file() and not path.is_symlink(),'Own session not ready')
            session=read_json_utf8(path);url=urllib.parse.urlparse(session.get('origin',''))
            require(url.scheme=='http' and url.hostname=='127.0.0.1' and url.port in (4323,4324,4325,4321) and not url.username and not url.password,'Own backend origin mismatch')
            require(session.get('version')==version and session.get('clientName')=='GalaxyControl' and session.get('ownerId')=='desktop','Own backend version/identity mismatch')
            token=session.get('token');require(isinstance(token,str) and re.fullmatch(r'[A-Za-z0-9_-]{32,256}',token),'Own backend token invalid')
            status_paths=[state/'bridge'/f'native-{pid}'/'status.json',state/'bridge/status.json']
            statuses=[read_json_utf8(p) for p in status_paths if p.is_file() and not p.is_symlink()]
            require(any(s.get('pid')==pid for s in statuses),'Native heartbeat is not from known PID')
            req=urllib.request.Request(session['origin']+'/health',headers={'Origin':session['origin'],'X-Local-Agent-Token':token})
            with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(req,timeout=2) as response: value=json.load(response)
            require(value.get('version')==version and value.get('nativeReady') is True,'Own backend/native bridge not ready')
            return {'version':version,'nativeReady':True,'origin':session['origin'],'knownNativePid':pid,'sessionTokenReported':False}
        except (OSError,ValueError,KeyError,json.JSONDecodeError) as error: last=type(error).__name__
        time.sleep(.3)
    raise RuntimeError('Own backend did not become ready: '+last)


def powershell(script, environment, timeout=45):
    exe=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    run=subprocess.run([str(exe),'-NoProfile','-NonInteractive','-Command',script],env=environment,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    require(run.returncode==0,'Owned Windows probe failed; code '+str(run.returncode))
    return json.loads(run.stdout.strip().lstrip('\ufeff'))


def windows_pid(executable, env, timeout=120):
    deadline=time.monotonic()+timeout; expected=str(Path(executable).resolve())
    while time.monotonic()<deadline:
        value=powershell("$p=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $env:BOGO_EXPECTED_EXE} | Select-Object ProcessId); @{'pids'=@($p|ForEach-Object{[int]$_.ProcessId})}|ConvertTo-Json -Compress",dict(env,BOGO_EXPECTED_EXE=expected))
        if len(value['pids'])==1:return int(value['pids'][0])
        require(len(value['pids'])<=1,'Multiple own exact-path native processes');time.sleep(.3)
    raise RuntimeError('Exact-path native Windows process did not start')


def windows_window(pid, env, timeout=120, title='Bogo Tools'):
    script=r'''Add-Type @'
using System;using System.Text;using System.Runtime.InteropServices;
public class W { public delegate bool F(IntPtr h,IntPtr p);[DllImport("user32.dll")]public static extern bool EnumWindows(F f,IntPtr p);[DllImport("user32.dll")]public static extern bool IsWindowVisible(IntPtr h);[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);[DllImport("user32.dll",CharSet=CharSet.Unicode)]public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);}
'@;$r=@();[W]::EnumWindows({param($h,$v);[uint32]$owner=0;[W]::GetWindowThreadProcessId($h,[ref]$owner)|Out-Null;if($owner -eq [int]$env:BOGO_PID -and [W]::IsWindowVisible($h)){$s=New-Object Text.StringBuilder 2048;[W]::GetWindowText($h,$s,2048)|Out-Null;$script:r+=@{'hwnd'=$h.ToInt64();'title'=$s.ToString();'pid'=$owner}};return $true},[IntPtr]::Zero)|Out-Null;@{'windows'=@($r)}|ConvertTo-Json -Compress -Depth 5'''
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=powershell(script,dict(env,BOGO_PID=str(pid)))
        own=[w for w in result['windows'] if title in w['title']]
        if own:return max(own,key=lambda w:len(w['title']))
        time.sleep(.5)
    raise RuntimeError('No visible own-PID '+title+' window within deadline')


WINDOWS_CAPTURE=r'''Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;using System.Runtime.InteropServices;
public class C { [StructLayout(LayoutKind.Sequential)] public struct R{public int L,T,Ri,B;} [DllImport("user32.dll")]public static extern bool GetClientRect(IntPtr h,out R r);[DllImport("user32.dll")]public static extern bool ClientToScreen(IntPtr h,ref System.Drawing.Point p);[DllImport("user32.dll")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);}
'@ -ReferencedAssemblies System.Drawing
$h=[IntPtr]([long]$env:BOGO_HWND);[uint32]$owner=0;[C]::GetWindowThreadProcessId($h,[ref]$owner)|Out-Null;if($owner -ne [int]$env:BOGO_PID){throw 'Own HWND changed'}
[C]::SetForegroundWindow($h)|Out-Null;Start-Sleep -Milliseconds 1000;if([C]::GetForegroundWindow() -ne $h){throw 'Own HWND is not foreground'}
$r=New-Object C+R;[C]::GetClientRect($h,[ref]$r)|Out-Null;$p=New-Object Drawing.Point 0,0;[C]::ClientToScreen($h,[ref]$p)|Out-Null;$w=$r.Ri-$r.L;$height=$r.B-$r.T;if($w -lt 100 -or $height -lt 100 -or $w -gt 10000 -or $height -gt 10000){throw 'Invalid own window size'}
$b=New-Object Drawing.Bitmap($w,$height);$g=[Drawing.Graphics]::FromImage($b);try{$g.CopyFromScreen($p.X,$p.Y,0,0,(New-Object Drawing.Size($w,$height)));$b.Save($env:BOGO_SCREENSHOT,[Drawing.Imaging.ImageFormat]::Png);$c=@{'FFF3E8'=0;'FFFAF6'=0;'FFE7D4'=0;'F1D3BD'=0;'342B26'=0};for($y=0;$y -lt $height;$y+=2){for($x=0;$x -lt $w;$x+=2){$v=$b.GetPixel($x,$y);$s='{0:X2}{1:X2}{2:X2}' -f $v.R,$v.G,$v.B;if($c.ContainsKey($s)){$c[$s]++}}};[C]::GetWindowThreadProcessId($h,[ref]$owner)|Out-Null;if($owner -ne [int]$env:BOGO_PID -or [C]::GetForegroundWindow() -ne $h){throw 'Own HWND changed during capture'};@{'width'=$w;'height'=$height;'paletteCounts'=$c;'ownPid'=$owner}|ConvertTo-Json -Compress}finally{$g.Dispose();$b.Dispose()}
'''


def windows_probe(executable, pid, source, output, env, label):
    window=windows_window(pid,env); ico=source/'windows/GalaxyControl.ico'; embedded=embedded_icons(executable,ico)
    from bogo_runtime_icons import check_runtime_icons
    icons=check_runtime_icons(int(window['hwnd']),pid,ico,ICO_SHA,output/(label+'-hicons'))
    capture=powershell(WINDOWS_CAPTURE,dict(env,BOGO_HWND=str(window['hwnd']),BOGO_PID=str(pid),BOGO_SCREENSHOT=str(output/(label+'.png'))))
    require((output/(label+'.png')).is_file(),'Own screenshot absent')
    require(capture['paletteCounts']['FFF3E8']>20 and capture['paletteCounts']['FFFAF6']>100,'Actual window does not show required pale Tools chrome')
    # Read OS version resources rather than assuming a filename is the product.
    version=powershell("$v=[Diagnostics.FileVersionInfo]::GetVersionInfo($env:BOGO_EXPECTED_EXE);@{product=$v.ProductName;version=$v.ProductVersion;description=$v.FileDescription}|ConvertTo-Json -Compress",dict(env,BOGO_EXPECTED_EXE=str(executable)))
    require(version['product']=='Bogo Tools' and version['version']==VERSION,'Actual PE product metadata mismatch')
    return {'pid':pid,'window':window,'embeddedIcons':embedded,'runtimeIconSources':icons,'screenshot':dict(capture,sha256=digest(output/(label+'.png'))),'osVersionResources':version,'visualReviewRequired':True}


def stop_windows(pid, executable, env):
    # Exact PID + exact full image path; never stop by global executable name.
    powershell("$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$env:BOGO_PID);if($p -and $p.ExecutablePath -eq $env:BOGO_EXPECTED_EXE){Stop-Process -Id ([int]$env:BOGO_PID) -ErrorAction Stop};@{stopped=$true}|ConvertTo-Json -Compress",dict(env,BOGO_PID=str(pid),BOGO_EXPECTED_EXE=str(executable)))
    # Native owns a KILL_ON_JOB_CLOSE backend job; closing this exact process
    # closes only its job. Never stop an ambient python/adb process by name.


def stop_windows_path(executable, env):
    value=powershell("$p=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $env:BOGO_EXPECTED_EXE});@{pids=@($p|ForEach-Object{[int]$_.ProcessId})}|ConvertTo-Json -Compress",dict(env,BOGO_EXPECTED_EXE=str(executable)))
    require(len(value['pids'])<=1,'Multiple exact-path applications during cleanup')
    for pid in value['pids']:stop_windows(pid,executable,env)


MAC_PROBE=r'''import AppKit
import CoreGraphics
import ScreenCaptureKit
import Foundation
@main struct Probe {
 static func save(_ image:NSImage,_ path:String)throws{var r=NSRect(x:0,y:0,width:1024,height:1024);guard let c=image.cgImage(forProposedRect:&r,context:nil,hints:nil),let d=NSBitmapImageRep(cgImage:c).representation(using:.png,properties:[:])else{throw NSError(domain:"BogoProbe",code:2)};try d.write(to:URL(fileURLWithPath:path))}
 static func main() async {
  let a=CommandLine.arguments;var result:[String:Any]=[:]
  do {guard a.count==5 else{throw NSError(domain:"BogoProbe",code:1)}
   let expected=URL(fileURLWithPath:a[2]).standardizedFileURL
   if a[4]=="find" {let apps=NSWorkspace.shared.runningApplications.filter{$0.bundleURL?.standardizedFileURL==expected && $0.bundleIdentifier=="local.galaxycontrol.portable" && !$0.isTerminated};guard apps.count<=1 else{throw NSError(domain:"BogoProbe",code:8)};result=["passed":true,"pids":apps.map{Int($0.processIdentifier)}];let d=try JSONSerialization.data(withJSONObject:result);FileHandle.standardOutput.write(d);return}
   guard let p=Int32(a[1]),p>0,let app=NSRunningApplication(processIdentifier:p),!app.isTerminated,let bundle=app.bundleURL,bundle.standardizedFileURL==expected,app.bundleIdentifier=="local.galaxycontrol.portable" else{throw NSError(domain:"BogoProbe",code:3)}
   if a[4]=="terminate" {result=["passed":app.terminate(),"pid":p];let d=try JSONSerialization.data(withJSONObject:result);FileHandle.standardOutput.write(d);return}
   guard a[4]=="capture",app.localizedName=="Bogo Tools" else{throw NSError(domain:"BogoProbe",code:9)}
   result=["pid":p,"localizedName":app.localizedName!,"bundleIdentifier":app.bundleIdentifier!,"bundlePath":bundle.path,"finderDisplayName":FileManager.default.displayName(atPath:bundle.path),"infoBundleDisplayName":Bundle(url:bundle)?.object(forInfoDictionaryKey:"CFBundleDisplayName") as? String ?? "","screenCapturePermission":CGPreflightScreenCaptureAccess()]
   let out=URL(fileURLWithPath:a[3]);guard let icon=app.icon else{throw NSError(domain:"BogoProbe",code:4)};try save(icon,out.appendingPathComponent("mac-running-icon.png").path);try save(NSWorkspace.shared.icon(forFile:bundle.path),out.appendingPathComponent("mac-finder-icon.png").path)
   app.activate(options:[.activateAllWindows]);try await Task.sleep(nanoseconds:1_000_000_000)
   let content=try await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:true)
   let windows=content.windows.filter{$0.owningApplication?.processID==p && $0.frame.width>=300 && $0.frame.height>=200};guard let w=windows.max(by:{$0.frame.width*$0.frame.height < $1.frame.width*$1.frame.height})else{throw NSError(domain:"BogoProbe",code:5)}
   result["windowId"]=w.windowID;result["windowTitle"]=w.title ?? "";result["windowWidth"]=w.frame.width;result["windowHeight"]=w.frame.height
   let cfg=SCStreamConfiguration();cfg.width=Int(w.frame.width);cfg.height=Int(w.frame.height);cfg.showsCursor=false
   let image=try await SCScreenshotManager.captureImage(contentFilter:SCContentFilter(desktopIndependentWindow:w),configuration:cfg)
   guard !app.isTerminated,NSRunningApplication(processIdentifier:p)?.bundleURL?.standardizedFileURL==expected else{throw NSError(domain:"BogoProbe",code:6)}
   let bitmap=NSBitmapImageRep(cgImage:image);guard let data=bitmap.representation(using:.png,properties:[:])else{throw NSError(domain:"BogoProbe",code:7)};try data.write(to:out.appendingPathComponent("mac-window.png"))
   var counts=["FFF3E8":0,"FFFAF6":0,"FFE7D4":0,"F1D3BD":0,"342B26":0]
   for y in stride(from:0,to:bitmap.pixelsHigh,by:2){for x in stride(from:0,to:bitmap.pixelsWide,by:2){if let c=bitmap.colorAt(x:x,y:y)?.usingColorSpace(.deviceRGB){let key=String(format:"%02X%02X%02X",Int((c.redComponent*255).rounded()),Int((c.greenComponent*255).rounded()),Int((c.blueComponent*255).rounded()));if counts[key] != nil{counts[key]! += 1}}}}
   result["paletteCounts"]=counts;result["capturedOwnWindow"]=true;result["passed"]=true
  }catch{result["passed"]=false;let e=error as NSError;result["errorDomain"]=e.domain;result["errorCode"]=e.code;result["error"]=e.localizedDescription}
  let d=try! JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]);FileHandle.standardOutput.write(d)
 }
}
'''


def mac_observer(work, output, env):
    helper=work/'mac-own-window.swift';helper.write_text(MAC_PROBE,encoding='utf-8');binary=work/'mac-own-window'
    run=subprocess.run(['swiftc','-parse-as-library',str(helper),'-framework','AppKit','-framework','ScreenCaptureKit','-o',str(binary)],capture_output=True,text=True,env=env,timeout=120)
    (output/'mac-observer-build.log').write_text(run.stdout+run.stderr,encoding='utf-8')
    require(run.returncode==0,'Mac observer compiler failed; see mac-observer-build.log')
    return binary


def mac_pid(app, observer, env, timeout=60):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        run=subprocess.run([str(observer),'0',str(app),'unused','find'],capture_output=True,text=True,env=env,timeout=15)
        require(run.returncode==0,'Mac process lookup failed');value=json.loads(run.stdout)
        require(value.get('passed') is True,'Mac process lookup identity failed')
        if len(value['pids'])==1:return int(value['pids'][0])
        time.sleep(.3)
    raise RuntimeError('Exact-bundle Mac application did not start')


def stop_mac(app, observer, env):
    run=subprocess.run([str(observer),'0',str(app),'unused','find'],capture_output=True,text=True,env=env,timeout=15)
    require(run.returncode==0,'Mac cleanup lookup failed');value=json.loads(run.stdout)
    require(value.get('passed') is True,'Mac cleanup bundle identity failed')
    for pid in value['pids']:
        stopped=subprocess.run([str(observer),str(pid),str(app),'unused','terminate'],capture_output=True,text=True,env=env,timeout=15)
        require(stopped.returncode==0 and json.loads(stopped.stdout).get('passed') is True,'Exact-bundle normal Mac termination failed')
        for _ in range(60):
            check=subprocess.run([str(observer),'0',str(app),'unused','find'],capture_output=True,text=True,env=env,timeout=15)
            require(check.returncode==0,'Owned Mac exit lookup failed');current=json.loads(check.stdout)
            require(current.get('passed') is True,'Owned Mac exit identity failed')
            if pid not in current['pids']:break
            time.sleep(.25)
        else:raise RuntimeError('Owned Mac application did not terminate')


def mac_bundle_metadata(app, output, env, label):
    import plistlib
    meta=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    observed={key:meta.get(key) for key in ['CFBundleName','CFBundleDisplayName','CFBundleIdentifier','CFBundleShortVersionString','CFBundleVersion','CFBundleIconFile','CFBundleExecutable']}
    write_json(output/(label+'-bundle-info.json'),observed)
    require(meta.get('CFBundleName')==meta.get('CFBundleDisplayName')=='Bogo Tools' and meta.get('CFBundleIdentifier')=='local.galaxycontrol.portable' and meta.get('CFBundleShortVersionString')==VERSION,'Actual bundle metadata mismatch')
    executable=verify_executable(app/'Contents/MacOS/KIOControl','macos')
    require(digest(app/'Contents/Resources/KIOTools.icns')==ICNS_SHA,'Actual Mac ICNS differs')
    strict=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],capture_output=True,text=True,env=env)
    signature=subprocess.run(['/usr/bin/codesign','-d','-r-',str(app)],capture_output=True,text=True,env=env)
    write_json(output/(label+'-codesign.json'),{'strictVerifyReturnCode':strict.returncode,'strictVerifyStdout':strict.stdout[:16384],
        'strictVerifyStderr':strict.stderr[:16384],'requirementReturnCode':signature.returncode,'requirementStdout':signature.stdout[:16384],'requirementStderr':signature.stderr[:16384]})
    require(strict.returncode==0,'Actual codesign --verify --deep --strict failed')
    requirement=designated_requirement(signature.returncode,signature.stdout)
    return {'bundleInfo':observed,'executable':executable,'icnsSha256':ICNS_SHA,'strictSignatureVerified':True,'designatedRequirement':requirement}


def mac_probe(app, source, work, output, env, observer, *, launched_pid=None, label='mac'):
    metadata=mac_bundle_metadata(app,output,env,label)
    # A pure preexisting self-check supplements, never replaces, normal GUI launch.
    pure=subprocess.run([str(app/'Contents/MacOS/KIOControl'),'--self-check'],capture_output=True,env=env,timeout=45)
    require(pure.returncode==0,'Frozen Mac pure self-check failed')
    process=None;pid=launched_pid
    try:
        if pid is None:
            with (work/(label+'-private-process.log')).open('wb') as log:
                process=subprocess.Popen([str(app/'Contents/MacOS/KIOControl')],stdout=log,stderr=subprocess.STDOUT,env=env)
            pid=process.pid
        backend=health(state_root('macos'),pid,VERSION);write_json(output/(label+'-backend.json'),backend)
        capture_dir=output/label;capture_dir.mkdir()
        observed=subprocess.run([str(observer),str(pid),str(app),str(capture_dir),'capture'],capture_output=True,text=True,env=env,timeout=45)
        require(observed.returncode==0,'Mac own-PID observer failed')
        result=json.loads(observed.stdout);write_json(capture_dir/'own-window.json',result)
        require(result.get('passed') is True,'Actual Mac screen capture unavailable: '+str(result.get('errorDomain'))+':'+str(result.get('errorCode')))
        require('Bogo Tools' in result.get('finderDisplayName','') and result.get('infoBundleDisplayName')=='Bogo Tools','Actual OS Finder/Info display name still differs: '+str(result.get('finderDisplayName')))
        require('Bogo Tools' in result.get('windowTitle',''),'Own actual Mac title is not Bogo Tools')
        require(result['paletteCounts']['FFF3E8']>20 and result['paletteCounts']['FFFAF6']>100,'Actual Mac window lacks pale Tools chrome')
        result.update(backend=backend,signatureVerified=True,bundleMetadata=metadata,pureSelfCheckSupplement=True,iconSourceComparison='OS NSRunningApplication/NSWorkspace PNGs retained for visual review; not claimed exact if OS representation differs',visualReviewRequired=True)
        return result
    finally:
        stop_mac(app,observer,env)
        if process is not None:process.wait(timeout=10)


def prepare_old_helper(prior, work, source, target):
    engine=prior/'tools/engine' if target=='windows' else prior/'Contents/Resources/tools/engine'
    arch='win64' if target=='windows' else 'x86_64'
    runtime=prior/'tools/python' if target=='windows' else prior/'Contents/Resources/tools/python/x86_64'
    helper=engine/'agent/update_helper.py'
    require(helper.is_file() and runtime.is_dir(),'Actual old updater/runtime missing')
    old_config=read_json_utf8(engine/'agent/update-channel.json')
    require(old_config.get('publicKey')==PUBLIC_KEY and read_json_utf8(source/'agent/update-channel.json').get('publicKey')==PUBLIC_KEY,'Old/new original public signing identities differ')
    detached=work/('old-'+target+'-updater');detached.mkdir();shutil.copytree(runtime,detached/'python',symlinks=True)
    for name in ('update_helper.py','update_security.py'):shutil.copy2(helper.with_name(name),detached/name)
    deps=detached/'deps';deps.mkdir()
    for pattern in ('cryptography','_cffi_backend*','cffi'):
        for p in (engine/'deps-agent'/arch).glob(pattern):
            if p.is_dir():shutil.copytree(p,deps/p.name)
            else:shutil.copy2(p,deps/p.name)
    return detached,{'originalHelperSha256':digest(helper),'originalVerifierSha256':digest(helper.with_name('update_security.py')),'originalPublicKey':PUBLIC_KEY,'helperAndRuntimeCopiedFromActualPriorRelease':True}


def run_old_helper(detached, prior, target, assets, state, output, env):
    envelope=read_json_utf8(assets/ENVELOPE_PIN[1])
    receipt=state/'updates'/'ci-receipt.json';receipt.parent.mkdir(exist_ok=True)
    plan={'archive':str(assets/PINS[target+'-update'][1]),'target':str(prior),'platform':'Windows' if target=='windows' else 'Mac','version':VERSION,'pids':[],'receipt':str(receipt),'publicKey':PUBLIC_KEY,'envelope':envelope}
    plan_file=detached/'plan.json';write_json(plan_file,plan)
    python=detached/('python/python.exe' if target=='windows' else 'python/bin/python3')
    result=subprocess.run([str(python),'-I','-B','-X','utf8',str(detached/'update_helper.py'),str(plan_file)],cwd=detached,env=env,capture_output=True,timeout=240)
    require(receipt.is_file(),'Actual old signed updater did not emit its receipt')
    value=read_json_utf8(receipt);write_json(output/(target+'-upgrade-receipt.json'),value)
    require(result.returncode==0 and value.get('phase')=='complete' and value.get('reopened') is True,'Actual signed old-to-new update failed: '+str(value.get('error'))+' at '+str(value.get('failedStage')))
    return value


def windows_upgrade(assets, work, source, output, env):
    prior=extract(assets/'prior-windows-update.zip',work/'prior','KIO-Control-Windows')/'KIO-Control-Windows'
    require((prior/'KIOControl.exe').is_file(),'Prior actual program missing')
    old_sha=digest(prior/'KIOControl.exe'); old_pid=None
    try:
        with (work/'old-private-process.log').open('wb') as log:old_process=subprocess.Popen([str(prior/'KIOControl.exe')],env=env,stdout=log,stderr=subprocess.STDOUT)
        old_pid=old_process.pid;windows_window(old_pid,env,title='KIO Tools');old_health=health(state_root('windows'),old_pid,'4.6.21')
    finally:
        if old_pid:stop_windows(old_pid,prior/'KIOControl.exe',env);old_process.wait(timeout=10)
    state=state_root('windows'); canary=state/'bogo-ci-profile-canary.txt'; user=prior/'bogo-ci-user-document.txt'; nonce='CI-only-'+str(uuid.uuid4())
    canary.write_text(nonce,encoding='utf-8');user.write_text(nonce,encoding='utf-8');require(digest(prior/'KIOControl.exe')==old_sha,'Old executable changed before upgrade')
    detached,provenance=prepare_old_helper(prior,work,source,'windows')
    try:
        run_old_helper(detached,prior,'windows',assets,state,output,env)
        require(canary.read_text(encoding='utf-8')==user.read_text(encoding='utf-8')==nonce,'Profile/user document canary changed')
        verify_executable(prior/'KIOControl.exe','windows')
        installed=inventory(prior);installed.pop('bogo-ci-user-document.txt',None)
        reference=work/'independent-update/KIO-Control-Windows';expected=inventory(reference)
        difference=tree_difference(expected,installed,reference,prior)
        write_json(output/'windows-upgrade-tree-difference.json',difference)
        require(installed==expected,'Actual upgraded Windows managed tree differs from frozen update; see windows-upgrade-tree-difference.json')
        pid=windows_pid(prior/'KIOControl.exe',env)
        current=health(state,pid,VERSION);gui=windows_probe(prior/'KIOControl.exe',pid,source,output,env,'windows-upgraded')
    finally:stop_windows_path(prior/'KIOControl.exe',env)
    return {'fromVersion':'4.6.21','toVersion':VERSION,'oldBackend':old_health,'newBackend':current,'normalOldSignatureGateUsed':True,'canariesPreserved':True,'installedManagedFileTreeExact':True,'actualNewExecutableSha256':EXE_SHA['windows'],'gui':gui,**provenance}


def mac_upgrade(assets, work, source, output, env, observer):
    import plistlib
    root=extract(assets/'prior-macos-update.zip',work/'prior','KIO-Control-Mac')/'KIO-Control-Mac'
    prior=root/'KIO Tools.app'
    info=plistlib.loads((prior/'Contents/Info.plist').read_bytes())
    require(info.get('CFBundleIdentifier')=='local.galaxycontrol.portable' and info.get('CFBundleShortVersionString')=='4.6.21','Actual prior Mac identity differs')
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(prior)],check=True,capture_output=True,env=env)
    old_process=None
    try:
        with (work/'old-private-process.log').open('wb') as log:old_process=subprocess.Popen([str(prior/'Contents/MacOS/KIOControl')],env=env,stdout=log,stderr=subprocess.STDOUT)
        old_health=health(state_root('macos'),old_process.pid,'4.6.21')
    finally:
        stop_mac(prior,observer,env)
        if old_process is not None:old_process.wait(timeout=10)
    state=state_root('macos');canary=state/'bogo-ci-profile-canary.txt';user=root/'bogo-ci-user-document.txt';nonce='CI-only-'+str(uuid.uuid4())
    canary.write_text(nonce,encoding='utf-8');user.write_text(nonce,encoding='utf-8')
    detached,provenance=prepare_old_helper(prior,work,source,'macos')
    try:
        run_old_helper(detached,prior,'macos',assets,state,output,env)
        require(canary.read_text(encoding='utf-8')==user.read_text(encoding='utf-8')==nonce,'Mac profile/user document canary changed')
        verify_executable(prior/'Contents/MacOS/KIOControl','macos')
        require(inventory(prior)==inventory(work/'update/KIO-Control-Mac/Bogo Tools.app'),'Actual upgraded Mac app tree differs from frozen update')
        pid=mac_pid(prior,observer,env)
        gui=mac_probe(prior,source,work,output,env,observer,launched_pid=pid,label='mac-upgraded')
    finally:stop_mac(prior,observer,env)
    return {'fromVersion':'4.6.21','toVersion':VERSION,'oldBackend':old_health,'normalOldSignatureGateUsed':True,'canariesPreserved':True,'installedFileTreeExact':True,'actualNewExecutableSha256':EXE_SHA['macos'],'gui':gui,**provenance}


def validate_receipt(receipt, target, environment):
    expected_keys={'repository','releaseId','draft','platform','workflowSha','assets','tokenPersisted','fetchRole','workflowRunId','workflowAttempt'}
    require(isinstance(receipt,dict) and set(receipt)==expected_keys,'Fetch receipt schema differs')
    require(receipt['repository']==REPOSITORY and receipt['releaseId']==RELEASE_ID and receipt['platform']==target
            and receipt['draft'] is True and receipt['tokenPersisted'] is False and receipt['fetchRole']=='fetch-only','Fetch receipt identity mismatch')
    require(receipt['workflowSha']==environment.get('GITHUB_SHA'),'Fetch/GUI workflow source differs')
    identity=workflow_identity(environment)
    require(all(receipt[k]==v for k,v in identity.items()),'Fetch/GUI workflow run or attempt differs')
    pins={'source':PINS['source'],target:PINS[target],target+'-update':PINS[target+'-update'],'envelope':ENVELOPE_PIN}
    expected={key:{'id':p[0],'name':p[1],'bytes':p[2],'sha256':p[3],'releaseId':RELEASE_ID} for key,p in pins.items()}
    expected['sourceBinding']={'repository':SOURCE_REPO,'commit':SOURCE_COMMIT,'byteExactFiles':438}
    url,size,sha=OLD_WINDOWS if target=='windows' else OLD_MACOS
    expected['prior']={'bytes':size,'sha256':sha,'url':url,'version':'4.6.21'}
    require(receipt['assets']==expected,'Transferred input pins/source binding differ from frozen receipt')
    return [p[1] for p in pins.values()]+['prior-'+target+'-update.zip']


def transferred_inputs(root, target, environment):
    root=Path(root)
    require(root.is_dir() and not root.is_symlink() and {p.name for p in root.iterdir()}=={'assets','receipt.json','output'},'Transferred input root is not fresh/limited')
    for name in ('assets','output'):
        require((root/name).is_dir() and not (root/name).is_symlink(),'Transferred directory is not plain')
    path=root/'receipt.json';require(path.is_file() and not path.is_symlink() and path.stat().st_size<=1024*1024,'Transferred receipt is not plain/bounded')
    receipt=read_json_utf8(path)
    names=validate_receipt(receipt,target,environment)
    require({p.name for p in (root/'assets').iterdir()}==set(names),'Transferred asset set differs')
    require(all((root/'assets'/name).is_file() and not (root/'assets'/name).is_symlink() for name in names),'Transferred asset is not a plain file')
    proof=root/'output/fetch-proof.json'
    require({p.name for p in (root/'output').iterdir()}=={'fetch-proof.json'} and proof.is_file() and not proof.is_symlink() and proof.stat().st_size<=1024*1024,'Transferred evidence contains unexpected files')
    require(read_json_utf8(proof)==receipt,'Transferred fetch proof/receipt differ')
    return receipt


def accept(root, target):
    require_phase(os.environ,'gui')
    temp=hosted_context(os.environ,platform.system());root=owned_root(root,temp)
    receipt=transferred_inputs(root,target,os.environ)
    assets=root/'assets';output=root/'output';work=root/'work';work.mkdir(mode=0o700)
    for pin in (PINS['source'],PINS[target],PINS[target+'-update'],ENVELOPE_PIN):
        require((assets/pin[1]).stat().st_size==pin[2] and digest(assets/pin[1])==pin[3],'Frozen downloaded artifact changed')
    prior_pin=OLD_WINDOWS if target=='windows' else OLD_MACOS
    prior_archive=assets/('prior-'+target+'-update.zip')
    require(prior_archive.stat().st_size==prior_pin[1] and digest(prior_archive)==prior_pin[2],'Actual prior release changed after fetch')
    source=extract(assets/PINS['source'][1],work/'source');require(digest(source/'desktop-ui/src/assets/bogo-tools-icon.png')==MASTER_SHA,'Frozen original artwork changed')
    manifest=read_json_utf8(source/'SOURCE-MANIFEST.json')
    for row in manifest['files']:
        p=source.joinpath(*member_path(row['path']).parts);require(p.is_file() and p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],'Corresponding-source manifest mismatch')
    require(not state_root(target).exists(),'Refusing GUI: application profile already exists on this VM')
    # Neither caller credentials nor injected library hooks may reach applications.
    environment=clean_environment(os.environ)
    for key in list(os.environ):
        if key not in environment:os.environ.pop(key,None)
    report={'status':'running','version':VERSION,'platform':target,'repository':REPOSITORY,'draftReleaseId':RELEASE_ID,'workflowSha':receipt['workflowSha'],'sourceGitBinding':receipt['assets']['sourceBinding'],'normalFrozenApplication':True,'homeOverridden':False,'credentialsStrippedBeforeProcess':True,'checks':{},'limitations':['OS icon-source images are not screenshots of existing user Dock/taskbar pins.','Captured palette pixels require human visual review and do not prove every UI state.','The signed update uses the actual prior helper with a predownloaded candidate package; future public candidate URLs are not live or tested.','No publisher certificate/notarization policy is added by this test.']}
    try:
        if target=='macos':
            report['checks']['postpackagingExecutableMembers']=macos_archive_executable_members(assets)
            portable=extract(assets/PINS[target][1],work/'portable','Bogo Tools.app')/'Bogo Tools.app'
            update=extract(assets/PINS[target+'-update'][1],work/'update','KIO-Control-Mac')/'KIO-Control-Mac/Bogo Tools.app'
            require(inventory(portable)==inventory(update),'Portable/update Mac app file trees differ')
            report['checks']['portableUpdateSourceBinding']={'identicalAppFileTree':True,'sourceArchiveSha256':PINS['source'][3],'executableSha256':EXE_SHA['macos']}
            observer=mac_observer(work,output,environment)
            report['checks']['oldToNewUpgrade']=mac_upgrade(assets,work,source,output,environment,observer)
            report['checks']['actualGui']=mac_probe(portable,source,work,output,environment,observer,label='mac-portable')
        else:
            portable=extract(assets/PINS[target][1],work/'portable','Bogo Tools.exe')/'Bogo Tools.exe'
            embedded_icons(portable,source/'windows/GalaxyControl.ico')
            embedded=portable_payload(portable,work/'embedded-update.zip',PINS['windows-update'][2],PINS['windows-update'][3])
            require(digest(work/'embedded-update.zip')==digest(assets/PINS['windows-update'][1]),'Portable payload and independently downloaded update differ')
            update=extract(assets/PINS['windows-update'][1],work/'independent-update','KIO-Control-Windows')/'KIO-Control-Windows'
            verify_executable(update/'KIOControl.exe','windows')
            report['checks']['portableUpdateSourceBinding']=dict(embedded,sourceArchiveSha256=PINS['source'][3],independentUpdateExact=True)
            # Genuine 4.6.21 -> signed 4.6.23 update first, on the fresh OS profile.
            report['checks']['oldToNewUpgrade']=windows_upgrade(assets,work,source,output,environment)
            cached=Path(os.environ['LOCALAPPDATA'])/'KIO Tools'/VERSION/'KIO-Control-Windows/KIOControl.exe';require(not cached.parent.exists(),'Portable cache must be fresh')
            pid=None
            try:
                with (work/'portable-private-process.log').open('wb') as log:subprocess.Popen([str(portable)],env=environment,stdout=log,stderr=subprocess.STDOUT)
                pid=windows_pid(cached,environment)
                verify_executable(cached,'windows')
                expected,actual=inventory(update),inventory(cached.parent)
                write_json(output/'windows-portable-tree-difference.json',tree_difference(expected,actual,update,cached.parent))
                require(actual==expected,'Actual SFX-extracted file tree differs from independently downloaded frozen update; see windows-portable-tree-difference.json')
                report['checks']['portableUpdateSourceBinding']['actualSfxExtractedFileTreeExact']=True
                report['checks']['portableBackend']=health(state_root(target),pid,VERSION)
                report['checks']['portableGui']=windows_probe(cached,pid,source,output,environment,'windows-portable')
            finally:
                stop_windows_path(cached,environment)
        report['status']='passed'
    except BaseException as error:
        report['status']='failed';report['failure']={'type':type(error).__name__,'message':str(error)[:600]};raise
    finally:
        # Upload only this explicit evidence directory, never sessions/profiles/assets.
        write_json(output/'report.json',report)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['fetch','accept']);parser.add_argument('--platform',choices=['windows','macos'],required=True);parser.add_argument('--root',required=True);args=parser.parse_args()
    require((platform.system()=='Windows')==(args.platform=='windows'),'Platform dispatch mismatch')
    try:(fetch if args.command=='fetch' else accept)(Path(args.root),args.platform)
    except BaseException as error:
        # Keep only explicit public diagnostics, never private process/session logs.
        temp=Path(os.environ.get('RUNNER_TEMP',''))
        if temp.is_absolute() and temp.is_dir():
            root=owned_root(Path(args.root),temp)
            if (root/'output').is_dir():
                diagnostic={'status':'failed','command':args.command,'platform':args.platform,'type':type(error).__name__,'message':str(error)[:600]}
                if isinstance(error,urllib.error.HTTPError) and hasattr(error,'bogo_diagnostic'):diagnostic['http']=error.bogo_diagnostic
                write_json(root/'output/terminal-error.json',diagnostic)
        raise

if __name__=='__main__':main()
