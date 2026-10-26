"""Remove obsolete promotional UI/actions while preserving legal and data identities.

The recorder applies this after normal Bogo display/theme changes. These are
reviewed source contracts, not a global replacement of author/license strings.
"""
import json
import re
from pathlib import Path
import hashlib

from bogo_promotion_four import apply as apply_four
from bogo_promotion_launcher_tests import apply as apply_launcher_tests

APPS = {'cad','design','vector','film','light','pdf','effect','ui','word','sound','deck','grid','launcher','photo'}
PROMOTION = re.compile(r'discord|getartcraft|aircraft|artcraft(?:\s+(?:website|family|apps|community|team))|github\.com/storytold',re.I)
LEGAL = re.compile(r'copyright|©|license|licensed|licence|MIT OR Apache|Apache-2',re.I)
LIGHT_RETRY_KEY = '{n} change{} saved in memory but not written to disk: {e}\nLightCraft retries automatically; quitting now would lose {}.'
LIGHT_RETRY_FORMATS = {f'crates/ui-egui/locales/{locale}-formats.json': locale not in ('ja','pt-br')
                       for locale in ('de','es','fr','ja','pt-br','ru','uk','zh-hans','zh-hant')}

# Only compiled-in public demonstrations and their exact test/benchmark
# references. Existing documents, model operations and technical theme IDs are
# never scanned or rewritten by these contracts.
SAMPLE_LITERAL_REPLACEMENTS = {
    ('film','crates/engine/src/demo.rs'): [('"FilmCraft Demo"','"Bogo Film Demo"',2)],
    ('film','crates/project/src/gtemplate.rs'): [('Made with FilmCraft','Made with Bogo Film',1)],
    ('light','crates/engine/src/demo.rs'): [('creator: "LightCraft Demo".into(),','creator: "Bogo Light Demo".into(),',1)],
    ('effect','crates/engine/src/demo.rs'): [('"EffectCraft Intro"','"Bogo Effect Intro"',1),('"Built with EffectCraft"','"Built with Bogo Effect"',2),('"EFFECTCRAFT"','"Bogo Effect"',2)],
    ('effect','crates/engine/src/tests.rs'): [('"EFFECTCRAFT"','"Bogo Effect"',1)],
    ('effect','crates/ui-egui/tests/ui_agent_audit.rs'): [('"EFFECTCRAFT"','"Bogo Effect"',2)],
    ('effect','xtask/src/bench.rs'): [('"EffectCraft Intro"','"Bogo Effect Intro"',1)],
    ('word','crates/engine/src/sample.rs'): [('d.core.creator = "WordCraft".into();','d.core.creator = "Bogo Word".into();',1)],
    ('deck','crates/engine/src/sample.rs'): [('Welcome everyone. This deck was made in DeckCraft.','Welcome everyone. This deck was made in Bogo Deck.',1),('Made with DeckCraft — free and open source','Made with Bogo Deck — free and open source',1)],
}


def replace_exact(text, before, after='', count=1):
    if text.count(before) != count:
        raise ValueError('Unreviewed promotion source contract: '+before[:130])
    return text.replace(before,after)


def block_end(text, opening):
    """Find a Rust brace pair without treating strings/comments as syntax."""
    if text[opening]!='{':raise ValueError('Expected Rust opening brace')
    depth=0;i=opening
    while i<len(text):
        if text.startswith('//',i):
            end=text.find('\n',i);i=len(text)if end<0 else end+1;continue
        if text.startswith('/*',i):
            n=1;i+=2
            while i<len(text)and n:
                if text.startswith('/*',i):n+=1;i+=2
                elif text.startswith('*/',i):n-=1;i+=2
                else:i+=1
            continue
        raw=re.match(r'r(#+)?"',text[i:])
        if raw:
            ending='"'+(raw[1]or'');end=text.find(ending,i+raw.end())
            if end<0:raise ValueError('Unterminated Rust raw string')
            i=end+len(ending);continue
        if text[i]=='"':
            i+=1
            while i<len(text):
                if text[i]=='\\':i+=2
                elif text[i]=='"':i+=1;break
                else:i+=1
            continue
        if text[i]=='{':depth+=1
        elif text[i]=='}':
            depth-=1
            if depth==0:return i+1
        i+=1
    raise ValueError('Unbalanced Rust promotion block')


def remove_block(text, marker, trailing=''):
    if text.count(marker)!=1:raise ValueError('Ambiguous promotion block: '+marker)
    at=text.index(marker);start=text.rfind('\n',0,at)+1;opening=text.index('{',at);end=block_end(text,opening)
    if trailing:
        if not text.startswith(trailing,end):raise ValueError('Unexpected promotion block suffix')
        end+=len(trailing)
    if end<len(text)and text[end]=='\n':end+=1
    return text[:start]+text[end:]


