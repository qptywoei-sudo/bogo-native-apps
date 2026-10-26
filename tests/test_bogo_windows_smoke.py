import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_native as bogo
import smoke_bogo_windows as smoke


class WindowsSmokeInputs(unittest.TestCase):
    def test_exact_fourteen_published_upgrade_pins_keep_each_actual_upgrade_code(self):
        pins = json.loads((ROOT / 'manifests/bogo-legacy-upgrade-inputs.json').read_text())
        self.assertEqual(pins['repository'], 'qptywoei777-rgb/kio-native-apps')
        self.assertEqual({row['id'] for row in pins['applications']}, set(bogo.NAMES))
        for row in pins['applications']:
            current = bogo.load_lock(row['id'])
            self.assertEqual(row['upgradeCode'].upper(), current['bogoOverlay']['windowsInstallerIdentity']['upgradeCode'].upper())
            self.assertEqual(row['bundleId'], current['bundleId'])
            pin = row['windowsMsi']
            legacy = row['name'].replace(' ', '-') + '-' + row['version'] + '-windows-x64.msi'
            self.assertEqual(pin['url'], 'https://github.com/qptywoei777-rgb/kio-native-apps/releases/download/' + row['id'] + '-v' + row['version'] + '/' + legacy)
            self.assertGreater(pin['bytes'], 1000000)
            self.assertRegex(pin['sha256'], r'^[a-f0-9]{64}$')

    def test_every_real_owner_derived_ico_frame_is_read_and_bad_bounds_are_refused(self):
        for app in bogo.NAMES:
            raw = (ROOT / 'assets/bogo-program-icons' / (app + '.ico')).read_bytes()
            frames = smoke.ico_frames(raw)
            self.assertEqual(set(frames), {(s, s) for s in (16, 24, 32, 48, 64, 128, 256)})
            bad = bytearray(raw)
            struct.pack_into('<I', bad, 18, len(raw) + 1)
            with self.assertRaisesRegex(ValueError, 'bounds'):
                smoke.ico_frames(bad)

    def test_actual_pe_identity_rejects_wrong_architecture_and_console_images(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.exe'
            raw = bytearray(256)
            raw[:2] = b'MZ'
            struct.pack_into('<I', raw, 60, 64)
            raw[64:68] = b'PE\0\0'
            struct.pack_into('<H', raw, 68, 0x8664)
            struct.pack_into('<H', raw, 88, 0x20B)
            struct.pack_into('<H', raw, 156, 2)
            path.write_bytes(raw)
            self.assertEqual(smoke.pe_identity(path)['machine'], 'AMD64')
            struct.pack_into('<H', raw, 156, 3)
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'GUI subsystem'):
                smoke.pe_identity(path)
            struct.pack_into('<H', raw, 68, 0x14C)
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'x64'):
                smoke.pe_identity(path)

    def test_child_environment_keeps_home_and_excludes_ci_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'HOME': '/preserved-home', 'GITHUB_TOKEN': 'do-not-inherit', 'PRIVATE_KEY_TEST': 'do-not-inherit', 'ORDINARY_SETTING': 'yes'}):
            environment = smoke.child_environment(Path(directory))
            self.assertEqual(environment['HOME'], '/preserved-home')
            self.assertNotIn('GITHUB_TOKEN', environment)
            self.assertNotIn('PRIVATE_KEY_TEST', environment)
            self.assertEqual(environment['ORDINARY_SETTING'], 'yes')
            self.assertEqual(environment['BOGO_QA_MODE'], '1')
            self.assertTrue(Path(environment['BOGO_QA_ROOT']).is_relative_to(directory))

    def test_installer_gate_refuses_self_hosted_other_context_and_linked_ancestry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            values = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows', 'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_REPOSITORY': 'qptywoei-sudo/bogo-native-apps', 'GITHUB_WORKFLOW': 'Bogo native applications (manual verification)', 'GITHUB_REF': 'refs/heads/codex/bogo-native-rebrand-20261026', 'RUNNER_TEMP': str(base)}
            with patch.object(smoke.sys, 'platform', 'win32'), patch.dict(os.environ, values, clear=True):
                self.assertEqual(smoke.ephemeral_output(base / 'fresh', True), base / 'fresh')
                for key, value in (('RUNNER_ENVIRONMENT', 'self-hosted'), ('GITHUB_REPOSITORY', 'someone/else'), ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_WORKFLOW', 'Unreviewed workflow')):
                    with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                        with self.assertRaises(ValueError):
                            smoke.ephemeral_output(base / 'fresh', True)
                with self.assertRaises(ValueError):
                    smoke.ephemeral_output(base / 'fresh', False)
                with self.assertRaises(ValueError):
                    smoke.ephemeral_output(base, True)
                if os.name != 'nt':
                    link = base / 'linked'
                    link.symlink_to(base, target_is_directory=True)
                    with self.assertRaisesRegex(ValueError, 'ancestry'):
                        smoke.ephemeral_output(link / 'fresh', True)

    @unittest.skipIf(sys.platform == 'win32', 'Non-Windows refusal is verified on other operating systems')
    def test_non_windows_never_attempts_install_or_creates_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'must-not-exist'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_bogo_windows.py'), '--app', 'grid', '--directory', directory, '--output', str(output), '--allow-ephemeral-install'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('explicit opt-in on an ephemeral GitHub-hosted Windows runner', result.stderr)
            self.assertFalse(output.exists())

    def test_complete_source_export_carries_the_windows_verification_inputs(self):
        paths = {relative for relative, _ in bogo.public_files(bogo.load_lock('grid'))}
        for required in ('scripts/smoke_bogo_windows.py', 'tests/test_bogo_windows_smoke.py', 'manifests/bogo-legacy-upgrade-inputs.json', '.github/workflows/full-native-launcher.yml'):
            self.assertIn(required, paths)
        self.assertTrue({row['patch'] for row in json.loads(bogo.CATALOG.read_text())['applications']}.issubset(paths))


if __name__ == '__main__':
    unittest.main()
