import copy
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
sys.path.insert(0, str(ROOT / 'tests'))
import bogo_native as bogo
import bogo_brand as brand
import bogo_promotion_removal as promo
from test_bogo_promotion_four import apply_text_hunks

APPS = ('cad','film','light','pdf','effect','ui','word','sound','deck','launcher')
EXTRA = {'word': ('crates/mcp/src/server.rs',), 'deck': ('crates/mcp/src/server.rs',)}
# Exact input classes edited by the source transformer. Media/document engines
# outside the seven closed complete-file exceptions are never handed to it.
def selected(app, relative):
    return (relative.startswith(('apps/', 'crates/ui-egui/', 'crates/native/', 'crates/core/')) and relative.endswith(('.rs','.json','.tsv'))) or (app,relative) in promo.PROTECTED_PATHS or relative in EXTRA.get(app,())


def fixture(app):
    lock = bogo.base_lock(app)
    archive = bogo.full.common.verified_archive(lock['source'],ROOT/'.cache/archives',False)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=lock['source']['sha256']:
        raise ValueError('Original source SHA differs')
    with tarfile.open(archive) as tar:
        prefix=lock['source']['root']+'/'
        contents={member.name[len(prefix):]:tar.extractfile(member).read() for member in tar.getmembers() if member.isfile() and member.name.startswith(prefix) and (selected(app,member.name[len(prefix):]) or Path(member.name).name.startswith(('LICENSE','NOTICE')) or member.name[len(prefix):] in ('crates/engine/src/lib.rs','crates/engine/src/document.rs','crates/ui-egui/src/credits.rs'))}
    original=copy.deepcopy(contents)
    for entry in [lock['branding'],*lock.get('functionalFixes',[])]:
        patch_path,manifest_path=ROOT/entry['patch'],ROOT/entry['manifest']
        if hashlib.sha256(patch_path.read_bytes()).hexdigest()!=entry['sha256'] or hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=entry['manifestSha256']:
            raise ValueError('Legacy source patch differs')
        declared={row['path']:row for row in json.loads(manifest_path.read_text(encoding='utf-8'))['files']}
        patch_text=patch_path.read_text(encoding='utf-8')
        for relative,raw in list(contents.items()):
            try:text=raw.decode('utf-8')
            except UnicodeDecodeError:continue
            changed=apply_text_hunks(text,patch_text,relative)
            if relative in declared:
                if promo.identity(changed)!=declared[relative]['after']:raise ValueError('Legacy patch full-file identity differs: '+relative)
            elif changed!=text:raise ValueError('Unlisted legacy source mutation')
            contents[relative]=changed.encode()
    for relative,raw in list(contents.items()):
        if relative.startswith(('apps/','crates/ui-egui/','crates/native/','crates/core/')):
            text=raw.decode('utf-8')
            if relative.endswith('.rs'):
                text=brand.rust_display(text)
                if relative.startswith('crates/ui-egui/'):
                    text=re.sub(r'\.color\((t|tokens)\.accent\)',lambda m:'.color('+m[1]+('.ink)'if app=='launcher'else'.text)'),text)
            else:text=brand.display(text)
            contents[relative]=text.encode()
    return lock,original,contents


