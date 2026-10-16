#!/usr/bin/env python3
"""Build the complete pinned Craft native applications; no Electron runtime or implicit publishing."""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import zipfile
import uuid
from xml.sax.saxutils import quoteattr
from pathlib import Path

import kio_native as common
import audit_windows_identity
import audit_rust_branding

ROOT = Path(__file__).resolve().parents[1]
IDS = ('photo', 'vector', 'film', 'light', 'pdf', 'effect', 'design', 'ui', 'word', 'sound', 'deck', 'cad', 'grid')
require, digest, run, write_json = common.require, common.digest, common.run, common.write_json
CATALOG = ROOT / 'manifests/full-native-apps.json'


def load_lock(app):
    require(app in IDS, 'Unknown native application')
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    require(catalog['schema'] == 1 and len(catalog['applications']) == len(IDS), 'Invalid native catalog')
    rows = [x for x in catalog['applications'] if x['id'] == app]
    require(len(rows) == 1, 'Duplicate/missing application lock')
    lock = rows[0]
    require(lock['rust'] == '1.95.0' and lock['name'].startswith('KIO ') and lock['bundleId'] == 'com.kio.' + app, 'Invalid app identity')
    require(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-kio\.[1-9][0-9]*', lock['version']), 'Invalid release version')
    require(lock['assetPrefix'] == lock['name'].replace(' ', '-'), 'Invalid asset name')
    expected_names = {'app': lock['name'] if app in ('grid', 'ui', 'sound') else lock['binaries']['app'], 'cli': 'SoundCraft CLI' if app == 'sound' else lock['binaries']['cli']}
    require(lock['versionOutputNames'] == expected_names and lock['windowsGuiVersionCheck'] == ('pe-resource' if app == 'film' else 'stdout'), 'Unexpected original version command contract')
    require(lock['features']['preserveDefaults'] is True and '--no-default-features' not in lock['cargoArgs'], 'Original full default features must remain enabled')
    require(lock['cargoArgs'][:3] == ['build', '--release', '--locked'], 'Full locked release build is required')
    upstream = lock['binaries']['app']
    require(upstream == ('figcraft' if app == 'ui' else app + 'craft'), 'Unexpected upstream application')
    require(lock['cargoPackages'] == [upstream, upstream + '-cli'] and lock['binaries']['cli'] == upstream + '-cli', 'Both the complete native GUI and CLI are required')
    expected = ['build', '--release', '--locked', '-p', upstream, '-p', upstream + '-cli']
    additions = lock['features']['officialNativeAdditionalFeatures']
    if additions:
        expected += ['--features', ','.join(additions)]
    require(lock['cargoArgs'] == expected, 'Native build differs from the official full-app feature selection')
    for key in ('source', 'fonts'):
        entry = lock[key]
        if entry is None:
            require(key == 'fonts' and app in ('effect', 'sound'), 'Required pinned fonts are missing')
            continue
        repository = 'storytold/' + upstream if key == 'source' else 'storytold/craft-fonts'
        require(entry['repository'] == repository and re.fullmatch(r'[a-f0-9]{40}', entry['commit']), 'Invalid immutable upstream')
        require(entry['url'] == 'https://codeload.github.com/' + repository + '/tar.gz/' + entry['commit'], 'Source URL is not the fixed upstream commit')
        require(entry['root'] == repository.split('/')[1] + '-' + entry['commit'] and common.HEX.fullmatch(entry['sha256']) and 0 < entry['bytes'] <= 128 * 1024 * 1024, 'Invalid archive integrity lock')
    branding = lock['branding']
    for key, sha_key in (('patch', 'sha256'), ('manifest', 'manifestSha256')):
        relative = common.check_public_path(branding[key])
        require(str(relative).startswith('patches/' + app + '/'), 'Branding file outside app allowlist')
        p = ROOT / relative
        require(p.is_file() and not p.is_symlink() and digest(p) == branding[sha_key], 'Locked branding bytes changed')
    meta = json.loads((ROOT / branding['manifest']).read_text(encoding='utf-8'))
    require(meta['schema'] == 'kio.native-branding-patch.v1' and meta['programId'] == app and meta['upstream']['commit'] == lock['source']['commit'], 'Patch metadata does not match original source')
    require(meta['patch']['sha256'] == branding['sha256'] and (ROOT / branding['patch']).stat().st_size == meta['patch']['bytes'], 'Patch hash/size mismatch')
    functional_fixes(lock)
    return lock


def vector_functional_paths(meta):
    """Keep the complete published crate; permit only the reviewed token reader fix."""
    dependency = meta['dependency']
    inventory = dependency['originalInventory']
    encoded = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    require(dependency['name'] == 'hayro-syntax' and dependency['version'] == '0.8.0' and
            dependency['archiveUrl'] == 'https://static.crates.io/crates/hayro-syntax/hayro-syntax-0.8.0.crate' and
            dependency['archiveSha256'] == '6cdc818d8d265dcb42081d488f7599df4f73fb79e9d347ecedcd3c23809d2026' and
            dependency['archiveBytes'] == 114123, 'Vector parser original crate pin changed')
    require(dependency['originalInventorySha256'] == hashlib.sha256(encoded).hexdigest() ==
            'c54c281427542e5f74afca4c96141f33ea7ef16f98ead161fe4ff1d4431d78fb' and
            len(inventory) == 59 and sum(row['bytes'] for row in inventory.values()) == 519602,
            'Vector complete original parser inventory changed')
    allowed = {'Cargo.toml', 'Cargo.lock', 'crates/pdf/tests/hayro_number_tokens.rs'}
    for name in inventory:
        common.check_public_path(name)
        allowed.add('vendor/hayro-syntax/' + name)
    require({row['path'] for row in meta['files']} == allowed and len(meta['files']) == 62,
            'Vector parser fix must retain every original crate file and only its reviewed integration')
    for row in meta['files']:
        if row['path'].startswith('vendor/hayro-syntax/'):
            name = row['path'][len('vendor/hayro-syntax/'):]
            require(row['before'] is None, 'Vector vendored original unexpectedly replaced existing app source')
            if name != 'src/object/number.rs':
                require(row['after'] == inventory[name], 'Vector changed an unreviewed original parser file')
    return allowed


def photo_fixture_functional_paths(meta):
    """Keep every original SVG assertion; separate its pinned icon input from branding."""
    expected = {
        'crates/io/src/svg.rs': ({'bytes': 38059, 'sha256': '1c6bb8d35da7aaf6f36ee37cb2fb681d105a92a7dc988551726451b3c47ff03a'},
                                 {'bytes': 38073, 'sha256': '8e1935f10b8ade3cacde4f817832ed3ea1f369cc175f0aae7c937910d000c952'}),
        'crates/io/tests/fixtures/upstream-photocraft-single-clip.svg':
            (None, {'bytes': 768636, 'sha256': 'a48333b7b794b70158da93a262d84fb82f5fbbf7442db60f235a0a69136a1ce2'}),
    }
    require(meta['upstream']['commit'] == 'c699e3cda69f4852b43c0b191ab0091aaeff9d6a'
            and len(meta['files']) == 2 and {row['path'] for row in meta['files']} == set(expected),
            'Photo test fixture correction requires the exact two reviewed paths')
    for row in meta['files']:
        require((row['before'], row['after']) == expected[row['path']],
                'Photo test fixture correction changed original input or production Rust bytes')
    return set(expected)


def functional_fixes(lock):
    result = []
    for fix in lock.get('functionalFixes', []):
        require(lock['id'] in ('word', 'effect', 'sound', 'design', 'vector', 'photo'), 'Functional fixes require an explicit application review')
        for key, sha_key in (('patch', 'sha256'), ('manifest', 'manifestSha256')):
            relative = common.check_public_path(fix[key])
            require(str(relative).startswith('patches/' + lock['id'] + '/functional-'), 'Functional fix outside its reviewed path')
            path = ROOT / relative
            require(path.is_file() and not path.is_symlink() and digest(path) == fix[sha_key], 'Functional fix bytes changed')
        meta = json.loads((ROOT / fix['manifest']).read_text(encoding='utf-8'))
        require(meta['schema'] == 'kio.native-functional-patch.v1' and meta['programId'] == lock['id'] and meta['upstream']['commit'] == lock['source']['commit'], 'Functional fix source identity mismatch')
        require(meta['base']['brandingPatchSha256'] == lock['branding']['sha256'], 'Functional fix branding base mismatch')
        require(meta['patch']['sha256'] == fix['sha256'] and meta['patch']['bytes'] == (ROOT / fix['patch']).stat().st_size, 'Functional fix patch mismatch')
        allowed = {'word': {'crates/engine/src/io.rs', 'crates/engine/src/cmd/file.rs', 'crates/engine/tests/wordml2003_save.rs'},
                   'effect': {'crates/engine/src/' + name for name in ('tests_frame_export.rs', 'tests_m137.rs', 'tests_essential.rs', 'tests_import_project.rs', 'commands/relink_moved.rs', 'footage_check.rs')},
                   'sound': {'crates/engine/src/file_access.rs'},
                   'design': {'Cargo.lock', 'crates/engine/Cargo.toml', 'crates/engine/src/recovery.rs',
                              'crates/engine/src/cmd/book/safety_tests.rs', 'crates/engine/tests/save_state_atomicity.rs'},
                   'vector': set(), 'photo': set()}[lock['id']]
        if lock['id'] == 'vector':
            allowed = vector_functional_paths(meta)
        if lock['id'] == 'photo':
            allowed = photo_fixture_functional_paths(meta)
        require(meta['files'] and {x['path'] for x in meta['files']} <= allowed, 'Functional fix changed an unreviewed engine or legal file')
        result.append((fix, meta))
    return result


def apply_functional_fixes(lock, source):
    for fix, meta in functional_fixes(lock):
        before = {r: digest(p) for r, p in source_files(lock, source)}
        for item in meta['files']:
            value = item['before']
            require((value is None and item['path'] not in before) or (value is not None and before.get(item['path']) == value['sha256']), 'Functional fix base changed')
        run(['git', 'apply', '--check', '--binary', ROOT / fix['patch']], cwd=source)
        run(['git', 'apply', '--binary', ROOT / fix['patch']], cwd=source)
        after = {r: digest(p) for r, p in source_files(lock, source)}
        require({r for r in before.keys() | after.keys() if before.get(r) != after.get(r)} == {x['path'] for x in meta['files']}, 'Functional fix changed files outside its exact scope')
        for item in meta['files']:
            value = item['after']
            require((value is None and item['path'] not in after) or (value is not None and after.get(item['path']) == value['sha256']), 'Functional fix output changed')


def source_validator(lock):
    exceptions = lock.get('originalArchivePathExceptions', [])
    require(not exceptions or lock['id'] in ('film', 'pdf'), 'Unreviewed source path exceptions')
    allowed = set()
    for item in exceptions:
        path = common.safe_relative(item['path'])
        fixture = (lock['id'] == 'film' and str(path).startswith('crates/h264enc/target/agent-h264enc/fixtures/h264enc/oracle/') and path.suffix == '.h264') or (lock['id'] == 'pdf' and str(path).startswith('crates/sign/tests/data/') and path.suffix == '.p12')
        require(fixture and common.HEX.fullmatch(item['sha256']) and 0 < item['bytes'] < 2 * 1024 * 1024, 'Invalid exact public upstream test fixture exception')
        allowed.update(str(p) for p in (path, *path.parents) if str(p) != '.')
    def validate(relative):
        if relative in allowed:
            return common.safe_relative(relative)
        return common.check_public_path(relative)
    return validate


def source_files(lock, source):
    files = common.regular_files(source, public=True, public_validator=source_validator(lock))
    lookup = dict(files)
    for item in lock.get('originalArchivePathExceptions', []):
        p = lookup.get(item['path'])
        require(p is not None and p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], 'Public upstream test fixture hash/bytes changed')
    return files


