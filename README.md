# Full native KIO applications

## Downloads

Open the [KIO app store](https://kio-library.vercel.app/) for the measured installers, portable packages and matching complete source. The table records published files as of 2026-10-16; a prepared source or running build is not a published download.

| Application | Version | macOS Apple Silicon | Windows x64 | Release and matching source |
|---|---|---|---|---|
| Word | 0.7.0-kio.2 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/word-v0.7.0-kio.2) |
| Grid | 0.7.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/grid-v0.7.0-kio.1) |
| Deck | 0.7.0-kio.2 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/deck-v0.7.0-kio.2) |
| Film | 0.8.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/film-v0.8.0-kio.1) |
| Sound | 0.7.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/sound-v0.7.0-kio.1) |
| UI | 0.6.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/ui-v0.6.0-kio.1) |
| Light | 0.8.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/light-v0.8.0-kio.1) |
| Effect | 0.10.0-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/effect-v0.10.0-kio.1) |
| Launcher | 0.4.1-kio.1 | DMG / ZIP | MSI / ZIP | [Download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/launcher-v0.4.1-kio.1) |
| PDF | 0.8.0-kio.1 | DMG / ZIP | New 0.8.0-kio.2 build in progress | [Current download](https://github.com/qptywoei777-rgb/kio-native-apps/releases/tag/pdf-v0.8.0-kio.1) |

Photo, Vector, Design and CAD are still completing their native builds and file QA. Studio is distributed separately as an owner-only private test build. Each release explains the actual engine/file checks and remaining interactive GUI/installation work. Development packages have ad-hoc Mac signatures without notarization and no Windows publisher certificate. Complete upstream functionality is retained; full commercial-product feature or format parity is not claimed.

## Build project

This separate build project packages complete upstream applications. It does not use the earlier KIO Apps 0.1 Electron editor prototype. The Word pipeline and the generic 13-application pipeline use independently pinned complete native workspaces. Source/patch readiness is not a record of successful binary builds or GUI validation. Preparing these files never creates or dispatches a remote release.

KIO Word is based on the **entire WordCraft v0.7.0 workspace**, commit `fc41918814f62645b6746ed68e71e8c2c2e85d6f`, and craft-fonts commit `8dcdacd5153e64560d109541a47d806f26f048c0`. Source/font compressed bytes and SHA-256, Rust `1.95.0`, the exact binary branding patch and both native Cargo packages are locked in `manifests/word.lock.json`. Engine source, Cargo manifests/lock, MIT/Apache licenses and NOTICE are protected against branding changes. The patch removes upstream trademark artwork, changes the display identity/profile/icons, and retains original commands and crate names.

Full original source does not imply full Microsoft Word compatibility. Consult the pinned [upstream roadmap](https://github.com/storytold/wordcraft/blob/fc41918814f62645b6746ed68e71e8c2c2e85d6f/ROADMAP.md), [gaps](https://github.com/storytold/wordcraft/blob/fc41918814f62645b6746ed68e71e8c2c2e85d6f/docs/gaps.md) and [parity assessment](https://github.com/storytold/wordcraft/blob/fc41918814f62645b6746ed68e71e8c2c2e85d6f/docs/target-app-parity.md). A percentage of registered commands is not document compatibility or paid-work readiness.

## Local build

Prerequisites: Python 3.11+, Git, Rustup, Rust 1.95.0, and the target OS SDK. Mac builds require Xcode command line tools on arm64 macOS. Windows x64 builds require Visual Studio C++ Build Tools and Windows SDK `rc.exe` on Windows x64. Both full native executables are built; no GUI wrapper is generated.

```sh
python3 -m unittest discover -s tests -v
rustup toolchain install 1.95.0 --profile minimal --target aarch64-apple-darwin
python3 scripts/kio_native.py prepare --app word
python3 scripts/kio_native.py build --app word --platform macos-arm64
python3 scripts/kio_native.py package --app word --platform macos-arm64
python3 scripts/kio_native.py verify --directory dist/word-macos-arm64
```

On Windows use `python` and target `x86_64-pc-windows-msvc`, platform `windows-x64`. The build uses the original default features, `--release --locked -p wordcraft -p wordcraft-cli`, a statically linked MSVC CRT, upstream engine/DOCX/formats tests, actual native architecture/subsystem checks and a synthetic DOCX save/reopen/PDF check. It records GUI launch as untested; an interactive installation/file-opening check is a separate release verification.

`prepare --archive-cache PATH --offline` can reuse only the exact locked archive filenames/bytes/SHA. `--reset` replaces only this project's isolated `.work/word` source workspace. Local caches, build directories and `dist` are ignored and never gathered into source artifacts implicitly. `KIO_CARGO_HOME` may point to a caller-selected existing Cargo cache; it is never included as a directory in a release.

For the explicitly reviewed implicit-host Mac build already produced by the parent task, `package --platform macos-arm64 --existing-target /absolute/path/to/target/release` imports the two real native executables after their architecture and exact original CLI/app version checks. Original binary/CLI names remain stable; the KIO UI/bundle identity comes from the verified source patch. Its provenance clearly says an existing caller-selected build was imported and does not fabricate compiler/core-test/GUI results. Normal CI always uses its own `build` result. All builds require the pinned fonts with `CRAFT_FONTS_REQUIRED=1`.

## Artifacts and source

- Mac: `.work/word/package-macos-arm64/KIO Word.app`, plus full `.app` ZIP and drag-to-Applications DMG in `dist/word-macos-arm64`. The app includes the full native GUI, native CLI, original legal notices, bundled-font licenses, dependency licenses and provenance. Signing is inside-out and strictly verified. Default signing is ad-hoc; there is no Apple notarization. `KIO_MAC_SIGN_IDENTITY` optionally selects an already available caller-owned identity; notarization is still not claimed.
- Windows: a full native GUI/CLI portable ZIP in `dist/word-windows-x64`, retaining the original license/NOTICE/font/dependency material. It has no Windows publisher certificate. MSI creation is not required for this initial portable release.
- `python3 scripts/kio_native.py source --app word` creates `dist/word-source` containing `KIO-Word-0.7.0-kio.1-source.zip`: the complete modified Word workspace, pinned full font tree, Cargo.lock, matching patch, original licenses/notices, an exact allowlist of build scripts/tests/workflow, and reproducible build instructions. Third-party crates remain pinned by Cargo.lock and are fetched by Cargo. Explicit `source --vendor` additionally includes every Cargo dependency source and an offline configuration; this can be substantial. If an individual redistributed dependency requires additional corresponding source, satisfy that exact requirement before publishing instead of assuming the project's MIT/Apache license replaces it.
- Each release has a strict file allowlist manifest with exact SHA-256 and bytes, plus a matching checksum file. Unlisted files, links, wrong architecture, source mutation and checksum mismatch stop the pipeline. No private web-app content/configuration/Drive directory is an input.

Inputs are reproducible and source-archive metadata is normalized. Native binaries/signatures/DMGs are measured after packaging; byte-identical binaries across different SDKs or signing times are not promised.

## Manual GitHub workflow

`.github/workflows/full-native-word.yml` has **only `workflow_dispatch`**. `publish_draft=false` builds and uploads private workflow artifacts without creating a release. Explicit `publish_draft=true` on `main` enables the separate draft-release job after both OS jobs and the full-source job pass. Build jobs have `contents:read`; only the publication job has `contents:write`, and its token is exposed only to the final `gh` invocation. Checkout credentials are not persisted. No push, pull-request or scheduled trigger exists.

The workflow pins official actions by complete commit SHA: checkout v6.0.2, upload-artifact v6.0.0 and download-artifact v7.0.0, verified with official repository tags on 2026-10-15. Runner labels are `macos-15` (arm64) and `windows-2022` (x64), as documented by [GitHub's runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). Do not replace the Mac label with the Intel variant or claim an unexecuted OS build succeeded. [Checkout source](https://github.com/actions/checkout/tree/de0fac2e4500dabe0009e67214ff5f5447ce83dd), [upload source](https://github.com/actions/upload-artifact/tree/b7c566a772e6b6bfb58ed0dc250532a479d7789f), [download source](https://github.com/actions/download-artifact/tree/37930b1c2abaa49bbe596cd826c3c89aef350131).

The parent task reviews these files and controls remote creation, push, dispatch and public promotion. This project does not disable signing/OS security checks or reuse another project's publishing credentials.


## Full native 13-application workflow

`manifests/full-native-apps.json` locks all 13 original application archives, the exact font archive when specified upstream, branding patch and patch-audit bytes, full native Cargo arguments and original engine/format test packages. `manifests/build-prerequisites-photo.json` and `build-prerequisites-office.json` cite the pinned original Mac/Windows packaging and the shared workflow at commit `f0808a5ccbc32869248193ffab0de98d733de451`. The application callers use a mutable `@main`; this pipeline records the reviewed immutable workflow instead. No mandatory FFmpeg, ONNX Runtime DLL, vcpkg or nasm stage appears in those original default-native packaging commands. Extra tools are not inferred from feature names.

```sh
python3 scripts/full_native.py prepare --app grid
python3 scripts/full_native.py build --app grid --platform macos-arm64
python3 scripts/full_native.py package --app grid --platform macos-arm64
python3 scripts/full_native.py source --app grid
python3 scripts/full_native.py verify --app grid --platform source --directory dist/grid-source
```

`package --existing-target /absolute/path/to/target/release` also imports complete caller-selected native binaries on their actual OS. It verifies architecture and both original version contracts and records imported-build checks honestly. Workspaces live separately under `.work/full-native/<app>`; this does not modify the installed KIO web application or the earlier Electron prototype. Only `prepare --reset` removes the selected isolated source workspace. Existing release/staging folders are never overwritten automatically.

`.github/workflows/full-native-apps.yml` is manual dispatch only. Choose one app or `all` to build real arm64 Mac and x64 Windows binaries. Both GUI and CLI are mandatory. Original default features remain enabled; Photo additionally enables original native HEIF and Light enables GUI+CLI HEIF while retaining default denoise. PDF runs the original `cargo xtask models` to ship both SHA-verified OCR models plus original CC-BY-SA license/attribution sidecars. Optional Film neural features, Effect model downloads and Sound ASIO retain their original extension capability without claiming they are bundled by default.

Each app produces `KIO-<Name>-<upstream-version>-kio.1-macos-arm64.{dmg,zip}`, `-windows-x64.{msi,zip}` and `-source.zip`, with separate exact manifests/provenance/SHA files. The Mac app and portable Windows ZIP include both original executables and complete license material. Windows MSI is built with the original KIO-branded installer script and WiX 5.0.2 (UI/Util extensions); original dialogs, file associations and install/update behavior are retained. An added component group places the full original dependency/font notices in the MSI. Development artifacts are ad-hoc signed on Mac and have no Apple notarization or Windows publisher certificate.

Full original source includes 14 public Film H.264 test-oracle files under an upstream-tracked `target` path and six synthetic PDF `.p12` signing test fixtures. Only their exact upstream paths, bytes and SHA-256 in the source lock are accepted. These are public test inputs from the pinned original archives, not KIO user data or publisher credentials. The default private/build-file guard remains unchanged for every other path.

The generic source ZIP contains the entire modified selected application, pinned fonts, original licenses, the exact matching Cargo.lock and reviewed functional-correction manifests, exact branding patch and an explicit public orchestration allowlist. It omits compiler outputs, caches, private local configuration and redundant Cargo-vendor archives. Neither a prepared source nor a passing command-registry test is represented as full commercial editor compatibility. Successful native build, installation, actual file-format checks and interactive GUI validation remain separately recorded evidence.
