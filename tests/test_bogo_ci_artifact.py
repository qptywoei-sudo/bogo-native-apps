import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_ci_artifact as acceptance

RUN = 40307486690
BUILT = 'a' * 40
HARNESS = 'b' * 40
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


class FakeGitHub:
    """Opaque fixtures only. No native binary, MSI or nested ZIP is executed."""
    def __init__(self, lock, mutate_provenance=None):
        self.app = lock['id']
        self.run = {'id': RUN, 'head_sha': BUILT, 'event': 'workflow_dispatch', 'head_branch': acceptance.BRANCH,
                    'path': acceptance.BUILD_WORKFLOW, 'workflow_id': 77, 'run_attempt': 2,
                    'status': 'in_progress', 'conclusion': None,
                    'repository': {'id': 90, 'full_name': acceptance.REPOSITORY},
                    'head_repository': {'id': 90, 'full_name': acceptance.REPOSITORY}}
        self.workflow = {'id': 77, 'path': acceptance.BUILD_WORKFLOW, 'state': 'active'}
        self.job = {'id': 99, 'run_id': RUN, 'run_attempt': 2, 'head_sha': BUILT,
                    'name': self.app + ' on windows-x64 with installer acceptance',
                    'status': 'completed', 'conclusion': 'success', 'labels': ['windows-2022'],
                    'runner_group_name': 'GitHub Actions', 'started_at': '2026-10-26T10:00:00Z',
                    'completed_at': '2026-10-26T11:00:00Z'}
        names = ['Set up job', 'Run actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd',
                 'Verify owner-derived icons and all source overlay identities on the target OS',
                 'Run rustup toolchain install 1.95.0 --profile minimal --component rustfmt --target x86_64-pc-windows-msvc',
                 'Run dotnet tool install --global wix --version 5.0.2',
                 'Run python scripts/bogo_native.py prepare --app ' + self.app,
                 'Run python scripts/bogo_native.py build --app ' + self.app + ' --platform windows-x64',
                 'Run python scripts/bogo_native.py package --app ' + self.app + ' --platform windows-x64',
                 'Run python scripts/bogo_native.py verify --app ' + self.app + ' --platform windows-x64 --directory dist/' + self.app + '-windows-x64',
                 acceptance.OLD_SMOKE_STEP, acceptance.UPLOAD_STEP,
                 'Post Run actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd', 'Complete job']
        self.job['steps'] = [{'number': index, 'name': name, 'status': 'completed', 'conclusion': 'success',
                             'started_at': '2026-10-26T10:00:00Z', 'completed_at': '2026-10-26T10:59:00Z'}
                            for index, name in enumerate(names, 1)]
        self.jobs = [self.job]
        self.calls = []
        self.after_download = None
        overlay = lock['bogoOverlay']
        provenance = {'schema': 1, 'app': self.app, 'version': lock['version'], 'platform': 'windows-x64',
                      'inputs': {'lock': lock, 'sourceTreeSha256': overlay['sourceTreeSha256'],
                                 'bogoOverlay': {'path': overlay['patch'], 'sha256': overlay['patchSha256']}},
                      'binaries': {'app': {'sha256': 'c' * 64, 'bytes': 123}}}
        if mutate_provenance:
            mutate_provenance(provenance)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            base = acceptance.bogo.full.artifact_base(lock, 'windows-x64')
            (folder / (base + '.msi')).write_bytes(b'opaque MSI unit fixture')
            (folder / (base + '.zip')).write_bytes(b'opaque portable unit fixture')
            (folder / (base + '-provenance.json')).write_text(json.dumps(provenance), encoding='utf-8')
            acceptance.bogo.full.finalize(folder, lock, 'windows-x64')
            self.files = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.archive = self.make_archive()
        self.artifact = {'id': 101, 'name': 'bogo-' + self.app + '-windows-x64', 'expired': False,
                         'url': acceptance.API + 'artifacts/101', 'archive_download_url': acceptance.API + 'artifacts/101/zip',
                         'created_at': '2026-10-26T10:58:00Z', 'updated_at': '2026-10-26T10:59:00Z',
                         'expires_at': '2026-11-02T10:59:00Z',
                         'workflow_run': {'id': RUN, 'repository_id': 90, 'head_repository_id': 90,
                                          'head_branch': acceptance.BRANCH, 'head_sha': BUILT}}
        self.bind_archive()
        self.artifacts = [self.artifact]

    def make_archive(self, extra=None, prefix='bogo-native-apps/bogo-native-apps/dist/'):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.files.items():
                archive.writestr(prefix + self.app + '-windows-x64/' + name, data)
            archive.writestr('_temp/bogo-windows-smoke-' + self.app + '/verified-legacy.msi', b'ignored historical input')
            archive.writestr('_temp/bogo-windows-smoke-' + self.app + '/do-not-execute.py', b'raise RuntimeError("never run")')
            if extra:
                extra(archive)
        return buffer.getvalue()

    def bind_archive(self):
        self.artifact.update(size_in_bytes=len(self.archive), digest='sha256:' + hashlib.sha256(self.archive).hexdigest())

    def json(self, endpoint):
        self.calls.append(endpoint)
        if endpoint.endswith('/runs/' + str(RUN)):
            return copy.deepcopy(self.run)
        if endpoint.endswith('/workflows/77'):
            return copy.deepcopy(self.workflow)
        if '/jobs?' in endpoint:
            return {'total_count': len(self.jobs), 'jobs': copy.deepcopy(self.jobs)}
        if '/artifacts?' in endpoint:
            return {'total_count': len(self.artifacts), 'artifacts': copy.deepcopy(self.artifacts)}
        if endpoint.endswith('/artifacts/101'):
            return copy.deepcopy(self.artifact)
        raise AssertionError('Unexpected fixed API fixture request')

    def download(self, artifact, destination):
        Path(destination).write_bytes(self.archive)
        if self.after_download:
            self.after_download(self)


class ArtifactAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = acceptance.bogo.load_lock('cad')

    def collect(self, github, base):
        with patch.dict(os.environ, {'RUNNER_TEMP': str(base)}), patch.object(acceptance, 'runner_context', return_value=HARNESS):
            return acceptance.collect(RUN, BUILT, 'cad', base / 'owned-input', github=github, now=NOW)

    def test_successful_selected_job_works_while_overall_build_is_running_and_extracts_only_five(self):
        github = FakeGitHub(self.lock)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            report = self.collect(github, base)
            self.assertEqual(report['status'], 'verified')
            self.assertEqual(report['builtSha'], BUILT)
            self.assertEqual(report['harnessSha'], HARNESS)
            self.assertFalse(report['nativeExecutionPerformed'])
            self.assertFalse(report['publicationPerformed'])
            self.assertEqual({p.name for p in (base / 'owned-input/candidate').iterdir()}, set(github.files))
            self.assertEqual(report['sourceTreeSha256'], self.lock['bogoOverlay']['sourceTreeSha256'])
            self.assertEqual(report['overlaySha256'], self.lock['bogoOverlay']['patchSha256'])
            self.assertTrue(any('/attempts/2/jobs?' in call for call in github.calls))
            self.assertFalse((base / 'owned-input/candidate/do-not-execute.py').exists())

    def test_wrong_run_branch_event_workflow_sha_fork_and_unsuccessful_target_are_refused(self):
        mutations = [
            lambda g: g.run.update(head_sha='d' * 40), lambda g: g.run.update(head_branch='main'),
            lambda g: g.run.update(event='push'), lambda g: g.run.update(path='.github/workflows/other.yml'),
            lambda g: g.run['head_repository'].update(id=91), lambda g: g.workflow.update(path='.github/workflows/other.yml'),
            lambda g: g.job.update(conclusion='failure'), lambda g: g.job.update(status='in_progress'),
            lambda g: g.job.update(run_attempt=1), lambda g: g.job.update(labels=['self-hosted', 'Windows']),
            lambda g: g.jobs.append(copy.deepcopy(g.job)),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                github = FakeGitHub(self.lock)
                mutate(github)
                with self.assertRaises(ValueError):
                    self.collect(github, Path(temporary).resolve())

    def old_smoke_failure(self, github):
        github.job['conclusion'] = 'failure'
        next(step for step in github.job['steps'] if step['name'] == acceptance.OLD_SMOKE_STEP)['conclusion'] = 'failure'

    def test_only_old_whole_smoke_failure_can_supply_inputs_and_never_counts_as_fresh_acceptance(self):
        for fresh_status in ('failed', 'passed'):
            with self.subTest(fresh_status=fresh_status), tempfile.TemporaryDirectory() as temporary:
                github = FakeGitHub(self.lock)
                self.old_smoke_failure(github)
                base = Path(temporary).resolve()
                binding = self.collect(github, base)
                self.assertEqual(binding['status'], 'verified', 'only the immutable input files are verified here')
                self.assertFalse(binding['nativeExecutionPerformed'])
                self.assertEqual(binding['job']['conclusion'], 'failure')
                eligibility = binding['job']['eligibility']
                self.assertEqual(eligibility['reason'], 'old harness failed; fresh full acceptance required')
                self.assertFalse(eligibility['priorNativeAcceptancePassed'])
                self.assertTrue(eligibility['freshFullAcceptanceRequired'])
                self.assertEqual([step['name'] for step in eligibility['failedSteps']], [acceptance.OLD_SMOKE_STEP])
                smoke = base / 'fresh-smoke'
                smoke.mkdir()
                report = {'app': 'cad', 'version': self.lock['version'], 'platform': 'windows-x64', 'status': fresh_status,
                          'installedExe': {'sha256': 'c' * 64}, 'portableExe': {'sha256': 'c' * 64}}
                (smoke / 'report.json').write_text(json.dumps(report), encoding='utf-8')
                with patch.dict(os.environ, {'RUNNER_TEMP': str(base)}), patch.object(acceptance, 'runner_context', return_value=HARNESS):
                    if fresh_status == 'failed':
                        with self.assertRaisesRegex(ValueError, 'did not pass'):
                            acceptance.record_acceptance(base / 'owned-input', smoke, 'cad')
                    else:
                        acceptance.record_acceptance(base / 'owned-input', smoke, 'cad')
                receipt = json.loads((base / 'owned-input/acceptance.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['status'], fresh_status)
                self.assertEqual(receipt['freshFullAcceptancePassed'], fresh_status == 'passed')
                self.assertEqual(receipt['previousNativeJob']['conclusion'], 'failure')
                self.assertEqual(receipt['previousNativeJob']['eligibility']['failedSteps'][0]['conclusion'], 'failure')

    def test_every_source_build_package_verify_and_upload_step_must_succeed_without_other_failure_or_timeout(self):
        for name in acceptance.mandatory_build_steps('cad'):
            for conclusion in ('failure', 'cancelled', 'timed_out', 'skipped'):
                with self.subTest(step=name, conclusion=conclusion), tempfile.TemporaryDirectory() as temporary:
                    github = FakeGitHub(self.lock)
                    self.old_smoke_failure(github)
                    next(step for step in github.job['steps'] if step['name'] == name)['conclusion'] = conclusion
                    with self.assertRaises(ValueError): self.collect(github, Path(temporary).resolve())
        for mutate in [lambda g: next(step for step in g.job['steps'] if step['name'] == 'Set up job').update(conclusion='failure'),
                       lambda g: g.job.update(conclusion='timed_out'),
                       lambda g: g.job.update(steps=[]),
                       lambda g: g.job['steps'].pop(8),
                       lambda g: g.job['steps'].append(copy.deepcopy(g.job['steps'][0]))]:
            with tempfile.TemporaryDirectory() as temporary:
                github = FakeGitHub(self.lock)
                self.old_smoke_failure(github)
                mutate(github)
                with self.assertRaises(ValueError): self.collect(github, Path(temporary).resolve())

    def test_expired_duplicate_tampered_zip_and_readback_changes_are_refused(self):
        mutations = [
            lambda g: g.artifact.update(expired=True), lambda g: g.artifact.update(digest=None),
            lambda g: g.artifact.update(digest='sha256:' + 'f' * 64),
            lambda g: g.artifact.update(size_in_bytes=len(g.archive) + 1),
            lambda g: g.artifact['workflow_run'].update(head_sha='f' * 40),
            lambda g: g.artifact.update(created_at='2026-10-26T09:59:00Z'),
            lambda g: g.artifacts.append(copy.deepcopy(g.artifact)),
            lambda g: setattr(g, 'after_download', lambda current: current.run.update(run_attempt=3)),
            lambda g: setattr(g, 'after_download', lambda current: current.artifact.update(digest='sha256:' + 'e' * 64)),
            lambda g: g.artifact.update(archive_download_url='https://other.example/private'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                github = FakeGitHub(self.lock)
                mutate(github)
                with self.assertRaises(ValueError):
                    self.collect(github, Path(temporary).resolve())

    def test_authenticated_provenance_must_match_current_source_tree_overlay_and_build_lock(self):
        for mutate in [lambda p: p['inputs'].update(sourceTreeSha256='d' * 64),
                       lambda p: p['inputs']['bogoOverlay'].update(sha256='e' * 64),
                       lambda p: p['inputs']['lock'].update(bundleId='com.bogo.cad')]:
            with tempfile.TemporaryDirectory() as temporary:
                github = FakeGitHub(copy.deepcopy(self.lock), mutate)
                with self.assertRaises(ValueError):
                    self.collect(github, Path(temporary).resolve())

    def test_unsafe_ignored_members_and_duplicate_candidate_roots_are_rejected_before_extracting(self):
        def symlink(archive):
            info = zipfile.ZipInfo('_temp/link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '../../outside')
        def reparse(archive):
            info = zipfile.ZipInfo('_temp/reparse')
            info.external_attr = 0x400
            archive.writestr(info, b'ignored reparse payload')
        cases = [lambda z: z.writestr('../outside', b'x'), lambda z: z.writestr('/absolute', b'x'),
                 lambda z: z.writestr('C:/drive', b'x'), lambda z: z.writestr('_temp/file:stream', b'x'),
                 lambda z: z.writestr('_temp/../escape', b'x'), symlink, reparse,
                 lambda z: z.writestr('other/dist/cad-windows-x64/' + next(iter(self.fixture_files)), b'duplicate')]
        github = FakeGitHub(self.lock)
        self.fixture_files = github.files
        for extra in cases:
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                archive = base / 'input.zip'
                archive.write_bytes(github.make_archive(extra))
                destination = base / 'candidate'
                with self.assertRaises(ValueError):
                    acceptance.extract_candidates(archive, destination, 'cad', set(github.files))
                self.assertFalse(destination.exists())
        with tempfile.TemporaryDirectory() as temporary, warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            base = Path(temporary).resolve()
            archive = base / 'input.zip'
            archive.write_bytes(github.make_archive(lambda z: z.writestr('_temp/bogo-windows-smoke-cad/do-not-execute.py', b'duplicate')))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                acceptance.extract_candidates(archive, base / 'candidate', 'cad', set(github.files))

    def test_mixed_native_directory_roots_and_expansion_bounds_are_refused(self):
        github = FakeGitHub(self.lock)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            archive = base / 'input.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                for index, (name, data) in enumerate(github.files.items()):
                    prefix = 'first' if index % 2 else 'second'
                    zipped.writestr(prefix + '/dist/cad-windows-x64/' + name, data)
            with self.assertRaisesRegex(ValueError, 'one exact five-file'):
                acceptance.extract_candidates(archive, base / 'mixed', 'cad', set(github.files))
            archive.write_bytes(github.archive)
            with patch.object(acceptance, 'MAX_MEMBER', 1), self.assertRaisesRegex(ValueError, 'type/size'):
                acceptance.extract_candidates(archive, base / 'bounded', 'cad', set(github.files))
            self.assertFalse((base / 'mixed').exists())
            self.assertFalse((base / 'bounded').exists())

    def test_output_is_new_owned_runner_temp_and_non_ci_context_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            with patch.dict(os.environ, {'RUNNER_TEMP': str(base)}):
                self.assertEqual(acceptance.runner_path(base / 'new', fresh=True), base / 'new')
                (base / 'existing').mkdir()
                with self.assertRaises(ValueError): acceptance.runner_path(base / 'existing', fresh=True)
                with self.assertRaises(ValueError): acceptance.runner_path(base.parent / 'outside')
                (base / 'linked').symlink_to(base / 'existing', target_is_directory=True)
                with self.assertRaises(ValueError): acceptance.runner_path(base / 'linked/output')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): acceptance.runner_context()

    def test_exact_runner_workflow_definition_is_required_even_when_ci_flags_are_present(self):
        values = {'RUNNER_OS': 'Windows', 'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_ACTIONS': 'true',
                  'GITHUB_REPOSITORY': acceptance.REPOSITORY, 'GITHUB_WORKFLOW': acceptance.WORKFLOW,
                  'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/' + acceptance.BRANCH,
                  'GITHUB_SHA': HARNESS, 'GITHUB_WORKFLOW_SHA': HARNESS, 'GITHUB_RUN_ID': '456',
                  'GITHUB_WORKFLOW_REF': acceptance.REPOSITORY + '/.github/workflows/bogo-windows-acceptance.yml@refs/heads/' + acceptance.BRANCH,
                  'GITHUB_WORKSPACE': str(ROOT.resolve())}
        with patch.dict(os.environ, values, clear=True), patch.object(acceptance.sys, 'platform', 'win32'), patch.object(acceptance.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=HARNESS+'\n')):
            self.assertEqual(acceptance.runner_context(), HARNESS)
            for key, value in [('RUNNER_ENVIRONMENT', 'self-hosted'), ('GITHUB_WORKFLOW_REF', 'other/workflow'), ('GITHUB_WORKFLOW_SHA', BUILT), ('GITHUB_REF', 'refs/heads/main')]:
                with patch.dict(os.environ, {key: value}):
                    with self.assertRaises(ValueError): acceptance.runner_context()

    def test_record_keeps_built_and_harness_shas_separate_and_rejects_changed_executed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            self.collect(FakeGitHub(self.lock), base)
            smoke = base / 'owned-smoke'
            smoke.mkdir()
            report = {'app': 'cad', 'version': self.lock['version'], 'platform': 'windows-x64', 'status': 'passed',
                      'installedExe': {'sha256': 'c' * 64}, 'portableExe': {'sha256': 'c' * 64}}
            (smoke / 'report.json').write_text(json.dumps(report), encoding='utf-8')
            with patch.dict(os.environ, {'RUNNER_TEMP': str(base)}), patch.object(acceptance, 'runner_context', return_value=HARNESS):
                receipt = acceptance.record_acceptance(base / 'owned-input', smoke, 'cad')
                self.assertEqual(receipt['builtSha'], BUILT)
                self.assertEqual(receipt['harnessSha'], HARNESS)
                self.assertEqual(receipt['status'], 'passed')
                with self.assertRaisesRegex(ValueError, 'never reused'):
                    acceptance.record_acceptance(base / 'owned-input', smoke, 'cad')
                # Remove only this test's disposable receipt to exercise another refusal.
                (base / 'owned-input/acceptance.json').unlink()
                report['installedExe']['sha256'] = 'd' * 64
                (smoke / 'report.json').write_text(json.dumps(report), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'executed EXEs'):
                    acceptance.record_acceptance(base / 'owned-input', smoke, 'cad')

    def test_public_diagnostic_does_not_echo_external_exception_urls_or_credentials(self):
        error = ValueError('https://blob.example/file?sig=private-token Authorization: Bearer secret')
        self.assertEqual(acceptance.diagnostic(error), 'ValueError')
        self.assertEqual(acceptance.diagnostic(acceptance.Refused('Selected native Windows job has not succeeded')), 'Selected native Windows job has not succeeded')

    def test_official_api_requests_are_closed_and_token_is_not_sent_to_blob_redirect(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'unit-test-secret'}):
            github = acceptance.GitHub()
        request = github.request('repos/' + acceptance.REPOSITORY + '/actions/runs/123')
        self.assertEqual(request.get_header('Authorization'), 'Bearer unit-test-secret')
        for endpoint in ('repos/other/repository/actions/runs/123', 'repos/' + acceptance.REPOSITORY + '/actions/runs/123?token=private', 'https://evil.example/'):
            with self.assertRaises(ValueError): github.request(endpoint)
        class Response(io.BytesIO):
            def __init__(self, status, headers, data=b''):
                super().__init__(data)
                self.status, self.headers = status, headers
        requests = []
        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return Response(302, {'Location': 'https://productionresultssa0.blob.core.windows.net/actions-results/file.zip?sig=private-fixture'})
            return Response(200, {'Content-Length': '3'}, b'ZIP')
        with tempfile.TemporaryDirectory() as temporary, patch.object(github, 'open', side_effect=respond):
            path = Path(temporary) / 'download.zip'
            github.download({'id': 101, 'size_in_bytes': 3}, path)
            self.assertEqual(path.read_bytes(), b'ZIP')
        self.assertIsNone(requests[1].get_header('Authorization'))
        self.assertEqual(requests[1].headers, {'User-agent': 'Bogo-Windows-Acceptance'})

    def test_workflow_is_manual_read_only_and_token_is_confined_to_collection(self):
        text = (ROOT / '.github/workflows/bogo-windows-acceptance.yml').read_text(encoding='utf-8')
        self.assertIn('name: ' + acceptance.WORKFLOW, text)
        self.assertIn('runs-on: windows-2022', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn('actions: read', text)
        self.assertIn('contents: read', text)
        self.assertEqual(text.count('GH_TOKEN:'), 1)
        job_header = text.split('  acceptance:', 1)[1].split('    steps:', 1)[0]
        self.assertNotIn('runner.temp', job_header, 'runner context is available in step env, not job env')
        smoke = text.split('- name: Run current own-window', 1)[1].split('- name:', 1)[0]
        self.assertNotIn('GH_TOKEN', smoke)
        for forbidden in ('workflow_call:', '  push:', '  schedule:', 'contents: write', 'actions: write', 'secrets: inherit', 'cargo build', 'bogo_native.py prepare', 'bogo_native.py build', 'bogo_native.py package', 'publish-draft'):
            self.assertNotIn(forbidden, text)
        self.assertIn('rustup toolchain install 1.95.0 --profile minimal', text)
        self.assertIn('cargo fetch --locked --manifest-path tools/runtime-icon-reference/Cargo.toml --target x86_64-pc-windows-msvc', text)
        self.assertEqual(len(acceptance.matrix('all')['include']), 14)
        self.assertEqual(acceptance.matrix('cad'), {'include': [{'app': 'cad'}]})
        with self.assertRaises(ValueError): acceptance.matrix('studio')
        with self.assertRaises(ValueError): acceptance.exact_sha('main')


if __name__ == '__main__':
    unittest.main()
