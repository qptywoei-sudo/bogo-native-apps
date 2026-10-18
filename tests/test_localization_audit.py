import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_localization.py'
spec = importlib.util.spec_from_file_location('localization_audit', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class LocalizationFailures(unittest.TestCase):
    def fixture(self, root, translation='Cài {name}', ui='tr("Install {name}")'):
        folder = root / 'crates/ui-egui/src/i18n'
        folder.mkdir(parents=True)
        (folder.parent / 'lib.rs').write_text(ui, encoding='utf-8')
        for lang in ('vi', 'ko', 'ja', 'zh-hant', 'zh-hans'):
            (folder / (lang + '.tsv')).write_text('\tInstall {name}\t' + translation + '\n', encoding='utf-8')

    def test_multilingual_sources_work_with_a_windows_legacy_default_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, 'Cài {name} — 설정 設定')
            original_open = Path.open

            def legacy_open(path, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
                if 'b' not in mode and encoding in (None, 'locale'):
                    encoding = 'cp1252'
                return original_open(path, mode, buffering, encoding, errors, newline)

            # Windows runners can use cp1252 while the repository contains UTF-8.
            # Exercise real catalog and Rust-source reads under that default.
            with patch.object(Path, 'open', legacy_open):
                result = audit.audit_app('fixture', root)
            self.assertTrue(result['complete'])
            self.assertEqual(result['languages']['vi']['keys'], 1)

    def test_missing_language_cannot_be_counted_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'crates/ui-egui/src/i18n/vi.tsv').unlink()
            result = audit.audit_app('fixture', root)
            self.assertFalse(result['complete'])
            self.assertEqual(result['languages']['vi']['missing'], 1)

    def test_empty_duplicate_and_wrong_variable_fail_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, 'Cài {other}')
            p = root / 'crates/ui-egui/src/i18n/vi.tsv'
            p.write_text(p.read_text(encoding='utf-8') + '\tInstall {name}\t\n', encoding='utf-8')
            result = audit.audit_app('fixture', root)
            self.assertTrue(result['parseErrors'])
            self.assertEqual(result['languages']['vi']['empty'], 1)
            self.assertEqual(result['languages']['ja']['placeholderErrors'], 1)
            self.assertFalse(result['complete'])

    def test_direct_ui_text_prevents_a_false_green_even_with_complete_catalogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, ui='ui.button("Install {name}");')
            result = audit.audit_app('fixture', root)
            self.assertTrue(result['directUiReview'])
            self.assertFalse(result['complete'])

    def test_invariant_plural_and_contextual_keys_are_not_conflated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'vi.tsv'
            p.write_text('@plural\t{n} app|{n} apps\t{n} ứng dụng\ncolumn\tApp\tỨng dụng\n\tApp\tỨng dụng\n', encoding='utf-8')
            rows, errors = audit.read_tsv(p)
            self.assertFalse(errors)
            self.assertEqual(len(rows), 3)
            self.assertNotEqual(('', 'App'), ('column', 'App'))
            self.assertEqual(audit.placeholders('{name} {name}'), {'name': 2})

    def test_required_languages_have_independent_chinese_catalogs(self):
        self.assertEqual(audit.canonical_language('zh-hans'), 'zh-CN')
        self.assertEqual(audit.canonical_language('zh-Hant'), 'zh-TW')
        self.assertEqual(audit.LANGUAGES, ('vi', 'en', 'ko', 'ja', 'zh-TW', 'zh-CN'))

    def test_legacy_missing_translation_does_not_allow_another_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.fixture(root)
            p=root/'crates/ui-egui/src/i18n/vi.tsv'
            p.unlink()
            before=audit.audit_app('fixture', root)
            baseline={'apps': {'fixture': audit.finding_inventory(before)}}
            self.assertFalse(audit.regressions(before, baseline))
            ko=root/'crates/ui-egui/src/i18n/ko.tsv'
            ko.write_text(ko.read_text(encoding='utf-8')+'\tSave\t저장\n', encoding='utf-8')
            after=audit.audit_app('fixture', root)
            self.assertIn('vi:missingKeys', audit.regressions(after, baseline))
            self.assertFalse(after['complete'])

    def test_new_raw_ui_string_is_not_hidden_by_legacy_raw_ui_debt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.fixture(root, ui='ui.button("Legacy label");')
            before=audit.audit_app('fixture', root)
            baseline={'apps': {'fixture': audit.finding_inventory(before)}}
            p=root/'crates/ui-egui/src/lib.rs'
            p.write_text('\n\n'+p.read_text(encoding='utf-8'), encoding='utf-8')
            self.assertFalse(audit.regressions(audit.audit_app('fixture', root), baseline))
            p.write_text(p.read_text(encoding='utf-8')+'\nui.button("Another label");', encoding='utf-8')
            self.assertIn('directUiReview', audit.regressions(audit.audit_app('fixture', root), baseline))


if __name__ == '__main__':
    unittest.main()
