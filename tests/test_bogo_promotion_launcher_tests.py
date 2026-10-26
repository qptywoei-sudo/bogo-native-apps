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


if __name__ == '__main__':
    unittest.main()
