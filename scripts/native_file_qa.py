#!/usr/bin/env python3
"""Manual file QA of verified native CI packages. No builds, installs or publication.

Use collect with the read-only artifact token, then smoke in a separate tokenless
step. Only the fixed KIO repository and 13 reviewed Craft CLI contracts exist.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import stat
import subprocess
import sys
import unicodedata
import zipfile

import collect_ci_artifact as collector
import full_native as full
import smoke_craft

ROOT = Path(__file__).resolve().parents[1]
APPS = full.IDS
PLATFORMS = {'macos-arm64': {'runner': 'macos-15', 'python': 'python3'},
             'windows-x64': {'runner': 'windows-2022', 'python': 'python'}}
SCHEMA = 'kio.native-file-qa.v1'
MAX_ENTRIES = 20_000
MAX_FILE_BYTES = 1024 ** 3
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MAX_RATIO = 1000
MAX_EVIDENCE_BYTES = 256 * 1024 ** 2
require = full.require


def request(run, app, platform):
    require(type(run) is int and 0 < run < 10 ** 20 and app in APPS and platform in PLATFORMS, 'Invalid allowlisted QA request')
    full.assert_host(platform)


def json_file(path, limit=16 * 1024 ** 2):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit, 'Invalid bounded JSON evidence: ' + path.name)
    return json.loads(path.read_text(encoding='utf-8'))


def save_report(root, report):
    path = root / 'report.json'
    require(not path.is_symlink(), 'Report symlink refused')
    full.write_json(path, report)


def collect(run, app, platform, output):
    request(run, app, platform)
    root = collector.fresh_output(output)
    report = {'schema': SCHEMA, 'repository': collector.REPOSITORY, 'run': run, 'app': app,
              'platform': platform, 'outputRoot': str(root), 'status': 'collecting',
              'publicationPerformed': False, 'installationPerformed': False, 'executedNativeBinaries': False}
    save_report(root, report)
    try:
        # Existing collector checks manual main-branch workflow, exact successful
        # current-attempt job, server metadata/digest, release hashes and full lock.
        result = collector.collect(run, app, platform, root / 'collection')
        require(result['status'] == 'verified', 'CI collection did not verify')
        report.update(status='collected', headSha=result['headSha'], runAttempt=result['runAttempt'],
                      artifact=result['artifact'], job=result['job'], nativeQaPerformed=False)
        save_report(root, report)
        return report
    except Exception as error:
        report.update(status='failed', stage='collection', errorType=type(error).__name__, error=str(error)[:1500])
        save_report(root, report)
        raise


def package_paths(lock, platform):
    if platform == 'macos-arm64':
        base = lock['name'] + '.app'
        return {'root': base, 'app': base + '/Contents/MacOS/' + lock['name'],
                'cli': base + '/Contents/MacOS/kio-' + lock['id'] + '-cli',
                'provenance': base + '/Contents/Resources/OpenSourceLicenses/BUILD-PROVENANCE.json',
                'plist': base + '/Contents/Info.plist'}
    base = lock['name']
    return {'root': base, 'app': base + '/' + lock['name'] + '.exe',
            'cli': base + '/kio-' + lock['id'] + '-cli.exe',
            'provenance': base + '/OpenSourceLicenses/BUILD-PROVENANCE.json'}


def inspect_zip(zipped, paths):
    """Validate the entire central directory before creating any output file."""
    infos = zipped.infolist()
    require(0 < len(infos) <= MAX_ENTRIES, 'Portable ZIP entry count exceeds limit')
    seen, spellings, total, normalized = {}, {}, 0, []
    for info in infos:
        raw = info.filename
        require(raw == info.orig_filename, 'NUL/truncated ZIP filename refused')
        name = raw[:-1] if info.is_dir() else raw
        relative = full.common.safe_relative(name)
        require(relative.parts[0] == paths['root'] and (len(relative.parts) > 1 or info.is_dir()), 'Portable ZIP has another package root')
        key = unicodedata.normalize('NFC', name).casefold()
        require(key not in seen, 'Duplicate/case/Unicode-colliding portable ZIP entry')
        for index in range(1, len(relative.parts) + 1):
            prefix = '/'.join(relative.parts[:index])
            folded = unicodedata.normalize('NFC', prefix).casefold()
            require(folded not in spellings or spellings[folded] == prefix, 'Case/Unicode-colliding ZIP directory spelling')
            spellings[folded] = prefix
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        require(not mode & 0o7000, 'Privileged ZIP permissions refused')
        require(kind in ((0, stat.S_IFDIR) if info.is_dir() else (0, stat.S_IFREG)), 'ZIP symlink or special file refused')
        require(info.is_dir() or not info.external_attr & 0x10, 'ZIP directory flag on a file')
        require(not info.flag_bits & 1 and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Encrypted/unsupported portable ZIP entry')
        require(0 <= info.file_size <= MAX_FILE_BYTES and (not info.is_dir() or info.file_size == 0), 'Portable ZIP file size exceeds limit')
        require(info.file_size <= MAX_RATIO * max(info.compress_size, 1), 'Portable ZIP compression bomb refused')
        total += info.file_size
        require(total <= MAX_TOTAL_BYTES, 'Portable ZIP expansion exceeds total limit')
        seen[key] = info.is_dir()
        normalized.append((info, relative))
    for info, relative in normalized:
        for parent in relative.parents:
            if str(parent) != '.':
                key = unicodedata.normalize('NFC', parent.as_posix()).casefold()
                require(key not in seen or seen[key], 'ZIP file used as an ancestor directory')
    names = {info.filename for info in infos if not info.is_dir()}
    require(all(paths[key] in names for key in paths if key != 'root'), 'Exact native GUI/CLI/package metadata missing')
    return normalized


def extract_portable(archive, destination, lock, platform, provenance):
    require(not destination.exists() and not destination.is_symlink(), 'Bundle extraction must use a new directory')
    paths = package_paths(lock, platform)
    with zipfile.ZipFile(archive) as zipped:
        items = inspect_zip(zipped, paths)
        require(zipped.getinfo(paths['provenance']).file_size <= 16 * 1024 ** 2, 'Bundled provenance exceeds metadata limit')
        inner = json.loads(zipped.read(paths['provenance']))
        require(inner.get('app') == lock['id'] and inner.get('version') == lock['version'] and inner.get('platform') == platform, 'Bundled provenance app/version/platform mismatch')
        require(inner.get('inputs', {}).get('lock') == lock and inner.get('binaries') == provenance.get('binaries'), 'Bundled provenance is not the exact verified native build')
        if 'plist' in paths:
            require(zipped.getinfo(paths['plist']).file_size <= 1024 ** 2, 'Mac plist exceeds metadata limit')
            info = plistlib.loads(zipped.read(paths['plist']))
            require(info.get('CFBundleIdentifier') == lock['bundleId'] and info.get('CFBundleExecutable') == lock['name'] and info.get('CFBundleShortVersionString') == lock['upstreamVersion'], 'Mac bundle identity mismatch')
        destination.mkdir(mode=0o700)
        inventory = []
        for info, relative in items:
            target = destination / relative
            if info.is_dir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            h, copied = hashlib.sha256(), 0
            with zipped.open(info) as source, target.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    require(copied <= info.file_size, 'Portable ZIP actual expansion differs from directory')
                    h.update(chunk)
                    output.write(chunk)
            require(copied == info.file_size, 'Truncated portable ZIP entry')
            target.chmod(0o700 if platform == 'macos-arm64' and (info.external_attr >> 16) & 0o111 else 0o600)
            inventory.append({'path': relative.as_posix(), 'bytes': copied, 'sha256': h.hexdigest()})
    for key in ('app', 'cli'):
        path = destination / paths[key]
        full.common.native_header(path, full.common.TARGETS[platform], key == 'app')
        if platform == 'windows-x64':
            require(full.digest(path) == provenance['binaries'][key]['sha256'] and path.stat().st_size == provenance['binaries'][key]['bytes'], 'Unsigned Windows packaged executable differs from compiled manifest')
    return paths, inventory


def child_environment(folder):
    # Never pass the artifact token, Actions runtime credentials, source-build
    # configuration, user profile or private application settings to a native CLI.
    allowed = {'PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ'}
    env = {key: value for key, value in os.environ.items() if key in allowed}
    folder.mkdir(mode=0o700)
    home = folder / '.home'
    home.mkdir(mode=0o700)
    for name, relative in [('HOME', ''), ('USERPROFILE', ''), ('APPDATA', 'Roaming'), ('LOCALAPPDATA', 'Local'), ('TMP', 'Temp'), ('TEMP', 'Temp'), ('TMPDIR', 'Temp')]:
        path = home / relative
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[name] = str(path)
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', LANG='en_US.UTF-8')
    return env


def run_process(command, environment, cwd, stdout, stderr, timeout):
    """Run only caller-constructed fixed commands; terminate own child tree on timeout."""
    options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    with stdout.open('xb') as output, stderr.open('xb') as errors:
        process = subprocess.Popen(list(map(str, command)), env=environment, cwd=cwd, stdin=subprocess.DEVNULL, stdout=output, stderr=errors, **options)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                taskkill = Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'
                subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=30)
            raise AssertionError('Native QA command timed out')
    require(stdout.stat().st_size <= 4 * 1024 ** 2 and stderr.stat().st_size <= 4 * 1024 ** 2, 'QA process log exceeds bound')
    require(code == 0, 'Native QA command failed with exit ' + str(code) + ': ' + stderr.read_text(encoding='utf-8', errors='replace')[-1500:])
    return stdout.read_text(encoding='utf-8', errors='replace')


def verified_collection(root, run, app, platform, lock):
    collected = root / 'collection'
    require(collected.is_dir() and not collected.is_symlink(), 'Collection directory symlink refused')
    report = json_file(collected / 'collection.json')
    require(report.get('status') == 'verified' and report.get('releaseReviewEligible') is True and report.get('executedNativeBinaries') is False and report.get('publicationPerformed') is False, 'Collection is not an unexecuted verified CI artifact')
    require(report.get('repository') == collector.REPOSITORY and report.get('run') == run and report.get('app') == app and report.get('platform') == platform, 'Collection request identity mismatch')
    require(report.get('job', {}).get('conclusion') == 'success' and report.get('job', {}).get('name') == collector.expected_job(app, platform), 'Collection is not the exact successful native job')
    require(json_file(collected / 'selected-lock.json') == lock, 'Collected source lock differs from current reviewed main')
    outer = collected / 'ci-artifact.zip'
    require(outer.is_file() and not outer.is_symlink() and full.digest(outer) == report.get('archiveSha256') and outer.stat().st_size == report['artifact']['size_in_bytes'], 'Collected outer artifact changed')
    payload = collected / 'release'
    files = collector.verify_release(payload, lock, platform)
    actual = [{'path': 'release/' + p.name, 'bytes': p.stat().st_size, 'sha256': full.digest(p)} for p in files]
    require(sorted(actual, key=lambda row: row['path']) == sorted(report['files'], key=lambda row: row['path']), 'Collected release files changed')
    base = full.artifact_base(lock, platform)
    return payload / (base + '.zip'), json_file(payload / (base + '-provenance.json'))


def smoke(run, app, platform, output):
    request(run, app, platform)
    requested = Path(output).expanduser().absolute()
    require(requested.is_dir() and not requested.is_symlink(), 'Expected the fresh collection output directory')
    root = requested.resolve(strict=True)
    report = json_file(root / 'report.json')
    try:
        require(report.get('schema') == SCHEMA and report.get('outputRoot') == str(root) and report.get('repository') == collector.REPOSITORY and report.get('status') == 'collected', 'Expected a completed collection stage; never reuse QA output')
        require((report.get('run'), report.get('app'), report.get('platform')) == (run, app, platform), 'QA stage request changed')
        lock = full.load_lock(app)
        archive, provenance = verified_collection(root, run, app, platform, lock)
        paths, inventory = extract_portable(archive, root / 'bundle', lock, platform, provenance)
        full.write_json(root / 'bundle-manifest.json', {'archiveSha256': full.digest(archive), 'files': inventory, 'cliPath': paths['cli'], 'guiPath': paths['app']})
        cli = root / 'bundle' / paths['cli']
        output = root / 'smoke'
        require(not output.exists() and not output.is_symlink(), 'Native QA output must be fresh')
        output.mkdir(mode=0o700)
        env = child_environment(root / 'runtime-profile')
        if platform == 'macos-arm64':
            run_process(['/usr/bin/codesign', '--verify', '--strict', '--deep', root / 'bundle' / paths['root']], env, output, root / 'codesign.stdout.txt', root / 'codesign.stderr.txt', 60)
        report.update(status='running', cliPath=paths['cli'], cliSha256=full.digest(cli),
                      sourceCommit=lock['source']['commit'], version=lock['version'],
                      bundleManifestSha256=full.digest(root / 'bundle-manifest.json'), tokenPassedToNative=False)
        save_report(root, report)
        report['executedNativeBinaries'] = True
        raw_version = run_process([cli, '--version'], env, root / 'runtime-profile', root / 'version.stdout.txt', root / 'version.stderr.txt', 60)
        version = smoke_craft.pinned_cli_version(app, raw_version, lock['versionOutputNames']['cli'], lock['upstreamVersion'], lock['source']['commit'])
        require(version is not None, 'Actual native CLI version differs from the pinned source contract')
        helper = 'smoke_word.py' if app == 'word' else 'smoke_office.py' if app in ('grid', 'deck') else 'smoke_craft.py'
        command = [sys.executable, ROOT / 'scripts' / helper]
        if app != 'word':
            command += ['--app', app]
        command += ['--cli', cli, '--output', output]
        run_process(command, env, output, root / 'helper.stdout.txt', root / 'helper.stderr.txt', 1200)
        native = json_file(output / 'report.json')
        require(native.get('status') == 'passed' and native.get('app') == app and native.get('cliSha256') == full.digest(cli), 'Native scenario did not produce a matching actual passing report')
        require(isinstance(native.get('checks'), list) and len(native['checks']) >= 3 and all(c.get('passed') is True for c in native['checks']), 'Native file assertions were not all executed successfully')
        require(isinstance(native.get('steps'), list) and len(native['steps']) >= 3 and all(c.get('exitCode') == 0 for c in native['steps']), 'Native file commands were not all executed successfully')
        evidence = []
        total = 0
        for relative, path in full.common.regular_files(output):
            total += path.stat().st_size
            require(total <= MAX_EVIDENCE_BYTES, 'Generated QA evidence exceeds limit')
            evidence.append({'path': 'smoke/' + relative, 'bytes': path.stat().st_size, 'sha256': full.digest(path)})
        require(full.load_lock(app) == lock, 'Reviewed source lock changed during native QA')
        report.update(status='passed', nativeQaPerformed=True, cliVersion=version,
                      checks=len(native['checks']), commands=len(native['steps']), files=evidence)
        save_report(root, report)
        return report
    except Exception as error:
        report.update(status='failed', stage='native-file-qa', nativeQaPerformed=False, errorType=type(error).__name__, error=str(error)[:1500])
        save_report(root, report)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('collect', 'smoke'))
    parser.add_argument('--run', type=collector.positive_id, required=True)
    parser.add_argument('--app', choices=APPS, required=True)
    parser.add_argument('--platform', choices=tuple(PLATFORMS), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    report = (collect if args.phase == 'collect' else smoke)(args.run, args.app, args.platform, args.output)
    print(json.dumps({k: report[k] for k in ('app', 'platform', 'run', 'status', 'executedNativeBinaries', 'publicationPerformed', 'installationPerformed')}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile, AssertionError, KeyError, TypeError) as error:
        print('Native file QA failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
