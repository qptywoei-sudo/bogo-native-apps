from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bogo_release_identity import CURRENT_REVISION, release_version, approved_promotion_transition, promotion_transition_records
import launcher_native


class ImmutableReleaseIdentity(unittest.TestCase):
    def test_new_promotions_free_revision_does_not_reuse_published_revision_one(self):
        self.assertEqual(CURRENT_REVISION, 2)
        for original in ('0.6.0', '0.7.0', '0.8.0', '0.9.0', '0.10.0', '0.11.0'):
            self.assertEqual(release_version(original), original + '-bogo.2')
            self.assertNotEqual(release_version(original), original + '-bogo.1')

    def test_noncanonical_or_already_qualified_inputs_are_refused(self):
        for value in (None, 7, '', '0.7', '00.7.0', '0.07.0', '0.7.00', '0.7.0 ',
                      '0.7.0\n', 'v0.7.0', '0.7.0-kio.1', '0.7.0-bogo.1', '0.7.0+build'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release_version(value)

    def test_bogo_launcher_real_stdout_contract_uses_brand_and_full_revision(self):
        lock = {'id': 'launcher', 'name': 'Bogo Launcher', 'publisher': 'Bogo',
                'upstreamVersion': '0.4.1', 'version': '0.4.1-bogo.2', 'bogoOverlay': {}}
        with patch.object(launcher_native, 'run', return_value='Bogo Launcher 0.4.1-bogo.2'):
            self.assertEqual(launcher_native.check_versions(lock, {'app': 'measured-binary'}, {})['app'], 'Bogo Launcher 0.4.1-bogo.2')
        for invalid in ('artcraft-launcher 0.4.1', 'Bogo Launcher 0.4.1', 'Bogo Launcher 0.4.1-bogo.1'):
            with patch.object(launcher_native, 'run', return_value=invalid), self.assertRaises(ValueError):
                launcher_native.check_versions(lock, {'app': 'measured-binary'}, {})
        legacy = {'upstreamVersion': '0.4.1'}
        with patch.object(launcher_native, 'run', return_value='artcraft-launcher 0.4.1'):
            self.assertEqual(launcher_native.check_versions(legacy, {'app': 'legacy-binary'}, {})['app'], 'artcraft-launcher 0.4.1')

    def test_protected_exceptions_require_exact_both_file_identities(self):
        for app in ('cad', 'design', 'vector', 'film', 'light', 'pdf', 'effect', 'ui', 'word', 'sound', 'deck', 'grid', 'launcher', 'photo'):
            for row in promotion_transition_records(app):
                self.assertTrue(approved_promotion_transition(app, row['path'], row['before'], row['after']))
                for before, after in ((None, row['after']), (row['before'], None),
                                      ({**row['before'], 'bytes': row['before']['bytes'] + 1}, row['after']),
                                      (row['before'], {**row['after'], 'sha256': '0' * 64})):
                    self.assertFalse(approved_promotion_transition(app, row['path'], before, after))
                for path in ('crates/engine/src/document.rs', 'Cargo.lock', 'LICENSE-MIT', 'vendor/library.rs'):
                    self.assertFalse(approved_promotion_transition(app, path, row['before'], row['after']))


if __name__ == '__main__':
    unittest.main()