def between(text, begin, end, replacement=''):
    if text.count(begin)!=1 or text.count(end)!=1:
        raise ValueError('Unreviewed promotion range: '+begin[:100])
    a=text.index(begin);b=text.index(end,a)
    return text[:a]+replacement+text[b:]


def function(text, signature, body):
    if text.count(signature)!=1:raise ValueError('Unreviewed promotion function: '+signature)
    a=text.index(signature);opening=text.index('{',a);end=block_end(text,opening)
    return text[:opening+1]+'\n'+body+'\n'+text[end-1:]


def drop_lines(text, pattern):
    return ''.join(line for line in text.splitlines(keepends=True) if not re.search(pattern,line))


def remove_line(text,line):
    rows=text.splitlines(keepends=True)
    if sum(row.strip()==line for row in rows)!=1:raise ValueError('Unreviewed promotional line: '+line)
    return ''.join(row for row in rows if row.strip()!=line)


def light_retry_brand(relative,text):
    """Keep the functional unsaved-data warning and every formatting argument."""
    renamed=LIGHT_RETRY_KEY.replace('LightCraft','Bogo Light')
    if relative=='crates/ui-egui/src/panels/topbar.rs':
        return replace_exact(text,json.dumps(LIGHT_RETRY_KEY,ensure_ascii=False),json.dumps(renamed,ensure_ascii=False))
    if relative not in LIGHT_RETRY_FORMATS:return text
    rows=text.splitlines(keepends=True)
    encoded_key=json.dumps(LIGHT_RETRY_KEY,ensure_ascii=False)
    matches=[i for i,row in enumerate(rows)if row.lstrip().startswith(encoded_key+':')]
    if len(matches)!=1:raise ValueError('Unreviewed Light retry locale key: '+relative)
    index=matches[0];row=rows[index]
    pair=json.loads('{'+row.strip().removesuffix(',')+'}')
    if set(pair)!={LIGHT_RETRY_KEY}or not isinstance(pair[LIGHT_RETRY_KEY],str):
        raise ValueError('Unreviewed Light retry locale row: '+relative)
    expected_mentions=1 if LIGHT_RETRY_FORMATS[relative]else 0
    if pair[LIGHT_RETRY_KEY].count('LightCraft')!=expected_mentions or row.count('LightCraft')!=1+expected_mentions:
        raise ValueError('Unreviewed Light retry translated brand: '+relative)
    # Only this one source-key/translation pair changes; surrounding JSON bytes stay exact.
    rows[index]=row.replace('LightCraft','Bogo Light')
    return ''.join(rows)


def localization(relative,text):
    if not (any('/'+part+'/'in'/'+relative for part in('locales','i18n','translations')) or relative.endswith('/i18n.rs')):return text
    if relative.endswith('.rs'):
        text=drop_lines(text,r'^\s*\("help\.(discord|website|appPage|github|reportIssue|sibling|onlineTutorials)",')
        text=''.join(line for line in text.splitlines(keepends=True)if not(
            re.match(r'^\s*\("',line)and re.search(r'\),\s*$',line)and
            (PROMOTION.search(line)or 'ArtCraft'in line)and not LEGAL.search(line)))
        # Embedded translated UI catalogs use one reviewed tuple per entry.
        text=re.sub(r'^    \(\n.*?^    \),\n',lambda m:''if PROMOTION.search(m[0])and not LEGAL.search(m[0])else m[0],text,flags=re.M|re.S)
    if relative.endswith('.tsv'):
        text=text.replace('Kilépés az ArtCraft Launcherből','Kilépés a Bogo Launcherből')
        # A functional update instruction is not a promotion; Hungarian inflects the app name.
        if relative=='crates/ui-egui/src/i18n/hu.tsv':
            text=text.replace('\tOpen Bogo Launcher to update.\tNyisd meg az ArtCraft Launchert a frissítéshez.', '\tOpen Bogo Launcher to update.\tNyisd meg a Bogo Launchert a frissítéshez.')
        return ''.join(line for line in text.splitlines(keepends=True)if not((PROMOTION.search(line)or re.search(r'ArtCraft',line))and not LEGAL.search(line)))
    if relative.endswith('.json'):
        obj=json.loads(text)
        if isinstance(obj,dict):
            filtered={key:value for key,value in obj.items()if not(PROMOTION.search(str(key)+' '+str(value))and not LEGAL.search(str(key)+' '+str(value)))}
            if len(filtered)!=len(obj):return json.dumps(filtered,ensure_ascii=False,indent=2)+'\n'
    return text


def _simple_about(text):
    # Every retained line containing legal attribution is kept byte-for-byte.
    return ''.join(line for line in text.splitlines(keepends=True)if not(
        ('ui.hyperlink_to('in line and PROMOTION.search(line))or
        ('ui.label('in line and 'Independent Bogo fork' in line and not LEGAL.search(line))))


