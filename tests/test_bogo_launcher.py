import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bogo_launcher as bogo


class LauncherOverlayGuards(unittest.TestCase):
    def test_unreviewed_or_ambiguous_source_is_refused(self):
        for text in ('missing', 'before before'):
            with self.assertRaises(ValueError):
                bogo.replace_once(text, 'before', 'after')
        self.assertEqual(bogo.replace_once('before', 'before', 'after'), 'after')

    def test_overlay_refuses_changed_application_identity_before_editing(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for lock in ({'id': 'word', 'bundleId': 'com.kio.launcher'},
                         {'id': 'launcher', 'bundleId': 'com.bogo.launcher'}):
                with self.assertRaises(ValueError):
                    bogo.transform_launcher(source, lock)
            self.assertEqual(list(source.iterdir()), [])

    def test_exact_legacy_catalog_has_fourteen_distinct_identities(self):
        self.assertEqual(len(bogo.LEGACY_NAMES), 14)
        self.assertEqual(len(set(bogo.LEGACY_NAMES.values())), 14)
        self.assertEqual(bogo.LEGACY_NAMES['cadcraft'], 'KIO Cad')
        self.assertNotIn('studio', bogo.LEGACY_NAMES)


@unittest.skipUnless(os.environ.get('BOGO_NATIVE_ARCHIVES'), 'set BOGO_NATIVE_ARCHIVES for real published-source overlay checks')
class PublishedSourceOverlayTests(unittest.TestCase):
    def source(self, app, temporary):
        archives = list((Path(os.environ['BOGO_NATIVE_ARCHIVES']) / app).glob('*-source.zip'))
        self.assertEqual(len(archives), 1)
        root = Path(temporary)
        with zipfile.ZipFile(archives[0]) as archive:
            names = [name for name in archive.namelist() if name.endswith('.rs') and '/orchestrator/' not in name]
            for name in names:
                relative = Path(*Path(name).parts[1:])
                self.assertNotIn('..', relative.parts)
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
        return root

    def test_launcher_preserves_storage_and_adds_both_release_families(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.source('launcher', temporary)
            storage = ['crates/native/src/paths.rs', 'crates/native/src/self_update.rs', 'crates/native/src/single_instance.rs']
            before = {name: (root / name).read_bytes() for name in storage}
            changed = bogo.transform_launcher(root, {'id': 'launcher', 'bundleId': 'com.kio.launcher'})
            self.assertEqual(len(changed), 5)
            for name, data in before.items():
                self.assertEqual((root / name).read_bytes(), data)
            catalog = (root / changed[0]).read_text()
            for old in bogo.LEGACY_NAMES.values():
                self.assertIn('"' + old + '"', catalog)
            self.assertIn('"Bogo CAD"', catalog)
            registry = (root / 'crates/core/src/kio_registry.rs').read_text()
            self.assertIn('full_version.split_once("-bogo.").or_else(|| full_version.split_once("-kio."))', registry)
            self.assertIn('both_measured_release_families_remain_bound', registry)
            install = (root / 'crates/native/src/install.rs').read_text()
            self.assertIn('std::fs::rename(&backup, &old)', install)
            self.assertIn('previous application remains at', install)
            self.assertIn('app.legacy_name(), "KIO"', install)
            self.assertIn('app.name, "Bogo"', install)

    def test_light_preserves_old_candidate_tests_and_adds_bogo_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.source('light', temporary)
            paths = bogo.transform_light_editor_discovery(root)
            text = (root / paths[0]).read_text()
            self.assertIn('bogo_mac_candidates(env("HOME").as_deref()).into_iter().chain(mac_candidates', text)
            self.assertIn('KIO\\Photo', text)
            self.assertIn('Bogo Photo.exe', text)
            self.assertIn('windows_lookup_prefers_the_recorded_install_folder', text)
            self.assertIn('const PHOTOCRAFT_ID: &str = "com.kio.photo"', text)

    def test_pdf_manifest_and_comparator_keep_old_tests_and_add_new_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.source('pdf', temporary)
            paths = bogo.transform_pdf_updates(root)
            app, ui = [(root / name).read_text() for name in paths]
            self.assertIn('offers_only_the_exact_published_kio_pdf_release_page', app)
            self.assertIn('old_and_new_pdf_release_names_cannot_be_mixed', app)
            self.assertIn('Some("com.kio.pdf")', app)
            self.assertIn('/{tag}/{brand}-PDF-{version}-{suffix}', app)
            self.assertIn('kio_revisions_and_legacy_numeric_versions_keep_their_order', ui)
            self.assertIn('bogo_is_newer_than_every_kio_revision_of_the_same_upstream', ui)


if __name__ == '__main__':
    unittest.main()
