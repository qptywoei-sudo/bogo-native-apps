#!/usr/bin/env python3
"""Build Bogo native apps from verified legacy sources plus exact reviewed overlays."""
import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import full_native as full
import launcher_native as launcher
from bogo_brand import NAMES, PALETTE

ROOT = full.ROOT
CATALOG = ROOT / 'manifests/bogo-native-apps.json'
NS = {'w': 'http://wixtoolset.org/schemas/v4/wxs'}
require, digest, run = full.require, full.digest, full.run


def base_lock(app):
    if app == 'launcher':
        return launcher.load_lock()
    old_catalog = full.CATALOG
    full.CATALOG = ROOT / 'manifests/full-native-apps.json'
    try:
        return full.load_lock(app)
    finally:
        full.CATALOG = old_catalog


def load_lock(app):
    require(app in NAMES, 'Unknown Bogo native app')
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    require(data['schema'] == 1 and data['brand'] == 'Bogo' and data['palette'] == PALETTE, 'Wrong Bogo native catalog')
    rows = [row for row in data['applications'] if row['id'] == app]
    require(len(rows) == 1, 'Missing or duplicate Bogo native overlay')
    row = rows[0]
    legacy = base_lock(app)
    require(row['baseLock'] == ('manifests/launcher.lock.json' if app == 'launcher' else 'manifests/full-native-apps.json') and digest(ROOT / row['baseLock']) == row['baseLockSha256'], 'Legacy input lock changed')
    require(row['name'] == 'Bogo ' + NAMES[app] and row['version'] == legacy['upstreamVersion'] + '-bogo.1' and row['assetPrefix'] == row['name'].replace(' ', '-'), 'Bogo display/release identity mismatch')
    require(row['bundleId'] == legacy['bundleId'] and row['legacyVersion'] == legacy['version'], 'Installed native identity changed')
    patch = ROOT / full.common.check_public_path(row['patch'])
    require(row['patch'] == 'patches/bogo/' + app + '.patch' and patch.is_file() and not patch.is_symlink() and patch.stat().st_size == row['patchBytes'] and digest(patch) == row['patchSha256'], 'Bogo overlay bytes changed')
    paths = [item['path'] for item in row['files']]
    require(paths and len(paths) == len(set(paths)), 'Duplicate Bogo overlay path')
    for item in row['files']:
        path = full.common.check_public_path(item['path'])
        require(not str(path).startswith(('crates/engine/', 'crates/doc/', 'crates/model/', 'vendor/', 'contributors/')) and path.name not in ('Cargo.toml', 'Cargo.lock', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE'), 'Protected Bogo source change refused')
        for side in ('before', 'after'):
            identity = item[side]
            require(identity is None or (full.common.HEX.fullmatch(identity['sha256']) and 0 <= identity['bytes'] < 32 * 1024 * 1024), 'Invalid Bogo overlay file identity')
    lock = copy.deepcopy(legacy)
    lock.update({key: row[key] for key in ('name', 'version', 'assetPrefix')})
    lock.update({'publisher': 'Bogo', 'legacyName': legacy['name'], 'bogoOverlay': row})
    if app in ('grid', 'ui', 'sound'):
        lock['versionOutputNames']['app'] = row['name']
    if app == 'launcher':
        lock['environment']['KIO_RELEASE_VERSION'] = row['version']
        lock['environment']['ARTCRAFT_LAUNCHER_VERSION'] = row['version']
        lock['releaseTag'] = 'launcher-v' + row['version']
        lock['artifacts'] = [row['assetPrefix'] + '-' + row['version'] + suffix for suffix in ('-macos-arm64.dmg', '-macos-arm64.zip', '-windows-x64.msi', '-windows-x64.zip')]
    return lock


def paths(lock):
    work = ROOT / '.work/bogo' / lock['id']
    require(not work.is_symlink() and not work.parent.is_symlink(), 'Bogo work symlink refused')
    return work, work / 'source', work / 'craft-fonts'


def audit_windows_transition(legacy, source, before_xml):
    relative = 'packaging/windows/' + legacy['binaries']['app'] + '.wxs'
    before, after = ET.fromstring(before_xml), ET.parse(Path(source) / relative).getroot()
    old, new = before.find('w:Package', NS), after.find('w:Package', NS)
    require(old is not None and new is not None and new.get('Name') == 'Bogo ' + NAMES[legacy['id']] and new.get('Manufacturer') == 'Bogo', 'Bogo MSI display identity missing')
    require(old.get('UpgradeCode') == new.get('UpgradeCode') and new.get('UpgradeCode'), 'Legacy MSI UpgradeCode changed')
    for tag, attr in [('Component', 'Guid'), ('RegistryValue', 'Key'), ('ProgId', 'Id'), ('ShortcutProperty', 'Value')]:
        old_values = sorted(e.get(attr, '') for e in before.findall('.//w:' + tag, NS))
        new_values = sorted(e.get(attr, '') for e in after.findall('.//w:' + tag, NS))
        require(old_values == new_values, 'Legacy MSI technical identity changed: ' + tag + '/' + attr)
    from bogo_windows_upgrade import validate_additive_searches, APPS as UPGRADE_APPS
    discovery = validate_additive_searches(before, after, legacy['id'])
    old_upgrade, new_upgrade = before.find('.//w:MajorUpgrade', NS), after.find('.//w:MajorUpgrade', NS)
    require(old_upgrade is not None and new_upgrade is not None and old_upgrade.get('AllowSameVersionUpgrades') == new_upgrade.get('AllowSameVersionUpgrades') == 'yes', 'Bogo same-numeric-version upgrade policy missing')
    result = {'path': relative, 'name': new.get('Name'), 'manufacturer': new.get('Manufacturer'), 'upgradeCode': new.get('UpgradeCode'), 'legacyRegistryComponentAndBundleIdentityRetained': True, 'sameNumericVersionUpgrade': True, 'sha256': digest(Path(source) / relative), 'actualMsiExecution': 'not-performed'}
    if legacy['id'] in UPGRADE_APPS:
        result['upgradeDiscovery'] = discovery
    return result


def public_files(lock):
    # The baseline source builder already has an explicit public orchestration allowlist.
    legacy = base_lock(lock['id'])
    legacy_catalog = full.CATALOG
    full.CATALOG = ROOT / 'manifests/full-native-apps.json'
    try:
        editor_lock = legacy if lock['id'] != 'launcher' else full.load_lock('grid')
        original = list(_original_public_files(editor_lock)) + list(launcher.public_files(launcher.load_lock()))
    finally:
        full.CATALOG = legacy_catalog
    seen = set()
    for relative, path in original:
        if relative in seen:
            continue
        seen.add(relative)
        yield relative, path
    extra = ['scripts/bogo_native.py', 'scripts/bogo_brand.py', 'scripts/bogo_assets.py', 'scripts/bogo_launcher.py', 'scripts/record_bogo_overlays.py', 'tests/test_bogo_native.py', 'tests/test_bogo_launcher.py', 'docs/bogo-rebrand.md', 'manifests/bogo-native-apps.json', '.github/workflows/bogo-native-apps.yml']
    extra += ['scripts/smoke_bogo_windows.py', 'manifests/bogo-legacy-upgrade-inputs.json', 'tests/test_bogo_windows_smoke.py', '.github/workflows/full-native-launcher.yml']
    extra += ['scripts/bogo_qa_profiles.py', 'tests/test_bogo_qa_profiles.py']
    extra += ['scripts/bogo_windows_upgrade.py', 'tests/test_bogo_windows_upgrade.py', 'docs/legacy-native-readme.md', 'manifests/bogo-native-downloads.json']
    extra += ['scripts/bogo_packaging.py', 'tests/test_bogo_packaging.py']
    extra += ['docs/bogo-ci-verification.md']
    extra += [row['patch'] for row in json.loads(CATALOG.read_text(encoding='utf-8'))['applications']]
    extra += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'assets/bogo-program-icons').iterdir() if p.is_file()]
    for relative in sorted(set(extra) - seen):
        path = ROOT / full.common.check_public_path(relative)
        require(path.is_file() and not path.is_symlink(), 'Missing Bogo public build input')
        yield relative, path


