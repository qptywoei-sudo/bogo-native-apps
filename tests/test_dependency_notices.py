"""Regression coverage for legal material present in full native dependencies."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('notice_builder', Path(__file__).resolve().parents[1] / 'scripts/kio_native.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DependencyNotices(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'workspace'
        self.source.mkdir()
        self.cargo = self.root / 'cargo'
        self.folder = self.cargo / 'registry/src/synthetic-1.0.0'
        self.folder.mkdir(parents=True)
        (self.folder / 'Cargo.toml').write_text('[package]\nname="synthetic"\nversion="1.0.0"\n')
        self.package = {'name': 'synthetic', 'version': '1.0.0', 'manifest_path': str(self.folder / 'Cargo.toml'),
                        'source': 'registry+https://github.com/rust-lang/crates.io-index',
                        'repository': 'https://codeberg.org/example/synthetic', 'license': 'MIT OR Apache-2.0'}
        self.output = self.root / 'notices'
        builder._UPSTREAM_NOTICE_CACHE.clear()

    def tearDown(self):
        builder._UPSTREAM_NOTICE_CACHE.clear()
        self.temporary.cleanup()

    def collect(self):
        with patch.object(builder, 'run', return_value=json.dumps({'packages': [self.package]})):
            builder.dependency_licenses({'rust': '1.95.0'}, self.source,
                                        {'CARGO_HOME': str(self.cargo)}, 'aarch64-apple-darwin', self.output)

    def test_reuse_notices_are_retained_from_crate_without_github_fallback(self):
        texts = {'MIT.txt': 'original MIT text', 'Apache-2.0.txt': 'original Apache text', 'CC0-1.0.txt': 'original CC0 text'}
        (self.folder / 'LICENSES').mkdir()
        for name, contents in texts.items():
            (self.folder / 'LICENSES' / name).write_text(contents)
        with patch.object(builder, 'upstream_license_files', side_effect=AssertionError('No remote fallback needed')):
            self.collect()
        for name, contents in texts.items():
            self.assertEqual((self.output / 'synthetic-1.0.0/LICENSES' / name).read_text(), contents)
        index = json.loads((self.output / 'index.json').read_text())
        self.assertEqual(set(index[0]['files']), {'LICENSES/' + name for name in texts})

    def test_arbitrary_nested_source_does_not_satisfy_missing_notice(self):
        (self.folder / 'LICENSES').mkdir()
        (self.folder / 'LICENSES/implementation.rs').write_text('not a license')
        with patch.object(builder, 'upstream_license_files', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'synthetic-1.0.0'):
                self.collect()

    def test_git_workspace_root_notices_keep_working(self):
        parent = self.cargo / 'git/checkouts/example/commit'
        self.folder = parent / 'crates/child'
        self.folder.mkdir(parents=True)
        (parent / 'Cargo.toml').write_text('[workspace]\n')
        (parent / 'LICENSE-MIT').write_text('original git workspace license')
        (self.folder / 'Cargo.toml').write_text('[package]\n')
        self.package.update(manifest_path=str(self.folder / 'Cargo.toml'), source='git+https://github.com/example/project#' + 'a' * 40)
        with patch.object(builder, 'upstream_license_files', side_effect=AssertionError('Root notice already present')):
            self.collect()
        self.assertEqual((self.output / 'synthetic-1.0.0/LICENSE-MIT').read_text(), 'original git workspace license')

    def test_txt_notices_are_fetched_only_at_the_published_crate_commit(self):
        commit = 'e5f1c5205326804637368422fe420aa1b9769676'
        self.package['repository'] = 'https://github.com/robertknight/ocrs'
        (self.folder / '.cargo_vcs_info.json').write_text(json.dumps({'git': {'sha1': commit}}))
        root = self.package['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') + '/' + commit + '/'
        expected = {'LICENSE-MIT.txt': b'Synthetic upstream MIT notice used only by this test.',
                    'LICENSE-APACHE.txt': b'Synthetic upstream Apache notice used only by this test.'}
        fetched = []

        class Response:
            def __init__(self, url, data): self.url, self.data = url, data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return self.data[:limit]

        def open_url(request, timeout):
            url = request.full_url
            fetched.append(url)
            name = url.removeprefix(root)
            if url.startswith(root) and name in expected:
                return Response(url, expected[name])
            raise urllib.error.HTTPError(url, 404, 'No such file', {}, None)

        with patch.object(builder.urllib.request, 'urlopen', side_effect=open_url):
            records = builder.upstream_license_files(self.package, self.folder, self.root / 'cache')
        self.assertEqual({name for name, _, _ in records}, set(expected))
        self.assertTrue(all(url.startswith(root) for url in fetched))
        for name, path, url in records:
            self.assertEqual(path.read_bytes(), expected[name])
            self.assertEqual(url, root + name)


if __name__ == '__main__':
    unittest.main()
