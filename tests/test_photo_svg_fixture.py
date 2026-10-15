"""Offline tests of the real pinned Photo patch, scope guard and source package.

No native code runs. The original SVG regression's assertions remain unchanged.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import full_native as full

RUST = 'crates/io/src/svg.rs'
FIXTURE = 'crates/io/tests/fixtures/upstream-photocraft-single-clip.svg'
OLD = b'include_bytes!("../../../assets/app-icon/photocraft.svg")'
NEW = b'include_bytes!("../tests/fixtures/upstream-photocraft-single-clip.svg")'
ICON_SHA = 'a48333b7b794b70158da93a262d84fb82f5fbbf7442db60f235a0a69136a1ce2'
ORIGINAL_SHA = '1c6bb8d35da7aaf6f36ee37cb2fb681d105a92a7dc988551726451b3c47ff03a'
AFTER_SHA = '8e1935f10b8ade3cacde4f817832ed3ea1f369cc175f0aae7c937910d000c952'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class PhotoSvgOriginalFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = full.load_lock('photo')
        cls.fix, cls.meta = full.functional_fixes(cls.lock)[0]
        cls.original = (full.ROOT / 'tests/fixtures/photo-svg/upstream-svg.rs').read_bytes()
        cls.provenance = json.loads((full.ROOT / 'tests/fixtures/photo-svg/provenance.json').read_text(encoding='utf-8'))

    def test_hash_locked_correction_and_original_rust_fixture(self):
        self.assertEqual(len(self.lock['functionalFixes']), 1)
        self.assertEqual(sha(self.original), ORIGINAL_SHA)
        self.assertEqual(len(self.original), 38059)
        self.assertEqual(self.provenance['upstream'], self.lock['source'])
        self.assertEqual(self.provenance['originalRust'], {'path': RUST, 'bytes': 38059, 'sha256': ORIGINAL_SHA})
        self.assertEqual(self.provenance['originalIcon']['sha256'], ICON_SHA)
        self.assertFalse(self.provenance['sourceDownloadedOrExecutedByTests'])
        self.assertEqual(full.photo_fixture_functional_paths(self.meta), {RUST, FIXTURE})

    def test_guard_rejects_third_path_even_with_otherwise_valid_metadata(self):
        meta = copy.deepcopy(self.meta)
        meta['files'].append({'path': 'crates/engine/src/lib.rs', 'before': None, 'after': {'bytes': 1, 'sha256': '0' * 64}})
        with self.assertRaises(ValueError):
            full.photo_fixture_functional_paths(meta)

    def test_guard_rejects_duplicate_paths(self):
        meta = copy.deepcopy(self.meta)
        meta['files'] = [meta['files'][0], copy.deepcopy(meta['files'][0])]
        with self.assertRaises(ValueError):
            full.photo_fixture_functional_paths(meta)

    def test_guard_rejects_different_upstream(self):
        meta = copy.deepcopy(self.meta)
        meta['upstream']['commit'] = '0' * 40
        with self.assertRaises(ValueError):
            full.photo_fixture_functional_paths(meta)

    def test_guard_rejects_changed_before_after_or_fixture_bytes(self):
        for index, side, key, value in [(0, 'before', 'sha256', '0' * 64), (0, 'after', 'sha256', '0' * 64),
                                        (0, 'after', 'bytes', 38074), (1, 'after', 'sha256', '0' * 64),
                                        (1, 'after', 'bytes', 768637)]:
            with self.subTest(index=index, side=side, key=key):
                meta = copy.deepcopy(self.meta)
                meta['files'][index][side][key] = value
                with self.assertRaises(ValueError):
                    full.photo_fixture_functional_paths(meta)
        meta = copy.deepcopy(self.meta)
        meta['files'][1]['before'] = {'bytes': 1, 'sha256': '0' * 64}
        with self.assertRaises(ValueError):
            full.photo_fixture_functional_paths(meta)

    def test_guard_rejects_other_fixture_location(self):
        meta = copy.deepcopy(self.meta)
        meta['files'][1]['path'] = 'assets/app-icon/photocraft.svg'
        with self.assertRaises(ValueError):
            full.photo_fixture_functional_paths(meta)

    def source_fixture(self, root):
        path = root / RUST
        path.parent.mkdir(parents=True)
        path.write_bytes(self.original)
        for relative, data in [('Cargo.lock', b'unchanged Cargo sentinel\n'), ('crates/engine/src/lib.rs', b'unchanged engine sentinel\n'),
                               ('assets/app-icon/photocraft.svg', b'unchanged branded product icon sentinel\n')]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return {name: full.digest(path) for name, path in full.source_files(self.lock, root)}

    def test_real_patch_keeps_every_assertion_and_production_byte_then_reverses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = self.source_fixture(root)
            full.apply_functional_fixes(self.lock, root)
            after = {name: full.digest(path) for name, path in full.source_files(self.lock, root)}
            self.assertEqual({name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}, {RUST, FIXTURE})
            data = (root / RUST).read_bytes()
            self.assertEqual(len(data), 38073)
            self.assertEqual(sha(data), AFTER_SHA)
            self.assertEqual(data.replace(NEW, OLD), self.original)
            boundary = self.original.index(b'#[cfg(test)]')
            self.assertGreater(self.original.index(OLD), boundary)
            self.assertEqual(data[:boundary], self.original[:boundary])
            self.assertEqual(len(re.findall(rb'#\[test\]', data)), 5)
            self.assertEqual(len(re.findall(rb'\bassert(?:_eq|_ne)?!', data)), 28)
            self.assertIn(b'assert!(icon.document.layers.iter().any(|l| l.vector_mask.is_some())', data)
            self.assertEqual(((root / RUST).parent / '../tests/fixtures/upstream-photocraft-single-clip.svg').resolve(), (root / FIXTURE).resolve())
            icon = (root / FIXTURE).read_bytes()
            self.assertEqual(len(icon), 768636)
            self.assertEqual(sha(icon), ICON_SHA)
            elements = list(ET.fromstring(icon).iter())
            self.assertEqual({key: sum(node.tag.rsplit('}', 1)[-1] == key for node in elements) for key in ('clipPath', 'rect', 'path', 'image')},
                             {'clipPath': 1, 'rect': 2, 'path': 2, 'image': 0})
            self.assertTrue(any('clip-path' in node.attrib for node in elements))
            subprocess.run(['git', 'apply', '--reverse', '--check', '--binary', full.ROOT / self.fix['patch']], cwd=root, check=True, capture_output=True)
            subprocess.run(['git', 'apply', '--reverse', '--binary', full.ROOT / self.fix['patch']], cwd=root, check=True, capture_output=True)
            self.assertEqual({name: full.digest(path) for name, path in full.source_files(self.lock, root)}, before)

    def test_wrong_rust_baseline_fails_before_git_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.source_fixture(root)
            (root / RUST).write_bytes(self.original + b'\n')
            with patch.object(full, 'run') as execute:
                with self.assertRaisesRegex(ValueError, 'base changed'):
                    full.apply_functional_fixes(self.lock, root)
                execute.assert_not_called()

    def test_preexisting_fixture_fails_before_git_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.source_fixture(root)
            path = root / FIXTURE
            path.parent.mkdir(parents=True)
            path.write_bytes(b'unreviewed fixture')
            with patch.object(full, 'run') as execute:
                with self.assertRaisesRegex(ValueError, 'base changed'):
                    full.apply_functional_fixes(self.lock, root)
                execute.assert_not_called()

    def test_patch_hash_change_fails_closed(self):
        lock = copy.deepcopy(self.lock)
        lock['functionalFixes'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            full.functional_fixes(lock)

    def test_manifest_hash_change_fails_closed(self):
        lock = copy.deepcopy(self.lock)
        lock['functionalFixes'][0]['manifestSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            full.functional_fixes(lock)

    def test_only_reviewed_photo_version_and_full_release_features(self):
        self.assertEqual(self.lock['version'], '0.9.0-kio.1')
        self.assertEqual(self.lock['source']['commit'], 'c699e3cda69f4852b43c0b191ab0091aaeff9d6a')
        self.assertEqual(self.lock['testPackages'], ['photocraft-engine', 'photocraft-io'])
        self.assertEqual(self.lock['cargoArgs'], ['build', '--release', '--locked', '-p', 'photocraft', '-p', 'photocraft-cli', '--features', 'heif'])
        self.assertTrue(self.lock['features']['preserveDefaults'])

    def test_source_bundle_contains_patches_both_evidences_and_offline_regression(self):
        paths = dict(full.public_files(self.lock))
        for name in ['tests/test_photo_svg_fixture.py', 'tests/fixtures/photo-svg/upstream-svg.rs', 'tests/fixtures/photo-svg/provenance.json',
                     self.fix['patch'], self.fix['manifest'], 'manifests/build-prerequisites-photo-tests.json', 'manifests/build-prerequisites-photo-svg-fixture.json']:
            self.assertIn(name, paths)
        original = paths['manifests/build-prerequisites-photo-tests.json'].read_bytes()
        self.assertEqual(len(original), 92119)
        self.assertEqual(sha(original), '6ad1ced35ad1d672b4f6ffdc666efc37671bdc733573a7f0b8af0e545fccbfe2')
        current = json.loads(paths['manifests/build-prerequisites-photo-svg-fixture.json'].read_text(encoding='utf-8'))
        self.assertEqual(current['functionalCorrection'], self.fix)
        self.assertEqual(current['originalBuildAndRustFilesChecked'], 375)
        self.assertEqual(current['originalFilesByteIdentical'], 374)
        self.assertEqual(current['originalRustFilesByteIdentical'], 368)
        self.assertEqual(len(current['originalAndCurrentFileAssessment']), 375)
        exact = [row for row in current['originalAndCurrentFileAssessment'] if row['comparison'] == 'byte-identical-to-original']
        self.assertEqual(len(exact), 374)
        self.assertTrue(all(row['original'] == row['current'] for row in exact))
        self.assertEqual(current['appAndFontFiles'], 1773)
        self.assertEqual(current['sourceTreeSha256'], '8269234e10fabbd02128ca1139b12ec3998abdf1598fa2ce5371a463daea90b7')
        self.assertTrue(current['staticCoverageAssessment']['countsAreStaticDefinitionsNotExecutedTests'])
        self.assertEqual(current['staticCoverageAssessment']['unitTestAttributesUnchanged'], 2354)
        self.assertEqual(current['staticCoverageAssessment']['assertionMacroCallsUnchanged'], 11483)
        self.assertEqual(current['staticCoverageAssessment']['existingIgnoreAttributesUnchanged'], 24)
        self.assertFalse(current['nativeRebuildExecutedAfterFix'])
        self.assertFalse(current['nativeAssertionsClaimedPassedAfterFix'])
        self.assertTrue(current['productIconByteIdentical'])

    def test_both_os_provenance_binds_history_and_current_test_fixture_evidence(self):
        # Reuse the original profile tests' mocked orchestration boundary; no Cargo or native process runs.
        sys.path.insert(0, str(full.ROOT / 'tests'))
        import test_photo_test_profile as profile
        helper = profile.PhotoOriginalTestProfile()
        for platform in full.common.TARGETS:
            _, _, record = helper.build_fixture('photo', platform, {})
            execution = record['checks']['originalCoreTestExecution']
            self.assertEqual(execution['profile'], 'test')
            self.assertEqual(execution['originalProfileEvidence']['sha256'], '6ad1ced35ad1d672b4f6ffdc666efc37671bdc733573a7f0b8af0e545fccbfe2')
            binding = execution['originalTestFixtureEvidence']
            self.assertEqual(binding['path'], 'manifests/build-prerequisites-photo-svg-fixture.json')
            data = (full.ROOT / binding['path']).read_bytes()
            self.assertEqual(binding['bytes'], len(data))
            self.assertEqual(binding['sha256'], sha(data))

    def test_other_twelve_apps_do_not_get_photo_fixture_provenance(self):
        sys.path.insert(0, str(full.ROOT / 'tests'))
        import test_photo_test_profile as profile
        helper = profile.PhotoOriginalTestProfile()
        for app in set(full.IDS) - {'photo'}:
            _, _, record = helper.build_fixture(app, 'macos-arm64', {})
            self.assertNotIn('originalTestFixtureEvidence', record['checks']['originalCoreTestExecution'])


if __name__ == '__main__':
    unittest.main()
