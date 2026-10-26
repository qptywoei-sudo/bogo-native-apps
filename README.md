# Bogo native applications

This public repository builds Bogo CAD, Design, Vector, Film, Light, PDF, Effect,
UI, Word, Sound, Deck, Grid, Launcher and Photo from their complete pinned native
workspaces. The owner-provided original icons and pale orange application chrome
are recorded as exact, separately verified source overlays.

Build and verification instructions are in [docs/bogo-rebrand.md](docs/bogo-rebrand.md).
The [application manifest](manifests/bogo-native-apps.json) identifies every full
source overlay. The [manual workflow](.github/workflows/bogo-native-apps.yml) builds
real Windows x64 MSI/portable packages, macOS Apple Silicon DMG/ZIP packages, and
matching complete source. It does not publish automatically. A prepared source
or running CI job is not a completed or published native installer.

Measured Bogo release entries will appear in
[the download catalog](manifests/bogo-native-downloads.json) only after the actual
files and their SHA-256 values are verified. Empty entries mean no verified Bogo
release has been published yet. Development Mac packages are ad-hoc signed and
not notarized; Windows packages have no publisher certificate.

## Compatibility and historical releases

Existing bundle IDs, MSI UpgradeCodes, registry identities and normal user profile
paths remain stable. Launcher and PDF distinguish exact Bogo releases from this
repository from legacy KIO releases in
[qptywoei777-rgb/kio-native-apps](https://github.com/qptywoei777-rgb/kio-native-apps).
Historical versions, URLs and hashes are preserved. The first transition from the
old KIO-only Launcher requires a verified manual Bogo Launcher installation.

The previous repository documentation and its accurately dated KIO download table
are preserved in [historical native documentation](docs/legacy-native-readme.md).
Those historical installers are not Bogo rebuilds. This repository contains only
public build inputs and original open-source notices; private web records, user
profiles, credentials, compiler caches and local build outputs are excluded.