def transform(app,relative,text):
    if app not in APPS:return text
    if app=='light':text=light_retry_brand(relative,text)
    text=localization(relative,text)
    if (app,relative)in{('sound','crates/ui-egui/src/panels.rs'),('ui','crates/ui-egui/src/dialogs.rs'),('deck','crates/ui-egui/src/dialogs.rs')}:
        text=_simple_about(text)
    if app=='ui'and relative=='crates/ui-egui/src/dialogs.rs':
        text=replace_exact(text,'Dual-licensed MIT OR Apache-2.0. Made by the ArtCraft team and community.','Dual-licensed MIT OR Apache-2.0.')
    if app=='ui'and relative=='crates/ui-egui/src/lib.rs':
        text=replace_exact(text,'            "open.help" => self.services.open_url("https://getartcraft.com/apps/figcraft"),\n','            "open.help" => self.ui.shortcuts_panel = true,\n')
    if app=='cad'and relative=='crates/ui-egui/src/dialogs.rs':
        label='Independent Bogo fork of CADCraft v0.7.0 by the ArtCraft team. No upstream endorsement.'
        if text.count(label)!=1:raise ValueError('Unreviewed CAD About blurb')
        pattern=r'(?m)^[ \t]*ui\.label\(\s*RichText::new\(crate::tl!\("'+re.escape(label)+r'"\)\)\s*\.color\(t.text_dim\),?\s*\);[ \t]*\n'
        text,count=re.subn(pattern,'',text)
        if count!=1:raise ValueError('Unreviewed CAD About label wrapper')
        text=_simple_about(text)
    if app=='cad'and relative=='apps/cadcraft/src/native_menu.rs':
        text=replace_exact(text,'    let discord = MenuItem::with_id("cc-discord", i18n::tr(language, "Join the ArtCraft Discord…"), true, None);\n','')
        text=replace_exact(text,'&about, &discord, &PredefinedMenuItem::separator()','&about, &PredefinedMenuItem::separator()')
        text=replace_exact(text,'    items.insert("cc-discord".into(), ("ui.discord".into(), "Join the ArtCraft Discord…".into(), discord));\n','')
        text=replace_exact(text,'''                if cmd == "ui.discord" {
                    ctx.open_url(egui::OpenUrl::new_tab("https://discord.gg/artcraft"));
                } else {
                    menus::activate(app, &cmd.clone());
                }''','''                menus::activate(app, &cmd.clone());''')
    if app=='word':
        if relative=='crates/ui-egui/src/chrome.rs':text=remove_block(text,'if app.ui.show_discord {')
        elif relative=='crates/ui-egui/src/ribbon.rs':text=remove_line(text,'big(ui, app, "discord", "Community\\nDiscord", "ui.discord", json!({}), false);')
        elif relative=='crates/ui-egui/src/options.rs':text=remove_line(text,'ui.checkbox(&mut app.ui.show_discord, tl!("Show the community button in the title bar"));')
        elif relative=='crates/ui-egui/src/keytips.rs':text=replace_exact(text,'d("Help", "about"), c("Community Discord", "ui.discord"), d("Commands", "commands")','d("Help", "about"), d("Commands", "commands")')
        elif relative=='crates/ui-egui/src/lib.rs':
            text=remove_block(text,'"ui.discord" => {')
            text=drop_lines(text,r'^\s*\| "ui.discord"$')
            text=text.replace('"ui.tab", "ui.discord", "file.options"','"ui.tab", "file.options"')
    return text