class PromotionRemoval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs={app:fixture(app) for app in APPS}

    def test_all_ten_authenticated_sources_remove_promotions_and_preserve_legal_and_documents(self):
        for app,(_,original,contents) in self.inputs.items():
            with self.subTest(app=app),tempfile.TemporaryDirectory() as folder:
                source=Path(folder)
                for relative,raw in contents.items():
                    path=source/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
                expected_protected=promo.protected_changes(source,app)
                changed=promo.apply(source,app)
                self.assertTrue(changed)
                for relative,before in contents.items():
                    after=(source/relative).read_bytes()
                    if relative not in changed:self.assertEqual(after,before,relative)
                    if Path(relative).name.startswith(('LICENSE','NOTICE')) or relative in ('crates/engine/src/lib.rs','crates/engine/src/document.rs','crates/ui-egui/src/credits.rs'):
                        self.assertEqual(after,before,(app,relative))
                    if relative.endswith('.rs'):
                        before_legal=[line for line in before.decode().splitlines()if promo.LEGAL.search(line)and ('ArtCraft'in line or 'copyright'in line.lower()or'©'in line)]
                        for line in before_legal:
                            if (app,relative)==('ui','crates/ui-egui/src/dialogs.rs'):
                                line=line.replace(' Made by the ArtCraft team and community.','')
                            self.assertIn(line,after.decode(),(app,relative,line))
                for row in expected_protected:
                    self.assertEqual(promo.identity((source/row['path']).read_bytes()),row['after'])
                if app=='word':
                    before=contents['crates/engine/src/sample.rs'];after=(source/'crates/engine/src/sample.rs').read_bytes()
                    self.assertEqual(after.replace(b'https://example.com/',b'https://getartcraft.com/'),before)
                    self.assertEqual(before.count(b'https://getartcraft.com/'),1)
                    lib=(source/'crates/ui-egui/src/lib.rs').read_text(encoding='utf-8')
                    self.assertIn('pub show_discord: bool',lib) # old serialized preferences survive
                    self.assertNotIn('"ui.discord" =>',lib)
                elif app=='pdf':
                    before=contents['crates/engine/src/links.rs'].decode();after=(source/'crates/engine/src/links.rs').read_text(encoding='utf-8')
                    tail='pub fn for_command'
                    self.assertEqual(before[before.index(tail):],after[after.index(tail):])
                    self.assertIn('pub const LINKS: &[Link] = &[];',after)
                elif app=='effect':
                    menus=(source/'crates/engine/src/menus.rs').read_text(encoding='utf-8')
                    self.assertNotIn('| help.discord',menus)
                    self.assertIn('| help.inAppTutorials',menus)
                    self.assertIn('| help.systemReport',menus)
                    original_tutorial=contents['crates/engine/src/tests_m137.rs'].decode()
                    updated_tutorial=(source/'crates/engine/src/tests_m137.rs').read_text(encoding='utf-8')
                    restored=updated_tutorial.replace('    assert!(s.execute("help.onlineTutorials", json!({})).is_err());','    s.execute("help.onlineTutorials", json!({})).unwrap();')
                    restored=restored.replace('    assert!(!ev.iter().any(|e| matches!(e, Event::OpenUrl(_))));','    assert!(ev.iter().any(|e| matches!(e, Event::OpenUrl(u) if u == crate::links::APP_PAGE)));')
                    self.assertEqual(restored,original_tutorial)
                elif app=='launcher':
                    main=(source/'apps/artcraft-launcher/src/main.rs').read_text(encoding='utf-8')
                    self.assertIn('println!("Bogo Launcher {}", env!("ARTCRAFT_LAUNCHER_VERSION"));',main)
                    self.assertNotIn('println!("artcraft-launcher {}"',main)
                    views=(source/'crates/ui-egui/src/views.rs').read_text(encoding='utf-8')
                    self.assertNotIn('tl!("Discord")',views)
                    self.assertNotIn('widgets::social_icons',views)
                    self.assertIn('app.website()',views) # current Bogo product links remain
                    self.assertIn('entry.app.repo_url()',views)
                    catalog=(source/'crates/core/src/catalog.rs').read_text(encoding='utf-8')
                    widgets=(source/'crates/ui-egui/src/widgets.rs').read_text(encoding='utf-8')
                    self.assertNotIn('pub const SOCIAL:',catalog)
                    self.assertNotIn('pub const DISCORD_URL:',catalog)
                    self.assertNotIn('pub fn social_icons(',widgets)
                    for relative in changed:
                        if relative.endswith('.rs'):
                            code='\n'.join(line for line in (source/relative).read_text(encoding='utf-8').splitlines()if not line.lstrip().startswith('//'))
                            self.assertNotRegex(code,r'\b(?:SOCIAL|DISCORD_URL)\b',relative)
                elif app=='film':
                    header=(source/'crates/ui-egui/src/header.rs').read_text(encoding='utf-8')
                    self.assertNotIn('header.discord',header)
                    self.assertIn('let right = wr.min.x - 12.0;',header)
                    self.assertIn('let popup_id =',header)

    def test_protected_guard_is_closed_to_seven_exact_whole_file_pairs(self):
        self.assertEqual(len(promo.PROTECTED_PATHS),7)
        for app,(_,_,contents) in self.inputs.items():
            for selected,relative in promo.PROTECTED_PATHS:
                if selected!=app:continue
                before=promo.identity(contents[relative]);after=promo.identity(promo.app_text(app,relative,contents[relative].decode()))
                self.assertTrue(promo.protected_transition_allowed(app,relative,before,after))
                self.assertFalse(promo.protected_transition_allowed(app,relative,{**before,'bytes':before['bytes']+1},after))
                self.assertFalse(promo.protected_transition_allowed(app,relative,before,{**after,'sha256':'0'*64}))
                self.assertFalse(promo.protected_transition_allowed(app,relative+'.other',before,after))
                self.assertFalse(promo.protected_transition_allowed(app,relative,{**before,'extra':True},after))

    def test_marker_parser_rejects_unknown_and_preserves_braces_in_strings_and_comments(self):
        text='if retired { let x = "}"; /* } /* { */ */ let y = r#"{"#; }\nfn retained() {}\n'
        self.assertEqual(promo.remove_block(text,'if retired {'),'fn retained() {}\n')
        for invalid in ('if other {}','if retired {\n','if retired {}\nif retired {}'):
            with self.assertRaises(ValueError):promo.remove_block(invalid,'if retired {')

    def test_localization_retains_legal_rows_and_never_rewrites_normal_documents(self):
        text='Join Discord\tDiscord community\nCopyright © ArtCraft Team\tCopyright © ArtCraft Team\nOpen\t열기\n'
        self.assertEqual(promo.localization('crates/ui-egui/src/i18n/ko.tsv',text),'Copyright © ArtCraft Team\tCopyright © ArtCraft Team\nOpen\t열기\n')
        self.assertEqual(promo.app_text('word','user/document.tsv',text),text)
        self.assertEqual(promo.app_text('word','crates/engine/src/edit.rs','https://getartcraft.com/'), 'https://getartcraft.com/')
        tuples='pub const TABLE: &[(&str,&str)] = &[\n    ("Join our Discord", "Discord に参加"),\n    ("Copyright © ArtCraft Team", "Copyright © ArtCraft Team"),\n    ("Open", "開く"),\n];\n'
        self.assertEqual(promo.localization('crates/ui-egui/src/i18n/ja.rs',tuples),tuples.replace('    ("Join our Discord", "Discord に参加"),\n',''))


