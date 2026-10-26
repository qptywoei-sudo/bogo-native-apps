"""Compatibility overlay for the separately prepared, pinned native Launcher.

The original KIO patches/locks stay immutable. This overlay retains installed
identities and accepts both measured KIO and Bogo release families.
"""
from pathlib import Path


LEGACY_NAMES = {
    'photocraft': 'KIO Photo', 'vectorcraft': 'KIO Vector', 'filmcraft': 'KIO Film',
    'lightcraft': 'KIO Light', 'pdfcraft': 'KIO PDF', 'effectcraft': 'KIO Effect',
    'designcraft': 'KIO Design', 'figcraft': 'KIO UI', 'wordcraft': 'KIO Word',
    'soundcraft': 'KIO Sound', 'deckcraft': 'KIO Deck', 'cadcraft': 'KIO Cad',
    'gridcraft': 'KIO Grid', 'artcraft-launcher': 'KIO Launcher',
}

BOGO_REPOSITORY = 'qptywoei-sudo/bogo-native-apps'
LEGACY_REPOSITORY = 'qptywoei777-rgb/kio-native-apps'
BOGO_REGISTRY = 'https://raw.githubusercontent.com/qptywoei-sudo/bogo-native-apps/refs/heads/codex/bogo-native-rebrand-20261026/manifests/bogo-native-downloads.json'
LEGACY_REGISTRY = 'https://kio-library.vercel.app/downloads/native-apps-manifest.json'


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Unreviewed Launcher source contract: ' + before[:100])
    return text.replace(before, after, 1)


def transform_launcher(source, lock):
    """Apply after original preparation and before generic visible-string/icon edits.

    Return paths owned by this compatibility overlay. A caller must preserve its
    legacy literals when doing later generic display changes.
    """
    source = Path(source)
    if lock['id'] != 'launcher' or lock['bundleId'] != 'com.kio.launcher':
        raise ValueError('Wrong Launcher overlay identity')
    changed = []

    def edit(relative, transform):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing regular Launcher source: ' + relative)
        before = path.read_text(encoding='utf-8')
        after = transform(before)
        if after == before:
            raise ValueError('Launcher overlay made no change: ' + relative)
        path.write_text(after, encoding='utf-8')
        changed.append(relative)

    edit('crates/core/src/catalog.rs', _catalog)
    edit('crates/core/src/kio_registry.rs', _registry)
    edit('crates/core/src/version.rs', _version)
    edit('crates/native/src/detect.rs', _detect)
    edit('crates/native/src/install.rs', _install)
    edit('crates/core/src/feed.rs', _repository_feed)
    edit('crates/native/src/backend.rs', _repository_backend)
    edit('crates/native/src/source.rs', lambda text: replace_once(text, 'The verified KIO release registry is unavailable.', 'The verified Bogo release registry is unavailable.'))
    edit('crates/ui-egui/src/widgets.rs', _brand_case)
    return changed


def _catalog(text):
    text = text.replace('Installs and updates the KIO App Suite', 'Installs and updates the Bogo App Suite')
    for name in LEGACY_NAMES.values():
        text = text.replace('"' + name + '"', '"' + name.replace('KIO ', 'Bogo ').replace(' Cad', ' CAD') + '"')
    text = text.replace('starts_with("KIO ")', 'starts_with("Bogo ")')
    arms = '\n'.join('            "' + key + '" => "' + name + '",' for key, name in LEGACY_NAMES.items())
    method = '''    /// Exact historical installer names remain discoverable after rebranding.
    pub fn legacy_name(&self) -> &'static str {
        match self.id {
ARMS
            _ => self.name,
        }
    }

'''.replace('ARMS', arms)
    text = replace_once(text, '    pub fn kio_id(&self)', method + '    pub fn kio_id(&self)')
    text = replace_once(text, 'std::iter::once(self.name).chain(self.former_names.iter().copied())',
                        'std::iter::once(self.name).chain(std::iter::once(self.legacy_name())).chain(self.former_names.iter().copied())')
    text = replace_once(text, '["Bogo PDF", "PrintCraft"]', '["Bogo PDF", "KIO PDF", "PrintCraft"]')
    # Keep the original identity assertions and add explicit KIO discovery coverage.
    text += '''
#[cfg(test)]
mod bogo_identity_tests {
    use super::*;
    #[test]
    fn display_changes_keep_original_bundle_and_installer_names() {
        for app in SUITE.iter().chain(std::iter::once(&LAUNCHER)) {
            assert!(app.name.starts_with("Bogo "));
            assert!(app.legacy_name().starts_with("KIO "));
            assert!(app.names().any(|name| name == app.legacy_name()));
            assert_eq!(app.bundle_id(), format!("com.kio.{}", app.kio_id()));
        }
    }
}
'''
    return text.replace(LEGACY_REPOSITORY, BOGO_REPOSITORY)


