"""Authenticate the real PDF installer scripts and retain its original MSI tests."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import full_native as full

FIXTURES = ROOT / 'tests/fixtures/pdf-msi-brand-contract'
NS = {'w': 'http://wixtoolset.org/schemas/v4/wxs'}


def contract(project):
    """Compare the actual XML producers with the preserved PowerShell consumers."""
    wxs = ET.parse(project / 'packaging/windows/pdfcraft.wxs').getroot()
    ui = ET.parse(project / 'packaging/windows/installer-ui.wxs').getroot()
    test = (project / 'packaging/windows/test-msi.ps1').read_text(encoding='utf-8')
    def capture(pattern):
        result = re.search(pattern, test)
        assert result, pattern
        return result.group(1)
    assert wxs.find('.//w:Launch', NS).get('Message') == capture(r"\$scopeMessage = '([^']+)'")
    assert wxs.find('w:Package', NS).get('Manufacturer') == capture(r"Assert-Equal \$manufacturer\[0\] '([^']+)' 'MSI manufacturer'")
    values = wxs.findall('.//w:RegistryValue', NS)
    def registry(key, name=None):
        entries = [v for v in values if v.get('Key') == key and v.get('Name') == name]
        assert len(entries) == 1, (key, name)
        return entries[0]
    key = re.search(r"\$key = '([^']*)' \+ \$ext \+ '([^']*)'", test)
    assert key
    extensions = re.findall(r"'([^']+)'", capture(r'foreach \(\$ext in @\(([^)]+)\)\)'))
    assert len(extensions) == 10 and len(set(extensions)) == 10
    for ext in extensions:
        actual = key.group(1) + ext + key.group(2)
        assert registry(actual).get('Value') == capture(r"Assert-Equal \$menu\[0\] '([^']+)'")
        assert registry(actual + '\\command').get('Value') == capture(r"Assert-Equal \$command\[0\] '([^']+)'")
        assert registry(actual, 'MultiSelectModel').get('Value') == 'Single'
    pdf_key = capture(r"\$pdfKey = '([^']+)'")
    assert registry(pdf_key).get('Value') == capture(r"Assert-Equal \$pdfMenu\[1\] '([^']+)'")
    assert registry(pdf_key + '\\command').get('Value') == capture(r"Assert-Equal \$pdfCommand\[0\] '([^']+)'")
    assert re.search(capture(r"\$pdfCheckbox\[2\] -notmatch '([^']+)'"), ui.find('.//w:Control[@Id="PdfContextMenu"]', NS).get('Text'))
    # These are visible KIO installer labels; internal WiX IDs retain upstream names.
    assert wxs.find('.//w:Feature', NS).get('Title') == 'KIO PDF'
    assert wxs.find('.//w:MajorUpgrade', NS).get('DowngradeErrorMessage') == 'A newer version of KIO PDF is already installed.'


class PdfMsiBrandContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = full.load_lock('pdf')
        cls.proof = json.loads((FIXTURES / 'provenance.json').read_text(encoding='utf-8'))
        assert cls.proof['upstreamSource'] == cls.lock['source']
        assert cls.proof['brandingPatchSha256'] == cls.lock['branding']['sha256']
        assert cls.proof['upstreamTestBodyOnlyPreviouslyRebrandedDisplayNames'] is True
        for row in cls.proof['files']:
            data = (FIXTURES / row['file']).read_bytes()
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        original = (FIXTURES / 'upstream-test-msi.ps1').read_bytes()
        assert len(original) == 14506 and hashlib.sha256(original).hexdigest() == '0234bf90f87de956ed5e683e0958c1d6a474273da0f63d4816976acc94650c4b'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='kio-pdf-msi-stage-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.project = self.root / 'package-windows-x64/original-msi-project'
        shutil.copytree(FIXTURES / 'before', self.source)
        shutil.copytree(self.source, self.project)
        self.before = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()}

    def apply(self, lock=None):
        return full.pdf_msi_brand_contract(lock or self.lock, self.source, self.project)

    def assert_source_unchanged(self):
        self.assertEqual(self.before, {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*') if p.is_file()})

    def test_actual_failed_contract_is_repaired_only_in_the_stage_with_exact_provenance(self):
        with self.assertRaises(AssertionError):
            contract(self.project)
        evidence = self.apply()
        contract(self.project)
        self.assertEqual(evidence['status'], 'applied-to-windows-copy-only')
        self.assertEqual(evidence['replacementCount'], 7)
        self.assertEqual(len(evidence['files']), 3)
        self.assertEqual([row['replacementCount'] for row in evidence['files']], [3, 3, 1])
        self.assertTrue(evidence['preparedSourceFilesUnchanged'])
        for row in evidence['files']:
            self.assertEqual(row['beforeSha256'], hashlib.sha256(self.before[row['path']]).hexdigest())
            self.assertEqual(row['afterSha256'], full.digest(self.project / row['path']))
            self.assertEqual(sum(r['count'] for r in row['replacements']), row['replacementCount'])
        self.assert_source_unchanged()

    def test_entire_original_msi_test_body_and_all_eight_scope_cases_are_retained(self):
        self.apply()
        original = (FIXTURES / 'upstream-test-msi.ps1').read_text(encoding='utf-8')
        expected = original.replace('PdfCraft', 'KIO PDF')
        expected = expected.replace("Assert-Equal $manufacturer[0] 'Learning Machines LLC' 'MSI manufacturer'", "Assert-Equal $manufacturer[0] 'KIO' 'MSI manufacturer'")
        expected = expected.replace('\\shell\\KIO PDF.CreatePdf', '\\shell\\KIO.PDF.CreatePdf').replace('\\shell\\KIO PDF.Edit', '\\shell\\KIO.PDF.Edit')
        self.assertEqual((self.project / 'packaging/windows/test-msi.ps1').read_text(encoding='utf-8'), expected)
        cases = lambda text: re.findall(r"^\s+@\('[^\n]+, [01]\)\)?", text.split("$session.Property('ALLUSERS')", 1)[0], re.M)
        self.assertEqual(len(cases(original)), 8)
        self.assertEqual(cases(original), cases(expected))
        before = ET.fromstring(self.before['packaging/windows/pdfcraft.wxs'])
        after = ET.parse(self.project / 'packaging/windows/pdfcraft.wxs').getroot()
        self.assertEqual(before.find('.//w:Launch', NS).get('Condition'), after.find('.//w:Launch', NS).get('Condition'))
        self.assertEqual(after.find('.//w:Launch', NS).get('Condition'), 'ALLUSERS = 1 OR (Installed AND REMOVE = "ALL")')
        self.assert_source_unchanged()

    def test_each_of_the_five_actual_producer_consumer_regressions_is_detected(self):
        self.apply()
        fixed = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        regressions = [
            ('packaging/windows/pdfcraft.wxs', 'Message="KIO PDF must be installed', 'Message="PdfCraft must be installed'),
            ('packaging/windows/test-msi.ps1', "Assert-Equal $manufacturer[0] 'KIO'", "Assert-Equal $manufacturer[0] 'Learning Machines LLC'"),
            ('packaging/windows/test-msi.ps1', '\\shell\\KIO.PDF.CreatePdf', '\\shell\\KIO PDF.CreatePdf'),
            ('packaging/windows/test-msi.ps1', '\\shell\\KIO.PDF.Edit', '\\shell\\KIO PDF.Edit'),
            ('packaging/windows/installer-ui.wxs', '&amp;Edit with KIO PDF', '&amp;Edit with PdfCraft'),
        ]
        for relative, before, after in regressions:
            with self.subTest(regression=relative + ':' + before):
                for path, data in fixed.items():
                    (self.project / path).write_bytes(data)
                p = self.project / relative
                text = p.read_text(encoding='utf-8')
                self.assertEqual(text.count(before), 1)
                p.write_text(text.replace(before, after), encoding='utf-8')
                with self.assertRaises(AssertionError):
                    contract(self.project)

    def test_changed_last_input_fails_before_any_stage_file_is_written(self):
        p = self.project / 'packaging/windows/installer-ui.wxs'
        p.write_bytes(p.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'exact before bytes'):
            self.apply()
        for relative in ('packaging/windows/pdfcraft.wxs', 'packaging/windows/test-msi.ps1'):
            self.assertEqual((self.project / relative).read_bytes(), self.before[relative])
        self.assert_source_unchanged()

    def test_missing_file_or_symlink_is_never_repaired(self):
        p = self.project / 'packaging/windows/installer-ui.wxs'
        p.unlink()
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.apply()
        outside = self.root / 'outside.wxs'
        outside.write_bytes(self.before['packaging/windows/installer-ui.wxs'])
        p.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.apply()
        self.assertEqual(outside.read_bytes(), self.before['packaging/windows/installer-ui.wxs'])
        self.assert_source_unchanged()

    def test_unknown_source_or_branding_pin_and_changed_prepared_source_are_rejected(self):
        for field in ('source', 'branding'):
            lock = copy.deepcopy(self.lock)
            lock[field]['commit' if field == 'source' else 'sha256'] = '0' * (40 if field == 'source' else 64)
            with self.assertRaisesRegex(ValueError, 'Unreviewed PDF MSI'):
                self.apply(lock)
        path = self.source / 'packaging/windows/test-msi.ps1'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'exact before bytes'):
            self.apply()

    def test_prepared_source_or_a_child_cannot_be_used_as_the_stage(self):
        with self.assertRaisesRegex(ValueError, 'separate original-msi-project'):
            full.pdf_msi_brand_contract(self.lock, self.source, self.source)
        child = self.source / 'original-msi-project'
        child.mkdir()
        with self.assertRaisesRegex(ValueError, 'separate original-msi-project'):
            full.pdf_msi_brand_contract(self.lock, self.source, child)

    def test_other_programs_are_not_changed_and_double_application_fails_closed(self):
        lock = copy.deepcopy(self.lock)
        lock['id'] = 'word'
        self.assertEqual(self.apply(lock), {'status': 'not-applicable'})
        for relative, data in self.before.items():
            self.assertEqual((self.project / relative).read_bytes(), data)
        self.apply()
        with self.assertRaisesRegex(ValueError, 'exact before bytes'):
            self.apply()

    def test_real_msi_entry_point_repairs_before_notices_and_keeps_original_test_invocation(self):
        shutil.rmtree(self.project)
        stage = self.project.parent
        destination = self.root / 'native.msi'
        notices = []
        def add_notices(text, lock, directory):
            contract(self.project)
            notices.append(text)
            return text, 3
        def invoke(args, *, cwd, env, timeout):
            self.assertEqual([str(x) for x in args], ['pwsh', '-NoLogo', '-NoProfile', '-File', str(self.project / 'packaging/windows/package.ps1'), '-Arch', 'x64', '-SkipBuild'])
            self.assertEqual(cwd, self.project)
            self.assertEqual(env['CARGO_TARGET_DIR'], 'the-original-full-native-target')
            contract(cwd)
            (Path(env['DIST']) / 'original.msi').write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture')
        with mock.patch.object(full, 'source_files', return_value=[(r, self.source / r) for r in self.before]), mock.patch.object(full, 'add_msi_notices', side_effect=add_notices), mock.patch.object(full, 'run', side_effect=invoke):
            result = full.original_windows_msi(self.lock, self.source, self.root / 'licenses', stage, {'CARGO_TARGET_DIR': 'the-original-full-native-target'}, destination)
        self.assertEqual(len(notices), 1)
        self.assertEqual(result['originalScript'], 'packaging/windows/package.ps1')
        self.assertEqual(result['stagedPdfBrandContract']['replacementCount'], 7)
        self.assertTrue(destination.is_file())
        self.assert_source_unchanged()

    def test_source_archive_contains_the_builder_guard_and_all_small_reviewed_fixtures(self):
        public = {name for name, _ in full.public_files(self.lock)}
        self.assertIn('tests/test_pdf_msi_brand_contract.py', public)
        for path in FIXTURES.rglob('*'):
            if path.is_file():
                self.assertIn(path.relative_to(ROOT).as_posix(), public)


if __name__ == '__main__':
    unittest.main()
