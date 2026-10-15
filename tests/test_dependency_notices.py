"""Regression coverage for legal material present in full native dependencies."""
import importlib.util
import copy
import hashlib
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


class ReviewedDeclaredLicenseTests(unittest.TestCase):
    """Small synthetic fixtures exercise guards; real archive verification is separate.

    Only the synthetic file-tree pin is substituted. Public production pins are
    tested literally below and the real checksum-authenticated published
    archives are used for the explicit packaging review, never downloaded here.
    """
    setUp = DependencyNotices.setUp
    tearDown = DependencyNotices.tearDown
    collect = DependencyNotices.collect

    def fixture(self, label='cms-0.2.3'):
        self.pin = copy.deepcopy(builder._REVIEWED_DECLARED_LICENSES[label])
        self.notice_contents = {}
        for notice in self.pin.get('upstreamNotices', []):
            data = ('Synthetic original upstream notice for ' + notice['path'] + '; tests never download a license.\n').encode()
            notice.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            self.notice_contents[notice['path']] = data
        self.folder = self.cargo / 'registry/src' / label
        self.folder.mkdir(parents=True)
        self.package = {key: copy.deepcopy(self.pin[key]) for key in ('name', 'version', 'repository', 'license', 'authors')}
        self.package.update(manifest_path=str(self.folder / 'Cargo.toml'), source='registry+https://github.com/rust-lang/crates.io-index')
        declarations = {'Cargo.toml': b'[package]\n# synthetic original author and dual-license declaration\n',
                        'Cargo.toml.orig': b'[package]\n# synthetic unnormalized manifest\n',
                        'README.md': b'Synthetic original source declaration; not a real upstream license text.\n'}
        self.contents = {name: declarations[name] for name in self.pin['declarationFiles']}
        self.contents['src/lib.rs'] = b'// Synthetic public source retained byte for byte.\n'
        if self.pin['vcsInfoPresent']:
            vcs = {'git': {'sha1': self.pin['commit']}}
            if self.pin['pathInVcsPresent']:
                vcs['path_in_vcs'] = self.pin['pathInVcs']
            self.contents['.cargo_vcs_info.json'] = json.dumps(vcs).encode()
        for path in self.pin['publicTestCertificates']:
            data = ('synthetic public test certificate only: ' + path).encode()
            self.contents[path] = data
            self.pin['publicTestCertificates'][path] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for path, data in self.contents.items():
            target = self.folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.rehash()
        return label

    def rehash(self):
        self.hashes = {path: hashlib.sha256(data).hexdigest() for path, data in self.contents.items()}
        self.pin.update(fileCount=len(self.hashes), sourceBytes=sum(map(len, self.contents.values())),
                        filesManifestSha256=hashlib.sha256(json.dumps(self.hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        builder.write_json(self.folder / '.cargo-checksum.json', {'files': self.hashes, 'package': self.pin['archiveSha256']})

    def reviewed_collect(self, label):
        (self.root / 'LICENSE').write_bytes((builder.ROOT / 'LICENSE').read_bytes())
        with patch.dict(builder._REVIEWED_DECLARED_LICENSES, {label: self.pin}), patch.object(builder, 'upstream_license_files', side_effect=AssertionError('Known omission must not fetch mutable licenses')), \
                patch.object(builder, 'ROOT', self.root), patch.object(builder.urllib.request, 'urlopen', side_effect=self.notice_response):
            self.collect()

    def notice_response(self, request, timeout):
        root = 'https://raw.githubusercontent.com/' + self.pin['vcsRepository'] + '/' + self.pin['commit'] + '/'
        url = request.full_url
        name = url.removeprefix(root)
        self.assertTrue(url.startswith(root))
        self.assertIn(name, self.notice_contents)

        class Response:
            def __enter__(response): return response
            def __exit__(response, *args): pass
            def read(response, limit): return self.notice_contents[name][:limit]

        response = Response()
        response.url = url
        return response

    def assert_refused(self, label):
        with self.assertRaises(ValueError):
            self.reviewed_collect(label)
        self.assertFalse((self.output / label).exists())

    def test_exact_seven_production_pins_and_no_other_license_exception(self):
        expected = {
            'cms-0.2.3': ('7b77c319abfd5219629c45c34c89ba945ed3c5e49fcde9d16b6c3885f118a730', '5821a21553509dbd03eae593b0a1fad4e2083d4e', 179143, 62),
            'fmt-derive-0.1.2': ('1cb4a4b45c26455885f8b462db12978e51f60cc914337bccb9a36faf93410169', '3f1abe44dc5e36e467565d3bf636faba5193f2a1', 5201, 14),
            'fmt-derive-proc-0.1.2': ('7704da0760734344ce8753f15b21e97c6be85dc5a8f2c3a963fbd042b3380d23', '3f1abe44dc5e36e467565d3bf636faba5193f2a1', 4154, 12),
            'rustls-cng-0.7.1': ('3eeed9c3e96253f36d1cfdd593388ecca775b532b6ff0c649a3010f6af60fe70', 'b9126716029a105a08c1786993922103d9865bad', 29106, 24),
            'block-0.1.6': ('0d8c1fef690941d3e7788d328517591fecc684c084084702d6ff1641e993699a', None, 4077, 4),
            'malloc_buf-0.0.6': ('62bb907fe88d54d8d9ce32a3cceab4218ed2f6b7d35617cafe9adf84e43919cb', None, 1239, 2),
            'simd_helpers-0.1.0': ('95890f873bec569a0362c235787f3aca6e1e887302ba4840839bcc6459c42da6', 'ca1a2f84aa386d758e98f8a609d990263932fb85', 1527, 7),
            'zune-inflate-0.2.54': ('73ab332fe2f6680068f3582b16a24f90ad7096d5d39b974d1c0aff0125116f02', '69502ce83fdfecdd0beefd677e2abb3781b29d98', 37973, 16),
        }
        self.assertEqual(set(builder._REVIEWED_DECLARED_LICENSES), set(expected))
        declarations = {
            'cms-0.2.3': ('https://github.com/RustCrypto/formats/tree/master/cms', 'Apache-2.0 OR MIT', 'cms', ['RustCrypto Developers'], '3566b00b46b7b42cc0d6ed4424764f7d60db435144b2b68d2ae9671bb501caca'),
            'fmt-derive-0.1.2': ('https://github.com/danielschemmel/fmt-derive', 'MIT OR Apache-2.0', 'fmt-derive', ['Daniel Schemmel <daniel@schemmel.net>'], 'b35a3d17158fbc7ab8c2419e88b3bd582d78371b871e6f8a9e09830742ee7439'),
            'fmt-derive-proc-0.1.2': ('https://github.com/danielschemmel/fmt-derive', 'MIT OR Apache-2.0', 'fmt-derive-proc', ['Daniel Schemmel <daniel@schemmel.net>'], 'd7018a1d32aeed2ada20bbf7111847a834df461d6d31eeb70785542163c89101'),
            'rustls-cng-0.7.1': ('https://github.com/rustls/rustls-cng', 'MIT/Apache-2.0', '', ['Dmitry Pankratov <dmitry@pankratov.net>'], '1cf3147636b5ca0f8d1e9bcf88cddb6527dc8fb6630cfe741b175c22ab9b85b9'),
            'block-0.1.6': ('http://github.com/SSheldon/rust-block', 'MIT', None, ['Steven Sheldon'], '438aeb0004ae316f4618bf6597c498043e4b6a0640dd1b57e6c2e9e72d0807d3'),
            'malloc_buf-0.0.6': ('https://github.com/SSheldon/malloc_buf', 'MIT', None, ['Steven Sheldon'], '750a7cb75c76ac13a6448fec88535f22ca9b97432edc4f2e05e0a4b398b38130'),
            'simd_helpers-0.1.0': ('https://github.com/lu-zero/simd_helpers', 'MIT', None, ['Luca Barbato <lu_zero@gentoo.org>'], '7b361c6f6baf32d9baf33d39ec80036472a375245075b7d279cfb47eff1155bf'),
            'zune-inflate-0.2.54': (None, 'MIT OR Apache-2.0 OR Zlib', 'zune-inflate', [], 'eb32c5ed232eb27d811b9c3c662514e4a4c6a898bef7bad44a81e5c0388319df'),
        }
        for label, values in expected.items():
            pin = builder._REVIEWED_DECLARED_LICENSES[label]
            self.assertEqual(tuple(pin[key] for key in ('archiveSha256', 'commit', 'archiveBytes', 'fileCount')), values)
            self.assertEqual(tuple(pin[key] for key in ('repository', 'license', 'pathInVcs', 'authors', 'filesManifestSha256')), declarations[label])
        first_four = {label: pin for label, pin in builder._REVIEWED_DECLARED_LICENSES.items() if label not in ('block-0.1.6', 'malloc_buf-0.0.6', 'simd_helpers-0.1.0', 'zune-inflate-0.2.54')}
        self.assertEqual(sum(p['archiveBytes'] for p in first_four.values()), 217604)
        first_seven = {label: pin for label, pin in builder._REVIEWED_DECLARED_LICENSES.items() if label != 'zune-inflate-0.2.54'}
        self.assertEqual(sum(p['archiveBytes'] for p in first_seven.values()), 224447)
        self.assertEqual(sum(p['archiveBytes'] for p in builder._REVIEWED_DECLARED_LICENSES.values()), 262420)
        self.assertEqual(sum(len(p['publicTestCertificates']) for p in builder._REVIEWED_DECLARED_LICENSES.values()), 4)
        with self.assertRaisesRegex(ValueError, 'no reviewed'):
            builder.reviewed_declared_license(self.package, self.folder, self.output)

    def test_all_seven_preserve_complete_authenticated_source_and_label_standard_text(self):
        for label in builder._REVIEWED_DECLARED_LICENSES:
            with self.subTest(label=label):
                self.fixture(label)
                (self.folder / '.cargo-ok').write_text('{"v":1}')
                self.reviewed_collect(label)
                output = self.output / label
                for relative, contents in self.contents.items():
                    self.assertEqual((output / 'original-crate' / relative).read_bytes(), contents)
                self.assertEqual((output / 'original-crate/.cargo-checksum.json').read_bytes(), (self.folder / '.cargo-checksum.json').read_bytes())
                self.assertFalse((output / 'original-crate/.cargo-ok').exists())
                proof = json.loads((output / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
                self.assertEqual(proof['selectedLicense'], 'MIT')
                self.assertEqual(proof['declaredLicense'], self.pin['license'])
                self.assertEqual(proof['authors'], self.package['authors'])
                self.assertEqual(proof['publishedArchive']['sha256'], self.pin['archiveSha256'])
                self.assertEqual(len(proof['originalFiles']), len(self.contents))
                self.assertEqual([item['path'] for item in proof['originalDeclarationFiles']],
                                 ['original-crate/' + name for name in self.pin['declarationFiles']])
                self.assertEqual(proof['publishedVcsMetadata']['present'], self.pin['vcsInfoPresent'])
                self.assertEqual(proof['publishedVcsMetadata']['pathInVcsKeyPresent'], self.pin['pathInVcsPresent'])
                if self.pin['vcsInfoPresent']:
                    self.assertIn(self.pin['commit'], proof['immutableVcsUrl'])
                else:
                    self.assertIsNone(proof['commit'])
                    self.assertIsNone(proof['pathInVcs'])
                    self.assertIsNone(proof['immutableVcsUrl'])
                    self.assertEqual(proof['publishedVcsMetadata']['status'], 'absent-in-published-archive')
                self.assertFalse(proof['standardMit']['isUpstreamOriginal'])
                self.assertFalse(proof['standardMit']['addsCopyrightNotice'])
                text = (output / 'STANDARD-MIT-TEXT.txt').read_text()
                self.assertIn('not an upstream license file', text)
                if self.pin['license'] == 'MIT':
                    self.assertIn('this redistributed copy uses that declared license', text)
                else:
                    self.assertIn('KIO elects the MIT option', text)
                self.assertNotIn('Copyright (c) 2026 KIO', text)
                self.assertEqual(text.split('Permission is hereby granted', 1)[1], (builder.ROOT / 'LICENSE').read_text().split('Permission is hereby granted', 1)[1])

    def test_repository_license_authors_and_registry_identity_must_match_exactly(self):
        label = self.fixture()
        original = copy.deepcopy(self.package)
        for field, value in [('repository', 'https://github.com/other/cms'), ('license', 'MIT'),
                             ('authors', ['Unrelated author']), ('source', 'git+https://github.com/RustCrypto/formats#' + self.pin['commit']),
                             ('license_file', 'imagined-license.txt')]:
            with self.subTest(field=field):
                self.package = dict(original, **{field: value})
                self.assert_refused(label)
        for field, value in [('name', 'cms-unreviewed'), ('version', '0.2.4')]:
            changed = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'no reviewed'):
                builder.reviewed_declared_license(changed, self.folder, self.output)

    def test_package_checksum_and_forged_checksum_map_are_rejected(self):
        label = self.fixture()
        path = self.folder / '.cargo-checksum.json'
        checksum = json.loads(path.read_text())
        for changed in [dict(checksum, package='0' * 64), dict(checksum, files=dict(checksum['files'], **{'src/lib.rs': '1' * 64})),
                        dict(checksum, files={k: v for k, v in checksum['files'].items() if k != 'src/lib.rs'})]:
            builder.write_json(path, changed)
            self.assert_refused(label)
        builder.write_json(path, checksum)
        (self.folder / 'src/lib.rs').write_text('// changed source with unchanged Cargo checksums')
        self.assert_refused(label)
        forged = copy.deepcopy(checksum)
        forged['files']['src/lib.rs'] = builder.digest(self.folder / 'src/lib.rs')
        builder.write_json(path, forged)
        self.assert_refused(label)  # a coherently forged local map is still not the published map

    def test_exact_commit_and_path_in_vcs_are_independent_required_guards(self):
        label = self.fixture()
        for value in [{'git': {'sha1': 'f' * 40}, 'path_in_vcs': self.pin['pathInVcs']},
                      {'git': {'sha1': self.pin['commit']}, 'path_in_vcs': 'some-other-crate'}]:
            self.contents['.cargo_vcs_info.json'] = json.dumps(value).encode()
            (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
            self.rehash()  # independently exercise VCS guard after a synthetic valid map
            self.assert_refused(label)

    def test_missing_extra_and_hidden_source_files_are_rejected_before_copying(self):
        label = self.fixture()
        path = self.folder / 'src/lib.rs'
        original = path.read_bytes()
        path.unlink()
        self.assert_refused(label)
        path.write_bytes(original)
        for relative in ('extra-public.rs', '.git/secret', '__pycache__/private.pyc'):
            extra = self.folder / relative
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b'must never copy this additional file')
            self.assert_refused(label)
            extra.unlink()
            if relative.startswith(('.git/', '__pycache__/')):
                extra.parent.rmdir()

    def test_public_certificate_requires_separate_exact_bytes_and_checksum(self):
        label = self.fixture()
        path = next(iter(self.pin['publicTestCertificates']))
        with self.assertRaises(ValueError):
            builder.check_public_path(path)  # global private-name guard is unchanged
        data = self.contents[path]
        self.contents[path] = bytes([data[0] ^ 1]) + data[1:]
        (self.folder / path).write_bytes(self.contents[path])
        self.assert_refused(label)  # original Cargo checksum rejects changed bytes
        self.rehash()  # even a coherent local checksum cannot alter the certificate pin
        self.assert_refused(label)

    def test_additional_private_file_is_not_allowed_by_the_reviewed_crate_name(self):
        label = self.fixture('fmt-derive-0.1.2')
        self.contents['secret.key'] = b'unknown certificate/key must never be included'
        (self.folder / 'secret.key').write_bytes(self.contents['secret.key'])
        self.rehash()  # synthetic authenticated file map still cannot bypass private filter
        self.assert_refused(label)

    def test_unreviewed_crate_with_identical_license_expression_still_fails(self):
        self.package.update(name='some-other-crate', version='0.2.3', repository='https://github.com/other/project',
                            license='Apache-2.0 OR MIT', authors=['Someone'])
        with patch.object(builder, 'upstream_license_files', return_value=[]), self.assertRaisesRegex(ValueError, 'need review'):
            self.collect()

    def test_existing_dispatch_exception_is_preserved(self):
        self.package.update(name='dispatch', version='0.2.0', repository='http://github.com/SSheldon/rust-dispatch',
                            license='MIT', authors=['Original dispatch author'])
        with patch.object(builder, 'upstream_license_files', return_value=[]):
            self.collect()
        output = self.output / 'dispatch-0.2.0'
        self.assertTrue((output / 'original-crate/Cargo.toml').is_file())
        self.assertIn('Original authors: Original dispatch author', (output / 'STANDARD-MIT-TEXT.txt').read_text())

    def test_exact_declaration_files_and_vcs_presence_are_pinned(self):
        first_four = ('cms-0.2.3', 'fmt-derive-0.1.2', 'fmt-derive-proc-0.1.2', 'rustls-cng-0.7.1')
        for label in first_four:
            pin = builder._REVIEWED_DECLARED_LICENSES[label]
            self.assertEqual(pin['declarationFiles'], ['Cargo.toml', 'Cargo.toml.orig', 'README.md'])
            self.assertIs(pin['vcsInfoPresent'], True)
            self.assertIs(pin['pathInVcsPresent'], True)
        for label, declarations, vcs_present in (
                ('block-0.1.6', ['Cargo.toml', 'README.md'], False),
                ('malloc_buf-0.0.6', ['Cargo.toml'], False),
                ('simd_helpers-0.1.0', ['Cargo.toml', 'Cargo.toml.orig', 'README.md'], True)):
            pin = builder._REVIEWED_DECLARED_LICENSES[label]
            self.assertEqual(pin['declarationFiles'], declarations)
            self.assertIs(pin['vcsInfoPresent'], vcs_present)
            self.assertIs(pin['pathInVcsPresent'], False)
            self.assertIsNone(pin['pathInVcs'])
            if not vcs_present:
                self.assertIsNone(pin['commit'])
                self.assertIsNone(pin['vcsRepository'])

    def test_legacy_crates_cannot_gain_invented_vcs_even_with_a_coherent_file_map(self):
        for label in ('block-0.1.6', 'malloc_buf-0.0.6'):
            with self.subTest(label=label):
                self.fixture(label)
                self.contents['.cargo_vcs_info.json'] = json.dumps({'git': {'sha1': 'a' * 40}}).encode()
                (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
                self.rehash()
                self.assert_refused(label)

    def test_simd_absent_vcs_path_key_is_not_equivalent_to_null_or_empty(self):
        label = self.fixture('simd_helpers-0.1.0')
        for path_value in (None, '', 'some-other-crate'):
            with self.subTest(path_in_vcs=path_value):
                self.contents['.cargo_vcs_info.json'] = json.dumps({'git': {'sha1': self.pin['commit']}, 'path_in_vcs': path_value}).encode()
                (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
                self.rehash()
                self.assert_refused(label)

    def test_simd_published_commit_cannot_change_or_disappear(self):
        label = self.fixture('simd_helpers-0.1.0')
        self.contents['.cargo_vcs_info.json'] = json.dumps({'git': {'sha1': 'f' * 40}}).encode()
        (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
        self.rehash()
        self.assert_refused(label)
        del self.contents['.cargo_vcs_info.json']
        (self.folder / '.cargo_vcs_info.json').unlink()
        self.rehash()
        self.assert_refused(label)

    def test_exact_legacy_declaration_files_cannot_be_removed(self):
        for label, filename in (('block-0.1.6', 'README.md'), ('malloc_buf-0.0.6', 'Cargo.toml')):
            with self.subTest(label=label):
                self.fixture(label)
                del self.contents[filename]
                (self.folder / filename).unlink()
                self.rehash()
                self.assert_refused(label)

    def test_three_new_pins_reject_metadata_and_archive_identity_mutations(self):
        for label in ('block-0.1.6', 'malloc_buf-0.0.6', 'simd_helpers-0.1.0'):
            self.fixture(label)
            original = copy.deepcopy(self.package)
            for field, value in (('repository', 'https://github.com/unreviewed/source'),
                                 ('authors', ['Unrelated author']), ('license', 'MIT OR Apache-2.0'),
                                 ('source', 'git+https://github.com/unreviewed/source#' + 'a' * 40)):
                with self.subTest(label=label, field=field):
                    self.package = dict(original, **{field: value})
                    self.assert_refused(label)
            self.package = original
            checksum = json.loads((self.folder / '.cargo-checksum.json').read_text())
            checksum['package'] = '0' * 64
            builder.write_json(self.folder / '.cargo-checksum.json', checksum)
            self.assert_refused(label)

    def test_three_new_pins_reject_changed_bytes_and_coherently_forged_local_maps(self):
        for label in ('block-0.1.6', 'malloc_buf-0.0.6', 'simd_helpers-0.1.0'):
            with self.subTest(label=label):
                self.fixture(label)
                checksum_path = self.folder / '.cargo-checksum.json'
                checksum = json.loads(checksum_path.read_text())
                (self.folder / 'src/lib.rs').write_bytes(b'changed source must not be copied')
                self.assert_refused(label)
                checksum['files']['src/lib.rs'] = builder.digest(self.folder / 'src/lib.rs')
                builder.write_json(checksum_path, checksum)
                self.assert_refused(label)

    def test_new_reviewed_crate_does_not_allow_private_extra_files_or_file_links(self):
        label = self.fixture('malloc_buf-0.0.6')
        self.contents['private.key'] = b'unknown private input'
        (self.folder / 'private.key').write_bytes(self.contents['private.key'])
        self.rehash()
        self.assert_refused(label)
        del self.contents['private.key']
        (self.folder / 'private.key').unlink()
        self.rehash()
        (self.folder / 'src/lib.rs').unlink()
        (self.folder / 'src/lib.rs').symlink_to('../Cargo.toml')
        self.assert_refused(label)

    def test_duplicate_checksum_json_keys_are_rejected_before_output(self):
        label = self.fixture('block-0.1.6')
        files = json.dumps(self.hashes)
        (self.folder / '.cargo-checksum.json').write_text(
            '{"files":' + files + ',"files":' + files + ',"package":' + json.dumps(self.pin['archiveSha256']) + '}')
        self.assert_refused(label)

    def test_zune_exact_original_notice_pins_and_missing_metadata_are_honest(self):
        pin = builder._REVIEWED_DECLARED_LICENSES['zune-inflate-0.2.54']
        self.assertIsNone(pin['repository'])
        self.assertEqual(pin['authors'], [])
        self.assertEqual(pin['vcsRepository'], 'etemesi254/zune-image')
        self.assertEqual(pin['upstreamNotices'], [
            {'path': 'LICENSE.md', 'bytes': 384, 'sha256': 'e870d7fd7819a9f0453c62798cb52ae95d148a8c91dc2de1d983f997143c72de'},
            {'path': 'LICENSE-ZLIB', 'bytes': 818, 'sha256': '7fa429541e55b1509909e058f2d21a37467e4958ec713b357f6e0cf9dc4ee352'},
        ])
        self.assertFalse(any('upstreamNotices' in value for key, value in builder._REVIEWED_DECLARED_LICENSES.items()
                             if key != 'zune-inflate-0.2.54'))

    def test_zune_original_notices_are_retained_and_indexed_beside_all_source(self):
        label = self.fixture('zune-inflate-0.2.54')
        self.reviewed_collect(label)
        output = self.output / label
        proof = json.loads((output / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
        self.assertIsNone(proof['repository'])
        self.assertEqual(proof['authors'], [])
        self.assertEqual(proof['selectedLicense'], 'MIT')
        self.assertIn('VCS-root originals are retained separately', proof['omission'])
        self.assertEqual(proof['declaredLicense'], 'MIT OR Apache-2.0 OR Zlib')
        index = json.loads((self.output / 'index.json').read_text())[0]
        self.assertEqual(set(index['files']), {'UPSTREAM-LICENSE.md', 'UPSTREAM-LICENSE-ZLIB',
                                               'STANDARD-MIT-TEXT.txt', 'REVIEWED-LICENSE-PROVENANCE.json'})
        for original in proof['upstreamNotices']:
            self.assertEqual((output / ('UPSTREAM-' + original['path'])).read_bytes(), self.notice_contents[original['path']])
            self.assertEqual(original['url'], 'https://raw.githubusercontent.com/etemesi254/zune-image/' + self.pin['commit'] + '/' + original['path'])
            self.assertEqual(hashlib.sha256(self.notice_contents[original['path']]).hexdigest(), original['sha256'])
        for path, contents in self.contents.items():
            self.assertEqual((output / 'original-crate' / path).read_bytes(), contents)

    def test_zune_cannot_gain_invented_repository_authors_or_different_license(self):
        label = self.fixture('zune-inflate-0.2.54')
        original = copy.deepcopy(self.package)
        for key, value in [('repository', 'https://github.com/etemesi254/zune-image'),
                           ('authors', ['Invented author']), ('license', 'MIT'), ('license_file', 'LICENSE')]:
            with self.subTest(key=key):
                self.package = dict(original, **{key: value})
                self.assert_refused(label)

    def test_zune_published_vcs_identity_and_path_cannot_be_rewritten(self):
        label = self.fixture('zune-inflate-0.2.54')
        for vcs in [{'git': {'sha1': 'f' * 40}, 'path_in_vcs': 'zune-inflate'},
                    {'git': {'sha1': self.pin['commit']}, 'path_in_vcs': 'other-crate'},
                    {'git': {'sha1': self.pin['commit']}}]:
            with self.subTest(vcs=vcs):
                self.contents['.cargo_vcs_info.json'] = json.dumps(vcs).encode()
                (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
                self.rehash()
                self.assert_refused(label)

    def test_zune_rejects_changed_second_upstream_notice_before_creating_output(self):
        label = self.fixture('zune-inflate-0.2.54')
        self.notice_contents['LICENSE-ZLIB'] = b'changed or truncated upstream license'
        self.assert_refused(label)
        # The first successfully authenticated original may be cached; no
        # unverified response or partial notice output may be retained.
        cache = self.root / '.cache/upstream-licenses'
        self.assertEqual(len(list(cache.glob('*.txt'))), 1)
        self.assertEqual(next(cache.glob('*.txt')).read_bytes(), self.notice_contents['LICENSE.md'])

    def test_zune_rejects_redirects_before_retaining_original_notices(self):
        label = self.fixture('zune-inflate-0.2.54')
        original = self.notice_response

        def redirect(request, timeout):
            result = original(request, timeout)
            result.url = 'https://example.invalid/replacement-license'
            return result

        with patch.object(self, 'notice_response', side_effect=redirect):
            self.assert_refused(label)
        self.assertFalse((self.root / '.cache/upstream-licenses').exists())

    def test_zune_revalidates_cached_notice_bytes_and_refuses_file_links(self):
        label = self.fixture('zune-inflate-0.2.54')
        self.reviewed_collect(label)
        import shutil
        shutil.rmtree(self.output / label)
        cache = next((self.root / '.cache/upstream-licenses').glob('*.txt'))
        original = cache.read_bytes()
        cache.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        self.assert_refused(label)
        cache.unlink()
        target = self.root / 'replacement-original.txt'
        target.write_bytes(original)
        cache.symlink_to(target)
        self.assert_refused(label)

    def test_zune_rejects_forged_source_checksum_and_unreviewed_version(self):
        label = self.fixture('zune-inflate-0.2.54')
        (self.folder / 'src/lib.rs').write_bytes(b'changed original source')
        checksum = json.loads((self.folder / '.cargo-checksum.json').read_text())
        checksum['files']['src/lib.rs'] = builder.digest(self.folder / 'src/lib.rs')
        builder.write_json(self.folder / '.cargo-checksum.json', checksum)
        self.assert_refused(label)
        package = dict(self.package, version='0.2.55')
        with self.assertRaisesRegex(ValueError, 'no reviewed'):
            builder.reviewed_declared_license(package, self.folder, self.output)


if __name__ == '__main__':
    unittest.main()
