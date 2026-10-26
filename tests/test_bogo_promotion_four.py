import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import bogo_brand as brand
import bogo_chrome_contrast as chrome
import bogo_native as bogo
import bogo_promotion_four as promo


def apply_text_hunks(original, patch_text, relative):
    """Apply authenticated legacy text hunks to task fixtures without invoking Git."""
    sections = re.split(r'(?m)^diff --git ', patch_text)
    sections = [section for section in sections[1:] if section.splitlines()[0] == 'a/' + relative + ' b/' + relative]
    if not sections:
        return original
    if len(sections) != 1 or 'GIT binary patch' in sections[0]:
        raise ValueError('Expected one ordinary Rust text patch')
    lines, out, cursor = original.splitlines(keepends=True), [], 0
    patch_lines = sections[0].splitlines(keepends=True)
    index = 0
    while index < len(patch_lines):
        match = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', patch_lines[index])
        if not match:
            index += 1; continue
        start = int(match[1]) - 1
        if start < cursor:
            raise ValueError('Overlapping source fixture hunks')
        out.extend(lines[cursor:start]); cursor = start; index += 1
        old_count, new_count = 0, 0
        while index < len(patch_lines) and not patch_lines[index].startswith('@@ '):
            line = patch_lines[index]
            if line.startswith('\\ No newline'):
                raise ValueError('Unexpected non-newline Rust fixture')
            if line.startswith((' ', '-')):
                if cursor >= len(lines) or lines[cursor] != line[1:]:
                    raise ValueError('Authenticated source fixture context differs')
                cursor += 1; old_count += 1
            if line.startswith((' ', '+')):
                out.append(line[1:]); new_count += 1
            index += 1
        if old_count != int(match[2] or 1) or new_count != int(match[4] or 1):
            raise ValueError('Source fixture hunk bounds differ')
    out.extend(lines[cursor:])
    return ''.join(out)


def authenticated_fixture(app):
    lock = bogo.base_lock(app)
    # Public source downloads are bounded and SHA-locked by the existing archive
    # verifier. No tests are skipped when the original cache is initially empty.
    archive = bogo.full.common.verified_archive(lock['source'], ROOT / '.cache/archives', False)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock['source']['sha256']:
        raise ValueError('Original public source archive differs')
    wanted = set(promo.PLANS[app]) | {relative for selected, relative in promo.PROTECTED_BEFORE if selected == app}
    preserved = ('LICENSE-MIT', 'LICENSE-APACHE', 'crates/engine/src/lib.rs', 'crates/ui-egui/src/credits.rs')
    with tarfile.open(archive) as tar:
        members = {member.name: member for member in tar.getmembers()}
        wanted |= {relative for relative in preserved if lock['source']['root'] + '/' + relative in members}
        original = {relative: tar.extractfile(members[lock['source']['root'] + '/' + relative]).read() for relative in wanted}
    contents = {relative: raw.decode('utf-8') for relative, raw in original.items()}
    for entry in [lock['branding'], *lock.get('functionalFixes', [])]:
        patch_path, manifest_path = ROOT / entry['patch'], ROOT / entry['manifest']
        if hashlib.sha256(patch_path.read_bytes()).hexdigest() != entry['sha256'] or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != entry['manifestSha256']:
            raise ValueError('Legacy source patch/manifest differs')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        declared = {row['path']: row for row in manifest['files']}
        for relative, text in list(contents.items()):
            changed = apply_text_hunks(text, patch_path.read_text(encoding='utf-8'), relative)
            if relative in declared:
                expected = declared[relative]['after']
                if expected is None or promo.identity(changed) != expected:
                    raise ValueError('Legacy fixture whole-file hash differs: ' + relative)
            elif changed != text:
                raise ValueError('Legacy fixture changed an undeclared file')
            contents[relative] = changed
    for relative, text in list(contents.items()):
        if relative.startswith(('apps/', 'crates/ui-egui/')) and relative.endswith('.rs'):
            text = brand.rust_display(text)
            if relative.startswith('crates/ui-egui/'):
                text = re.sub(r'\.color\((t|tokens)\.accent\)', lambda match: '.color(' + match[1] + '.text)', text)
                text = chrome.transform(app, relative, text)
        contents[relative] = text
    return original, contents


def write_fixture(root, contents):
    for relative, text in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='')


def function_text(text, name):
    match = re.search(r'(?m)^(?:pub(?:\([^\n]*\))?\s+)?fn\s+' + re.escape(name) + r'\b', text)
    if match is None:
        raise ValueError('Function fixture missing: ' + name)
    end = promo.brace_end(text, text.index('{', match.end()))
    return text[match.start():end]


