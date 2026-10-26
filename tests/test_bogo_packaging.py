import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bogo_packaging as art


class ArtworkGuardTests(unittest.TestCase):
    def test_unreviewed_contracts_refuse_and_unselected_apps_are_untouched(self):
        for text in ('absent', 'twice twice'):
            with self.assertRaises(ValueError):
                art.once(text, 'twice', 'updated')
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(art.transform_packaging_source(Path(temporary), 'cad'), [])
            self.assertEqual(list(Path(temporary).iterdir()), [])


@unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES'), 'set BOGO_NATIVE_ARCHIVES for exact published packaging checks')
class PublishedArtworkTests(unittest.TestCase):
    def test_five_real_packagers_change_backdrop_colors_and_preserve_all_original_icon_draws(self):
        for app in art.APPS:
            with self.subTest(app=app), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'packaging/windows/package.ps1'
                archive = next((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
                with zipfile.ZipFile(archive) as z:
                    names = [n for n in z.namelist() if n.endswith('/packaging/windows/package.ps1') and not n.startswith('orchestrator/') and '/orchestrator/' not in n]
                    self.assertEqual(len(names), 1)
                    path.parent.mkdir(parents=True)
                    path.write_bytes(z.read(names[0]))
                before = path.read_text()
                draw = re.findall(r'^.*\$g\.DrawImage.*$', before, re.M)
                artwork_inputs = re.findall(r'^.*(?:FromFile|New-InstallerArt \(|New-PanelBitmap\().*$', before, re.M)
                self.assertEqual(art.transform_packaging_source(root, app), ['packaging/windows/package.ps1'])
                after = path.read_text()
                self.assertEqual(draw, re.findall(r'^.*\$g\.DrawImage.*$', after, re.M))
                self.assertEqual(artwork_inputs, re.findall(r'^.*(?:FromFile|New-InstallerArt \(|New-PanelBitmap\().*$', after, re.M))
                if app == 'light':
                    self.assertIn('493 312 164 ([byte[]](0xFF, 0xF3, 0xE8)) ([byte[]](0xFF, 0xFA, 0xF6))', after)
                    self.assertIn('493 58 0 ([byte[]](0xFF, 0xF3, 0xE8)) ([byte[]](0xFF, 0xF3, 0xE8))', after)
                else:
                    self.assertIn("FromHtml('#FFF3E8')", after)
                    self.assertIn("FromHtml('#FC7501')", after)
                    self.assertIn("$g.Clear([System.Drawing.ColorTranslator]::FromHtml('#FFFAF6'))", after)
                    if app == 'launcher':
                        self.assertIn("FromHtml('#342B26')", after)
                        self.assertIn("FromHtml('#F1D3BD')", after)
                with self.assertRaises(ValueError):
                    art.transform_packaging_source(root, app)
                self.assertEqual(path.read_text(), after)


if __name__ == '__main__':
    unittest.main()
