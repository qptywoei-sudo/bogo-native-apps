#!/usr/bin/env python3
"""Collect one successful native CI artifact for manual release review.

The enclosing workflow may still be queued/running. Only the selected job must
have succeeded in the current run attempt. The outer GitHub artifact ZIP is
validated before extraction; nested release archives are never extracted or
executed. This tool does not create or update a public release.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import full_native as full
import launcher_native as launcher

REPOSITORY = 'qptywoei777-rgb/kio-native-apps'
APPS = (*full.IDS, 'launcher')
PLATFORMS = (*full.common.TARGETS, 'source')
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024 + 64 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024 * 1024
require = full.require


def positive_id(value):
    require(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}', value), 'Expected a positive numeric run ID')
    return int(value)


def integer(value):
    return type(value) is int and value > 0


def utc_time(value):
    require(isinstance(value, str) and value.endswith('Z'), 'Missing UTC metadata timestamp')
    parsed = datetime.fromisoformat(value[:-1] + '+00:00')
    require(parsed.utcoffset().total_seconds() == 0, 'Expected UTC metadata timestamp')
    return parsed


class GitHub:
    """Only fixed-host, fixed-repository GETs; credentials stay in gh's environment."""
    def __init__(self):
        self.executable = shutil.which('gh')
        require(self.executable, 'GitHub CLI gh is required')
        self.environment = dict(os.environ, GH_REPO=REPOSITORY, GH_PROMPT_DISABLED='1', GH_PAGER='cat')

    def command(self, endpoint):
        prefix = 'repos/' + REPOSITORY + '/actions/'
        require(endpoint.startswith(prefix), 'GitHub endpoint outside the reviewed repository')
        route = endpoint[len(prefix):]
        require(re.fullmatch(r'(?:runs/[1-9][0-9]*(?:(?:/attempts/[1-9][0-9]*/jobs|/artifacts)\?per_page=100&page=[1-9][0-9]*)?|workflows/[1-9][0-9]*|artifacts/[1-9][0-9]*(?:/zip)?)', route), 'GitHub endpoint is not an allowlisted read operation')
        return [self.executable, 'api', '--hostname', 'github.com', '--method', 'GET',
                '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: 2022-11-28', endpoint]

    def json(self, endpoint):
        result = subprocess.run(self.command(endpoint), env=self.environment, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        require(len(result.stdout) <= MAX_METADATA_BYTES, 'GitHub metadata exceeds the collection limit')
        return json.loads(result.stdout)

    def download(self, artifact, destination):
        # gh run download would extract the ZIP before we could reject malicious
        # entries. Download the exact numeric artifact's raw ZIP through gh api.
        endpoint = f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'
        with destination.open('xb') as output:
            subprocess.run(self.command(endpoint), env=self.environment, check=True,
                           stdout=output, stderr=subprocess.PIPE, timeout=3600)


def get_pages(github, endpoint, field):
    rows, count, page = [], None, 1
    while count is None or len(rows) < count:
        value = github.json(endpoint + f'?per_page=100&page={page}')
        require(isinstance(value, dict) and type(value.get('total_count')) is int and isinstance(value.get(field), list), 'Invalid paginated GitHub metadata')
        require(0 <= value['total_count'] <= 1000, 'Too many GitHub metadata rows')
        if count is None:
            count = value['total_count']
        require(count == value['total_count'] and (value[field] or count == 0), 'GitHub metadata changed or pagination stopped early')
        rows.extend(value[field])
        require(len(rows) <= count and all(isinstance(row, dict) for row in rows), 'Invalid GitHub metadata page')
        page += 1
    ids = [row.get('id') for row in rows]
    require(all(integer(value) for value in ids) and len(ids) == len(set(ids)), 'Duplicate/invalid GitHub metadata IDs')
    return rows


def workflow_path(app):
    return '.github/workflows/full-native-' + ('launcher' if app == 'launcher' else 'apps') + '.yml'


def validate_run(run, run_id, app):
    require(isinstance(run, dict) and run.get('id') == run_id, 'Run ID does not match the explicit request')
    require(run.get('event') == 'workflow_dispatch' and run.get('head_branch') == 'main', 'Only a manual main-branch native build is eligible')
    for field in ('repository', 'head_repository'):
        row = run.get(field)
        require(isinstance(row, dict) and row.get('full_name') == REPOSITORY and integer(row.get('id')), 'Run/head repository differs from the KIO allowlist')
    require(run['repository']['id'] == run['head_repository']['id'], 'Forked workflow heads are not eligible')
    require(isinstance(run.get('head_sha'), str) and re.fullmatch(r'[a-f0-9]{40}', run['head_sha']), 'Invalid run commit')
    require(integer(run.get('run_attempt')) and integer(run.get('workflow_id')), 'Missing run attempt/workflow identity')
    require(run.get('path') == workflow_path(app), 'Wrong native workflow for the selected app')
    return run


def expected_job(app, platform):
    if platform == 'source':
        return 'full-source' if app == 'launcher' else f'full-source ({app})'
    runner, target, python = ('macos-15', 'aarch64-apple-darwin', 'python3') if platform == 'macos-arm64' else ('windows-2022', 'x86_64-pc-windows-msvc', 'python')
    values = [runner, platform, target, python]
    if app != 'launcher':
        values.insert(0, app)
    return 'native (' + ', '.join(values) + ')'


def select_job(jobs, run, app, platform):
    selected = [job for job in jobs if job.get('name') == expected_job(app, platform)]
    require(len(selected) == 1, 'Expected exactly one app/platform job in the current attempt')
    job = selected[0]
    require(job.get('run_id') == run['id'] and job.get('run_attempt') == run['run_attempt'] and job.get('head_sha') == run['head_sha'], 'Job belongs to a different run attempt or commit')
    require(job.get('status') == 'completed' and job.get('conclusion') == 'success', 'Selected app/platform job has not succeeded')
    require(utc_time(job.get('started_at')) <= utc_time(job.get('completed_at')), 'Invalid completed job timestamps')
    return job


def select_artifact(artifacts, run, job, app, platform, now):
    selected = [item for item in artifacts if item.get('name') == f'{app}-{platform}']
    require(len(selected) == 1, 'Expected exactly one artifact with the exact app/platform name')
    artifact = selected[0]
    validate_artifact(artifact, run, job, app, platform, now)
    return artifact


def validate_artifact(artifact, run, job, app, platform, now):
    require(isinstance(artifact, dict) and integer(artifact.get('id')) and artifact.get('name') == f'{app}-{platform}', 'Invalid artifact identity')
    require(artifact.get('expired') is False and utc_time(artifact.get('expires_at')) > now, 'CI artifact is expired')
    require(integer(artifact.get('size_in_bytes')) and artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES, 'CI artifact size is invalid or exceeds the limit')
    binding = artifact.get('workflow_run')
    require(isinstance(binding, dict) and binding.get('id') == run['id'] and binding.get('head_branch') == 'main' and binding.get('head_sha') == run['head_sha'], 'Artifact belongs to a different run or commit')
    require(binding.get('repository_id') == run['repository']['id'] and binding.get('head_repository_id') == run['head_repository']['id'], 'Artifact repository identity mismatch')
    # REST artifacts do not expose run_attempt/job_id. Bind the upload to this
    # successful current-attempt job by its server-side creation/update window.
    require(utc_time(job['started_at']) <= utc_time(artifact.get('created_at')) <= utc_time(artifact.get('updated_at')) <= utc_time(job['completed_at']), 'Artifact upload is outside the selected successful job window')
    digest = artifact.get('digest')
    require(digest is None or (isinstance(digest, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', digest)), 'Invalid GitHub artifact digest')


def expected_files(lock, platform):
    base = full.artifact_base(lock, platform)
    suffixes = ['.zip', '-provenance.json', '-manifest.json', '-SHA256SUMS.txt']
    if platform != 'source':
        suffixes.append('.dmg' if platform == 'macos-arm64' else '.msi')
    return {base + suffix for suffix in suffixes}


def extract_artifact(archive, destination, expected):
    require(not destination.exists() and not destination.is_symlink(), 'Artifact extraction directory must be new')
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        require(len(infos) == len(expected), 'Unexpected artifact ZIP entry count')
        seen, total = set(), 0
        for item in infos:
            name = item.filename
            require(item.orig_filename == name and full.common.safe_relative(name).name == name and name in expected, 'Unexpected or unsafe artifact ZIP path')
            require(name.casefold() not in seen, 'Duplicate/case-colliding artifact ZIP entry')
            seen.add(name.casefold())
            mode = item.external_attr >> 16
            require(not item.is_dir() and not (item.external_attr & 0x10) and stat.S_IFMT(mode) in (0, stat.S_IFREG), 'Artifact ZIP link or special file refused')
            require(not (item.flag_bits & 1) and item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported/encrypted artifact ZIP entry')
            limit = MAX_FILE_BYTES if name.endswith(('.zip', '.dmg', '.msi')) else MAX_METADATA_BYTES
            require(0 < item.file_size <= limit, 'Artifact ZIP entry exceeds its size limit')
            total += item.file_size
            require(total <= MAX_ARCHIVE_BYTES, 'Artifact ZIP expansion exceeds the limit')
        require({item.filename for item in infos} == expected, 'Artifact ZIP release-file allowlist mismatch')
        destination.mkdir(mode=0o700)
        for item in infos:
            # Never use extract()/extractall(); the entire outer ZIP was checked
            # above, and exclusive writes cannot overwrite an existing file.
            with zipped.open(item) as source, (destination / item.filename).open('xb') as target:
                copied = 0
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    require(copied <= item.file_size, 'Artifact ZIP expansion differs from its directory record')
                    target.write(chunk)
                require(copied == item.file_size, 'Truncated artifact ZIP entry')


def load_lock(app):
    return launcher.load_lock() if app == 'launcher' else full.load_lock(app)


def verify_release(directory, lock, platform):
    # Both original orchestrators use this same exact full.verify implementation.
    # load_lock above retains each orchestrator's complete protected-input checks.
    files = full.verify(directory, lock, platform)
    provenance = json.loads((directory / (full.artifact_base(lock, platform) + '-provenance.json')).read_text(encoding='utf-8'))
    require(isinstance(provenance, dict) and provenance.get('schema') == 1 and provenance.get('app') == lock['id'], 'Invalid release provenance identity')
    inputs = provenance.get('inputs')
    require(isinstance(inputs, dict) and inputs.get('lock') == lock, 'Release provenance differs from the exact reviewed local lock')
    if platform != 'source':
        require(provenance.get('version') == lock['version'] and provenance.get('platform') == platform, 'Native provenance version/platform mismatch')
    return files


def fresh_output(value):
    requested = Path(value).expanduser().absolute()
    require(not requested.exists() and not requested.is_symlink(), 'Output must be a fresh directory; existing paths are never reused')
    # Anchor the user's chosen parent to its canonical directory (macOS /tmp
    # itself is a system symlink). The output and every extracted entry are new.
    parent = requested.parent.resolve(strict=True)
    require(parent.is_dir(), 'Output parent directory must already exist')
    destination = parent / requested.name
    require(not destination.exists() and not destination.is_symlink(), 'Output must be a fresh directory')
    destination.mkdir(mode=0o700)
    return destination


def collect(run_id, app, platform, output, github=None, now=None):
    require(type(run_id) is int and run_id > 0 and app in APPS and platform in PLATFORMS, 'Invalid explicit collection request')
    destination = fresh_output(output)
    report_path = destination / 'collection.json'
    report = {'schema': 'kio.ci-artifact-collection.v1', 'repository': REPOSITORY, 'run': run_id,
              'app': app, 'platform': platform, 'status': 'checking', 'releaseReviewEligible': False,
              'publicationPerformed': False, 'executedNativeBinaries': False}
    full.write_json(report_path, report)
    try:
        lock = load_lock(app)
        github = github or GitHub()
        check_time = now or datetime.now(timezone.utc)
        endpoint = f'repos/{REPOSITORY}/actions/runs/{run_id}'
        run = validate_run(github.json(endpoint), run_id, app)
        workflow = github.json(f'repos/{REPOSITORY}/actions/workflows/{run["workflow_id"]}')
        require(isinstance(workflow, dict) and workflow.get('id') == run['workflow_id'] and workflow.get('path') == workflow_path(app) and workflow.get('state') == 'active', 'Native workflow identity is not active/allowlisted')
        jobs = get_pages(github, endpoint + f'/attempts/{run["run_attempt"]}/jobs', 'jobs')
        job = select_job(jobs, run, app, platform)
        artifacts = get_pages(github, endpoint + '/artifacts', 'artifacts')
        artifact = select_artifact(artifacts, run, job, app, platform, check_time)
        report.update(headSha=run['head_sha'], runAttempt=run['run_attempt'], workflow=workflow_path(app),
                      job={'id': job['id'], 'name': job['name'], 'conclusion': job['conclusion']},
                      artifact={key: artifact.get(key) for key in ('id', 'name', 'size_in_bytes', 'digest', 'created_at', 'updated_at', 'expires_at')},
                      status='downloading')
        full.write_json(report_path, report)
        archive = destination / 'ci-artifact.zip'
        github.download(artifact, archive)
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size == artifact['size_in_bytes'], 'Downloaded CI ZIP byte count differs from GitHub metadata')
        archive_digest = full.digest(archive)
        if artifact.get('digest') is not None:
            require(artifact['digest'] == 'sha256:' + archive_digest, 'Downloaded CI ZIP digest differs from GitHub metadata')
        # Fail closed if a rerun started or the selected artifact expired/changed
        # during the download. No new artifact is selected or downloaded on retry.
        current_run = validate_run(github.json(endpoint), run_id, app)
        require(all(current_run[key] == run[key] for key in ('head_sha', 'run_attempt', 'workflow_id')), 'CI run attempt changed while collecting')
        current = github.json(f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}')
        validate_artifact(current, run, job, app, platform, datetime.now(timezone.utc) if now is None else now)
        require(current == artifact, 'CI artifact metadata changed while collecting')
        payload = destination / 'release'
        extract_artifact(archive, payload, expected_files(lock, platform))
        files = verify_release(payload, lock, platform)
        require(load_lock(app) == lock, 'Reviewed local lock changed while collecting')
        full.write_json(destination / 'selected-lock.json', lock)
        report.update(status='verified', releaseReviewEligible=True, archiveSha256=archive_digest,
                      verification='existing full_native.verify with the exact app lock plus complete provenance lock equality',
                      files=[{'path': 'release/' + path.name, 'bytes': path.stat().st_size, 'sha256': full.digest(path)} for path in files])
        full.write_json(report_path, report)
        return report
    except Exception as error:
        report.update(status='blocked', releaseReviewEligible=False, errorType=type(error).__name__, error=str(error)[:1000])
        full.write_json(report_path, report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=positive_id, required=True)
    parser.add_argument('--app', choices=APPS, required=True)
    parser.add_argument('--platform', choices=PLATFORMS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.run, args.app, args.platform, args.output)
    print(json.dumps({'status': report['status'], 'artifact': report['artifact']['name'], 'output': str(args.output), 'publicationPerformed': False}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile, KeyError, TypeError) as error:
        print('CI artifact collection blocked: ' + str(error), file=sys.stderr)
        sys.exit(1)