def _registry(text):
    text = replace_once(text,
        'let (upstream, revision) = full_version.split_once("-kio.").ok_or("missing KIO release revision")?;',
        'let (upstream, revision) = full_version.split_once("-bogo.").or_else(|| full_version.split_once("-kio.")).ok_or("missing Bogo release revision")?;')
    text = replace_once(text, "let prefix = app.name.replace(' ', \"-\");",
        "let display = if full_version.contains(\"-bogo.\") { app.name } else { app.legacy_name() };\n            let prefix = display.replace(' ', \"-\");")
    start = text.index('pub fn asset_name(')
    end = text.index('\n#[cfg(test)]', start)
    text = text[:start] + '''pub fn asset_name(name: &str, stems: &[&str]) -> Option<AssetName> {
    for app in SUITE.iter().chain(std::iter::once(&LAUNCHER)) {
        if !stems.contains(&app.id) {
            continue;
        }
        for display in [app.name, app.legacy_name()] {
            let prefix = format!("{}-", display.replace(' ', "-"));
            let Some(rest) = name.strip_prefix(&prefix) else { continue };
            let (body, kind) = if let Some(b) = rest.strip_suffix(".dmg") {
                (b, PackageKind::Dmg)
            } else if let Some(b) = rest.strip_suffix(".msi") {
                (b, PackageKind::Msi)
            } else if let Some(b) = rest.strip_suffix(".zip") {
                (b, PackageKind::PortableZip)
            } else {
                continue;
            };
            let mut parts = body.rsplitn(3, '-');
            let arch = parts.next()?;
            let os = parts.next()?;
            let v = parts.next()?;
            let version = version::parse(v)?;
            let family_matches = if display.starts_with("Bogo ") {
                version.pre.as_str().starts_with("bogo.")
            } else {
                version.pre.as_str().starts_with("kio.")
            };
            if !family_matches || version::packaging_revision(&version).is_none() {
                continue;
            }
            let token = match (os, arch, kind) {
                ("macos", "arm64", PackageKind::Dmg) => "macos-aarch64",
                ("windows", "x64", PackageKind::Msi | PackageKind::PortableZip) => "windows-x64",
                _ => continue,
            };
            return Some(AssetName { stem: app.id.into(), version: v.into(), token: token.into(), kind });
        }
    }
    None
}
''' + text[end:]
    text += '''
#[cfg(test)]
mod bogo_registry_tests {
    use super::*;
    #[test]
    fn both_measured_release_families_remain_bound() {
        for (family, brand) in [("kio", "KIO"), ("bogo", "Bogo")] {
            let version = format!("0.7.0-{family}.1");
            let tag = format!("word-v{version}");
            let name = format!("{brand}-Word-{version}-windows-x64.msi");
            let row = serde_json::json!({"schemaVersion":1,"programs":[{
                "id":"word","version":version,"upstreamVersion":"0.7.0","repository":REPOSITORY,
                "releaseTag":tag,"artifacts":[{"platform":"windows","arch":"x86_64","kind":"msi",
                "bytes":123,"sha256":"a".repeat(64),"url":format!("https://github.com/{REPOSITORY}/releases/download/{tag}/{name}")}]}]});
            let json = row.to_string();
            assert!(parse(&json).is_ok());
            assert!(asset_name(&name, &["wordcraft"]).is_some());
            assert!(asset_name(&name, &["gridcraft"]).is_none());
            let wrong = json.replace(&format!("{brand}-Word-"), "Bogo-Grid-");
            assert!(parse(&wrong).is_err());
        }
        assert!(asset_name("Bogo-Word-0.7.0-kio.1-windows-x64.msi", &["wordcraft"]).is_none());
        assert!(asset_name("KIO-Word-0.7.0-bogo.1-windows-x64.msi", &["wordcraft"]).is_none());
    }
}
'''
    for noun in ('registry', 'program', 'release', 'version', 'upstream', 'tag', 'artifact', 'asset'):
        text = text.replace('KIO ' + noun, 'Bogo ' + noun)
    return _repository_registry(text)


def _repository_registry(text):
    production, tests = text.split('#[cfg(test)]', 1)
    production = replace_once(production, f'pub const REPOSITORY: &str = "{LEGACY_REPOSITORY}";', f'pub const REPOSITORY: &str = "{BOGO_REPOSITORY}";\npub const LEGACY_REPOSITORY: &str = "{LEGACY_REPOSITORY}";')
    production = replace_once(production, f'pub const REGISTRY_URL: &str = "{LEGACY_REGISTRY}";', f'pub const REGISTRY_URL: &str = "{BOGO_REGISTRY}";\npub const LEGACY_REGISTRY_URL: &str = "{LEGACY_REGISTRY}";')
    production = replace_once(production, '''        if row.get("repository").and_then(serde_json::Value::as_str) != Some(REPOSITORY) {
            return Err("Bogo release repository is not allowed".into());
        }
''', '')
    production = replace_once(production, '        let parsed = version::parse(upstream)', '''        let repository = if full_version.contains("-bogo.") { REPOSITORY } else { LEGACY_REPOSITORY };
        if row.get("repository").and_then(serde_json::Value::as_str) != Some(repository) {
            return Err("release family does not match its exact repository".into());
        }
        let parsed = version::parse(upstream)''')
    production = production.replace('https://github.com/{REPOSITORY}/releases/', 'https://github.com/{repository}/releases/')
    production = replace_once(production, 'name: format!("{} {full_version}", app.name),', 'name: format!("{} {full_version}", if full_version.contains("-bogo.") { app.name } else { app.legacy_name() }),')
    production = replace_once(production, 'feed.apps.insert(app.id.into(), FeedApp { repo: Some(REPOSITORY.into()), fetched_at: Some(0), release });', 'feed.apps.insert(app.id.into(), FeedApp { repo: Some(repository.into()), fetched_at: Some(0), release });')
    historical, current = tests.split('#[cfg(test)]\nmod bogo_registry_tests', 1)
    historical = historical.replace('REPOSITORY', 'LEGACY_REPOSITORY')
    current = replace_once(current, 'let version = format!("0.7.0-{family}.1");', 'let version = format!("0.7.0-{family}.1");\n            let repository = if family == "bogo" { REPOSITORY } else { LEGACY_REPOSITORY };')
    current = current.replace('"repository":REPOSITORY', '"repository":repository').replace('https://github.com/{REPOSITORY}/releases/', 'https://github.com/{repository}/releases/')
    current = replace_once(current, 'assert!(parse(&json).is_ok());', '''assert!(parse(&json).is_ok());
            let other_repository = if family == "bogo" { LEGACY_REPOSITORY } else { REPOSITORY };
            assert!(parse(&json.replace(repository, other_repository)).is_err());
            assert!(catalog_family(&json, family == "bogo").is_ok());
            assert!(catalog_family(&json, family != "bogo").is_err());''')
    production += '''
/// Validate a fetched catalog's family as well as every individual exact artifact.
/// Cached historical catalogs still use parse(), which binds each family itself.
pub fn catalog_family(body: &str, bogo: bool) -> Result<bool, String> {
    parse(body)?;
    let raw: serde_json::Value = serde_json::from_str(body).map_err(|_| "invalid registry")?;
    let rows = raw["programs"].as_array().ok_or("missing programs")?;
    let suffix = if bogo { "-bogo." } else { "-kio." };
    if rows.iter().any(|row| !row["version"].as_str().is_some_and(|value| value.contains(suffix))) {
        return Err("catalog contains a different release family".into());
    }
    Ok(rows.iter().any(|row| row["artifacts"].as_array().is_some_and(|items| !items.is_empty())))
}
'''
    return production + '#[cfg(test)]' + historical + '#[cfg(test)]\nmod bogo_registry_tests' + current


