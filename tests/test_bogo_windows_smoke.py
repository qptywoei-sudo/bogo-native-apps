import json
import copy
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_native as bogo
import smoke_bogo_windows as smoke


class WindowsSmokeInputs(unittest.TestCase):
    def test_native_startup_waits_for_actual_visible_bogo_window_after_slow_first_frame(self):
        elapsed = [0.0]
        hidden = {'title': 'Bogo Effect', 'windowHandle': 123, 'visible': False}
        def scan():
            return [{**hidden, 'visible': elapsed[0] >= 35}]
        def pause(seconds):
            elapsed[0] += seconds
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.json'
            own, windows = smoke.wait_for_native_window(SimpleNamespace(pid=42, poll=lambda: None), scan, path,
                clock=lambda: elapsed[0], pause=pause)
            self.assertTrue(own['visible'])
            self.assertGreaterEqual(elapsed[0], 35)
            self.assertLess(elapsed[0], 36)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['status'], 'visible-bogo-window')
            self.assertEqual(receipt['ownProcessWindows'], windows)

    def test_native_startup_deadline_never_accepts_hidden_bogo_or_visible_old_title(self):
        elapsed = [0.0]
        rows = [{'title': 'Bogo Effect', 'windowHandle': 123, 'visible': False},
                {'title': 'KIO Effect', 'windowHandle': 124, 'visible': True}]
        def pause(seconds):
            elapsed[0] += seconds
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.json'
            with self.assertRaisesRegex(ValueError, 'within 120 seconds'):
                smoke.wait_for_native_window(SimpleNamespace(pid=42, poll=lambda: None), lambda: rows, path,
                    clock=lambda: elapsed[0], pause=pause)
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['status'], 'deadline-expired')
            self.assertEqual(receipt['elapsedSeconds'], 120)
            self.assertTrue(receipt['processAlive'])
            self.assertEqual(receipt['ownProcessWindows'], rows)

    def test_native_startup_process_exit_is_failure_even_if_window_title_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.json'
            with self.assertRaisesRegex(ValueError, 'GUI exited'):
                smoke.wait_for_native_window(SimpleNamespace(pid=42, poll=lambda: 9),
                    lambda: [{'title': 'Bogo Effect', 'windowHandle': 123, 'visible': True}], path,
                    clock=lambda: 0, pause=lambda seconds: self.fail('exited process must not wait'))
            receipt = json.loads(path.read_text())
            self.assertEqual(receipt['returnCode'], 9)
            self.assertFalse(receipt['processAlive'])

    def test_msi_guids_compare_exact_uuid_identity_with_balanced_optional_braces(self):
        guid = 'F98E3616-1291-59D9-AEFD-8E055186CBD4'
        self.assertEqual(smoke.canonical_guid(guid), smoke.canonical_guid('{' + guid.lower() + '}'))
        self.assertEqual(smoke.canonical_guid(guid.lower()), guid)
        self.assertNotEqual(smoke.canonical_guid(guid), smoke.canonical_guid('48194C34-8826-5C1A-9A37-764B83BD695E'))
        for invalid in (None, '', '{' + guid, guid + '}', '{{' + guid + '}}', ' ' + guid, guid + ' ', guid.replace('-', ''), 'urn:uuid:' + guid, guid + '-extra', guid[:-1] + 'G'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                smoke.canonical_guid(invalid)

    def test_exact_fourteen_published_upgrade_pins_keep_each_actual_upgrade_code(self):
        pins = json.loads((ROOT / 'manifests/bogo-legacy-upgrade-inputs.json').read_text(encoding='utf-8'))
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

    def test_runtime_png_is_exactly_the_compiled_native_viewport_source_for_all_fourteen(self):
        with tempfile.TemporaryDirectory() as directory:
            for app in bogo.NAMES:
                output = Path(directory) / app
                output.mkdir()
                png, sha = smoke.runtime_source_png(app, output)
                self.assertEqual(smoke.digest(png), sha)
                lock = bogo.load_lock(app)
                path = 'assets/app-icon/hicolor/256x256/apps/com.kio.' + app + '.png'
                expected = next(row['after'] for row in lock['bogoOverlay']['files'] if row['path'] == path)
                self.assertEqual(expected, {'sha256': sha, 'bytes': png.stat().st_size})

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
                with patch.dict(os.environ, {'GITHUB_WORKFLOW': 'Bogo Windows artifact acceptance (manual)'}):
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
        for required in ('scripts/smoke_bogo_windows.py', 'tests/test_bogo_windows_smoke.py', 'manifests/bogo-legacy-upgrade-inputs.json', 'manifests/bogo-prior-bogo-upgrade-inputs.json', '.github/workflows/full-native-launcher.yml'):
            self.assertIn(required, paths)
        self.assertTrue({row['patch'] for row in json.loads(bogo.CATALOG.read_text(encoding='utf-8'))['applications']}.issubset(paths))


class PublishedBogoUpgrade(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((ROOT / 'manifests/bogo-prior-bogo-upgrade-inputs.json').read_text(encoding='utf-8'))

    def target(self, app='design', revision=2):
        lock = copy.deepcopy(bogo.load_lock(app))
        lock['version'] = lock['upstreamVersion'] + '-bogo.' + str(revision)
        return lock

    def properties(self, row, current=False):
        return {'ProductName': row['name'], 'Manufacturer': 'Bogo', 'ProductVersion': row['windowsProductVersion'],
                'ProductCode': '{337A28A1-F51B-4D50-9BBF-72CEAFABAA30}' if current else row['productCode'], 'UpgradeCode': row['upgradeCode']}

    def original_report(self, current):
        return {'status': 'running', 'actualMsiUpgrade': {'bogo': current, 'oldInstallExit': 0, 'upgradeExit': 0,
                'sameUpgradeCode': True, 'oldProductRemoved': True, 'newProductInstalled': True,
                'legacyCustomInstallDirectoryPreservedWithoutOverride': True}}

    def environment(self, base):
        return {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'GITHUB_REPOSITORY': 'qptywoei-sudo/bogo-native-apps', 'GITHUB_WORKFLOW': 'Bogo native applications (manual verification)',
                'GITHUB_REF': 'refs/heads/codex/bogo-native-rebrand-20261026', 'RUNNER_TEMP': str(base)}

    def test_pins_are_exact_actual_published_bogo1_msi_bytes_not_legacy_aliases(self):
        expected = {'design': (56530623, '69d9eb651ed07c7d9f372d5ee9af938acc6d698927a5e500043c8e81e34efa6d'),
                    'grid': (14626090, 'b574ea1562e9cead555c36a1bd0980a44e774d33903dcde7530e10df1fe01619')}
        for app, (size, sha) in expected.items():
            row = smoke.prior_bogo_input(self.target(app), self.pins)
            self.assertEqual((row['windowsMsi']['bytes'], row['windowsMsi']['sha256']), (size, sha))
            self.assertIn('/qptywoei-sudo/bogo-native-apps/releases/download/' + app + '-v', row['windowsMsi']['url'])
            self.assertTrue(row['version'].endswith('-bogo.1'))
            self.assertNotIn('KIO-', row['windowsMsi']['filename'])

    def test_only_design_grid_revision2_plus_require_additional_phase(self):
        for app in bogo.NAMES:
            self.assertIsNone(smoke.prior_bogo_input(self.target(app, 1), self.pins))
            selected = smoke.prior_bogo_input(self.target(app, 2), self.pins)
            self.assertEqual(selected is not None, app in ('design', 'grid'))
        for revision in (2, 3, 20):
            self.assertIsNotNone(smoke.prior_bogo_input(self.target('grid', revision), self.pins))
        lock = self.target(); lock['version'] = '0.8.0-kio.2'
        with self.assertRaises(ValueError):
            smoke.prior_bogo_input(lock, self.pins)

    def test_bad_repository_family_product_duplicate_and_pin_inputs_are_refused(self):
        changes = [lambda p: p.update(repository='qptywoei777-rgb/kio-native-apps'),
                   lambda p: p.update(schema=True),
                   lambda p: p['applications'].append(copy.deepcopy(p['applications'][0])),
                   lambda p: p['applications'][0].update(name='KIO Design'),
                   lambda p: p['applications'][0].update(version='0.8.0-kio.1'),
                   lambda p: p['applications'][0].update(bundleId='com.other.design'),
                   lambda p: p['applications'][0]['windowsMsi'].update(url=p['applications'][0]['windowsMsi']['url'] + '?token=x'),
                   lambda p: p['applications'][0]['windowsMsi'].update(bytes=True),
                   lambda p: p['applications'][0]['windowsMsi'].update(sha256='not-a-sha'),
                   lambda p: p['applications'][0].update(productCode='not-a-guid')]
        for change in changes:
            pins = copy.deepcopy(self.pins); change(pins)
            with self.subTest(pins=pins), self.assertRaises(ValueError):
                smoke.prior_bogo_input(self.target(), pins)
        lock = self.target(); lock['bogoOverlay']['windowsInstallerIdentity']['upgradeCode'] = 'F98E3616-1291-59D9-AEFD-8E055186CBD4'
        with self.assertRaisesRegex(ValueError, 'preserved app identity'):
            smoke.prior_bogo_input(lock, self.pins)

    def test_actual_prior_msi_identity_cannot_be_old_kio_wrong_version_or_same_product(self):
        lock = self.target(); row = smoke.prior_bogo_input(lock, self.pins); previous = self.properties(row); current = self.properties(row, True)
        smoke.validate_prior_bogo_msi(row, previous, current, lock)
        for key, value in [('ProductName', 'KIO Design'), ('Manufacturer', 'KIO'), ('ProductVersion', '0.7.0'),
                           ('ProductCode', current['ProductCode']), ('UpgradeCode', 'F98E3616-1291-59D9-AEFD-8E055186CBD4')]:
            changed = {**previous, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                smoke.validate_prior_bogo_msi(row, changed, current, lock)
        with self.assertRaisesRegex(ValueError, 'distinct current ProductCode'):
            smoke.validate_prior_bogo_msi(row, previous, previous, lock)

    def test_downloaded_pin_mismatch_is_rejected_before_any_msi_execution(self):
        lock = self.target(); row = smoke.prior_bogo_input(lock, self.pins)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            def download(_url, path):
                Path(path).write_bytes(b'not-the-published-installer')
            with patch.object(smoke.urllib.request, 'urlretrieve', side_effect=download), patch.object(smoke, 'msi_run') as install, patch.object(smoke, 'msi_properties') as properties:
                with self.assertRaisesRegex(ValueError, 'published size/SHA-256 pin'):
                    smoke.prepare_prior_bogo_upgrade(lock, output, self.properties(row, True))
                properties.assert_not_called(); install.assert_not_called()

    def test_existing_published_bogo_is_refused_during_preflight_not_uninstalled(self):
        lock = self.target(); row = copy.deepcopy(smoke.prior_bogo_input(lock, self.pins)); payload = b'x' * 1_000_000
        row['windowsMsi'].update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(smoke, 'prior_bogo_input', return_value=row), patch.object(smoke.urllib.request, 'urlretrieve', side_effect=lambda _url, path: Path(path).write_bytes(payload)), patch.object(smoke, 'msi_properties', return_value=self.properties(row)), patch.object(smoke, 'product_state', return_value=5), patch.object(smoke, 'msi_run') as install:
                with self.assertRaisesRegex(ValueError, 'pre-existing published Bogo'):
                    smoke.prepare_prior_bogo_upgrade(lock, Path(directory), self.properties(row, True))
                install.assert_not_called()

    def test_correct_size_wrong_sha_and_wrong_installed_executable_fail_closed(self):
        lock = self.target(); row = copy.deepcopy(smoke.prior_bogo_input(lock, self.pins)); payload = b'x' * 1_000_000
        row['windowsMsi'].update(bytes=len(payload), sha256='a' * 64)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(smoke, 'prior_bogo_input', return_value=row), patch.object(smoke.urllib.request, 'urlretrieve', side_effect=lambda _url, path: Path(path).write_bytes(payload)), patch.object(smoke, 'msi_properties') as properties:
                with self.assertRaisesRegex(ValueError, 'published size/SHA-256 pin'):
                    smoke.prepare_prior_bogo_upgrade(lock, output, self.properties(row, True))
                properties.assert_not_called()
            executable = output / (lock['name'] + '.exe'); executable.write_bytes(b'wrong executable')
            with patch.object(smoke, 'file_version', return_value={'ProductName': lock['name']}):
                with self.assertRaisesRegex(ValueError, 'authenticated new native build provenance'):
                    smoke.installed_gui_binary(output, lock, {'sha256': 'b' * 64, 'bytes': executable.stat().st_size})

    def test_additional_phase_keeps_original_ephemeral_runner_and_explicit_opt_in_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); output = base / 'owned'; output.mkdir()
            with patch.object(smoke, 'msi_run') as install:
                with self.assertRaisesRegex(ValueError, 'ephemeral GitHub-hosted Windows runner'):
                    smoke.actual_prior_bogo_upgrade({}, {}, None, {}, {}, output, {}, [], [], True)
                self.assertFalse((output / 'prior-bogo-upgrade').exists()); install.assert_not_called()
            with patch.object(smoke.sys, 'platform', 'win32'), patch.dict(os.environ, self.environment(base), clear=True), patch.object(smoke, 'msi_run') as install:
                with self.assertRaises(ValueError):
                    smoke.actual_prior_bogo_upgrade({}, {}, None, {}, {}, output, {}, [], [], False)
                install.assert_not_called()

    def test_missing_original_kio_phase_and_missing_supplemental_receipt_cannot_pass(self):
        lock = self.target(); row = smoke.prior_bogo_input(lock, self.pins); current = self.properties(row, True)
        with self.assertRaisesRegex(ValueError, 'Original KIO-to-current'):
            smoke.require_legacy_upgrade_before_supplemental({}, current)
        with self.assertRaisesRegex(ValueError, 'missing/incomplete'):
            smoke.require_prior_bogo_completion(lock, self.original_report(current))
        phase = {'status': 'passed', 'fromVersion': row['version'], 'toVersion': lock['version'], 'currentMsi': current,
                 'sameUpgradeCode': True, 'priorProductRemoved': True, 'newProductInstalled': True,
                 'customInstallDirectoryPreservedWithoutOverride': True, 'profileAndWorkCanariesPreserved': True,
                 'installedExecutableSha256': 'a' * 64}
        report = {**self.original_report(current), 'priorBogoUpgrade': phase, 'installedExe': {'sha256': 'a' * 64},
                  'installedGui': {'started': True, 'runtimeIcons': {'passed': True}}}
        smoke.require_prior_bogo_completion(lock, report)
        for key in ('priorProductRemoved', 'profileAndWorkCanariesPreserved', 'customInstallDirectoryPreservedWithoutOverride'):
            broken = copy.deepcopy(report); broken['priorBogoUpgrade'][key] = False
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'continuity evidence'):
                smoke.require_prior_bogo_completion(lock, broken)
        broken = copy.deepcopy(report); broken['installedExe']['sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'existing installed GUI/icon'):
            smoke.require_prior_bogo_completion(lock, broken)
        broken = copy.deepcopy(report); broken['priorBogoUpgrade'].pop('installedExecutableSha256'); broken.pop('installedExe')
        with self.assertRaisesRegex(ValueError, 'existing installed GUI/icon'):
            smoke.require_prior_bogo_completion(lock, broken)

    def run_model_phase(self, app, fail_upgrade=False, corrupt_work=False):
        lock = self.target(app); row = smoke.prior_bogo_input(lock, self.pins); prior = self.properties(row); current = self.properties(row, True)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); output = base / 'owned'; output.mkdir(); prior_path = output / 'prior.msi'; prior_path.write_bytes(b'prior'); current_path = output / 'current.msi'; current_path.write_bytes(b'current')
            profile = output / 'synthetic-profile.txt'; profile.write_bytes(b'preserve-profile')
            sentinels = [(profile, smoke.digest(profile))]; tracked = ['{D6287451-47DE-5DFD-8962-E778CFAB447A}', current['ProductCode']]
            states = {prior['ProductCode']: -1, current['ProductCode']: 5}; calls = []; installed_at = [None]; new_bytes = b'new-native-bogo2'; report = self.original_report(current)
            def execute(args, log):
                calls.append((args, log))
                if args[0] == '/x':
                    states[args[1]] = -1; return 0
                if args[1] == str(prior_path):
                    destination = Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('INSTALLFOLDER='))); destination.mkdir(); installed_at[0] = destination
                    (destination / (lock['name'] + '.exe')).write_bytes(b'prior-native-bogo1'); states[prior['ProductCode']] = 5; return 0
                self.assertEqual(args, ['/i', str(current_path)], 'new MSI must discover the prior custom folder without any INSTALLFOLDER override')
                if fail_upgrade:
                    raise ValueError('actual MSI upgrade failed')
                states[prior['ProductCode']] = -1; states[current['ProductCode']] = 5
                (installed_at[0] / (lock['name'] + '.exe')).write_bytes(new_bytes)
                if corrupt_work:
                    (installed_at[0] / 'qa-existing-user-work.txt').write_bytes(b'corrupted')
                return 0
            with patch.object(smoke.sys, 'platform', 'win32'), patch.dict(os.environ, self.environment(base), clear=True), patch.object(smoke, 'product_state', side_effect=lambda code: states.get(code, -1)), patch.object(smoke, 'msi_run', side_effect=execute), patch.object(smoke, 'file_version', return_value={'ProductName': lock['name']}):
                prepared = {'row': row, 'path': prior_path, 'properties': prior}
                if fail_upgrade or corrupt_work:
                    with self.assertRaises(ValueError):
                        smoke.actual_prior_bogo_upgrade(prepared, lock, current_path, current, {'sha256': hashlib.sha256(new_bytes).hexdigest(), 'bytes': len(new_bytes)}, output, report, tracked, sentinels, True)
                    self.assertEqual(report['priorBogoUpgrade']['status'], 'failed')
                    self.assertIn(prior['ProductCode'], tracked)
                    smoke.cleanup_owned_products(tracked, output, report)
                    self.assertTrue(all(value == -1 for value in states.values()))
                else:
                    installed = smoke.actual_prior_bogo_upgrade(prepared, lock, current_path, current, {'sha256': hashlib.sha256(new_bytes).hexdigest(), 'bytes': len(new_bytes)}, output, report, tracked, sentinels, True)
                    self.assertEqual(installed.parent, installed_at[0]); self.assertEqual(installed.read_bytes(), new_bytes)
                    self.assertTrue(report['priorBogoUpgrade']['customInstallDirectoryPreservedWithoutOverride'])
                    self.assertTrue(report['priorBogoUpgrade']['profileAndWorkCanariesPreserved'])
                    self.assertEqual(profile.read_bytes(), b'preserve-profile')
                    self.assertEqual([args[0] for args, _ in calls], ['/x', '/i', '/i'])
                    smoke.cleanup_owned_products(tracked, output, report)

    def test_actual_phase_model_preserves_custom_folder_new_provenance_and_canaries_for_both_apps(self):
        for app in ('design', 'grid'):
            with self.subTest(app=app):
                self.run_model_phase(app)

    def test_failure_and_work_corruption_leave_only_owned_products_for_cleanup(self):
        self.run_model_phase('design', fail_upgrade=True)
        self.run_model_phase('grid', corrupt_work=True)

    def test_cleanup_never_touches_untracked_products_and_continues_after_a_failure(self):
        states = {'owned-a': 5, 'owned-b': 5, 'unrelated': 5}; attempted = []
        def uninstall(args, _log):
            attempted.append(args[1])
            if args[1] == 'owned-b':
                raise ValueError('simulated uninstall failure')
            states[args[1]] = -1; return 0
        with tempfile.TemporaryDirectory() as directory, patch.object(smoke, 'product_state', side_effect=lambda code: states[code]), patch.object(smoke, 'msi_run', side_effect=uninstall):
            report = {'status': 'running'}; smoke.cleanup_owned_products(['owned-a', 'owned-b'], Path(directory), report)
        self.assertEqual(attempted, ['owned-b', 'owned-a']); self.assertEqual(states['unrelated'], 5)
        self.assertEqual(report['status'], 'failed'); self.assertIn('error', report['cleanup'][0])


if __name__ == '__main__':
    unittest.main()
