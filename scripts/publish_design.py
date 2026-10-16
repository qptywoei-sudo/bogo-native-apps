"""Publish only the measured Design packages after both native file-QA jobs pass.

No build or native executable runs here. Inputs come exclusively from the fixed
public KIO CI repository, and the existing collector authenticates every package.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

import collect_ci_artifact as collector
import full_native as full

REPO = collector.REPOSITORY
APP = 'design'
BUILD_RUN = 38828671066
WINDOWS_BUILD_RUN = 38836274669
TAG = 'design-v0.8.0-kio.1'
require = full.require


def build_run(platform):
    return BUILD_RUN if platform == 'macos-arm64' else WINDOWS_BUILD_RUN


def read_qa(archive, platform, collection, lock):
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        require(len(names) == len(set(names)) and len(names) < 2000, 'Invalid QA ZIP directory')
        for info in zipped.infolist():
            collector.full.common.safe_relative(info.filename.rstrip('/'))
            require(info.file_size < 256 * 1024**2 and not info.flag_bits & 1, 'Invalid QA entry')
        require('report.json' in names and 'smoke/report.json' in names and 'bundle-manifest.json' in names,
                'QA reports missing')
        def bounded(name):
            require(zipped.getinfo(name).file_size <= 16 * 1024**2, 'QA JSON too large')
            return json.loads(zipped.read(name))
        report, native = bounded('report.json'), bounded('smoke/report.json')
        bundle = bounded('bundle-manifest.json')
        require(report.get('schema') == 'kio.native-file-qa.v1' and report.get('status') == 'passed'
                and report.get('app') == APP and report.get('platform') == platform
                and report.get('run') == build_run(platform) and report.get('repository') == REPO,
                'QA identity/status mismatch')
        require(report.get('nativeQaPerformed') is True and report.get('executedNativeBinaries') is True
                and report.get('tokenPassedToNative') is False
                and report.get('version') == lock['version']
                and report.get('sourceCommit') == lock['source']['commit'], 'QA execution mismatch')
        require(report.get('artifact') == collection['artifact'] and report.get('headSha') == collection['headSha'],
                'QA tested another artifact')
        require(report.get('checks') == len(native.get('checks', [])) >= 11
                and report.get('commands') == len(native.get('steps', [])) >= 5
                and native.get('status') == 'passed' and native.get('app') == APP
                and all(row.get('passed') is True for row in native['checks'])
                and all(row.get('exitCode') == 0 for row in native['steps'])
                and native.get('cliSha256') == report.get('cliSha256'), 'Native assertions missing or failed')
        portable = next(row for row in collection['files'] if row['path'].endswith('.zip'))
        require(bundle.get('archiveSha256') == portable['sha256'], 'QA portable bytes differ')
        require(hashlib.sha256(zipped.read('bundle-manifest.json')).hexdigest() == report['bundleManifestSha256'],
                'QA inventory differs')
        for row in report['files']:
            require(row['path'].startswith('smoke/') and row['path'] in names, 'QA evidence missing')
            data = zipped.read(row['path'])
            require(len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'],
                    'QA evidence bytes differ')
        return {'report': report, 'native': native, 'bundle': bundle}


def collect_qa(github, run_id, platform, collection, lock, root):
    run = github.json(f'repos/{REPO}/actions/runs/{run_id}')
    require(run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('head_branch') == 'main' and run.get('event') == 'workflow_dispatch'
            and run.get('path') == '.github/workflows/native-file-qa.yml'
            and run.get('repository', {}).get('full_name') == REPO
            and run.get('head_repository', {}).get('full_name') == REPO,
            'QA must be a successful manual KIO main workflow')
    jobs = collector.get_pages(github, f'repos/{REPO}/actions/runs/{run_id}/attempts/{run["run_attempt"]}/jobs', 'jobs')
    require(len(jobs) == 1 and jobs[0].get('conclusion') == 'success', 'QA job incomplete')
    artifacts = collector.get_pages(github, f'repos/{REPO}/actions/runs/{run_id}/artifacts', 'artifacts')
    selected = [row for row in artifacts if row['name'] == f'file-qa-{APP}-{platform}-{build_run(platform)}']
    require(len(selected) == 1, 'Expected exactly one matching QA artifact')
    artifact = selected[0]
    require(not artifact.get('expired') and 0 < artifact['size_in_bytes'] <= 256 * 1024**2,
            'QA artifact unavailable/too large')
    require(collector.utc_time(jobs[0]['started_at']) <= collector.utc_time(artifact['created_at'])
            <= collector.utc_time(artifact['updated_at']) <= collector.utc_time(jobs[0]['completed_at']),
            'QA artifact is from another attempt')
    archive = root / (platform + '-qa.zip')
    github.download(artifact, archive)
    require(archive.stat().st_size == artifact['size_in_bytes']
            and 'sha256:' + full.digest(archive) == artifact['digest'], 'QA archive integrity mismatch')
    evidence = read_qa(archive, platform, collection, lock)
    receipt = root / f'KIO-Design-{lock["version"]}-{platform}-file-qa.json'
    full.write_json(receipt, {'schema': 1, 'buildRun': build_run(platform), 'qaRun': run_id,
                             'qaArtifact': artifact, **evidence})
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mac-qa', type=collector.positive_id, required=True)
    parser.add_argument('--windows-qa', type=collector.positive_id, required=True)
    args = parser.parse_args()
    require(os.environ.get('GITHUB_REPOSITORY') == REPO and os.environ.get('GITHUB_REF') == 'refs/heads/main',
            'Publication is confined to KIO main')
    lock = full.load_lock(APP)
    require(lock['version'] == '0.8.0-kio.1' and lock['source']['commit'] == '11a51d5b665aec8d6e675bd107a8a01514f10d00',
            'Design pin changed; a new reviewed publisher is required')
    github = collector.GitHub()
    with tempfile.TemporaryDirectory(prefix='kio-design-release-') as temporary:
        root = Path(temporary)
        collections, files = {}, []
        for platform in ('macos-arm64', 'windows-x64', 'source'):
            folder = root / platform
            collections[platform] = collector.collect(build_run(platform), APP, platform, folder, github=github)
            files += collector.verify_release(folder / 'release', lock, platform)
        require(len(files) == 14, 'Unexpected Design release inventory')
        for platform, qa_run in [('macos-arm64', args.mac_qa), ('windows-x64', args.windows_qa)]:
            files.append(collect_qa(github, qa_run, platform, collections[platform], lock, root))
        require(full.load_lock(APP) == lock, 'Source lock changed during publication review')
        notes = root / 'notes.md'
        notes.write_text('KIO Design 0.8.0-kio.1\n\n'
            'Complete upstream DesignCraft native workspace, KIO name and supplied icon, original engines and licenses. '
            'Windows x64 MSI/portable ZIP; Apple Silicon macOS DMG/app ZIP; complete matching source with pinned fonts.\n\n'
            'Both OS packages passed the original engine tests and actual native document creation, editable native/IDML '
            'save/reopen, EPUB/PDF/PNG export checks. File-QA receipts are attached. '
            'GUI installation, every menu/format, KIO account gating and direct in-editor Drive saving are not verified by these CLI checks. '
            'Development release: Mac ad-hoc signed, not notarized; no Windows publisher certificate. '
            'Full Adobe InDesign compatibility is not claimed.\n\n'
            f'Mac build: https://github.com/{REPO}/actions/runs/{BUILD_RUN}\n'
            f'Windows and corresponding-source build: https://github.com/{REPO}/actions/runs/{WINDOWS_BUILD_RUN}\n'
            f'Mac QA: https://github.com/{REPO}/actions/runs/{args.mac_qa}\n'
            f'Windows QA: https://github.com/{REPO}/actions/runs/{args.windows_qa}\n', encoding='utf-8')
        existing = subprocess.run(['gh', 'release', 'view', TAG, '--repo', REPO], capture_output=True)
        require(existing.returncode != 0, 'Release already exists; refuse replacement')
        command = ['gh', 'release', 'create', TAG, '--repo', REPO, '--target', collections['source']['headSha'],
                   '--title', 'KIO Design 0.8.0-kio.1', '--notes-file', str(notes), '--draft', '--prerelease']
        subprocess.run(command + [str(file) for file in files], check=True)
        # Measure uploaded bytes before promotion; never replace an existing asset.
        uploaded = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/releases/tags/{TAG}']))
        assets = {row['name']: row for row in uploaded['assets']}
        require(uploaded['draft'] is True and set(assets) == {file.name for file in files}, 'Draft inventory differs')
        for file in files:
            require(assets[file.name]['size'] == file.stat().st_size
                    and assets[file.name].get('digest') == 'sha256:' + full.digest(file), 'Uploaded asset digest differs')
        subprocess.run(['gh', 'release', 'edit', TAG, '--repo', REPO, '--draft=false', '--prerelease'], check=True)
        print('Published verified KIO Design packages and native file-QA receipts: ' + TAG)


if __name__ == '__main__':
    main()
