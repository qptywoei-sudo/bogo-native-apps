#!/usr/bin/env python3
"""Build the full pinned KIO Launcher native Rust workspace, separately from the 13 editors."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

import full_native as full

common = full.common
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'manifests/launcher.lock.json'
SOURCE_COMMIT = 'cbae640688c5fa3daa120a7f5e050f8e24148a47'
SOURCE_SHA = '5973336d8a48213feb51e96b2eac73bcdc0e0c94f58b299a6e1b2fb40024ada7'
require, run, digest, write_json = common.require, common.run, common.digest, common.write_json


def load_lock():
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    require(lock['schema'] == 1 and lock['id'] == 'launcher' and lock['rust'] == '1.95.0', 'Invalid Launcher lock')
    require(lock['name'] == 'KIO Launcher' and lock['bundleId'] == 'com.kio.launcher' and lock['assetPrefix'] == 'KIO-Launcher', 'Wrong Launcher identity')
    require(lock['upstreamVersion'] == '0.4.1' and re.fullmatch(r'0\.4\.1-kio\.[1-9][0-9]*', lock['version']), 'Unreviewed Launcher version')
    require(lock['cargoPackages'] == ['artcraft-launcher'] and lock['binaries'] == {'app': 'artcraft-launcher', 'cli': None}, 'Launcher has exactly one original GUI binary; no synthetic CLI')
    require(lock['cargoArgs'] == ['build', '--release', '--locked', '-p', 'artcraft-launcher'] and lock['features'] == {'preserveDefaults': True, 'officialNativeAdditionalFeatures': [], 'developerLocalMirrorEnabled': False}, 'Original default features required; developer mirrors excluded')
    require(lock['testPackages'] == ['artcraft-launcher-core', 'artcraft-launcher-native', 'artcraft-launcher-ui-egui'], 'All meaningful original core/backend/UI tests are required')
    require(lock['fonts'] is None and lock['sourceDateEpoch'] == 1791908909, 'Unreviewed bundled resource or epoch')
    entry = lock['source']
    require(entry == {'repository': 'storytold/craft-launcher', 'commit': SOURCE_COMMIT, 'tag': 'v0.4.1', 'url': 'https://codeload.github.com/storytold/craft-launcher/tar.gz/' + SOURCE_COMMIT, 'root': 'craft-launcher-' + SOURCE_COMMIT, 'sha256': SOURCE_SHA, 'bytes': 2003171}, 'Unreviewed immutable Launcher source')
    brand = lock['branding']
    for key, hash_key, expected in [('patch', 'sha256', 'patches/launcher/craft-launcher-v0.4.1-kio-launcher.patch'), ('manifest', 'manifestSha256', 'patches/launcher/manifest.json')]:
        require(brand[key] == expected and common.HEX.fullmatch(brand[hash_key]), 'Wrong Launcher branding path/hash')
        path = ROOT / common.check_public_path(brand[key])
        require(path.is_file() and not path.is_symlink() and digest(path) == brand[hash_key], 'Launcher branding input changed')
    meta = json.loads((ROOT / brand['manifest']).read_text(encoding='utf-8'))
    require(meta['programId'] == 'launcher' and meta['upstream']['commit'] == SOURCE_COMMIT and meta['patch']['sha256'] == brand['sha256'], 'Launcher patch/source mismatch')
    require((ROOT / brand['patch']).stat().st_size == meta['patch']['bytes'] and meta['checks']['originalArchivePatchRoundtrip'], 'Launcher patch bytes/roundtrip mismatch')
    require(lock['environment']['KIO_RELEASE_VERSION'] == lock['version'] and lock['environment']['ARTCRAFT_LAUNCHER_VERSION'] == lock['version'], 'KIO revision must be embedded')
    return lock


def paths(lock):
    require(lock['id'] == 'launcher', 'Wrong isolated work owner')
    work = ROOT / '.work/launcher'
    require(not work.is_symlink() and not work.parent.is_symlink(), 'Work symlink refused')
    return work, work / 'source', work / 'craft-fonts'


def public_files(lock):
    files = ['README.md', 'LICENSE', '.gitignore', '.gitattributes', 'scripts/kio_native.py', 'scripts/full_native.py', 'scripts/launcher_native.py',
             'tests/test_launcher_native.py', 'scripts/audit_windows_identity.py', 'manifests/launcher.lock.json', 'patches/launcher/manifest.json', lock['branding']['patch'], '.github/workflows/full-native-launcher.yml']
    for relative in files:
        p = ROOT / common.check_public_path(relative)
        require(p.is_file() and not p.is_symlink(), 'Missing reviewed Launcher source input')
        yield relative, p


@contextmanager
def helpers():
    # Change only context-local input paths for reused helpers; generic IDS13/locks/contracts
    # remain untouched on disk and are restored even if source/packaging validation fails.
    old = full.paths, full.public_files, full.CATALOG
    full.paths, full.public_files, full.CATALOG = paths, public_files, LOCK
    try:
        yield
    finally:
        full.paths, full.public_files, full.CATALOG = old


def prepare(args, lock):
    with helpers():
        full.prepare(args, lock)
    _, source, _, _ = prepared(lock)
    import audit_windows_identity
    audit_windows_identity.audit(lock, source, archive_cache=args.archive_cache)
    require((source / 'crates/core/src/kio_registry.rs').is_file(), 'Reviewed native registry missing')
    require(not any(x.is_file() and x.name != 'LICENSE-brand.txt' for x in (source / 'docs/brand').rglob('*')), 'Upstream trademark artwork remains')
    meta = json.loads((ROOT / lock['branding']['manifest']).read_text(encoding='utf-8'))
    for item in meta['protectedFiles']:
        require(digest(source / item['path']) == item['sha256'], 'Protected source/license/font changed')


def prepared(lock):
    with helpers():
        return full.prepared(lock)


def build_env(lock, fonts, target_dir, target):
    env = full.build_env(lock, fonts, target_dir, target)
    env.update(lock['environment'])
    for suffix in ('BUILD_SHA', 'BUILD_DATE', 'VERSION', 'REQUIRE_WINRES'):
        wrong = 'ARTCRAFT-LAUNCHER_' + suffix
        if wrong in env:
            env['ARTCRAFT_LAUNCHER_' + suffix] = env.pop(wrong)
    # The original native user API, local mirror and update environment switches remain opt-in.
    env.pop('ARTCRAFT_LAUNCHER_DOWNLOAD_BASE', None)
    env.pop('ARTCRAFT_LAUNCHER_FEED_URL', None)
    env.pop('ARTCRAFT_LAUNCHER_PRETEND_VERSION', None)
    return env


def binary_paths(lock, folder, kind):
    path = folder / ('artcraft-launcher.exe' if kind == 'windows-x64' else 'artcraft-launcher')
    require(path.is_file() and not path.is_symlink(), 'Real upstream Launcher binary missing')
    common.native_header(path, common.TARGETS[kind], True)
    return {'app': path}


def check_versions(lock, binaries, env):
    value = run([binaries['app'], '--version'], env=env, capture=True, timeout=60)
    require(value == 'artcraft-launcher ' + lock['upstreamVersion'], 'Wrong Launcher native binary version')
    return {'app': value}


def build(args, lock):
    full.assert_host(args.platform)
    work, source, fonts, inputs = prepared(lock)
    target = common.TARGETS[args.platform]
    target_dir = work / ('target-' + args.platform)
    env = build_env(lock, fonts, target_dir, target)
    cargo = ['rustup', 'run', lock['rust'], 'cargo']
    rustc = run(['rustup', 'run', lock['rust'], 'rustc', '--version'], env=env, capture=True)
    require(rustc.startswith('rustc ' + lock['rust'] + ' '), 'Wrong Rust compiler')
    # Check source formatting without changing the reviewed source tree.
    run(cargo + ['fmt', '--all', '--', '--check'], cwd=source, env=env)
    run(cargo + lock['cargoArgs'] + ['--target', target], cwd=source, env=env)
    tests = cargo + ['test', '--release', '--locked', '--target', target]
    for package in lock['testPackages']:
        tests += ['-p', package]
    run(tests, cwd=source, env=env)
    binaries = binary_paths(lock, target_dir / target / 'release', args.platform)
    versions = check_versions(lock, binaries, env)
    prepared(lock)
    write_json(work / ('build-' + args.platform + '.json'), {'schema': 1, 'app': 'launcher', 'version': lock['version'], 'platform': args.platform,
        'target': target, 'rustc': rustc, 'inputs': inputs, 'cargoArgs': lock['cargoArgs'], 'features': lock['features'],
        'binaries': {'app': {'sha256': digest(binaries['app']), 'bytes': binaries['app'].stat().st_size}},
        'checks': {'nativeArchitecture': 'passed', 'originalCoreBackendUiTests': 'passed', 'testPackages': lock['testPackages'], 'binaryVersions': versions,
                   'registryBindingAndArchitectureTests': 'passed-in-original-core-tests', 'guiLaunch': 'not-performed-by-orchestrator', 'cli': 'not-present-in-original-upstream'}})


def notices(lock, source, fonts, destination, record, env, target):
    full.notices(lock, source, fonts, destination, record, env, target)
    (destination / 'KIO-README.txt').write_text('KIO Launcher ' + lock['version'] + '\nFull original native Rust desktop Launcher; no companion CLI exists upstream.\nKIO fork of ArtCraft Launcher v0.4.1; original MIT OR Apache-2.0 licenses, notices, font licenses and credits are retained.\nOriginal install, update, verified download, launch, tray, remove and developer local-mirror source are retained. Production builds use only the exact KIO app registry.\nStudio is private and absent from the public registry. No embedded owner tokens.\nDevelopment release: ad-hoc Apple signature; no notarization or Windows publisher certificate.\nUse the matching full source asset, immutable input lock, branding patch and Cargo.lock to rebuild.\n', encoding='utf-8')


def validate_msi(lock, msi):
    # Real Windows Installer database inspection; does not execute the MSI.
    env = os.environ.copy()
    env['KIO_LAUNCHER_MSI'] = str(msi.resolve())
    code = "$ErrorActionPreference='Stop'; $w=New-Object -ComObject WindowsInstaller.Installer; $d=$w.OpenDatabase($env:KIO_LAUNCHER_MSI,0); $o=@{}; foreach($k in @('ProductName','Manufacturer','ProductVersion')) {$v=$d.OpenView(\"SELECT Value FROM Property WHERE Property='$k'\"); $v.Execute(); $r=$v.Fetch(); $o[$k]=$r.StringData(1); $v.Close()}; $o | ConvertTo-Json -Compress"
    props = json.loads(run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code], env=env, capture=True, timeout=60))
    require(props == {'ProductName': lock['name'], 'Manufacturer': 'KIO', 'ProductVersion': lock['upstreamVersion']}, 'Actual MSI identity differs from the native registry contract')
    return props


def package(args, lock):
    full.assert_host(args.platform)
    work, source, fonts, inputs = prepared(lock)
    target = common.TARGETS[args.platform]
    target_dir = work / ('target-' + args.platform)
    env = build_env(lock, fonts, target_dir, target)
    record = json.loads((work / ('build-' + args.platform + '.json')).read_text(encoding='utf-8'))
    require(record['inputs'] == inputs, 'Build inputs changed')
    binaries = binary_paths(lock, target_dir / target / 'release', args.platform)
    require(digest(binaries['app']) == record['binaries']['app']['sha256'], 'Validated binary changed')
    record['nativeLinkedLibraries'] = full.audit_native_dependencies(binaries, args.platform)
    stage = work / ('package-' + args.platform)
    output = ROOT / 'dist' / ('launcher-' + args.platform)
    require(not stage.exists() and not output.exists(), 'Inspect existing package staging before rebuilding explicitly')
    stage.mkdir()
    output.mkdir(parents=True)
    base = full.artifact_base(lock, args.platform)
    if args.platform == 'macos-arm64':
        app = stage / 'KIO Launcher.app'
        macos, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
        macos.mkdir(parents=True)
        resources.mkdir()
        executable = macos / lock['name']
        shutil.copy2(binaries['app'], executable)
        executable.chmod(0o755)
        shutil.copyfile(source / lock['icon'], resources / 'KIO Launcher.icns')
        template = (source / 'packaging/macos/Info.plist.in').read_text(encoding='utf-8')
        text = template.replace('@VERSION@', lock['version']).replace('@SHORT_VERSION@', lock['upstreamVersion']).replace('@BUILD_SHA@', SOURCE_COMMIT)
        info = plistlib.loads(text.encode('utf-8'))
        require(info['CFBundleIdentifier'] == lock['bundleId'] and info['CFBundleExecutable'] == lock['name'] and info['KIOLauncherVersion'] == lock['version'] and not info.get('LSUIElement', False), 'Original native Mac metadata was changed')
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        (app / 'Contents/PkgInfo').write_bytes(b'APPL????')
        notices(lock, source, fonts, resources / 'OpenSourceLicenses', record, env, target)
        run(['xattr', '-cr', app])
        sign = ['codesign', '--force', '--sign', '-', '--timestamp=none']
        # Keep the complete original launcher entitlements and hardened-runtime setup.
        for item in (executable, app):
            run(sign + ['--options', 'runtime', '--entitlements', source / 'packaging/macos/entitlements.plist', item])
        run(['codesign', '--verify', '--deep', '--strict', app])
        run(['ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent', app, output / (base + '.zip')])
        dmg_stage = stage / 'dmg'
        dmg_stage.mkdir()
        run(['ditto', '--norsrc', '--noextattr', app, dmg_stage / app.name])
        (dmg_stage / 'Applications').symlink_to('/Applications')
        run(['hdiutil', 'makehybrid', '-hfs', '-hfs-volume-name', lock['name'], '-o', stage / 'raw.dmg', dmg_stage])
        run(['hdiutil', 'convert', stage / 'raw.dmg', '-format', 'UDZO', '-imagekey', 'zlib-level=9', '-o', output / (base + '.dmg')])
        run(sign + [output / (base + '.dmg')])
        run(['codesign', '--verify', '--strict', output / (base + '.dmg')])
        record['signing'] = {'kind': 'ad-hoc', 'notarized': False}
    else:
        folder = stage / lock['name']
        folder.mkdir()
        # Keep the original filename: portable self-update replaces this exact executable.
        shutil.copy2(binaries['app'], folder / 'artcraft-launcher.exe')
        shutil.copyfile(source / 'packaging/windows/portable.txt', folder / 'portable.txt')
        notices(lock, source, fonts, folder / 'OpenSourceLicenses', record, env, target)
        common.create_source_zip(output / (base + '.zip'), [(folder.name + '/' + r, p) for r, p in common.regular_files(folder, public=True)], lock['sourceDateEpoch'])
        msi = output / (base + '.msi')
        record['msiPackaging'] = full.original_windows_msi(lock, source, folder / 'OpenSourceLicenses', stage, env, msi)
        record['msiIdentity'] = validate_msi(lock, msi)
        record['signing'] = {'kind': 'unsigned', 'publisherCertificate': False}
    write_json(output / (base + '-provenance.json'), record)
    full.finalize(output, lock, args.platform)
    prepared(lock)


def make_source(args, lock):
    with helpers():
        full.make_source(args, lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'build', 'package', 'source', 'verify', 'publish-draft'))
    parser.add_argument('--platform', choices=(*common.TARGETS, 'source'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--archive-cache', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()
    lock = load_lock()
    if args.command in ('build', 'package', 'verify'):
        require(args.platform, '--platform is required')
    if args.command == 'prepare': prepare(args, lock)
    elif args.command == 'build': build(args, lock)
    elif args.command == 'package': package(args, lock)
    elif args.command == 'source': make_source(args, lock)
    elif args.command == 'verify':
        require(args.directory, '--directory is required')
        full.verify(args.directory, lock, args.platform)
    elif args.command == 'publish-draft':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and os.environ.get('GITHUB_REF') == 'refs/heads/main' and os.environ.get('KIO_PUBLISH_DRAFT') == 'true' and args.directory, 'Publication requires manual main dispatch and explicit flag')
        require(os.environ.get('GH_REPO') == 'qptywoei777-rgb/kio-native-apps', 'Wrong KIO release repository')
        files = []
        for kind in (*common.TARGETS, 'source'):
            files += full.verify(args.directory / ('launcher-' + kind), lock, kind)
        run(['gh', 'release', 'create', lock['releaseTag'], '--draft', '--target', os.environ['GITHUB_SHA'], '--title', lock['name'] + ' ' + lock['version'] + ' full native development build', '--notes-file', ROOT / 'README.md', *files])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Launcher native build stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
