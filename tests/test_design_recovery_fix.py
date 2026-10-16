"""Keep the reviewed Design Windows recovery correction separate and exact."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'patches/design'
PATCH = FOLDER / 'functional-windows-recovery-lock.patch'
MANIFEST = FOLDER / 'functional-windows-recovery-lock.json'
PATHS = {'Cargo.lock', 'crates/engine/Cargo.toml', 'crates/engine/src/recovery.rs', 'crates/engine/src/cmd/book/safety_tests.rs',
         'crates/engine/tests/save_state_atomicity.rs'}
sys.path.insert(0, str(ROOT / 'scripts'))
import full_native as full


def sections(text):
    result = {}
    for block in text.split('diff --git ')[1:]:
        header, _, content = block.partition('\n')
        old, new = header.split()
        if old[2:] != new[2:]:
            raise AssertionError('Unexpected rename in narrow functional patch')
        result[new[2:]] = content
    return result


def changed_lines(block, sign):
    return [line[1:] for line in block.splitlines() if line.startswith(sign) and not line.startswith(sign * 3)]


class DesignRecoveryFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = json.loads(MANIFEST.read_text(encoding='utf-8'))
        cls.text = PATCH.read_text(encoding='utf-8')
        cls.parts = sections(cls.text)

    def test_patch_is_hash_locked_to_the_original_and_unchanged_branding(self):
        catalog = json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))
        lock = next(item for item in catalog['applications'] if item['id'] == 'design')
        self.assertEqual(self.meta['schema'], 'kio.native-functional-patch.v1')
        self.assertEqual(self.meta['programId'], 'design')
        self.assertEqual(self.meta['upstream']['commit'], '11a51d5b665aec8d6e675bd107a8a01514f10d00')
        self.assertEqual(self.meta['upstream']['sourceArchiveSha256'], lock['source']['sha256'])
        self.assertEqual(self.meta['base']['brandingPatchSha256'], lock['branding']['sha256'])
        self.assertEqual(hashlib.sha256(PATCH.read_bytes()).hexdigest(), self.meta['patch']['sha256'])
        self.assertEqual(PATCH.stat().st_size, self.meta['patch']['bytes'])

    def test_only_the_exact_five_reviewed_files_change(self):
        self.assertEqual(set(self.parts), PATHS)
        self.assertEqual({item['path'] for item in self.meta['files']}, PATHS)
        for item in self.meta['files']:
            self.assertRegex(item['before']['sha256'], r'^[a-f0-9]{64}$')
            self.assertRegex(item['after']['sha256'], r'^[a-f0-9]{64}$')
            self.assertNotEqual(item['before']['sha256'], item['after']['sha256'])
            self.assertGreater(item['before']['bytes'], 0)
            self.assertGreater(item['after']['bytes'], 0)
        self.assertNotIn('deleted file mode', self.text)
        self.assertNotIn('new file mode', self.text)

    def test_cargo_lock_changes_only_one_existing_dependency_edge(self):
        block = self.parts['Cargo.lock']
        self.assertEqual(changed_lines(block, '-'), [])
        self.assertEqual(changed_lines(block, '+'), [' "same-file",'])
        pin = self.meta['dependencyLock']
        self.assertEqual(pin['packageCountBefore'], 568)
        self.assertEqual(pin['packageCountAfter'], 568)
        self.assertEqual(pin['newPackages'], [])
        self.assertEqual(pin['removedPackages'], [])
        self.assertEqual(pin['changedPackageVersions'], [])
        self.assertEqual(pin['changedEdges'], [{'from': 'designcraft-engine 0.8.0', 'to': 'same-file 1.0.6', 'target': 'cfg(windows)'}])
        self.assertEqual(pin['existingLockedPackage'], {'name': 'same-file', 'version': '1.0.6', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': '93fc1dc3aaa9bfed95e02e6eadabb4baf7e3078b0bd1b4d7b6b0b68378900502', 'dependencies': ['winapi-util']})
        lock_file = next(item for item in self.meta['files'] if item['path'] == 'Cargo.lock')
        self.assertEqual(pin['original'], lock_file['before'])
        self.assertEqual(pin['modified'], lock_file['after'])

    def test_dependency_is_exact_and_windows_only_without_feature_changes(self):
        block = self.parts['crates/engine/Cargo.toml']
        self.assertEqual(changed_lines(block, '-'), [])
        added = '\n'.join(changed_lines(block, '+'))
        self.assertIn("[target.'cfg(windows)'.dependencies]", added)
        self.assertIn('same-file = "=1.0.6"', added)
        self.assertEqual([line for line in added.splitlines() if line.strip() and not line.startswith(('#', '['))], ['same-file = "=1.0.6"'])
        self.assertNotIn('features', added)
        self.assertNotIn('unsafe', added)

    def test_recovery_retains_every_original_line_and_adds_no_skip_or_unsafe(self):
        block = self.parts['crates/engine/src/recovery.rs']
        self.assertEqual(changed_lines(block, '-'), [])
        added = '\n'.join(changed_lines(block, '+'))
        self.assertNotIn('#[ignore', added)
        self.assertNotRegex(added, r'\bunsafe\b|#!\[feature\b|\.unlock\(')
        self.assertIn('#[cfg(not(windows))]', added)
        self.assertIn('let mut file = file;', added)
        self.assertIn('same_file::Handle::from_file(held.try_clone()?)?', added)
        self.assertIn('same_file::Handle::from_file(named.try_clone()?)?', added)
        self.assertIn('same_lock_file(lock, &named)', added)
        self.assertIn('same_lock_file(lock, &after_named)', added)
        self.assertIn('lock_marker(lock).map_err(|_| fail())?;', added)

    def test_all_six_added_native_regressions_are_present(self):
        added = '\n'.join(changed_lines(self.parts['crates/engine/src/recovery.rs'], '+'))
        tests = re.findall(r'#\[test\]\s*fn\s+(\w+)', added)
        self.assertEqual(tests, self.meta['tests']['added'])
        self.assertEqual(len(tests), 6)
        self.assertIn('lock_identity_accepts_the_owner_and_its_clone_without_unlocking', tests)
        self.assertIn('lock_identity_rejects_a_different_file_with_the_same_marker', tests)
        self.assertIn('lock_identity_rejects_path_replacement_and_preserves_the_replacement', tests)
        self.assertIn('lock_identity_preserves_the_bounded_marker_check', tests)
        self.assertIn('lock_identity_does_not_read_through_the_second_windows_handle', tests)
        self.assertIn('lock_identity_rejects_a_replaced_run_folder_without_touching_its_documents', tests)
        self.assertIn('Some(33)', added)
        self.assertIn('discard(&own, session.docs[0].uid);', added)
        self.assertIn('b"foreign document"', added)
        self.assertIn('b"foreign metadata"', added)

    def test_windows_fixture_moves_only_the_held_child_before_the_original_foreign_folder_checks(self):
        added = '\n'.join(changed_lines(self.parts['crates/engine/src/recovery.rs'], '+'))
        name = 'lock_identity_rejects_a_replaced_run_folder_without_touching_its_documents'
        body = added[added.index('    fn ' + name + '() {'):]
        body = body[:body.index('\n    }') + len('\n    }')]
        setup = ('        #[cfg(windows)]\n'
                 '        std::fs::rename(own.join(LOCK), root.path().join("relocated-held-lock")).unwrap();\n')
        original = '''    fn lock_identity_rejects_a_replaced_run_folder_without_touching_its_documents() {
        let root = tempfile::tempdir().unwrap();
        let own = run_dir(root.path()).unwrap();
        std::fs::rename(&own, root.path().join("former-run")).unwrap();
        std::fs::create_dir(&own).unwrap();
        std::fs::write(own.join(LOCK), b"").unwrap();
        let session = dirty_session();
        let (doc, meta) = files(&own, session.docs[0].uid);
        std::fs::write(&doc, b"foreign document").unwrap();
        std::fs::write(&meta, b"foreign metadata").unwrap();
        assert!(save(&session, &own).is_err());
        discard(&own, session.docs[0].uid);
        assert_eq!(std::fs::read(&doc).unwrap(), b"foreign document");
        assert_eq!(std::fs::read(&meta).unwrap(), b"foreign metadata");
    }'''
        self.assertEqual(body.count(setup), 1)
        self.assertEqual(body.replace(setup, ''), original)
        self.assertLess(body.index('relocated-held-lock'), body.index('former-run'))
        self.assertNotRegex(body, r'\breturn\b|\.unlock\(|\bdrop\(')
        self.assertNotIn('#[ignore', body)
        revision = self.meta['tests']['fixturePortability']
        self.assertEqual(revision['revision'], 2)
        self.assertEqual(revision['onlyAddedLines'], setup.splitlines())
        self.assertEqual(revision['observedNativeHead'], '425ca2a6c1b98703c2f86ab421d769ea2be750c5')
        self.assertIn('passed on actual Windows run 38818475536, job 116709095680', revision['newWindowsFixtureExecution'])
        self.assertFalse(revision['observationsApplyToSaveCopyRevision3'])

    def test_save_copy_changes_only_the_exact_expected_native_relative_path(self):
        block = self.parts['crates/engine/tests/save_state_atomicity.rs']
        self.assertEqual(changed_lines(block, '-'), [
            '    assert_eq!(copy.data_merge.sources[0].relative_path.as_deref(), Some("../../source/contacts.csv"));'])
        self.assertEqual(changed_lines(block, '+'), [
            '    let relative = Path::new("..").join("..").join("source").join("contacts.csv").to_string_lossy().into_owned();',
            '    assert_eq!(copy.data_merge.sources[0].relative_path.as_deref(), Some(relative.as_str()));'])
        self.assertEqual(len(re.findall(r'^@@', block, re.M)), 1)
        self.assertNotIn('#[cfg', block)
        self.assertNotIn('#[ignore', block)
        self.assertEqual(sum('assert_eq!(' in line for line in changed_lines(block, '-')), 1)
        self.assertEqual(sum('assert_eq!(' in line for line in changed_lines(block, '+')), 1)
        self.assertNotRegex('\n'.join(changed_lines(block, '+')), r'\breturn\b|\.replace\(|canonicalize\(')

    def test_save_copy_manifest_keeps_the_original_two_tests_and_eighteen_assertions(self):
        path = 'crates/engine/tests/save_state_atomicity.rs'
        entry = next(item for item in self.meta['files'] if item['path'] == path)
        self.assertEqual(entry['before'], {'sha256': 'ccbf07df7febe9d41ce1c37dcb8a1a607a58c4956068e1984b22bac4a29d4b58', 'bytes': 3387})
        self.assertEqual(entry['after'], {'sha256': '091c58e994878a91b91454698593814adb7e36a845a9a85472ff53a2225b5557', 'bytes': 3491})
        revision = self.meta['tests']['saveCopyPathPortability']
        self.assertEqual(revision['sourceOnlyChangeFrom425'], [path])
        self.assertEqual(revision['expectedPathComponents'], ['..', '..', 'source', 'contacts.csv'])
        self.assertEqual((revision['testDefinitionsBefore'], revision['testDefinitionsAfter']), (2, 2))
        self.assertEqual((revision['assertionMacrosBefore'], revision['assertionMacrosAfter']), (18, 18))
        self.assertTrue(revision['exactStringEqualityRetained'])
        self.assertEqual((revision['skipsAdded'], revision['runtimeChanges'], revision['additionalDependencyChanges']), (0, 0, 0))
        self.assertEqual(revision['newWholeNativeBothPlatforms'], 'pending')

    def test_actual_functional_guard_accepts_only_the_reviewed_design_paths(self):
        catalog = json.loads((ROOT / 'manifests/full-native-apps.json').read_text(encoding='utf-8'))
        lock = next(item for item in catalog['applications'] if item['id'] == 'design')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fix = lock['functionalFixes'][0]
            patch = root / fix['patch']
            manifest = root / fix['manifest']
            patch.parent.mkdir(parents=True)
            patch.write_bytes(PATCH.read_bytes())

            def check(meta):
                manifest.write_text(json.dumps(meta), encoding='utf-8')
                candidate = copy.deepcopy(lock)
                candidate['functionalFixes'][0]['manifestSha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
                with mock.patch.object(full, 'ROOT', root):
                    return full.functional_fixes(candidate)

            self.assertEqual(len(check(self.meta)), 1)
            for path in ('crates/engine/src/cmd/file.rs', 'crates/engine/tests/unreviewed.rs', 'LICENSE-MIT'):
                with self.subTest(path=path):
                    changed = copy.deepcopy(self.meta)
                    changed['files'].append({**changed['files'][-1], 'path': path})
                    with self.assertRaisesRegex(ValueError, 'unreviewed engine or legal file'):
                        check(changed)

    def test_book_partial_commit_assertions_compare_exact_debug_escaped_prefix(self):
        block = self.parts['crates/engine/src/cmd/book/safety_tests.rs']
        removed = changed_lines(block, '-')
        added = changed_lines(block, '+')
        self.assertEqual(len(removed), 2)
        self.assertTrue(all(line.lstrip().startswith('assert!(') for line in removed))
        self.assertEqual(sum(line.lstrip().startswith(('assert!(', 'assert_eq!(')) for line in added), 2)
        self.assertIn('assert_eq!(completed.trim(), format!("{:?}", vec![first.to_str().unwrap()]), "{error}");', '\n'.join(added))
        self.assertIn('second.to_str().unwrap()', '\n'.join(added))
        self.assertIn('third.to_str().unwrap()', '\n'.join(added))
        self.assertNotIn('#[ignore', block)


if __name__ == '__main__':
    unittest.main()
