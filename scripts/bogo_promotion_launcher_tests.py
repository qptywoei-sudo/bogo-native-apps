"""Adapt only obsolete Launcher UI promotion expectations; retain every test."""
from pathlib import Path
import re

from bogo_promotion_four import brace_end, identity, once, regular_source_file, require

API_COUNTS = {'chinese.rs': 1, 'french.rs': 1, 'german.rs': 1, 'hungarian.rs': 1,
              'japanese.rs': 1, 'polish.rs': 1, 'portuguese.rs': 1, 'russian.rs': 1,
              'spanish.rs': 1, 'ui.rs': 2}
TEST_ROOT = 'crates/ui-egui/tests/'
# Filled from both the authenticated post-brand source and its recorded rustfmt
# form. Unknown additions to a test file must never be silently discarded.
PREIMAGES = {
    'chinese.rs': ('3d18318506b23f1e2f36214445b1732f7340bc995a46db77feeb0d9656d734fc',),
    'french.rs': ('dab2f9c814184f3212061f9203e0f922ace15216783897de722ae577f2bb40fe',),
    'german.rs': ('bd2ccaae27d2f084bd6b0c21234f18521b7b4e1f40f727e1cc550fa716963bf8',),
    'hungarian.rs': ('e066f5c1b12a8ca3e8f3d65402f12f6a6e5dbd9aed6f214e2574ea2b35ad3d23',),
    'japanese.rs': ('db2f84e8d4a0c5be0468877829c7fe0cff2de6cb0ae5131d3e4018d81658db14',),
    'polish.rs': ('9f880656130fdaacfc2cf0bccbc94c5d3d5a5c24d42813e4e173d927a4d74f8c',),
    'portuguese.rs': ('95cf4e5567f3a4b2df857b5417b5af89b01e488867b56931975e22b999a50cc5',),
    'russian.rs': ('eb410c31c522a38212754195078f96c3393945b09db2ef6238d1754ab730d370',),
    'spanish.rs': ('fce083981f7662203bd7303a253483e741b3ba5f20833877d700e01b9ea1d6fd',),
    'ui.rs': ('562468f8885dc6143a67d50a3ec1680fc6c75384ed320bcd825e6637640b92cb',),
}

LINKS_VISIBLE = '''
    let (mut h, _) = harness(ViewMode::Grid, egui::Theme::Dark, true);
    h.run_steps(6);
    // Official Bogo product links remain; retired community widgets do not.
    assert_eq!(h.query_all_by_label("Discord").count(), 0);
    let shown_cards = h.query_all_by_label("GitHub").count();
    let shown_sites = h.query_all_by_label("Website").count();
    assert!(shown_cards >= 13, "{shown_cards}");
    assert_eq!(shown_sites, 13, "every Bogo app retains its official website page");
    let (mut h, _) = harness(ViewMode::Table, egui::Theme::Dark, true);
    h.run_steps(6);
    h.get_all_by_label("…").nth(7).unwrap().click(); // Bogo Word
    h.run_steps(3);
    h.get_by_label("GitHub repository");
    assert!(h.query_all_by_label_contains("Website").count() >= 1);
    assert_eq!(h.query_all_by_label("Discord").count(), 0);
'''

LINKS_OPEN = '''
    let (mut h, _) = harness(ViewMode::Grid, egui::Theme::Dark, true);
    h.run_steps(6);
    assert_eq!(click_opens(&mut h, "Discord"), None);
    let github = all_opened(&mut h, "GitHub");
    assert!(github.len() >= 13, "official Bogo product source links remain: {github:?}");
    assert!(github.iter().all(|url| url == "https://github.com/qptywoei-sudo/bogo-native-apps"), "{github:?}");
    let sites = all_opened(&mut h, "Website");
    assert!(!sites.contains(&"https://kio-library.vercel.app".to_string()), "the removed footer homepage must not remain: {sites:?}");
    assert!(sites.contains(&"https://kio-library.vercel.app/?program=photo".to_string()), "official product page remains: {sites:?}");
    for label in ["X", "YouTube", "TikTok", "Instagram", "LinkedIn"] {
        assert_eq!(h.query_all_by_label(label).count(), 0, "retired social widget: {label}");
        assert_eq!(click_opens(&mut h, label), None);
    }
    h.get_all_by_label("…").next().unwrap().click();
    h.run_steps(3);
    assert_eq!(click_opens(&mut h, "All releases").as_deref(), Some("https://github.com/qptywoei-sudo/bogo-native-apps/releases"));
'''