def app_text(app, relative, text):
    text = transform(app, relative, text)
    for before,after,count in SAMPLE_LITERAL_REPLACEMENTS.get((app,relative),[]):
        text=replace_exact(text,before,after,count)
    if app=='cad'and relative=='crates/engine/src/sample.rs':
        return replace_exact(text,'CADCRAFT SAMPLE','Bogo CAD SAMPLE')
    if app == 'film':
        if relative == 'crates/ui-egui/src/links.rs':
            text = between(text, 'pub const ALL:', '\n/// A link the web browser', 'pub const ALL: [(&str, &str, &str); 0] = [];\n')
            text=replace_exact(text,'assert_eq!(url_for("help.discord"), Some(DISCORD));','assert_eq!(url_for("help.discord"), None);')
        elif relative == 'crates/ui-egui/src/menus.rs':
            text = drop_lines(text, r'uic!\("help\.(discord|website|appPage|github|reportIssue)"')
        elif relative == 'apps/filmcraft/src/native_menu.rs':
            text = drop_lines(text, r'let discord =|^\s*&discord,')
            text = replace_exact(text, '[("app.about", &about), ("help.discord", &discord)]', '[("app.about", &about)]')
        elif relative == 'crates/ui-egui/src/header.rs':
            a = text.index('    // Community: a labelled Discord button, always one click away.')
            b = text.index('    let popup_id =', a)
            title = text[text.index('        // Localized menus', a):text.index('\n        if resp.clicked()', a)]
            title = title.replace('let right = r.min.x - 12.0;', 'let right = wr.min.x - 12.0;')
            text = text[:a] + '    {\n' + title + '\n    }\n' + text[b:]
        elif relative == 'crates/ui-egui/src/panels/import_mode.rs':
            text = between(text, '    let y = recent(app, ui, rect,', '\n}\n\n/// Recent projects', '    recent(app, ui, rect, 90.0 + 150.0 + 36.0);')
        elif relative == 'crates/ui-egui/src/panels/dialogs.rs':
            text = replace_exact(text, 'A clean-room, pure-Rust non-linear video editor. Part of the ArtCraft family.', 'A clean-room, pure-Rust non-linear video editor.')
            text = between(text, '    let mut link = |ui:', '    ui.label(egui::RichText::new(tl!("MIT OR Apache-2.0.')
        elif relative == 'crates/ui-egui/src/panels/keyboard.rs':
            text = drop_lines(text, r'uic!\("help.filmcraftHelp"')
            text = remove_block(text, '"help.filmcraftHelp" => {')
        elif relative == 'crates/ui-egui/tests/links_ui.rs':
            text = function(text, 'fn community_links_everywhere()', '''    let mut d = Driver::demo();
    let menu = d.ok("ui.menu.list", json!({})).to_string();
    for id in ["help.discord", "help.website", "help.appPage", "help.github", "help.reportIssue"] {
        assert!(!menu.contains(id), "retired promotion {id}");
        assert!(links::url_for(id).is_none());
    }
    assert!(d.ids("header.discord").is_empty());
    d.ok("engine.execute", json!({"command": "app.about", "params": {}}));
    d.frames(3);
    assert!(d.ids("about.discord").is_empty());
    d.ok("ui.key", json!({"key": "Escape"}));
    d.frames(3);
    assert!(d.ids("about.").is_empty(), "Escape closes About");
    d.ok("engine.execute", json!({"command": "mode.import", "params": {}}));
    d.frames(3);
    assert!(d.ids("import.link.").is_empty());''')
    elif app == 'light':
        retired = r'app\.(discord|website|github|artcraft|help|feedback)'
        if relative == 'crates/ui-egui/src/links.rs':
            text = between(text, 'pub const LINKS:', '\n/// Where feedback', 'pub const LINKS: &[(&str, &str, &str)] = &[];\n')
        elif relative == 'crates/ui-egui/src/menus.rs':
            text = drop_lines(text, r'^\s*\("' + retired + r'",')
            text = remove_block(text, '"app.discord" | "app.website" | "app.github" | "app.artcraft" | "app.help" | "app.feedback" => {')
        elif relative == 'crates/ui-egui/src/menubar.rs':
            text = drop_lines(text, r'^\s*"'+retired+r'",')
        elif relative == 'crates/ui-egui/src/panels/topbar.rs':
            text = drop_lines(text, r'^\s*\("discord", Icon::Chat,')
        elif relative == 'crates/ui-egui/src/panels/dialogs.rs':
            a = text.index('                            let discord = egui::Button::new(')
            b = text.index('\n                        }\n                    }', a)
            text = text[:a] + text[b:]
    elif app == 'pdf':
        if relative == 'crates/engine/src/links.rs':
            text = between(text, 'pub const LINKS:', '\npub fn for_command', 'pub const LINKS: &[Link] = &[];\n')
        elif relative == 'crates/engine/src/commands.rs':
            text = drop_lines(text, r'^\s*c\("help\.(discord|app_page|github|website)",')
        elif relative == 'crates/ui-egui/src/home.rs':
            a = text.index('            egui::Frame::NONE')
            b = text.index('            ui.add_space(22.0);', a)
            assert 'Visit the upstream ArtCraft community' in text[a:b]
            text = text[:a] + text[b:]
        elif relative == 'crates/ui-egui/src/chrome.rs':
            text = between(text, '                // Keep the two icon buttons, Discord', '                // Open stays in sight', '                let controls_width = 2.0 * button + 24.0 + window_controls::width(&controls.right);\n')
            text = remove_block(text, 'if widgets::ghost_button_sized(ui, "messages-square", "Discord", tab_h)')
        elif relative == 'crates/ui-egui/src/widgets.rs':
            text = function(text, 'pub fn community_links(', '    let _ = ui;\n    None')
            text = text.replace('.alt_text("ArtCraft")', '.alt_text("Bogo")')
        elif relative == 'apps/pdfcraft-cli/src/main.rs':
            text = replace_exact(text, '\nhelp and feedback: https://discord.gg/artcraft', '')
            text = drop_lines(text, r'stdout_line\(format_args!\("(Discord:|Web:|Source:)')
        elif relative == 'crates/ui-egui/tests/ui.rs':
            text = text.replace('let discord = h.get_by_label("Discord").rect();', 'let shortcuts = h.get_by_label("Keyboard shortcuts").rect();')
            text = text.replace('discord.left()', 'shortcuts.left()').replace('{discord:?}', '{shortcuts:?}')
            text = text.replace('h.get_by_label("Discord").rect().left()', 'h.get_by_label("Keyboard shortcuts").rect().left()')
            text = text.replace('"Open", "Discord", "Keyboard shortcuts"', '"Open", "Keyboard shortcuts"')
        elif relative == 'crates/ui-egui/tests/ui_group/links.rs':
            text = function(text, 'fn discord_button_in_the_top_bar_opens_discord()', '''    let h = harness(|_| {});
    assert!(h.query_by_label("Discord").is_none());
    assert!(h.state().last_opened_url.is_none());''')
            text = function(text, 'fn home_screen_links()', '''    let h = harness(|_| {});
    for label in ["Upstream Discord", "Visit the upstream ArtCraft community", "ArtCraft website"] {
        assert!(h.query_by_label(label).is_none(), "{label}");
    }
    assert!(h.state().last_opened_url.is_none());''')
            text = function(text, 'fn about_dialog_shows_the_brand_and_links()', '''    let h = harness(|app| app.dialog = Some(Dialog::About));
    assert!(h.query_all_by_label("Bogo").count() >= 1);
    assert!(h.query_by_label("Upstream Discord").is_none());
    assert!(h.state().last_opened_url.is_none());''')
            text = function(text, 'fn help_commands_open_each_link()', '''    assert!(links::LINKS.is_empty());
    for id in ["help.discord", "help.app_page", "help.github", "help.website"] {
        assert!(pdfcraft_engine::commands::command(id).is_none(), "{id}");
        assert!(links::for_command(id).is_none());
    }''')
    elif app == 'effect':
        if relative == 'crates/engine/src/commands/help.rs':
            text = '''//! Local tutorials remain available; retired project/community links are not commands.

use super::{CommandSpec, always};
use crate::cmd;

pub fn specs() -> Vec<CommandSpec> {
    vec![cmd!("help.inAppTutorials", "In-App Tutorials...", ["Help"], None, "{} → the Home screen's Learn tab", always, |s, p| super::frontend(
        s,
        "help.inAppTutorials",
        p
    ))]
}
'''
        elif relative == 'crates/engine/src/menus.rs':
            text=drop_lines(text,r'\| help\.(docs|onlineTutorials|discord|reportIssue|website|appPage|github)(?: |$)')
        elif relative == 'crates/engine/src/tests.rs':
            text=function(text,'fn help_links_emit_urls()', '''    let mut s = Session::default();
    for id in ["help.discord", "help.github", "help.website", "help.appPage", "help.reportIssue", "help.sibling", "help.docs", "help.onlineTutorials"] {
        assert!(s.execute(id, json!({})).is_err(), "{id}");
    }
    assert!(!s.drain_events().iter().any(|event| matches!(event, crate::Event::OpenUrl(_))));''')
        elif relative == 'crates/engine/src/tests_m137.rs':
            text=replace_exact(text,'    s.execute("help.onlineTutorials", json!({})).unwrap();','    assert!(s.execute("help.onlineTutorials", json!({})).is_err());')
            text=replace_exact(text,'    assert!(ev.iter().any(|e| matches!(e, Event::OpenUrl(u) if u == crate::links::APP_PAGE)));','    assert!(!ev.iter().any(|e| matches!(e, Event::OpenUrl(_))));')
        elif relative == 'crates/ui-egui/src/header.rs':
            text = between(text, '    // The pill fits its label', '    // Appearance: Sync with System,')
        elif relative == 'crates/ui-egui/src/panels/home.rs':
            text = between(text, '    // Community links at the foot', '\n}\n\n/// The Home page:')
            text = drop_lines(text,r'^\s*"home.help.(discord|github)",$')
        elif relative == 'crates/ui-egui/src/panels/dialogs.rs':
            text = drop_lines(text, r'ui.label\(tr\("Independent Bogo fork of EffectCraft')
            text = between(text, '    let links: [(Icon, &str, &str,', '\n}\n\nfn comp_settings')
        elif relative == 'crates/ui-egui/tests/ui_panels.rs':
            text = function(text, 'fn discord_pill_fits_its_label()', '''    let h = harness();
    for id in ["header.discord", "header.github", "header.web"] {
        assert!(h.state().auto.find(id).is_none(), "{id}");
    }''')
    elif app == 'deck':
        if relative == 'crates/ui-egui/src/backstage.rs':
            text = drop_lines(text, r'ui.hyperlink_to\("(Upstream DeckCraft community|Join our community on Discord|Source on GitHub)"')
        elif relative == 'crates/ui-egui/src/lib.rs':
            text = remove_block(text, '"app.links" => {')
            text = drop_lines(text,r'^\s*\("app.links", "Community Links",')
        elif relative == 'apps/deckcraft-cli/src/main.rs':
            text = between(text, '        Some("links") => {', '        _ => {')
            text = drop_lines(text, r'eprintln!\("\\nCommunity:')
            text = text.replace('deckcraft-cli links | --version', 'deckcraft-cli --version')
    elif app == 'word':
      if relative == 'crates/ui-egui/src/backstage.rs':
        text = replace_exact(text, '[("About", "about"), ("Discord community", "discord")]', '[("About", "about")]')
        text = replace_exact(text, '''                        if id == "discord" {
                            let _ = app.run("ui.discord", json!({}));
                        } else {
                            app.dialog = crate::dialogs::Dialog::open("about", app);
                        }''', '''                        let _ = id;
                        app.dialog = crate::dialogs::Dialog::open("about", app);''')
      elif relative == 'crates/ui-egui/src/dialogs.rs':
        text=drop_lines(text,r'ui.hyperlink_to\(tl!\("Source code: github.com/storytold/wordcraft"')
      elif relative == 'crates/engine/src/sample.rs':
        text=replace_exact(text,'https://getartcraft.com/','https://example.com/')
    if app in ('word','deck')and relative=='crates/mcp/src/server.rs':
        name='WordCraft'if app=='word'else'DeckCraft'
        text=text.replace('const INSTRUCTIONS: &str = "'+name,'const INSTRUCTIONS: &str = "Bogo '+('Word'if app=='word'else'Deck'))
        text=re.sub(r'"title": "'+name+r'", "version": env!\("CARGO_PKG_VERSION"\), "websiteUrl": [^\n}]+', '"title": "Bogo '+('Word'if app=='word'else'Deck')+'", "version": env!("CARGO_PKG_VERSION")',text)
        if app=='word':
            text=replace_exact(text,'{INSTRUCTIONS} Backend: {}. Community: https://discord.gg/artcraft · https://getartcraft.com/apps/wordcraft · https://github.com/storytold/wordcraft','{INSTRUCTIONS} Backend: {}.')
        else:
            text=replace_exact(text,'''                        "{INSTRUCTIONS} Backend: {}. Community: {} (Discord), {} (app page), {} (source). The `app.links` command returns these links.",
                        self.backend.describe(),
                        deckcraft_engine::links::DISCORD,
                        deckcraft_engine::links::APP_PAGE,
                        deckcraft_engine::links::GITHUB
''','''                        "{INSTRUCTIONS} Backend: {}.",
                        self.backend.describe()
''')
    if app == 'launcher':
        if relative == 'apps/artcraft-launcher/src/main.rs':
            text=replace_exact(text,'println!("artcraft-launcher {}", env!("CARGO_PKG_VERSION"));','println!("Bogo Launcher {}", env!("ARTCRAFT_LAUNCHER_VERSION"));')
        elif relative == 'crates/ui-egui/src/views.rs':
            text = remove_block(text, 'if widgets::nav_link(ui, tl!("Discord"),')
            a = text.index('        use artcraft_launcher_core::catalog::{DISCORD_URL, GITHUB_URL, SOCIAL, WEBSITE_URL};')
            b = text.index('        let platform_w =', a)
            text = text[:a] + '        let spacing = ui.spacing().item_spacing.x;\n        let links_w = 0.0;\n        let icons_w = 0.0;\n' + text[b:]
            a = text.index('            // Right to left, so this reads: Website')
            b = text.index('            ui.with_layout(egui::Layout::left_to_right', a)
            text = text[:a] + text[b:]
        elif relative == 'crates/ui-egui/src/dialogs.rs':
            text = between(text, '        section(ui, tl!("Community"));', '        section(ui, tl!("Appearance"));')
        elif relative == 'apps/artcraft-launcher/src/tray.rs':
            text = drop_lines(text, r'use artcraft_launcher_core::catalog::\{DISCORD_URL|let (website|github|discord) = MenuItem|\((website|github|discord), "')
            text = replace_exact(text, '&show, &check, &PredefinedMenuItem::separator(), &website, &github, &discord, &PredefinedMenuItem::separator(), &quit', '&show, &check, &PredefinedMenuItem::separator(), &quit')
            text = replace_exact(text, 'let links = [(website.id().clone(), WEBSITE_URL), (github.id().clone(), GITHUB_URL), (discord.id().clone(), DISCORD_URL)];', 'let links: [(MenuId, &\'static str); 0] = [];')
        elif relative == 'crates/core/src/protocol.rs':
            text = text.replace('=> "ArtCraft API"', '=> "Bogo catalog"').replace('=> "ArtCraft"', '=> "Bogo"')
        elif relative == 'crates/core/src/catalog.rs':
            a=text.index('pub const SOCIAL:');b=text.index('];',a)+2
            social=text[a:b]
            if social.count('https://')!=5:raise ValueError('Unreviewed Launcher social registry')
            text=text[:a]+text[b:]
            text=remove_line(text,'pub const DISCORD_URL: &str = "https://discord.gg/artcraft";')
        elif relative == 'crates/ui-egui/src/widgets.rs':
            text=remove_block(text,'pub fn social_icons(')
        elif relative.startswith(('crates/native/', 'crates/ui-egui/', 'apps/')) and relative.endswith('.rs'):
            # Human-readable source/feed labels, not serialized enum discriminants, keys or paths.
            text = text.replace('"ArtCraft API"', '"Bogo catalog"')
    return text


