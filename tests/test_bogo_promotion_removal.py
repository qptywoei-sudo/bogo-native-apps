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
# outside the fourteen closed complete-file exceptions are never handed to it.
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
                    restored=after.replace(b'https://example.com/',b'https://getartcraft.com/').replace(b'd.core.creator = "Bogo Word".into();',b'd.core.creator = "WordCraft".into();')
                    self.assertEqual(restored,before)
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

    def test_protected_guard_is_closed_to_fourteen_exact_whole_file_pairs(self):
        self.assertEqual(len(promo.PROTECTED_PATHS),14)
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


class LauncherFunctionalTsvPreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contents=fixture('launcher')[2]

    def test_hungarian_update_instruction_retains_three_fields_and_removes_only_promotions(self):
        relative='crates/ui-egui/src/i18n/hu.tsv'
        update='\tOpen Bogo Launcher to update.\tNyisd meg az ArtCraft Launchert a frissítéshez.\n'
        quit_row='\tQuit Bogo Launcher\tKilépés az ArtCraft Launcherből\n'
        legal='\tCopyright © ArtCraft Team\tCopyright © ArtCraft Team\n'
        other='\t{name} {v} is available\tElérhető: {name} {v}\n'
        promotion='\tJoin the ArtCraft Discord\tCsatlakozz az ArtCraft Discordhoz\n'
        before=update+quit_row+legal+other+promotion
        after=promo.localization(relative,before)
        self.assertEqual(after, update.replace('az ArtCraft Launchert','a Bogo Launchert')+quit_row.replace('az ArtCraft Launcherből','a Bogo Launcherből')+legal+other)
        rows=[row.split('\t')for row in after.splitlines()]
        self.assertTrue(all(len(row)==3 for row in rows))
        self.assertEqual(rows[0],['','Open Bogo Launcher to update.','Nyisd meg a Bogo Launchert a frissítéshez.'])
        self.assertEqual(promo.localization('user/document.tsv',before),before)
        # The reviewed exception cannot turn unrelated retired-brand rows into visible UI.
        self.assertEqual(promo.localization(relative,'\tUnreviewed ArtCraft action\tArtCraft Launchert\n'),'')

    def test_authenticated_launcher_catalog_keeps_update_key_and_grammatical_translation(self):
        contents=self.contents
        relative='crates/ui-egui/src/i18n/hu.tsv'
        before=contents[relative].decode('utf-8')
        key='Open Bogo Launcher to update.'
        before_rows=[line.split('\t')for line in before.splitlines()if line.startswith('\t'+key+'\t')]
        self.assertEqual(before_rows,[['',key,'Nyisd meg az ArtCraft Launchert a frissítéshez.']])
        after=promo.localization(relative,before)
        after_rows=[line.split('\t')for line in after.splitlines()if line.startswith('\t'+key+'\t')]
        self.assertEqual(after_rows,[['',key,'Nyisd meg a Bogo Launchert a frissítéshez.']])
        self.assertIn('tl!("'+key+'")',contents['crates/ui-egui/src/app.rs'].decode('utf-8'))
        self.assertIn('fn complete_catalogs_cover_every_ui_literal()',contents['crates/ui-egui/src/i18n/tests.rs'].decode('utf-8'))
        for line in after.splitlines():
            if line and not line.startswith('#'):
                self.assertEqual(len(line.split('\t')),3,line)
                self.assertFalse(promo.PROMOTION.search(line),line)
                self.assertTrue('ArtCraft'not in line or promo.LEGAL.search(line),line)

    def test_all_authenticated_launcher_tsv_functional_rows_survive_the_promotion_filter(self):
        catalogs={path:raw.decode('utf-8')for path,raw in self.contents.items()if path.endswith('.tsv')}
        self.assertEqual({Path(path).name for path in catalogs}, {'cs.tsv','de.tsv','es.tsv','fr.tsv','hu.tsv','ja.tsv','pl.tsv','pt-BR.tsv','ru.tsv','zh-CN.tsv'})
        retired_labels={'ArtCraft','ArtCraft on {name}','ArtCraft on GitHub'}
        changed_functional_rows=0
        for relative,before in catalogs.items():
            after=promo.localization(relative,before)
            for row in before.splitlines():
                if not row or row.startswith('#')or row in after.splitlines():continue
                fields=row.split('\t')
                self.assertEqual(len(fields),3,(relative,row))
                if promo.PROMOTION.search(row)or fields[1]in retired_labels:continue
                expected=row.replace('Kilépés az ArtCraft Launcherből','Kilépés a Bogo Launcherből')
                if relative=='crates/ui-egui/src/i18n/hu.tsv':
                    expected=expected.replace('Nyisd meg az ArtCraft Launchert a frissítéshez.','Nyisd meg a Bogo Launchert a frissítéshez.')
                self.assertNotEqual(expected,row,(relative,row))
                self.assertIn(expected,after.splitlines(),(relative,row))
                changed_functional_rows+=1
        self.assertEqual(changed_functional_rows,3) # plain + command-id Quit, and update instruction


