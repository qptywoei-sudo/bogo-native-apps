"""Opt-in native UI verification profiles, without changing normal identities.

Applied by the overlay recorder after the ordinary Bogo transforms. Runtime QA
requires both BOGO_QA_MODE=1 and a private absolute BOGO_QA_ROOT. Neither normal
launches nor missing/invalid QA configuration may silently use a test profile.
The helper never changes HOME or another platform profile environment variable.
"""

from pathlib import Path


APPS = {"cad", "pdf", "ui", "deck", "launcher"}


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Unreviewed QA profile source contract: " + before[:110])
    return text.replace(before, after, 1)


COMMON = r'''//! Explicit, private QA profiles. Normal storage identities stay unchanged.
#![allow(dead_code)]

use std::ffi::OsString;
use std::path::{Component, Path, PathBuf};

const APP: &str = "__APP__";

/// A pure parser, also used by tests: partial opt-in always fails closed.
fn resolve(mode: Option<OsString>, base: Option<OsString>) -> Result<Option<PathBuf>, String> {
    if mode.is_none() && base.is_none() {
        return Ok(None);
    }
    if mode.as_deref() != Some(std::ffi::OsStr::new("1")) {
        return Err("BOGO_QA_MODE must equal 1 when QA settings are supplied".into());
    }
    let base = base.filter(|value| !value.is_empty()).ok_or("BOGO_QA_ROOT is required in QA mode")?;
    let base = PathBuf::from(base);
    if !base.is_absolute()
        || base.components().any(|part| matches!(part, Component::ParentDir))
        || !base.components().any(|part| matches!(part, Component::Normal(_)))
    {
        return Err("BOGO_QA_ROOT must be an absolute task directory without parent traversal".into());
    }
    Ok(Some(base))
}

#[cfg(not(target_arch = "wasm32"))]
fn private_directory(path: &Path) -> Result<(), String> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            return Err("QA directory is a link or is not a directory".into());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let mut builder = std::fs::DirBuilder::new();
            builder.recursive(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::DirBuilderExt;
                builder.mode(0o700);
            }
            builder.create(path).map_err(|error| format!("cannot create QA directory: {error}"))?;
        }
        Err(error) => return Err(format!("cannot inspect QA directory: {error}")),
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|error| format!("cannot inspect QA directory: {error}"))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err("QA directory changed into a link or a file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err("QA directory must be private to its owner (mode 0700)".into());
        }
    }
    Ok(())
}

#[cfg(not(target_arch = "wasm32"))]
fn owned_root(base: &Path) -> Result<PathBuf, String> {
    private_directory(base)?;
    let base = std::fs::canonicalize(base).map_err(|error| format!("cannot resolve QA directory: {error}"))?;
    let app = base.join(APP);
    private_directory(&app)?;
    Ok(app)
}

#[cfg(not(target_arch = "wasm32"))]
fn refuse(message: &str) -> ! {
    eprintln!("Bogo QA profile refused: {message}");
    std::process::exit(2)
}

/// None only for a completely ordinary launch. Invalid QA settings exit before
/// the caller can fall back to personal preferences, recovery, logs or caches.
#[cfg(not(target_arch = "wasm32"))]
pub fn root() -> Option<PathBuf> {
    static ROOT: std::sync::OnceLock<Option<PathBuf>> = std::sync::OnceLock::new();
    ROOT.get_or_init(|| {
        match resolve(std::env::var_os("BOGO_QA_MODE"), std::env::var_os("BOGO_QA_ROOT")) {
            Ok(Some(base)) => Some(owned_root(&base).unwrap_or_else(|error| refuse(&error))),
            Ok(None) => None,
            Err(error) => refuse(&error),
        }
    }).clone()
}

/// Browser builds retain their existing browser storage and do not read native
/// process environment variables or create host directories.
#[cfg(target_arch = "wasm32")]
pub fn root() -> Option<PathBuf> {
    None
}

pub fn path(relative: &str) -> Option<PathBuf> {
    root().map(|root| {
        let relative = Path::new(relative);
        if relative.as_os_str().is_empty() || relative.components().any(|part| !matches!(part, Component::Normal(_))) {
            #[cfg(not(target_arch = "wasm32"))]
            refuse("invalid internal QA path");
        }
        root.join(relative)
    })
}

#[cfg(test)]
mod qa_profile_tests {
    use super::*;

    #[test]
    fn ordinary_launch_has_no_qa_profile() {
        assert_eq!(resolve(None, None), Ok(None));
    }

    #[test]
    fn partial_invalid_and_relative_configuration_never_fall_back() {
        for (mode, root) in [
            (Some("1"), None), (None, Some("/private/qa")),
            (Some("0"), Some("/private/qa")), (Some("true"), Some("/private/qa")),
            (Some("1"), Some("")), (Some("1"), Some("relative")),
            (Some("1"), Some("/")), (Some("1"), Some("/private/qa/../user")),
        ] {
            assert!(resolve(mode.map(OsString::from), root.map(OsString::from)).is_err());
        }
    }

    #[test]
    fn complete_configuration_is_explicit_and_keeps_the_app_namespace() {
        let absolute = std::env::temp_dir().join("bogo-qa-parser");
        assert_eq!(resolve(Some("1".into()), Some(absolute.as_os_str().into())), Ok(Some(absolute.clone())));
    }

    #[cfg(not(target_arch = "wasm32"))]
    #[test]
    fn owned_paths_are_private_and_links_or_existing_public_roots_are_refused() {
        let base = std::env::temp_dir().join(format!("bogo-qa-profile-{}-{}", APP, std::process::id()));
        assert!(!base.exists());
        let app = owned_root(&base).expect("fresh private QA root");
        assert_eq!(app, std::fs::canonicalize(&base).expect("QA base").join(APP));
        assert!(app.is_dir());
        #[cfg(unix)]
        {
            use std::os::unix::fs::{PermissionsExt, symlink};
            assert_eq!(std::fs::metadata(&base).expect("QA metadata").permissions().mode() & 0o777, 0o700);
            let link = base.with_extension("link");
            symlink(&base, &link).expect("QA link fixture");
            assert!(owned_root(&link).is_err());
            std::fs::remove_file(&link).expect("remove own link");
            std::fs::set_permissions(&base, std::fs::Permissions::from_mode(0o755)).expect("public fixture");
            assert!(owned_root(&base).is_err());
            std::fs::set_permissions(&base, std::fs::Permissions::from_mode(0o700)).expect("restore own fixture");
        }
        std::fs::remove_dir_all(&base).expect("remove own fixture");
    }
}
'''


