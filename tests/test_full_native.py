import importlib.util
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('full_native', SCRIPTS / 'full_native.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class FullNativeGuards(unittest.TestCase):
    def test_functional_engine_fix_requires_separate_hash_locked_narrow_scope(self):
        lock = builder.load_lock('word')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'patches/word'
            folder.mkdir(parents=True)
            patch_file = folder / 'functional-fixture.patch'
            patch_file.write_bytes(b'reviewed patch fixture')
            manifest = folder / 'functional-fixture.json'
            meta = {'schema':'kio.native-functional-patch.v1','programId':'word','upstream':{'commit':lock['source']['commit']},
                    'base':{'brandingPatchSha256':lock['branding']['sha256']},
                    'patch':{'sha256':builder.digest(patch_file),'bytes':patch_file.stat().st_size},
                    'files':[{'path':'crates/engine/src/io.rs','before':None,'after':None}]}
            manifest.write_text(json.dumps(meta))
            fix = {'patch':patch_file.relative_to(root).as_posix(),'sha256':builder.digest(patch_file),
                   'manifest':manifest.relative_to(root).as_posix(),'manifestSha256':builder.digest(manifest)}
            lock['functionalFixes'] = [fix]
            with patch.object(builder,'ROOT',root):
                self.assertEqual(len(builder.functional_fixes(lock)),1)
                meta['files'][0]['path']='Cargo.lock'
                manifest.write_text(json.dumps(meta))
                fix['manifestSha256']=builder.digest(manifest)
                with self.assertRaises(ValueError):builder.functional_fixes(lock)
                patch_file.write_bytes(b'changed after review')
                with self.assertRaises(ValueError):builder.functional_fixes(lock)

    def test_all_original_app_and_cli_and_patch_inputs_are_locked(self):
        self.assertEqual(len(builder.IDS), 13)
        for app in builder.IDS:
            with self.subTest(app=app):
                lock = builder.load_lock(app)
                self.assertEqual(len(lock['cargoPackages']), 2)
                self.assertIn('--locked', lock['cargoArgs'])
                self.assertNotIn('--no-default-features', lock['cargoArgs'])
                self.assertTrue(lock['testPackages'])
                self.assertNotIn('Electron', lock['binaries']['app'])

    def test_required_heif_is_in_full_gui_and_cli_build(self):
        photo = builder.load_lock('photo')
        light = builder.load_lock('light')
        self.assertEqual(photo['cargoArgs'][-2:], ['--features', 'heif'])
        self.assertEqual(light['cargoArgs'][-2:], ['--features', 'lightcraft/heif,lightcraft-cli/heif'])
        self.assertIn('denoise', light['features']['appDefaultFeatures'])

    def test_source_and_patch_tampering_or_feature_removal_is_refused(self):
        original = json.loads(builder.CATALOG.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'catalog.json'
            for mutate in ['feature', 'url', 'patch']:
                value = json.loads(json.dumps(original))
                app = next(x for x in value['applications'] if x['id'] == 'photo')
                if mutate == 'feature': app['cargoArgs'] += ['--no-default-features']
                if mutate == 'url': app['source']['url'] = 'https://attacker.invalid/source.tar.gz'
                if mutate == 'patch': app['branding']['sha256'] = '0' * 64
                path.write_text(json.dumps(value))
                with patch.object(builder, 'CATALOG', path), self.assertRaises(ValueError):
                    builder.load_lock('photo')

    def test_explicit_original_no_extra_fonts_and_target_static_crt(self):
        lock = builder.load_lock('sound')
        with patch.dict(os.environ, {'CRAFT_FONTS_DIR': '/unrelated', 'CRAFT_FONTS_REQUIRED': '1'}):
            env = builder.build_env(lock, Path('/fonts'), Path('/target'), 'x86_64-pc-windows-msvc')
        self.assertNotIn('CRAFT_FONTS_DIR', env)
        self.assertEqual(env['CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS'], '-C target-feature=+crt-static')
        self.assertEqual(env['SOUNDCRAFT_REQUIRE_WINRES'], '1')
        self.assertNotIn('RUSTFLAGS', {k: v for k, v in env.items() if k not in os.environ})
        lock = builder.load_lock('grid')
        env = builder.build_env(lock, Path('/fonts'), Path('/target'), 'aarch64-apple-darwin')
        self.assertEqual(env['CRAFT_FONTS_REQUIRED'], '1')
        self.assertEqual(env['GRIDCRAFT_BUILD_SHA'], lock['source']['commit'])

    def test_msi_preserves_original_installer_and_adds_all_legal_files_once(self):
        lock = builder.load_lock('grid')
        original = '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs"><Package><Feature Id="Main"><ComponentGroupRef Id="OriginalEngine" /></Feature></Package></Wix>'
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'license.txt').write_text('original license')
            (folder / 'font').mkdir()
            (folder / 'font/OFL.txt').write_text('font license')
            (folder / 'font/NOTICE.txt').write_text('font notice')
            text, count = builder.add_msi_notices(original, lock, folder)
            root = ET.fromstring(text)
            ns = {'w': 'http://wixtoolset.org/schemas/v4/wxs'}
            self.assertEqual(count, 3)
            self.assertIsNotNone(root.find('.//w:ComponentGroupRef[@Id="OriginalEngine"]', ns))
            self.assertEqual(len(root.findall('.//w:File', ns)), 3)
            ids = [x.attrib['Id'] for x in root.findall('.//w:Directory', ns)]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(text, builder.add_msi_notices(original, lock, folder)[0])

    def test_pdf_requires_original_model_and_license_sidecars(self):
        lock = builder.load_lock('pdf')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch.object(builder, 'run') as command, self.assertRaises(ValueError):
                builder.stage_extras(lock, folder, folder, {})
            self.assertEqual(command.call_args.args[0][:6], ['rustup', 'run', '1.95.0', 'cargo', 'xtask', 'models'])
            models = folder / 'models'
            models.mkdir()
            (models / 'ATTRIBUTION.txt').write_text('original model attribution')
            (models / 'ocr.LICENCE.txt').write_text('model license')
            (models / 'ocr.rten').write_bytes(b'model fixture')
            with patch.object(builder, 'run'):
                files = builder.stage_extras(lock, folder, folder, {})
            self.assertEqual(len(files), 3)
            self.assertTrue(all(len(x['sha256']) == 64 for x in files))

    def test_per_app_release_does_not_accept_another_app_artifact_or_extra_file(self):
        lock = builder.load_lock('grid')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            base = builder.artifact_base(lock, 'windows-x64')
            for suffix in ('.zip', '.msi', '-provenance.json'):
                (folder / (base + suffix)).write_bytes(b'fixture')
            builder.finalize(folder, lock, 'windows-x64')
            self.assertEqual(len(builder.verify(folder, lock, 'windows-x64')), 5)
            with self.assertRaises(ValueError):
                builder.verify(folder, builder.load_lock('deck'), 'windows-x64')
            (folder / 'private.txt').write_text('not in artifact allowlist')
            with self.assertRaises(ValueError):
                builder.verify(folder, lock, 'windows-x64')

    def test_each_version_contract_is_exact_and_branded_gui_is_not_confused_with_cli(self):
        for app in builder.IDS:
            lock = builder.load_lock(app)
            binaries = {'app': Path('/native-gui'), 'cli': Path('/native-cli')}
            expected = {key: name + ' ' + lock['upstreamVersion'] for key, name in lock['versionOutputNames'].items()}
            with patch.object(builder.sys, 'platform', 'darwin'), patch.object(builder, 'run', side_effect=lambda command, **kw: expected['app' if command[0] == binaries['app'] else 'cli']):
                self.assertEqual(builder.check_versions(lock, binaries, {}), expected)
            wrong = 'Other App ' + lock['upstreamVersion']
            with patch.object(builder.sys, 'platform', 'darwin'), patch.object(builder, 'run', return_value=wrong), self.assertRaises(ValueError):
                builder.check_versions(lock, binaries, {})
        self.assertEqual(builder.load_lock('sound')['versionOutputNames']['cli'], 'SoundCraft CLI')
        self.assertEqual(builder.load_lock('grid')['versionOutputNames']['app'], 'KIO Grid')

    def test_windows_film_checks_native_resource_without_opening_original_modal_dialog(self):
        lock = builder.load_lock('film')
        binaries = {'app': Path('/film.exe'), 'cli': Path('/film-cli.exe')}
        with patch.object(builder.sys, 'platform', 'win32'), patch.object(builder, 'check_windows_gui_resource', return_value={'mode': 'native-pe-version-resource'}) as resource, patch.object(builder, 'run', return_value='filmcraft-cli ' + lock['upstreamVersion']) as command:
            result = builder.check_versions(lock, binaries, {})
            self.assertEqual(result['app']['mode'], 'native-pe-version-resource')
            self.assertEqual(resource.call_count, 1)
            self.assertEqual(command.call_args.args[0], [binaries['cli'], '--version'])
        for product, version in [('Wrong Product', lock['upstreamVersion']), (lock['name'], '99.0.0')]:
            with patch.object(builder, 'run', return_value=json.dumps({'ProductName': product, 'ProductVersion': version, 'FileVersion': version})), self.assertRaises(ValueError):
                builder.check_windows_gui_resource(lock, binaries['app'], {})

    def test_only_exact_public_upstream_fixtures_bypass_build_or_key_filename_guard(self):
        film = builder.load_lock('film')
        pdf = builder.load_lock('pdf')
        for lock in (film, pdf):
            validator = builder.source_validator(lock)
            self.assertTrue(lock['originalArchivePathExceptions'])
            self.assertEqual(str(validator(lock['originalArchivePathExceptions'][0]['path'])), lock['originalArchivePathExceptions'][0]['path'])
            for bad in ('target/release/app', 'crates/else/target/file', 'crates/sign/tests/data/user.p12', '.env', '../../escape'):
                with self.subTest(app=lock['id'], bad=bad), self.assertRaises(ValueError):
                    validator(bad)
        with self.assertRaises(ValueError):
            builder.common.check_public_path(film['originalArchivePathExceptions'][0]['path'])

    def test_source_allowlist_is_only_explicit_public_files(self):
        selected = list(builder.public_files(builder.load_lock('grid')))
        for relative, path in selected:
            builder.common.check_public_path(relative)
            self.assertTrue(path.is_file())
            self.assertFalse(relative.startswith(('.work/', '.cache/', 'dist/')))


if __name__ == '__main__':
    unittest.main()
