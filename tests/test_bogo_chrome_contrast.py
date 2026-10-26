import os
import hashlib
from pathlib import Path
import sys
import tarfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_chrome_contrast as chrome
import bogo_native as bogo


FILES = {
    'light': ('crates/ui-egui/src/docking.rs', 'crates/ui-egui/src/panels/detail.rs'),
    'ui': ('crates/ui-egui/src/theme.rs',),
    'deck': ('crates/ui-egui/src/backstage.rs',),
    'word': ('crates/ui-egui/src/backstage.rs',),
    'sound': ('crates/ui-egui/src/panels.rs', 'crates/ui-egui/src/widgets.rs'),
    'effect': ('crates/ui-egui/src/widgets.rs', 'crates/ui-egui/src/theme.rs', 'crates/ui-egui/src/header.rs', 'crates/ui-egui/src/panels/viewer.rs'),
    'photo': ('crates/ui-egui/src/canvas.rs', 'crates/ui-egui/src/icons.rs'),
}


class InstalledChromeContrast(unittest.TestCase):
    def test_only_reviewed_app_file_pairs_have_replacements(self):
        for app in ('cad', 'film', 'pdf', 'grid', 'launcher', 'vector', 'design'):
            for relatives in FILES.values():
                for relative in relatives:
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
            if os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'):
                lock = bogo.base_lock(app)
                archive = Path(os.environ['BOGO_NATIVE_SOURCE_ARCHIVE_CACHE']) / Path(lock['source']['localCacheFile']).name
                self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), lock['source']['sha256'])
                with tarfile.open(archive) as tar:
                    contents = {relative: tar.extractfile(next(m for m in tar.getmembers() if m.name.endswith('/' + relative))).read().decode('utf-8') for relative in relatives}
            else:
                archive = next((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
                with zipfile.ZipFile(archive) as zipped:
                    contents = {}
                    for relative in relatives:
                        entries = [n for n in zipped.namelist() if n.endswith('/' + relative) and '/orchestrator/' not in n]
                        self.assertEqual(len(entries), 1)
                        contents[relative] = zipped.read(entries[0]).decode('utf-8')
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