PROTECTED_PATHS = {
    ('cad', 'crates/engine/src/sample.rs'),
    ('pdf', 'crates/engine/src/links.rs'),
    ('pdf', 'crates/engine/src/commands.rs'),
    ('effect', 'crates/engine/src/commands/help.rs'),
    ('effect', 'crates/engine/src/menus.rs'),
    ('effect', 'crates/engine/src/tests.rs'),
    ('effect', 'crates/engine/src/tests_m137.rs'),
    ('word', 'crates/engine/src/sample.rs'),
    ('film','crates/engine/src/demo.rs'),
    ('film','crates/project/src/gtemplate.rs'),
    ('light','crates/engine/src/demo.rs'),
    ('effect','crates/engine/src/demo.rs'),
    ('effect','xtask/src/bench.rs'),
    ('deck','crates/engine/src/sample.rs'),
}
PROTECTED_BEFORE = {
    ('cad', 'crates/engine/src/sample.rs'): ('91c8538dc95fd03cd37a1f5cc135e2c3128991ef6a277e87f8934df62ab7d64d', 11918),
    ('deck', 'crates/engine/src/sample.rs'): ('b2d8e6e9bc4078839c8a84825b582fea63a002f1efe92d43d86a1140b5e32908', 7796),
    ('effect', 'crates/engine/src/commands/help.rs'): ('c5ff3919266f4ba7a6bdce09e7e23a5b2001808cfdf80a101a444ff9316b9c66', 2517),
    ('effect', 'crates/engine/src/demo.rs'): ('cc63ccafc559e4acee29d9be99bf54279f02d1a99301d4fb58e9836dfd84c2a1', 20779),
    ('effect', 'crates/engine/src/menus.rs'): ('668abf4c3986d1841a34d5471c11c178ae2c8665e8363312de92dfa26a28cfad', 53697),
    ('effect', 'crates/engine/src/tests.rs'): ('407dce18ac68a400438d1cd442a1bb3ffcf117c872c8de6e77e2f36acf3f1d7e', 38720),
    ('effect', 'crates/engine/src/tests_m137.rs'): ('d19041cc223e223562eb9de5ac92e4c01eaf915ace2875f6d011687443682b2e', 9193),
    ('effect', 'xtask/src/bench.rs'): ('2ddfe5238783585c32075c3ad72a2a4edbfe9cedc03b337e3af1aa9f7f820136', 44466),
    ('film', 'crates/engine/src/demo.rs'): ('80161af8c5e2a30920b61e7763adfd1f66fdb4cc92082768f0581b4cf783ef26', 9521),
    ('film', 'crates/project/src/gtemplate.rs'): ('a8d21eeb398760aa0b17783199ca092b0502eb1c2d96a667e4bd4198bb78cf9d', 32149),
    ('light', 'crates/engine/src/demo.rs'): ('b2c5377de97504647cf28fa90f418b29704679f52ac952d016b9f4b151252e85', 30742),
    ('pdf', 'crates/engine/src/commands.rs'): ('e99e9c0d201f66b3b1d2390c165b87eb4a9079f930d12a1ab680aba364b8d690', 28340),
    ('pdf', 'crates/engine/src/links.rs'): ('3e872d1cab6c6255dbbd496512009162f7faeecb41fcabe89b2fcbe18049b398', 36972),
    ('word', 'crates/engine/src/sample.rs'): ('73fce0485c70d7508facb488f5c9f281cb74fd19567f7392d8b530e40ca29f9f', 9948),
}
PROTECTED_AFTER = {
    ('cad', 'crates/engine/src/sample.rs'): ('eb7e5738e8bea8dbb6a0435919c9397f74a6c5b6943df49683c2518fc8fb9767', 11918),
    ('deck', 'crates/engine/src/sample.rs'): ('d4ae5df4cfda1cb55822ce7ef05d4895d3a77ff4effac9b0fd0291eebcc28ffe', 7796),
    ('effect', 'crates/engine/src/commands/help.rs'): ('c55553616c6f7363f0431a38b1c1e8267eb8a66081789c0459e77d4c8f2e3d4e', 385),
    ('effect', 'crates/engine/src/demo.rs'): ('0a94e22625d31b710d0a08d684b67e8667d03ddb2fb6e45a2e199566aab04c50', 20779),
    ('effect', 'crates/engine/src/menus.rs'): ('52d52ec0d8e5fd25827c5987195eae3de956416cccf0ab2c350b8321755e3c71', 53232),
    ('effect', 'crates/engine/src/tests.rs'): ('fcc15119f2eeb1512501c079dd009354ac51dff3f78aed7964654fa8458ab5b9', 38694),
    ('effect', 'crates/engine/src/tests_m137.rs'): ('cd16d30e2854975940ffc2245be4b3f0afee305672602eb2f4e8b57edd981802', 9172),
    ('effect', 'xtask/src/bench.rs'): ('6bba69d6aaa6d7bb9a147b47086d6d799e699aa1e4edf4cb8daaebcfdfd2784d', 44466),
    ('film', 'crates/engine/src/demo.rs'): ('2814172cbdc92d37f75311bde87cab351550620b10fbb8bfd285d99d9896ec34', 9521),
    ('film', 'crates/project/src/gtemplate.rs'): ('b32c3f9c1c7aa892e7ab3d7400f4bc867cb400e667f0bef35b68f1945f6e1d92', 32149),
    ('light', 'crates/engine/src/demo.rs'): ('5de5933b889f756c4bfb8e1637421c4edca06bd3d58fb3002f66b602a0d21576', 30742),
    ('pdf', 'crates/engine/src/commands.rs'): ('e715e8621f291d1f0aef5858c9333e58716ad3f4560e726991cc14cc6410018e', 28015),
    ('pdf', 'crates/engine/src/links.rs'): ('aef0b7a128c30b404dab05ff59b5ab4b678010312c97e800ee8a2ebc8998056d', 36562),
    ('word', 'crates/engine/src/sample.rs'): ('64619d78139361d588ce0c0db499c4dddbefa3403e8cf19695ea73f26d58cda6', 9944),
}


