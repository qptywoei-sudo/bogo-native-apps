"""Regression coverage for legal material present in full native dependencies."""
import importlib.util
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET
import zipfile

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
        self.folder = self.cargo / 'registry/src/index.crates.io-fixture' / label
        self.folder.mkdir(parents=True)
        self.package = {key: copy.deepcopy(self.pin[key]) for key in ('name', 'version', 'repository', 'license', 'authors')}
        self.package.update(manifest_path=str(self.folder / 'Cargo.toml'), source='registry+https://github.com/rust-lang/crates.io-index')
        declarations = {'Cargo.toml': b'[package]\n# synthetic original author and dual-license declaration\n',
                        'Cargo.toml.orig': b'[package]\n# synthetic unnormalized manifest\n',
                        'README.md': b'Synthetic original source declaration; not a real upstream license text.\n',
                        'Readme.markdown': b'Synthetic mixed-case original readme; not a real upstream license text.\n',
                        'src/lib.rs': b'// Synthetic public source retained byte for byte.\n'}
        self.contents = {name: declarations[name] for name in self.pin['declarationFiles']}
        self.contents['src/lib.rs'] = b'// Synthetic public source retained byte for byte.\n'
        if 'inlineOriginalNotice' in self.pin:
            prefix = b'/* Synthetic original notice, preserved exactly for this unit test. */\n'
            data = prefix + self.contents['src/lib.rs']
            self.contents['src/lib.rs'] = data
            self.pin['inlineOriginalNotice'].update(sourceBytes=len(data), sourceSha256=hashlib.sha256(data).hexdigest(),
                                                     prefixBytes=len(prefix), prefixSha256=hashlib.sha256(prefix).hexdigest())
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
        archive = self.cargo / 'registry/cache/index.crates.io-fixture' / (self.pin['name'] + '-' + self.pin['version'] + '.crate')
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, 'w:gz') as stream:
            for name, contents in sorted(self.contents.items()):
                member = tarfile.TarInfo(self.pin['name'] + '-' + self.pin['version'] + '/' + name)
                member.size = len(contents)
                stream.addfile(member, io.BytesIO(contents))
        self.pin.update(archiveBytes=archive.stat().st_size, archiveSha256=builder.digest(archive))
        self.archive = archive
        builder.write_json(self.folder / '.cargo-checksum.json', {'files': self.hashes, 'package': self.pin['archiveSha256']})

    def reviewed_collect(self, label, response=None):
        (self.root / 'LICENSE').write_bytes((builder.ROOT / 'LICENSE').read_bytes())
        with patch.dict(builder._REVIEWED_DECLARED_LICENSES, {label: self.pin}), patch.object(builder, 'upstream_license_files', side_effect=AssertionError('Known omission must not fetch mutable licenses')), \
                patch.object(builder, 'ROOT', self.root), patch.object(builder.urllib.request, 'urlopen', side_effect=response or self.notice_response):
            self.collect()

    def archive_response(self, request, timeout):
        label = self.pin['name'] + '-' + self.pin['version']
        url = 'https://static.crates.io/crates/' + self.pin['name'] + '/' + label + '.crate'
        self.assertEqual(request.full_url, url)

        class Response:
            def __enter__(response): return response
            def __exit__(response, *args): pass
            def read(response, limit): return self.archive_response_bytes[:limit]

        response = Response()
        response.url = url
        return response

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
            'qrcodegen-1.8.0': ('4339fc7a1021c9c1621d87f5e3505f2805c8c105420ba2f2a4df86814590c142', '720f62bddb7226106071d4728c292cb1df519ceb', 15014, 6),
            'fax-0.2.6': ('f05de7d48f37cd6730705cbca900770cab77a89f413d23e100ad7fad7795a0ab', '40b226eb97b391355e971fd95a8dd532a4c127a0', 13279, 17),
            'fax_derive-0.2.0': ('a0aca10fb742cb43f9e7bb8467c91aa9bcb8e3ffbc6a6f7389bb93ffc920577d', '40b226eb97b391355e971fd95a8dd532a4c127a0', 4442, 5),
            'zune-core-0.4.12': ('3f423a2c17029964870cfaabb1f13dfab7d092a62a29a89264f4d36990ca414a', 'f8fbb123d5ed04441e8324a555bfcda0cb1bd28f', 17355, 18),
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
            'qrcodegen-1.8.0': ('https://github.com/nayuki/QR-Code-generator', 'MIT', None, ['Project Nayuki'], '48f3460745b4e80d5b8028c8b7a7895628f954d2f7dc83f16ae9da33a7f6e38e'),
            'fax-0.2.6': ('https://github.com/pdf-rs/fax', 'MIT', '', ['Sebastian K <s3bk@protonmail.com>'], 'b8be9723e8633167a4b3fa23beac27c8c11c7673985c18258fe9ff24b8334a5b'),
            'fax_derive-0.2.0': ('https://github.com/pdf-rs/fax', 'MIT', 'derive', ['Sebastian K <s3bk@protonmail.com>'], '10199d02f627838ea29401aa541997d9ee26cbbcdaac37dfc0cd65d0fe12be62'),
            'zune-core-0.4.12': (None, 'MIT OR Apache-2.0 OR Zlib', 'crates/zune-core', [], '15708727978a23ce1fca2279ba155296e537653e250cedac8e563a27e11e654c'),
        }
        for label, values in expected.items():
            pin = builder._REVIEWED_DECLARED_LICENSES[label]
            self.assertEqual(tuple(pin[key] for key in ('archiveSha256', 'commit', 'archiveBytes', 'fileCount')), values)
            self.assertEqual(tuple(pin[key] for key in ('repository', 'license', 'pathInVcs', 'authors', 'filesManifestSha256')), declarations[label])
        first_four = {label: builder._REVIEWED_DECLARED_LICENSES[label] for label in ('cms-0.2.3', 'fmt-derive-0.1.2', 'fmt-derive-proc-0.1.2', 'rustls-cng-0.7.1')}
        self.assertEqual(sum(p['archiveBytes'] for p in first_four.values()), 217604)
        previous_nine = {label: pin for label, pin in builder._REVIEWED_DECLARED_LICENSES.items() if label not in ('fax-0.2.6', 'fax_derive-0.2.0', 'zune-core-0.4.12')}
        first_seven = {label: pin for label, pin in previous_nine.items() if label not in ('zune-inflate-0.2.54', 'qrcodegen-1.8.0')}
        self.assertEqual(sum(p['archiveBytes'] for p in first_seven.values()), 224447)
        self.assertEqual(sum(p['archiveBytes'] for label, p in previous_nine.items() if label != 'qrcodegen-1.8.0'), 262420)
        self.assertEqual(sum(p['archiveBytes'] for p in previous_nine.values()), 277434)
        self.assertEqual(sum(p['archiveBytes'] for p in builder._REVIEWED_DECLARED_LICENSES.values()), 312510)
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
                if 'inlineOriginalNotice' in self.pin:
                    self.assertNotIn('standardMit', proof)
                    self.assertFalse((output / 'STANDARD-MIT-TEXT.txt').exists())
                    self.assertIs(proof['inlineOriginalNotice']['isUpstreamOriginal'], True)
                    self.assertEqual((output / 'ORIGINAL-LICENSE-HEADER.txt').read_bytes(),
                                     self.contents['src/lib.rs'][:self.pin['inlineOriginalNotice']['prefixBytes']])
                    continue
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

    def test_all_eight_actual_registry_layouts_need_no_vendor_checksum_file(self):
        for label in builder._REVIEWED_DECLARED_LICENSES:
            with self.subTest(label=label):
                self.fixture(label)
                (self.folder / '.cargo-checksum.json').unlink()
                (self.folder / '.cargo-ok').write_text('{"v":1}')
                self.reviewed_collect(label)
                output = self.output / label
                self.assertFalse((self.folder / '.cargo-checksum.json').exists())
                self.assertFalse((output / 'original-crate/.cargo-checksum.json').exists())
                self.assertFalse((output / 'original-crate/.cargo-ok').exists())
                for relative, contents in self.contents.items():
                    self.assertEqual((output / 'original-crate' / relative).read_bytes(), contents)
                proof = json.loads((output / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
                self.assertIsNone(proof['cargoChecksumFileSha256'])
                self.assertEqual(proof['cargoChecksumMetadata'], {
                    'present': False, 'generatedByCollector': False, 'status': 'absent-in-original-registry-unpack'})
                self.assertEqual(proof['archiveVerification'], {
                    'origin': 'cargo-registry-cache', 'sha256': self.pin['archiveSha256'], 'bytes': self.pin['archiveBytes'],
                    'filesManifestSha256': self.pin['filesManifestSha256'], 'originalFileCount': len(self.contents),
                    'sourceBytes': sum(map(len, self.contents.values()))})

    def test_checksumless_registry_still_rejects_changed_source_and_extra_files(self):
        for label in builder._REVIEWED_DECLARED_LICENSES:
            with self.subTest(label=label):
                self.fixture(label)
                (self.folder / '.cargo-checksum.json').unlink()
                original = (self.folder / 'src/lib.rs').read_bytes()
                (self.folder / 'src/lib.rs').write_bytes(original + b'changed')
                self.assert_refused(label)
                (self.folder / 'src/lib.rs').write_bytes(original)
                for name in ['unexpected.txt', '.hidden-source', '.env', 'credentials.json']:
                    extra = self.folder / name
                    extra.write_text('unreviewed extra input')
                    self.assert_refused(label)
                    extra.unlink()
                self.assertFalse((self.folder / '.cargo-checksum.json').exists())

    def test_missing_sibling_archive_uses_only_authenticated_fixed_official_url(self):
        label = self.fixture()
        (self.folder / '.cargo-checksum.json').unlink()
        self.archive_response_bytes = self.archive.read_bytes()
        self.archive.unlink()
        self.reviewed_collect(label, response=self.archive_response)
        cached = self.root / '.cache/reviewed-published-crates' / (label + '.crate')
        self.assertEqual(cached.read_bytes(), self.archive_response_bytes)
        proof = json.loads((self.output / label / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
        self.assertEqual(proof['archiveVerification']['origin'], 'fixed-official-archive-cache')
        self.assertFalse((self.folder / '.cargo-checksum.json').exists())

    def test_fixed_archive_redirect_or_modified_response_is_rejected_before_caching(self):
        label = self.fixture()
        self.archive_response_bytes = self.archive.read_bytes()
        self.archive.unlink()
        original = self.archive_response_bytes

        def redirected(request, timeout):
            response = self.archive_response(request, timeout)
            response.url = 'https://unrelated.example/modified.crate'
            return response

        with self.assertRaisesRegex(ValueError, 'redirect'):
            self.reviewed_collect(label, response=redirected)
        for data in [original[:-1], original + b'x', bytes([original[0] ^ 1]) + original[1:]]:
            self.archive_response_bytes = data
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, 'SHA/bytes mismatch'):
                self.reviewed_collect(label, response=self.archive_response)
        self.assertFalse((self.root / '.cache/reviewed-published-crates' / (label + '.crate')).exists())
        self.assertFalse((self.output / label).exists())

    def test_modified_sibling_archive_is_rejected_without_remote_fallback(self):
        label = self.fixture()
        raw = self.archive.read_bytes()
        self.archive.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'published archive SHA/bytes mismatch'):
            self.reviewed_collect(label)
        self.assertFalse((self.output / label).exists())

    def test_sibling_archive_and_cache_directory_links_are_refused(self):
        label = self.fixture()
        raw = self.archive.read_bytes()
        other = self.root / 'unrelated.crate'
        other.write_bytes(raw)
        self.archive.unlink()
        self.archive.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'published archive SHA/bytes mismatch'):
            self.reviewed_collect(label)
        self.archive.unlink()
        cache = self.archive.parent
        moved = cache.with_name('moved-index')
        cache.rename(moved)
        (moved / self.archive.name).write_bytes(raw)
        cache.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'cache directory symlink'):
            self.reviewed_collect(label)
        self.assertFalse((self.output / label).exists())

    def test_bounded_tar_rejects_bad_format_links_paths_duplicates_and_bombs(self):
        label = self.fixture()

        def archive(entries):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode='w') as stream:
                for member, contents in entries:
                    stream.addfile(member, io.BytesIO(contents) if contents is not None else None)
            return gzip.compress(raw.getvalue())

        def file(name, contents=b'x'):
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            return member, contents

        symbolic = tarfile.TarInfo(label + '/link')
        symbolic.type, symbolic.linkname = tarfile.SYMTYPE, '../outside'
        hard = tarfile.TarInfo(label + '/hard')
        hard.type, hard.linkname = tarfile.LNKTYPE, label + '/Cargo.toml'
        cases = [('not-tar', gzip.compress(b'not a tar archive')),
                 ('symlink', archive([(symbolic, None)])), ('hardlink', archive([(hard, None)])),
                 ('traversal', archive([file(label + '/../outside')])),
                 ('absolute', archive([file('/' + label + '/outside')])),
                 ('backslash', archive([file(label + '/bad\\file')])),
                 ('duplicate', archive([file(label + '/same'), file(label + '/same')])),
                 ('case-collision', archive([file(label + '/Same'), file(label + '/same')])),
                 ('private-file', archive([file(label + '/credentials.json')])),
                 ('too-many-files', archive([file(label + '/file' + str(i)) for i in range(self.pin['fileCount'] + 1)])),
                 ('uncompressed-bomb', gzip.compress(b'x' * (self.pin['sourceBytes'] + self.pin['fileCount'] * 4096 + 65537)))]
        for name, data in cases:
            self.archive.write_bytes(data)
            self.pin.update(archiveBytes=len(data), archiveSha256=hashlib.sha256(data).hexdigest())
            with self.subTest(case=name):
                self.assert_refused(label)

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
                             if key not in ('zune-inflate-0.2.54', 'zune-core-0.4.12')))

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


