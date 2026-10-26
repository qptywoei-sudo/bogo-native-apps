import os
import hashlib
from pathlib import Path
import sys
import tarfile
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_chrome_contrast as chrome
import bogo_native as bogo


FILES = {
    'light': ('crates/ui-egui/src/docking.rs', 'crates/ui-egui/src/panels/detail.rs', 'crates/ui-egui/src/panels/bottombar.rs', 'crates/ui-egui/src/widgets.rs'),
    'pdf': ('crates/ui-egui/src/lib.rs',),
    'ui': ('crates/ui-egui/src/theme.rs',),
    'deck': ('crates/ui-egui/src/backstage.rs',),
    'word': ('crates/ui-egui/src/backstage.rs',),
    'sound': ('crates/ui-egui/src/panels.rs', 'crates/ui-egui/src/widgets.rs'),
    'effect': ('crates/ui-egui/src/widgets.rs', 'crates/ui-egui/src/theme.rs', 'crates/ui-egui/src/header.rs', 'crates/ui-egui/src/panels/viewer.rs'),
    'photo': ('crates/ui-egui/src/canvas.rs', 'crates/ui-egui/src/icons.rs'),
}


def archived_sources(app, relatives):
    if os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'):
        lock = bogo.base_lock(app)
        archive = Path(os.environ['BOGO_NATIVE_SOURCE_ARCHIVE_CACHE']) / Path(lock['source']['localCacheFile']).name
        if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['source']['sha256']:
            raise ValueError('Authenticated original source archive changed')
        with tarfile.open(archive) as tar:
            return {relative: tar.extractfile(next(m for m in tar.getmembers() if m.name.endswith('/' + relative))).read().decode('utf-8') for relative in relatives}
    archive = next((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
    with zipfile.ZipFile(archive) as zipped:
        contents = {}
        for relative in relatives:
            entries = [n for n in zipped.namelist() if n.endswith('/' + relative) and '/orchestrator/' not in n]
            if len(entries) != 1:
                raise ValueError('Exactly one original source member required')
            contents[relative] = zipped.read(entries[0]).decode('utf-8')
        return contents


class InstalledChromeContrast(unittest.TestCase):
    def test_only_reviewed_app_file_pairs_have_replacements(self):
        for app in ('cad', 'film', 'pdf', 'light', 'ui', 'deck', 'word', 'sound', 'effect', 'photo', 'grid', 'launcher', 'vector', 'design'):
            for relatives in FILES.values():
                for relative in relatives:
                    if relative not in FILES.get(app, ()):
                        self.assertEqual(chrome.transform(app, relative, 'unchanged'), 'unchanged')
        self.assertEqual(chrome.transform('word', 'crates/core/src/lib.rs', 'APP_COLOR'), 'APP_COLOR')

    def test_unknown_and_duplicate_upstream_contracts_are_rejected(self):
        for app, relatives in FILES.items():
            for relative in relatives:
                rows = chrome.replacements(app, relative)
                valid = '\n'.join(before * count for before, _, count in rows)
                for invalid in ('', valid + valid, valid.replace(rows[0][0], 'unknown declaration', 1)):
                    with self.subTest(app=app, relative=relative), self.assertRaises(ValueError):
                        chrome.transform(app, relative, invalid)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_actual_archived_files_preserve_every_other_byte_and_interaction(self):
        for app, relatives in FILES.items():
            contents = archived_sources(app, relatives)
            for relative, before in contents.items():
                    # The reviewed expressions are upstream chrome code. Their
                    # inverse must restore the whole original file, including tests.
                    after = chrome.transform(app, relative, before)
                    spans = []
                    for old, new, count in chrome.replacements(app, relative):
                        offset = 0
                        for _ in range(count):
                            start = before.index(old, offset)
                            spans.append((start, start + len(old), old, new))
                            offset = start + len(old)
                    spans.sort()
                    delta = 0
                    actual_spans = []
                    for start, end, old, new in spans:
                        actual_start = start + delta
                        self.assertEqual(after[actual_start:actual_start + len(new)], new)
                        actual_spans.append((actual_start, actual_start + len(new), old))
                        delta += len(new) - len(old)
                    restored = after
                    for start, end, old in reversed(actual_spans):
                        restored = restored[:start] + old + restored[end:]
                    self.assertEqual(restored, before, (app, relative))
                    if app == 'word':
                        self.assertIn('Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)), egui::Color32::WHITE)', after)
                        self.assertNotIn('.fill(APP_COLOR)', after)
                    if app == 'light' and relative.endswith('detail.rs'):
                        self.assertIn('let label_background = crate::theme::label_background(base, label, selected);', after)
                        self.assertIn('p.image(tex.tex.id(), fr,', after)
                    if app == 'light' and relative.endswith('bottombar.rs'):
                        for marker in ('photo.rate', 'photo.flag', 'develop.paste', 'develop.copy', 'dialog.copySettings', 'button:copySettings', 'icon:copyGear', 'flag:{id}'):
                            self.assertGreater(before.count(marker), 0)
                            self.assertEqual(before.count(marker), after.count(marker))
                        self.assertIn('if f == Flag::Reject { t.reject } else { t.text }', after)
                        self.assertEqual(after.count('pill_ui.painter().rect_filled(r, 4.0, t.pressed);'), 1)
                        self.assertNotIn('t.pick', after)
                    if app == 'light' and relative.endswith('widgets.rs'):
                        self.assertEqual(after.count('if filled && id != "bottom" { t.star } else { t.icon });'), 1)
                        self.assertEqual(before.count('out = Some(if rating == i + 1 { 0 } else { i + 1 });'), after.count('out = Some(if rating == i + 1 { 0 } else { i + 1 });'))
                    if app == 'pdf':
                        self.assertEqual(before.count('canvas::document_area(self, index, ui)'), after.count('canvas::document_area(self, index, ui)'))
                        self.assertEqual(before.count('docking::show(self, ui)'), after.count('docking::show(self, ui)'))
                        self.assertEqual(before.count('combine_ui::page(self, ui)'), after.count('combine_ui::page(self, ui)'))

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_light_footer_colors_are_readable_without_changing_photo_semantic_colors(self):
        import bogo_brand
        theme = archived_sources('light', ('crates/ui-egui/src/theme.rs',))['crates/ui-egui/src/theme.rs']
        branded = bogo_brand.theme(theme)
        def colors(token):
            return {tuple(int(x, 16) for x in match) for match in re.findall(r'\b' + token + r': Color32::from_rgb\(0x([0-9a-fA-F]{2}), 0x([0-9a-fA-F]{2}), 0x([0-9a-fA-F]{2})\)', branded)}
        self.assertEqual(colors('button'), {(255, 250, 246)})
        self.assertEqual(colors('pressed'), {(255, 231, 212)})
        self.assertEqual(colors('icon'), {(52, 43, 38)})
        self.assertEqual(colors('text_label'), {(52, 43, 38)})
        def luminance(rgb):
            values = [v / 255 for v in rgb]
            return sum((v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) * w for v, w in zip(values, (.2126, .7152, .0722)))
        for ink in colors('icon') | colors('text_label'):
            for fill in colors('button') | colors('pressed'):
                light, dark = sorted((luminance(ink), luminance(fill)), reverse=True)
                self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)
        for declaration in re.findall(r'^\s*(?:canvas|grid_bg|star|pick|reject):.*$', theme, re.M):
            self.assertIn(declaration, branded)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_pdf_home_fill_matches_actual_dispatch_and_rejects_all_three_guard_mutants(self):
        original = archived_sources('pdf', ('crates/ui-egui/src/lib.rs',))['crates/ui-egui/src/lib.rs']
        enum = re.search(r'pub enum Mode \{(.*?)\n\}', original, re.S).group(1)
        enum = '\n'.join(line for line in enum.splitlines() if not line.strip().startswith('#['))
        variants = [line.strip().rstrip(',') for line in enum.splitlines() if line.strip()]
        self.assertEqual(variants, ['AllTools', 'Read', 'Edit', 'Convert', 'Sign'])
        start = original.index('            if self.mode == Mode::Read {', original.index(chrome.PDF_CENTRAL_BEFORE))
        end = original.index('\n        });', start)
        dispatch = textwrap.dedent(original[start:end])
        for before, after in [('combine_ui::page(self, ui)', 'Branch::Combine'), ('home::show(self, ui)', 'Branch::Home'), ('canvas::document_area(self, index, ui)', 'Branch::Document(index)'), ('docking::show(self, ui);', 'Branch::Docking')]:
            self.assertEqual(dispatch.count(before), 1)
            dispatch = dispatch.replace(before, after)
        block = chrome.PDF_CENTRAL_AFTER
        block = textwrap.dedent(block[block.index('        let central_fill ='):block.index('        egui::CentralPanel')])
        rustc = shutil.which('rustc')
        self.assertIsNotNone(rustc, 'Pinned Rust runtime is required for the actual dispatch regression')
        versions = [('exact', block, True), ('omit-combine', block.replace(' && !self.combine_showing()', ''), False), ('omit-active', block.replace(' && self.active.is_none()', ''), False), ('omit-mode', block.replace('self.mode == Mode::Read && ', ''), False)]
        with tempfile.TemporaryDirectory(prefix='bogo-pdf-chrome-dispatch-') as temporary:
            for name, fill, should_pass in versions:
                source = '''use std::cell::Cell;
#[derive(Clone, Copy, Debug, PartialEq, Eq)] enum Mode {''' + enum + '''}
#[derive(Clone, Copy, Debug, PartialEq, Eq)] enum Color { Panel, Pasteboard }
#[derive(Debug, PartialEq, Eq)] enum Branch { Home, Combine, Document(usize), Docking }
struct Tokens { panel: Color, pasteboard: Color }
#[derive(Debug)] struct State { mode: Mode, active: Option<usize>, combine: bool, calls: Cell<usize> }
impl State {
fn combine_showing(&self) -> bool { self.calls.set(self.calls.get() + 1); self.combine }
fn original_dispatch(&self) -> Branch {''' + dispatch + '''}
fn proposed_fill(&self, t: &Tokens) -> Color {''' + fill + '''central_fill }
}
#[test] fn all_original_dispatch_states() {
let t = Tokens { panel: Color::Panel, pasteboard: Color::Pasteboard }; let mut cases = 0;
for mode in [''' + ','.join('Mode::' + v for v in variants) + '''] { for active in [None, Some(0), Some(42)] { for combine in [false, true] {
let state = State { mode, active, combine, calls: Cell::new(0) }; let branch = state.original_dispatch(); let calls = state.calls.get(); state.calls.set(0);
let expected = if branch == Branch::Home { Color::Panel } else { Color::Pasteboard };
assert_eq!(state.proposed_fill(&t), expected, "{:?}; {:?}", state, branch);
assert_eq!(state.calls.get(), calls, "short-circuit behavior changed"); cases += 1;
}}} assert_eq!(cases, 30);
}
'''
                path = Path(temporary) / (name + '.rs')
                binary = Path(temporary) / name
                path.write_text(source, encoding='utf-8')
                compiled = subprocess.run([rustc, '--edition=2024', '--test', str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                result = subprocess.run([str(binary), '--nocapture'], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode == 0, should_pass, (name, result.stdout, result.stderr))

    def test_light_filmstrip_ink_choice_preserves_wcag_bound_across_background_hues(self):
        # Validate the independent WCAG bound across dark, selected, hovered and
        # saturated catalog-label hues, rather than requiring a fixed ink color.
        def luminance(rgb):
            channels = [v / 255 for v in rgb]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
            return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
        primary = luminance((0x34, 0x2B, 0x26))
        for red in range(0, 256, 17):
            for green in range(0, 256, 17):
                for blue in range(0, 256, 17):
                    background = luminance((red, green, blue))
                    ratio = (max(background, primary) + .05) / (min(background, primary) + .05)
                    if ratio < 4.5:
                        ratio = 1.05 / (background + .05)
                        if ratio < 4.5:
                            ratio = (background + .05) / .05
                    self.assertGreaterEqual(ratio, 4.5)


if __name__ == '__main__':
    unittest.main()
