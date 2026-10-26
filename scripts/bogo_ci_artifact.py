#!/usr/bin/env python3
"""Authenticate existing Bogo Windows artifacts for a separate, manual smoke run.

No compilation, publication, extracted scripts or native binaries run here.
The outer artifact is authenticated before extracting only five release files.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import bogo_native as bogo
import collect_ci_artifact as reviewed

REPOSITORY = 'qptywoei-sudo/bogo-native-apps'
BRANCH = 'codex/bogo-native-rebrand-20261026'
WORKFLOW = 'Bogo Windows artifact acceptance (manual)'
BUILD_WORKFLOW = '.github/workflows/bogo-native-apps.yml'
OLD_SMOKE_STEP = 'Install, upgrade, inspect PE icons and launch installed and portable apps'
UPLOAD_STEP = 'Run actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f'
API = 'https://api.github.com/repos/' + REPOSITORY + '/actions/'
APPS = tuple(bogo.NAMES)
MAX_ARCHIVE = reviewed.MAX_ARCHIVE_BYTES
MAX_METADATA = reviewed.MAX_METADATA_BYTES
MAX_MEMBER = reviewed.MAX_FILE_BYTES
MAX_ENTRIES = 20000
MAX_EXPANDED = 12 * 1024 * 1024 * 1024
HARNESS_FILES = ('.github/workflows/bogo-windows-acceptance.yml', 'scripts/bogo_ci_artifact.py', 'scripts/smoke_bogo_windows.py', 'scripts/bogo_runtime_icons.py', 'scripts/bogo_msi_art.py',
    'tools/runtime-icon-reference/Cargo.toml', 'tools/runtime-icon-reference/Cargo.lock', 'tools/runtime-icon-reference/src/main.rs', 'tools/runtime-icon-reference/reference-contract.json') + tuple('tools/runtime-icon-reference/application-locks/' + app + '.Cargo.lock' for app in APPS)

class Refused(ValueError):
    """Only fixed verifier messages may enter a public diagnostic receipt."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def diagnostic(error):
    return str(error)[:500] if isinstance(error, Refused) else type(error).__name__


def sha256(path):
    return bogo.digest(path)


def exact_sha(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{40}', value), 'Expected an exact lowercase 40-character commit SHA')
    return value


def matrix(app):
    require(app in (*APPS, 'all'), 'Unknown Bogo application')
    return {'include': [{'app': item} for item in (APPS if app == 'all' else (app,))]}


def no_links(path):
    for current in (path, *path.parents):
        if current.exists() or current.is_symlink():
            metadata = current.lstat()
            require(not current.is_symlink() and not (getattr(metadata, 'st_file_attributes', 0) & 0x400), 'Runner/output ancestry contains a link or reparse point')


def runner_context():
    require(sys.platform == 'win32' and os.environ.get('RUNNER_OS') == 'Windows' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and os.environ.get('GITHUB_ACTIONS') == 'true', 'Artifact acceptance requires an ephemeral GitHub-hosted Windows runner')
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and os.environ.get('GITHUB_WORKFLOW') == WORKFLOW and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH, 'Artifact acceptance requires the exact manual repository/workflow/ref')
    harness = exact_sha(os.environ.get('GITHUB_SHA'))
    require(os.environ.get('GITHUB_WORKFLOW_REF') == REPOSITORY + '/.github/workflows/bogo-windows-acceptance.yml@refs/heads/' + BRANCH and os.environ.get('GITHUB_WORKFLOW_SHA') == harness, 'Workflow definition differs from the exact acceptance harness')
    reviewed.positive_id(os.environ.get('GITHUB_RUN_ID'))
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=bogo.ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
    require(result.returncode == 0 and result.stdout.strip() == harness, 'Checkout differs from the exact acceptance harness SHA')
    require(Path(os.environ.get('GITHUB_WORKSPACE', '')).resolve() == bogo.ROOT.resolve(), 'Acceptance checkout/workspace differs')
    return harness