def _repository_feed(text):
    return replace_once(text, '        let repo = self.repo_for(app);', '''        let repo = if self.kio_registry && entry.repo.as_deref() == Some(crate::kio_registry::LEGACY_REPOSITORY) {
            crate::kio_registry::LEGACY_REPOSITORY.to_string()
        } else {
            self.repo_for(app)
        };''')


def _repository_backend(text):
    text = replace_once(text, 'let outcome = match http.get_feed(url) {', 'let outcome = match bogo_registry_body(http, url) {')
    production, tests = text.split('#[cfg(test)]', 1)
    tests = replace_once(tests, '"photocraft": {"repo": "' + LEGACY_REPOSITORY + '", "latest_release": {"tag": "v0.6.0"}', '"photocraft": {"repo": "' + BOGO_REPOSITORY + '", "latest_release": {"tag": "v0.6.0"}')
    text = production + '#[cfg(test)]' + tests
    return text + '''
/// Only the exact new catalog or the exact historical KIO catalog are trusted.
/// An unpublished/empty Bogo catalog may show genuine legacy availability.
fn bogo_registry_body(http: &Http, url: &str) -> Result<String, http::FeedError> {
    use artcraft_launcher_core::kio_registry as registry;
    if url != registry::REGISTRY_URL {
        return http.get_feed(url);
    }
    let primary = http.get_feed(registry::REGISTRY_URL);
    let mut empty_primary = None;
    match primary {
        Ok(body) => match registry::catalog_family(&body, true) {
            Ok(true) => return Ok(body),
            Ok(false) => empty_primary = Some(body),
            Err(why) => return Err(http::FeedError { why, throttled: false, retry_after: None }),
        },
        Err(_) => {}
    }
    match http.get_feed(registry::LEGACY_REGISTRY_URL) {
        Ok(body) if registry::catalog_family(&body, false).is_ok() => Ok(body),
        _ => empty_primary.ok_or_else(|| http::FeedError {
            why: "neither exact Bogo catalog nor validated historical catalog is available".into(),
            throttled: false, retry_after: None,
        }),
    }
}
'''


def _brand_case(text):
    if text.count('text.to_uppercase()') != 2:
        raise ValueError('Unreviewed Launcher caps widgets')
    return text.replace('text.to_uppercase()', 'text.to_uppercase().replace("BOGO", "Bogo")')