def source_fingerprint(lock, source):
    h = hashlib.sha256()
    for relative, p in source_files(lock, source):
        h.update(relative.encode('utf-8') + b'\0' + digest(p).encode('ascii') + b'\n')
    return h.hexdigest()


def paths(lock):
    work = ROOT / '.work/full-native' / lock['id']
    require(not work.is_symlink() and not work.parent.is_symlink(), 'Work symlink refused')
    return work, work / 'source', work / 'craft-fonts'


def light_format_contract(source):
    """Every literal tr_format call must exist in all pinned Light catalogs."""
    catalogs = [json.loads(p.read_text(encoding='utf-8')) for p in source.rglob('*-formats.json')]
    require(len(catalogs) == 9, 'Expected nine original Light format catalogs')
    keys = set(catalogs[0])
    require(all(set(catalog) == keys for catalog in catalogs), 'Light format catalog key sets diverged')
    calls = []
    for path in source.rglob('*.rs'):
        text = path.read_text(encoding='utf-8')
        # Preserve normal/raw string contents while removing Rust comments.
        tokens = re.compile(r'r(#+)?".*?"\1|"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
        text = tokens.sub(lambda m: '' if m[0].startswith(('//', '/*')) else m[0], text)
        for match in re.finditer(r'\btr_format\s*!\s*[({\[]\s*("(?:\\.|[^"\\])*")', text, re.S):
            key = json.loads(match[1].replace('\n', '\\n').replace('\r', '\\r'))
            require(key in keys, 'Light literal format has no catalog key: ' + str(path.relative_to(source)) + ': ' + key)
            calls.append(key)
    require(calls, 'No original Light format calls were inspected')
    return {'catalogs': len(catalogs), 'keys': len(keys), 'literalCalls': len(calls)}


def prepare(args, lock):
    work, source, fonts = paths(lock)
    if work.exists():
        require(args.reset, 'Prepared source exists; explicit --reset is required')
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for key, dest in (('source', source), ('fonts', fonts)):
        if lock[key] is not None:
            archive = common.verified_archive(lock[key], args.archive_cache or ROOT / '.cache/archives', args.offline)
            common.safe_extract(archive, dest, lock[key]['root'], public_validator=source_validator(lock) if key == 'source' else None)
    original = {r: digest(p) for r, p in source_files(lock, source)}
    protected = {r: sha for r, sha in original.items() if Path(r).name in ('Cargo.toml', 'Cargo.lock', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE', 'LICENSE-brand.txt')}
    run(['git', 'init', '--quiet'], cwd=source)
    run(['git', 'config', 'core.autocrlf', 'false'], cwd=source)
    patch = ROOT / lock['branding']['patch']
    run(['git', 'apply', '--check', '--binary', patch], cwd=source)
    run(['git', 'apply', '--binary', patch], cwd=source)
    for r, sha in protected.items():
        require((source / r).is_file() and digest(source / r) == sha, 'Branding changed protected original Cargo/license material: ' + r)
    after = {r: digest(p) for r, p in source_files(lock, source)}
    changed = {r for r in original.keys() | after.keys() if original.get(r) != after.get(r)}
    meta = json.loads((ROOT / lock['branding']['manifest']).read_text(encoding='utf-8'))
    require(changed == {x['path'] for x in meta['files']}, 'Applied source differs from the reviewed complete patch scope')
    for item in meta['files']:
        for side, actual in (('before', original), ('after', after)):
            declared = item[side]
            require((declared is None and item['path'] not in actual) or (declared is not None and actual.get(item['path']) == declared['sha256']), 'Patch roundtrip hash mismatch')
    for r, sha in meta.get('protectedFileHashes', {}).items():
        require(after.get(r) == sha, 'Original protected engine bytes changed: ' + r)
    for item in meta.get('protectedFiles', []):
        require(after.get(item['path']) == item['sha256'], 'Original protected source bytes changed: ' + item['path'])
    if lock['id'] == 'light':
        light_format_contract(source)
    # Compare actual WiX XML to the hash-locked upstream before permitting any
    # native build/source package. KIO must coexist with the original app.
    windows_identity = audit_windows_identity.audit(lock, source, archive_cache=args.archive_cache)
    # Functional corrections are separate, hash-locked, narrow patches, applied only
    # after the original branding-only source and protected engine check succeeded.
    apply_functional_fixes(lock, source)
    rust_audit = audit_rust_branding.audit_source(source)
    require(rust_audit['rustFiles'] > 0 and not rust_audit['findings'], 'KIO display name corrupted executable Rust source')
    record = {'schema': 1, 'app': lock['id'], 'catalogSha256': digest(CATALOG), 'lock': lock,
              'sourceTreeSha256': source_fingerprint(lock, source), 'fontsTreeSha256': common.tree_fingerprint(fonts) if fonts.exists() else None,
              'windowsInstallerIdentity': windows_identity, 'rustBrandingAudit': rust_audit}
    write_json(work / 'prepared.json', record)
    print('Prepared complete native ' + lock['name'] + ' source, original engine and dependencies retained.')


def prepared(lock):
    work, source, fonts = paths(lock)
    record = json.loads((work / 'prepared.json').read_text(encoding='utf-8'))
    require(record['lock'] == lock, 'App source lock changed; prepare again')
    require(record['sourceTreeSha256'] == source_fingerprint(lock, source), 'Prepared source changed')
    require(record['fontsTreeSha256'] == (common.tree_fingerprint(fonts) if fonts.exists() else None), 'Prepared fonts changed')
    return work, source, fonts, record


def build_env(lock, fonts, target_dir, target):
    env = os.environ.copy()
    prefix = lock['binaries']['app'].upper()
    env.update({'CARGO_TARGET_DIR': str(target_dir), 'CARGO_HOME': os.environ.get('KIO_CARGO_HOME', str(ROOT / '.cache/cargo')),
                'KIO_RELEASE_VERSION': lock['version'],
                'SOURCE_DATE_EPOCH': str(lock['sourceDateEpoch']), prefix + '_BUILD_SHA': lock['source']['commit'],
                prefix + '_VERSION': lock['version'], prefix + '_BUILD_DATE': time.strftime('%Y-%m-%d', time.gmtime(lock['sourceDateEpoch']))})
    if lock['fonts'] is not None:
        env.update({'CRAFT_FONTS_DIR': str(fonts.resolve()), 'CRAFT_FONTS_REQUIRED': '1'})
    else:
        env.pop('CRAFT_FONTS_DIR', None)
        env.pop('CRAFT_FONTS_REQUIRED', None)
    if target == 'aarch64-apple-darwin':
        env['MACOSX_DEPLOYMENT_TARGET'] = '11.0'
    else:
        env['CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS'] = '-C target-feature=+crt-static'
        env[prefix + '_REQUIRE_WINRES'] = '1'
    return env


def assert_host(kind):
    require((kind == 'macos-arm64' and sys.platform == 'darwin' and platform.machine() == 'arm64') or
            (kind == 'windows-x64' and sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64')), 'Use the actual native OS/architecture')


def binary_paths(lock, folder, kind):
    extension = '.exe' if kind == 'windows-x64' else ''
    result = {key: folder / (name + extension) for key, name in lock['binaries'].items()}
    for key, p in result.items():
        require(p.is_file() and not p.is_symlink(), 'Missing real full native binary')
        common.native_header(p, common.TARGETS[kind], key == 'app')
    return result


def check_windows_gui_resource(lock, path, env):
    resource_env = env.copy()
    resource_env['KIO_NATIVE_VERSION_BINARY'] = str(path.resolve())
    code = "$v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($env:KIO_NATIVE_VERSION_BINARY); @{ProductName=$v.ProductName;ProductVersion=$v.ProductVersion;FileVersion=$v.FileVersion} | ConvertTo-Json -Compress"
    resource = json.loads(run(['pwsh', '-NoLogo', '-NoProfile', '-Command', code], env=resource_env, capture=True, timeout=60))
    require(resource['ProductName'] == lock['name'], 'Native GUI PE product identity mismatch')
    require(re.fullmatch(re.escape(lock['upstreamVersion']) + r'(?:\.0)?', resource['ProductVersion'] or '') and re.fullmatch(re.escape(lock['upstreamVersion']) + r'(?:\.0)?', resource['FileVersion'] or ''), 'Native GUI PE version mismatch')
    return {'mode': 'native-pe-version-resource', 'resource': resource, 'reason': 'Original Windows Film --version intentionally displays a modal native information dialog; it is not invoked in headless CI'}


def check_versions(lock, binaries, env):
    versions = {}
    for key, p in binaries.items():
        if key == 'app' and sys.platform == 'win32' and lock['windowsGuiVersionCheck'] == 'pe-resource':
            versions[key] = check_windows_gui_resource(lock, p, env)
            continue
        value = run([p, '--version'], env=env, capture=True, timeout=60)
        require(re.match(re.escape(lock['versionOutputNames'][key]) + r'\s+' + re.escape(lock['upstreamVersion']) + r'(?:\s|$)', value), 'Native binary version differs from its exact pinned source contract')
        versions[key] = value
    return versions


def audit_native_dependencies(binaries, kind):
    result = {}
    if kind == 'macos-arm64':
        for key, binary in binaries.items():
            output = run(['otool', '-L', binary], capture=True, timeout=60)
            libraries = [line.strip().split(' (', 1)[0] for line in output.splitlines()[1:] if line.strip()]
            require(libraries and all(x.startswith(('/usr/lib/', '/System/Library/')) for x in libraries), 'Unstaged non-system Mac shared library')
            result[key] = libraries
    else:
        tool = shutil.which('dumpbin')
        if not tool:
            base = os.environ.get('ProgramFiles(x86)')
            require(base, 'Visual Studio discovery path missing')
            vswhere = Path(base) / 'Microsoft Visual Studio/Installer/vswhere.exe'
            require(vswhere.is_file(), 'Visual Studio C++ tool discovery missing')
            visual_studio = run([vswhere, '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], capture=True, timeout=60)
            candidates = sorted(Path(visual_studio).glob('VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe'))
            require(candidates, 'dumpbin from the required MSVC build tools is missing')
            tool = candidates[-1]
        system = Path(os.environ['SystemRoot']) / 'System32'
        for key, binary in binaries.items():
            output = run([tool, '/nologo', '/dependents', binary], capture=True, timeout=60)
            libraries = re.findall(r'^\s+([A-Za-z0-9_.-]+\.dll)\s*$', output, re.I | re.M)
            require(libraries, 'No PE dependency table was inspected')
            for library in libraries:
                require(not re.match(r'(?:msvcp|vcruntime|concrt|vcomp)[0-9]', library, re.I), 'Native package unexpectedly depends on the VC++ redistributable')
                require(library.lower().startswith(('api-ms-win-', 'ext-ms-win-')) or (system / library).is_file(), 'Unstaged non-system Windows DLL: ' + library)
            result[key] = libraries
    return result


def check_cli_probe(lock, binary, source, env):
    if lock['id'] == 'cad':
        # Original CAD CLI sends unsupported --help to stderr and exits 1.
        # Its supported commands endpoint exposes the actual complete engine registry.
        value = json.loads(run([binary, 'commands'], cwd=source, env=env, capture=True, timeout=60))
        require(isinstance(value, list) and value and all(isinstance(item, dict) and isinstance(item.get('id'), str) for item in value), 'Invalid original CAD command registry')
        ids = [item['id'] for item in value]
        require({'new', 'open', 'qsave', 'saveas', 'line', 'circle', 'ellipse', 'drawing.inspect', 'dist', 'area'} <= set(ids), 'Incomplete original CAD command registry')
        return {'mode': 'original-command-registry', 'arguments': ['commands'], 'commands': len(ids), 'status': 'passed'}
    if lock['id'] == 'deck':
        # Original Deck CLI has no --help branch; unknown arguments correctly exit1.
        # Exercise the real headless registry and require complete essential commands instead.
        value = json.loads(run([binary, 'commands'], cwd=source, env=env, capture=True, timeout=60))
        require(isinstance(value, list) and value and all(isinstance(item, dict) and isinstance(item.get('id'), str) for item in value), 'Invalid original Deck command registry')
        ids = [item['id'] for item in value]
        require({'file.new', 'file.open', 'file.save', 'file.saveAs', 'file.export', 'document.inspect'} <= set(ids), 'Incomplete original Deck command registry')
        return {'mode': 'original-command-registry', 'arguments': ['commands'], 'commands': len(ids), 'status': 'passed'}
    run([binary, '--help'], cwd=source, env=env, capture=True, timeout=60)
    return {'mode': 'original-help', 'arguments': ['--help'], 'status': 'passed'}


def build(args, lock):
    assert_host(args.platform)
    work, source, fonts, inputs = prepared(lock)
    target = common.TARGETS[args.platform]
    target_dir = work / ('target-' + args.platform)
    env = build_env(lock, fonts, target_dir, target)
    cargo = ['rustup', 'run', lock['rust'], 'cargo']
    rustc = run(['rustup', 'run', lock['rust'], 'rustc', '--version'], env=env, capture=True)
    require(rustc.startswith('rustc ' + lock['rust'] + ' '), 'Wrong Rust compiler')
    run(cargo + lock['cargoArgs'] + ['--target', target], cwd=source, env=env)
    require(lock['testPackages'], 'No original core tests selected')
    # Match CAD/Photo's original `cargo xtask ci` unit-test profile. The shipped
    # GUI/CLI above and the actual packaged-file QA remain full release builds.
    original_unit_test_profile = lock['id'] in ('cad', 'photo')
    serial_windows_unit = original_unit_test_profile and args.platform == 'windows-x64'
    command = cargo + ['test'] + ([] if original_unit_test_profile else ['--release']) + ['--locked', '--target', target]
    for package in lock['testPackages']:
        command += ['-p', package]
    test_env = dict(env, CARGO_BUILD_JOBS='1') if serial_windows_unit else env
    run(command, cwd=source, env=test_env)
    core_test_execution = {'profile': 'test' if original_unit_test_profile else 'release',
                           'command': command, 'packages': lock['testPackages'],
                           'compilerJobsSetting': test_env.get('CARGO_BUILD_JOBS', 'cargo-default'),
                           'compilerJobsOverride': '1' if serial_windows_unit else None,
                           'profileBasis': 'original-cargo-xtask-ci' if original_unit_test_profile else 'release-core-tests'}
    if original_unit_test_profile:
        evidence = ROOT / ('manifests/build-prerequisites-' + lock['id'] + '-tests.json')
        core_test_execution['originalProfileEvidence'] = {'path': evidence.relative_to(ROOT).as_posix(),
                                                        'sha256': digest(evidence), 'bytes': evidence.stat().st_size}
    if lock['id'] == 'photo':
        # The original profile evidence predates the separate test-icon fixture.
        # Bind its explicit 374-exact/one-test-only-exception assessment as well.
        evidence = ROOT / 'manifests/build-prerequisites-photo-svg-fixture.json'
        core_test_execution['originalTestFixtureEvidence'] = {'path': evidence.relative_to(ROOT).as_posix(),
                                                            'sha256': digest(evidence), 'bytes': evidence.stat().st_size}
    if lock['id'] == 'vector':
        # Keep the original engine suite and additionally verify the complete
        # vendored PDF number parser through the real application dependency.
        run(cargo + ['test', '--release', '--locked', '--target', target, '-p', 'vectorcraft-pdf', '--test', 'hayro_number_tokens'], cwd=source, env=env)
    if lock['id'] == 'light':
        # Keep the original engine suites and exercise KIO Photo discovery in
        # the native host too, without launching a graphical window.
        run(cargo + ['test', '--release', '--locked', '--target', target, '-p', 'lightcraft', '--bin', 'lightcraft', 'editors::tests'], cwd=source, env=env)
    if lock['id'] == 'pdf':
        # The KIO updater belongs to the native shell and UI, outside the original
        # engine test package. Keep those tests and run both new boundaries too.
        run(cargo + ['test', '--release', '--locked', '--target', target, '-p', 'pdfcraft', '--bin', 'pdfcraft', 'updates::tests'], cwd=source, env=env)
        run(cargo + ['test', '--release', '--locked', '--target', target, '-p', 'pdfcraft-ui-egui', '--lib', 'updates::kio_version_tests'], cwd=source, env=env)
    binaries = binary_paths(lock, target_dir / target / 'release', args.platform)
    versions = check_versions(lock, binaries, env)
    cli_probe = check_cli_probe(lock, binaries['cli'], source, env)
    prepared(lock)
    record = {'schema': 1, 'app': lock['id'], 'version': lock['version'], 'platform': args.platform, 'target': target, 'rustc': rustc,
              'inputs': inputs, 'cargoArgs': lock['cargoArgs'], 'features': lock['features'],
              'binaries': {key: {'sha256': digest(p), 'bytes': p.stat().st_size} for key, p in binaries.items()},
              'checks': {'nativeArchitecture': 'passed', 'originalCoreTests': 'passed', 'testPackages': lock['testPackages'], 'originalCoreTestExecution': core_test_execution, 'kioVectorPdfNumberRegressionTests': 'passed' if lock['id'] == 'vector' else 'not-applicable', 'kioLightEditorRegressionTests': 'passed' if lock['id'] == 'light' else 'not-applicable', 'kioPdfUpdateRegressionTests': 'passed' if lock['id'] == 'pdf' else 'not-applicable', 'binaryVersions': versions, 'cliProbe': cli_probe, 'guiLaunch': 'not-performed-by-orchestrator'}}
    write_json(work / ('build-' + args.platform + '.json'), record)


def notices(lock, source, fonts, destination, record, env, target):
    destination.mkdir(parents=True)
    common.copy_license_tree(source, destination / 'original-application', public_validator=source_validator(lock))
    if fonts.exists():
        common.copy_license_tree(fonts, destination / 'craft-fonts')
    common.dependency_licenses(lock, source, env, target, destination / 'Rust-dependencies')
    for fix, _ in functional_fixes(lock):
        correction_dir = destination / 'KIO-functional-corrections'
        correction_dir.mkdir(exist_ok=True)
        for key in ('patch', 'manifest'):
            p = ROOT / fix[key]
            shutil.copyfile(p, correction_dir / p.name)
    for relative in ('KIO-FORK.md', 'KIO-FORK.json', 'README.md', 'ROADMAP.md', 'ATTRIBUTION.md', 'docs/gaps.md', 'docs/target-app-parity.md'):
        p = source / relative
        if p.is_file():
            out = destination / 'original-application' / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, out)
    write_json(destination / 'BUILD-PROVENANCE.json', record)
    (destination / 'KIO-README.txt').write_text(lock['name'] + ' ' + lock['version'] + '\nComplete original native GUI and CLI, with KIO branding.\nOriginal default features and official native additions are retained.\nRead the original README/ROADMAP/gaps; this is not a claim of full commercial-product compatibility.\nDevelopment release: no Apple notarization or Windows publisher certificate.\nUse the exact matching full-source release asset and Cargo.lock for rebuilding.\n', encoding='utf-8')


def stage_extras(lock, source, destination, env):
    if lock['id'] != 'pdf':
        return []
    models = destination / 'models'
    # The original xtask selects all original ATTRIBUTION.toml model entries, checks
    # their pinned SHA-256 and copies the original individual licenses and attribution.
    run(['rustup', 'run', lock['rust'], 'cargo', 'xtask', 'models', models], cwd=source, env=env, timeout=1800)
    require((models / 'ATTRIBUTION.txt').is_file() and list(models.glob('*.LICENCE.txt')), 'Original OCR models/licenses missing')
    files = common.regular_files(models, public=True)
    require(files and not any(r.endswith('.part') for r, _ in files), 'Incomplete OCR model staging')
    return [{'path': 'models/' + r, 'sha256': digest(p), 'bytes': p.stat().st_size} for r, p in files]


def package(args, lock):
    assert_host(args.platform)
    work, source, fonts, inputs = prepared(lock)
    target = common.TARGETS[args.platform]
    target_dir = work / ('target-' + args.platform)
    env = build_env(lock, fonts, target_dir, target)
    if args.existing_target:
        base = args.existing_target.resolve()
        folder = base if base.name == 'release' else base / 'release'
        binaries = binary_paths(lock, folder, args.platform)
        versions = check_versions(lock, binaries, env)
        record = {'schema': 1, 'app': lock['id'], 'version': lock['version'], 'platform': args.platform, 'inputs': inputs,
                  'buildOrigin': 'existing-native-host-build-explicitly-selected-by-caller', 'checks': {'nativeArchitecture': 'passed', 'binaryVersions': versions, 'originalCoreTests': 'not-repeated-for-import', 'guiLaunch': 'not-performed-by-orchestrator'},
                  'binaries': {k: {'sha256': digest(p), 'bytes': p.stat().st_size} for k, p in binaries.items()}}
    else:
        record = json.loads((work / ('build-' + args.platform + '.json')).read_text(encoding='utf-8'))
        require(record['inputs'] == inputs, 'Build inputs changed')
        binaries = binary_paths(lock, target_dir / target / 'release', args.platform)
    for key, p in binaries.items():
        require(digest(p) == record['binaries'][key]['sha256'], 'Binary changed since native validation')
    record['nativeLinkedLibraries'] = audit_native_dependencies(binaries, args.platform)
    stage = work / ('package-' + args.platform)
    output = ROOT / 'dist' / (lock['id'] + '-' + args.platform)
    require(not stage.exists() and not output.exists(), 'Package staging/output exists; inspect it before replacing explicitly')
    stage.mkdir()
    output.mkdir(parents=True)
    base = artifact_base(lock, args.platform)
    if args.platform == 'macos-arm64':
        app = stage / (lock['name'] + '.app')
        macos, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
        macos.mkdir(parents=True)
        resources.mkdir()
        shutil.copy2(binaries['app'], macos / lock['name'])
        shutil.copy2(binaries['cli'], macos / ('kio-' + lock['id'] + '-cli'))
        for p in macos.iterdir():
            p.chmod(0o755)
        icon = source / lock['icon']
        require(icon.is_file(), 'KIO native icon missing')
        shutil.copyfile(icon, resources / (lock['name'] + '.icns'))
        text = (source / 'packaging/macos/Info.plist.in').read_text(encoding='utf-8')
        text = text.replace('@VERSION@', lock['version']).replace('@SHORT_VERSION@', lock['upstreamVersion']).replace('@BUILD_SHA@', lock['source']['commit'])
        info = plistlib.loads(text.encode('utf-8'))
        require(info['CFBundleIdentifier'] == lock['bundleId'] and info['CFBundleExecutable'] == lock['name'] and info['CFBundleIconFile'] == lock['name'], 'Unexpected patched native bundle metadata')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        (app / 'Contents/PkgInfo').write_bytes(b'APPL????')
        record['bundledExtras'] = stage_extras(lock, source, resources, env)
        notices(lock, source, fonts, resources / 'OpenSourceLicenses', record, env, target)
        sign = ['codesign', '--force', '--sign', '-', '--timestamp=none']
        for p in [*macos.iterdir(), app]:
            run(sign + [p])
        run(['codesign', '--verify', '--strict', '--deep', app])
        run(['ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent', app, output / (base + '.zip')])
        dmg = stage / 'dmg'
        dmg.mkdir()
        run(['ditto', app, dmg / app.name])
        (dmg / 'Applications').symlink_to('/Applications')
        run(['hdiutil', 'makehybrid', '-hfs', '-hfs-volume-name', lock['name'], '-o', stage / 'raw.dmg', dmg])
        run(['hdiutil', 'convert', stage / 'raw.dmg', '-format', 'UDZO', '-imagekey', 'zlib-level=9', '-o', output / (base + '.dmg')])
        run(sign + [output / (base + '.dmg')])
        run(['codesign', '--verify', '--strict', output / (base + '.dmg')])
        record['signing'] = {'kind': 'ad-hoc', 'notarized': False}
    else:
        folder = stage / lock['name']
        folder.mkdir()
        shutil.copy2(binaries['app'], folder / (lock['name'] + '.exe'))
        shutil.copy2(binaries['cli'], folder / ('kio-' + lock['id'] + '-cli.exe'))
        record['bundledExtras'] = stage_extras(lock, source, folder, env)
        portable = source / 'packaging/windows/portable.txt'
        if portable.is_file():
            shutil.copyfile(portable, folder / 'portable.txt')
        notices(lock, source, fonts, folder / 'OpenSourceLicenses', record, env, target)
        legal_validator = common.reviewed_notice_public_validator(folder, 'OpenSourceLicenses/Rust-dependencies')
        common.create_source_zip(output / (base + '.zip'), [(lock['name'] + '/' + r, p) for r, p in common.regular_files(folder, public=True, public_validator=legal_validator)], lock['sourceDateEpoch'])
        record['msiPackaging'] = original_windows_msi(lock, source, folder / 'OpenSourceLicenses', stage, env, output / (base + '.msi'))
        record['signing'] = {'kind': 'unsigned', 'publisherCertificate': False}
    write_json(output / (base + '-provenance.json'), record)
    finalize(output, lock, args.platform)
    print('Full native package: ' + str(output))


def add_msi_notices(original, lock, license_dir):
    """Preserve the original installer, associations and dialogs; add a legal-files component group."""
    require(original.count('</Feature>') >= 1 and original.count('</Wix>') == 1, 'Unexpected original WiX document')
    original = original.replace('</Feature>', '<ComponentGroupRef Id="KioNotices" /></Feature>', 1)
    components, references = [], []
    legal_validator = common.reviewed_notice_public_validator(license_dir, 'Rust-dependencies')
    for relative, p in common.regular_files(license_dir, public=True, public_validator=legal_validator):
        token = hashlib.sha256((lock['id'] + '/' + relative).encode('utf-8')).hexdigest()[:28]
        component, file_id = 'KioC' + token, 'KioF' + token
        guid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://kio-library.vercel.app/native/' + lock['id'] + '/legal/' + relative)).upper()
        parts = Path(relative).parts
        # Each directory path is emitted once below; this leaf is grouped by its parent.
        components.append((parts[:-1], '<Component Id=' + quoteattr(component) + ' Guid=' + quoteattr(guid) + '><File Id=' + quoteattr(file_id) + ' Source=' + quoteattr(str(p.resolve())) + ' Name=' + quoteattr(parts[-1]) + ' KeyPath="yes" /></Component>'))
        references.append('<ComponentRef Id=' + quoteattr(component) + ' />')
    require(components, 'MSI legal material missing')
    tree = {'components': [], 'children': {}}
    for parts, component in components:
        node = tree
        for part in parts:
            node = node['children'].setdefault(part, {'components': [], 'children': {}})
        node['components'].append(component)
    def emit(node, parts=()):
        result = ''.join(node['components'])
        for part, child in sorted(node['children'].items()):
            path = parts + (part,)
            token = hashlib.sha256((lock['id'] + '/' + '/'.join(path)).encode('utf-8')).hexdigest()[:28]
            result += '<Directory Id="KioD' + token + '" Name=' + quoteattr(part) + '>' + emit(child, path) + '</Directory>'
        return result
    fragment = '<Fragment><DirectoryRef Id="INSTALLFOLDER"><Directory Id="KioNoticesDirectory" Name="OpenSourceLicenses">' + emit(tree) + '</Directory></DirectoryRef><ComponentGroup Id="KioNotices">' + ''.join(references) + '</ComponentGroup></Fragment>'
    return original.replace('</Wix>', fragment + '</Wix>'), len(components)


_PDF_MSI_BRAND_CONTRACT = (
    ('packaging/windows/pdfcraft.wxs',
     16873, '0be7eb9beb2b8ad3e266c5a6951424acc4a22c5a05bb72bf85a5369a2bd65f40',
     16870, 'f35f1b3371bc5667e12247475e2c77d3e1f677712d97f5e30b832295f7af0885', (
         ('Message="PdfCraft must be installed for all users.', 'Message="KIO PDF must be installed for all users.'),
         ('DowngradeErrorMessage="A newer version of PdfCraft is already installed."', 'DowngradeErrorMessage="A newer version of KIO PDF is already installed."'),
         ('Title="PdfCraft" Level="1"', 'Title="KIO PDF" Level="1"'))),
    ('packaging/windows/test-msi.ps1',
     14496, 'f631acf80a2ee1d14b0fb493fd2c18fdd0fbcc983e0f2ab30867780758578103',
     14478, 'a73eac48220b234d863a7793ca5c8d01a93f2d8689759e953f8ad9cb4895f4d8', (
         ("Assert-Equal $manufacturer[0] 'Learning Machines LLC' 'MSI manufacturer'", "Assert-Equal $manufacturer[0] 'KIO' 'MSI manufacturer'"),
         ('\\shell\\KIO PDF.CreatePdf', '\\shell\\KIO.PDF.CreatePdf'),
         ('\\shell\\KIO PDF.Edit', '\\shell\\KIO.PDF.Edit'))),
    ('packaging/windows/installer-ui.wxs',
     8444, 'ab02462f1e12c09f2bbd912035ec8cf13537390f756a8ea060db9e3d96af6627',
     8443, '92e54b5ea2430e227217c590c332d2f8763ac695e1e7c54e2753549dc08f8625', (
         ('Text="Add &quot;&amp;Edit with PdfCraft&quot; to the right-click menu of PDF files"',
          'Text="Add &quot;&amp;Edit with KIO PDF&quot; to the right-click menu of PDF files"'),)),
)


def pdf_msi_brand_contract(lock, source, project):
    """Correct seven authenticated installer-identity strings in the Windows copy only.

    Keep the prepared workspace, compiled inputs, original MSI evaluator and all
    eight scope cases intact. Unknown source/branding/file bytes fail closed.
    """
    if lock['id'] != 'pdf':
        return {'status': 'not-applicable'}
    require(lock['upstreamVersion'] == '0.8.0' and lock['name'] == 'KIO PDF'
            and lock['source']['commit'] == '9931329b9fae0b05373b4dc3ac7c58541f0891a4'
            and lock['branding']['sha256'] == 'c3a7a7302acfb8c357e6524a6bc454e7b0108ae9117c24649072e65f4e927d5e',
            'Unreviewed PDF MSI source or branding contract')
    source, project = Path(source), Path(project)
    require(project.name == 'original-msi-project' and project.is_dir() and not project.is_symlink()
            and not project.resolve().is_relative_to(source.resolve())
            and not source.resolve().is_relative_to(project.resolve()),
            'PDF MSI repair requires a separate original-msi-project copy')
    pending, records = [], []
    for relative, before_bytes, before_sha, after_bytes, after_sha, replacements in _PDF_MSI_BRAND_CONTRACT:
        path, original = project / relative, source / relative
        for root, item in ((project, path), (source, original)):
            require(item.is_file() and not item.is_symlink(), 'PDF MSI input must be a regular file: ' + relative)
            for parent in item.parents:
                require(not parent.is_symlink(), 'PDF MSI input has a symlink ancestor')
                if parent == root:
                    break
        data = path.read_bytes()
        require(len(data) == before_bytes and hashlib.sha256(data).hexdigest() == before_sha
                and original.read_bytes() == data, 'PDF MSI exact before bytes differ: ' + relative)
        text, changes = data.decode('utf-8'), []
        for before, after in replacements:
            require(text.count(before) == 1, 'PDF MSI identity replacement count differs: ' + relative)
            text = text.replace(before, after)
            changes.append({'before': before, 'after': after, 'count': 1})
        result = text.encode('utf-8')
        require(len(result) == after_bytes and hashlib.sha256(result).hexdigest() == after_sha,
                'PDF MSI exact after bytes differ: ' + relative)
        pending.append((path, original, data, result))
        records.append({'path': relative, 'beforeBytes': before_bytes, 'beforeSha256': before_sha,
                        'afterBytes': after_bytes, 'afterSha256': after_sha,
                        'replacementCount': len(changes), 'replacements': changes})
    require(sum(row['replacementCount'] for row in records) == 7, 'PDF MSI requires exactly seven identity corrections')
    # Authenticate every input and computed output before changing any stage file.
    for path, _, _, result in pending:
        path.write_bytes(result)
    require(all(original.read_bytes() == before for _, original, before, _ in pending),
            'Prepared PDF MSI inputs changed unexpectedly')
    return {'status': 'applied-to-windows-copy-only', 'sourceCommit': lock['source']['commit'],
            'brandingPatchSha256': lock['branding']['sha256'], 'files': records,
            'replacementCount': 7, 'phase': 'before-additional-license-components',
            'preparedSourceFilesUnchanged': True,
            'originalMsiEvaluatorAndEightScopeCases': 'retained'}


def original_windows_msi(lock, source, license_dir, stage, env, destination):
    # Use a separate full project copy so the prepared, fingerprinted source remains immutable.
    project = stage / 'original-msi-project'
    project.mkdir()
    for relative, p in source_files(lock, source):
        out = project / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)
    pdf_brand_contract = pdf_msi_brand_contract(lock, source, project)
    wxs = project / 'packaging/windows' / (lock['binaries']['app'] + '.wxs')
    text, count = add_msi_notices(wxs.read_text(encoding='utf-8'), lock, license_dir)
    wxs.write_text(text, encoding='utf-8')
    upstream_output = stage / 'original-msi-output'
    upstream_output.mkdir()
    package_env = env.copy()
    package_env['DIST'] = str(upstream_output)
    # The original installer consumes the original upstream executable filenames.
    # These are the same full native bytes already validated above.
    run(['pwsh', '-NoLogo', '-NoProfile', '-File', project / 'packaging/windows/package.ps1', '-Arch', 'x64', '-SkipBuild'], cwd=project, env=package_env, timeout=1800)
    candidates = list(upstream_output.glob('*.msi'))
    require(len(candidates) == 1 and candidates[0].is_file() and not candidates[0].is_symlink(), 'Original native MSI was not produced')
    require(candidates[0].read_bytes()[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'Invalid MSI container')
    shutil.copyfile(candidates[0], destination)
    return {'originalScript': 'packaging/windows/package.ps1', 'skipBuild': True, 'architecture': 'x64', 'addedOriginalLicenseFiles': count, 'upstreamInstallerBehavior': 'retained', 'publisherCertificate': False, 'stagedPdfBrandContract': pdf_brand_contract}


def artifact_base(lock, kind):
    require(kind in (*common.TARGETS, 'source'), 'Unknown artifact kind')
    return lock['assetPrefix'] + '-' + lock['version'] + '-' + kind


def finalize(output, lock, kind):
    base = artifact_base(lock, kind)
    files = [{'path': r, 'sha256': digest(p), 'bytes': p.stat().st_size} for r, p in common.regular_files(output, public=True)]
    write_json(output / (base + '-manifest.json'), {'schema': 1, 'app': lock['id'], 'version': lock['version'], 'kind': kind, 'upstreamCommit': lock['source']['commit'], 'brandingPatchSha256': lock['branding']['sha256'], 'files': files})
    manifest = output / (base + '-manifest.json')
    entries = files + [{'path': manifest.name, 'sha256': digest(manifest), 'bytes': manifest.stat().st_size}]
    (output / (base + '-SHA256SUMS.txt')).write_text(''.join(x['sha256'] + '  ' + x['path'] + '\n' for x in entries), encoding='utf-8')
    verify(output, lock, kind)


def verify(folder, lock, kind):
    base = artifact_base(lock, kind)
    folder = Path(folder)
    manifest = folder / (base + '-manifest.json')
    require(manifest.is_file() and not manifest.is_symlink(), 'Expected app-specific release manifest missing')
    value = json.loads(manifest.read_text(encoding='utf-8'))
    require(value['schema'] == 1 and value['app'] == lock['id'] and value['version'] == lock['version'] and value['kind'] == kind, 'Release identity mismatch')
    require(value['upstreamCommit'] == lock['source']['commit'] and value['brandingPatchSha256'] == lock['branding']['sha256'], 'Release source/patch identity mismatch')
    suffixes = ['.zip', '-provenance.json'] + (['.dmg'] if kind == 'macos-arm64' else ['.msi'] if kind == 'windows-x64' else [])
    require(len(value['files']) == len(suffixes) and {x['path'] for x in value['files']} == {base + s for s in suffixes}, 'Release artifact allowlist mismatch')
    expected = {manifest.name, base + '-SHA256SUMS.txt'}
    lines = []
    for item in value['files']:
        require(common.safe_relative(item['path']).name == item['path'] and common.HEX.fullmatch(item['sha256']) and 0 < item['bytes'] <= 2 * 1024 * 1024 * 1024, 'Invalid release artifact record')
        p = folder / item['path']
        require(p.is_file() and not p.is_symlink() and p.stat().st_size == item['bytes'] and digest(p) == item['sha256'], 'Release SHA/byte mismatch')
        expected.add(p.name)
        lines.append(item['sha256'] + '  ' + p.name + '\n')
    lines.append(digest(manifest) + '  ' + manifest.name + '\n')
    require((folder / (base + '-SHA256SUMS.txt')).read_text(encoding='utf-8') == ''.join(lines), 'Release checksums changed')
    require({r for r, _ in common.regular_files(folder, public=True)} == expected, 'Unlisted release file')
    return [folder / x for x in sorted(expected)]


def public_files(lock):
    files = set(common.PUBLIC_FILES) | {'scripts/full_native.py', 'scripts/audit_windows_identity.py', 'tests/test_full_native.py', 'tests/test_windows_identity.py', 'manifests/full-native-apps.json', 'manifests/archive-inputs.json', '.github/workflows/full-native-apps.yml'}
    files.update({'.github/workflows/native-file-qa.yml', 'docs/native-file-qa.md',
                  'scripts/native_file_qa.py', 'scripts/collect_ci_artifact.py', 'scripts/smoke_word.py', 'scripts/smoke_craft.py', 'scripts/smoke_office.py',
                  'tests/test_native_file_qa.py', 'tests/test_collect_ci_artifact.py', 'tests/test_smoke_word.py', 'tests/test_smoke_craft.py',
                  'tests/test_photo_cli_build_metadata.py'})
    files.update({'scripts/audit_rust_branding.py', 'tests/test_rust_branding.py',
                  'tests/fixtures/rust-branding/provenance.json', 'tests/fixtures/rust-branding/ui-home-recents.rs'})
    files.update({'tests/test_native_contract_regressions.py',
                  'tests/fixtures/native-contracts/winit-3d51077fd1a966f84df9ef287839dc84fd5b4ca7/LICENSE',
                  'tests/fixtures/native-contracts/winit-3d51077fd1a966f84df9ef287839dc84fd5b4ca7/provenance.json'})
    files.update({'tests/test_cad_plotter_api.py', 'tests/fixtures/cad-plotter-api/provenance.json',
                  'tests/fixtures/cad-plotter-api/apps/cadcraft/Cargo.toml',
                  'tests/fixtures/cad-plotter-api/crates/engine/src/lib.rs',
                  'tests/fixtures/cad-plotter-api/crates/doc/src/lib.rs',
                  'tests/fixtures/cad-plotter-api/crates/doc/src/plotter.rs'})
    files.add('tests/test_design_recovery_fix.py')
    files.add('tests/test_cad_test_profile.py')
    files.add('tests/test_photo_test_profile.py')
    files.update({'tests/test_photo_svg_fixture.py',
                  'tests/fixtures/photo-svg/upstream-svg.rs',
                  'tests/fixtures/photo-svg/provenance.json'})
    files.update({'tests/test_pdf_msi_brand_contract.py',
                  'tests/fixtures/pdf-msi-brand-contract/provenance.json',
                  'tests/fixtures/pdf-msi-brand-contract/upstream-test-msi.ps1',
                  'tests/fixtures/pdf-msi-brand-contract/before/packaging/windows/pdfcraft.wxs',
                  'tests/fixtures/pdf-msi-brand-contract/before/packaging/windows/test-msi.ps1',
                  'tests/fixtures/pdf-msi-brand-contract/before/packaging/windows/installer-ui.wxs'})
    # Small original XML fixtures make the installer collision tests independent
    # of the source archive cache. Include the exact Launcher branding input too.
    files.update('tests/fixtures/windows-identity/' + app + '.wxs' for app in (*IDS, 'launcher'))
    files.update({'tests/fixtures/windows-identity/provenance.json', 'manifests/launcher.lock.json', 'patches/launcher/manifest.json', 'patches/launcher/craft-launcher-v0.4.1-kio-launcher.patch'})
    for app in IDS:
        other = load_lock(app)
        files.update([other['branding']['patch'], other['branding']['manifest']])
        for fix in other.get('functionalFixes', []):
            files.update([fix['patch'], fix['manifest']])
        readme = 'patches/' + app + '/README.md'
        if (ROOT / readme).is_file():
            files.add(readme)
    for p in (ROOT / 'manifests').glob('build-prerequisites-*.json'):
        files.add(p.relative_to(ROOT).as_posix())
    for relative in sorted(files):
        common.check_public_path(relative)
        path = ROOT / relative
        require(path.is_file() and not path.is_symlink(), 'Missing reviewed public build input: ' + relative)
        yield relative, path


def make_source(args, lock):
    work, source, fonts, inputs = prepared(lock)
    output = ROOT / 'dist' / (lock['id'] + '-source')
    require(not output.exists(), 'Source release exists; explicit inspection required before replacing')
    output.mkdir(parents=True)
    readme = work / 'SOURCE-README.txt'
    fonts_note = 'Set CRAFT_FONTS_DIR to the absolute craft-fonts folder and CRAFT_FONTS_REQUIRED=1.\n' if lock['fonts'] else 'This upstream release does not specify an additional craft-fonts checkout.\n'
    readme.write_text('Complete modified ' + lock['name'] + ' original native workspace. No engine features were removed.\nOriginal dependency version pins, licenses, notices, credits, formats and optional extension capability remain. Any reviewed Cargo.lock dependency-edge correction is recorded in its functional patch manifest.\nThird-party Cargo archives are not duplicated; Cargo fetches their exact locked sources.\nInstall Rust 1.95.0 and the target OS SDK/tooling documented in orchestrator/manifests/build-prerequisites-*.json.\n' + fonts_note + 'From ' + lock['binaries']['app'] + '/ run: cargo +1.95.0 ' + ' '.join(lock['cargoArgs']) + '\nPDF full packages also run cargo xtask models to stage SHA-verified OCR models and original model licenses beside the app.\nReproducible KIO source locks, original feature selection, branding patch and native packaging scripts are in orchestrator/.\nRead original README/ROADMAP/gaps for known application limitations. No full commercial-product parity is claimed.\n', encoding='utf-8')
    files = [(lock['binaries']['app'] + '/' + r, p) for r, p in source_files(lock, source)]
    if fonts.exists():
        files += [('craft-fonts/' + r, p) for r, p in common.regular_files(fonts, public=True)]
    files += [('SOURCE-README.txt', readme), ('BUILD-INPUTS.json', work / 'prepared.json')]
    files += [('orchestrator/' + r, p) for r, p in public_files(lock)]
    base = artifact_base(lock, 'source')
    common.create_source_zip(output / (base + '.zip'), files, lock['sourceDateEpoch'])
    write_json(output / (base + '-provenance.json'), {'schema': 1, 'app': lock['id'], 'inputs': inputs, 'fileCount': len(files), 'cargoVendored': False})
    finalize(output, lock, 'source')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('matrix', 'prepare', 'build', 'package', 'source', 'verify', 'publish-draft'))
    parser.add_argument('--app', choices=(*IDS, 'all'), required=True)
    parser.add_argument('--platform', choices=(*common.TARGETS, 'source'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--existing-target', type=Path)
    parser.add_argument('--archive-cache', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()
    selected = IDS if args.app == 'all' else (args.app,)
    locks = [load_lock(app) for app in selected]
    if args.command == 'matrix':
        matrix = {'include': [{'app': x['id'], 'runner': runner, 'platform': kind, 'target': target, 'python': python} for x in locks for runner, kind, target, python in [('macos-15', 'macos-arm64', 'aarch64-apple-darwin', 'python3'), ('windows-2022', 'windows-x64', 'x86_64-pc-windows-msvc', 'python')]]}
        print(json.dumps(matrix, separators=(',', ':')))
        return
    if args.command == 'publish-draft':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and os.environ.get('GITHUB_REF') == 'refs/heads/main' and os.environ.get('KIO_PUBLISH_DRAFT') == 'true' and args.directory, 'Publication requires manual main dispatch and explicit flag')
        for lock in locks:
            files = []
            for kind in (*common.TARGETS, 'source'):
                files += verify(args.directory / (lock['id'] + '-' + kind), lock, kind)
            run(['gh', 'release', 'create', lock['id'] + '-v' + lock['version'], '--draft', '--target', os.environ['GITHUB_SHA'], '--title', lock['name'] + ' ' + lock['version'] + ' full native development build', '--notes-file', ROOT / 'README.md', *files])
        return
    require(args.app != 'all', 'Use an individual app for native operations')
    lock = locks[0]
    if args.command in ('build', 'package', 'verify'):
        require(args.platform, '--platform is required')
    if args.command == 'prepare': prepare(args, lock)
    elif args.command == 'build': build(args, lock)
    elif args.command == 'package': package(args, lock)
    elif args.command == 'source': make_source(args, lock)
    elif args.command == 'verify':
        require(args.directory, '--directory is required')
        verify(args.directory, lock, args.platform)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Native build stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
