"""KIO plotter storage must use the original GUI's public dependency API.

These offline source-contract regressions replay the observed E0433 failure.
They apply the real branding patch and use byte-exact pinned upstream fixtures;
they do not compile or execute a native application.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/cad-plotter-api'
HELPER = 'apps/cadcraft/src/kio_plotters.rs'


def direct_dependencies(manifest):
    # The four byte-pinned original fixtures use simple unquoted dependency keys.
    section = re.search(r'^\[dependencies\]\n(.*?)(?=^\[|\Z)', manifest, re.M | re.S)
    if section is None:
        raise ValueError('Original direct GUI dependencies are missing')
    return {name.replace('-', '_') for name in re.findall(r'^([A-Za-z0-9_-]+)\s*=', section[1], re.M)}


def resolve_constant_references(helper, sources):
    dependencies = direct_dependencies(sources['apps/cadcraft/Cargo.toml'])
    references = re.findall(r'\b(cadcraft_\w+(?:::\w+)*::(?:PLOTTER_FILE_EXT|MAX_PLOTTER_FILE))\b', helper)
    if not references:
        raise ValueError('Plotter constants were removed')
    for reference in references:
        parts = reference.split('::')
        if parts[0] not in dependencies:
            raise ValueError('Constant uses an undeclared GUI dependency: ' + reference)
        if parts[0] == 'cadcraft_engine' and len(parts) == 3:
            alias = re.search(r'^pub use cadcraft_doc as (\w+);$', sources['crates/engine/src/lib.rs'], re.M)
            if alias is None or parts[1] != alias[1]:
                raise ValueError('Engine does not publicly export that document namespace')
            parts = ['cadcraft_doc', parts[-1]]
        if parts[0] != 'cadcraft_doc' or len(parts) != 2:
            raise ValueError('No original public document-constant export: ' + reference)
        if not re.search(r'^pub use plotter::\*;$', sources['crates/doc/src/lib.rs'], re.M):
            raise ValueError('Document crate no longer exports its plotter constants')
        if not re.search(r'^pub const ' + re.escape(parts[-1]) + r':', sources['crates/doc/src/plotter.rs'], re.M):
            raise ValueError('Original public plotter constant is missing')
    return references


class CadPlotterPublicApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog = json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))
        cls.lock = next(row for row in catalog['applications'] if row['id'] == 'cad')
        cls.proof = json.loads((FIXTURE / 'provenance.json').read_text(encoding='utf-8'))
        cls.sources = {record['path']: (FIXTURE / record['path']).read_text(encoding='utf-8') for record in cls.proof['files']}
        cls.branding = ROOT / cls.lock['branding']['patch']
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            command = ['git', 'apply', '--binary', '--include=' + HELPER, str(cls.branding)]
            subprocess.run(command[:2] + ['--check'] + command[2:], cwd=source, check=True, capture_output=True)
            subprocess.run(command, cwd=source, check=True, capture_output=True)
            cls.helper = (source / HELPER).read_text(encoding='utf-8')

    def test_original_fixture_bytes_are_bound_to_locked_archive_and_protected_source(self):
        self.assertEqual(self.proof['repository'], self.lock['source']['repository'])
        self.assertEqual(self.proof['commit'], 'fc4e98315a8d771b5ab832f0ade0b5e7b106df7f')
        self.assertEqual(self.proof['commit'], self.lock['source']['commit'])
        self.assertEqual(self.proof['sourceArchiveSha256'], self.lock['source']['sha256'])
        self.assertEqual(self.proof['sourceArchiveBytes'], self.lock['source']['bytes'])
        metadata = json.loads((ROOT / self.lock['branding']['manifest']).read_text(encoding='utf-8'))
        protected = {record['path']: record['sha256'] for record in metadata['protectedFiles']}
        self.assertEqual(len(self.proof['files']), 4)
        for record in self.proof['files']:
            with self.subTest(path=record['path']):
                data = (FIXTURE / record['path']).read_bytes()
                self.assertEqual(len(data), record['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
                if record['path'] == 'apps/cadcraft/Cargo.toml':
                    self.assertNotIn(record['path'], {item['path'] for item in metadata['files']})
                    self.assertTrue(metadata['checks']['everyCargoManifestAndLockByteIdentical'])
                else:
                    self.assertEqual(record['sha256'], protected[record['path']])
                self.assertEqual(record['member'], self.lock['source']['root'] + '/' + record['path'])
        self.assertEqual(hashlib.sha256(self.branding.read_bytes()).hexdigest(), self.lock['branding']['sha256'])
        entry = next(record for record in metadata['files'] if record['path'] == HELPER)
        self.assertIsNone(entry['before'])
        self.assertEqual(hashlib.sha256(self.helper.encode('utf-8')).hexdigest(), entry['after']['sha256'])

    def test_actual_helper_resolves_all_three_constants_through_unchanged_public_api(self):
        references = resolve_constant_references(self.helper, self.sources)
        self.assertEqual(len(references), 3)
        self.assertEqual({value.split('::')[-1] for value in references}, {'PLOTTER_FILE_EXT', 'MAX_PLOTTER_FILE'})
        self.assertIn('pub const PLOTTER_FILE_EXT: &str = ".plotter.json";', self.sources['crates/doc/src/plotter.rs'])
        self.assertIn('pub const MAX_PLOTTER_FILE: usize = 1 << 20;', self.sources['crates/doc/src/plotter.rs'])
        # Native GUI's Cargo manifest stays unchanged: no new dependency needed.
        dependencies = direct_dependencies(self.sources['apps/cadcraft/Cargo.toml'])
        self.assertNotIn('cadcraft_doc', dependencies)
        self.assertIn('cadcraft_engine', dependencies)

    def test_observed_windows_undeclared_crate_failure_is_rejected(self):
        old = self.helper.replace('cadcraft_engine::doc::', 'cadcraft_doc::')
        self.assertNotEqual(old, self.helper)
        with self.assertRaisesRegex(ValueError, 'undeclared GUI dependency'):
            resolve_constant_references(old, self.sources)

    def test_compiler_similar_name_suggestion_does_not_silently_pass(self):
        wrong = self.helper.replace('cadcraft_engine::doc::', 'cadcraft_io::')
        with self.assertRaisesRegex(ValueError, 'No original public'):
            resolve_constant_references(wrong, self.sources)

    def test_public_reexport_and_original_constant_are_required(self):
        for path, before, after in [
            ('crates/engine/src/lib.rs', 'pub use cadcraft_doc as doc;', 'use cadcraft_doc as doc;'),
            ('crates/doc/src/lib.rs', 'pub use plotter::*;', 'use plotter::*;'),
            ('crates/doc/src/plotter.rs', 'pub const MAX_PLOTTER_FILE:', 'const MAX_PLOTTER_FILE:'),
        ]:
            with self.subTest(path=path):
                mutated = {**self.sources, path: self.sources[path].replace(before, after)}
                self.assertNotEqual(mutated[path], self.sources[path])
                with self.assertRaises(ValueError):
                    resolve_constant_references(self.helper, mutated)


if __name__ == '__main__':
    unittest.main()