class FourPromotionRemovals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = {app: authenticated_fixture(app) for app in promo.APPS}

    def test_all_four_authenticated_sources_remove_promotions_without_other_file_changes(self):
        for app, (original, contents) in self.fixtures.items():
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); write_fixture(root, contents)
                proof = promo.protected_changes(root, app)
                changed = promo.apply(root, app)
                expected = set(promo.PLANS[app]) | {relative for selected, relative in promo.PROTECTED_BEFORE if selected == app}
                self.assertEqual(set(changed), expected)
                for relative, before in contents.items():
                    after = (root / relative).read_text(encoding='utf-8')
                    if relative not in expected:
                        self.assertEqual(after, before, relative)
                    if Path(relative).name.startswith('LICENSE') or relative.endswith('/credits.rs'):
                        self.assertEqual(after.encode(), original[relative], relative)
                for row in proof:
                    after = promo.identity((root / row['path']).read_bytes())
                    self.assertTrue(promo.protected_transition_allowed(app, row['path'], row['before'], after))
                if app == 'design':
                    inspect = (root / 'crates/engine/src/cmd/inspect.rs').read_text(encoding='utf-8')
                    baseline = contents['crates/engine/src/cmd/inspect.rs']
                    self.assertEqual(inspect, baseline.replace(promo.DESIGN_QUERY, '', 1))
                    self.assertEqual(function_text(inspect, 'item_json'), function_text(baseline, 'item_json'))
                    server = (root / 'crates/mcp/src/server.rs').read_text(encoding='utf-8')
                    self.assertIn('"name": "designcraft"', server)
                    self.assertIn('"capabilities": {"tools": {}, "resources": {}}', server)
                    self.assertNotIn('designcraft_engine::links::', server)
                if app == 'grid':
                    self.assertIn('MIT OR Apache-2.0. Copyright (c) 2026 ArtCraft Team and the GridCraft contributors.', (root / 'crates/ui-egui/src/dialogs.rs').read_text(encoding='utf-8'))
                if app == 'photo':
                    after_links = (root / 'crates/ui-egui/src/links.rs').read_text(encoding='utf-8')
                    self.assertEqual(function_text(after_links, 'open'), function_text(contents['crates/ui-egui/src/links.rs'], 'open'))
                    for name in ('documents', 'document_area'):
                        self.assertEqual(function_text((root / 'crates/ui-egui/src/canvas.rs').read_text(encoding='utf-8'), name), function_text(contents['crates/ui-egui/src/canvas.rs'], name))

    def test_design_cli_removes_retired_arm_usage_and_restores_every_other_byte(self):
        relative = 'apps/designcraft-cli/src/main.rs'
        before = self.fixtures['design'][1][relative]
        after = promo.design_cli(before)
        self.assertNotIn('Some("links") =>', after)
        self.assertNotIn('designcraft-cli links', after)
        self.assertNotIn('designcraft_engine::links::', after)
        self.assertNotRegex(after, r'\b(?:DISCORD|WEBSITE|APP_PAGE|GITHUB|ISSUES)\b')
        for name in ('run', 'describe', 'script', 'app', 'mcp', 'validate_pdf', 'stdout_failed'):
            self.assertEqual(function_text(after, name), function_text(before, name), name)
        start = before.index('        Some("links") => {')
        end = promo.brace_end(before, before.index('{', start))
        arm = before[start:end] + '\n'
        footer = function_text(before, 'usage_footer')
        restored = after.replace(function_text(after, 'usage_footer'), footer, 1)
        help_comment = '        // Asking for help is not an error:'
        self.assertEqual(restored.count(help_comment), 1)
        restored = restored.replace(help_comment, arm + help_comment, 1)
        restored = restored.replace(r'\n       designcraft-cli --version', r'\n       designcraft-cli links\n       designcraft-cli --version', 1)
        doc = '//! designcraft-cli links                   # Discord, website, app page and GitHub links\n'
        restored = restored.replace('//! designcraft-cli --version', doc + '//! designcraft-cli --version', 1)
        self.assertEqual(restored, before)

    def test_engine_exceptions_are_exact_three_file_whole_byte_contracts(self):
        self.assertEqual(set(promo.PROTECTED_BEFORE), {('design', 'crates/engine/src/links.rs'), ('design', 'crates/engine/src/cmd/inspect.rs'), ('vector', 'crates/engine/src/cmd/help.rs')})
        for app, relative in promo.PROTECTED_BEFORE:
            original = self.fixtures[app][0][relative]
            self.assertEqual(promo.identity(original), dict(zip(('sha256', 'bytes'), promo.PROTECTED_BEFORE[app, relative])))
            transformed = promo.protected_transform(app, relative, original)
            self.assertEqual(promo.identity(transformed), dict(zip(('sha256', 'bytes'), promo.PROTECTED_AFTER[app, relative])))
            with self.assertRaisesRegex(ValueError, 'preimage changed'):
                promo.protected_transform(app, relative, original + b'\n')
            self.assertFalse(promo.protected_transition_allowed(app, relative, promo.identity(original), promo.identity(transformed + '\n')))
        self.assertFalse(promo.protected_transition_allowed('design', 'crates/engine/src/document.rs', {}, {}))
        with self.assertRaisesRegex(ValueError, 'exact file'):
            promo.protected_transform('photo', 'crates/engine/src/links.rs', b'')

    def test_unknown_or_duplicate_source_is_refused_atomically(self):
        for app, (_original, contents) in self.fixtures.items():
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                broken = copy.deepcopy(contents)
                first = next(iter(promo.PLANS[app])); broken[first] = ''
                root = Path(directory); write_fixture(root, broken)
                before = {relative: (root / relative).read_bytes() for relative in broken}
                with self.assertRaises(ValueError):
                    promo.apply(root, app)
                self.assertEqual({relative: (root / relative).read_bytes() for relative in broken}, before)
        for value in ('', 'x\nx\n'):
            with self.assertRaises(ValueError):
                promo.once(value, 'x\n')

    def test_live_ui_catalogs_headers_native_menus_and_dispatchers_have_no_retired_actions(self):
        for app, (_original, contents) in self.fixtures.items():
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); write_fixture(root, contents); promo.apply(root, app)
                menus = (root / 'crates/ui-egui/src/menus.rs').read_text(encoding='utf-8') if app != 'grid' else ''
                # Retired IDs may occur in negative cfg(test) assertions, but not
                # production command declarations, native menus or dispatch branches.
                for line in menus.splitlines():
                    self.assertNotRegex(line, r'^\s*(?:\("help\.(?:discord|website|appPage|app|github|issues|artcraftWebsite|reportIssue)"|c\("[^"\n]*", "help\.(?:discord|website|appPage|github)"|"ui:help\.(?:discord|website|appPage|github|issues)")')
                for relative in promo.PLANS[app]:
                    if relative.endswith(('/titlebar.rs', '/tests_nativemenu.rs', '/community.rs', '/links.rs')):
                        continue
                    after = (root / relative).read_text(encoding='utf-8')
                    self.assertNotIn('crate::links::discord_button(', after)
                    self.assertNotIn('crate::community::discord_button(', after)
                    self.assertNotIn('crate::community::links(', after)
                    self.assertNotIn('discord.gg/', after)
                    self.assertNotIn('getartcraft.com', after)

    def test_rust_brace_bounds_keep_comments_raw_strings_chars_and_lifetimes(self):
        text = r'''if enabled {
            let text = r##"{ raw } \" text"##;
            let brace = '}'; let escaped = '\'';
            // } ignored
            /* { outer /* } inner */ still } */
            let reference: &'static str = "{ escaped \\\" }";
            nested(|| { keep(); });
        }
        next();'''
        end = promo.brace_end(text, text.index('{'))
        self.assertEqual(text[end:].strip(), 'next();')
        self.assertEqual(promo.remove_block('    if enabled { call(); }\n    next();\n', 'if enabled'), '    next();\n')
        with self.assertRaises(ValueError):
            promo.brace_end('{ /* missing close', 0)


class VectorPromotionFormatterProof(unittest.TestCase):
    def test_project_formatting_only_normalizes_whitespace_and_one_optional_comma(self):
        formatted='        for id in ["help.discord", "help.website", "help.appPage", "help.github", "help.links"] {'
        previous='''        for id in [
            "help.discord",
            "help.website",
            "help.appPage",
            "help.github",
            "help.links",
        ] {'''
        self.assertEqual(promo.VECTOR_HELP.count(formatted),1)
        restored=promo.VECTOR_HELP.replace(formatted,previous)
        self.assertEqual(promo.identity(restored),{'sha256':'049b3f1d9c95ddbc0c08e7ed28395b7c67c36bec88cc5261d4170c5b1d77017f','bytes':609})
        self.assertEqual(promo.identity(promo.VECTOR_HELP),dict(zip(('sha256','bytes'),promo.PROTECTED_AFTER['vector','crates/engine/src/cmd/help.rs'])))


if __name__ == '__main__':
    unittest.main()
