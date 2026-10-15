import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('launcher_native', SCRIPTS / 'launcher_native.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherNativeGuards(unittest.TestCase):
    def test_full_original_gui_and_native_tests_with_no_invented_cli(self):
        lock = launcher.load_lock()
        self.assertEqual(lock['cargoPackages'], ['artcraft-launcher'])
        self.assertEqual(lock['binaries'], {'app': 'artcraft-launcher', 'cli': None})
        self.assertEqual(len(lock['testPackages']), 3)
        self.assertEqual(len(launcher.full.IDS), 13)
        self.assertNotIn('launcher', launcher.full.IDS)
        self.assertIsNone(lock['fonts'])

    def test_context_restores_original_generic_helpers_even_after_failure(self):
        old = launcher.full.paths, launcher.full.public_files, launcher.full.CATALOG
        with self.assertRaises(RuntimeError):
            with launcher.helpers():
                self.assertEqual(launcher.full.paths, launcher.paths)
                self.assertEqual(launcher.full.CATALOG, launcher.LOCK)
                raise RuntimeError('test')
        self.assertEqual(old, (launcher.full.paths, launcher.full.public_files, launcher.full.CATALOG))

    def test_source_and_patch_and_full_default_features_cannot_be_substituted(self):
        original = json.loads(launcher.LOCK.read_text())
        for variant in ['source', 'patch', 'features', 'binary', 'mirror']:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                changed = json.loads(json.dumps(original))
                if variant == 'source': changed['source']['url'] = 'https://attacker.invalid/source.tar.gz'
                if variant == 'patch': changed['branding']['sha256'] = '0' * 64
                if variant == 'features': changed['cargoArgs'] += ['--no-default-features']
                if variant == 'binary': changed['binaries']['app'] = 'other'
                if variant == 'mirror': changed['features']['developerLocalMirrorEnabled'] = True
                p = Path(tmp) / 'lock.json'
                p.write_text(json.dumps(changed))
                with patch.object(launcher, 'LOCK', p), self.assertRaises(ValueError):
                    launcher.load_lock()

    def test_kio_version_and_original_environment_spelling_static_crt_and_no_remote_override(self):
        lock = launcher.load_lock()
        with patch.dict(os.environ, {'ARTCRAFT_LAUNCHER_DOWNLOAD_BASE': 'https://untrusted.invalid', 'ARTCRAFT_LAUNCHER_PRETEND_VERSION': '9.0.0', 'CRAFT_FONTS_DIR': '/unrelated'}):
            env = launcher.build_env(lock, Path('/fonts'), Path('/target'), 'x86_64-pc-windows-msvc')
        self.assertEqual(env['KIO_RELEASE_VERSION'], lock['version'])
        self.assertEqual(env['ARTCRAFT_LAUNCHER_VERSION'], lock['version'])
        self.assertEqual(env['ARTCRAFT_LAUNCHER_BUILD_SHA'], launcher.SOURCE_COMMIT)
        self.assertEqual(env['ARTCRAFT_LAUNCHER_REQUIRE_WINRES'], '1')
        self.assertEqual(env['CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS'], '-C target-feature=+crt-static')
        for key in ['CRAFT_FONTS_DIR', 'ARTCRAFT_LAUNCHER_DOWNLOAD_BASE', 'ARTCRAFT_LAUNCHER_PRETEND_VERSION']:
            self.assertNotIn(key, env)

    def test_native_version_output_requires_real_original_identity(self):
        lock = launcher.load_lock()
        with patch.object(launcher, 'run', return_value='artcraft-launcher 0.4.1'):
            launcher.check_versions(lock, {'app': Path('/app')}, {})
        for value in ['wordcraft 0.4.1', 'artcraft-launcher 0.4.2']:
            with patch.object(launcher, 'run', return_value=value), self.assertRaises(ValueError):
                launcher.check_versions(lock, {'app': Path('/app')}, {})

    def test_actual_msi_database_identity_checks_app_publisher_and_numeric_upstream(self):
        lock = launcher.load_lock()
        expected = {'ProductName': 'KIO Launcher', 'Manufacturer': 'KIO', 'ProductVersion': '0.4.1'}
        with patch.object(launcher, 'run', return_value=json.dumps(expected)) as command:
            self.assertEqual(launcher.validate_msi(lock, Path('/actual.msi')), expected)
            self.assertIn('WindowsInstaller.Installer', command.call_args.args[0][-1])
        for key, wrong in [('ProductName', 'KIO Word'), ('Manufacturer', 'Learning Machines LLC'), ('ProductVersion', '0.4.2')]:
            value = dict(expected); value[key] = wrong
            with patch.object(launcher, 'run', return_value=json.dumps(value)), self.assertRaises(ValueError):
                launcher.validate_msi(lock, Path('/actual.msi'))

    def test_public_source_inputs_explicitly_include_launcher_patch_lock_tests_and_workflow(self):
        lock = launcher.load_lock()
        files = dict(launcher.public_files(lock))
        self.assertIn('scripts/launcher_native.py', files)
        self.assertIn('manifests/launcher.lock.json', files)
        self.assertIn('tests/test_launcher_native.py', files)
        self.assertIn('.github/workflows/full-native-launcher.yml', files)
        self.assertEqual(len([x for x in files if x.endswith('.patch')]), 1)
        self.assertNotIn('manifests/full-native-apps.json', files)

    def test_launcher_release_is_bound_to_own_app_and_exact_files_and_digests(self):
        lock = launcher.load_lock()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            base = launcher.full.artifact_base(lock, 'windows-x64')
            for suffix in ['.zip', '.msi', '-provenance.json']:
                (directory / (base + suffix)).write_bytes(b'unit fixture')
            launcher.full.finalize(directory, lock, 'windows-x64')
            self.assertEqual(len(launcher.full.verify(directory, lock, 'windows-x64')), 5)
            (directory / (base + '.msi')).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                launcher.full.verify(directory, lock, 'windows-x64')


if __name__ == '__main__':
    unittest.main()