LAUNCHER = r'''
/// QA must never ask an installed launcher to show, quit, or replace itself.
/// Query process names only; no process is signalled and no existing socket is
/// contacted. Query failure is a refusal, rather than permission to continue.
pub fn launcher_listener(addr: std::net::SocketAddr) -> Result<std::net::TcpListener, String> {
    let output = {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let executable = std::env::var_os("SystemRoot").map_or_else(|| PathBuf::from(r"C:\Windows"), PathBuf::from).join(r"System32\tasklist.exe");
            std::process::Command::new(executable).args(["/FO", "CSV", "/NH"]).creation_flags(0x08000000).output()
        }
        #[cfg(not(windows))]
        {
            std::process::Command::new("/bin/ps").args(["-axo", "pid=,comm="]).output()
        }
    }.map_err(|error| format!("cannot inspect existing Launcher processes: {error}"))?;
    if !output.status.success() {
        return Err("cannot inspect existing Launcher processes".into());
    }
    let text = String::from_utf8(output.stdout).map_err(|_| "unreadable Launcher process list")?;
    refuse_other_launchers(&text, std::process::id(), cfg!(windows))?;
    qa_bind(addr)
}

fn launcher_name(name: &str) -> bool {
    let name = name.rsplit(['/', '\\']).next().unwrap_or(name).to_ascii_lowercase();
    matches!(name.as_str(), "bogo launcher" | "kio launcher" | "artcraft-launcher" |
        "bogo launcher.exe" | "kio launcher.exe" | "artcraft-launcher.exe")
}

fn refuse_other_launchers(text: &str, ours: u32, windows: bool) -> Result<(), String> {
    let mut seen = false;
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let (pid, name) = if windows {
            let fields: Vec<_> = line.trim().trim_matches('"').split("\",\"").collect();
            if fields.len() < 2 {
                return Err("unreadable Launcher process row".into());
            }
            (fields[1].parse::<u32>().map_err(|_| "unreadable Launcher process id")?, fields[0])
        } else {
            let line = line.trim_start();
            let (pid, name) = line.split_once(char::is_whitespace).ok_or("unreadable Launcher process row")?;
            (pid.parse::<u32>().map_err(|_| "unreadable Launcher process id")?, name.trim())
        };
        seen = true;
        if pid != ours && launcher_name(name) {
            return Err("another Launcher process is running; QA will not signal or replace it".into());
        }
    }
    if !seen {
        return Err("empty Launcher process list".into());
    }
    Ok(())
}

fn qa_bind(addr: std::net::SocketAddr) -> Result<std::net::TcpListener, String> {
    std::net::TcpListener::bind(addr).map_err(|_| "Launcher instance port is occupied; QA will not contact or replace its owner".into())
}

#[cfg(test)]
mod qa_launcher_tests {
    use super::*;

    #[test]
    fn process_guard_excludes_only_itself_and_refuses_old_and_new_launchers() {
        assert!(refuse_other_launchers("42 /tmp/Bogo Launcher\n43 /usr/bin/python3\n", 42, false).is_ok());
        for name in ["/Applications/KIO Launcher.app/Contents/MacOS/KIO Launcher", "/tmp/Bogo Launcher", "/tmp/artcraft-launcher"] {
            assert!(refuse_other_launchers(&format!("42 /tmp/Bogo Launcher\n43 {name}\n"), 42, false).is_err());
        }
        assert!(refuse_other_launchers("\"Bogo Launcher.exe\",\"42\",\"Console\"", 42, true).is_ok());
        assert!(refuse_other_launchers("\"KIO Launcher.exe\",\"43\",\"Console\"", 42, true).is_err());
        assert!(refuse_other_launchers("", 42, false).is_err());
        assert!(refuse_other_launchers("unreadable", 42, false).is_err());
    }

    #[test]
    fn occupied_port_is_refused_without_any_connection_or_handshake() {
        let owner = std::net::TcpListener::bind("127.0.0.1:0").expect("own socket fixture");
        owner.set_nonblocking(true).expect("nonblocking own fixture");
        let addr = owner.local_addr().expect("fixture address");
        assert!(qa_bind(addr).is_err());
        assert!(matches!(owner.accept(), Err(error) if error.kind() == std::io::ErrorKind::WouldBlock));
        drop(owner);
        let ours = qa_bind(addr).expect("free port can be owned by QA");
        assert_eq!(ours.local_addr().expect("QA address"), addr);
    }
}
'''