class LightFunctionalRetryBrandProof(unittest.TestCase):
    BASELINES = {
        'de': ('2b0d8dedfedd3552c715ec94cd25d88e98731dd242a6a6c898afcb52d50f6a19',21141),
        'es': ('1d44078a4dda6a56ebf198b441cbd5e6094b1ada7b7e6703be4c91f6e751233f',20975),
        'fr': ('3a4f44712ee13210b7438e5ea773403e08d020f8232a9b9763362b24ed3ae14c',21689),
        'ja': ('ce84a505251427ed2cd076e9bbca7bcbdd776d035579418e947cdde2168d3253',23028),
        'pt-br': ('8925c7b42a535270df947c30c4b23ee3c5523bf3bfd30150e42b80936131405e',21039),
        'ru': ('392e4b76c0a7fdc25c0bfd9fd8e08ac4a50c211774098a60a1e1625077d12571',25574),
        'uk': ('485457abf21176a87a5d1d2229f6231d7996defcfbd64015cf88c19dd8f1e1d2',25774),
        'zh-hans': ('b7f9265457eec6ba038133479fdd72200a74cbd71b7f0766e7f9bc4db61d87e7',20530),
        'zh-hant': ('6c2967596a333ae7f49290312d4dd6a908da47c8215df81e5e9c9ae1545a0ea9',20393),
    }

    @classmethod
    def setUpClass(cls):
        cls.contents=fixture('light')[2]

    def test_nine_authenticated_locale_rows_change_only_brand_and_preserve_every_other_byte(self):
        old=promo.LIGHT_RETRY_KEY;new=old.replace('LightCraft','Bogo Light')
        self.assertEqual(len(self.BASELINES),9)
        self.assertEqual(set(promo.LIGHT_RETRY_FORMATS),{f'crates/ui-egui/locales/{locale}-formats.json'for locale in self.BASELINES})
        changed_translations=0
        for locale,(sha,size)in self.BASELINES.items():
            relative=f'crates/ui-egui/locales/{locale}-formats.json'
            before=self.contents[relative].decode('utf-8')
            self.assertEqual(promo.identity(before),{'sha256':sha,'bytes':size})
            after=promo.light_retry_brand(relative,before)
            changes=[(a,b)for a,b in zip(before.splitlines(keepends=True),after.splitlines(keepends=True))if a!=b]
            self.assertEqual(len(changes),1,locale)
            self.assertEqual(after.replace(changes[0][1],changes[0][0],1),before)
            previous=json.loads(before);current=json.loads(after)
            old_value=previous.pop(old);new_value=current.pop(new)
            self.assertEqual(previous,current)
            self.assertEqual(new_value,old_value.replace('LightCraft','Bogo Light'))
            self.assertEqual(re.findall(r'\{[^{}]*\}',new_value),re.findall(r'\{[^{}]*\}',old_value))
            changed_translations+=new_value!=old_value
            full=json.loads(promo.app_text('light',relative,before))
            self.assertIn(new,full)
            self.assertNotIn(old,full)
        self.assertEqual(changed_translations,7)

    def test_rust_required_key_matches_every_locale_and_warning_arguments_are_unchanged(self):
        relative='crates/ui-egui/src/panels/topbar.rs';before=self.contents[relative].decode('utf-8')
        self.assertEqual(promo.identity(before),{'sha256':'5ec1302b0bab5a4f82db213efffd52177bdcf77706f95fa78f0415ae80d84c97','bytes':12678})
        old=json.dumps(promo.LIGHT_RETRY_KEY,ensure_ascii=False);new=old.replace('LightCraft','Bogo Light')
        after=promo.light_retry_brand(relative,before)
        self.assertEqual(before.count(old),1)
        self.assertEqual(after.count(new),1)
        self.assertEqual(after.replace(new,old),before)
        self.assertIn(new,promo.app_text('light',relative,before))
        self.assertNotIn(old,promo.app_text('light',relative,before))
        for path in promo.LIGHT_RETRY_FORMATS:
            self.assertIn(json.loads(new),json.loads(promo.light_retry_brand(path,self.contents[path].decode('utf-8'))))

    def test_unknown_rows_locales_and_user_error_data_cannot_be_rewritten(self):
        relative='crates/ui-egui/locales/de-formats.json';before=self.contents[relative].decode('utf-8')
        for changed in (before.replace('LightCraft retries automatically','Different retries automatically'),
                        before.replace('LightCraft versucht','Unexpected versucht')):
            with self.assertRaises(ValueError):promo.light_retry_brand(relative,changed)
        self.assertEqual(promo.light_retry_brand('user/errors.json',before),before)
        self.assertEqual(promo.light_retry_brand('crates/ui-egui/locales/unreviewed-formats.json',before),before)
        self.assertEqual(promo.app_text('word','user/errors.json',before),before)