class EffectPromotionFormatterProof(unittest.TestCase):
    def test_project_formatting_only_changes_whitespace_in_retained_tutorial_call(self):
        # The old sealed input identity is retained; this proof covers the entire
        # prior promotion output, independent of every other engine function.
        previous='''//! Local tutorials remain available; retired project/community links are not commands.

use super::{CommandSpec, always};
use crate::cmd;

pub fn specs() -> Vec<CommandSpec> {
    vec![cmd!("help.inAppTutorials", "In-App Tutorials...", ["Help"], None, "{} → the Home screen's Learn tab", always, |s, p| super::frontend(s, "help.inAppTutorials", p))]
}
'''
        raw=promo.PROTECTED_BEFORE['effect','crates/engine/src/commands/help.rs']
        self.assertEqual(raw,('c5ff3919266f4ba7a6bdce09e7e23a5b2001808cfdf80a101a444ff9316b9c66',2517))
        after=promo.app_text('effect','crates/engine/src/commands/help.rs','')
        formatted='''super::frontend(
        s,
        "help.inAppTutorials",
        p
    )'''
        self.assertEqual(after.count(formatted),1)
        restored=after.replace(formatted,'super::frontend(s, "help.inAppTutorials", p)')
        self.assertEqual(restored,previous)
        self.assertEqual(promo.identity(restored),{'sha256':'3a5b448163899b585cbb5b7fe9e4c9abaa900af86cb1c21c67d7f1ffd5451860','bytes':355})
        expected=promo.PROTECTED_AFTER['effect','crates/engine/src/commands/help.rs']
        self.assertEqual(promo.identity(after),{'sha256':expected[0],'bytes':expected[1]})


if __name__=='__main__':unittest.main()