def helper(app):
    if app not in APPS:
        raise ValueError("Unsupported QA profile app: " + app)
    return COMMON.replace("__APP__", app) + (LAUNCHER if app == "launcher" else "")


def transform_qa_source(source, app):
    """Return every changed/new source path; reject unexpected source contracts."""
    if app not in APPS:
        return []
    source = Path(source)
    changed = []

    def edit(relative, transform):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing regular QA source: " + relative)
        before = path.read_text(encoding="utf-8")
        after = transform(before)
        if before == after:
            raise ValueError("QA overlay made no change: " + relative)
        path.write_text(after, encoding="utf-8")
        changed.append(relative)

    def add(relative):
        path = source / relative
        if path.exists() or path.is_symlink():
            raise ValueError("QA helper already exists: " + relative)
        path.write_text(helper(app), encoding="utf-8")
        changed.append(relative)

    def early(text, signature, expression):
        return replace_once(text, signature, signature + "\n    let _ = " + expression + ";")

    if app == "cad":
        add("apps/cadcraft/src/bogo_qa.rs")
        def cad_main(text):
            text = replace_once(text, "mod control_server;", "mod bogo_qa;\nmod control_server;")
            text = early(text, "fn main() -> eframe::Result {", "bogo_qa::root()")
            text = replace_once(text, "fn config_dir() -> Option<std::path::PathBuf> {", "fn config_dir() -> Option<std::path::PathBuf> {\n    if let Some(path) = bogo_qa::path(\"profile\") { return Some(path); }")
            return replace_once(text, "        persist_window: false,", "        persistence_path: bogo_qa::path(\"profile/app.ron\"),\n        persist_window: false,")
        edit("apps/cadcraft/src/main.rs", cad_main)
        edit("apps/cadcraft/src/workspace.rs", lambda text: replace_once(text,
            'Self::at(config_dir_from(std::env::consts::OS, |key| std::env::var_os(key)).map(|root| root.join("workspace.json")))',
            'Self::at(crate::bogo_qa::path("profile").or_else(|| config_dir_from(std::env::consts::OS, |key| std::env::var_os(key))).map(|root| root.join("workspace.json")))'))

    elif app == "pdf":
        add("crates/ui-egui/src/bogo_qa.rs")
        edit("crates/ui-egui/src/lib.rs", lambda text: replace_once(text, "mod a11y_ui;", "pub mod bogo_qa;\nmod a11y_ui;"))
        def pdf_main(text):
            text = early(text, "fn main() -> eframe::Result {", "pdfcraft_ui_egui::bogo_qa::root()")
            text = replace_once(text, "fn settings_dir() -> Option<std::path::PathBuf> {", "fn settings_dir() -> Option<std::path::PathBuf> {\n    if let Some(path) = pdfcraft_ui_egui::bogo_qa::path(\"profile\") { return Some(path); }")
            return replace_once(text, "fn migrate_legacy_folders() {", "fn migrate_legacy_folders() {\n    if pdfcraft_ui_egui::bogo_qa::root().is_some() { return; }")
        edit("apps/pdfcraft/src/main.rs", pdf_main)
        edit("apps/pdfcraft/src/single_instance.rs", lambda text: replace_once(text,
            "pub fn claim(files: &[String], may_hand_off: bool) -> Claim {",
            "pub fn claim(files: &[String], may_hand_off: bool) -> Claim {\n    if pdfcraft_ui_egui::bogo_qa::root().is_some() { return Claim::Alone; }"))
        edit("crates/ui-egui/src/recovery.rs", lambda text: replace_once(text, "    pub fn default_dir() -> Option<PathBuf> {", '    pub fn default_dir() -> Option<PathBuf> {\n        if let Some(path) = crate::bogo_qa::path("recovery") { return Some(path); }'))
        edit("crates/ui-egui/src/image_pick.rs", lambda text: replace_once(text, "fn clipboard_dir() -> Option<std::path::PathBuf> {", 'fn clipboard_dir() -> Option<std::path::PathBuf> {\n    if let Some(path) = crate::bogo_qa::path("cache/clipboard") { return Some(path); }'))

    elif app == "ui":
        add("apps/figcraft/src/bogo_qa.rs")
        def ui_main(text):
            text = early(replace_once(text, "mod args;", "mod bogo_qa;\nmod args;"), "fn main() -> eframe::Result {", "bogo_qa::root()")
            return replace_once(text, "session.live.links = figcraft_collab_net::links::system();", "session.live.links = if bogo_qa::root().is_some() { None } else { figcraft_collab_net::links::system() };")
        edit("apps/figcraft/src/main.rs", ui_main)
        edit("apps/figcraft/src/services.rs", lambda text: replace_once(text, "pub fn config_dir() -> Option<PathBuf> {", 'pub fn config_dir() -> Option<PathBuf> {\n    if let Some(path) = crate::bogo_qa::path("profile") { return Some(path); }'))

    elif app == "deck":
        add("apps/deckcraft/src/bogo_qa.rs")
        def deck_main(text):
            text = replace_once(text, "mod control_server;", "mod bogo_qa;\nmod control_server;")
            text = early(text, "fn main() -> eframe::Result {", "bogo_qa::root()")
            text = replace_once(text, "fn config_dir() -> Option<std::path::PathBuf> {", 'fn config_dir() -> Option<std::path::PathBuf> {\n    if let Some(path) = bogo_qa::path("profile") { return Some(path); }')
            return replace_once(text, "app.session.recovery_dir = deckcraft_engine::recovery::default_dir();", 'app.session.recovery_dir = bogo_qa::path("recovery").or_else(deckcraft_engine::recovery::default_dir);')
        edit("apps/deckcraft/src/main.rs", deck_main)

    elif app == "launcher":
        add("crates/native/src/bogo_qa.rs")
        edit("crates/native/src/lib.rs", lambda text: replace_once(text, "pub mod backend;", "pub mod bogo_qa;\npub mod backend;"))
        edit("crates/native/src/paths.rs", lambda text: replace_once(text, "    pub fn new() -> Result<Self, String> {", '    pub fn new() -> Result<Self, String> {\n        if let Some(root) = crate::bogo_qa::root() { return Ok(Self::under(&root)); }'))
        edit("apps/artcraft-launcher/src/settings_file.rs", lambda text: replace_once(text, "pub fn path(app_id: &str) -> Option<PathBuf> {", 'pub fn path(app_id: &str) -> Option<PathBuf> {\n    if let Some(path) = artcraft_launcher_native::bogo_qa::path("settings/app.ron") { return Some(path); }'))
        def launcher_main(text):
            text = early(text, "fn main() -> ExitCode {", "artcraft_launcher_native::bogo_qa::root()")
            return replace_once(text,
                "eframe::NativeOptions { viewport, persist_window: true, wgpu_options: wgpu_options(), ..Default::default() }",
                'eframe::NativeOptions { viewport, persistence_path: artcraft_launcher_native::bogo_qa::path("settings/app.ron"), persist_window: true, wgpu_options: wgpu_options(), ..Default::default() }')
        edit("apps/artcraft-launcher/src/main.rs", launcher_main)
        edit("crates/native/src/single_instance.rs", lambda text: replace_once(text,
            "    let ours = ours();\n    if let Ok(listener) = TcpListener::bind(addr) {",
            '''    let ours = ours();
    if crate::bogo_qa::root().is_some() {
        let listener = crate::bogo_qa::launcher_listener(addr).unwrap_or_else(|error| {
            eprintln!("Bogo Launcher QA refused: {error}");
            std::process::exit(2)
        });
        return Instance::Primary(listen(listener, ours, wake));
    }
    if let Ok(listener) = TcpListener::bind(addr) {'''))

    return changed