def runner_path(value, fresh=False):
    base = Path(os.environ.get('RUNNER_TEMP', ''))
    path = Path(value)
    require(base.is_absolute() and base.is_dir() and path.is_absolute() and '..' not in path.parts, 'Use an absolute owned path inside RUNNER_TEMP')
    no_links(base)
    no_links(path)
    base, path = base.resolve(), path.resolve()
    require(path != base and path.is_relative_to(base), 'Acceptance output is outside RUNNER_TEMP')
    if fresh:
        require(not path.exists(), 'Acceptance output must be fresh; existing paths are never reused')
    return path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Fixed API GETs only; signed blob GETs receive no GitHub credentials."""
    def __init__(self):
        self.token = os.environ.get('GH_TOKEN', '')
        require(self.token and not any(c in self.token for c in '\r\n'), 'Job-scoped GH_TOKEN is required')
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, endpoint):
        prefix = 'repos/' + REPOSITORY + '/actions/'
        require(endpoint.startswith(prefix), 'GitHub API repository is not allowlisted')
        route = endpoint[len(prefix):]
        require(re.fullmatch(r'(?:runs/[1-9][0-9]*(?:(?:/attempts/[1-9][0-9]*/jobs|/artifacts)\?per_page=100&page=[1-9][0-9]*)?|workflows/[1-9][0-9]*|artifacts/[1-9][0-9]*(?:/zip)?)', route), 'GitHub API operation is not an allowlisted read')
        return urllib.request.Request(API + route, headers={'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Authorization': 'Bearer ' + self.token, 'User-Agent': 'Bogo-Windows-Acceptance'})

    def open(self, request):
        try:
            return self.opener.open(request, timeout=120)
        except urllib.error.HTTPError as error:
            if error.code == 302:
                return error
            raise Refused('GitHub artifact request failed (HTTP ' + str(error.code) + ')') from None
        except (urllib.error.URLError, OSError):
            # Never retain an exception containing a signed URL or a header.
            raise Refused('GitHub artifact request could not be completed') from None

    def json(self, endpoint):
        with self.open(self.request(endpoint)) as response:
            require(response.status == 200, 'GitHub API metadata unexpectedly redirected')
            data = response.read(MAX_METADATA + 1)
        require(len(data) <= MAX_METADATA, 'GitHub metadata exceeds its bound')
        try:
            return json.loads(data)
        except (UnicodeError, ValueError):
            raise Refused('GitHub API returned invalid JSON metadata') from None

    def download(self, artifact, destination):
        endpoint = f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'
        response = self.open(self.request(endpoint))
        if response.status == 302:
            location = response.headers.get('Location', '')
            response.close()
            parsed = urllib.parse.urlsplit(location)
            host = parsed.hostname or ''
            allowed = re.fullmatch(r'productionresults[a-z0-9-]*\.blob\.core\.windows\.net', host) or host == 'pipelines.actions.githubusercontent.com'
            require(parsed.scheme == 'https' and allowed and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment, 'Artifact redirect host is not allowlisted')
            # Deliberately create a new request without Authorization or cookies.
            response = self.open(urllib.request.Request(location, headers={'User-Agent': 'Bogo-Windows-Acceptance'}))
        with response:
            require(response.status == 200, 'Artifact download did not return a binary response')
            length = response.headers.get('Content-Length')
            require(length is None or (length.isdigit() and int(length) == artifact['size_in_bytes']), 'Artifact HTTP byte count differs from GitHub metadata')
            copied = 0
            with Path(destination).open('xb') as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    require(copied <= artifact['size_in_bytes'] and copied <= MAX_ARCHIVE, 'Artifact download exceeds its authenticated bound')
                    output.write(chunk)
            require(copied == artifact['size_in_bytes'], 'Artifact download was truncated')


def validate_run(run, run_id, expected_sha):
    require(isinstance(run, dict) and run.get('id') == run_id and run.get('head_sha') == exact_sha(expected_sha), 'Requested build run or commit differs')
    require(run.get('event') == 'workflow_dispatch' and run.get('head_branch') == BRANCH and run.get('path') == BUILD_WORKFLOW, 'Build is not the exact manual Bogo workflow/ref')
    for key in ('repository', 'head_repository'):
        row = run.get(key)
        require(isinstance(row, dict) and row.get('full_name') == REPOSITORY and reviewed.integer(row.get('id')), 'Build repository/head is not allowlisted')
    require(run['repository']['id'] == run['head_repository']['id'] and reviewed.integer(run.get('workflow_id')) and reviewed.integer(run.get('run_attempt')), 'Build workflow/attempt/repository binding is invalid')
    return run


def mandatory_build_steps(app):
    return (
        'Verify owner-derived icons and all source overlay identities on the target OS',
        'Run python scripts/bogo_native.py prepare --app ' + app,
        'Run python scripts/bogo_native.py build --app ' + app + ' --platform windows-x64',
        'Run python scripts/bogo_native.py package --app ' + app + ' --platform windows-x64',
        'Run python scripts/bogo_native.py verify --app ' + app + ' --platform windows-x64 --directory dist/' + app + '-windows-x64',
        UPLOAD_STEP,
    )


def job_eligibility(job, app):
    """Build inputs may be reused; an old smoke failure is never acceptance proof.

    The build command includes its native/core checks. All required source,
    prepare/build/package/verify/upload steps must have succeeded. The only
    permitted failure is the old complete smoke step, which the new workflow
    repeats in full. No error-text allowlist or failed check is treated as a pass.
    """
    require(job.get('status') == 'completed' and job.get('conclusion') in ('success', 'failure'), 'Selected native Windows job is unfinished, cancelled or timed out')
    steps = job.get('steps')
    require(isinstance(steps, list) and 0 < len(steps) <= 128 and all(isinstance(step, dict) for step in steps), 'Native job step evidence is missing or exceeds its bound')
    names, numbers = {}, set()
    for step in steps:
        name, number = step.get('name'), step.get('number')
        require(isinstance(name, str) and 0 < len(name) <= 300 and name not in names and reviewed.integer(number) and number not in numbers, 'Duplicate/invalid native step identity')
        require(step.get('status') == 'completed' and step.get('conclusion') in ('success', 'failure'), 'Native job contains an unfinished, skipped, cancelled or timed-out step')
        names[name] = step
        numbers.add(number)
    mandatory = mandatory_build_steps(app)
    require(all(name in names and names[name].get('conclusion') == 'success' for name in mandatory), 'Mandatory source/build/core/package/verify/upload step did not succeed')
    require(OLD_SMOKE_STEP in names, 'Exact prior complete smoke step is missing')
    smoke = names[OLD_SMOKE_STEP]
    order = [names[name]['number'] for name in mandatory[:-1]] + [smoke['number'], names[UPLOAD_STEP]['number']]
    require(order == sorted(order) and len(order) == len(set(order)), 'Build/verification/smoke/upload sequence differs')
    failed = [step for step in steps if step['conclusion'] == 'failure']
    old_failed = job['conclusion'] == 'failure'
    if old_failed:
        require(len(failed) == 1 and failed[0]['name'] == OLD_SMOKE_STEP, 'Only the prior whole-smoke failure can be reverified')
    else:
        require(not failed and smoke.get('conclusion') == 'success', 'Successful native job contains contradictory failure evidence')
    fields = ('number', 'name', 'status', 'conclusion', 'started_at', 'completed_at')
    return {'eligibleForFreshAcceptance': True, 'freshFullAcceptanceRequired': True,
            'priorJobConclusion': job['conclusion'], 'priorNativeAcceptancePassed': not old_failed,
            'reason': 'old harness failed; fresh full acceptance required' if old_failed else 'prior native job succeeded; fresh full acceptance still required',
            'mandatoryBuildSteps': [{key: names[name].get(key) for key in fields} for name in mandatory],
            'failedSteps': [{key: step.get(key) for key in fields} for step in failed]}


def select_job(jobs, run, app):
    selected = [job for job in jobs if job.get('name') == app + ' on windows-x64 with installer acceptance']
    require(len(selected) == 1, 'Exactly one selected native Windows job is required')
    job = selected[0]
    require(job.get('run_id') == run['id'] and job.get('run_attempt') == run['run_attempt'] and job.get('head_sha') == run['head_sha'], 'Native job belongs to another run attempt/commit')
    job_eligibility(job, app)
    require(job.get('labels') == ['windows-2022'] and job.get('runner_group_name') == 'GitHub Actions', 'Built artifact did not come from the reviewed hosted Windows target')
    require(reviewed.utc_time(job.get('started_at')) <= reviewed.utc_time(job.get('completed_at')), 'Native job timestamps are invalid')
    return job


def validate_artifact(artifact, run, job, app, now):
    require(isinstance(artifact, dict) and reviewed.integer(artifact.get('id')) and artifact.get('name') == 'bogo-' + app + '-windows-x64', 'Artifact name/identity differs')
    require(artifact.get('expired') is False and reviewed.utc_time(artifact.get('expires_at')) > now, 'Artifact is expired')
    require(reviewed.integer(artifact.get('size_in_bytes')) and artifact['size_in_bytes'] <= MAX_ARCHIVE and isinstance(artifact.get('digest'), str) and re.fullmatch(r'sha256:[a-f0-9]{64}', artifact['digest']), 'Artifact API ZIP digest/size is missing or invalid')
    binding = artifact.get('workflow_run')
    require(isinstance(binding, dict) and binding.get('id') == run['id'] and binding.get('head_branch') == BRANCH and binding.get('head_sha') == run['head_sha'] and binding.get('repository_id') == run['repository']['id'] and binding.get('head_repository_id') == run['head_repository']['id'], 'Artifact run/head/repository binding differs')
    require(reviewed.utc_time(job['started_at']) <= reviewed.utc_time(artifact.get('created_at')) <= reviewed.utc_time(artifact.get('updated_at')) <= reviewed.utc_time(job['completed_at']), 'Artifact upload is outside the eligible current-attempt job window')
    expected = API + 'artifacts/' + str(artifact['id'])
    require(artifact.get('url') == expected and artifact.get('archive_download_url') == expected + '/zip', 'Artifact API URLs differ from the exact repository')
    return artifact


def extract_candidates(archive, destination, app, expected):
    require(not destination.exists() and not destination.is_symlink(), 'Candidate extraction directory must be fresh')
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        require(0 < len(entries) <= MAX_ENTRIES, 'Artifact ZIP entry count exceeds its bound')
        seen, selected, roots, total = set(), {}, set(), 0
        for item in entries:
            name = item.filename
            raw = name.rstrip('/').split('/')
            require(name == item.orig_filename and not name.startswith(('/', '\\')) and '\\' not in name and len(name) <= 1000 and all(part not in ('', '.', '..') and not re.search(r'[<>:"|?*\x00-\x1f]', part) and not part.endswith((' ', '.')) for part in raw), 'Unsafe artifact ZIP path')
            require(name.rstrip('/').casefold() not in seen, 'Duplicate/case-colliding artifact ZIP path')
            seen.add(name.rstrip('/').casefold())
            mode = stat.S_IFMT(item.external_attr >> 16)
            require(mode in (0, stat.S_IFREG, stat.S_IFDIR) and not (item.external_attr & 0x400) and not (item.flag_bits & 1) and item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Artifact ZIP link/reparse/special/encrypted entry refused')
            require(item.is_dir() == (mode == stat.S_IFDIR or name.endswith('/')) and 0 <= item.file_size <= MAX_MEMBER, 'Artifact ZIP entry type/size is invalid')
            total += item.file_size
            require(total <= MAX_EXPANDED, 'Artifact ZIP total expansion exceeds its bound')
            if item.is_dir():
                continue
            parts = PurePosixPath(name).parts
            if len(parts) >= 3 and parts[-3:-1] == ('dist', app + '-windows-x64'):
                require(parts[-1] in expected and parts[-1] not in selected, 'Unexpected/duplicate selected native candidate')
                require(0 < item.file_size <= (MAX_MEMBER if parts[-1].endswith(('.msi', '.zip')) else MAX_METADATA), 'Selected native file exceeds its bound')
                selected[parts[-1]] = item
                roots.add(parts[:-1])
        require(set(selected) == expected and len(roots) == 1, 'Artifact must contain one exact five-file native directory under dist/app-windows-x64')
        destination.mkdir(mode=0o700)
        for name, item in selected.items():
            with zipped.open(item) as source, (destination / name).open('xb') as output:
                copied = 0
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    copied += len(chunk)
                    require(copied <= item.file_size, 'Selected ZIP entry exceeds its declared size')
                    output.write(chunk)
                require(copied == item.file_size, 'Selected ZIP entry was truncated')


def verify_provenance(folder, lock):
    files = reviewed.verify_release(folder, lock, 'windows-x64')
    value = json.loads((folder / (bogo.full.artifact_base(lock, 'windows-x64') + '-provenance.json')).read_text(encoding='utf-8'))
    inputs = value['inputs']
    overlay = lock['bogoOverlay']
    require(inputs.get('sourceTreeSha256') == overlay['sourceTreeSha256'] and inputs.get('bogoOverlay') == {'path': overlay['patch'], 'sha256': overlay['patchSha256']}, 'Authenticated source tree/overlay differs from the current selected app')
    binary = value.get('binaries', {}).get('app', {})
    require(isinstance(binary.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', binary['sha256']) and reviewed.integer(binary.get('bytes')), 'Authenticated built executable identity is missing')
    return files, value


def collect(run_id, expected_sha, app, output, github=None, now=None):
    require(type(run_id) is int and run_id > 0 and app in APPS, 'Invalid explicit artifact request')
    exact_sha(expected_sha)
    harness = runner_context()
    destination = runner_path(output, fresh=True)
    destination.mkdir(parents=True, mode=0o700)
    report = {'schema': 'bogo.windows-artifact-input.v1', 'repository': REPOSITORY, 'app': app, 'platform': 'windows-x64', 'builtSha': expected_sha, 'harnessSha': harness, 'harnessRunId': os.environ.get('GITHUB_RUN_ID'), 'status': 'checking', 'phase': 'source-lock', 'nativeExecutionPerformed': False, 'publicationPerformed': False}
    report_path = destination / 'authenticated-build.json'
    bogo.full.write_json(report_path, report)
    try:
        lock = bogo.load_lock(app)
        github = github or GitHub()
        check_time = now or datetime.now(timezone.utc)
        endpoint = f'repos/{REPOSITORY}/actions/runs/{run_id}'
        report['phase'] = 'build-run-and-workflow'
        run = validate_run(github.json(endpoint), run_id, expected_sha)
        workflow = github.json(f'repos/{REPOSITORY}/actions/workflows/{run["workflow_id"]}')
        require(workflow.get('id') == run['workflow_id'] and workflow.get('path') == BUILD_WORKFLOW and workflow.get('state') == 'active', 'Build workflow identity is not active/allowlisted')
        report['phase'] = 'eligible-completed-native-job'
        jobs = reviewed.get_pages(github, endpoint + f'/attempts/{run["run_attempt"]}/jobs', 'jobs')
        job = select_job(jobs, run, app)
        report['phase'] = 'artifact-identity'
        artifacts = reviewed.get_pages(github, endpoint + '/artifacts', 'artifacts')
        selected = [item for item in artifacts if item.get('name') == 'bogo-' + app + '-windows-x64' and item.get('expired') is False]
        require(len(selected) == 1, 'Exactly one named build artifact is required')
        artifact = validate_artifact(selected[0], run, job, app, check_time)
        archive = destination / 'authenticated-artifact.zip'
        report['phase'] = 'download-and-api-readback'
        github.download(artifact, archive)
        require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size == artifact['size_in_bytes'] and artifact['digest'] == 'sha256:' + sha256(archive), 'Downloaded ZIP differs from the actual API size/digest')
        current_run = validate_run(github.json(endpoint), run_id, expected_sha)
        require(all(current_run[key] == run[key] for key in ('head_sha', 'run_attempt', 'workflow_id')), 'Build run attempt changed during download')
        current = github.json(f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}')
        validate_artifact(current, run, job, app, now or datetime.now(timezone.utc))
        require(current == artifact, 'Artifact API metadata changed during download')
        candidate = destination / 'candidate'
        report['phase'] = 'bounded-native-files-only-extraction'
        extract_candidates(archive, candidate, app, reviewed.expected_files(lock, 'windows-x64'))
        report['phase'] = 'manifest-checksums-and-native-provenance'
        files, provenance = verify_provenance(candidate, lock)
        require(bogo.load_lock(app) == lock and runner_context() == harness, 'Selected source or harness changed during artifact verification')
        harness_files = {}
        for relative in HARNESS_FILES:
            path = bogo.ROOT / relative
            require(path.is_file() and not path.is_symlink(), 'Required current acceptance harness file is missing')
            harness_files[relative] = sha256(path)
        report.update(status='verified', phase='verified-inputs-only', buildRunId=run_id, buildRunAttempt=run['run_attempt'], buildWorkflow=BUILD_WORKFLOW, job={'id': job['id'], 'name': job['name'], 'status': job['status'], 'conclusion': job['conclusion'], 'eligibility': job_eligibility(job, app)}, artifact={key: artifact[key] for key in ('id', 'name', 'size_in_bytes', 'digest', 'created_at', 'updated_at', 'expires_at')}, sourceTreeSha256=lock['bogoOverlay']['sourceTreeSha256'], overlaySha256=lock['bogoOverlay']['patchSha256'], builtExecutable=provenance['binaries']['app'], harnessFiles=harness_files, files=[{'filename': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)} for path in files])
        bogo.full.write_json(report_path, report)
        return report
    except Exception as error:
        # Error text from network/native code is intentionally not copied into public receipts.
        report.update(status='blocked', errorType=type(error).__name__, error=diagnostic(error))
        bogo.full.write_json(report_path, report)
        raise


def record_acceptance(directory, smoke_directory, app):
    require(app in APPS, 'Unknown acceptance application')
    harness = runner_context()
    directory, smoke_directory = runner_path(directory), runner_path(smoke_directory)
    require(not (directory / 'acceptance.json').exists() and not (directory / 'acceptance.json').is_symlink(), 'Existing acceptance receipts are never reused or overwritten')
    binding_file = directory / 'authenticated-build.json'
    require(binding_file.is_file() and not binding_file.is_symlink() and binding_file.stat().st_size <= MAX_METADATA, 'Authenticated input receipt is missing or too large')
    binding = json.loads(binding_file.read_text(encoding='utf-8'))
    require(binding.get('schema') == 'bogo.windows-artifact-input.v1' and binding.get('repository') == REPOSITORY and binding.get('app') == app and binding.get('status') == 'verified' and binding.get('harnessSha') == harness and binding.get('harnessRunId') == os.environ.get('GITHUB_RUN_ID'), 'Authenticated input receipt differs from this acceptance harness/app/run')
    lock = bogo.load_lock(app)
    expected = reviewed.expected_files(lock, 'windows-x64')
    require(isinstance(binding.get('files'), list) and len(binding['files']) == 5 and {item.get('filename') for item in binding['files']} == expected, 'Authenticated candidate file allowlist changed')
    require(isinstance(binding.get('harnessFiles'), dict) and set(binding['harnessFiles']) == set(HARNESS_FILES), 'Acceptance harness file allowlist changed')
    for relative, digest in binding['harnessFiles'].items():
        path = bogo.ROOT / relative
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest, 'Acceptance harness changed during native smoke')
    for item in binding['files']:
        path = directory / 'candidate' / item['filename']
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == item['bytes'] and sha256(path) == item['sha256'], 'Authenticated candidate changed during native smoke')
    smoke_file = smoke_directory / 'report.json'
    require(smoke_file.is_file() and not smoke_file.is_symlink() and smoke_file.stat().st_size <= MAX_METADATA, 'Actual smoke report is missing or too large')
    smoke = json.loads(smoke_file.read_text(encoding='utf-8'))
    require(smoke.get('app') == app and smoke.get('platform') == 'windows-x64' and smoke.get('version') == lock['version'], 'Actual smoke report belongs to another app/platform/version')
    accepted = smoke.get('status') == 'passed'
    if accepted:
        require(smoke.get('installedExe', {}).get('sha256') == binding['builtExecutable']['sha256'] and smoke.get('portableExe', {}).get('sha256') == binding['builtExecutable']['sha256'], 'Actual executed EXEs differ from the authenticated build')
    receipt = {'schema': 'bogo.windows-artifact-acceptance.v1', 'repository': REPOSITORY, 'app': app, 'builtSha': binding['builtSha'], 'harnessSha': harness, 'harnessRunId': os.environ.get('GITHUB_RUN_ID'), 'buildRunId': binding['buildRunId'], 'previousNativeJob': binding['job'], 'freshFullAcceptancePassed': accepted, 'artifact': binding['artifact'], 'harnessFiles': binding['harnessFiles'], 'smokeReportSha256': sha256(smoke_file), 'status': 'passed' if accepted else 'failed', 'publicationPerformed': False}
    bogo.full.write_json(directory / 'acceptance.json', receipt)
    require(accepted, 'Actual updated Windows acceptance did not pass')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    choose = commands.add_parser('matrix')
    choose.add_argument('--app', choices=(*APPS, 'all'), required=True)
    acquire = commands.add_parser('collect')
    acquire.add_argument('--app', choices=APPS, required=True)
    acquire.add_argument('--run-id', type=reviewed.positive_id, required=True)
    acquire.add_argument('--expected-build-sha', type=exact_sha, required=True)
    acquire.add_argument('--output', type=Path, required=True)
    record = commands.add_parser('record')
    record.add_argument('--app', choices=APPS, required=True)
    record.add_argument('--directory', type=Path, required=True)
    record.add_argument('--smoke-directory', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'matrix':
        print(json.dumps(matrix(args.app), separators=(',', ':')))
    elif args.command == 'collect':
        result = collect(args.run_id, args.expected_build_sha, args.app, args.output)
        print(json.dumps({key: result[key] for key in ('app', 'status', 'builtSha', 'harnessSha')}))
    else:
        result = record_acceptance(args.directory, args.smoke_directory, args.app)
        print(json.dumps({key: result[key] for key in ('app', 'status', 'builtSha', 'harnessSha')}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Bogo artifact acceptance refused: ' + diagnostic(error), file=sys.stderr)
        sys.exit(1)
