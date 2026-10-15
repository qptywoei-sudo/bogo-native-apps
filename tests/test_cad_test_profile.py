"""Exercise the real build boundary without compiling or launching native code."""
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_native as full


class CadOriginalTestProfile(unittest.TestCase):
    def build_fixture(self, app, platform, env, fail_tests=False):
        lock = full.load_lock(app)
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as mocks:
            work = Path(temporary)
            binaries = {'app': work / lock['binaries']['app'], 'cli': work / lock['binaries']['cli']}
            for binary in binaries.values():
                binary.write_bytes(b'fixture only; never executed')
            mocks.enter_context(patch.object(full, 'assert_host'))
            mocks.enter_context(patch.object(full, 'prepared', return_value=(work, work / 'source', work / 'fonts', {})))
            mocks.enter_context(patch.object(full, 'build_env', return_value=env))
            mocks.enter_context(patch.object(full, 'binary_paths', return_value=binaries))
            versions = mocks.enter_context(patch.object(full, 'check_versions', return_value={}))
            mocks.enter_context(patch.object(full, 'check_cli_probe', return_value={}))
            written = mocks.enter_context(patch.object(full, 'write_json'))

            def invoke(command, **kwargs):
                if fail_tests and 'test' in command:
                    raise subprocess.CalledProcessError(101, command)
                return 'rustc 1.95.0 (fixture)'

            calls = mocks.enter_context(patch.object(full, 'run', side_effect=invoke))
            if fail_tests:
                with self.assertRaises(subprocess.CalledProcessError):
                    full.build(SimpleNamespace(platform=platform), lock)
                written.assert_not_called()
                versions.assert_not_called()
                return lock, calls.call_args_list, None
            full.build(SimpleNamespace(platform=platform), lock)
            written.assert_called_once()
            return lock, calls.call_args_list, written.call_args.args[1]

    def test_cad_both_platforms_keep_the_full_release_app_and_all_default_profile_core_tests(self):
        for platform, target in full.common.TARGETS.items():
            with self.subTest(platform=platform):
                env = {'CARGO_BUILD_JOBS': '7', 'CRAFT_FONTS_REQUIRED': '1', 'KIO_RELEASE_VERSION': 'fixture'}
                original_env = dict(env)
                lock, calls, record = self.build_fixture('cad', platform, env)
                cargo = ['rustup', 'run', '1.95.0', 'cargo']
                app = [call for call in calls if 'build' in call.args[0]]
                self.assertEqual(len(app), 1)
                self.assertEqual(app[0].args[0], cargo + lock['cargoArgs'] + ['--target', target])
                self.assertIs(app[0].kwargs['env'], env)
                tests = [call for call in calls if 'test' in call.args[0]]
                self.assertEqual(len(tests), 1)
                expected = cargo + ['test', '--locked', '--target', target, '-p', 'cadcraft-engine', '-p', 'cadcraft-io']
                self.assertEqual(tests[0].args[0], expected)
                execution = record['checks']['originalCoreTestExecution']
                self.assertEqual(execution['profile'], 'test')
                self.assertEqual(execution['command'], expected)
                self.assertEqual(execution['packages'], lock['testPackages'])
                self.assertEqual(execution['profileBasis'], 'original-cargo-xtask-ci')
                self.assertEqual(env, original_env)
                if platform == 'windows-x64':
                    self.assertIsNot(tests[0].kwargs['env'], env)
                    self.assertEqual(tests[0].kwargs['env'], {**env, 'CARGO_BUILD_JOBS': '1'})
                    self.assertEqual(execution['compilerJobsOverride'], '1')
                    self.assertEqual(execution['compilerJobsSetting'], '1')
                else:
                    self.assertIs(tests[0].kwargs['env'], env)
                    self.assertIsNone(execution['compilerJobsOverride'])
                    self.assertEqual(execution['compilerJobsSetting'], '7')
                evidence = full.ROOT / execution['originalProfileEvidence']['path']
                self.assertEqual(execution['originalProfileEvidence']['sha256'], full.digest(evidence))
                self.assertEqual(execution['originalProfileEvidence']['bytes'], evidence.stat().st_size)

    def test_the_other_eleven_apps_and_platforms_retain_release_core_tests_and_the_identical_environment(self):
        for app in sorted(set(full.IDS) - {'cad', 'photo'}):
            for platform, target in full.common.TARGETS.items():
                with self.subTest(app=app, platform=platform):
                    env = {'CARGO_BUILD_JOBS': '7', 'CRAFT_FONTS_REQUIRED': '1'}
                    lock, calls, record = self.build_fixture(app, platform, env)
                    tests = [call for call in calls if 'test' in call.args[0]]
                    core = ['rustup', 'run', '1.95.0', 'cargo', 'test', '--release', '--locked', '--target', target]
                    for package in lock['testPackages']:
                        core += ['-p', package]
                    self.assertEqual(tests[0].args[0], core)
                    for call in calls:
                        self.assertIs(call.kwargs['env'], env)
                    self.assertEqual(env, {'CARGO_BUILD_JOBS': '7', 'CRAFT_FONTS_REQUIRED': '1'})
                    execution = record['checks']['originalCoreTestExecution']
                    self.assertEqual(execution['profile'], 'release')
                    self.assertEqual(execution['command'], core)
                    self.assertIsNone(execution['compilerJobsOverride'])
                    self.assertNotIn('originalProfileEvidence', execution)

    def test_cad_core_failure_propagates_without_a_success_provenance_or_binary_probe(self):
        for platform in full.common.TARGETS:
            with self.subTest(platform=platform):
                _, calls, record = self.build_fixture('cad', platform, {}, fail_tests=True)
                self.assertIsNone(record)
                self.assertEqual(sum('test' in call.args[0] for call in calls), 1)

    def test_the_original_profile_and_test_inventory_evidence_is_shipped_with_corresponding_source(self):
        relative = 'manifests/build-prerequisites-cad-tests.json'
        lock = full.load_lock('cad')
        inputs = dict(full.public_files(lock))
        self.assertIn(relative, inputs)
        self.assertIn('tests/test_cad_test_profile.py', inputs)
        evidence = json.loads((full.ROOT / relative).read_text())
        self.assertEqual(evidence['upstream']['commit'], lock['source']['commit'])
        self.assertEqual(evidence['upstream']['sha256'], lock['source']['sha256'])
        self.assertEqual(evidence['originalTestProfile']['command'], 'cargo test --workspace')
        self.assertEqual(evidence['staticCoverageAssessment']['unitTestAttributesUnchanged'], 1239)
        self.assertEqual(evidence['staticCoverageAssessment']['profileConditionalDefinitionsInSelectedCore'], 0)
        self.assertFalse(evidence['nativeTestExecuted'])
        self.assertFalse(evidence['wholeNativeBuildExecuted'])


if __name__ == '__main__':
    unittest.main()
