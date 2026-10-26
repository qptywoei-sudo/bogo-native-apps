"""Exact UI-only promotion removal for Design, Vector, Grid and Photo.

Three engine files contain only retired promotional registries/query wiring. Their
complete authenticated before/after identities are separately closed and exported;
this module does not grant a directory-wide engine exception.
"""
from pathlib import Path
import hashlib
import re

APPS = ('design', 'vector', 'grid', 'photo')
PROTECTED_BEFORE = {
    ('design', 'crates/engine/src/links.rs'): ('1012dee41e72f8832fa324a296dcc6cccdd2df7b61d28c42706ce4a5d204d8a8', 1769),
    ('design', 'crates/engine/src/cmd/inspect.rs'): ('f8d05d83968e55964907464b7cc9f99e12ac018c696ceae8c88ede2796048fee', 5607),
    ('vector', 'crates/engine/src/cmd/help.rs'): ('89a83c76479c2f6946caf652e0bbf713fefbdb4f1cec86db689fbf585364ceaf', 2206),
}
PROTECTED_AFTER = {
    ('design', 'crates/engine/src/links.rs'): ('a865611c97bae5a9c85b744fed71e8b4f57fa2c542a66d05dc549338ddcdb008', 514),
    ('design', 'crates/engine/src/cmd/inspect.rs'): ('7286dc35bb9d261757625157c0646a2d3c2935b9d43df32aa5ad8c2cee177ffc', 5368),
    ('vector', 'crates/engine/src/cmd/help.rs'): ('36520d4c4893e2cb952a10b8518e30a8e25934b2021188d62f6dce6c6e83d173', 538),
}
SOURCE_ARCHIVES = {
    'design': '5044162f9e7c2260156419b7e2c69c87801c5facc88e6b7aaa3552aca70c2acf',
    'vector': '91582b06374205c80a07c58da465c4fd681452777ded9678c240cfca7e39489f',
}
WHOLE_UI_BEFORE = {
    ('vector', 'crates/ui-egui/src/community.rs'): ('93130a7d3cbe14120c5b94470cc15bc26d0b6f2902470a6cf5839b8936a862be', 4533),
    ('photo', 'crates/ui-egui/src/links.rs'): ('cfb04f96551c34a22c57f956ac64dc47bc24b238547cdf58fd6faae6c353e388', 5863),
}
DESIGN_QUERY = '''        cmd!(query "app.links", "Community & Project Links", [], None,
            "{} → {discord, website, appPage, github, issues} (ArtCraft Discord, website, DesignCraft page and repository)", always, |_, _| Ok(crate::links::all())),
'''
DESIGN_LINKS = '''//! Retired promotional registry. General document links are handled elsewhere.

use serde_json::{Value, json};

pub fn all() -> Value {
    json!({})
}

pub fn get(_key: &str) -> Option<&'static str> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retired_promotions_have_no_registered_urls() {
        assert!(all().as_object().unwrap().is_empty());
        for key in ["discord", "website", "appPage", "github", "issues"] {
            assert_eq!(get(key), None);
        }
    }
}
'''
VECTOR_HELP = '''//! Retired promotional commands. Document and editing command modules are unchanged.

use super::CommandSpec;

pub fn specs() -> Vec<CommandSpec> {
    Vec::new()
}

#[cfg(test)]
mod tests {
    use crate::Session;
    use serde_json::json;

    #[test]
    fn retired_promotions_are_not_engine_commands() {
        let mut session = Session::new();
        for id in ["help.discord", "help.website", "help.appPage", "help.github", "help.links"] {
            assert!(session.execute(id, &json!({})).is_err(), "{id}");
        }
    }
}
'''
VECTOR_COMMUNITY = '''//! No product promotion is rendered or dispatched by this module.

#[cfg(test)]
mod tests {
    #[test]
    fn retired_link_actions_do_not_open_the_browser() {
        use std::sync::{Arc, Mutex};
        let opened = Arc::new(Mutex::new(Vec::<String>::new()));
        let record = opened.clone();
        let services = crate::Services {
            open_url: Some(Box::new(move |url: &str| record.lock().unwrap().push(url.to_string()))),
            ..Default::default()
        };
        let mut app = crate::VectorcraftApp::new(vectorcraft_engine::Session::new(), services);
        for id in ["help.discord", "help.website", "help.appPage", "help.github", "help.links"] {
            crate::menus::invoke(&mut app, id, serde_json::json!({}));
            assert!(app.run(id, serde_json::json!({})).is_err(), "{id}");
        }
        assert!(opened.lock().unwrap().is_empty());
    }
}
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def once(text, before, after=''):
    require(text.count(before) == 1, 'Expected one exact promotion anchor: ' + before[:100])
    return text.replace(before, after, 1)


def between(text, start, end, replacement=''):
    require(text.count(start) == 1 and text.count(end) == 1, 'Promotion range anchors changed')
    first, last = text.index(start), text.index(end)
    require(last > first, 'Promotion range order changed')
    return text[:first] + replacement + text[last:]


def brace_end(text, start):
    """Rust-aware brace bound, ignoring strings, raw strings, chars and nested comments."""
    require(text[start] == '{', 'Expected opening Rust brace')
    depth, index = 0, start
    while index < len(text):
        if text.startswith('//', index):
            end = text.find('\n', index); index = len(text) if end < 0 else end + 1; continue
        if text.startswith('/*', index):
            nesting, index = 1, index + 2
            while index < len(text) and nesting:
                if text.startswith('/*', index): nesting += 1; index += 2
                elif text.startswith('*/', index): nesting -= 1; index += 2
                else: index += 1
            require(nesting == 0, 'Unterminated Rust comment'); continue
        raw = re.match(r'(?:b|c)?r(#{0,32})"', text[index:])
        if raw:
            stop = '"' + raw[1]; end = text.find(stop, index + raw.end())
            require(end >= 0, 'Unterminated Rust raw string'); index = end + len(stop); continue
        if text[index] == '"':
            index += 1
            while index < len(text):
                if text[index] == '\\': index += 2
                elif text[index] == '"': index += 1; break
                else: index += 1
            continue
        char = re.match(r"'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^'\\\r\n])'", text[index:])
        if char: index += char.end(); continue
        if text[index] == '{': depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0: return index + 1
        index += 1
    raise ValueError('Unterminated Rust promotion block')


def remove_block(text, anchor, suffix=''):
    require(text.count(anchor) == 1, 'Expected one promotion block: ' + anchor[:100])
    start = text.index(anchor); line = text.rfind('\n', 0, start) + 1
    require(not text[line:start].strip(), 'Promotion block must begin on its own line')
    opening = text.index('{', start); end = brace_end(text, opening)
    require(text[end:end + len(suffix)] == suffix, 'Promotion block suffix changed')
    end += len(suffix)
    if text[end:end + 1] == '\n': end += 1
    return text[:line] + text[end:]


def remove_function(text, name):
    matches = list(re.finditer(r'(?m)^(?:pub(?:\([^\n]*\))?\s+)?fn\s+' + re.escape(name) + r'\b', text))
    require(len(matches) == 1, 'Expected one promotion function: ' + name)
    start = matches[0].start(); end = brace_end(text, text.index('{', matches[0].end()))
    if text[end:end + 1] == '\n': end += 1
    return text[:start] + text[end:]


def drop_lines(text, pattern, count):
    lines = text.splitlines(keepends=True); removed = [line for line in lines if re.search(pattern, line)]
    require(len(removed) == count, 'Promotion line inventory changed: ' + pattern)
    return ''.join(line for line in lines if not re.search(pattern, line))


def design_chrome(text):
    text = remove_block(text, 'if crate::about::discord_button(ui, "Discord", vec2(78.0, 22.0))')
    text = once(text, '                        // Always one click away: the ArtCraft community Discord.\n')
    text = once(text, '            community_card(app, ui);\n')
    text = remove_function(text, 'community_card')
    return once(text, '/// Start screen: the ArtCraft community (Discord first) and project links.\n')


def design_about(text):
    text = once(text, 'use designcraft_engine::links;\n')
    text = once(text, 'use serde_json::json;\n')
    text = between(text, '/// The other ArtCraft apps (app-page slug, name, what it is)', '/// The About window\'s tabs')
    for name in ('paint_chat_icon', 'discord_button', 'link'):
        text = remove_function(text, name)
    text = once(text, 'pub const DISCORD: Color32 = Color32::from_rgb(0x58, 0x65, 0xf2);\n')
    text = once(text, "    let mut open: Option<&'static str> = None;\n")
    formatted_start = '''            ui.label(crate::rtl::widget(
                ui,
                egui::RichText::new(crate::i18n::tr(
                    &app.ui.language,
                    "Independent Bogo fork of DesignCraft v0.8.0 by the ArtCraft team. No upstream endorsement.",'''
    raw_start = '''            ui.label(crate::rtl::widget(
                ui,
                egui::RichText::new(crate::i18n::tr(&app.ui.language, "Independent Bogo fork of DesignCraft v0.8.0 by the ArtCraft team. No upstream endorsement."))'''
    candidates = [value for value in (formatted_start, raw_start) if value in text]
    require(len(candidates) == 1, 'Design About promotion source wrapper changed')
    start = candidates[0]
    end = '''            ui.add_space(12.0);
            ui.label(crate::rtl::widget(
                ui,
                egui::RichText::new(crate::i18n::tr(&app.ui.language, "Open source. No telemetry."))'''
    text = between(text, start, end)
    return remove_block(text, 'if let Some(k) = open')


def design_menus(text):
    ids = r'help\.(?:discord|appPage|github|issues|website|app)'
    text = drop_lines(text, r'^    \("' + ids + r'",', 6)
    text = drop_lines(text, r'^            "ui:help\.(?:discord|appPage|github|issues|website)",', 5)
    text = remove_block(text, '"help.app" => match p.get("app").and_then(Value::as_str)', ',')
    return remove_block(text, 'h if h.starts_with("help.") && designcraft_engine::links::get(&h[5..]).is_some() =>')


def design_native_menu(text):
    return drop_lines(text, r'(?:let discord = MenuItem::with_id\("dc-discord"|^            &discord,|items\.insert\("dc-discord")', 3)


def design_cli(text):
    start = text.index('fn usage_footer() -> String')
    end = brace_end(text, text.index('{', start))
    require(text[start:end].count('designcraft_engine::links::') == 3, 'Design CLI promotion footer changed')
    return text[:start] + 'fn usage_footer() -> String {\n    String::new()\n}' + text[end:]


def design_mcp(text):
    text = once(text, 'const INSTRUCTIONS: &str = "DesignCraft is a page-layout app', 'const INSTRUCTIONS: &str = "Bogo Design is a page-layout app')
    text = once(text, '"serverInfo": {"name": "designcraft", "title": "DesignCraft", "version": env!("CARGO_PKG_VERSION"), "websiteUrl": designcraft_engine::links::APP_PAGE},', '"serverInfo": {"name": "designcraft", "title": "Bogo Design", "version": env!("CARGO_PKG_VERSION")},')
    return once(text, '''                        "{INSTRUCTIONS} Backend: {}. Community: {} (Discord), {} (app page), {} (source). The `app.links` command returns these links.",
                        self.backend.describe(),
                        designcraft_engine::links::DISCORD,
                        designcraft_engine::links::APP_PAGE,
                        designcraft_engine::links::GITHUB
''', '''                        "{INSTRUCTIONS} Backend: {}.",
                        self.backend.describe()
''')


def vector_chrome(text):
    text = drop_lines(text, r'^            let discord = search && room >= ', 1)
    return remove_block(text, 'if discord')


def vector_canvas(text):
    return once(text, '''    ui.add_space(28.0);
    ui.label(egui::RichText::new(tl!("Community")).font(theme::semibold(14.0)).color(t.text));
    ui.add_space(10.0);
    crate::community::links(app, ui);
''')


def vector_about(text):
    text = once(text, '    crate::community::links(app, ui);\n')
    return once(text, 'Independent Bogo fork. Upstream by ArtCraft. MIT OR Apache-2.0.', 'MIT OR Apache-2.0.')


def vector_menus(text):
    text = once(text, 'vec![c("About Bogo Vector", "help.about"), c("Join Our Discord", "help.discord")]', 'vec![c("About Bogo Vector", "help.about")]')
    text = drop_lines(text, r'^                c\("(?:Join Our Discord|ArtCraft Website|Bogo Vector on getartcraft\.com|Bogo Vector on GitHub)", "help\.', 4)
    return remove_block(text, 'if matches!(id, "help.discord" | "help.website" | "help.appPage" | "help.github")')


def vector_native_tests(text):
    return once(text, 'assert!(help.contains(&"help.discord".to_string()) && !help.contains(&"help.about".to_string()), "{help:?}");', 'assert!(!help.contains(&"help.discord".to_string()) && !help.contains(&"help.about".to_string()), "{help:?}");')


def titlebar_tests(text, app):
    if app == 'vector':
        return once(text, 'assert_eq!(has("Discord"), width > 1000.0, "{width}: {texts:?}");', 'assert!(!has("Discord"), "retired promotion at {width}: {texts:?}");')
    return once(text, 'assert_eq!(has_discord, width > 1000.0, "Discord at {width}");', 'assert!(!has_discord, "retired promotion at {width}");')


def grid_dialogs(text):
    # The adjacent MIT/Apache copyright line is deliberately retained byte-for-byte.
    return drop_lines(text, r'^            ui\.(?:label\("Independent Bogo fork\. Original GridCraft|hyperlink_to\("Upstream source: GridCraft"|hyperlink_to\("Upstream GridCraft community")', 3)


def grid_native(text):
    return drop_lines(text, r'^                \("Upstream GridCraft (?:project|community…)", "url:', 2)


def photo_panels(text):
    text = remove_block(text, 'if ui.available_width() >= DISCORD_ROOM')
    return once(text, 'const DISCORD_ROOM: f32 = 120.0;\n')


def photo_canvas(text):
    return once(text, '''            ui.add_space(26.0);
            crate::links::discord_button(app, ui, 190.0);
            ui.add_space(10.0);
            crate::links::link_row(app, ui);
''')


def photo_dialogs(text):
    return once(text, '''            ui.add_space(12.0);
            ui.vertical_centered(|ui| {
                crate::links::discord_button(app, ui, 220.0);
                ui.add_space(8.0);
                crate::links::link_row(app, ui);
            });
''')


def photo_menus(text):
    text = drop_lines(text, r'^    \("help\.(?:discord|website|artcraftWebsite|github|reportIssue)",', 5)
    return remove_block(text, 'if let Some(url) = crate::links::url_for(id)')


def photo_links(text):
    # Preserve the generic document-link platform service implementation in full.
    sha, size = WHOLE_UI_BEFORE['photo', 'crates/ui-egui/src/links.rs']
    require(identity(text) == {'sha256': sha, 'bytes': size}, 'Photo promotion module preimage changed')
    match = re.search(r'(?m)^pub fn open\(', text)
    require(match is not None, 'Photo generic document-link helper missing')
    end = brace_end(text, text.index('{', match.end()))
    generic_open = text[match.start():end]
    return '''//! General document-link browser service. Product promotions are not registered.

use serde_json::{Value, json};
use crate::PhotocraftApp;

pub const COMMANDS: &[(&str, &str)] = &[];

pub fn url_for(_id: &str) -> Option<&'static str> {
    None
}

''' + generic_open + '''

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordinary_document_links_keep_the_platform_browser_service() {
        use std::sync::{Arc, Mutex};
        let opened = Arc::new(Mutex::new(Vec::<String>::new()));
        let record = opened.clone();
        let services = crate::Services {
            open_url: Some(Box::new(move |url: &str| {
                record.lock().unwrap().push(url.to_string());
                Ok(())
            })),
            ..Default::default()
        };
        let mut app = PhotocraftApp::new(photocraft_engine::Session::new(), services);
        let ctx = egui::Context::default();
        let target = "https://example.invalid/qa-document-link";
        assert_eq!(open(&mut app, &ctx, target)["url"], target);
        assert_eq!(*opened.lock().unwrap(), [target]);
    }

    #[test]
    fn only_functional_help_items_remain_and_retired_actions_are_absent() {
        let mut app = PhotocraftApp::new(photocraft_engine::Session::new(), Default::default());
        let ctx = egui::Context::default();
        let help: Vec<String> = crate::menus::menu_items(&app).into_iter().filter(|item| item.path == ["Help"] && item.id != "---").map(|item| item.id).collect();
        assert_eq!(help, ["help.systemInfo", "help.about"]);
        assert!(COMMANDS.is_empty());
        for id in ["help.discord", "help.website", "help.artcraftWebsite", "help.github", "help.reportIssue"] {
            assert_eq!(url_for(id), None);
            assert!(!crate::menus::is_live(id), "{id}");
            assert!(crate::menus::invoke(&mut app, &ctx, id, json!({})).is_err(), "{id}");
        }
    }
}
'''


def vector_community(text):
    sha, size = WHOLE_UI_BEFORE['vector', 'crates/ui-egui/src/community.rs']
    require(identity(text) == {'sha256': sha, 'bytes': size}, 'Vector promotion module preimage changed')
    return VECTOR_COMMUNITY


PLANS = {
    'design': {'crates/ui-egui/src/chrome.rs': design_chrome, 'crates/ui-egui/src/about.rs': design_about,
               'crates/ui-egui/src/menus.rs': design_menus, 'apps/designcraft/src/native_menu.rs': design_native_menu,
               'apps/designcraft-cli/src/main.rs': design_cli, 'crates/mcp/src/server.rs': design_mcp},
    'vector': {'crates/ui-egui/src/chrome.rs': vector_chrome, 'crates/ui-egui/src/canvas.rs': vector_canvas,
               'crates/ui-egui/src/dialogs/about.rs': vector_about, 'crates/ui-egui/src/menus.rs': vector_menus,
               'crates/ui-egui/src/community.rs': vector_community,
               'crates/ui-egui/src/tests_nativemenu.rs': vector_native_tests,
               'crates/ui-egui/src/titlebar.rs': lambda text: titlebar_tests(text, 'vector')},
    'grid': {'crates/ui-egui/src/dialogs.rs': grid_dialogs, 'apps/gridcraft/src/native_menu.rs': grid_native},
    'photo': {'crates/ui-egui/src/panels.rs': photo_panels, 'crates/ui-egui/src/canvas.rs': photo_canvas,
              'crates/ui-egui/src/dialogs.rs': photo_dialogs, 'crates/ui-egui/src/links.rs': photo_links,
              'crates/ui-egui/src/menus.rs': photo_menus, 'crates/ui-egui/src/titlebar.rs': lambda text: titlebar_tests(text, 'photo')},
}


def protected_transform(app, relative, raw):
    require((app, relative) in PROTECTED_BEFORE, 'No protected promotion exception for this exact file')
    expected_sha, expected_bytes = PROTECTED_BEFORE[app, relative]
    require(identity(raw) == {'sha256': expected_sha, 'bytes': expected_bytes}, 'Authenticated protected promotion preimage changed')
    text = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    if (app, relative) == ('design', 'crates/engine/src/cmd/inspect.rs'):
        changed = once(text, DESIGN_QUERY)
    else:
        changed = DESIGN_LINKS if app == 'design' else VECTOR_HELP
    sha, size = PROTECTED_AFTER[app, relative]
    require(identity(changed) == {'sha256': sha, 'bytes': size}, 'Protected promotion output differs from exact reviewed bytes')
    return changed


def protected_transition_allowed(app, relative, before, after):
    key = (app, relative)
    if key not in PROTECTED_BEFORE:
        return False
    old_sha, old_size = PROTECTED_BEFORE[key]; new_sha, new_size = PROTECTED_AFTER[key]
    return before == {'sha256': old_sha, 'bytes': old_size} and after == {'sha256': new_sha, 'bytes': new_size}


def regular_source_file(source, relative):
    path = source / relative
    require(path.is_file() and not path.is_symlink(), 'Missing regular promotion input: ' + relative)
    for parent in [source, *[p for p in path.parents if p != source and source in p.parents]]:
        metadata = parent.lstat()
        require(not parent.is_symlink() and not (getattr(metadata, 'st_file_attributes', 0) & 0x400), 'Linked promotion input ancestry refused')
    return path


def protected_changes(source, app):
    source = Path(source)
    result = []
    for (selected, relative), (sha, size) in PROTECTED_BEFORE.items():
        if selected != app:
            continue
        path = regular_source_file(source, relative)
        raw = path.read_bytes(); changed = protected_transform(app, relative, raw)
        result.append({'app': app, 'path': relative, 'sourceArchiveSha256': SOURCE_ARCHIVES[app],
                       'before': {'sha256': sha, 'bytes': size}, 'after': identity(changed),
                       'scope': 'retired promotional registry/query only; no document/edit/media operation whitelist'})
    return result


def apply(source, app):
    require(app in APPS, 'Unsupported four-app promotion transform')
    source = Path(source)
    require(source.is_dir() and not source.is_symlink(), 'Promotion source must be a regular prepared directory')
    planned = {}
    # Validate every exact marker before writing any file, including protected preimages.
    for relative, transform in PLANS[app].items():
        path = regular_source_file(source, relative)
        before = path.read_text(encoding='utf-8'); after = transform(before)
        require(before != after, 'Promotion transform made no change: ' + relative)
        planned[relative] = after
    for (selected, relative) in PROTECTED_BEFORE:
        if selected == app:
            planned[relative] = protected_transform(app, relative, regular_source_file(source, relative).read_bytes())
    for relative, text in planned.items():
        (source / relative).write_text(text, encoding='utf-8', newline='')
    return sorted(planned)
