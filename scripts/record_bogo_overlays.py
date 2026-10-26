#!/usr/bin/env python3
"""Record exact Bogo overlays on independently verified legacy native workspaces.

Maintainer authoring command. Normal builds only apply and verify the committed
overlays; they never regenerate source hashes or approve arbitrary changed files.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import full_native as full
import launcher_native as launcher
from bogo_brand import transform_source, NAMES, PALETTE
from bogo_assets import ASSETS, originals
from bogo_qa_profiles import transform_qa_source
from bogo_windows_upgrade import transform_windows_upgrade
from bogo_packaging import transform_packaging_source

ROOT = full.ROOT


def inventory(lock, source):
    return {r: {'sha256': full.digest(p), 'bytes': p.stat().st_size} for r, p in full.source_files(lock, source)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', choices=(*NAMES, 'all'), required=True)
    args = parser.parse_args()
    selected = list(NAMES) if args.app == 'all' else [args.app]
    catalog_path = ROOT / 'manifests/bogo-native-apps.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'schema': 1, 'brand': 'Bogo', 'palette': PALETTE, 'applications': []}
    list(originals())
    for app in selected:
        lock = launcher.load_lock() if app == 'launcher' else full.load_lock(app)
        if app == 'launcher':
            from bogo_launcher import transform_launcher
            work = ROOT / '.work/bogo-record/launcher'
            old_paths, old_catalog = full.paths, full.CATALOG
            full.paths = lambda _: (work, work / 'source', work / 'craft-fonts')
            full.CATALOG = launcher.LOCK
            try:
                full.prepare(SimpleNamespace(reset=work.exists(), archive_cache=ROOT / '.cache/archives', offline=False), lock)
            finally:
                full.paths, full.CATALOG = old_paths, old_catalog
            source = work / 'source'
        else:
            work, source, _ = full.paths(lock)
            full.prepared(lock)
        before = inventory(lock, source)
        base_tree = full.source_fingerprint(lock, source)
        subprocess.run(['git', 'add', '--force', '--all'], cwd=source, check=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=source).returncode:
            subprocess.run(['git', '-c', 'user.name=Bogo Overlay Recorder', '-c', 'user.email=bogo-overlay@localhost', 'commit', '--quiet', '-m', 'Verified immutable legacy native source'], cwd=source, check=True)
        if app == 'pdf':
            # Preserve the previously authenticated seven Windows-only identity corrections
            # in the Bogo source itself, before recording the additional display overlay.
            import shutil
            with tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary) / 'original-msi-project'
                project.mkdir()
                for relative, *_ in full._PDF_MSI_BRAND_CONTRACT:
                    out = project / relative
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / relative, out)
                full.pdf_msi_brand_contract(lock, source, project)
                for relative, *_ in full._PDF_MSI_BRAND_CONTRACT:
                    shutil.copyfile(project / relative, source / relative)
        if app == 'launcher':
            transform_launcher(source, lock)
        if app == 'light':
            from bogo_launcher import transform_light_editor_discovery
            transform_light_editor_discovery(source)
        if app == 'pdf':
            from bogo_launcher import transform_pdf_updates
            transform_pdf_updates(source)
        transform_source(source, app)
        transform_qa_source(source, app)
        transform_windows_upgrade(source, app)
        transform_packaging_source(source, app)
        intermediate = inventory(lock, source)
        rust_paths = [source / r for r in sorted(before.keys() | intermediate.keys()) if r.endswith('.rs') and before.get(r) != intermediate.get(r)]
        if rust_paths:
            subprocess.run(['rustup', 'run', lock['rust'], 'rustfmt', '--edition', '2024', '--config', 'skip_children=true', *rust_paths], check=True)
        after = inventory(lock, source)
        changed = [r for r in sorted(before.keys() | after.keys()) if before.get(r) != after.get(r)]
        if not changed or any(r.endswith(('Cargo.toml', 'Cargo.lock', 'LICENSE-MIT', 'LICENSE-APACHE', 'NOTICE')) or r.startswith(('crates/engine/', 'crates/doc/', 'crates/model/', 'vendor/', 'contributors/')) for r in changed):
            raise ValueError('Bogo overlay changed a protected engine/dependency/license path')
        subprocess.run(['git', 'add', '--force', '--all'], cwd=source, check=True)
        patch = subprocess.check_output(['git', 'diff', '--cached', '--binary', '--full-index', 'HEAD'], cwd=source)
        out = ROOT / 'patches/bogo' / (app + '.patch')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(patch)
        row = {'id': app, 'name': 'Bogo ' + NAMES[app], 'version': lock['upstreamVersion'] + '-bogo.1', 'assetPrefix': 'Bogo-' + NAMES[app], 'bundleId': lock['bundleId'], 'legacyVersion': lock['version'], 'baseLock': 'manifests/launcher.lock.json' if app == 'launcher' else 'manifests/full-native-apps.json', 'baseLockSha256': full.digest(ROOT / ('manifests/launcher.lock.json' if app == 'launcher' else 'manifests/full-native-apps.json')), 'baseSourceTreeSha256': base_tree, 'sourceTreeSha256': full.source_fingerprint(lock, source), 'patch': out.relative_to(ROOT).as_posix(), 'patchSha256': full.digest(out), 'patchBytes': len(patch), 'files': [{'path': r, 'before': before.get(r), 'after': after.get(r)} for r in changed], 'compatibility': {'bundleIdRetained': True, 'msiUpgradeCodeRetained': True, 'profileAndPortableStorageRetained': True, 'originalEngineDependenciesLicensesRetained': True}, 'nativeBuild': 'not-yet-executed'}
        from bogo_native import audit_windows_transition
        row['windowsInstallerIdentity'] = audit_windows_transition(lock, source, before_xml=subprocess.check_output(['git', 'show', 'HEAD:packaging/windows/' + lock['binaries']['app'] + '.wxs'], cwd=source).decode())
        catalog['applications'] = [r for r in catalog['applications'] if r['id'] != app] + [row]
        catalog['applications'].sort(key=lambda r: list(NAMES).index(r['id']))
        full.write_json(catalog_path, catalog)
        print(app, len(changed), len(patch), 'bytes', flush=True)


if __name__ == '__main__':
    main()
