"""Display branding must not turn original Rust variants into spaced app names.

These are lexical/source-patch checks, not native compilation or GUI QA.
The real upstream fixture is bounded, authenticated and usable offline on CI.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rust_branding_audit', ROOT / 'scripts/audit_rust_branding.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class RustBrandingGuard(unittest.TestCase):
    def test_executable_enum_corruption_is_found_at_actual_line(self):
        text = '// KIO UI is an allowed comment\nmatch kind {\n FileKind::KIO UI | FileKind::Fig => {}\n}\n'
        self.assertEqual(audit.audit_text(text, 'home_recents.rs'),
                         [{'path': 'home_recents.rs', 'line': 3, 'expression': 'KIO UI'}])

    def test_all_known_display_names_are_rejected_only_as_executable_tokens(self):
        for name in audit.DISPLAY_NAMES:
            with self.subTest(name=name):
                self.assertTrue(audit.audit_text('let value = Kind::KIO ' + name + ';'))
                self.assertEqual(audit.audit_text('let label = "KIO ' + name + '";'), [])

    def test_comments_strings_raw_bytes_and_c_literals_do_not_trigger(self):
        text = '''// FileKind::KIO UI
/* KIO Photo /* nested KIO Vector */ KIO Film */
let a = "KIO UI and an escaped quote \\\" KIO Launcher";
let b = r###"KIO PDF \" KIO Light"###;
let c = br##"KIO Sound"##;
let d = cr#"KIO Design"#;
let e = b"KIO Word";
let f = c"KIO Effect";
let g = '\"'; let h = '\\u{1f600}'; let i = '\\\\';
fn lifetime<'a>(value: &'a str) -> &'a str { value }
let retained = FileKind::FigCraft;
'''
        masked = audit.executable_code(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count('\n'), text.count('\n'))
        self.assertIn("fn lifetime<'a>", masked)
        self.assertIn('FileKind::FigCraft', masked)
        self.assertEqual(audit.audit_text(text), [])

    def test_raw_string_ending_and_unicode_literal_boundaries_preserve_real_error(self):
        text = 'let x = r##"KIO UI #\" still string"##; let y = \'한\';\nKind::KIO Grid;'
        findings = audit.audit_text(text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['line'], 2)
        self.assertEqual(findings[0]['expression'], 'KIO Grid')

    def test_unterminated_literals_and_comments_fail_closed(self):
        for text in ['/* unterminated', 'r###"unterminated', '"unterminated']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                audit.executable_code(text)

    def test_real_upstream_ui_file_applies_current_patch_and_retains_original_variant(self):
        fixture = ROOT / 'tests/fixtures/rust-branding'
        proof = json.loads((fixture / 'provenance.json').read_text())
        lock = next(row for row in json.loads((ROOT / 'manifests/full-native-apps.json').read_text())['applications'] if row['id'] == 'ui')
        original = (fixture / proof['file']).read_bytes()
        self.assertEqual(proof['repository'], lock['source']['repository'])
        self.assertEqual(proof['commit'], lock['source']['commit'])
        self.assertEqual(proof['sourceArchiveSha256'], lock['source']['sha256'])
        self.assertEqual(proof['bytes'], len(original))
        self.assertEqual(proof['sha256'], hashlib.sha256(original).hexdigest())
        branding = ROOT / lock['branding']['patch']
        self.assertEqual(audit.sha256(branding), lock['branding']['sha256'])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            target = source / proof['path']
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            subprocess.run(['git', 'apply', '--check', '--binary', '--include=' + proof['path'], str(branding)], cwd=source, check=True, capture_output=True)
            subprocess.run(['git', 'apply', '--binary', '--include=' + proof['path'], str(branding)], cwd=source, check=True, capture_output=True)
            report = audit.audit_source(source)
            self.assertEqual(report['rustFiles'], 1)
            self.assertEqual(report['findings'], [])
            self.assertEqual(target.read_bytes(), original)
            self.assertIn('FileKind::FigCraft | FileKind::Fig => {', target.read_text())
            # Negative replay of the actual Windows failure, with identical
            # surrounding source; checks meaningful behavior rather than a patch hunk.
            target.write_text(target.read_text().replace('FileKind::FigCraft | FileKind::Fig', 'FileKind::KIO UI | FileKind::Fig'))
            findings = audit.audit_source(source)['findings']
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]['path'], proof['path'])
            self.assertEqual(findings[0]['line'], 709)


if __name__ == '__main__':
    unittest.main()
