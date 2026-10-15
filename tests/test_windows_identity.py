"""Actual prepared WiX XML collision regressions; no app binary is run."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import audit_windows_identity as windows


def locks():
    entries = json.loads((ROOT / 'manifests/full-native-apps.json').read_text())['applications']
    return {entry['id']: entry for entry in entries} | {'launcher': json.loads((ROOT / 'manifests/launcher.lock.json').read_text())}


class WindowsInstallerIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='kio-actual-wix-audit-')
        cls.inputs = {}
        for ident, lock in locks().items():
            fixture_root = ROOT / 'tests/fixtures/windows-identity'
            records = json.loads((fixture_root / 'provenance.json').read_text())['files']
            record = next(row for row in records if row['id'] == ident)
            original = (fixture_root / record['file']).read_bytes()
            assert hashlib.sha256(original).hexdigest() == record['sha256'] and len(original) == record['bytes']
            assert record['commit'] == lock['source']['commit'] and record['archiveSha256'] == lock['source']['sha256']
            assert record['archiveBytes'] == lock['source']['bytes']
            relative = 'packaging/windows/' + lock['binaries']['app'] + '.wxs'
            assert record['archiveMember'] == lock['source']['root'] + '/' + relative
            source = Path(cls.tmp.name) / ident
            path = source / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(original)
            # Apply the actual immutable branding patch to the original XML, rather than
            # assuming a particular string in a patch proves an effective installer change.
            patch = ROOT / lock['branding']['patch']
            subprocess.run(['git', 'apply', '--binary', '--include=' + relative, str(patch)], cwd=source, check=True, capture_output=True)
            cls.inputs[ident] = (lock, source, original, relative)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_fourteen_prepared_installers_are_isolated_and_cross_app_guids_unique(self):
        upgrade_codes, component_guids, registry_values = set(), set(), set()
        original_trees = [ET.fromstring(case[2]) for case in self.inputs.values()]
        original_guids = set().union(*(windows._guids(tree) for tree in original_trees))
        original_upgrades = {tree.find('w:Package', windows.NS).get('UpgradeCode').casefold() for tree in original_trees}
        original_values = set().union(*(windows._registrations(tree, 'RegistryValue') for tree in original_trees))
        for ident, (lock, source, original, relative) in self.inputs.items():
            with self.subTest(app=ident):
                evidence = windows.audit(lock, source, original_xml=original)
                self.assertEqual(evidence['gui'], lock['name'] + '.exe')
                upgrade = evidence['upgradeCode'].casefold()
                self.assertNotIn(upgrade, original_upgrades)
                self.assertNotIn(upgrade, upgrade_codes)
                upgrade_codes.add(upgrade)
                guids = set(evidence['fixedComponentGuids'])
                self.assertFalse(guids & original_guids, ident)
                self.assertFalse(guids & component_guids, ident)
                component_guids.update(guids)
                registered = windows._registrations(ET.parse(source / relative).getroot(), 'RegistryValue')
                self.assertFalse(registered & original_values, ident)
                self.assertFalse(registered & registry_values, ident)
                registry_values.update(registered)

    def corrupted(self, ident, mutate):
        lock, source, original, relative = self.inputs[ident]
        with tempfile.TemporaryDirectory(prefix='kio-wix-negative-') as tmp:
            root = Path(tmp)
            path = root / relative
            path.parent.mkdir(parents=True)
            tree = ET.parse(source / relative)
            mutate(tree.getroot(), ET.fromstring(original))
            tree.write(path, encoding='utf-8', xml_declaration=True)
            with self.assertRaises(ValueError):
                windows.audit(lock, root, original_xml=original)

    def test_restored_upstream_upgrade_code_or_component_guid_are_rejected(self):
        def upgrade(current, original):
            current.find('w:Package', windows.NS).set('UpgradeCode', original.find('w:Package', windows.NS).get('UpgradeCode'))
        def component(current, original):
            old = next(e for e in original.findall('.//w:Component', windows.NS) if e.get('Guid') not in (None, '*'))
            current.find('.//w:Component', windows.NS).set('Guid', old.get('Guid'))
        self.corrupted('ui', upgrade)
        self.corrupted('launcher', component)

    def test_original_install_dir_search_is_rejected_even_if_new_directory_name_is_kio(self):
        def search(current, original):
            old = original.find('.//w:RegistrySearch', windows.NS)
            current.find('.//w:RegistrySearch', windows.NS).set('Key', old.get('Key'))
        self.corrupted('photo', search)

    def test_original_app_paths_write_is_rejected_even_if_it_points_to_kio_binary(self):
        def app_paths(current, original):
            old = next(e for e in original.findall('.//w:RegistryValue', windows.NS) if '\\app paths\\' in windows._key(e.get('Key')))
            new = next(e for e in current.findall('.//w:RegistryValue', windows.NS) if '\\app paths\\' in windows._key(e.get('Key')))
            new.set('Key', old.get('Key'))
        self.corrupted('launcher', app_paths)

    def test_original_prog_id_and_shared_native_extension_default_are_rejected(self):
        def progid(current, original):
            current.find('.//w:ProgId', windows.NS).set('Id', original.find('.//w:ProgId', windows.NS).get('Id'))
        self.corrupted('ui', progid)
        for app in ['ui', 'sound', 'deck']:
            def extension(current, original):
                old = original.find('.//w:Extension', windows.NS)
                current.find('.//w:ProgId', windows.NS).append(copy.deepcopy(old))
            self.corrupted(app, extension)

    def test_each_shared_native_format_retains_unique_kio_open_command_and_open_with(self):
        for ident, ext, progid in [('photo', 'pcraft', 'KIO.Photo.Document'), ('ui', 'figcraft', 'KIO.UI.Document'), ('sound', 'scraft', 'KIO.Sound.Session'), ('deck', 'deckcraft', 'KIO.Deck.Presentation')]:
            with self.subTest(app=ident):
                lock, source, _, relative = self.inputs[ident]
                tree = ET.parse(source / relative).getroot()
                values = tree.findall('.//w:RegistryValue', windows.NS)
                command = next(e for e in values if e.get('Key') == 'Software\\Classes\\' + progid + '\\shell\\open\\command')
                self.assertIn('"%1"', command.get('Value'))
                open_with = next(e for e in values if e.get('Key') == 'Software\\Classes\\.' + ext + '\\OpenWithProgids')
                self.assertEqual(open_with.get('Name'), progid)
                self.assertFalse(tree.findall('.//w:Extension', windows.NS))

    def test_gui_rename_or_removed_supported_type_fails(self):
        def wrong_gui(current, original):
            file = next(e for e in current.findall('.//w:File', windows.NS) if e.get('Name') == 'KIO UI.exe')
            file.set('Name', 'figcraft.exe')
        def removed_type(current, original):
            for entry in current.findall('.//w:RegistryValue', windows.NS):
                if windows._key(entry.get('Key')).endswith('\\supportedtypes'):
                    entry.set('Name', '.unrelated')
                    break
        self.corrupted('ui', wrong_gui)
        self.corrupted('ui', removed_type)

    def test_archive_cache_is_explicit_and_never_downloads_missing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'never downloads'):
                windows._upstream(self.inputs['ui'][0], archive_cache=Path(tmp))


if __name__ == '__main__':
    unittest.main()
