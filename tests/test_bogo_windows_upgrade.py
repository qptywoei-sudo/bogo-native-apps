import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bogo_windows_upgrade as upgrade


class UpgradeContractTests(unittest.TestCase):
    def test_only_exact_nine_installers_are_selected(self):
        self.assertEqual(set(upgrade.APPS), {'cad', 'design', 'film', 'pdf', 'word', 'sound', 'deck', 'grid', 'light'})
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(upgrade.transform_windows_upgrade(Path(temporary), 'launcher'), [])
            self.assertEqual(list(Path(temporary).iterdir()), [])
        for value in ('absent', 'twice twice'):
            with self.assertRaises(ValueError):
                upgrade.replace_once(value, 'twice', 'new')

    def test_exact_parent_adoption_has_both_existence_guards_and_preserves_explicit_folder(self):
        for app in set(upgrade.APPS) - {'light'}:
            xml = upgrade._wrapper(upgrade.additions(app))
            searches = xml.findall('.//w:RegistrySearch', upgrade.NS)
            self.assertEqual(len(searches), 3)
            for search in searches:
                self.assertEqual(search.get('Root'), 'HKLM')
                self.assertEqual(search.get('Bitness'), 'always64')
                self.assertEqual(search.get('Key'), upgrade.app_key(app))
                self.assertEqual(search.get('Type'), 'file')
            self.assertEqual(len(searches[0]), 0)
            self.assertEqual(searches[1][0].get('Name'), 'KIO ' + upgrade.APPS[app][1] + '.exe')
            self.assertEqual(searches[2][0].get('Name'), 'Bogo ' + upgrade.APPS[app][2] + '.exe')
            setter = xml.find('w:SetProperty', upgrade.NS)
            self.assertEqual(setter.attrib, {'Id': 'INSTALLFOLDER', 'Action': 'BogoSetExistingAppFolder',
                                           'Value': '[BOGOPREVIOUSAPPFOLDER]', 'After': 'AppSearch',
                                           'Sequence': 'both', 'Condition': upgrade.FOLDER_CONDITION})


@unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES'), 'set BOGO_NATIVE_ARCHIVES for exact published MSI source checks')
class PublishedInstallerUpgradeTests(unittest.TestCase):
    def source(self, app, temporary):
        path = Path(temporary) / 'packaging/windows' / (upgrade.APPS[app][0] + '.wxs')
        archives = list((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            names = [name for name in archive.namelist() if name.endswith('/packaging/windows/' + path.name)
                     and '/orchestrator/' not in name and not name.startswith('orchestrator/')]
            self.assertEqual(len(names), 1)
            path.parent.mkdir(parents=True)
            path.write_bytes(archive.read(names[0]))
        return path

    def test_all_nine_preserve_original_searches_registry_writes_guids_and_upgrade_identity(self):
        for app in upgrade.APPS:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = self.source(app, root)
                before = ET.fromstring(path.read_text())
                text = path.read_text().replace('Name="KIO ' + upgrade.APPS[app][1] + '.exe"', 'Name="Bogo ' + upgrade.APPS[app][2] + '.exe"')
                if app == 'pdf':
                    text = text.replace('<FileSearch Name="KIO PDF.lnk" />', '<FileSearch Name="Bogo PDF.lnk" />')
                path.write_text(text)
                self.assertEqual(upgrade.transform_windows_upgrade(root, app), ['packaging/windows/' + path.name])
                after = ET.fromstring(path.read_text())
                receipt = upgrade.validate_additive_searches(before, after, app)
                self.assertTrue(receipt['originalSearchesUnchanged'])
                for tag in ('RegistryValue', 'Component', 'ProgId', 'MajorUpgrade'):
                    fields = {'Component': ('Id', 'Guid'), 'RegistryValue': None,
                              'ProgId': ('Id',), 'MajorUpgrade': None}[tag]
                    def identity(element):
                        return tuple(sorted(element.attrib.items())) if fields is None else tuple(element.get(key) for key in fields)
                    self.assertEqual([identity(e) for e in before.findall('.//w:' + tag, upgrade.NS)],
                                     [identity(e) for e in after.findall('.//w:' + tag, upgrade.NS)])
                self.assertEqual(before.find('w:Package', upgrade.NS).get('UpgradeCode'), after.find('w:Package', upgrade.NS).get('UpgradeCode'))
                if app == 'cad':
                    desktop = [e for e in after.findall('.//w:Shortcut', upgrade.NS) if e.get('Id') == 'DesktopShortcut']
                    self.assertEqual(desktop[0].get('Target'), '[#CadcraftExe]')
                with self.assertRaises(ValueError):
                    upgrade.transform_windows_upgrade(root, app)

    def test_exact_validator_rejects_broader_keys_missing_existence_or_changed_legacy_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.source('cad', root)
            before = ET.fromstring(path.read_text())
            upgrade.transform_windows_upgrade(root, 'cad')
            after = ET.fromstring(path.read_text())
            search = after.find('.//w:RegistrySearch[@Id="BogoPreviousAppFolder"]', upgrade.NS)
            for key, value in [('Root', 'HKCU'), ('Key', 'Software\\Other App'), ('Type', 'raw'), ('Bitness', 'always32')]:
                altered = copy.deepcopy(after)
                altered.find('.//w:RegistrySearch[@Id="BogoPreviousAppFolder"]', upgrade.NS).set(key, value)
                with self.assertRaises(ValueError):
                    upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            altered.find('.//w:SetProperty[@Action="BogoSetExistingAppFolder"]', upgrade.NS).set('Condition', 'BOGOPREVIOUSAPPFOLDER')
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            altered.find('.//w:FileSearch[@Id="BogoPreviousAppExeFile"]', upgrade.NS).set('Name', '*.exe')
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            altered.find('.//w:RegistrySearch[@Id="PreviousDesktopShortcut"]', upgrade.NS).set('Key', 'Software\\New Name')
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            parent = altered.find('.//w:Property[@Id="PREVIOUSDESKTOPSHORTCUT"]', upgrade.NS)
            parent.set('Id', 'UNBOUNDSEARCHRESULT')
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            ET.SubElement(altered.find('w:Package', upgrade.NS), '{' + upgrade.NS['w'] + '}SetProperty', {'Id': 'INSTALLFOLDER', 'Value': 'C:\\Elsewhere', 'After': 'CostFinalize'})
            with self.assertRaisesRegex(ValueError, 'action'):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            ET.SubElement(altered.find('w:Package', upgrade.NS), '{' + upgrade.NS['w'] + '}SetProperty',
                          {'Id': 'INSTALLFOLDER', 'Value': 'C:\\unrelated', 'After': 'CostFinalize'})
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')
            altered = copy.deepcopy(after)
            altered.find('.//w:Property[@Id="PREVIOUSDESKTOPSHORTCUT"]', upgrade.NS).set('Id', 'RENAMEDPROPERTY')
            with self.assertRaises(ValueError):
                upgrade.validate_additive_searches(before, altered, 'cad')


if __name__ == '__main__':
    unittest.main()