def _repository_pdf(text):
    production, tests = text.split('#[cfg(test)]', 1)
    production = replace_once(production, f'const REPOSITORY: &str = "{LEGACY_REPOSITORY}";', f'const REPOSITORY: &str = "{BOGO_REPOSITORY}";\nconst LEGACY_REPOSITORY: &str = "{LEGACY_REPOSITORY}";')
    production = replace_once(production, f'const MANIFEST: &str = "{LEGACY_REGISTRY}";', f'const MANIFEST: &str = "{BOGO_REGISTRY}";\nconst LEGACY_MANIFEST: &str = "{LEGACY_REGISTRY}";')
    production = replace_once(production, '        || entry["repository"].as_str() != Some(REPOSITORY)\n', '')
    production = replace_once(production, '    let tag = format!("pdf-v{version}");', '''    let repository = if brand == "Bogo" { REPOSITORY } else { LEGACY_REPOSITORY };
    if entry["repository"].as_str() != Some(repository) { return Err(invalid()); }
    let tag = format!("pdf-v{version}");''')
    production = production.replace('https://github.com/{REPOSITORY}/releases/', 'https://github.com/{repository}/releases/')
    start = production.index('    let mut response = agent\n')
    end = production.index('\n/// The certificate authorities', start)
    production = production[:start] + '''    if let Ok(body) = fetch_manifest(&agent, MANIFEST) {
        if let Some(release) = published_bogo_manifest(&body)? {
            return Ok(release);
        }
    }
    let legacy = fetch_manifest(&agent, LEGACY_MANIFEST).and_then(|body| parse(&body))?;
    if !legacy.version.contains("-kio.") {
        return Err("historical PDF catalog contains a different release family".into());
    }
    Ok(legacy)
}

fn published_bogo_manifest(body: &str) -> Result<Option<Release>, String> {
    let value: serde_json::Value = serde_json::from_str(body).map_err(|_| "invalid Bogo PDF catalog")?;
    let rows = value["programs"].as_array().filter(|rows| rows.len() <= 64).ok_or("invalid Bogo PDF catalog")?;
    if value["schemaVersion"].as_u64() != Some(1) { return Err("invalid Bogo PDF catalog".into()); }
    if rows.iter().all(|row| row["id"].as_str() != Some("pdf")) { return Ok(None); }
    let release = parse(body)?;
    if !release.version.contains("-bogo.") { return Err("Bogo PDF catalog contains a different release family".into()); }
    Ok(Some(release))
}

fn fetch_manifest(agent: &ureq::Agent, url: &str) -> Result<String, String> {
    let mut response = agent.get(url).header("Accept", "application/json")
        .header("User-Agent", concat!("Bogo-PDF/", env!("CARGO_PKG_VERSION")))
        .config().http_status_as_error(false).build().call()
        .map_err(|error| format!("couldn't reach the Bogo PDF release service ({error})"))?;
    let status = response.status().as_u16();
    if !(200..300).contains(&status) {
        return Err(format!("couldn't reach the Bogo PDF release service (http status: {status})"));
    }
    response.body_mut().with_config().limit(1 << 20).read_to_string()
        .map_err(|error| format!("unreadable Bogo release manifest ({error})"))
}
''' + production[end:]
    historical, current = tests.split('#[cfg(test)]\nmod bogo_manifest_tests', 1)
    historical = historical.replace('REPOSITORY', 'LEGACY_REPOSITORY')
    current += '''
#[cfg(test)]
mod bogo_repository_boundary_tests {
    use super::*;
    #[test]
    fn repositories_are_bound_to_version_family() {
        let legacy = serde_json::json!({"id":"pdf","name":"KIO PDF","version":"0.8.0-kio.2","upstreamVersion":"0.8.0","releaseTag":"pdf-v0.8.0-kio.2","repository":LEGACY_REPOSITORY,"bundleId":"com.kio.pdf","artifacts":[{"platform":"macos","arch":"aarch64","kind":"dmg","url":format!("https://github.com/{LEGACY_REPOSITORY}/releases/download/pdf-v0.8.0-kio.2/KIO-PDF-0.8.0-kio.2-macos-arm64.dmg"),"sha256":"a".repeat(64),"bytes":123}]});
        let body = serde_json::json!({"schemaVersion":1,"programs":[legacy]}).to_string();
        assert!(parse_for_platform(&body, "macos", "aarch64").is_ok());
        assert!(parse_for_platform(&body.replace(LEGACY_REPOSITORY, REPOSITORY), "macos", "aarch64").is_err());
        let bogo = body.replace("KIO PDF", "Bogo PDF").replace("KIO-PDF-", "Bogo-PDF-").replace("-kio.2", "-bogo.1").replace(LEGACY_REPOSITORY, REPOSITORY);
        assert!(parse_for_platform(&bogo, "macos", "aarch64").is_ok());
        assert!(parse_for_platform(&bogo.replace(REPOSITORY, LEGACY_REPOSITORY), "macos", "aarch64").is_err());
    }
}
'''
    return production + '#[cfg(test)]' + historical + '#[cfg(test)]\nmod bogo_manifest_tests' + current


def _version(text):
    text = replace_once(text, 'pub fn is_newer(latest: &Version, installed: &Version) -> bool {', '''pub fn is_newer(latest: &Version, installed: &Version) -> bool {
    if installed.pre.as_str().starts_with("bogo.") && latest.pre.as_str().starts_with("kio.") { return false; }''')
    text = replace_once(text, '''    a.cmp_precedence(b)''', '''    if (a.major, a.minor, a.patch) == (b.major, b.minor, b.patch)
        && let (Some(a), Some(b)) = (packaging_revision(a), packaging_revision(b))
    {
        return a.cmp(&b);
    }
    a.cmp_precedence(b)''')
    start = text.index('pub fn is_update(')
    end = text.index('\n#[cfg(test)]', start)
    text = text[:start] + '''pub fn packaging_revision(version: &Version) -> Option<(u8, u64)> {
    let pre = version.pre.as_str();
    let (family, revision) = if let Some(revision) = pre.strip_prefix("bogo.") {
        (1, revision)
    } else if let Some(revision) = pre.strip_prefix("kio.") {
        (0, revision)
    } else {
        return None;
    };
    if revision.is_empty() || !revision.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    revision.parse::<u64>().ok().filter(|n| *n > 0).map(|n| (family, n))
}

pub fn is_update(latest: &Version, installed: &Version) -> bool {
    if installed.pre.as_str().starts_with("bogo.") && latest.pre.as_str().starts_with("kio.") { return false; }
    if (latest.major, latest.minor, latest.patch) == (installed.major, installed.minor, installed.patch) {
        match (packaging_revision(latest), packaging_revision(installed)) {
            (Some(a), Some(b)) => return a > b,
            (Some(_), None) if installed.pre.is_empty() => return true,
            _ => {}
        }
        if installed.pre.is_empty() && !latest.pre.is_empty() {
            return false;
        }
    }
    is_newer(latest, installed)
}
''' + text[end:]
    text += '''
#[cfg(test)]
mod bogo_version_tests {
    use super::*;
    #[test]
    fn bogo_updates_legacy_and_never_downgrades_to_kio() {
        let v = |s| parse(s).unwrap();
        assert!(is_update(&v("0.7.0-bogo.1"), &v("0.7.0-kio.99")));
        assert!(!is_update(&v("0.7.0-kio.99"), &v("0.7.0-bogo.1")));
        assert!(!is_update(&v("0.9.0-kio.1"), &v("0.8.0-bogo.1")));
        assert!(!is_newer(&v("0.9.0-kio.1"), &v("0.8.0-bogo.1")));
        assert!(is_update(&v("0.7.0-bogo.1"), &v("0.7.0")));
        assert!(is_update(&v("0.7.0-bogo.2"), &v("0.7.0-bogo.1")));
        assert!(!is_update(&v("0.7.0-bogo.1"), &v("0.7.0-bogo.1")));
        assert!(!is_update(&v("0.6.0-bogo.9"), &v("0.7.0-kio.1")));
        assert!(packaging_revision(&v("0.7.0-bogo.0")).is_none());
        assert!(packaging_revision(&v("0.7.0-bogo.alpha")).is_none());
    }
}
'''
    return text


