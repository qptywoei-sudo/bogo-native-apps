import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('full_native', SCRIPTS / 'full_native.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class FullNativeGuards(unittest.TestCase):
    def test_sound_windows_test_retains_diagnostic_without_moving_fixture(self):
        lock = builder.load_lock('sound')
        fixes = builder.functional_fixes(lock)
        self.assertEqual(len(fixes), 1)
        fix, meta = fixes[0]
        self.assertEqual([item['path'] for item in meta['files']], ['crates/engine/src/file_access.rs'])
        text = (builder.ROOT / fix['patch']).read_text()
        removed = [line[1:] for line in text.splitlines() if line.startswith('-') and not line.startswith('---')]
        added = [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
        self.assertEqual(len(removed), 1)
        self.assertEqual(added, [removed[0].replace('roots.check(upper,', 'roots.check(&upper,')])
        self.assertIn('roots.check(upper, Access::Read)', removed[0])
        self.assertEqual(meta['files'][0]['after']['bytes'], meta['files'][0]['before']['bytes'] + 1)
        for line in added + removed:
            self.assertNotIn('#[ignore]', line)
            self.assertNotIn('#[cfg', line)

    def test_effect_portability_fix_is_scoped_to_original_test_helpers_and_path_assertions(self):
        lock = builder.load_lock('effect')
        fixes = builder.functional_fixes(lock)
        self.assertEqual(len(fixes), 1)
        fix, meta = fixes[0]
        self.assertEqual(len(meta['files']), 6)
        text = (builder.ROOT / fix['patch']).read_text()
        removed = [line[1:] for line in text.splitlines() if line.startswith('-') and not line.startswith('---')]
        added = [line[1:] for line in text.splitlines() if line.startswith('+') and not line.startswith('+++')]
        self.assertEqual(len(removed), 6)
        self.assertEqual(len(added), 6)
        self.assertEqual(sum('target/test-out' in line for line in removed), 4)
        self.assertEqual(sum('std::env::temp_dir()' in line for line in added), 4)
        self.assertEqual(sum('assert' in line for line in removed), 2)
        self.assertEqual(sum('assert' in line for line in added), 2)
        self.assertNotIn('#[ignore]', '\n'.join(added))
        self.assertNotIn('#[cfg', '\n'.join(added))
        # This review does not authorize changes to production path discovery.
        with patch.object(builder, 'ROOT', builder.ROOT):
            tampered = json.loads(json.dumps(lock))
            tampered['id'] = 'cad'
            with self.assertRaisesRegex(ValueError, 'explicit application review'):
                builder.functional_fixes(tampered)

    def test_light_build_runs_original_engine_and_native_editor_discovery_tests(self):
        lock = builder.load_lock('light')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            binaries = {'app': work / 'lightcraft', 'cli': work / 'lightcraft-cli'}
            for path in binaries.values():
                path.write_bytes(b'native binary validation is tested separately')
            with patch.object(builder, 'assert_host'), patch.object(builder, 'prepared', return_value=(work, work / 'source', work / 'fonts', {})), patch.object(builder, 'build_env', return_value={}), patch.object(builder, 'run', return_value='rustc 1.95.0 (fixture)') as commands, patch.object(builder, 'binary_paths', return_value=binaries), patch.object(builder, 'check_versions', return_value={}), patch.object(builder, 'write_json'):
                builder.build(SimpleNamespace(platform='macos-arm64'), lock)
            tests = [call.args[0] for call in commands.call_args_list if 'test' in call.args[0]]
            self.assertEqual(len(tests), 2)
            for package in ('lightcraft-denoise-core', 'lightcraft-engine'):
                self.assertIn(package, tests[0])
            self.assertIn('editors::tests', tests[1])
            self.assertIn('lightcraft', tests[1])
            for command in tests:
                self.assertIn('--locked', command)
                self.assertIn('aarch64-apple-darwin', command)

    def test_light_format_literals_must_exist_in_all_original_catalogs(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for i in range(9):
                (source / f'{i}-formats.json').write_text(json.dumps({'Downloads from {host}. KIO Light installs it, {after}.': 'translated'}))
            code = source / 'panel.rs'
            code.write_text('// tr_format!("comment is not a call")\ntr_format!("Downloads from {host}. KIO Light installs it, {after}.", host = host, after = after);\n')
            self.assertEqual(builder.light_format_contract(source), {'catalogs': 9, 'keys': 1, 'literalCalls': 1})
            code.write_text('tr_format!("Downloads from {host}. LightCraft installs it, {after}.", host = host, after = after);\n')
            with self.assertRaisesRegex(ValueError, 'no catalog key'):
                builder.light_format_contract(source)
            code.write_text('tr_format!("Downloads from {host}. KIO Light installs it, {after}.");\n')
            (source / '0-formats.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'key sets diverged'):
                builder.light_format_contract(source)

    def test_pdf_build_runs_original_engine_and_both_native_update_boundaries(self):
        lock = builder.load_lock('pdf')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            binaries = {'app': work / 'pdfcraft', 'cli': work / 'pdfcraft-cli'}
            for path in binaries.values():
                path.write_bytes(b'native header inspection is covered separately')
            with patch.object(builder, 'assert_host'), patch.object(builder, 'prepared', return_value=(work, work / 'source', work / 'fonts', {})), patch.object(builder, 'build_env', return_value={'CRAFT_FONTS_REQUIRED': '1'}), patch.object(builder, 'run', return_value='rustc 1.95.0 (fixture)') as commands, patch.object(builder, 'binary_paths', return_value=binaries), patch.object(builder, 'check_versions', return_value={}), patch.object(builder, 'write_json'):
                builder.build(SimpleNamespace(platform='macos-arm64'), lock)
            tests = [call.args[0] for call in commands.call_args_list if 'test' in call.args[0]]
            self.assertEqual(len(tests), 3)
            self.assertIn('pdfcraft-engine', tests[0])
            self.assertIn('updates::tests', tests[1])
            self.assertIn('pdfcraft-ui-egui', tests[2])
            self.assertIn('updates::kio_version_tests', tests[2])
            for command in tests:
                self.assertIn('--locked', command)
                self.assertIn('aarch64-apple-darwin', command)

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

    def test_branding_preserves_original_rust_module_source_locations(self):
        # These identify source modules, not profile or application display names.
        # Replacing a crate directory here breaks the full native CLI on its target OS.
        literal = re.compile(r'^[-+]\s*#\[\s*path\s*=\s*"([^"\n]+)"\s*\]', re.M)
        for app in builder.IDS:
            lock = builder.load_lock(app)
            branding = (builder.ROOT / lock['branding']['patch']).read_text(encoding='utf-8')
            for section in re.split(r'(?=^diff --git )', branding, flags=re.M):
                header = section.split('\n', 1)[0]
                if not header.endswith('.rs'):
                    continue
                paths = literal.findall(section)
                with self.subTest(app=app, file=header):
                    self.assertEqual(paths, [], 'Branding must preserve original Rust module paths')

    def test_branding_keeps_real_upstream_documentation_urls(self):
        # Reverse-DNS bundle IDs are not GitHub repositories. A profile rename
        # must not also rename the target of an existing help/issues link.
        wrong = re.compile(r'https://(?:github\.com/storytold/|api\.github\.com/repos/storytold/)com\.kio\.')
        for app in builder.IDS:
            lock = builder.load_lock(app)
            patch_text = (builder.ROOT / lock['branding']['patch']).read_text(encoding='utf-8')
            added = '\n'.join(line[1:] for line in patch_text.splitlines() if line.startswith('+') and not line.startswith('+++'))
            with self.subTest(app=app):
                self.assertIsNone(wrong.search(added), 'Bundle IDs must not corrupt help or update repository URLs')

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
        deck = builder.load_lock('deck')
        env = builder.build_env(deck, Path('/fonts'), Path('/target'), 'aarch64-apple-darwin')
        self.assertEqual(env['KIO_RELEASE_VERSION'], deck['version'])
        self.assertEqual(env['DECKCRAFT_VERSION'], deck['version'])

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


class DesignSourceOnlyWorkflowGuards(unittest.TestCase):
    """Execute the actual matrix program without Rust, network or publication."""

    def workflow(self):
        return (builder.ROOT / '.github/workflows/full-native-apps.yml').read_text(encoding='utf-8')

    def select(self, app='design', platform='source', publish='false'):
        import subprocess
        import textwrap
        workflow = self.workflow()
        programs = re.findall(r"          python3 - <<'PY'\n(.*?)\n          PY", workflow, re.S)
        self.assertEqual(len(programs), 1)
        apps = builder.IDS if app == 'all' else (app,)
        rows = [{'app': selected, 'platform': target, 'runner': runner}
                for selected in apps
                for target, runner in (('macos-arm64', 'macos-14'), ('windows-x64', 'windows-2022'))]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'outputs'
            env = {'KIO_SELECTED_APP': app, 'KIO_SELECTED_PLATFORM': platform,
                   'KIO_DRAFT_PUBLICATION': publish, 'GITHUB_OUTPUT': str(output)}
            with patch.dict(os.environ, env), patch.object(subprocess, 'check_output', return_value=json.dumps({'include': rows})) as commands:
                exec(compile(textwrap.dedent(programs[0]), '<actual-workflow-matrix>', 'exec'), {})
            commands.assert_called_once_with(['python3', 'scripts/full_native.py', 'matrix', '--app', app], text=True)
            return {key: json.loads(value) for key, value in
                    (line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines())}

    def test_source_only_selects_design_and_skips_both_native_runners(self):
        selected = self.select()
        self.assertEqual(selected['source'], {'app': ['design']})
        # Retain a valid nonempty matrix; the job-level condition skips every
        # native runner instead of submitting an empty GitHub Actions matrix.
        self.assertEqual({row['platform'] for row in selected['native']['include']}, {'macos-arm64', 'windows-x64'})
        self.assertEqual({row['app'] for row in selected['native']['include']}, {'design'})
        workflow = self.workflow()
        native = workflow.split('\n  native:\n', 1)[1].split('\n  full-source:\n', 1)[0]
        self.assertRegex(native, r"(?m)^    if: inputs\.platform != 'source'$")
        self.assertIn('python3 -m unittest discover -s tests -v', workflow)
        source = workflow.split('\n  full-source:\n', 1)[1].split('\n  publish-draft:\n', 1)[0]
        self.assertIn('scripts/full_native.py source --app ${{ matrix.app }}', source)
        self.assertIn('scripts/full_native.py verify --app ${{ matrix.app }} --platform source', source)
        self.assertNotRegex(source, r'(?m)^\s*run:.*(?:rustup|cargo|publish-draft|scripts/full_native.py build)')
        self.assertIn("inputs.publish_draft && github.ref == 'refs/heads/main'", workflow)

    def test_source_only_rejects_another_app_or_all_apps(self):
        for app in builder.IDS + ('all',):
            if app == 'design':
                continue
            with self.subTest(app=app), self.assertRaisesRegex(AssertionError, 'Source-only selection is reviewed only for Design'):
                self.select(app=app)

    def test_source_only_cannot_publish_or_accept_invalid_inputs(self):
        for publish in ('true', 'yes', ''):
            with self.subTest(publish=publish), self.assertRaises(AssertionError):
                self.select(publish=publish)
        with self.assertRaisesRegex(AssertionError, 'Invalid native platform'):
            self.select(platform='source-other')

    def test_existing_native_platforms_and_all_apps_keep_their_matrices(self):
        for app in builder.IDS + ('all',):
            expected_apps = list(builder.IDS) if app == 'all' else [app]
            for platform in ('all', 'macos-arm64', 'windows-x64'):
                with self.subTest(app=app, platform=platform):
                    selected = self.select(app=app, platform=platform)
                    self.assertEqual(selected['source'], {'app': expected_apps})
                    self.assertEqual(len(selected['native']['include']), len(expected_apps) * (2 if platform == 'all' else 1))
                    if platform != 'all':
                        self.assertEqual({row['platform'] for row in selected['native']['include']}, {platform})
        self.assertEqual(len(self.select(platform='all', publish='true')['native']['include']), 2)
        for platform in ('macos-arm64', 'windows-x64'):
            with self.assertRaisesRegex(AssertionError, 'Draft publication requires both native platforms'):
                self.select(platform=platform, publish='true')

    def test_reproducible_source_contains_exact_design_inspector_inputs(self):
        selected = dict(builder.public_files(builder.load_lock('design')))
        required = {'scripts/inspect_design_winit.py', 'tests/test_winit_windows_license.py',
                    'tests/fixtures/winit-LICENSE.txt.b64', 'scripts/full_native.py',
                    'scripts/kio_native.py', 'tests/test_full_native.py',
                    '.github/workflows/full-native-apps.yml'}
        self.assertTrue(required <= selected.keys())
        self.assertTrue(all(selected[name].is_file() and not selected[name].is_symlink() for name in required))
        # The build source closure does not authorize a new publishing surface.
        self.assertTrue({'scripts/publish_design.py', 'tests/test_publish_design.py',
                         '.github/workflows/publish-design.yml'}.isdisjoint(selected))


if __name__ == '__main__':
    unittest.main()
