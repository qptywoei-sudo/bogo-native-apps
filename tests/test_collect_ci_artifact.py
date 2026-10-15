import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('collect_ci_artifact', SCRIPTS / 'collect_ci_artifact.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
RUN_ID = 12345
SHA = 'a' * 40


class FakeGitHub:
    def __init__(self, lock, platform='macos-arm64', transform=None):
        self.app, self.platform = lock['id'], platform
        self.calls, self.downloads = [], []
        self.run = {'id': RUN_ID, 'event': 'workflow_dispatch', 'head_branch': 'main',
                    'head_sha': SHA, 'run_attempt': 2, 'workflow_id': 88,
                    'status': 'queued', 'conclusion': None,
                    'path': collector.workflow_path(self.app),
                    'repository': {'id': 7, 'full_name': collector.REPOSITORY},
                    'head_repository': {'id': 7, 'full_name': collector.REPOSITORY}}
        self.workflow = {'id': 88, 'path': collector.workflow_path(self.app), 'state': 'active'}
        self.job = {'id': 99, 'run_id': RUN_ID, 'run_attempt': 2, 'head_sha': SHA,
                    'name': collector.expected_job(self.app, platform), 'status': 'completed',
                    'conclusion': 'success', 'started_at': '2026-10-15T19:00:00Z',
                    'completed_at': '2026-10-15T19:20:00Z'}
        self.jobs = [self.job]
        self.artifact = {'id': 101, 'name': f'{self.app}-{platform}', 'expired': False,
                         'created_at': '2026-10-15T19:19:00Z', 'updated_at': '2026-10-15T19:19:30Z',
                         'expires_at': '2026-10-29T19:19:00Z',
                         'workflow_run': {'id': RUN_ID, 'repository_id': 7, 'head_repository_id': 7,
                                          'head_branch': 'main', 'head_sha': SHA}}
        self.artifacts = [self.artifact]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = collector.full.artifact_base(lock, platform)
            provenance = {'schema': 1, 'app': self.app, 'version': lock['version'],
                          'platform': platform, 'inputs': {'schema': 1, 'app': self.app, 'lock': lock}}
            (folder / (base + '.zip')).write_bytes(b'opaque nested release ZIP fixture; never executed')
            if platform != 'source':
                (folder / (base + ('.dmg' if platform == 'macos-arm64' else '.msi'))).write_bytes(b'opaque native fixture; never executed')
            if transform:
                transform(folder, base, provenance)
            (folder / (base + '-provenance.json')).write_text(json.dumps(provenance))
            collector.full.finalize(folder, lock, platform)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(folder.iterdir()):
                    archive.writestr(path.name, path.read_bytes())
            self.archive = buffer.getvalue()
        self.bind_archive()
        self.after_download = None

    def bind_archive(self):
        self.artifact['size_in_bytes'] = len(self.archive)
        self.artifact['digest'] = 'sha256:' + hashlib.sha256(self.archive).hexdigest()

    def json(self, endpoint):
        self.calls.append(endpoint)
        base = f'repos/{collector.REPOSITORY}/actions'
        responses = {base + f'/runs/{RUN_ID}': self.run,
                     base + '/workflows/88': self.workflow,
                     base + f'/runs/{RUN_ID}/attempts/2/jobs?per_page=100&page=1': {'total_count': len(self.jobs), 'jobs': self.jobs},
                     base + f'/runs/{RUN_ID}/artifacts?per_page=100&page=1': {'total_count': len(self.artifacts), 'artifacts': self.artifacts},
                     base + '/artifacts/101': self.artifact}
        if endpoint not in responses:
            raise AssertionError('Unexpected API request: ' + endpoint)
        return copy.deepcopy(responses[endpoint])

    def download(self, artifact, destination):
        self.downloads.append(copy.deepcopy(artifact))
        destination.write_bytes(self.archive)
        if self.after_download:
            self.after_download(self)


class CollectCIArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = collector.load_lock('film')

    def collect(self, fake, output):
        return collector.collect(RUN_ID, fake.app, fake.platform, output, github=fake, now=NOW)

    def assert_blocked(self, fake, downloads=0):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fresh'
            with self.assertRaises((ValueError, zipfile.BadZipFile)):
                self.collect(fake, output)
            report = json.loads((output / 'collection.json').read_text())
            self.assertEqual(report['status'], 'blocked')
            self.assertFalse(report['releaseReviewEligible'])
            self.assertFalse(report['publicationPerformed'])
            self.assertFalse(report['executedNativeBinaries'])
            self.assertEqual(len(fake.downloads), downloads)

    def test_selected_success_is_collectible_while_overall_run_is_queued(self):
        fake = FakeGitHub(self.lock)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fresh'
            with patch.object(collector.full, 'verify', wraps=collector.full.verify) as verify:
                result = self.collect(fake, output)
            self.assertEqual(result['status'], 'verified')
            self.assertTrue(result['releaseReviewEligible'])
            self.assertFalse(result['publicationPerformed'])
            self.assertFalse(result['executedNativeBinaries'])
            self.assertEqual(len(fake.downloads), 1)
            self.assertEqual(fake.downloads[0]['id'], 101)
            self.assertEqual(len(list((output / 'release').iterdir())), 5)
            self.assertEqual(json.loads((output / 'selected-lock.json').read_text()), self.lock)
            verify.assert_called_once_with((output / 'release').resolve(), self.lock, 'macos-arm64')
        self.assertTrue(all(endpoint.startswith(f'repos/{collector.REPOSITORY}/actions/') for endpoint in fake.calls))

    def test_launcher_and_source_use_their_own_exact_locks_and_job_names(self):
        for app, platform in [('launcher', 'windows-x64'), ('launcher', 'source'), ('film', 'source')]:
            with self.subTest(app=app, platform=platform), tempfile.TemporaryDirectory() as tmp:
                lock = collector.load_lock(app)
                fake = FakeGitHub(lock, platform)
                result = self.collect(fake, Path(tmp) / 'fresh')
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['workflow'], collector.workflow_path(app))
                self.assertEqual(len(fake.downloads), 1)

    def test_non_manual_fork_branch_workflow_and_head_are_rejected_before_download(self):
        mutations = [lambda f: f.run.update(event='push'), lambda f: f.run.update(head_branch='feature'),
                     lambda f: f.run['head_repository'].update(full_name='attacker/kio-native-apps'),
                     lambda f: f.run['repository'].update(full_name='other/repository'),
                     lambda f: f.run.update(path='.github/workflows/full-native-word.yml'),
                     lambda f: f.workflow.update(path='.github/workflows/unknown.yml'),
                     lambda f: f.workflow.update(state='disabled_manually'),
                     lambda f: f.run.update(head_sha='invalid')]
        for mutate in mutations:
            fake = FakeGitHub(self.lock)
            mutate(fake)
            self.assert_blocked(fake)

    def test_only_exact_selected_successful_current_attempt_job_is_allowed(self):
        mutations = [lambda f: f.job.update(conclusion='failure'), lambda f: f.job.update(status='in_progress'),
                     lambda f: f.job.update(run_attempt=1), lambda f: f.job.update(head_sha='b' * 40),
                     lambda f: f.job.update(name=collector.expected_job('photo', f.platform)),
                     lambda f: f.jobs.append(dict(f.job, id=100))]
        for mutate in mutations:
            fake = FakeGitHub(self.lock)
            mutate(fake)
            self.assert_blocked(fake)

    def test_wrong_expired_ambiguous_and_stale_attempt_artifacts_are_rejected(self):
        mutations = [lambda f: f.artifact.update(name='photo-macos-arm64'),
                     lambda f: f.artifact.update(expired=True),
                     lambda f: f.artifact.update(expires_at='2026-10-15T19:19:00Z'),
                     lambda f: f.artifact.update(size_in_bytes=0),
                     lambda f: f.artifact.update(size_in_bytes=collector.MAX_ARCHIVE_BYTES + 1),
                     lambda f: f.artifact.update(created_at='2026-10-14T19:19:00Z'),
                     lambda f: f.artifact['workflow_run'].update(head_sha='b' * 40),
                     lambda f: f.artifact['workflow_run'].update(head_repository_id=8),
                     lambda f: f.artifacts.append(dict(f.artifact, id=102))]
        for mutate in mutations:
            fake = FakeGitHub(self.lock)
            mutate(fake)
            self.assert_blocked(fake)

    def test_archive_size_and_github_digest_are_checked_before_extraction(self):
        for mutate in [lambda f: f.artifact.update(size_in_bytes=len(f.archive) + 1),
                       lambda f: f.artifact.update(digest='sha256:' + '0' * 64)]:
            fake = FakeGitHub(self.lock)
            mutate(fake)
            self.assert_blocked(fake, downloads=1)

    def test_rerun_or_expiration_during_the_single_download_is_blocked(self):
        for callback in [lambda f: f.run.update(run_attempt=3), lambda f: f.artifact.update(expired=True)]:
            fake = FakeGitHub(self.lock)
            fake.after_download = callback
            self.assert_blocked(fake, downloads=1)

    def test_checksum_failure_and_exact_provenance_lock_mismatch_stay_blocked(self):
        fake = FakeGitHub(self.lock)
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(fake.archive)) as old, zipfile.ZipFile(buffer, 'w') as new:
            for item in old.infolist():
                new.writestr(item.filename, b'changed' if item.filename.endswith('.dmg') else old.read(item))
        fake.archive = buffer.getvalue()
        fake.bind_archive()
        self.assert_blocked(fake, downloads=1)
        def wrong_lock(folder, base, provenance):
            provenance['inputs'] = copy.deepcopy(provenance['inputs'])
            provenance['inputs']['lock']['cargoArgs'] += ['--no-default-features']
        self.assert_blocked(FakeGitHub(self.lock, transform=wrong_lock), downloads=1)

    def test_local_lock_change_during_collection_is_blocked(self):
        fake = FakeGitHub(self.lock)
        changed = copy.deepcopy(self.lock)
        changed['version'] = '99.0.0-kio.1'
        with patch.object(collector, 'load_lock', side_effect=[self.lock, changed]):
            self.assert_blocked(fake, downloads=1)

    def test_zip_slip_symlink_special_extra_directory_and_duplicates_are_rejected(self):
        for filename, mode, repeat in [('../outside', 0, False), ('/absolute', 0, False),
                                       ('C:\\escape', 0, False), ('unexpected.txt', 0, False),
                                       (None, stat.S_IFLNK | 0o777, False), (None, stat.S_IFIFO | 0o600, False),
                                       (None, stat.S_IFDIR | 0o755, False), (None, 0, True)]:
            with self.subTest(filename=filename, mode=mode, repeat=repeat):
                fake = FakeGitHub(self.lock)
                buffer = io.BytesIO()
                with warnings.catch_warnings(), zipfile.ZipFile(io.BytesIO(fake.archive)) as old, zipfile.ZipFile(buffer, 'w') as new:
                    warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)
                    for index, item in enumerate(old.infolist()):
                        if index == 0:
                            entry = zipfile.ZipInfo(filename or item.filename)
                            if mode:
                                entry.create_system = 3
                                entry.external_attr = mode << 16
                            new.writestr(entry, old.read(item))
                            if repeat:
                                continue  # duplicate the first path in place of the second entry
                        elif repeat and index == 1:
                            new.writestr(old.infolist()[0].filename, old.read(item))
                        else:
                            new.writestr(item.filename, old.read(item))
                fake.archive = buffer.getvalue()
                fake.bind_archive()
                self.assert_blocked(fake, downloads=1)

    def test_entire_outer_zip_is_validated_before_any_release_entry_is_written(self):
        fake = FakeGitHub(self.lock)
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(fake.archive)) as old, zipfile.ZipFile(buffer, 'w') as new:
            for index, item in enumerate(old.infolist()):
                new.writestr('../last-is-unsafe' if index == len(old.infolist()) - 1 else item.filename, old.read(item))
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'outer.zip'
            archive.write_bytes(buffer.getvalue())
            release = Path(tmp) / 'release'
            with self.assertRaises(ValueError):
                collector.extract_artifact(archive, release, collector.expected_files(self.lock, fake.platform))
            self.assertFalse(release.exists())
            self.assertFalse((Path(tmp) / 'last-is-unsafe').exists())

    def test_zip_expansion_limit_is_checked_before_decompression(self):
        fake = FakeGitHub(self.lock)
        archive = bytearray(fake.archive)
        central = archive.index(b'PK\x01\x02')
        # The first entry is the small SHA256SUMS text. Inflate only its central
        # directory claim; no large data or decompression is needed for this test.
        struct.pack_into('<I', archive, central + 24, collector.MAX_METADATA_BYTES + 1)
        fake.archive = bytes(archive)
        fake.bind_archive()
        self.assert_blocked(fake, downloads=1)

    def test_fresh_output_does_not_overwrite_existing_directory_or_follow_output_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / 'existing'
            existing.mkdir()
            marker = existing / 'preserve.txt'
            marker.write_text('keep')
            linked = root / 'link'
            linked.symlink_to(existing, target_is_directory=True)
            for path in (existing, linked):
                with self.assertRaises(ValueError):
                    self.collect(FakeGitHub(self.lock), path)
                self.assertEqual(marker.read_text(), 'keep')
                self.assertFalse((existing / 'collection.json').exists())

    def test_fixed_host_repository_get_and_numeric_raw_artifact_endpoint(self):
        with patch.object(collector.shutil, 'which', return_value='/reviewed/gh'):
            github = collector.GitHub()
        endpoint = f'repos/{collector.REPOSITORY}/actions/artifacts/101/zip'
        command = github.command(endpoint)
        self.assertIn('--hostname', command)
        self.assertIn('github.com', command)
        self.assertIn('GET', command)
        self.assertEqual(command[-1], endpoint)
        self.assertEqual(github.environment['GH_REPO'], collector.REPOSITORY)
        for unsafe in ['https://attacker.invalid/data', 'repos/attacker/repo/actions/runs/1',
                       f'repos/{collector.REPOSITORY}/actions/../../pulls',
                       f'repos/{collector.REPOSITORY}/actions/runs/1?repo=attacker']:
            with self.assertRaises(ValueError):
                github.command(unsafe)
        with tempfile.TemporaryDirectory() as tmp, patch.object(collector.subprocess, 'run') as command_run:
            github.download({'id': 101}, Path(tmp) / 'one.zip')
            self.assertEqual(command_run.call_count, 1)
            self.assertEqual(command_run.call_args.args[0][-1], endpoint)
            self.assertNotIn('shell', command_run.call_args.kwargs)

    def test_explicit_allowlist_and_numeric_run_are_required(self):
        self.assertEqual(collector.positive_id('38778800473'), 38778800473)
        for bad in ['latest', '-1', '0', '1/../../etc', '1;echo bad']:
            with self.assertRaises(ValueError):
                collector.positive_id(bad)
        with tempfile.TemporaryDirectory() as tmp:
            for app, platform in [('studio', 'macos-arm64'), ('film', 'linux-x64')]:
                with self.assertRaises(ValueError):
                    collector.collect(RUN_ID, app, platform, Path(tmp) / 'never-created')
            self.assertFalse((Path(tmp) / 'never-created').exists())


if __name__ == '__main__':
    unittest.main()