def _detect(text):
    text = replace_once(text, 'managed.pre.as_str().starts_with("kio.")', 'version::packaging_revision(&managed).is_some()')
    text = replace_once(text, 'publisher == PUBLISHER && app.names().filter(|n| n.starts_with("KIO ")).any(|n| n == display_name)',
        '(publisher == "Bogo" && display_name == app.name) || (publisher == PUBLISHER && display_name == app.legacy_name())')
    text = text.replace('app.names().filter(|n| n.starts_with("KIO "))', 'app.names().filter(|n| n.starts_with("Bogo ") || n.starts_with("KIO "))')
    text = replace_once(text, 'std::iter::once(format!("{}.exe", app.name)).chain(app.stems().map(|s| format!("{s}.exe")))',
        '[app.name, app.legacy_name()].into_iter().map(|name| format!("{name}.exe")).chain(app.stems().map(|s| format!("{s}.exe")))')
    start = text.index('    pub fn candidates(app: &CraftApp) -> Vec<PathBuf> {')
    end = text.index('\n    pub fn detect(', start)
    text = text[:start] + '''    pub fn candidates(app: &CraftApp) -> Vec<PathBuf> {
        let mut out = Vec::new();
        for name in [app.name, app.legacy_name()] {
            let bundle = format!("{name}.app");
            out.push(Path::new("/Applications").join(&bundle));
            if let Some(home) = dirs::home_dir() {
                out.push(home.join("Applications").join(&bundle));
            }
        }
        out
    }
''' + text[end:]
    text = replace_once(text, 'let text = [full_key.as_str(), legacy_key.as_str(), "CFBundleShortVersionString", "CFBundleVersion"]',
        '''let prior_full_key = format!("{}Version", app.legacy_name().replace(' ', ""));
        let prior_spaced_key = format!("{}Version", app.legacy_name());
        let text = [full_key.as_str(), legacy_key.as_str(), prior_full_key.as_str(), prior_spaced_key.as_str(), "CFBundleShortVersionString", "CFBundleVersion"]''')
    # Existing source tests still verify legacy KIO packages; expand only the new candidates.
    text = replace_once(text, 'std::iter::once(location.clone()).chain(roots.iter().map(|r| r.join("KIO PDF")))',
        'std::iter::once(location.clone()).chain(roots.iter().flat_map(|r| ["Bogo PDF", "KIO PDF"].map(|name| r.join(name))))')
    text = replace_once(text, 'for name in ["KIO PDF.exe", "pdfcraft.exe", "printcraft.exe"]',
        'for name in ["Bogo PDF.exe", "KIO PDF.exe", "pdfcraft.exe", "printcraft.exe"]')
    # Custom location equals a legacy root in this regression: deduplicate as production does.
    text = replace_once(text, '                want.push(dir.join(name));',
        '                let candidate = dir.join(name);\n                if !want.contains(&candidate) { want.push(candidate); }')
    text = replace_once(text, 'assert!(is_installer_entry(app, app.name, LEARNING_MACHINES),',
        'assert!(is_installer_entry(app, app.name, "Bogo"),')
    text = replace_once(text, 'std::iter::once(location.clone()).chain(roots.iter().map(|r| r.join(app.name)))',
        'std::iter::once(location.clone()).chain(roots.iter().flat_map(|r| [app.name, app.legacy_name()].map(|name| r.join(name))))')
    text = replace_once(text, '                want.push(dir.join(format!("{}.exe", app.name)));',
        '                want.push(dir.join(format!("{}.exe", app.name)));\n                want.push(dir.join(format!("{}.exe", app.legacy_name())));')
    text = replace_once(text, '''        let app_path_key = format!(r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{}.exe", app.name);
        let mut app_paths = Vec::new();
        for (hive, flags) in [(HKEY_LOCAL_MACHINE, KEY_WOW64_64KEY), (HKEY_LOCAL_MACHINE, KEY_WOW64_32KEY), (HKEY_CURRENT_USER, 0)] {
            if let Ok(key) = RegKey::predef(hive).open_subkey_with_flags(&app_path_key, KEY_READ | flags)
                && let Ok(path) = key.get_value::<String, _>("")
            {
                app_paths.push(PathBuf::from(path.trim_matches('"')));
            }
        }''', '''        let mut app_paths = Vec::new();
        for name in [app.name, app.legacy_name()] {
            let app_path_key = format!(r"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{name}.exe");
            for (hive, flags) in [(HKEY_LOCAL_MACHINE, KEY_WOW64_64KEY), (HKEY_LOCAL_MACHINE, KEY_WOW64_32KEY), (HKEY_CURRENT_USER, 0)] {
                if let Ok(key) = RegKey::predef(hive).open_subkey_with_flags(&app_path_key, KEY_READ | flags)
                    && let Ok(path) = key.get_value::<String, _>("")
                {
                    app_paths.push(PathBuf::from(path.trim_matches('"')));
                }
            }
        }''')
    text += '''
#[cfg(test)]
mod bogo_detect_tests {
    use super::*;
    #[test]
    fn publisher_and_identity_must_match_the_same_release_family() {
        let word = CraftApp::by_id("wordcraft").unwrap();
        assert!(is_installer_entry(word, "Bogo Word", "Bogo"));
        assert!(is_installer_entry(word, "KIO Word", "KIO"));
        assert!(!is_installer_entry(word, "Bogo Word", "KIO"));
        assert!(!is_installer_entry(word, "KIO Word", "Bogo"));
        assert!(!is_installer_entry(word, "Bogo Grid", "Bogo"));
    }
}
'''
    return text


