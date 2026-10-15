"""Exercise Photo's real orchestrator boundary; never compile or launch native code."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_native as full


class PhotoOriginalTestProfile(unittest.TestCase):
    def build_fixture(self, app, platform, env, failure=None):
        lock = full.load_lock(app)
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as mocks:
            work = Path(temporary)
            binaries = {kind: work / lock['binaries'][kind] for kind in ('app', 'cli')}
            for binary in binaries.values():
                binary.write_bytes(b'nonexecutable fixture')
            mocks.enter_context(patch.object(full, 'assert_host'))
            mocks.enter_context(patch.object(full, 'prepared', return_value=(work, work / 'source', work / 'fonts', {})))
            mocks.enter_context(patch.object(full, 'build_env', return_value=env))
            mocks.enter_context(patch.object(full, 'binary_paths', return_value=binaries))
            versions = mocks.enter_context(patch.object(full, 'check_versions', return_value={}))
            probe = mocks.enter_context(patch.object(full, 'check_cli_probe', return_value={}))
            written = mocks.enter_context(patch.object(full, 'write_json'))

            def invoke(command, **kwargs):
                if failure is not None and failure in command:
                    raise subprocess.CalledProcessError(101, command)
                return 'rustc 1.95.0 (mock; no native execution)'

            calls = mocks.enter_context(patch.object(full, 'run', side_effect=invoke))
            if failure is not None:
                with self.assertRaises(subprocess.CalledProcessError):
                    full.build(SimpleNamespace(platform=platform), lock)
                written.assert_not_called()
                versions.assert_not_called()
                probe.assert_not_called()
                return lock, calls.call_args_list, None
            full.build(SimpleNamespace(platform=platform), lock)
            written.assert_called_once()
            return lock, calls.call_args_list, written.call_args.args[1]

    def test_both_platforms_keep_full_release_heif_apps_and_complete_default_profile_tests(self):
        for platform, target in full.common.TARGETS.items():
            with self.subTest(platform=platform):
                env = {'CARGO_BUILD_JOBS': '7', 'CRAFT_FONTS_REQUIRED': '1', 'KIO_RELEASE_VERSION': '0.9.0-kio.1'}
                lock, calls, record = self.build_fixture('photo', platform, env)
                cargo = ['rustup', 'run', '1.95.0', 'cargo']
                builds = [call for call in calls if 'build' in call.args[0]]
                self.assertEqual(len(builds), 1)
                self.assertEqual(builds[0].args[0], cargo + lock['cargoArgs'] + ['--target', target])
                self.assertIn('--release', builds[0].args[0])
                self.assertEqual(builds[0].args[0][builds[0].args[0].index('--features') + 1], 'heif')
                self.assertIs(builds[0].kwargs['env'], env)
                tests = [call for call in calls if 'test' in call.args[0]]
                expected = cargo + ['test', '--locked', '--target', target, '-p', 'photocraft-engine', '-p', 'photocraft-io']
                self.assertEqual(len(tests), 1)
                self.assertEqual(tests[0].args[0], expected)
                execution = record['checks']['originalCoreTestExecution']
                self.assertEqual(execution['command'], expected)
                self.assertEqual(execution['profile'], 'test')
                self.assertEqual(execution['profileBasis'], 'original-cargo-xtask-ci')
                self.assertEqual(execution['packages'], ['photocraft-engine', 'photocraft-io'])
                self.assertEqual(record['cargoArgs'], lock['cargoArgs'])
                self.assertEqual(record['features'], lock['features'])
                self.assertEqual(record['checks']['originalCoreTests'], 'passed')

    def test_windows_serializes_only_unit_compilation_with_a_new_environment_copy(self):
        for setting in (None, '7'):
            with self.subTest(previousJobs=setting):
                env = {'CRAFT_FONTS_REQUIRED': '1', 'UNCHANGED': 'sentinel'}
                if setting is not None:
                    env['CARGO_BUILD_JOBS'] = setting
                before = dict(env)
                _, calls, record = self.build_fixture('photo', 'windows-x64', env)
                tests = next(call for call in calls if 'test' in call.args[0])
                self.assertEqual(env, before)
                self.assertIsNot(tests.kwargs['env'], env)
                self.assertEqual(tests.kwargs['env'], {**before, 'CARGO_BUILD_JOBS': '1'})
                for call in calls:
                    if call is not tests:
                        self.assertIs(call.kwargs['env'], env)
                execution = record['checks']['originalCoreTestExecution']
                self.assertEqual(execution['compilerJobsSetting'], '1')
                self.assertEqual(execution['compilerJobsOverride'], '1')

    def test_mac_unit_environment_is_the_same_object_and_has_no_jobs_override(self):
        for env in ({}, {'CARGO_BUILD_JOBS': '7'}):
            before = dict(env)
            _, calls, record = self.build_fixture('photo', 'macos-arm64', env)
            self.assertEqual(env, before)
            for call in calls:
                self.assertIs(call.kwargs['env'], env)
            execution = record['checks']['originalCoreTestExecution']
            self.assertIsNone(execution['compilerJobsOverride'])
            self.assertEqual(execution['compilerJobsSetting'], env.get('CARGO_BUILD_JOBS', 'cargo-default'))

    def test_other_eleven_apps_keep_exact_release_commands_and_the_original_environment(self):
        others = sorted(set(full.IDS) - {'cad', 'photo'})
        self.assertEqual(len(others), 11)
        for app in others:
            for platform, target in full.common.TARGETS.items():
                with self.subTest(app=app, platform=platform):
                    env = {'CARGO_BUILD_JOBS': '7', 'UNCHANGED': app}
                    lock, calls, record = self.build_fixture(app, platform, env)
                    tests = [call for call in calls if 'test' in call.args[0]]
                    expected = ['rustup', 'run', '1.95.0', 'cargo', 'test', '--release', '--locked', '--target', target]
                    for package in lock['testPackages']:
                        expected.extend(['-p', package])
                    self.assertEqual(tests[0].args[0], expected)
                    for call in calls:
                        self.assertIs(call.kwargs['env'], env)
                    self.assertEqual(env, {'CARGO_BUILD_JOBS': '7', 'UNCHANGED': app})
                    execution = record['checks']['originalCoreTestExecution']
                    self.assertEqual(execution['profile'], 'release')
                    self.assertIsNone(execution['compilerJobsOverride'])
                    self.assertNotIn('originalProfileEvidence', execution)

    def test_core_failure_cannot_write_success_provenance_or_probe_binaries(self):
        for platform in full.common.TARGETS:
            with self.subTest(platform=platform):
                _, calls, record = self.build_fixture('photo', platform, {}, failure='test')
                self.assertIsNone(record)
                self.assertEqual(sum('test' in call.args[0] for call in calls), 1)

    def test_release_build_failure_cannot_start_tests_or_write_provenance(self):
        for platform in full.common.TARGETS:
            with self.subTest(platform=platform):
                _, calls, record = self.build_fixture('photo', platform, {}, failure='build')
                self.assertIsNone(record)
                self.assertEqual(sum('test' in call.args[0] for call in calls), 0)

    def test_provenance_binds_the_portable_original_profile_evidence_bytes(self):
        for platform in full.common.TARGETS:
            with self.subTest(platform=platform):
                _, _, record = self.build_fixture('photo', platform, {})
                binding = record['checks']['originalCoreTestExecution']['originalProfileEvidence']
                self.assertEqual(binding['path'], 'manifests/build-prerequisites-photo-tests.json')
                data = (full.ROOT / binding['path']).read_bytes()
                self.assertEqual(binding['bytes'], len(data))
                self.assertEqual(binding['sha256'], hashlib.sha256(data).hexdigest())

    def test_source_bundle_contains_exact_original_inventory_and_the_regression(self):
        lock = full.load_lock('photo')
        relative = 'manifests/build-prerequisites-photo-tests.json'
        inputs = dict(full.public_files(lock))
        self.assertIn(relative, inputs)
        self.assertIn('tests/test_photo_test_profile.py', inputs)
        evidence = json.loads(inputs[relative].read_text(encoding='utf-8'))
        self.assertEqual(evidence['upstream'], lock['source'])
        self.assertFalse(evidence['nativeTestExecuted'])
        self.assertFalse(evidence['wholeNativeBuildExecuted'])
        self.assertFalse(evidence['applicationSourceModified'])
        self.assertFalse(evidence['runtimeOrLockChanged'])
        self.assertFalse(evidence['workflowTimeoutChanged'])
        original_files = evidence['originalSourceProof']
        self.assertEqual({x['path'] for x in original_files}, {'Cargo.toml', '.github/workflows/ci.yml', 'xtask/src/main.rs', 'xtask/src/corpus.rs', 'crates/engine/Cargo.toml', 'crates/io/Cargo.toml'})
        inventory = evidence['selectedRustSourceInventory']
        self.assertEqual(len(inventory), 369)
        self.assertEqual(len({x['path'] for x in inventory}), 369)
        self.assertEqual(sum(x['path'].startswith('crates/engine/') for x in inventory), 259)
        self.assertEqual(sum(x['path'].startswith('crates/io/') for x in inventory), 110)
        for row in original_files + inventory:
            relative_path = PurePosixPath(row['path'])
            self.assertFalse(relative_path.is_absolute())
            self.assertNotIn('..', relative_path.parts)
            self.assertTrue(row['preparedByteIdentical'])
            self.assertRegex(row['sha256'], r'^[0-9a-f]{64}$')
            self.assertGreater(row['bytes'], 0)
        encoded = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(evidence['selectedRustSourceInventorySha256'], hashlib.sha256(encoded).hexdigest())
        counts = evidence['staticCoverageAssessment']
        for key, expected in {'rustSourceFilesUnchanged': 369, 'unitTestAttributesUnchanged': 2354,
                              'assertionMacroCallsUnchanged': 11483, 'existingIgnoreAttributesUnchanged': 24,
                              'profileConditionalDefinitionsInSelectedCore': 0, 'profileEnvironmentReadsInSelectedCore': 0}.items():
            self.assertEqual(counts[key], expected)
        self.assertTrue(counts['countsAreStaticDefinitionsNotExecutedTests'])
        self.assertTrue(counts['optionalCorpusFeatureAndOriginalIgnoredTestsNotClaimedExecuted'])
        self.assertEqual(evidence['originalTestProfile']['command'], 'cargo test --workspace')
        self.assertEqual(evidence['originalTestProfile']['ci']['command'], 'cargo test --workspace --locked --features heif')
        self.assertEqual(evidence['approvedExecution']['shippedGuiCliCargoArgsUnchanged'], lock['cargoArgs'])
        self.assertEqual(evidence['approvedExecution']['shippedGuiCliFeaturesUnchanged'], lock['features'])
        actual = evidence['actualDeadlineEvidence']
        self.assertEqual((actual['run'], actual['job']), (38798362753, 116640950969))
        self.assertEqual(actual['annotation'], 'The job has exceeded the maximum execution time of 3h0m0s')
        self.assertTrue(actual['fullReleaseGuiCliCompilationCompleted'])
        self.assertFalse(actual['originalUnitExecutionMarkersObserved'])
        self.assertFalse(actual['packagingStarted'])


if __name__ == '__main__':
    unittest.main()
