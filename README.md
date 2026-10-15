# Full native KIO applications

This separate build project packages complete upstream applications. It does not use the earlier KIO Apps 0.1 Electron editor prototype. Word is the first configured pipeline; the 13-entry catalog is an acquisition/build roadmap, not a completion list. No GitHub repository, workflow run or release is created by preparing these files.

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
