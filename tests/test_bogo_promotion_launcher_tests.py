import copy
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_brand as brand
import bogo_native as bogo
import bogo_promotion_launcher_tests as launcher_tests
from bogo_promotion_four import brace_end, identity
from test_bogo_promotion_four import apply_text_hunks, function_text


def authenticated_launcher_tests():
    lock = bogo.base_lock('launcher')
    archive = bogo.full.common.verified_archive(lock['source'], ROOT / '.cache/archives', False)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['source']['sha256']:
        raise ValueError('Original Launcher archive differs')
    branding = lock['branding']; patch_file = ROOT / branding['patch']; manifest_file = ROOT / branding['manifest']
    if hashlib.sha256(patch_file.read_bytes()).hexdigest() != branding['sha256'] or hashlib.sha256(manifest_file.read_bytes()).hexdigest() != branding['manifestSha256']:
        raise ValueError('Original Launcher branding patch differs')
    meta = {row['path']: row for row in json.loads(manifest_file.read_text(encoding='utf-8'))['files']}
    wanted = [launcher_tests.TEST_ROOT + name for name in launcher_tests.API_COUNTS]
    with tarfile.open(archive) as tar:
        original = {relative: tar.extractfile(lock['source']['root'] + '/' + relative).read().decode('utf-8') for relative in wanted}
    source = {}
    for relative, before in original.items():
        legacy = apply_text_hunks(before, patch_file.read_text(encoding='utf-8'), relative)
        if relative in meta and identity(legacy) != meta[relative]['after']:
            raise ValueError('Launcher legacy whole-file identity differs')
        source[relative] = brand.rust_display(legacy)
    return lock, source


def replace_function(text, name, replacement):
    match = re.search(r'(?m)^fn ' + re.escape(name) + r'\b', text)
    end = brace_end(text, text.index('{', match.end()))
    return text[:match.start()] + replacement + text[end:]