def identity(value):
    raw=value.encode('utf-8')if isinstance(value,str)else value
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def protected_transition_allowed(app,relative,before,after):
    key=(app,relative)
    if key not in PROTECTED_BEFORE:return False
    b,n=PROTECTED_BEFORE[key],PROTECTED_AFTER[key]
    return before=={'sha256':b[0],'bytes':b[1]}and after=={'sha256':n[0],'bytes':n[1]}


def protected_changes(source,app):
    rows=[]
    for selected,relative in sorted(PROTECTED_PATHS):
        if selected!=app:continue
        path=Path(source)/relative
        if path.is_symlink()or not path.is_file():raise ValueError('Linked or missing promotional registry')
        before=path.read_text(encoding='utf-8');after=app_text(app,relative,before)
        if not protected_transition_allowed(app,relative,identity(before),identity(after)):
            raise ValueError('Unreviewed protected promotion transition: '+relative)
        rows.append({'app':app,'path':relative,'before':identity(before),'after':identity(after),'scope':'retired UI promotion registry only; document/media operations remain unchanged'})
    return rows


def apply(source, app):
    """Apply reviewed source contracts after display/theme transforms, before QA/packaging."""
    source = Path(source)
    if source.is_symlink()or not source.is_dir():raise ValueError('Prepared source must be a regular directory')
    protected_changes(source,app)
    changed = [];planned={}
    for path in sorted(source.rglob('*')):
        if not path.is_file() or '.git' in path.parts:
            continue
        relative = path.relative_to(source).as_posix()
        allowed = relative.startswith(('apps/', 'crates/ui-egui/', 'crates/native/', 'crates/core/')) or (app, relative) in PROTECTED_PATHS or (app in ('word','deck')and relative=='crates/mcp/src/server.rs')
        if not allowed or path.suffix not in ('.rs', '.json', '.tsv'):
            continue
        if path.is_symlink()or any(parent.is_symlink()for parent in path.parents if parent==source or source in parent.parents):
            raise ValueError('Linked promotion source ancestry refused: '+relative)
        try:
            before = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        after = app_text(app, relative, before)
        if after != before:
            planned[path]=after
            changed.append(relative)
    for path,text in planned.items():path.write_text(text,encoding='utf-8',newline='')
    if app in ('design','vector','grid','photo'):
        changed.extend(apply_four(source, app))
    if app=='launcher':changed.extend(apply_launcher_tests(source))
    return sorted(set(changed))