def _install(text):
    # diskimages-helper cannot mount below an external/private application cache
    # on macOS even when the calling process can write there. Mount at the OS
    # volume namespace, without creating or reusing any caller-controlled entry.
    text = replace_once(text,
        'pub fn install_dmg(app: &CraftApp, dmg: &Path, existing: Option<&Installed>, paths: &Paths, expect: &Expect<\'_>)',
        'pub fn install_dmg(app: &CraftApp, dmg: &Path, existing: Option<&Installed>, _paths: &Paths, expect: &Expect<\'_>)')
    text = replace_once(text, '''        let mount = paths.cache.join(format!("mount-{}-{}-{attempt}", app.id, std::process::id()));
        std::fs::create_dir_all(&mount).map_err(|e| format!("couldn't create a folder to open the disk image in ({e})"))?;''', '''        let mount = Path::new("/Volumes").join(format!("Bogo-{}-{}-{attempt}", app.id, std::process::id()));
        match std::fs::symlink_metadata(&mount) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Ok(_) => return Err("the unique disk-image mount location already exists; nothing was mounted".into()),
            Err(error) => return Err(format!("couldn't inspect the disk-image mount location ({error})")),
        }''')
    text = text.replace('unusual characters in the cache folder\'s path', 'unusual characters in the disk-image path')
    text = replace_once(text, '''if text("ProductName") != Some(app.name)
            || text("Manufacturer") != Some("KIO")''', '''let family = release.version.as_ref().and_then(artcraft_launcher_core::version::packaging_revision).map(|(family, _)| family);
        let expected = if family == Some(1) { (app.name, "Bogo") } else { (app.legacy_name(), "KIO") };
        if text("ProductName") != Some(expected.0)
            || text("Manufacturer") != Some(expected.1)''')
    # A KIO release may still be installed while the new catalog displays Bogo.
    text = replace_once(text, '''let bundle = format!("{}.app", app.name);
        let src = mount.join(&bundle);''', '''let family = expect.version.and_then(artcraft_launcher_core::version::packaging_revision).map(|(family, _)| family);
        let display = match family {
            Some(0) => app.legacy_name(),
            Some(1) => app.name,
            _ if mount.join(format!("{}.app", app.name)).is_dir() => app.name,
            _ => app.legacy_name(),
        };
        let bundle = format!("{display}.app");
        let src = mount.join(&bundle);''')
    # Only move a verified legacy app bundle. Keep it as an explicitly named,
    # hidden backup; if the final move fails, restore it before returning failure.
    text = replace_once(text, '''        swap_into_place(&staged, &dest)?;
        Ok(dest)''', '''        let legacy = existing.filter(|installed| installed.source == InstallSource::MacApp)
            .map(|installed| PathBuf::from(&installed.location))
            .filter(|path| path != &dest && path.parent() == Some(dir.as_path())
                && path.file_name().is_some_and(|name| name.to_string_lossy() == format!("{}.app", app.legacy_name()))
                && crate::detect::macos::read_bundle(app, path).is_some());
        let mut preserved = None;
        if let Some(old) = legacy {
            let backup = dir.join(format!(".{}.bogo-previous-{}-{}.app", app.legacy_name(), crate::now(), std::process::id()));
            if backup.exists() {
                return Err("the previous application backup already exists; no application was replaced".into());
            }
            std::fs::rename(&old, &backup).map_err(|e| format!("couldn't preserve the previous application ({e})"))?;
            preserved = Some((old, backup));
        }
        if let Err(error) = swap_into_place(&staged, &dest) {
            if let Some((old, backup)) = preserved {
                std::fs::rename(&backup, &old).map_err(|e| format!("{error}; previous application remains at {} ({e})", backup.display()))?;
            }
            return Err(error);
        }
        Ok(dest)''')
    text = replace_once(text, '''    /// Checks a copied bundle against what its release promises, before it replaces anything.''', '''    #[cfg(test)]
    mod bogo_copy_tests {
        use super::*;

        fn fixture(parent: &Path, display: &str, version: &str) -> PathBuf {
            let bundle = parent.join(format!("{display}.app"));
            let contents = bundle.join("Contents");
            std::fs::create_dir_all(contents.join("MacOS")).unwrap();
            std::fs::write(contents.join("Info.plist"), format!(
                "<?xml version=\\"1.0\\"?><plist version=\\"1.0\\"><dict><key>CFBundleIdentifier</key><string>com.kio.photo</string><key>CFBundleExecutable</key><string>{display}</string><key>CFBundleShortVersionString</key><string>{version}</string></dict></plist>"
            )).unwrap();
            std::fs::write(contents.join("MacOS").join(display), version).unwrap();
            bundle
        }

        #[test]
        fn bogo_copy_preserves_the_previous_kio_bundle_without_mounting_a_dmg() {
            let temporary = tempfile::tempdir().unwrap();
            let apps = temporary.path().join("Applications");
            let old = fixture(&apps, "KIO Photo", "0.9.0-kio.1");
            let mount = temporary.path().join("mounted-release");
            fixture(&mount, "Bogo Photo", "0.9.0-bogo.1");
            let existing = Installed { version: None, source: InstallSource::MacApp, location: old.display().to_string(), package: None };
            let app = artcraft_launcher_core::catalog::CraftApp::by_id("photocraft").unwrap();
            let version = artcraft_launcher_core::version::parse("0.9.0-bogo.1").unwrap();
            let installed = copy_app(app, &mount, Some(&existing), &Expect { team: None, version: Some(&version) }).unwrap();
            assert_eq!(installed, apps.join("Bogo Photo.app"));
            assert!(!old.exists());
            assert_eq!(std::fs::read_to_string(installed.join("Contents/MacOS/Bogo Photo")).unwrap(), "0.9.0-bogo.1");
            let backups: Vec<_> = std::fs::read_dir(&apps).unwrap().flatten().map(|entry| entry.path())
                .filter(|path| path.file_name().unwrap().to_string_lossy().starts_with(".KIO Photo.bogo-previous-")).collect();
            assert_eq!(backups.len(), 1);
            assert_eq!(std::fs::read_to_string(backups[0].join("Contents/MacOS/KIO Photo")).unwrap(), "0.9.0-kio.1");
        }
    }

    /// Checks a copied bundle against what its release promises, before it replaces anything.''')
    return text