class LauncherPromotionTestAdaptation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock, cls.source = authenticated_launcher_tests()

    def test_every_original_test_and_nonpromotional_helper_remains(self):
        allowed = {'ui.rs': {'grid_shows_every_status_and_installs_on_click', 'settings_link_to_discord',
                            'links_to_the_website_github_and_each_apps_pages', 'links_open_the_right_pages',
                            'the_rate_limit_notice_never_runs_under_the_footer_links'},
                   'hungarian.rs': {'check_settings_layout'}}
        for relative, before in self.source.items():
            with self.subTest(relative=relative):
                after = launcher_tests.transform(relative, before)
                self.assertEqual(after.count('#[test]'), before.count('#[test]'))
                self.assertEqual(after.count('#[ignore'), before.count('#[ignore'))
                self.assertEqual(re.findall(r'(?m)^fn ([a-zA-Z0-9_]+)\(', before), re.findall(r'(?m)^fn ([a-zA-Z0-9_]+)\(', after))
                restored = after.replace('Bogo catalog', 'ArtCraft API')
                if relative.endswith('/ui.rs'):
                    restored = launcher_tests.restore_optional_link_helpers(restored)
                if relative.endswith('/hungarian.rs'):
                    restored = restored.replace('Kilépés a Bogo Launcherből', 'Kilépés az ArtCraft Launcherből')
                for name in allowed.get(Path(relative).name, set()):
                    restored = replace_function(restored, name, function_text(before, name))
                self.assertEqual(restored, before, 'Every byte outside the bounded obsolete UI-promotion expectations must remain exact')

    def test_ui_absence_still_checks_real_settings_install_updates_links_and_layout(self):
        relative = launcher_tests.TEST_ROOT + 'ui.rs'; after = launcher_tests.transform(relative, self.source[relative])
        grid = function_text(after, 'grid_shows_every_status_and_installs_on_click')
        for marker in ['h.get_by_label("Update all (2)").click()', 'assert_eq!(installs.len(), 2', 'installs.contains(&"photocraft".to_string())', 'h.get_by_label_contains("48 MB of 131 MB")']:
            self.assertIn(marker, grid)
        settings = function_text(after, 'settings_link_to_discord')
        self.assertIn('h.get_by_label("Settings").click()', settings)
        self.assertIn('h.get_by_label("Done")', settings)
        self.assertIn('query_all_by_label_contains("Discord").count(), 0', settings)
        links = function_text(after, 'links_open_the_right_pages')
        self.assertIn('github.len() >= 13', links)
        self.assertIn('https://github.com/qptywoei-sudo/bogo-native-apps', links)
        self.assertIn('https://kio-library.vercel.app/?program=photo', links)
        self.assertIn('"All releases"', links)
        layout = function_text(after, 'the_rate_limit_notice_never_runs_under_the_footer_links')
        for marker in ['notice.width() >= 120.0', 'notice.right() <= width', '!r.intersects(notice)', '!r.intersects(checked)', 'platform.is_some()', 'right.len(), 0']:
            self.assertIn(marker, layout)

    def test_hungarian_scroll_resize_and_fixed_functional_controls_are_preserved(self):
        relative = launcher_tests.TEST_ROOT + 'hungarian.rs'; before = self.source[relative]; after = launcher_tests.transform(relative, before)
        for marker in ['(1180.0, 900.0), (720.0, 500.0), (480.0, 500.0), (1180.0, 900.0)', 'screen.contains_rect(done)', 'screen.contains_rect(quit)', '!done.intersects(quit)', 'screen.contains_rect(title)', 'theme.bottom() < done.top()', 'h.get_by_label("Nyelv").scroll_to_me()', 'screen.contains_rect(language)']:
            self.assertIn(marker, before); self.assertIn(marker, after)
        self.assertIn('Kilépés a Bogo Launcherből', after)
        self.assertNotIn('let discord = h.get_by_label', after)
        self.assertIn('query_all_by_label(label).count(), 0', after)

    def test_locale_change_is_display_literal_only_not_protocol_or_security_ids(self):
        for relative, before in self.source.items():
            after = launcher_tests.transform(relative, before)
            self.assertEqual(before.count('Origin::ArtCraftApi'), after.count('Origin::ArtCraftApi'))
            self.assertEqual(before.count('Source::GitHubApi'), after.count('Source::GitHubApi'))
            if Path(relative).name not in ('ui.rs', 'hungarian.rs'):
                self.assertEqual(after, before.replace('ArtCraft API', 'Bogo catalog'))
        with self.assertRaisesRegex(ValueError, 'restricted to exact existing UI test files'):
            launcher_tests.transform('crates/native/src/backend.rs', 'ArtCraft API')

    def test_apply_is_atomic_and_rejects_changed_or_duplicate_obsolete_contracts(self):
        for invalid_name in ('ui.rs', 'hungarian.rs'):
            with self.subTest(invalid=invalid_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inputs = copy.deepcopy(self.source)
                inputs[launcher_tests.TEST_ROOT + invalid_name] += '\n// Unknown changed source\n'
                for relative, text in inputs.items():
                    path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, newline='')
                # Whole-file preimages refuse even additions unrelated to promotions.
                with self.assertRaises(ValueError):
                    launcher_tests.apply(root)
                self.assertEqual({relative: (root / relative).read_text(encoding='utf-8') for relative in inputs}, inputs)
        with self.assertRaises(ValueError):
            launcher_tests.transform(launcher_tests.TEST_ROOT + 'ui.rs', self.source[launcher_tests.TEST_ROOT + 'ui.rs'] * 2)

    def test_optional_query_whole_file_inverse_recovers_actual_authenticated_4dc_source(self):
        relative = launcher_tests.TEST_ROOT + 'ui.rs'
        after = launcher_tests.transform(relative, self.source[relative])
        launcher_tests.validate_optional_click_helper(after)
        recorded = launcher_tests.restore_optional_link_helpers(after)
        self.assertEqual(identity(recorded), launcher_tests.RECORDED_UI_BEFORE_QUERY_FIX)
        # This exact complete preimage is independently measured from the real
        # successful4dc Source job ZIP, not a fabricated reduced helper fixture.
        self.assertEqual(hashlib.sha256(recorded.encode()).hexdigest(),
                         'd866dd7d7bacd1ee5d251513233859d506fcea3d6ece7672778599ba08d5ed44')
        before_helper = function_text(self.source[relative], 'click_nth_opens')
        after_helper = function_text(after, 'click_nth_opens')
        self.assertEqual(after_helper.replace(launcher_tests.CLICK_QUERY_AFTER, launcher_tests.CLICK_QUERY_BEFORE), before_helper)

    def test_optional_query_preserves_every_positive_and_negative_link_assertion(self):
        relative = launcher_tests.TEST_ROOT + 'ui.rs'
        after = launcher_tests.transform(relative, self.source[relative])
        helper = function_text(after, 'click_nth_opens')
        self.assertIn(launcher_tests.CLICK_QUERY_AFTER, helper)
        self.assertNotIn(launcher_tests.CLICK_QUERY_BEFORE, helper)
        links = function_text(after, 'links_open_the_right_pages')
        for marker in ['assert_eq!(click_opens(&mut h, "Discord"), None)',
                       'github.len() >= 13',
                       'url == "https://github.com/qptywoei-sudo/bogo-native-apps"',
                       'https://kio-library.vercel.app/?program=photo',
                       'for label in ["X", "YouTube", "TikTok", "Instagram", "LinkedIn"]',
                       'assert_eq!(h.query_all_by_label(label).count(), 0',
                       'assert_eq!(click_opens(&mut h, label), None)',
                       'Some("https://github.com/qptywoei-sudo/bogo-native-apps/releases")']:
            self.assertIn(marker, links)
        all_opened = function_text(after, 'all_opened')
        self.assertEqual(all_opened.replace(launcher_tests.ALL_OPENED_AFTER, launcher_tests.ALL_OPENED_BEFORE),
                         function_text(self.source[relative], 'all_opened'))

    def test_optional_query_contract_rejects_broken_helper_or_weakened_assertions(self):
        relative = launcher_tests.TEST_ROOT + 'ui.rs'
        after = launcher_tests.transform(relative, self.source[relative])
        mutants = [after.replace(launcher_tests.CLICK_QUERY_AFTER, launcher_tests.CLICK_QUERY_BEFORE),
                   after + '\n' + launcher_tests.CLICK_QUERY_AFTER,
                   after.replace('assert_eq!(click_opens(&mut h, "Discord"), None);', ''),
                   after.replace('github.len() >= 13', 'github.len() >= 0'),
                   after.replace('https://github.com/qptywoei-sudo/bogo-native-apps/releases', 'https://example.invalid/releases'),
                   after.replace('assert_eq!(click_opens(&mut h, label), None);', ''),
                   after.replace('h.run_steps(4);\n    let target', 'h.run_steps(0);\n    let target'),
                   after.replace('h.query_all_by_label(label).nth(n)?;', 'h.query_all_by_label(label).next()?;'),
                   after.replace('assert!(!ids[..i].contains(id), "{label}: every link button must have a distinct identity");', ''),
                   after.replace('assert_eq!(&actual_id, expected_id, "{label}[{i}]: link order must remain stable");', ''),
                   after.replace('h.get_all_by_label("…").next().unwrap().scroll_to_me();', ''),
                   after.replace('.nth(n)?', '.next()?'),
                   after.replace('assert_eq!(target.accesskit_node().id(), target_id, "{label}[{n}]: scrolling must preserve the button identity");', '')]
        for mutant in mutants:
            with self.subTest(mutant=hashlib.sha256(mutant.encode()).hexdigest()), self.assertRaises(ValueError):
                launcher_tests.validate_optional_click_helper(mutant)

    def test_all_distinct_link_buttons_are_scrolled_settled_requeried_and_checked_in_order(self):
        relative = launcher_tests.TEST_ROOT + 'ui.rs'
        after = launcher_tests.transform(relative, self.source[relative])
        helper = function_text(after, 'click_nth_opens')
        self.assertEqual(helper.count('.nth(n)?'), 3, 'capture, scroll and click must address the same nth button')
        self.assertLess(helper.index('scroll_to_me()'), helper.index('h.run_steps(4)'))
        self.assertLess(helper.index('h.run_steps(4)'), helper.index('let target ='))
        self.assertLess(helper.index('let target ='), helper.index('assert_eq!(target.accesskit_node().id(), target_id'))
        self.assertLess(helper.index('assert_eq!(target.accesskit_node().id(), target_id'), helper.index('target.click()'))
        all_opened = function_text(after, 'all_opened')
        for marker in ['let ids: Vec<_>', '!ids[..i].contains(id)', 'ids.iter()', '.enumerate()',
                       'h.query_all_by_label(label).nth(i)', 'assert_eq!(&actual_id, expected_id',
                       'click_nth_opens(h, label, i).expect("every distinct reachable link must emit its own OpenUrl")']:
            self.assertIn(marker, all_opened)
        self.assertNotIn('filter_map', all_opened, 'a missed offscreen link must fail, not silently reduce coverage')
        links = function_text(after, 'links_open_the_right_pages')
        self.assertIn(launcher_tests.MORE_AFTER, links)
        self.assertIn('github.len() >= 13', links)


if __name__ == '__main__':
    unittest.main()
