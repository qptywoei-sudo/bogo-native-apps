import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bogo_packaging as art
import bogo_brand as brand
import full_native as full

ROOT = Path(__file__).resolve().parents[1]
PDF_ASSERTION = b"Assert-Equal $manufacturer[0] 'KIO' 'MSI manufacturer'"
BOGO_ASSERTION = b"Assert-Equal $manufacturer[0] 'Bogo' 'MSI manufacturer'"


def corrected_pdf_source(root, archive=None):
    source = root / 'original-source'
    if archive is None:
        shutil.copytree(ROOT / 'tests/fixtures/pdf-msi-brand-contract/before', source)
    else:
        with zipfile.ZipFile(archive) as zipped:
            for relative, *_ in full._PDF_MSI_BRAND_CONTRACT:
                choices = [name for name in zipped.namelist() if name.endswith('/' + relative)
                           and '/orchestrator/' not in name and not name.startswith('orchestrator/')]
                if len(choices) != 1:
                    raise AssertionError('Expected one authenticated original PDF input: ' + relative)
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(zipped.read(choices[0]))
    original = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    project = root / 'package-windows-x64/original-msi-project'
    shutil.copytree(source, project)
    evidence = full.pdf_msi_brand_contract(full.load_lock('pdf'), source, project)
    assert evidence['replacementCount'] == 7
    assert original == {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    for relative, *_ in full._PDF_MSI_BRAND_CONTRACT:
        path = project / relative
        text = path.read_text(encoding='utf-8')
        path.write_text(brand.rust_display(text) if path.suffix == '.ps1' else brand.xml_display(text), encoding='utf-8')
    return project


class PdfPublisherTests(unittest.TestCase):
    def check_corrected_source(self, source):
        path = source / 'packaging/windows/test-msi.ps1'
        before = path.read_bytes()
        other = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file() and p != path}
        self.assertEqual(art.transform_packaging_source(source, 'pdf'), ['packaging/windows/test-msi.ps1'])
        after = path.read_bytes()
        self.assertEqual(after, before.replace(PDF_ASSERTION, BOGO_ASSERTION, 1))
        self.assertEqual(other, {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file() and p != path})
        expected = re.search(rb"Assert-Equal \$manufacturer\[0\] '([^']+)' 'MSI manufacturer'", after).group(1).decode('ascii')
        package = ET.parse(source / 'packaging/windows/pdfcraft.wxs').getroot().find('{http://wixtoolset.org/schemas/v4/wxs}Package')
        self.assertEqual(package.get('Manufacturer'), expected)
        self.assertEqual(expected, 'Bogo')
        cases = re.findall(rb"^\s+@\('[^\n]+, [01]\)\)?", after.split(b"$session.Property('ALLUSERS')", 1)[0], re.M)
        self.assertEqual(len(cases), 8)
        for technical in (b'\\shell\\KIO.PDF.CreatePdf', b'\\shell\\KIO.PDF.Edit', b'C:\\Users\\Public\\Desktop\\KIO PDF.lnk'):
            self.assertIn(technical, after)
        with self.assertRaises(ValueError):
            art.transform_packaging_source(source, 'pdf')
        self.assertEqual(path.read_bytes(), after)

    def test_exact_pdf_publisher_matches_producer_and_retains_seven_corrections_and_original_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.check_corrected_source(corrected_pdf_source(Path(temporary)))

    def test_missing_duplicate_altered_or_non_full_line_assertions_fail_before_writing(self):
        bad = (b'absent\n', PDF_ASSERTION + b'\n' + PDF_ASSERTION + b'\n',
               PDF_ASSERTION.replace(b"'KIO'", b"'Unknown'"), b'# ' + PDF_ASSERTION)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'packaging/windows/test-msi.ps1'
            path.parent.mkdir(parents=True)
            for data in bad:
                with self.subTest(data=data):
                    path.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, 'assertion contract'):
                        art.transform_packaging_source(root, 'pdf')
                    self.assertEqual(path.read_bytes(), data)
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'regular'):
                art.transform_packaging_source(root, 'pdf')
            outside = root / 'outside.ps1'
            outside.write_bytes(PDF_ASSERTION + b'\r\n')
            path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'regular'):
                art.transform_packaging_source(root, 'pdf')
            self.assertEqual(outside.read_bytes(), PDF_ASSERTION + b'\r\n')

    def test_pdf_only_change_preserves_original_line_endings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'packaging/windows/test-msi.ps1'
            path.parent.mkdir(parents=True)
            data = b'# unchanged\r\n' + PDF_ASSERTION + b'\r\n# end\r\n'
            path.write_bytes(data)
            self.assertEqual(art.transform_packaging_source(root, 'cad'), [])
            self.assertEqual(path.read_bytes(), data)
            art.transform_packaging_source(root, 'pdf')
            self.assertEqual(path.read_bytes(), data.replace(PDF_ASSERTION, BOGO_ASSERTION))

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES'), 'set BOGO_NATIVE_ARCHIVES for exact published PDF checks')
    def test_published_pdf_packager_retains_original_seven_corrections_and_all_guards(self):
        archive = next((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / 'pdf').glob('*-source.zip'))
        with tempfile.TemporaryDirectory() as temporary:
            self.check_corrected_source(corrected_pdf_source(Path(temporary), archive))


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
                before = path.read_text(encoding='utf-8')
                draw = re.findall(r'^.*\$g\.DrawImage.*$', before, re.M)
                artwork_inputs = re.findall(r'^.*(?:FromFile|New-InstallerArt \(|New-PanelBitmap\().*$', before, re.M)
                self.assertEqual(art.transform_packaging_source(root, app), ['packaging/windows/package.ps1'])
                after = path.read_text(encoding='utf-8')
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
                self.assertEqual(path.read_text(encoding='utf-8'), after)


if __name__ == '__main__':
    unittest.main()
