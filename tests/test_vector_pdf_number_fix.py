"""Authenticate the complete parser source and the narrow Vector PDF correction.

These guards inspect reviewed source inputs and mock the build command boundary;
the actual numeric/array behavior is tested by the native Rust integration suite.
No Cargo invocation, native build, network request or application launch occurs.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import full_native as native

FOLDER = ROOT / 'patches/vector'
MANIFEST = FOLDER / 'functional-hayro-number-token.json'
PATCH = FOLDER / 'functional-hayro-number-token.patch'
PREFIX = 'vendor/hayro-syntax/'
REGRESSION = 'crates/pdf/tests/hayro_number_tokens.rs'
INVENTORY_SHA = 'c54c281427542e5f74afca4c96141f33ea7ef16f98ead161fe4ff1d4431d78fb'
NUMBER_OUTSIDE_READER_SHA = 'e16741353a37c50384d79b31551e8afe837282bc9478e77effc2500a01faa5bb'
ORIGINAL_NUMBER_TESTS_SHA = 'dbd3afa9c6bf29b2c96395cb1357ae15f2cbf00ecf55f5d289acdf4acac302be'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(data):
    return {'sha256': sha(data), 'bytes': len(data)}


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def sections(text):
    result = {}
    for block in text.split('diff --git ')[1:]:
        header, _, body = block.partition('\n')
        old, new = header.split()
        if old[2:] != new[2:] or new[2:] in result:
            raise AssertionError('Unexpected rename or duplicate patch path')
        result[new[2:]] = body
    return result


def changed_lines(block, sign):
    return [line[1:] for line in block.splitlines()
            if line.startswith(sign) and not line.startswith(sign * 3)]


def new_file_bytes(block):
    """Recover full added text bytes, including the original final-newline state."""
    if 'new file mode 100644\n' not in block:
        raise AssertionError('Expected a new regular source file')
    chunks = []
    in_hunk = False
    for line in block.splitlines(keepends=True):
        if line.startswith('@@ '):
            if in_hunk or not re.match(r'@@ -0,0 \+1(?:,\d+)? @@', line):
                raise AssertionError('Added source is not one complete file')
            in_hunk = True
        elif in_hunk:
            if line.startswith('+'):
                chunks.append(line[1:])
            elif line.startswith('\\ No newline at end of file'):
                chunks[-1] = chunks[-1].removesuffix('\n')
            else:
                raise AssertionError('Unexpected omitted or removed added-file bytes')
    if not in_hunk:
        raise AssertionError('Missing full added source')
    return ''.join(chunks).encode('utf-8')


def mask_read_inner_body(text):
    """Hash unchanged surroundings without mirroring the implementation text."""
    start = re.search(r'^fn read_inner\b', text, re.M)
    if start is None:
        raise AssertionError('Missing Number reader')
    left = text.index('{', start.start())
    depth, right = 1, left + 1
    while depth and right < len(text):
        depth += (text[right] == '{') - (text[right] == '}')
        right += 1
    if depth:
        raise AssertionError('Incomplete Number reader')
    return text[:left] + '{ /* reviewed implementation */ }' + text[right:]


class VectorPdfNumberFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = json.loads(MANIFEST.read_text(encoding='utf-8'))
        cls.parts = sections(PATCH.read_text(encoding='utf-8'))
        cls.inventory = cls.meta['dependency']['originalInventory']
        cls.files = {row['path']: row for row in cls.meta['files']}
        cls.added = {path: new_file_bytes(block) for path, block in cls.parts.items()
                     if path not in ('Cargo.toml', 'Cargo.lock')}
        catalog = json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))
        cls.locks = {row['id']: row for row in catalog['applications']}

    def test_descriptor_and_catalog_authenticate_reviewed_source_bytes(self):
        meta, lock = self.meta, self.locks['vector']
        self.assertEqual(meta['schema'], 'kio.native-functional-patch.v1')
        self.assertEqual(meta['programId'], 'vector')
        self.assertEqual(meta['upstream']['commit'], '0a33cff3f6e2a1e9e672f4c3816f58cd8d3d032e')
        self.assertEqual(meta['upstream']['commit'], lock['source']['commit'])
        self.assertEqual(meta['base']['brandingPatchSha256'], lock['branding']['sha256'])
        self.assertEqual(meta['patch']['sha256'], sha(PATCH.read_bytes()))
        self.assertEqual(meta['patch']['bytes'], PATCH.stat().st_size)
        fixes = native.functional_fixes(lock)
        self.assertEqual(len(fixes), 1)
        fix, checked = fixes[0]
        self.assertEqual(checked, meta)
        self.assertEqual(fix['manifestSha256'], sha(MANIFEST.read_bytes()))

    def test_full_original_inventory_is_immutable_and_not_an_external_fixture(self):
        dependency = self.meta['dependency']
        self.assertNotIn('originalInventoryFile', dependency)
        self.assertEqual(len(self.inventory), 59)
        self.assertEqual(sum(row['bytes'] for row in self.inventory.values()), 519602)
        self.assertEqual(sha(canonical(self.inventory)), INVENTORY_SHA)
        self.assertEqual(dependency['originalInventorySha256'], INVENTORY_SHA)
        self.assertEqual(dependency['archiveSha256'], '6cdc818d8d265dcb42081d488f7599df4f73fb79e9d347ecedcd3c23809d2026')
        self.assertEqual(dependency['archiveBytes'], 114123)
        self.assertEqual(dependency['vcsCommit'], 'ea9c81dc70cde40c64205986fdcfcd481fe934d8')
        self.assertEqual(dependency['license'], 'Apache-2.0 OR MIT')

    def test_only_62_regular_paths_change_and_every_added_byte_is_authenticated(self):
        expected = {'Cargo.toml', 'Cargo.lock', REGRESSION} | {PREFIX + p for p in self.inventory}
        self.assertEqual(len(expected), 62)
        self.assertEqual(len(self.meta['files']), 62)
        self.assertEqual(set(self.files), expected)
        self.assertEqual(set(self.parts), expected)
        self.assertEqual(native.vector_functional_paths(self.meta), expected)
        for path, data in self.added.items():
            with self.subTest(path=path):
                self.assertIsNone(self.files[path]['before'])
                self.assertEqual(fingerprint(data), self.files[path]['after'])

    def test_58_original_files_including_features_licenses_and_array_are_identical(self):
        changed = []
        for relative, original in self.inventory.items():
            actual = fingerprint(self.added[PREFIX + relative])
            if actual != original:
                changed.append(relative)
        self.assertEqual(changed, ['src/object/number.rs'])
        vcs = json.loads(self.added[PREFIX + '.cargo_vcs_info.json'])
        self.assertEqual(vcs['git']['sha1'], self.meta['dependency']['vcsCommit'])
        self.assertEqual(vcs['path_in_vcs'], 'hayro-syntax')
        # The canonical inventory above includes the complete original Cargo
        # manifests/lock, licenses, features, decoder code and every other test.
        array = self.added[PREFIX + 'src/object/array.rs'].decode('utf-8')
        self.assertEqual(len(re.findall(r'#\[test\]', array)), 14)

    def test_number_skip_and_existing_tests_are_preserved_outside_reader_body(self):
        number = self.added[PREFIX + 'src/object/number.rs'].decode('utf-8')
        self.assertEqual(sha(mask_read_inner_body(number).encode()), NUMBER_OUTSIDE_READER_SHA)
        original_tests = number[number.index('#[cfg(test)]'):]
        self.assertEqual(sha(original_tests.encode()), ORIGINAL_NUMBER_TESTS_SHA)
        self.assertEqual(len(re.findall(r'#\[test\]', original_tests)), 29)

    def test_cargo_changes_only_exact_local_override_and_one_registry_identity(self):
        self.assertEqual(changed_lines(self.parts['Cargo.toml'], '-'), [])
        meaningful = [line.strip() for line in changed_lines(self.parts['Cargo.toml'], '+')
                      if line.strip() and not line.lstrip().startswith('#')]
        self.assertEqual(meaningful[0], '[patch.crates-io]')
        self.assertEqual(len(meaningful), 2)
        name, assignment = meaningful[1].split('=', 1)
        self.assertEqual(name.strip(), 'hayro-syntax')
        pairs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', assignment))
        self.assertEqual(pairs, {'path': 'vendor/hayro-syntax', 'version': '=0.8.0'})
        self.assertEqual(re.sub(r'\w+\s*=\s*"[^"]*"|[{},\s]', '', assignment), '')
        self.assertEqual(changed_lines(self.parts['Cargo.lock'], '+'), [])
        self.assertEqual(changed_lines(self.parts['Cargo.lock'], '-'), [
            'source = "registry+https://github.com/rust-lang/crates.io-index"',
            'checksum = "6cdc818d8d265dcb42081d488f7599df4f73fb79e9d347ecedcd3c23809d2026"'])
        self.assertIn('name = "hayro-syntax"', self.parts['Cargo.lock'])
        self.assertIn('version = "0.8.0"', self.parts['Cargo.lock'])

    def test_guard_refuses_rehashed_inventory_paths_or_unreviewed_original_changes(self):
        mutations = []
        item = copy.deepcopy(self.meta)
        item['dependency']['originalInventory']['README.md']['sha256'] = '0' * 64
        item['dependency']['originalInventorySha256'] = sha(canonical(item['dependency']['originalInventory']))
        mutations.append(item)
        item = copy.deepcopy(self.meta)
        item['files'].pop()
        mutations.append(item)
        item = copy.deepcopy(self.meta)
        item['files'].append({'path': 'crates/engine/src/lib.rs', 'before': None, 'after': {'sha256': '0' * 64, 'bytes': 1}})
        mutations.append(item)
        item = copy.deepcopy(self.meta)
        next(row for row in item['files'] if row['path'] == PREFIX + 'Cargo.toml')['after']['sha256'] = '0' * 64
        mutations.append(item)
        item = copy.deepcopy(self.meta)
        next(row for row in item['files'] if row['path'] == PREFIX + 'LICENSE-MIT')['before'] = {'sha256': '0' * 64, 'bytes': 1}
        mutations.append(item)
        for index, item in enumerate(mutations):
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                native.vector_functional_paths(item)

    def test_all_eight_native_regressions_are_present_without_ignores_or_panic_swallowing(self):
        text = self.added[REGRESSION].decode('utf-8')
        names = re.findall(r'#\[test\]\s*fn\s+(\w+)', text)
        self.assertEqual(len(names), 8)
        self.assertEqual(names, [name.rsplit('::', 1)[1] for name in self.meta['tests']['added']])
        self.assertNotRegex(text, r'#\[\s*(?:ignore|should_panic)\b|catch_unwind')
        self.assertIn('read_without_context::<Number>', text)
        self.assertIn('skip::<Number>', text)
        self.assertIn('raw_iter()', text)
        self.assertIn('read.offset()', text)

    def build_commands(self, app, platform, fail_regression=False):
        lock = self.locks[app]
        commands = []
        env = {'KIO_SYNTHETIC_TEST': '1'}
        work, source, fonts = [Path('/synthetic') / p for p in ('work', 'source', 'fonts')]
        def run(command, **kwargs):
            commands.append((command, kwargs))
            if '--test' in command and 'hayro_number_tokens' in command and fail_regression:
                raise RuntimeError('synthetic parser regression failure')
            return 'rustc 1.95.0 (synthetic)' if 'rustc' in command else ''
        writer = mock.Mock()
        binary = mock.Mock()
        binary.stat.return_value.st_size = 1
        with mock.patch.multiple(native, assert_host=mock.Mock(),
                                 prepared=mock.Mock(return_value=(work, source, fonts, {})),
                                 build_env=mock.Mock(return_value=env), run=run,
                                 binary_paths=mock.Mock(return_value={'app': binary, 'cli': binary}),
                                 digest=mock.Mock(return_value='0' * 64),
                                 check_versions=mock.Mock(return_value={}),
                                 check_cli_probe=mock.Mock(return_value={}), write_json=writer):
            if fail_regression:
                with self.assertRaisesRegex(RuntimeError, 'synthetic parser regression failure'):
                    native.build(SimpleNamespace(platform=platform), lock)
            else:
                native.build(SimpleNamespace(platform=platform), lock)
        return commands, writer, lock, source, env

    def test_native_hook_keeps_original_engine_suite_then_runs_real_parser_target_on_both_os(self):
        for platform, target in native.common.TARGETS.items():
            with self.subTest(platform=platform):
                calls, writer, lock, source, env = self.build_commands('vector', platform)
                cargo = ['rustup', 'run', '1.95.0', 'cargo']
                original = cargo + ['test', '--release', '--locked', '--target', target, '-p', 'vectorcraft-engine']
                regression = cargo + ['test', '--release', '--locked', '--target', target, '-p', 'vectorcraft-pdf', '--test', 'hayro_number_tokens']
                commands = [command for command, _ in calls]
                self.assertEqual(lock['testPackages'], ['vectorcraft-engine'])
                self.assertEqual(commands.count(original), 1)
                self.assertEqual(commands.count(regression), 1)
                self.assertLess(commands.index(original), commands.index(regression))
                self.assertIn(cargo + lock['cargoArgs'] + ['--target', target], commands)
                self.assertNotIn('--no-default-features', lock['cargoArgs'])
                self.assertIs(lock['features']['preserveDefaults'], True)
                for command, kwargs in calls:
                    if command in (original, regression):
                        self.assertEqual(kwargs['cwd'], source)
                        self.assertEqual(kwargs['env'], env)
                writer.assert_called_once()
                self.assertEqual(writer.call_args[0][1]['checks']['kioVectorPdfNumberRegressionTests'], 'passed')

    def test_failed_native_regression_cannot_produce_a_passed_build_record(self):
        _, writer, _, _, _ = self.build_commands('vector', 'windows-x64', fail_regression=True)
        writer.assert_not_called()

    def test_parser_hook_is_not_run_for_other_native_programs(self):
        calls, writer, _, _, _ = self.build_commands('grid', 'macos-arm64')
        self.assertFalse(any('hayro_number_tokens' in command for command, _ in calls))
        self.assertEqual(writer.call_args[0][1]['checks']['kioVectorPdfNumberRegressionTests'], 'not-applicable')


if __name__ == '__main__':
    unittest.main()