def transform_light_editor_discovery(source):
    """Prefer Bogo Photo while preserving saved KIO external-editor selections."""
    path = Path(source) / 'apps/lightcraft/src/editors.rs'
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, 'if !app.eq_ignore_ascii_case(PHOTOCRAFT) {',
        'if !app.eq_ignore_ascii_case(PHOTOCRAFT) && !app.eq_ignore_ascii_case("KIO Photo") {')
    text = text.replace('"KIO Photo isn\'t installed.', '"Bogo Photo isn\'t installed.')
    text = replace_once(text, 'mac_candidates(env("HOME").as_deref()).into_iter().find(|p| p.is_dir())',
        'bogo_mac_candidates(env("HOME").as_deref()).into_iter().chain(mac_candidates(env("HOME").as_deref())).find(|p| p.is_dir())')
    text = replace_once(text, 'return windows_candidates(install_dir, app_path, env).into_iter().find(|p| p.is_file()).map(Launcher::Program);',
        r'''let bogo_path = reg_query(r"HKLM\Software\Microsoft\Windows\CurrentVersion\App Paths\Bogo Photo.exe", None);
        return bogo_windows_candidates(install_dir.clone(), bogo_path, &env).into_iter()
            .chain(windows_candidates(install_dir, app_path, env)).find(|p| p.is_file()).map(Launcher::Program);''')
    text = text.replace('assert_eq!(PHOTOCRAFT, "KIO Photo")', 'assert_eq!(PHOTOCRAFT, "Bogo Photo")')
    text += '''
fn bogo_mac_candidates(home: Option<&str>) -> Vec<PathBuf> {
    let mut out = vec![PathBuf::from("/Applications/Bogo Photo.app")];
    if let Some(home) = home {
        for folder in ["Applications", "Applications/KIO Native Apps", "Applications/Bogo Native Apps"] {
            out.push(Path::new(home).join(folder).join("Bogo Photo.app"));
        }
    }
    out
}

fn bogo_windows_candidates(install_dir: Option<String>, app_path: Option<String>, env: impl Fn(&str) -> Option<String>) -> Vec<PathBuf> {
    let mut out = Vec::new();
    out.extend(install_dir.map(|dir| Path::new(&dir).join("Bogo Photo.exe")));
    out.extend(app_path.map(|path| PathBuf::from(path.trim_matches('"'))));
    for var in ["ProgramW6432", "ProgramFiles"] {
        out.extend(env(var).map(|dir| Path::new(&dir).join("Bogo Photo").join("Bogo Photo.exe")));
    }
    out.extend(env("LOCALAPPDATA").map(|dir| Path::new(&dir).join("Programs").join("Bogo Photo").join("Bogo Photo.exe")));
    out
}

#[cfg(test)]
mod bogo_editor_tests {
    use super::*;
    #[test]
    fn new_display_candidates_keep_legacy_storage_and_bundle_identity() {
        assert_eq!(PHOTOCRAFT_ID, "com.kio.photo");
        assert_eq!(bogo_mac_candidates(None)[0], PathBuf::from("/Applications/Bogo Photo.app"));
        assert_eq!(mac_candidates(None)[0], PathBuf::from("/Applications/KIO Photo.app"));
        let candidates = bogo_windows_candidates(Some("/old/KIO Photo".into()), None, |_| None);
        assert_eq!(candidates, [PathBuf::from("/old/KIO Photo/Bogo Photo.exe")]);
    }
}
'''
    path.write_text(text, encoding='utf-8')
    return ['apps/lightcraft/src/editors.rs']


