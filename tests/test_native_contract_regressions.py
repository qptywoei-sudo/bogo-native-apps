"""Real upstream CLI and fixed-source legal-link contracts; no app compilation or GUI calls."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import kio_native as native
import full_native as full
FIXTURE = Path(__file__).parent / 'fixtures/native-contracts/winit-3d51077fd1a966f84df9ef287839dc84fd5b4ca7'
PROVENANCE = json.loads((FIXTURE / 'provenance.json').read_text(encoding='utf-8'))
assert PROVENANCE['upstream']['commit'] == '3d51077fd1a966f84df9ef287839dc84fd5b4ca7'
SOURCE = 'git+https://github.com/skylartaylor/winit.git?rev=3d51077fd1a966f84df9ef287839dc84fd5b4ca7#3d51077fd1a966f84df9ef287839dc84fd5b4ca7'
PACKAGE = {'name': 'winit', 'version': '0.30.13', 'source': SOURCE}
LICENSE = (FIXTURE / 'LICENSE').read_bytes()
assert len(LICENSE) == PROVENANCE['files'][0]['bytes'] == 11323
assert hashlib.sha256(LICENSE).hexdigest() == PROVENANCE['files'][0]['sha256'] == '6dc0e068dcf3a5bc8e054205b85b7720e1d49265bbc64bf515d2cf79197df69a'
COMMANDS = [{'id': v} for v in ['file.new', 'file.open', 'file.save', 'file.saveAs', 'file.export', 'document.inspect']]

class DesignLicenseLink(unittest.TestCase):

    def fixture(self, root, windows=False):
        (root / 'dpi').mkdir()
        (root / 'LICENSE').write_bytes(LICENSE)
        (root / 'Cargo.toml').write_text('original source fixture')
        if windows:
            (root / 'dpi/LICENSE').write_bytes(b'../LICENSE')
        else:
            (root / 'dpi/LICENSE').symlink_to('../LICENSE')

    def test_exact_reviewed_symlink_copies_full_original_license(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            files = dict(native.dependency_source_files(PACKAGE, r))
            self.assertEqual(files['dpi/LICENSE'].read_bytes(), LICENSE)
            self.assertEqual(files['dpi/LICENSE'], r.resolve() / 'LICENSE')
            with self.assertRaisesRegex(ValueError, 'Non-regular'):
                native.regular_files(r)

    def test_windows_git_materialized_link_copies_full_license(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r, True)
            self.assertEqual(dict(native.dependency_source_files(PACKAGE, r))['dpi/LICENSE'].read_bytes(), LICENSE)

    def test_wrong_source_or_version_does_not_receive_exception(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            for package in [{**PACKAGE, 'source': SOURCE.replace('3d51077', 'fffffff')}, {**PACKAGE, 'version': '0.30.14'}, {**PACKAGE, 'name': 'another'}]:
                with self.subTest(package=package), self.assertRaises(ValueError):
                    native.dependency_source_files(package, r)

    def test_changed_original_license_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            (r / 'LICENSE').write_bytes(LICENSE + b'x')
            with self.assertRaisesRegex(ValueError, 'original license changed'):
                native.dependency_source_files(PACKAGE, r)

    def test_link_escape_is_rejected_even_when_target_license_is_valid(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            (r / 'dpi/LICENSE').unlink()
            (r / 'dpi/LICENSE').symlink_to('../../outside/LICENSE')
            with self.assertRaisesRegex(ValueError, 'target changed'):
                native.dependency_source_files(PACKAGE, r)

    def test_arbitrary_file_symlink_remains_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            (r / 'arbitrary.rs').symlink_to('LICENSE')
            with self.assertRaisesRegex(ValueError, 'Non-regular'):
                native.dependency_source_files(PACKAGE, r)

    def test_directory_link_remains_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            (r / 'linked-directory').symlink_to('dpi', target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'Directory symlink'):
                native.dependency_source_files(PACKAGE, r)

    def test_wrong_windows_stand_in_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r, True)
            (r / 'dpi/LICENSE').write_bytes(b'../NOTICE!')
            with self.assertRaisesRegex(ValueError, 'target changed'):
                native.dependency_source_files(PACKAGE, r)

    def test_target_itself_must_not_be_a_symlink(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            self.fixture(r)
            (r / 'LICENSE').unlink()
            (r / 'actual').write_bytes(LICENSE)
            (r / 'LICENSE').symlink_to('actual')
            with self.assertRaisesRegex(ValueError, 'original license changed'):
                native.dependency_source_files(PACKAGE, r)

class DeckRegistry(unittest.TestCase):

    def probe(self, data):
        with patch.object(full, 'run', return_value=json.dumps(data)) as run:
            result = full.check_cli_probe({'id': 'deck'}, Path('deckcraft-cli'), Path('source'), {})
        self.assertEqual(run.call_args.args[0], [Path('deckcraft-cli'), 'commands'])
        return result

    def test_deck_checks_actual_original_success_contract(self):
        result = self.probe(COMMANDS)
        self.assertEqual(result['mode'], 'original-command-registry')
        self.assertEqual(result['commands'], 6)

    def test_registry_must_contain_essential_commands(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.probe(COMMANDS[:-1])

    def test_original_registry_alias_rows_are_retained(self):
        self.assertEqual(self.probe(COMMANDS + COMMANDS[:1])['commands'], 7)

    def test_empty_or_non_array_or_malformed_registry_rejected(self):
        for data in [[], {}, [1], [{'id': 7}]]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.probe(data)

    def test_command_failure_is_not_ignored(self):
        with patch.object(full, 'run', side_effect=subprocess.CalledProcessError(1, ['deckcraft-cli', 'commands'])):
            with self.assertRaises(subprocess.CalledProcessError):
                full.check_cli_probe({'id': 'deck'}, Path('deckcraft-cli'), Path('source'), {})

    def test_invalid_json_is_rejected(self):
        with patch.object(full, 'run', return_value='usage: command failed'):
            with self.assertRaises(ValueError):
                full.check_cli_probe({'id': 'deck'}, Path('deckcraft-cli'), Path('source'), {})

    def test_other_cli_help_failure_remains_fatal(self):
        with patch.object(full, 'run', side_effect=subprocess.CalledProcessError(1, ['gridcraft-cli', '--help'])):
            with self.assertRaises(subprocess.CalledProcessError):
                full.check_cli_probe({'id': 'grid'}, Path('gridcraft-cli'), Path('source'), {})

    def test_other_cli_help_contract_retained(self):
        with patch.object(full, 'run', return_value='usage...') as run:
            result = full.check_cli_probe({'id': 'grid'}, Path('gridcraft-cli'), Path('source'), {})
        self.assertEqual(run.call_args.args[0], [Path('gridcraft-cli'), '--help'])
        self.assertEqual(result['mode'], 'original-help')
if __name__ == '__main__':
    unittest.main()