def pdf_msi_contract(lock, source, project):
    if lock['id'] != 'pdf':
        return {'status': 'not-applicable'}
    records = []
    for relative, *_ in full._PDF_MSI_BRAND_CONTRACT:
        declared = next((r for r in lock['bogoOverlay']['files'] if r['path'] == relative), None)
        require(declared and declared['after'] and digest(Path(source) / relative) == declared['after']['sha256'] and (Path(project) / relative).read_bytes() == (Path(source) / relative).read_bytes(), 'Exact Bogo PDF MSI contract changed')
        records.append({'path': relative, 'sha256': declared['after']['sha256']})
    return {'status': 'authenticated-bogo-source', 'originalSevenCorrectionsRetained': True, 'originalMsiEvaluatorAndEightScopeCases': 'retained', 'files': records}


_original_public_files = full.public_files


@contextmanager
def helpers():
    old = full.paths, full.public_files, full.CATALOG, full.pdf_msi_brand_contract, launcher.paths
    full.paths, full.public_files, full.CATALOG, full.pdf_msi_brand_contract, launcher.paths = paths, public_files, CATALOG, pdf_msi_contract, paths
    try:
        yield
    finally:
        full.paths, full.public_files, full.CATALOG, full.pdf_msi_brand_contract, launcher.paths = old


