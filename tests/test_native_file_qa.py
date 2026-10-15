"""Utility/security tests only. Synthetic headers are never executed as binaries."""
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import native_file_qa as qa


RUN = 12345


def native_bytes(platform, gui=False):
    """Minimal architecture/header fixture; not a runnable native executable."""
    if platform == 'macos-arm64':
        data = bytearray(64)
        data[:4] = b'\xcf\xfa\xed\xfe'
        struct.pack_into('<I', data, 4, 0x0100000C)
        struct.pack_into('<I', data, 12, 2)
    else:
        data = bytearray(256)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3C, 64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<H', data, 68, 0x8664)
        struct.pack_into('<H', data, 88, 0x20B)
        struct.pack_into('<H', data, 64 + 0x5C, 2 if gui else 3)
    return bytes(data)


def row(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def portable(lock, platform, change=None):
    paths = qa.package_paths(lock, platform)
    gui, cli = native_bytes(platform, True), native_bytes(platform)
    provenance = {'schema': 1, 'app': lock['id'], 'version': lock['version'],
                  'platform': platform, 'inputs': {'schema': 1, 'app': lock['id'], 'lock': lock},
                  'binaries': {'app': row(gui), 'cli': row(cli)}}
    files = {paths['app']: gui, paths['cli']: cli,
             paths['provenance']: json.dumps(provenance).encode(),
             paths['root'] + '/Resources/models/example.rten': b'synthetic resource must remain beside the whole bundle',
             paths['root'] + '/Resources/fonts/OFL.txt': b'synthetic retained font notice'}
    if 'plist' in paths:
        files[paths['plist']] = plistlib.dumps({'CFBundleIdentifier': lock['bundleId'],
                                             'CFBundleExecutable': lock['name'],
                                             'CFBundleShortVersionString': lock['upstreamVersion'],
                                             'CFBundleVersion': lock['upstreamVersion']})
    if change:
        change(files, paths, provenance)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, data in files.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if name in (paths['app'], paths['cli']) else 0o644)) << 16
            zipped.writestr(info, data)
    return buffer.getvalue(), provenance


def append_entries(data, entries):
    buffer = io.BytesIO(data)
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, 'a', zipfile.ZIP_DEFLATED) as zipped:
        warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = mode << 16
            zipped.writestr(info, content)
    return buffer.getvalue()


class NativeFileQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = qa.full.load_lock('word')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()

    def extract(self, data, provenance, platform='windows-x64', name='bundle'):
        archive = self.folder / (name + '.zip')
        archive.write_bytes(data)
        destination = self.folder / name
        return qa.extract_portable(archive, destination, self.lock, platform, provenance)

    def collection(self, platform='windows-x64'):
        """A local hash-authenticated release fixture. It makes no API requests."""
        root = self.folder / 'qa'
        root.mkdir()
        collection = root / 'collection'
        collection.mkdir()
        release = collection / 'release'
        release.mkdir()
        base = qa.full.artifact_base(self.lock, platform)
        package, provenance = portable(self.lock, platform)
        (release / (base + '.zip')).write_bytes(package)
        (release / (base + ('.msi' if platform == 'windows-x64' else '.dmg'))).write_bytes(b'not an installer; utility fixture only')
        qa.full.write_json(release / (base + '-provenance.json'), provenance)
        qa.full.finalize(release, self.lock, platform)
        archive = collection / 'ci-artifact.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(release.iterdir()):
                zipped.write(path, path.name)
        files = qa.collector.verify_release(release, self.lock, platform)
        collected = {'status': 'verified', 'releaseReviewEligible': True, 'executedNativeBinaries': False,
                     'publicationPerformed': False, 'repository': qa.collector.REPOSITORY,
                     'run': RUN, 'app': 'word', 'platform': platform, 'headSha': 'a' * 40, 'runAttempt': 1,
                     'workflow': qa.collector.workflow_path('word'),
                     'job': {'id': 3, 'name': qa.collector.expected_job('word', platform), 'conclusion': 'success'},
                     'artifact': {'id': 4, 'name': 'word-' + platform, 'size_in_bytes': archive.stat().st_size,
                                  'digest': 'sha256:' + qa.full.digest(archive)},
                     'archiveSha256': qa.full.digest(archive),
                     'files': [{'path': 'release/' + p.name, 'bytes': p.stat().st_size, 'sha256': qa.full.digest(p)} for p in files]}
        qa.full.write_json(collection / 'collection.json', collected)
        qa.full.write_json(collection / 'selected-lock.json', self.lock)
        qa.full.write_json(root / 'report.json', {'schema': qa.SCHEMA, 'repository': qa.collector.REPOSITORY,
                                                'run': RUN, 'app': 'word', 'platform': platform,
                                                'status': 'collected', 'outputRoot': str(root.resolve()),
                                                'publicationPerformed': False, 'installationPerformed': False,
                                                'executedNativeBinaries': False})
        return root.resolve(), collected

    def test_explicit_choices_and_target_os_are_required(self):
        with patch.object(qa.full, 'assert_host') as host:
            qa.request(RUN, 'word', 'windows-x64')
            host.assert_called_once_with('windows-x64')
            for run, app, platform in [(True, 'word', 'windows-x64'), (0, 'word', 'windows-x64'),
                                       (10 ** 20, 'word', 'windows-x64'), (RUN, 'launcher', 'windows-x64'),
                                       (RUN, 'word', 'source'), (RUN, 'https://example.com', 'windows-x64')]:
                with self.subTest(run=run, app=app, platform=platform), self.assertRaises(ValueError):
                    qa.request(run, app, platform)
        with patch.object(qa.full, 'assert_host', side_effect=ValueError('wrong actual runner')):
            with self.assertRaisesRegex(ValueError, 'wrong actual runner'):
                qa.request(RUN, 'word', 'windows-x64')

    def test_collection_delegates_to_existing_collector_without_native_execution(self):
        result = {'status': 'verified', 'headSha': 'a' * 40, 'runAttempt': 1,
                  'artifact': {'id': 2}, 'job': {'id': 3}}
        root = self.folder / 'fresh'
        with patch.object(qa.full, 'assert_host'), patch.object(qa.collector, 'collect', return_value=result) as collect, patch.object(qa, 'run_process') as process:
            report = qa.collect(RUN, 'word', 'windows-x64', root)
        collect.assert_called_once_with(RUN, 'word', 'windows-x64', root.resolve() / 'collection')
        process.assert_not_called()
        self.assertEqual(report['status'], 'collected')
        self.assertFalse(report['nativeQaPerformed'])
        self.assertFalse(report['executedNativeBinaries'])
        self.assertFalse(report['publicationPerformed'])
        self.assertFalse(report['installationPerformed'])
        with self.assertRaises(ValueError):
            qa.collector.fresh_output(root)

    def test_collection_failure_is_a_real_failed_report(self):
        root = self.folder / 'failed'
        with patch.object(qa.full, 'assert_host'), patch.object(qa.collector, 'collect', side_effect=ValueError('job has not succeeded')), self.assertRaises(ValueError):
            qa.collect(RUN, 'word', 'windows-x64', root)
        report = qa.json_file(root / 'report.json')
        self.assertEqual((report['status'], report['stage']), ('failed', 'collection'))
        self.assertFalse(report['executedNativeBinaries'])

    def test_whole_bundle_and_resources_are_extracted_to_exact_paths(self):
        for platform in qa.PLATFORMS:
            with self.subTest(platform=platform):
                data, provenance = portable(self.lock, platform)
                paths, inventory = self.extract(data, provenance, platform, 'bundle-' + platform)
                output = self.folder / ('bundle-' + platform)
                self.assertEqual(len(inventory), 6 if platform == 'macos-arm64' else 5)
                for item in inventory:
                    path = output / item['path']
                    self.assertEqual(row(path.read_bytes()), {k: item[k] for k in ('bytes', 'sha256')})
                self.assertTrue((output / paths['cli']).is_file())
                self.assertIn('synthetic resource', (output / paths['root'] / 'Resources/models/example.rten').read_text())
                if platform == 'macos-arm64' and os.name != 'nt':
                    self.assertEqual((output / paths['cli']).stat().st_mode & 0o777, 0o700)
                with self.assertRaises(ValueError):
                    qa.extract_portable(self.folder / ('bundle-' + platform + '.zip'), output, self.lock, platform, provenance)

    def test_entire_zip_is_validated_before_any_entry_is_extracted(self):
        original, provenance = portable(self.lock, 'windows-x64')
        data = append_entries(original, [('../outside', b'bad', stat.S_IFREG | 0o644)])
        with self.assertRaises(ValueError):
            self.extract(data, provenance)
        self.assertFalse((self.folder / 'bundle').exists())
        self.assertFalse((self.folder / 'outside').exists())

    def test_links_devices_privileged_modes_and_unsafe_paths_are_refused(self):
        original, _ = portable(self.lock, 'windows-x64')
        paths = qa.package_paths(self.lock, 'windows-x64')
        root = paths['root']
        attacks = [(root + '/link', stat.S_IFLNK | 0o777), (root + '/pipe', stat.S_IFIFO | 0o600),
                   (root + '/device', stat.S_IFCHR | 0o600), (root + '/socket', stat.S_IFSOCK | 0o600),
                   (root + '/privileged', stat.S_IFREG | 0o4755), ('/absolute', stat.S_IFREG),
                   ('C:\\escape', stat.S_IFREG), (root + '/file:stream', stat.S_IFREG),
                   (root + '/NUL.txt', stat.S_IFREG), (root + '/trailing.', stat.S_IFREG),
                   (root + '//empty', stat.S_IFREG), ('another/root', stat.S_IFREG),
                   (root, stat.S_IFREG)]
        for name, mode in attacks:
            with self.subTest(name=name, mode=mode):
                data = append_entries(original, [(name, b'bad', mode)])
                with zipfile.ZipFile(io.BytesIO(data)) as zipped, self.assertRaises(ValueError):
                    qa.inspect_zip(zipped, paths)

    def test_duplicate_case_unicode_and_file_directory_collisions_are_refused(self):
        original, _ = portable(self.lock, 'windows-x64')
        paths = qa.package_paths(self.lock, 'windows-x64')
        root, regular = paths['root'], stat.S_IFREG | 0o644
        attacks = [[(paths['cli'], b'duplicate', regular)],
                   [(root + '/Case/a', b'a', regular), (root + '/case/b', b'b', regular)],
                   [(root + '/Caf\u00e9/a', b'a', regular), (root + '/Cafe\u0301/b', b'b', regular)],
                   [(root + '/parent', b'a', regular), (root + '/parent/child', b'b', regular)],
                   [(root + '/same/', b'', stat.S_IFDIR | 0o755), (root + '/same', b'b', regular)]]
        for entries in attacks:
            with self.subTest(paths=[x[0] for x in entries]):
                with zipfile.ZipFile(io.BytesIO(append_entries(original, entries))) as zipped, self.assertRaises(ValueError):
                    qa.inspect_zip(zipped, paths)

    def test_compression_bombs_and_entry_file_total_limits_fail_before_extraction(self):
        original, provenance = portable(self.lock, 'windows-x64')
        paths = qa.package_paths(self.lock, 'windows-x64')
        bomb = append_entries(original, [(paths['root'] + '/bomb', b'X' * (2 * 1024 ** 2), stat.S_IFREG | 0o644)])
        with self.assertRaisesRegex(ValueError, 'compression bomb'):
            self.extract(bomb, provenance)
        self.assertFalse((self.folder / 'bundle').exists())
        for constant, limit, message in [('MAX_ENTRIES', 1, 'entry count'), ('MAX_FILE_BYTES', 8, 'file size'),
                                          ('MAX_TOTAL_BYTES', 128, 'total limit')]:
            with self.subTest(limit=constant), patch.object(qa, constant, limit):
                with zipfile.ZipFile(io.BytesIO(original)) as zipped, self.assertRaisesRegex(ValueError, message):
                    qa.inspect_zip(zipped, paths)

    def test_missing_cli_wrong_provenance_and_wrong_mac_identity_are_refused(self):
        for platform, change in [
            ('windows-x64', lambda files, paths, p: files.pop(paths['cli'])),
            ('windows-x64', lambda files, paths, p: files.__setitem__(paths['provenance'], json.dumps(dict(p, app='photo')).encode())),
            ('windows-x64', lambda files, paths, p: files.__setitem__(paths['provenance'], json.dumps(dict(p, inputs={'lock': dict(self.lock, version='99.0.0-kio.1')})).encode())),
            ('macos-arm64', lambda files, paths, p: files.__setitem__(paths['plist'], plistlib.dumps({'CFBundleIdentifier': 'upstream.wordcraft'})))]:
            with self.subTest(platform=platform), tempfile.TemporaryDirectory(dir=self.folder) as temp:
                data, provenance = portable(self.lock, platform, change)
                archive = Path(temp) / 'portable.zip'
                archive.write_bytes(data)
                destination = Path(temp) / 'bundle'
                with self.assertRaises(ValueError):
                    qa.extract_portable(archive, destination, self.lock, platform, provenance)
                self.assertFalse(destination.exists())

    def test_windows_native_architecture_and_exact_compiled_cli_bytes_are_checked(self):
        def wrong_hash(files, paths, provenance):
            provenance['binaries']['cli']['sha256'] = '0' * 64
            files[paths['provenance']] = json.dumps(provenance).encode()
        for change, message in [(lambda f, paths, p: f.__setitem__(paths['cli'], b'not a native executable'), 'native Windows PE'),
                                (wrong_hash, 'differs from compiled manifest')]:
            data, provenance = portable(self.lock, 'windows-x64', change)
            with tempfile.TemporaryDirectory(dir=self.folder) as temp:
                archive = Path(temp) / 'portable.zip'
                archive.write_bytes(data)
                with self.assertRaisesRegex(ValueError, message):
                    qa.extract_portable(archive, Path(temp) / 'bundle', self.lock, 'windows-x64', provenance)

    def test_collection_is_rechecked_against_current_lock_and_actual_release_bytes(self):
        root, collected = self.collection()
        archive, provenance = qa.verified_collection(root, RUN, 'word', 'windows-x64', self.lock)
        self.assertTrue(archive.name.endswith('-windows-x64.zip'))
        self.assertEqual(provenance['inputs']['lock'], self.lock)
        original = (root / 'collection/collection.json').read_bytes()
        for field, value in [('executedNativeBinaries', True), ('publicationPerformed', True), ('status', 'blocked'), ('run', RUN + 1)]:
            changed = dict(collected, **{field: value})
            qa.full.write_json(root / 'collection/collection.json', changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                qa.verified_collection(root, RUN, 'word', 'windows-x64', self.lock)
        (root / 'collection/collection.json').write_bytes(original)
        selected = root / 'collection/selected-lock.json'
        qa.full.write_json(selected, dict(self.lock, version='0.7.0-kio.99'))
        with self.assertRaisesRegex(ValueError, 'current reviewed main'):
            qa.verified_collection(root, RUN, 'word', 'windows-x64', self.lock)
        qa.full.write_json(selected, self.lock)
        archive.write_bytes(archive.read_bytes() + b'changed-after-collection')
        with self.assertRaises(ValueError):
            qa.verified_collection(root, RUN, 'word', 'windows-x64', self.lock)
        outer = root / 'collection/ci-artifact.zip'
        outer.write_bytes(outer.read_bytes() + b'changed-after-collection')
        with self.assertRaisesRegex(ValueError, 'outer artifact changed'):
            qa.verified_collection(root, RUN, 'word', 'windows-x64', self.lock)

    def test_native_environment_excludes_tokens_credentials_and_real_profiles(self):
        inherited = {'PATH': '/known/tools', 'GH_TOKEN': 'private-artifact-token', 'GITHUB_TOKEN': 'private-token',
                     'ACTIONS_RUNTIME_TOKEN': 'private-runtime-token', 'AWS_SECRET_ACCESS_KEY': 'private-key',
                     'HOME': '/real-user', 'CRAFT_FONTS_DIR': '/source/fonts', 'RUSTFLAGS': 'unreviewed'}
        with patch.dict(os.environ, inherited, clear=True):
            environment = qa.child_environment(self.folder / 'profile')
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'AWS_SECRET_ACCESS_KEY', 'CRAFT_FONTS_DIR', 'RUSTFLAGS'):
            self.assertNotIn(key, environment)
        self.assertEqual(environment['PATH'], '/known/tools')
        self.assertEqual(environment['PYTHONUTF8'], '1')
        for key in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TMP', 'TEMP', 'TMPDIR'):
            self.assertTrue(Path(environment[key]).is_dir())
            self.assertTrue(Path(environment[key]).is_relative_to(self.folder))

    def simulate(self, root, native_status='passed', bad_check=False, wrong_version=False, command_failure=False):
        commands = []
        def command(args, environment, cwd, stdout, stderr, timeout):
            commands.append(list(map(str, args)))
            self.assertNotIn('GH_TOKEN', environment)
            self.assertNotIn('GITHUB_TOKEN', environment)
            self.assertFalse(str(cwd).startswith(str(root / 'collection')))
            stdout.write_text('', encoding='utf-8')
            stderr.write_text('', encoding='utf-8')
            if len(commands) == 1:
                self.assertEqual(args[1], '--version')
                self.assertEqual(Path(args[0]), root / 'bundle' / qa.package_paths(self.lock, 'windows-x64')['cli'])
                return 'wrong-cli 0.7.0' if wrong_version else 'wordcraft-cli ' + self.lock['upstreamVersion']
            self.assertEqual(Path(args[0]), Path(sys.executable))
            self.assertEqual(Path(args[1]), SCRIPTS / 'smoke_word.py')
            self.assertEqual(list(map(str, args[2:])), ['--cli', commands[0][0], '--output', str(root / 'smoke')])
            # This ensures the runner did not make the helper's fresh-output
            # directory non-empty by placing its isolated profile inside it.
            self.assertEqual(list((root / 'smoke').iterdir()), [])
            if command_failure:
                raise ValueError('actual native command exit 1')
            report = {'status': native_status, 'app': 'word', 'cliSha256': qa.full.digest(Path(commands[0][0])),
                      'checks': [{'name': str(i), 'passed': not bad_check} for i in range(3)],
                      'steps': [{'label': str(i), 'exitCode': 0} for i in range(3)]}
            qa.full.write_json(root / 'smoke/report.json', report)
            (root / 'smoke/synthetic.docx').write_bytes(b'synthetic utility evidence; no native application ran')
            return ''
        with patch.object(qa.full, 'assert_host'), patch.object(qa, 'run_process', side_effect=command), patch.object(qa.subprocess, 'Popen') as process:
            result = qa.smoke(RUN, 'word', 'windows-x64', root)
            process.assert_not_called()
        return result, commands

    def test_only_actual_matching_successful_scenario_can_mark_qa_passed(self):
        root, _ = self.collection()
        with patch.dict(os.environ, {'GH_TOKEN': 'secret-must-not-reach-native'}):
            result, commands = self.simulate(root)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['executedNativeBinaries'])
        self.assertTrue(result['nativeQaPerformed'])
        self.assertFalse(result['tokenPassedToNative'])
        self.assertFalse(result['publicationPerformed'])
        self.assertFalse(result['installationPerformed'])
        self.assertEqual((result['checks'], result['commands'], len(commands)), (3, 3, 2))
        self.assertTrue(any(item['path'] == 'smoke/synthetic.docx' for item in result['files']))
        with patch.object(qa.full, 'assert_host'), self.assertRaisesRegex(ValueError, 'never reuse'):
            qa.smoke(RUN, 'word', 'windows-x64', root)

    def test_native_qa_uses_the_same_shared_strict_version_helper_with_lock_identity(self):
        root, _ = self.collection()
        with patch.object(qa.smoke_craft, 'pinned_cli_version', wraps=qa.smoke_craft.pinned_cli_version) as helper:
            result, _ = self.simulate(root)
        version = 'wordcraft-cli ' + self.lock['upstreamVersion']
        helper.assert_called_once_with('word', version, self.lock['versionOutputNames']['cli'],
                                       self.lock['upstreamVersion'], self.lock['source']['commit'])
        self.assertEqual(result['cliVersion'], version)

    def test_plan_failed_content_command_and_wrong_native_version_never_pass(self):
        for options in [dict(native_status='not_run'), dict(native_status='failed'), dict(bad_check=True),
                        dict(wrong_version=True), dict(command_failure=True)]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                previous = self.folder
                self.folder = Path(temp)
                try:
                    root, _ = self.collection()
                    with self.assertRaises(ValueError):
                        self.simulate(root, **options)
                    report = qa.json_file(root / 'report.json')
                    self.assertEqual(report['status'], 'failed')
                    self.assertFalse(report['nativeQaPerformed'])
                    self.assertFalse(report['publicationPerformed'])
                    self.assertTrue(report['executedNativeBinaries'])
                finally:
                    self.folder = previous

    def test_timeout_terminates_only_the_qa_child_tree_and_is_an_error(self):
        process = Mock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 1), 0]
        with patch.object(qa.subprocess, 'Popen', return_value=process), patch.object(qa.subprocess, 'run') as taskkill, patch.object(qa.os, 'killpg', create=True) as killpg:
            with self.assertRaisesRegex(AssertionError, 'timed out'):
                qa.run_process(['fixture-never-executed'], {}, self.folder, self.folder / 'out.txt', self.folder / 'err.txt', 1)
            if os.name == 'nt':
                self.assertEqual(taskkill.call_args.args[0][1:], ['/PID', '12345', '/T', '/F'])
                killpg.assert_not_called()
            else:
                killpg.assert_called_once_with(12345, qa.signal.SIGKILL)
                taskkill.assert_not_called()

    def test_manual_workflow_has_fixed_main_repository_read_permissions_and_tokenless_execution(self):
        text = (SCRIPTS.parent / '.github/workflows/native-file-qa.yml').read_text()
        self.assertIn('workflow_dispatch:', text)
        self.assertNotIn('pull_request', text)
        self.assertNotIn('contents: write', text)
        self.assertIn('contents: read\n  actions: read', text)
        self.assertIn("github.repository == 'qptywoei777-rgb/kio-native-apps' && github.ref == 'refs/heads/main'", text)
        self.assertIn('ref: main\n          persist-credentials: false', text)
        self.assertIn('"macos-arm64":"macos-15","windows-x64":"windows-2022"', text)
        execution = text.split('      - name: Extract the whole verified portable bundle', 1)[1].split('      - name:', 1)[0]
        self.assertIn("assert not os.environ.get('GH_TOKEN')", execution)
        self.assertNotIn('env:', execution)
        self.assertNotIn('${{ inputs.', execution)
        self.assertNotIn('publish', execution)
        self.assertNotIn('install', execution)


if __name__ == '__main__':
    unittest.main()