def transform_pdf_updates(source):
    """Bind each PDF release family to its own brand and order Bogo after KIO."""
    source = Path(source)
    path = source / 'apps/pdfcraft/src/updates.rs'
    text = path.read_text(encoding='utf-8')
    text = replace_once(text, '|| entry["name"].as_str() != Some("KIO PDF")',
        '|| !matches!(entry["name"].as_str(), Some("KIO PDF" | "Bogo PDF"))')
    text = replace_once(text, 'version.split_once("-kio.").map(|(core, _)| core)',
        'version.split_once("-bogo.").or_else(|| version.split_once("-kio.")).map(|(core, _)| core)')
    text = replace_once(text, 'let Some((core, revision)) = value.split_once("-kio.")',
        'let Some((core, revision)) = value.split_once("-bogo.").or_else(|| value.split_once("-kio."))')
    text = replace_once(text, 'let tag = format!("pdf-v{version}");',
        '''let brand = if version.contains("-bogo.") { "Bogo" } else { "KIO" };
    if entry["name"].as_str() != Some(format!("{brand} PDF").as_str()) {
        return Err(invalid());
    }
    let tag = format!("pdf-v{version}");''')
    text = replace_once(text, '/{tag}/KIO-PDF-{version}-{suffix}', '/{tag}/{brand}-PDF-{version}-{suffix}')
    # Change UI errors and user agent without changing historical release fixtures.
    production, tests = text.split('#[cfg(test)]', 1)
    for before in ('KIO PDF release', 'KIO release manifest', 'KIO PDF has', 'KIO PDF {version}'):
        production = production.replace(before, before.replace('KIO', 'Bogo'))
    production = production.replace('concat!("KIO-PDF/"', 'concat!("Bogo-PDF/"')
    text = production + '#[cfg(test)]' + tests
    text += '''
#[cfg(test)]
mod bogo_manifest_tests {
    use super::*;
    #[test]
    fn old_and_new_pdf_release_names_cannot_be_mixed() {
        let body = serde_json::json!({"schemaVersion":1,"programs":[{
            "id":"pdf","name":"Bogo PDF","bundleId":"com.kio.pdf","repository":REPOSITORY,
            "version":"0.8.0-bogo.1","upstreamVersion":"0.8.0","releaseTag":"pdf-v0.8.0-bogo.1",
            "artifacts":[{"platform":"macos","arch":"aarch64","kind":"dmg","bytes":123,
            "sha256":"a".repeat(64),"url":format!("https://github.com/{REPOSITORY}/releases/download/pdf-v0.8.0-bogo.1/Bogo-PDF-0.8.0-bogo.1-macos-arm64.dmg")}]}]}).to_string();
        assert!(parse_for_platform(&body, "macos", "aarch64").is_ok());
        assert!(parse_for_platform(&body.replace("Bogo-PDF-", "KIO-PDF-"), "macos", "aarch64").is_err());
        assert!(parse_for_platform(&body.replace("Bogo PDF", "KIO PDF"), "macos", "aarch64").is_err());
    }
}
'''
    text = _repository_pdf(text)
    path.write_text(text, encoding='utf-8')
    ui = source / 'crates/ui-egui/src/updates.rs'
    text = ui.read_text(encoding='utf-8')
    text = replace_once(text, 'pub fn is_newer(latest: &str, current: &str) -> bool {', '''pub fn is_newer(latest: &str, current: &str) -> bool {
    if current.contains("-bogo.") && latest.contains("-kio.") { return false; }''')
    text = replace_once(text, 'Option<(u64, u64, u64, u64)>', 'Option<(u64, u64, u64, u8, u64)>')
    text = replace_once(text, 'let (core, revision) = match v.split_once("-kio.") {',
        'let family = u8::from(v.contains("-bogo."));\n    let (core, revision) = match v.split_once("-bogo.").or_else(|| v.split_once("-kio.")) {')
    text = replace_once(text, '(next(true)?, next(false)?, next(false)?, revision)',
        '(next(true)?, next(false)?, next(false)?, family, revision)')
    # Translation keys and catalogs are handled by the generic display overlay.
    text += '''
#[cfg(test)]
mod bogo_update_order_tests {
    use super::*;
    #[test]
    fn bogo_is_newer_than_every_kio_revision_of_the_same_upstream() {
        assert!(is_newer("0.8.0-bogo.1", "0.8.0-kio.99"));
        assert!(!is_newer("0.8.0-kio.99", "0.8.0-bogo.1"));
        assert!(!is_newer("0.9.0-kio.1", "0.8.0-bogo.1"));
        assert!(is_newer("0.8.0-bogo.2", "0.8.0-bogo.1"));
        assert!(!is_newer("0.8.0-bogo.1", "0.9.0-kio.1"));
    }
}
'''
    ui.write_text(text, encoding='utf-8')
    return ['apps/pdfcraft/src/updates.rs', 'crates/ui-egui/src/updates.rs']