HUNGARIAN_COMMUNITY_BEFORE = '''        // The footer has the same services, and the cards behind the modal have Webhely and GitHub
        // links as one 14px line of text; keep only the settings body's buttons (34px) and icons (24px).
        let discord = h.get_by_label("Csatlakozás a Discordhoz").rect();
        let theme = h.get_by_label("Rendszerbeállítás szerint").rect();
        assert!(screen.contains_rect(discord), "community links must be reachable by scrolling");
        assert!(theme.bottom() < done.top(), "appearance controls must scroll above the fixed actions");
        let mut links = vec![discord];
        for label in ["Webhely", "GitHub", "X", "Instagram", "LinkedIn", "YouTube", "TikTok"] {
            let candidates: Vec<_> = h
                .query_all_by_label(label)
                .map(|n| n.rect())
                .filter(|r| r.top() >= discord.top() - 1.0 && r.bottom() < theme.top() && r.height() > 20.0)
                .collect();
            assert_eq!(candidates.len(), 1, "{width}x{height}: settings link {label}: {candidates:?}");
            links.extend(candidates);
        }
        for (i, r) in links.iter().enumerate() {
            assert!(screen.contains_rect(*r), "{width}x{height}: link is clipped: {r:?}");
            for other in links.iter().skip(i + 1) {
                assert!(!r.intersects(*other), "{width}x{height}: links overlap: {r:?}, {other:?}");
            }
        }
'''
HUNGARIAN_COMMUNITY_AFTER = '''        // Appearance controls still scroll above the fixed functional actions.
        let theme = h.get_by_label("Rendszerbeállítás szerint").rect();
        assert!(theme.bottom() < done.top(), "appearance controls must scroll above the fixed actions");
        for label in ["Csatlakozás a Discordhoz", "X", "Instagram", "LinkedIn", "YouTube", "TikTok"] {
            assert_eq!(h.query_all_by_label(label).count(), 0, "retired community widget: {label}");
        }
        // Official card links behind the modal remain small text, not settings buttons.
        for label in ["Webhely", "GitHub"] {
            let candidates: Vec<_> = h.query_all_by_label(label).map(|node| node.rect()).filter(|rect| rect.height() > 20.0).collect();
            assert!(candidates.is_empty(), "{width}x{height}: retired settings link {label}: {candidates:?}");
        }
'''


def replace_test_body(text, name, replacement):
    pattern = r'(?m)^#\[test\]\nfn ' + re.escape(name) + r'\(\)\s*\{'
    matches = list(re.finditer(pattern, text))
    require(len(matches) == 1, 'Expected one exact existing Launcher promotion test: ' + name)
    opening = matches[0].end() - 1
    end = brace_end(text, opening)
    return text[:opening + 1] + replacement + text[end - 1:]


def transform_ui(text):
    text = once(text, 'assert!(h.query_all_by_label_contains("Discord").count() >= 2); // header link and footer link', 'assert_eq!(h.query_all_by_label_contains("Discord").count(), 0); // retired header/footer promotion')
    text = once(text, '    h.get_by_label("Questions, ideas and news from the ArtCraft team");', '    h.get_by_label("Done"); // Settings really opened, rather than making absence vacuous.\n    assert!(h.query_by_label("Questions, ideas and news from the ArtCraft team").is_none());')
    text = once(text, '    assert!(h.query_all_by_label_contains("Discord").count() >= 2);', '    assert_eq!(h.query_all_by_label_contains("Discord").count(), 0);')
    text = replace_test_body(text, 'links_to_the_website_github_and_each_apps_pages', LINKS_VISIBLE)
    text = replace_test_body(text, 'links_open_the_right_pages', LINKS_OPEN)
    text = once(text, '        assert_eq!(right.len(), 8, "{width}: {right:?}");', '        assert_eq!(right.len(), 0, "{width}: retired footer promotions remain: {right:?}");')
    return once(text, '        assert_eq!(platform.is_some(), width > 720.0, "{width}: the platform label shows unless the window is narrow");', '        assert!(platform.is_some(), "{width}: removing promotions leaves room for the functional platform label");')


def transform(relative, text):
    require(relative.startswith(TEST_ROOT) and relative[len(TEST_ROOT):] in API_COUNTS, 'Launcher helper is restricted to exact existing UI test files')
    filename = relative[len(TEST_ROOT):]
    require(identity(text)['sha256'] in PREIMAGES[filename], 'Launcher UI test preimage differs from authenticated source')
    require(text.count('ArtCraft API') == API_COUNTS[filename], 'Launcher source-label expectation inventory changed')
    before_tests = re.findall(r'(?m)^fn ([a-zA-Z0-9_]+)\(', text)
    after = text.replace('ArtCraft API', 'Bogo catalog')
    if filename == 'ui.rs':
        after = transform_ui(after)
    elif filename == 'hungarian.rs':
        after = once(after, 'Kilépés az ArtCraft Launcherből', 'Kilépés a Bogo Launcherből')
        after = once(after, HUNGARIAN_COMMUNITY_BEFORE, HUNGARIAN_COMMUNITY_AFTER)
    require(before_tests == re.findall(r'(?m)^fn ([a-zA-Z0-9_]+)\(', after), 'Launcher test/helper inventory must remain intact')
    require('#[ignore' not in after and after.count('#[test]') == text.count('#[test]'), 'Launcher tests must not be removed or ignored')
    return after


def apply(source):
    source = Path(source)
    require(source.is_dir() and not source.is_symlink(), 'Launcher test source must be regular')
    planned = {}
    for filename in API_COUNTS:
        relative = TEST_ROOT + filename
        path = regular_source_file(source, relative)
        before = path.read_text(encoding='utf-8'); planned[relative] = transform(relative, before)
    for relative, after in planned.items():
        (source / relative).write_text(after, encoding='utf-8', newline='')
    return sorted(planned)