def prepare(args, lock):
    legacy = base_lock(lock['id'])
    work, source, fonts = paths(lock)
    old_paths, old_catalog = full.paths, full.CATALOG
    full.paths = paths
    full.CATALOG = ROOT / lock['bogoOverlay']['baseLock']
    try:
        full.prepare(args, legacy)
    finally:
        full.paths, full.CATALOG = old_paths, old_catalog
    row = lock['bogoOverlay']
    require(full.source_fingerprint(legacy, source) == row['baseSourceTreeSha256'], 'Bogo overlay base tree differs')
    before_xml = (source / row['windowsInstallerIdentity']['path']).read_text(encoding='utf-8')
    for item in row['files']:
        file = source / item['path']
        identity = item['before']
        require((identity is None and not file.exists()) or (identity is not None and file.is_file() and digest(file) == identity['sha256'] and file.stat().st_size == identity['bytes']), 'Bogo overlay before bytes differ: ' + item['path'])
    run(['git', 'apply', '--check', '--binary', ROOT / row['patch']], cwd=source)
    run(['git', 'apply', '--binary', ROOT / row['patch']], cwd=source)
    for item in row['files']:
        file, identity = source / item['path'], item['after']
        require((identity is None and not file.exists()) or (identity is not None and file.is_file() and digest(file) == identity['sha256'] and file.stat().st_size == identity['bytes']), 'Bogo overlay after bytes differ: ' + item['path'])
    require(full.source_fingerprint(lock, source) == row['sourceTreeSha256'], 'Bogo complete source tree differs')
    windows = audit_windows_transition(legacy, source, before_xml)
    record = json.loads((work / 'prepared.json').read_text(encoding='utf-8'))
    record.update({'lock': lock, 'catalogSha256': digest(CATALOG), 'sourceTreeSha256': row['sourceTreeSha256'], 'bogoOverlay': {'path': row['patch'], 'sha256': row['patchSha256']}, 'windowsInstallerIdentity': windows})
    full.write_json(work / 'prepared.json', record)
    print('Prepared exact Bogo native overlay: ' + lock['name'])


def shared_target_cache(lock, platform):
    """Reuse only generated Cargo outputs; source, locks and per-app receipts stay isolated."""
    full.assert_host(platform)
    work, _, _ = paths(lock)
    cache = ROOT / '.cache/bogo-target' / platform
    require(not cache.is_symlink() and not cache.parent.is_symlink(), 'Bogo target cache symlink refused')
    cache.mkdir(parents=True, exist_ok=True)
    target = work / ('target-' + platform)
    if target.is_symlink():
        require(target.resolve() == cache.resolve(), 'Unexpected native target cache link')
    elif target.exists():
        require(target.is_dir(), 'Unexpected native target output')
        return  # An existing per-app build is preserved and reused in place.
    else:
        target.symlink_to(cache, target_is_directory=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('matrix', 'prepare', 'build', 'package', 'source', 'verify'))
    parser.add_argument('--app', choices=(*NAMES, 'all'), required=True)
    parser.add_argument('--platform', choices=(*full.common.TARGETS, 'source'))
    parser.add_argument('--archive-cache', type=Path)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--reset', action='store_true')
    args = parser.parse_args()
    locks = [load_lock(app) for app in (NAMES if args.app == 'all' else [args.app])]
    if args.command == 'matrix':
        print(json.dumps({'include': [{'app': lock['id'], 'runner': runner, 'platform': kind, 'target': target, 'python': python} for lock in locks for runner, kind, target, python in [('macos-15', 'macos-arm64', 'aarch64-apple-darwin', 'python3'), ('windows-2022', 'windows-x64', 'x86_64-pc-windows-msvc', 'python')]]}))
        return
    require(len(locks) == 1, 'Choose one app for native operations')
    lock = locks[0]
    if args.command in ('build', 'package', 'verify'):
        require(args.platform, '--platform required')
    with helpers():
        if args.command == 'prepare':
            prepare(args, lock)
        elif args.command == 'build':
            shared_target_cache(lock, args.platform)
            (launcher.build if lock['id'] == 'launcher' else full.build)(args, lock)
        elif args.command == 'package':
            args.existing_target = None
            (launcher.package if lock['id'] == 'launcher' else full.package)(args, lock)
        elif args.command == 'source':
            full.make_source(args, lock)
        else:
            require(args.directory, '--directory required')
            full.verify(args.directory, lock, args.platform)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print('Bogo native build stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