class QrcodegenInlineNoticeTests(unittest.TestCase):
    """Synthetic whole-crate fixtures test the authenticated source-prefix path.

    Production archive/source/prefix hashes are pinned literally; these unit
    tests replace only their small synthetic file-tree and byte-range hashes.
    Actual published archive verification is retained as separate QA evidence.
    """
    setUp = DependencyNotices.setUp
    tearDown = DependencyNotices.tearDown
    collect = DependencyNotices.collect
    fixture = ReviewedDeclaredLicenseTests.fixture
    rehash = ReviewedDeclaredLicenseTests.rehash
    reviewed_collect = ReviewedDeclaredLicenseTests.reviewed_collect
    notice_response = ReviewedDeclaredLicenseTests.notice_response
    assert_refused = ReviewedDeclaredLicenseTests.assert_refused

    def test_exact_published_source_and_original_prefix_are_pinned_without_new_fixture_exceptions(self):
        pin = builder._REVIEWED_DECLARED_LICENSES['qrcodegen-1.8.0']
        self.assertEqual((pin['fileCount'], pin['sourceBytes'], pin['archiveBytes']), (6, 49996, 15014))
        self.assertEqual(pin['declarationFiles'], ['Cargo.toml', 'Cargo.toml.orig', 'Readme.markdown', 'src/lib.rs'])
        self.assertIs(pin['vcsInfoPresent'], True)
        self.assertIs(pin['pathInVcsPresent'], False)
        self.assertEqual(pin['publicTestCertificates'], {})
        self.assertEqual(pin['inlineOriginalNotice'], {
            'sourcePath': 'src/lib.rs', 'sourceBytes': 46056,
            'sourceSha256': 'a4546464799faaea27393dd60a24be08349618fb98333decbaf686d4c98ca410',
            'prefixBytes': 1239, 'prefixSha256': '29dd69709492b2f774fc322f0c18835d26a481fb02cd225beff64e32675d5e76',
            'officialSourceUrl': 'https://raw.githubusercontent.com/nayuki/QR-Code-generator/720f62bddb7226106071d4728c292cb1df519ceb/rust/src/lib.rs',
        })
        self.assertEqual([key for key, value in builder._REVIEWED_DECLARED_LICENSES.items() if 'inlineOriginalNotice' in value], ['qrcodegen-1.8.0'])

    def test_exact_original_prefix_is_copied_and_indexed_without_standard_text_or_remote_fetch(self):
        label = self.fixture('qrcodegen-1.8.0')
        self.reviewed_collect(label)
        output = self.output / label
        prefix = self.contents['src/lib.rs'][:self.pin['inlineOriginalNotice']['prefixBytes']]
        self.assertEqual((output / 'ORIGINAL-LICENSE-HEADER.txt').read_bytes(), prefix)
        self.assertFalse((output / 'STANDARD-MIT-TEXT.txt').exists())
        for name, content in self.contents.items():
            self.assertEqual((output / 'original-crate' / name).read_bytes(), content)
        proof = json.loads((output / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
        self.assertNotIn('standardMit', proof)
        self.assertEqual(proof['authors'], ['Project Nayuki'])
        self.assertEqual(proof['inlineOriginalNotice'], dict(self.pin['inlineOriginalNotice'],
                         file='ORIGINAL-LICENSE-HEADER.txt', isUpstreamOriginal=True,
                         publishedArchiveMember='qrcodegen-1.8.0/src/lib.rs'))
        self.assertEqual(set(json.loads((self.output / 'index.json').read_text())[0]['files']),
                         {'ORIGINAL-LICENSE-HEADER.txt', 'REVIEWED-LICENSE-PROVENANCE.json'})
        self.assertNotIn('Copyright (c) 2026 KIO', (output / 'ORIGINAL-LICENSE-HEADER.txt').read_text())

    def test_wrong_archive_digest_or_byte_count_fails_before_output(self):
        label = self.fixture('qrcodegen-1.8.0')
        original = self.archive.read_bytes()
        for wrong in (original + b'\0', bytes([original[0] ^ 1]) + original[1:]):
            with self.subTest(length=len(wrong)):
                self.archive.write_bytes(wrong)
                self.assert_refused(label)
        self.archive.write_bytes(original)

    def test_source_header_or_body_changes_fail_even_with_forged_cargo_checksums(self):
        label = self.fixture('qrcodegen-1.8.0')
        path = self.folder / 'src/lib.rs'
        original = path.read_bytes()
        for index in (0, len(original) - 1):
            with self.subTest(index=index):
                changed = original[:index] + bytes([original[index] ^ 1]) + original[index + 1:]
                path.write_bytes(changed)
                checksum = json.loads((self.folder / '.cargo-checksum.json').read_text())
                checksum['files']['src/lib.rs'] = hashlib.sha256(changed).hexdigest()
                builder.write_json(self.folder / '.cargo-checksum.json', checksum)
                self.assert_refused(label)
        path.write_bytes(original)

    def test_inline_descriptor_cannot_change_source_path_range_hash_or_official_identity(self):
        label = self.fixture('qrcodegen-1.8.0')
        original = copy.deepcopy(self.pin['inlineOriginalNotice'])
        for field, value in [('sourcePath', 'Cargo.toml'), ('sourceBytes', original['sourceBytes'] + 1),
                             ('sourceSha256', '0' * 64), ('prefixBytes', original['prefixBytes'] - 1),
                             ('prefixSha256', '0' * 64), ('officialSourceUrl', 'https://example.invalid/LICENSE')]:
            with self.subTest(field=field):
                self.pin['inlineOriginalNotice'] = dict(original, **{field: value})
                self.assert_refused(label)

    def test_qrcode_metadata_and_vcs_identity_remain_exact(self):
        label = self.fixture('qrcodegen-1.8.0')
        original = dict(self.package)
        for field, value in [('repository', 'https://github.com/other/project'), ('authors', ['Invented author']),
                             ('license', 'MIT OR Apache-2.0'), ('source', 'git+https://github.com/nayuki/QR-Code-generator'),
                             ('license_file', 'src/lib.rs')]:
            with self.subTest(field=field):
                self.package = dict(original, **{field: value})
                self.assert_refused(label)
        self.package = original
        for vcs in [{'git': {'sha1': 'f' * 40}}, {'git': {'sha1': self.pin['commit']}, 'path_in_vcs': None}]:
            self.contents['.cargo_vcs_info.json'] = json.dumps(vcs).encode()
            (self.folder / '.cargo_vcs_info.json').write_bytes(self.contents['.cargo_vcs_info.json'])
            self.rehash()  # A coherent forged archive/map cannot change reviewed identity.
            self.assert_refused(label)

    def test_missing_source_or_injected_private_file_remains_refused(self):
        label = self.fixture('qrcodegen-1.8.0')
        readme = self.folder / 'Readme.markdown'
        original = readme.read_bytes()
        readme.unlink()
        self.assert_refused(label)
        readme.write_bytes(original)
        (self.folder / 'private.key').write_bytes(b'unreviewed private material')
        self.assert_refused(label)

    def test_unreviewed_version_and_name_still_use_missing_notice_failure(self):
        self.fixture('qrcodegen-1.8.0')
        original = dict(self.package)
        for changes in ({'version': '1.8.1'}, {'name': 'other-qrcodegen'}):
            self.package = dict(original, **changes)
            with self.subTest(changes=changes), patch.object(builder, 'upstream_license_files', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'Dependencies without a packaged license'):
                    self.collect()

    def test_staged_missing_changed_or_forged_original_notice_is_refused(self):
        label = self.fixture('qrcodegen-1.8.0')
        self.reviewed_collect(label)
        root = self.root / 'staged'
        stage = root / 'Rust-dependencies' / label
        shutil.copytree(self.output / label, stage)
        path = stage / 'ORIGINAL-LICENSE-HEADER.txt'
        original = path.read_bytes()
        proof_path = stage / 'REVIEWED-LICENSE-PROVENANCE.json'
        original_proof = proof_path.read_bytes()
        with patch.dict(builder._REVIEWED_DECLARED_LICENSES, {label: self.pin}):
            self.assertTrue(builder.regular_files(root, public=True,
                            public_validator=builder.reviewed_notice_public_validator(root, 'Rust-dependencies')))
            path.unlink()
            with self.assertRaisesRegex(ValueError, 'notice missing or changed'):
                builder.reviewed_notice_public_validator(root, 'Rust-dependencies')
            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            with self.assertRaisesRegex(ValueError, 'notice missing or changed'):
                builder.reviewed_notice_public_validator(root, 'Rust-dependencies')
            path.write_bytes(original)
            proof = json.loads(original_proof)
            del proof['inlineOriginalNotice']
            builder.write_json(proof_path, proof)
            with self.assertRaisesRegex(ValueError, 'notice provenance differs'):
                builder.reviewed_notice_public_validator(root, 'Rust-dependencies')
            proof = json.loads(original_proof)
            proof['inlineOriginalNotice']['prefixSha256'] = '0' * 64
            builder.write_json(proof_path, proof)
            with self.assertRaisesRegex(ValueError, 'notice provenance differs'):
                builder.reviewed_notice_public_validator(root, 'Rust-dependencies')
            proof_path.write_bytes(original_proof)
            target = self.root / 'linked-notice.txt'
            path.rename(target)
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'notice missing or changed'):
                builder.reviewed_notice_public_validator(root, 'Rust-dependencies')


class StagedPublicNoticeTests(unittest.TestCase):
    """The Windows ZIP/MSI boundary authenticates complete staged legal copies."""
    setUp = DependencyNotices.setUp
    tearDown = DependencyNotices.tearDown
    collect = DependencyNotices.collect
    fixture = ReviewedDeclaredLicenseTests.fixture
    rehash = ReviewedDeclaredLicenseTests.rehash
    reviewed_collect = ReviewedDeclaredLicenseTests.reviewed_collect
    notice_response = ReviewedDeclaredLicenseTests.notice_response

    def stage(self, label='cms-0.2.3', checksum=False):
        self.fixture(label)
        if not checksum:
            (self.folder / '.cargo-checksum.json').unlink()
        self.reviewed_collect(label)
        app = self.root / 'portable'
        destination = app / 'OpenSourceLicenses/Rust-dependencies' / label
        shutil.copytree(self.output / label, destination)
        if not hasattr(self, 'staged_pins'):
            self.staged_pins = {}
        self.staged_pins[label] = copy.deepcopy(self.pin)
        return app, destination

    def traverse(self, root, prefix):
        with patch.dict(builder._REVIEWED_DECLARED_LICENSES, self.staged_pins):
            validator = builder.reviewed_notice_public_validator(root, prefix)
            return builder.regular_files(root, public=True, public_validator=validator)

    def test_all_four_original_fixture_paths_survive_both_packaging_boundaries(self):
        for label in ('cms-0.2.3', 'rustls-cng-0.7.1'):
            app, _ = self.stage(label)
            for root, prefix in ((app, 'OpenSourceLicenses/Rust-dependencies'),
                                 (app / 'OpenSourceLicenses', 'Rust-dependencies')):
                with self.subTest(crate=label, prefix=prefix):
                    with self.assertRaisesRegex(ValueError, 'Private file refused'):
                        builder.regular_files(root, public=True)
                    files = dict(self.traverse(root, prefix))
                    for relative, contents in self.contents.items():
                        self.assertEqual(files[prefix + '/' + label + '/original-crate/' + relative].read_bytes(), contents)

    def test_same_path_changed_certificate_is_rejected_even_when_proof_is_forged(self):
        app, stage = self.stage()
        relative = next(iter(self.pin['publicTestCertificates']))
        path = stage / 'original-crate' / relative
        path.write_bytes(b'private replacement certificate')
        proof_path = stage / 'REVIEWED-LICENSE-PROVENANCE.json'
        proof = json.loads(proof_path.read_text())
        for row in proof['originalFiles']:
            if row['path'] == relative:
                row.update(bytes=path.stat().st_size, sha256=builder.digest(path))
        builder.write_json(proof_path, proof)
        with self.assertRaisesRegex(ValueError, 'manifest differs|SHA/bytes mismatch'):
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_removing_every_fixture_still_authenticates_the_complete_staged_crate(self):
        for label in ('cms-0.2.3', 'rustls-cng-0.7.1'):
            app, stage = self.stage(label)
            originals = {stage / 'original-crate' / path: self.contents[path]
                         for path in self.pin['publicTestCertificates']}
            for path in originals:
                path.unlink()
            for root, prefix in ((app, 'OpenSourceLicenses/Rust-dependencies'),
                                 (app / 'OpenSourceLicenses', 'Rust-dependencies')):
                with self.subTest(crate=label, prefix=prefix), self.assertRaisesRegex(ValueError, 'missing or additional'):
                    self.traverse(root, prefix)
            for path, data in originals.items():
                path.write_bytes(data)
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_identical_fixture_bytes_at_any_other_path_are_rejected(self):
        app, stage = self.stage()
        original = stage / 'original-crate' / next(iter(self.pin['publicTestCertificates']))
        for relative in ('personal.pfx', 'OpenSourceLicenses/private.p12',
                         'OpenSourceLicenses/Rust-dependencies/cms-0.2.3/copied.pfx',
                         'OpenSourceLicenses/Rust-dependencies/cms-0.2.3/original-crate/tests/other.pfx',
                         'OpenSourceLicenses/Rust-dependencies/unreviewed-1.0.0/original-crate/tests/examples/example.pfx'):
            extra = app / relative
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(original.read_bytes())
            with self.subTest(path=relative), self.assertRaises(ValueError):
                self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')
            extra.unlink()

    def test_complete_original_manifest_rejects_changed_missing_or_extra_source(self):
        app, stage = self.stage()
        source = stage / 'original-crate/src/lib.rs'
        original = source.read_bytes()
        for contents in (None, original + b'changed'):
            if contents is None:
                source.unlink()
            else:
                source.write_bytes(contents)
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')
        source.write_bytes(original)
        extra = stage / 'original-crate/unreviewed.rs'
        extra.write_bytes(b'extra public source is still not the pinned original')
        with self.assertRaisesRegex(ValueError, 'additional files'):
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_staged_proof_cannot_replace_archive_author_identity_or_manifest(self):
        app, stage = self.stage()
        proof_path = stage / 'REVIEWED-LICENSE-PROVENANCE.json'
        original = json.loads(proof_path.read_text())
        changed_archive = dict(original['publishedArchive'], sha256='0' * 64)
        for key, value in (('publishedArchive', changed_archive), ('authors', ['unreviewed']),
                           ('reviewedPublicTestCertificates', {}), ('filesManifestSha256', '0' * 64),
                           ('sourceBytes', original['sourceBytes'] + 1), ('originalFiles', []),
                           ('cargoChecksumMetadata', {'present': False, 'generatedByCollector': True}),
                           ('cargoChecksumFileSha256', '0' * 64)):
            builder.write_json(proof_path, dict(original, **{key: value}))
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')
        for value in ([], None, 'not proof'):
            builder.write_json(proof_path, value)
            with self.subTest(proof=value), self.assertRaises(ValueError):
                self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_optional_original_checksum_is_authenticated_without_inventing_one(self):
        app, stage = self.stage(checksum=True)
        checksum = stage / 'original-crate/.cargo-checksum.json'
        self.assertIn('OpenSourceLicenses/Rust-dependencies/cms-0.2.3/original-crate/.cargo-checksum.json',
                      dict(self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')))
        value = json.loads(checksum.read_text())
        builder.write_json(checksum, dict(value, package='0' * 64))
        with self.assertRaisesRegex(ValueError, 'checksum metadata changed'):
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')
        checksum.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or additional'):
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_legal_source_and_metadata_links_are_rejected(self):
        app, stage = self.stage()
        paths = [stage / 'original-crate/src/lib.rs', stage / 'REVIEWED-LICENSE-PROVENANCE.json',
                 stage / 'original-crate/tests', app / 'OpenSourceLicenses']
        for index, path in enumerate(paths):
            saved = self.root / ('link-target-' + str(index))
            path.rename(saved)
            path.symlink_to(saved, target_is_directory=saved.is_dir())
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')
            path.unlink()
            saved.rename(path)

    def test_fixture_bytes_are_rechecked_after_cached_whole_crate_authentication(self):
        app, stage = self.stage('rustls-cng-0.7.1')
        with patch.dict(builder._REVIEWED_DECLARED_LICENSES, {'rustls-cng-0.7.1': self.pin}):
            validate = builder.reviewed_notice_public_validator(app, 'OpenSourceLicenses/Rust-dependencies')
            paths = list(self.pin['publicTestCertificates'])
            validate('OpenSourceLicenses/Rust-dependencies/rustls-cng-0.7.1/original-crate/' + paths[0])
            (stage / 'original-crate' / paths[1]).write_bytes(b'changed after authentication')
            with self.assertRaisesRegex(ValueError, 'certificate SHA/bytes mismatch'):
                validate('OpenSourceLicenses/Rust-dependencies/rustls-cng-0.7.1/original-crate/' + paths[1])

    def test_unscoped_public_policy_and_invalid_prefixes_remain_closed(self):
        app, stage = self.stage()
        for name in ('.env', 'personal.pfx', 'personal.p12', 'secret.key', 'records.sqlite', 'credentials.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                builder.check_public_path(name)
        for prefix in ('', 'Other', '../Rust-dependencies', 'OpenSourceLicenses'):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                builder.reviewed_notice_public_validator(app, prefix)
        private = stage / 'original-crate/private.key'
        private.write_bytes(b'private input')
        with self.assertRaises(ValueError):
            self.traverse(app, 'OpenSourceLicenses/Rust-dependencies')

    def test_real_windows_zip_and_msi_builders_retain_all_four_reviewed_fixture_files(self):
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location('fixture_full_native', scripts / 'full_native.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        pins, expected = {}, {}
        for label in ('cms-0.2.3', 'rustls-cng-0.7.1'):
            app, _ = self.stage(label)
            pins[label] = copy.deepcopy(self.pin)
            expected.update({'OpenSourceLicenses/Rust-dependencies/' + label + '/original-crate/' + path: contents
                             for path, contents in self.contents.items()})
        with patch.dict(native.common._REVIEWED_DECLARED_LICENSES, pins):
            validate = native.common.reviewed_notice_public_validator(app, 'OpenSourceLicenses/Rust-dependencies')
            files = native.common.regular_files(app, public=True, public_validator=validate)
            output = self.root / 'portable.zip'
            native.common.create_source_zip(output, [('KIO PDF/' + name, path) for name, path in files], 1700000000)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(len(archive.infolist()), len(files))
                for path, contents in expected.items():
                    self.assertEqual(archive.read('KIO PDF/' + path), contents)
            original = '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs"><Package><Feature Id="Original"></Feature></Package></Wix>'
            text, count = native.add_msi_notices(original, {'id': 'pdf'}, app / 'OpenSourceLicenses')
            root = ET.fromstring(text)
            installed = root.findall('.//{http://wixtoolset.org/schemas/v4/wxs}File')
            self.assertEqual(count, len(files))
            self.assertEqual({Path(node.attrib['Source']) for node in installed}, {path.resolve() for _, path in files})
            self.assertEqual(sum(Path(node.attrib['Source']).suffix in ('.pfx', '.p12') for node in installed), 4)
            # Exercise package() itself: native compilation and WiX execution are
            # deliberately mocked, while both legal traversals and ZIP writes run.
            lock = native.load_lock('pdf')
            work = self.root / 'package-work'
            work.mkdir()
            binaries = {'app': self.root / 'synthetic-gui.exe', 'cli': self.root / 'synthetic-cli.exe'}
            for name, path in binaries.items():
                path.write_bytes(('Synthetic ' + name + ' fixture; not a real native executable').encode())
            native.write_json(work / 'build-windows-x64.json', {'inputs': {}, 'binaries': {
                name: {'sha256': native.digest(path), 'bytes': path.stat().st_size} for name, path in binaries.items()}})

            def staged_notices(lock, source, fonts, destination, record, env, target):
                shutil.copytree(app / 'OpenSourceLicenses', destination)

            msi_calls = []
            def msi(lock, source, legal, stage, env, destination):
                xml, count = native.add_msi_notices(original, lock, legal)
                msi_calls.append((xml, count))
                destination.write_bytes(b'Synthetic MSI runner output; actual WiX is not executed by this test')
                return {'legalFiles': count}

            package_root = self.root / 'package-run'
            with patch.object(native, 'ROOT', package_root), patch.object(native, 'assert_host'), \
                    patch.object(native, 'prepared', return_value=(work, self.source, self.root / 'fonts', {})), \
                    patch.object(native, 'build_env', return_value={}), patch.object(native, 'binary_paths', return_value=binaries), \
                    patch.object(native, 'audit_native_dependencies', return_value={}), patch.object(native, 'stage_extras', return_value=[]), \
                    patch.object(native, 'notices', side_effect=staged_notices), patch.object(native, 'original_windows_msi', side_effect=msi), \
                    patch('sys.stdout', new=io.StringIO()):
                native.package(SimpleNamespace(platform='windows-x64', existing_target=None), lock)
            output = package_root / 'dist/pdf-windows-x64' / (native.artifact_base(lock, 'windows-x64') + '.zip')
            with zipfile.ZipFile(output) as archive:
                for path, contents in expected.items():
                    self.assertEqual(archive.read('KIO PDF/' + path), contents)
            self.assertEqual(len(msi_calls), 1)
            self.assertEqual(msi_calls[0][1], len(files))


class PhotoDependencyNoticeTests(unittest.TestCase):
    """Exact Photo packaging omissions reuse the authenticated source collector.

    Fixtures are small synthetic archives; no network or native execution is
    required. Production archives and immutable originals are audited separately.
    """
    labels = ('fax-0.2.6', 'fax_derive-0.2.0', 'zune-core-0.4.12')
    setUp = DependencyNotices.setUp
    tearDown = DependencyNotices.tearDown
    collect = DependencyNotices.collect
    fixture = ReviewedDeclaredLicenseTests.fixture
    rehash = ReviewedDeclaredLicenseTests.rehash
    reviewed_collect = ReviewedDeclaredLicenseTests.reviewed_collect
    notice_response = ReviewedDeclaredLicenseTests.notice_response
    assert_refused = ReviewedDeclaredLicenseTests.assert_refused

    def test_exact_photo_archives_source_manifests_and_no_new_private_exceptions(self):
        expected = {
            'fax-0.2.6': (13279, 17, 49986, 'b8be9723e8633167a4b3fa23beac27c8c11c7673985c18258fe9ff24b8334a5b'),
            'fax_derive-0.2.0': (4442, 5, 14434, '10199d02f627838ea29401aa541997d9ee26cbbcdaac37dfc0cd65d0fe12be62'),
            'zune-core-0.4.12': (17355, 18, 76660, '15708727978a23ce1fca2279ba155296e537653e250cedac8e563a27e11e654c'),
        }
        for label, values in expected.items():
            pin = builder._REVIEWED_DECLARED_LICENSES[label]
            self.assertEqual(tuple(pin[k] for k in ('archiveBytes', 'fileCount', 'sourceBytes', 'filesManifestSha256')), values)
            self.assertEqual(pin['publicTestCertificates'], {})
        zune = builder._REVIEWED_DECLARED_LICENSES['zune-core-0.4.12']
        self.assertIsNone(zune['repository'])
        self.assertEqual(zune['authors'], [])
        self.assertEqual(zune['upstreamNotices'], [
            {'path': 'LICENSE.md', 'bytes': 357, 'sha256': 'c6dff146a9f31848ac296faa5a08a4253caf2c384c86f906dc99e7fc0a39cc8c'},
            {'path': 'LICENSE-ZLIB', 'bytes': 818, 'sha256': '7fa429541e55b1509909e058f2d21a37467e4958ec713b357f6e0cf9dc4ee352'},
        ])

    def test_all_three_preserve_complete_source_without_inventing_original_notices(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                self.reviewed_collect(label)
                output = self.output / label
                proof = json.loads((output / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
                self.assertEqual(proof['authors'], self.pin['authors'])
                self.assertEqual(proof['repository'], self.pin['repository'])
                self.assertEqual(proof['declaredLicense'], self.pin['license'])
                self.assertEqual(proof['selectedLicense'], 'MIT')
                self.assertFalse(proof['standardMit']['isUpstreamOriginal'])
                self.assertFalse(proof['standardMit']['addsCopyrightNotice'])
                text = (output / 'STANDARD-MIT-TEXT.txt').read_text()
                self.assertIn('not an upstream license file', text)
                self.assertNotIn('Copyright (c)', text)
                for relative, data in self.contents.items():
                    self.assertEqual((output / 'original-crate' / relative).read_bytes(), data)
                for notice in self.pin.get('upstreamNotices', []):
                    self.assertEqual((output / ('UPSTREAM-' + notice['path'])).read_bytes(), self.notice_contents[notice['path']])
                if label.startswith('fax'):
                    self.assertNotIn('upstreamNotices', proof)
                    self.assertNotIn('inlineOriginalNotice', proof)

    def test_all_three_registry_unpack_without_vendor_checksum_is_honest(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                (self.folder / '.cargo-checksum.json').unlink()
                self.reviewed_collect(label)
                proof = json.loads((self.output / label / 'REVIEWED-LICENSE-PROVENANCE.json').read_text())
                self.assertEqual(proof['cargoChecksumMetadata'], {'present': False, 'generatedByCollector': False,
                                                                 'status': 'absent-in-original-registry-unpack'})
                self.assertFalse((self.output / label / 'original-crate/.cargo-checksum.json').exists())

    def test_all_three_refuse_source_tampering_before_output(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                source = self.folder / 'src/lib.rs'
                source.write_bytes(source.read_bytes() + b'// changed\n')
                self.assert_refused(label)

    def test_all_three_refuse_unreviewed_private_or_extra_files(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                (self.folder / 'private.pfx').write_bytes(b'Not an approved public certificate fixture')
                self.assert_refused(label)

    def test_all_three_refuse_wrong_archive_even_with_matching_unpacked_metadata(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                data = self.archive.read_bytes()
                self.archive.write_bytes(bytes([data[0] ^ 1]) + data[1:])
                self.assert_refused(label)

    def test_all_three_refuse_forged_vendor_checksum_or_published_vcs_identity(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                checksum = self.folder / '.cargo-checksum.json'
                original = checksum.read_bytes()
                metadata = json.loads(original)
                metadata['package'] = '0' * 64
                builder.write_json(checksum, metadata)
                self.assert_refused(label)
                checksum.write_bytes(original)
                metadata['package'] = self.pin['archiveSha256']
                metadata['files']['src/lib.rs'] = '0' * 64
                builder.write_json(checksum, metadata)
                self.assert_refused(label)
                checksum.write_bytes(original)
                vcs = self.folder / '.cargo_vcs_info.json'
                metadata = json.loads(vcs.read_text())
                metadata['git']['sha1'] = '0' * 40
                builder.write_json(vcs, metadata)
                self.assert_refused(label)

    def test_all_three_refuse_invented_authors_repository_license_or_versions(self):
        for label in self.labels:
            with self.subTest(label=label):
                self.fixture(label)
                original = dict(self.package)
                for key, value in [('authors', ['Invented KIO copyright holder']), ('repository', 'https://github.com/other/project'),
                                   ('license', 'Apache-2.0')]:
                    self.package = dict(original, **{key: value})
                    self.assert_refused(label)
                with self.assertRaisesRegex(ValueError, 'no reviewed omitted-license exception'):
                    builder.reviewed_declared_license(dict(original, version=self.pin['version'] + '.1'),
                                                      self.folder, self.output / label)
                self.assertFalse((self.output / label).exists())

    def test_zune_core_refuses_changed_or_redirected_original_notice_before_output(self):
        label = self.fixture('zune-core-0.4.12')
        original_response = self.notice_response

        def changed(request, timeout):
            response = original_response(request, timeout)
            response.read = lambda limit: b'X' * len(self.notice_contents['LICENSE.md'])
            return response

        with self.assertRaisesRegex(ValueError, 'original upstream notice checksum'):
            self.reviewed_collect(label, changed)
        self.assertFalse((self.output / label).exists())

        def redirected(request, timeout):
            response = original_response(request, timeout)
            response.url = 'https://example.org/unreviewed-license'
            return response

        with self.assertRaisesRegex(ValueError, 'redirect refused'):
            self.reviewed_collect(label, redirected)
        self.assertFalse((self.output / label).exists())


if __name__ == '__main__':
    unittest.main()
