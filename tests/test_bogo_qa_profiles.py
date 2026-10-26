"""Opt-in profile isolation and non-signalling Launcher regression checks."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bogo_qa_profiles as qa


class QAProfileContracts(unittest.TestCase):
    def test_unreviewed_sources_are_refused(self):
        for value in ("absent", "twice twice"):
            with self.assertRaises(ValueError):
                qa.replace_once(value, "twice", "updated")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(qa.transform_qa_source(root, "grid"), [])
            self.assertEqual(list(root.iterdir()), [])

    def test_helpers_never_change_platform_profile_environment_or_use_unsafe(self):
        for app in qa.APPS:
            text = qa.helper(app)
            self.assertNotIn("set_var", text)
            self.assertNotIn('var_os("HOME")', text)
            self.assertNotIn("unsafe", text)
            self.assertIn('const APP: &str = "' + app + '"', text)
            self.assertIn('std::env::var_os("BOGO_QA_MODE")', text)
            self.assertIn('std::env::var_os("BOGO_QA_ROOT")', text)
            self.assertIn("std::process::exit(2)", text)
            self.assertIn('#[cfg(target_arch = "wasm32")]', text)


@unittest.skipUnless(shutil.which("rustc"), "rustc required for actual standalone QA runtime checks")
class QARustRuntime(unittest.TestCase):
    def compile(self, root, source, name, test=False):
        path = root / (name + ".rs")
        path.write_text(source)
        exe = root / (name + (".exe" if os.name == "nt" else ""))
        command = ["rustc", "--edition", "2024", str(path), "-o", str(exe)]
        if test:
            command.insert(1, "--test")
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        return exe

    def environment(self, **values):
        env = os.environ.copy()
        env.pop("BOGO_QA_MODE", None)
        env.pop("BOGO_QA_ROOT", None)
        env.update(values)
        return env

    def test_compiled_helpers_validate_owned_paths_and_refuse_busy_launcher_without_signalling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for app in ("cad", "launcher"):
                exe = self.compile(root, qa.helper(app), "qa-tests-" + app, test=True)
                result = subprocess.run([str(exe), "--test-threads=1"], env=self.environment(), text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn("0 failed", result.stdout)
                self.assertNotIn("ignored, 1 filtered out", result.stdout)

    def test_actual_invalid_qa_start_exits_before_default_path_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "qa.rs").write_text(qa.helper("cad"))
            source = '''mod qa;
fn main() {
    match qa::path("profile/app.ron") {
        Some(path) => println!("qa:{}", path.display()),
        None => println!("ordinary-default-unchanged"),
    }
}
'''
            exe = self.compile(root, source, "probe")
            default = subprocess.run([str(exe)], env=self.environment(), text=True, capture_output=True)
            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertEqual(default.stdout.strip(), "ordinary-default-unchanged")
            absent = root / "not-created-on-invalid-start"
            for values in ({"BOGO_QA_MODE": "1"}, {"BOGO_QA_ROOT": str(absent)},
                           {"BOGO_QA_MODE": "0", "BOGO_QA_ROOT": str(absent)},
                           {"BOGO_QA_MODE": "1", "BOGO_QA_ROOT": "relative"}):
                result = subprocess.run([str(exe)], env=self.environment(**values), text=True, capture_output=True)
                self.assertEqual(result.returncode, 2, (values, result.stderr))
                self.assertNotIn("ordinary-default", result.stdout)
                self.assertIn("QA profile refused", result.stderr)
                self.assertFalse(absent.exists())
            owned = root / "owned-task-root"
            result = subprocess.run([str(exe)], env=self.environment(BOGO_QA_MODE="1", BOGO_QA_ROOT=str(owned)),
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "qa:" + str(owned.resolve() / "cad/profile/app.ron"))
            self.assertTrue((owned / "cad").is_dir())
            self.assertFalse((owned / "cad/profile/app.ron").exists())


@unittest.skipUnless(os.environ.get("BOGO_NATIVE_ARCHIVES"), "set BOGO_NATIVE_ARCHIVES for exact legacy source integration checks")
class PublishedSourceQAProfiles(unittest.TestCase):
    def source(self, app, temporary):
        archives = list((Path(os.environ["BOGO_NATIVE_ARCHIVES"]) / app).glob("*-source.zip"))
        self.assertEqual(len(archives), 1)
        root = Path(temporary)
        with zipfile.ZipFile(archives[0]) as archive:
            for name in archive.namelist():
                if not name.endswith(".rs") or "/orchestrator/" in name:
                    continue
                relative = Path(*Path(name).parts[1:])
                self.assertNotIn("..", relative.parts)
                out = root / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(archive.read(name))
        return root

    def test_all_five_profiles_cover_real_native_persistence_without_changing_defaults(self):
        contracts = {
            "cad": [("apps/cadcraft/src/main.rs", 'persistence_path: bogo_qa::path("profile/app.ron")'),
                    ("apps/cadcraft/src/main.rs", 'bogo_qa::path("profile")'),
                    ("apps/cadcraft/src/workspace.rs", 'crate::bogo_qa::path("profile").or_else')],
            "pdf": [("apps/pdfcraft/src/main.rs", 'pdfcraft_ui_egui::bogo_qa::path("profile")'),
                    ("apps/pdfcraft/src/main.rs", 'if pdfcraft_ui_egui::bogo_qa::root().is_some() { return; }'),
                    ("apps/pdfcraft/src/single_instance.rs", 'if pdfcraft_ui_egui::bogo_qa::root().is_some() { return Claim::Alone; }'),
                    ("crates/ui-egui/src/recovery.rs", 'crate::bogo_qa::path("recovery")'),
                    ("crates/ui-egui/src/image_pick.rs", 'crate::bogo_qa::path("cache/clipboard")')],
            "ui": [("apps/figcraft/src/services.rs", 'crate::bogo_qa::path("profile")'),
                   ("apps/figcraft/src/main.rs", 'if bogo_qa::root().is_some() { None } else { figcraft_collab_net::links::system() }')],
            "deck": [("apps/deckcraft/src/main.rs", 'bogo_qa::path("profile")'),
                     ("apps/deckcraft/src/main.rs", 'bogo_qa::path("recovery").or_else(deckcraft_engine::recovery::default_dir)')],
            "launcher": [("crates/native/src/paths.rs", 'crate::bogo_qa::root()'),
                         ("apps/artcraft-launcher/src/settings_file.rs", 'bogo_qa::path("settings/app.ron")'),
                         ("apps/artcraft-launcher/src/main.rs", 'persistence_path: artcraft_launcher_native::bogo_qa::path("settings/app.ron")'),
                         ("crates/native/src/single_instance.rs", 'crate::bogo_qa::launcher_listener(addr)')],
        }
        for app in sorted(qa.APPS):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as temporary:
                root = self.source(app, temporary)
                before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.rs")}
                changed = qa.transform_qa_source(root, app)
                self.assertTrue(changed)
                self.assertFalse(any(path.startswith("crates/engine/") for path in changed))
                for relative, marker in contracts[app]:
                    self.assertIn(marker, (root / relative).read_text())
                if app == "pdf":
                    # The QA overlay preserves the historical normal settings identity.
                    text = (root / "apps/pdfcraft/src/main.rs").read_text()
                    self.assertIn('eframe::storage_dir("KIO PDF")', text)
                if app == "launcher":
                    text = (root / "crates/native/src/single_instance.rs").read_text()
                    self.assertLess(text.index("crate::bogo_qa::launcher_listener(addr)"), text.index("match ask(addr"))
                    for old in ('const PORT: u16 = 47_514;', 'b"kio-launcher:show"', '"kio-launcher:hello "'):
                        self.assertIn(old, text)
                    self.assertIn('const DIR: &str = "com.kio.launcher"', (root / "crates/native/src/paths.rs").read_text())
                # Every untouched upstream file remains byte-identical.
                for relative, content in before.items():
                    if relative not in changed:
                        self.assertEqual((root / relative).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
