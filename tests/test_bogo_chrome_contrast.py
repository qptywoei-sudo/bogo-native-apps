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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_chrome_contrast as chrome
import bogo_native as bogo


FILES = {
    'light': ('crates/ui-egui/src/docking.rs', 'crates/ui-egui/src/panels/detail.rs', 'crates/ui-egui/src/panels/bottombar.rs', 'crates/ui-egui/src/widgets.rs'),
    'pdf': tuple(chrome.PDF_ROLE_REPLACEMENTS),
    'ui': ('crates/ui-egui/src/theme.rs',),
    'deck': ('crates/ui-egui/src/backstage.rs',),
    'word': ('crates/ui-egui/src/backstage.rs',),
    'sound': ('crates/ui-egui/src/panels.rs', 'crates/ui-egui/src/widgets.rs'),
    'effect': ('crates/ui-egui/src/widgets.rs', 'crates/ui-egui/src/theme.rs', 'crates/ui-egui/src/header.rs', 'crates/ui-egui/src/panels/viewer.rs'),
    'photo': ('crates/ui-egui/src/canvas.rs', 'crates/ui-egui/src/icons.rs'),
}
FILES['light'] = tuple(sorted(set(FILES['light']) | set(chrome.LIGHT_ROLE_REPLACEMENTS)))
for _app, _path in chrome.EXTRA_VISUAL_REPLACEMENTS:
    FILES[_app] = tuple(sorted(set(FILES.get(_app, ())) | {_path}))


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
                        self.assertNotIn('if filled { t.star } else { t.icon });', after)
                        self.assertEqual(before.count('out = Some(if rating == i + 1 { 0 } else { i + 1 });'), after.count('out = Some(if rating == i + 1 { 0 } else { i + 1 });'))
                    if app == 'pdf' and relative.endswith('/home.rs'):
                        self.assertEqual(after.count('ui.painter().rect_filled(ui.max_rect(), 0.0, t.panel);'), 1)
                        self.assertLess(after.index('rect_filled(ui.max_rect()'), after.index('egui::ScrollArea::vertical()'))
                    if app == 'pdf' and relative.endswith('/tests/ui.rs'):
                        self.assertEqual(after.count('#[test]'), before.count('#[test]') + 2)
                        self.assertEqual(after.count('#[ignore'), before.count('#[ignore'))
                        self.assertIn('Mode::AllTools', after)
                        self.assertIn('Mode::Read', after)
                        self.assertIn('Action::Float', after)
                        self.assertIn('document_and_combine_pasteboards', after)

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

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_light_role_changes_preserve_image_inputs_semantic_fields_and_commands(self):
        import bogo_brand
        contents = archived_sources('light', FILES['light'])
        for relative, before in contents.items():
            after = chrome.transform('light', relative, before)
            # Existing commands, hit registration and image sampling calls stay exact.
            for pattern in [r'app\.run\([^\n]*', r'register\([^\n]*', r'\.(?:image|add_image)\([^\n]*']:
                self.assertEqual(re.findall(pattern, before), re.findall(pattern, after), relative)
            self.assertEqual(before.count('Sense::click'), after.count('Sense::click'), relative)
            self.assertEqual(before.count('Sense::hover'), after.count('Sense::hover'), relative)
            self.assertEqual(before.count('Sense::drag'), after.count('Sense::drag'), relative)
        relative = 'crates/ui-egui/src/theme.rs'
        branded = bogo_brand.theme(contents[relative])
        after = chrome.transform('light', relative, branded)
        fields = r'^\s*(?:canvas|grid_bg|star|pick|reject|mask_overlay|track|thumb|thumb_hover):.*$'
        self.assertEqual(re.findall(fields, branded, re.M), re.findall(fields, after, re.M))
        self.assertIn('pub fn readable_ink(', after)
        self.assertIn('pub fn media_label(', after)
        # Actual photo/HDR/Luminance/labels/clipping/mask inputs are excluded from the map.
        self.assertNotIn('crates/ui-egui/src/panels/masking.rs', chrome.LIGHT_ROLE_REPLACEMENTS)
        self.assertNotIn('crates/ui-egui/src/render.rs', chrome.LIGHT_ROLE_REPLACEMENTS)
        self.assertNotIn('crates/ui-egui/src/brush_live.rs', chrome.LIGHT_ROLE_REPLACEMENTS)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_actual_light_ink_function_meets_wcag_for_all_surface_roles_and_themes(self):
        relative = 'crates/ui-egui/src/theme.rs'
        original = archived_sources('light', (relative,))[relative]
        actual = chrome.transform('light', relative, original)
        start = actual.index('pub fn readable_ink(')
        end = actual.index('\n}\n', start) + 2
        function = actual[start:end]
        rustc = shutil.which('rustc')
        self.assertIsNotNone(rustc, 'Pinned Rust runtime required to execute the actual UI ink function')
        source = r"""
#[derive(Clone,Copy,Debug,PartialEq,Eq)] pub struct Color32([u8;3]);
impl Color32 {
 pub const WHITE:Self=Self([255,255,255]); pub const BLACK:Self=Self([0,0,0]);
 pub fn r(self)->u8{self.0[0]} pub fn g(self)->u8{self.0[1]} pub fn b(self)->u8{self.0[2]}
}
""" + function + r"""
fn lum(c:Color32)->f64 { c.0.into_iter().zip([0.2126,0.7152,0.0722]).map(|(v,w)| {
 let v=f64::from(v)/255.0; w*if v<=0.04045 {v/12.92} else {((v+0.055)/1.055).powf(2.4)}
}).sum() }
fn contrast(a:Color32,b:Color32)->f64 {let(a,b)=(lum(a),lum(b)); (a.max(b)+0.05)/(a.min(b)+0.05)}
#[test] fn actual_opaque_ink_is_readable_for_all_surface_samples(){
 let inks=[Color32([52,43,38]),Color32([252,117,1]),Color32([216,216,216])];
 for r in (0u8..=255).step_by(17){for g in (0u8..=255).step_by(17){for b in (0u8..=255).step_by(17){
 let bg=Color32([r,g,b]);for preferred in inks {let ink=readable_ink(bg,preferred);assert!(contrast(ink,bg)>=4.5-1e-6,"{:?} {:?}",ink,bg);
 if contrast(preferred,bg)>=4.501 {assert_eq!(ink,preferred);}
 }}}}
 // The four original canvas/grid kinds, warm chrome, active surfaces and warning accents.
 for bg in [[28,28,28],[18,18,18],[207,207,207],[236,236,236],[15,15,15],[8,8,8],[217,217,217],[242,242,242],[255,250,246],[255,231,212],[252,117,1],[224,74,74]] {
 assert!(contrast(readable_ink(Color32(bg),inks[0]),Color32(bg))>=4.5);
 }
}
#[test] fn fixed_black_alpha_media_labels_keep_legible_white_over_every_photo(){
 for r in (0u8..=255).step_by(17){for g in (0u8..=255).step_by(17){for b in (0u8..=255).step_by(17){
 let composed=Color32([r*35/255,g*35/255,b*35/255]);assert!(contrast(Color32::WHITE,composed)>=4.5);
 }}}
}
"""
        # Avoid integer multiplication overflow in the independent alpha-compositing oracle.
        source = source.replace('r*35/255,g*35/255,b*35/255', '(u16::from(r)*35/255) as u8,(u16::from(g)*35/255) as u8,(u16::from(b)*35/255) as u8')
        with tempfile.TemporaryDirectory(prefix='bogo-light-actual-ink-') as temporary:
            path = Path(temporary) / 'actual_ink.rs'
            binary = Path(temporary) / 'actual_ink'
            path.write_text(source, encoding='utf-8')
            compiled = subprocess.run([rustc, '--edition=2024', '--test', str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary), '--nocapture'], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('2 passed; 0 failed', result.stdout)

    def test_pdf_surface_patch_targets_actual_home_and_adds_mandatory_real_harness_cases(self):
        self.assertNotIn('crates/ui-egui/src/lib.rs', chrome.PDF_ROLE_REPLACEMENTS)
        home = chrome.PDF_ROLE_REPLACEMENTS['crates/ui-egui/src/home.rs']
        self.assertEqual(len(home), 2)
        self.assertIn('rect_filled(ui.max_rect(), 0.0, t.panel)', home[0][1])
        self.assertIn('press.fill(t.card, t.hover, t.pressed)', home[1][1])
        test = chrome.PDF_ROLE_REPLACEMENTS['crates/ui-egui/tests/ui.rs'][0][1]
        for evidence in ['h.output().shapes', 'clip_rect.contains(point)', 'painted_text(h)', 'canvases.iter().rev()', 'rect.contains(heading)', 'view.viewport_rect()', 'visible_page_rects()', 'panel: Panel::Tools', 'the document Canvas remains protected', 'a refused docking action cannot mutate layout', 'Mode::AllTools', 'Mode::Read', 'Action::Float', 'open_bytes("fixture.pdf", None, FIXTURE.to_vec())', 'open_combine_tab()']:
            self.assertIn(evidence, test)
        self.assertEqual(test.count('#[test]'), 2)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_pdf_dock_tab_uses_pressed_role_without_recoloring_document_selection(self):
        relative = 'crates/ui-egui/src/docking.rs'
        before = archived_sources('pdf', (relative,))[relative]
        rows = chrome.PDF_ROLE_REPLACEMENTS[relative]
        self.assertEqual(rows, [('    style.active_background = t.selected;', '    style.active_background = t.pressed;', 1)])
        after = chrome.transform('pdf', relative, before)
        self.assertEqual(after.replace(rows[0][1], rows[0][0]), before)
        self.assertEqual(before[before.index('fn permissions('):before.index('pub fn show(')], after[after.index('fn permissions('):after.index('pub fn show(')])
        theme_path = 'crates/ui-egui/src/theme.rs'
        theme = archived_sources('pdf', (theme_path,))[theme_path]
        self.assertEqual(chrome.transform('pdf', theme_path, theme), theme)
        from bogo_brand import theme as brand_theme
        final_theme = brand_theme(theme)
        pressed = re.findall(r'^\s*pressed:\s*Color32::from_rgb\(([^\n]+)\),', final_theme, re.M)
        self.assertEqual(pressed, ['0xFF, 0xE7, 0xD4'] * 2)
        source_tests = chrome.PDF_ROLE_REPLACEMENTS['crates/ui-egui/tests/ui.rs'][0][1]
        self.assertIn('text == "Tools"', source_tests)
        self.assertIn('bogo_last_opaque_fill(&default, tools.2.center())', source_tests)
        self.assertIn('the actual selected docktab uses the Bogo chrome selection surface', source_tests)
        self.assertEqual(source_tests.count('#[test]'), 2)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_photo_recovery_warning_uses_readable_ink_without_changing_renderer_state_or_semantic_warning(self):
        relative = 'crates/ui-egui/src/gpu_status.rs'
        before = archived_sources('photo', (relative,))[relative]
        rows = chrome.replacements('photo', relative)
        self.assertEqual(len(rows), 1)
        old, new, count = rows[0]
        self.assertEqual(count, 1)
        self.assertIn('GPU acceleration could not continue. Your documents are unchanged.', old)
        self.assertEqual(new, old.replace('.color(t.warning)', '.color(t.text)'))
        after = chrome.transform('photo', relative, before)
        self.assertEqual(after.replace(new, old), before)
        self.assertEqual(before[before.index('#[cfg(test)]'):], after[after.index('#[cfg(test)]'):])
        def lum(rgb):
            values = [x / 255 for x in rgb]
            values = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in values]
            return sum(x * w for x, w in zip(values, (.2126, .7152, .0722)))
        background, ink, old_ink = lum((255,250,246)), lum((52,43,38)), lum((232,176,70))
        self.assertGreaterEqual((background + .05) / (ink + .05), 4.5)
        self.assertLess((background + .05) / (old_ink + .05), 4.5)
        for changed in ('crates/ui-egui/src/renderer.rs', 'crates/engine/src/gpu_status.rs'):
            self.assertEqual(chrome.transform('photo', changed, before), before)

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_film_chrome_focus_does_not_modify_media_tokens_or_user_preferences(self):
        relative = 'crates/ui-egui/src/theme.rs'
        before = archived_sources('film', (relative,))[relative]
        after = chrome.transform('film', relative, before)
        fields = r'^\s*(?:pub\s+)?(?:accent|focus|playhead|hot_text|track_target)[A-Za-z_]*:.*$'
        self.assertEqual(re.findall(fields, before, re.M), re.findall(fields, after, re.M))
        start = before.index('pub fn with_appearance')
        end = before.index('\n    }', start) + len('\n    }')
        function = before[start:end]
        self.assertIn(function, after)
        self.assertIn('pub chrome_focus: Color32,', after)
        self.assertIn('chrome_focus: Color32::from_rgb(0xFC, 0x75, 0x01),', after)
        tools = 'crates/ui-egui/src/panels/tools.rs'
        source = archived_sources('film', (tools,))[tools]
        result = chrome.transform('film', tools, source)
        self.assertIn('current.icon(), t.icon);', result)
        self.assertIn('egui::Stroke::new(1.5, t.chrome_focus)', result)
        self.assertEqual(source.count('ui.interact('), result.count('ui.interact('))

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_actual_deck_display_mapping_changes_only_the_builtin_label_not_stored_ids(self):
        relative = 'crates/ui-egui/src/theme.rs'
        before = archived_sources('deck', (relative,))[relative]
        after = chrome.transform('deck', relative, before)
        start = after.index('pub(crate) fn builtin_display_name(')
        end = after.index('\n}', start) + 2
        function = after[start:end]
        source = function + '''
#[test] fn display_label_only() {
 assert_eq!(builtin_display_name("DeckCraft"), "Bogo Deck");
 for original in ["", "DeckCraft Custom", "my DeckCraft", "Bogo Deck", "Paper", "Dark", "測試", "테마"] {
  assert_eq!(builtin_display_name(original), original);
 }
 let stored_id = String::from("DeckCraft");
 let _ = builtin_display_name(&stored_id); assert_eq!(stored_id, "DeckCraft");
}
'''
        rustc = shutil.which('rustc')
        self.assertIsNotNone(rustc)
        with tempfile.TemporaryDirectory(prefix='bogo-deck-display-') as temporary:
            path, binary = Path(temporary) / 'display.rs', Path(temporary) / 'display'
            path.write_text(source, encoding='utf-8')
            built = subprocess.run([rustc, '--edition=2024', '--test', str(path), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        ribbon = 'crates/ui-egui/src/ribbon.rs'
        original = archived_sources('deck', (ribbon,))[ribbon]
        result = chrome.transform('deck', ribbon, original)
        # Keep every operation and its raw model names; only label/search expressions change.
        self.assertEqual(re.findall(r'app\.run\([^\n]*', original), re.findall(r'app\.run\([^\n]*', result))
        self.assertEqual(re.findall(r'let names[^\n]*', original), re.findall(r'let names[^\n]*', result))

    @unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES') or os.environ.get('BOGO_NATIVE_SOURCE_ARCHIVE_CACHE'), 'exact original source archives required')
    def test_real_brand_pipeline_reaches_exact_profiles_ui_role_without_touching_storage_files(self):
        import bogo_brand
        relative = 'crates/ui-egui/src/panels/profiles.rs'
        original = archived_sources('light', (relative,))[relative]
        expected = chrome.transform('light', relative, original)
        self.assertNotEqual(original, expected)
        for app in ('light', 'pdf'):
            with self.subTest(app=app), tempfile.TemporaryDirectory(prefix='bogo-settings-role-') as temporary:
                source = Path(temporary)
                ui = source / relative
                ui.parent.mkdir(parents=True)
                ui.write_text(original, encoding='utf-8')
                storage = source / 'crates/core/src/profiles.rs'
                storage.parent.mkdir(parents=True)
                sentinel = 'const STORAGE_KEY: &str = "KIO Light"; // if favorite { t.accent } else { t.text_dim }\n'
                storage.write_text(sentinel, encoding='utf-8')
                unrelated_ui = source / 'crates/ui-egui/src/other/profiles.rs'
                unrelated_ui.parent.mkdir(parents=True)
                unrelated_ui.write_text(sentinel, encoding='utf-8')
                # This isolates the real source routing, not the separately
                # authenticated icon and promotion subsystems.
                with mock.patch.object(bogo_brand, 'icon_assets'), mock.patch.object(bogo_brand, 'remove_promotions'):
                    bogo_brand.transform_source(source, app)
                self.assertEqual(ui.read_text(encoding='utf-8'), expected if app == 'light' else original)
                self.assertEqual(storage.read_text(encoding='utf-8'), sentinel)
                self.assertEqual(unrelated_ui.read_text(encoding='utf-8'), sentinel)


if __name__ == '__main__':
    unittest.main()