class BuiltinSampleBrandBatchProof(unittest.TestCase):
    BASELINES = {
        ('deck','crates/engine/src/sample.rs'): ('b2d8e6e9bc4078839c8a84825b582fea63a002f1efe92d43d86a1140b5e32908',7796),
        ('effect','crates/engine/src/demo.rs'): ('cc63ccafc559e4acee29d9be99bf54279f02d1a99301d4fb58e9836dfd84c2a1',20779),
        ('effect','crates/engine/src/tests.rs'): ('861b6a9ce063871b3496e87f664d12d8f27291e3ef7c63324db8f3f9079fcbcf',38694),
        ('effect','crates/ui-egui/tests/ui_agent_audit.rs'): ('5ea3e7a1ca533cfab10f4210d1c885d6a7b312cf34ee80c10dbe7df5c1fffb54',7634),
        ('effect','xtask/src/bench.rs'): ('2ddfe5238783585c32075c3ad72a2a4edbfe9cedc03b337e3af1aa9f7f820136',44466),
        ('film','crates/engine/src/demo.rs'): ('80161af8c5e2a30920b61e7763adfd1f66fdb4cc92082768f0581b4cf783ef26',9521),
        ('film','crates/project/src/gtemplate.rs'): ('a8d21eeb398760aa0b17783199ca092b0502eb1c2d96a667e4bd4198bb78cf9d',32149),
        ('light','crates/engine/src/demo.rs'): ('b2c5377de97504647cf28fa90f418b29704679f52ac952d016b9f4b151252e85',30742),
        ('word','crates/engine/src/sample.rs'): ('d56afdb642465682f693f36c930283cd2ae19b851754b85213b1caf1b5ce4290',9944),
    }

    @classmethod
    def setUpClass(cls):
        cls.inputs={app:fixture(app)[2]for app in ('deck','effect','film','light','word')}

    def test_exact_public_sample_literals_restore_every_other_original_output_byte(self):
        self.assertEqual(set(self.BASELINES),set(promo.SAMPLE_LITERAL_REPLACEMENTS))
        for (app,relative),baseline in self.BASELINES.items():
            with self.subTest(app=app,path=relative):
                before=self.inputs[app][relative].decode('utf-8')
                after=promo.app_text(app,relative,before)
                restored=after
                for old,new,count in reversed(promo.SAMPLE_LITERAL_REPLACEMENTS[app,relative]):
                    self.assertEqual(restored.count(new),count)
                    restored=restored.replace(new,old)
                self.assertEqual(promo.identity(restored),{'sha256':baseline[0],'bytes':baseline[1]})
                if (app,relative)in promo.PROTECTED_PATHS:
                    self.assertTrue(promo.protected_transition_allowed(app,relative,promo.identity(before),promo.identity(after)))
                if app=='deck':self.assertIn('json!({"theme": "DeckCraft"})',after)
                if relative.endswith('gtemplate.rs'):
                    self.assertIn('author: "FilmCraft contributors".into(),',after)
                    for name in ('Jordan Lee','Priya Natarajan','Marco Bianchi','Hana Kobayashi'):
                        self.assertIn(name,after)

    def test_collateral_or_unknown_sample_and_benchmark_bytes_are_refused(self):
        for app,relative in self.BASELINES:
            if (app,relative)not in promo.PROTECTED_PATHS:continue
            before=self.inputs[app][relative].decode('utf-8');after=promo.app_text(app,relative,before)
            self.assertFalse(promo.protected_transition_allowed(app,relative,promo.identity(before+'\n'),promo.identity(after)))
            self.assertFalse(promo.protected_transition_allowed(app,relative,promo.identity(before),promo.identity(after+'\n')))
            self.assertFalse(promo.protected_transition_allowed(app,relative+'.unreviewed',promo.identity(before),promo.identity(after)))


class CadBuiltinSampleBrandProof(unittest.TestCase):
    def test_exact_label_transition_preserves_whole_drawing_and_rejects_collateral_changes(self):
        relative='crates/engine/src/sample.rs'
        before=fixture('cad')[2][relative].decode('utf-8')
        after=promo.app_text('cad',relative,before)
        self.assertEqual(before.count('CADCRAFT SAMPLE'),1)
        self.assertEqual(after.count('Bogo CAD SAMPLE'),1)
        self.assertEqual(after.replace('Bogo CAD SAMPLE','CADCRAFT SAMPLE'),before)
        self.assertEqual(len(before.encode()),len(after.encode()))
        self.assertIn('DWG NO. CC-0001',after)
        self.assertTrue(promo.protected_transition_allowed('cad',relative,promo.identity(before),promo.identity(after)))
        for invalid in (before+'\n',before.replace('CC-0001','CC-9000'),before.replace('MOUNTING BRACKET','MOUNTING BRACKETS')):
            with self.subTest(sha=promo.identity(invalid)['sha256']),tempfile.TemporaryDirectory()as folder:
                root=Path(folder);path=root/relative;path.parent.mkdir(parents=True);path.write_text(invalid,encoding='utf-8',newline='')
                with self.assertRaisesRegex(ValueError,'Unreviewed protected promotion transition'):
                    promo.apply(root,'cad')
                self.assertEqual(path.read_text(encoding='utf-8'),invalid)
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);path=root/relative;path.parent.mkdir(parents=True);path.write_text(before,encoding='utf-8',newline='')
            self.assertEqual(promo.apply(root,'cad'),[relative])
            self.assertEqual(path.read_text(encoding='utf-8'),after)


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
