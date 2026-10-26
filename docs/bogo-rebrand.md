# Bogo native build inputs

The Bogo build prepares the exact existing KIO source and functional fixes first,
then applies a separately measured binary Git overlay for each of the 14 apps.
`manifests/bogo-native-apps.json` records every changed path, before/after bytes
and SHA-256, original input lock, resulting source tree, and installer identity.
Original branding patches, source/font pins, engine code, Cargo dependencies,
licences, notices and old release identities remain available unchanged.

The owner-supplied Drive PNG originals are in `assets/bogo-program-icons/`.
`scripts/bogo_assets.py` validates all 14 exact RGBA originals and derives only
resolution variants for seven Windows ICO sizes and seven macOS ICNS sizes.
The ICNS `ic10` entry contains the exact original 1024 PNG bytes.

The UI name is Bogo, including Bogo CAD. Internal `com.kio.*` bundle IDs,
MSI UpgradeCodes, component GUIDs, registry keys, portable markers and account /
profile paths remain stable. The existing same-numeric-version MSI upgrade
policy remains enabled. Launcher and PDF accept strict, matching KIO and Bogo
release filename/version families; Bogo packaging revisions follow KIO revisions
for the same upstream version. Launcher preserves a verified old macOS bundle
in a hidden previous-version backup, with rollback if the new swap fails.
Disk images use native HFS+ creation rather than hybrid-image conversion so the
mounted app retains its strict signature. Launcher asks macOS to create a unique,
previously absent `/Volumes/Bogo-*` mount point; private SSD cache directories
are not valid mount points for diskimages-helper on the verified host.

For isolated native GUI verification CAD, PDF, UI, Deck and Launcher accept the
explicit pair `BOGO_QA_MODE=1` and an absolute private `BOGO_QA_ROOT`. This routes
preferences, logs, recovery, caches and native UI persistence into an app-specific
child of that root. Partial or invalid opt-in exits before any personal-path
fallback. Ordinary startup preserves every legacy storage identity, including
PDF's `KIO PDF` storage directory. Unix roots must be private mode 0700 and cannot
be a symlink. Launcher QA refuses any existing Launcher process or occupied
47514 instance port without connecting to it, signalling it or forwarding a
request. The helper never changes HOME or platform profile environment settings.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/bogo_native.py prepare --app grid
python3 scripts/bogo_native.py build --app grid --platform macos-arm64
python3 scripts/bogo_native.py package --app grid --platform macos-arm64
python3 scripts/bogo_native.py verify --app grid --platform macos-arm64 --directory dist/grid-macos-arm64
python3 scripts/bogo_native.py source --app grid
```

Use Windows x64 and `--platform windows-x64` for real MSI/portable builds;
the native OS/architecture assertion is enforced. Rust 1.95.0 is required.
Windows additionally requires the existing VS C++/SDK and WiX 5.0.2 prerequisites.
Generated Cargo outputs may share an ignored `.cache/bogo-target/` directory;
each app's source and build receipt remain separate and binary hashes are checked
again before packaging.

The manual/reusable `bogo-native-apps.yml` workflow builds both OS targets and full source
with pinned actions and read-only permissions. It uploads workflow artifacts
without publishing a GitHub Release. Publishing requires measured successful
packages, repository write access and the existing explicit release policy.
The owner-authorized public repository is `qptywoei-sudo/bogo-native-apps`.
Its default is the reviewed `codex/bogo-native-rebrand-20261026` branch; no main
branch is pushed or merged. The old repository remains unchanged. Once this
branch is pushed and registered as default, run the direct manual workflow:

```sh
gh workflow run bogo-native-apps.yml --repo qptywoei-sudo/bogo-native-apps --ref codex/bogo-native-rebrand-20261026 -f app=all -f platform=windows-x64
```

The compatibility `full-native-launcher.yml` path also routes to that workflow
with publication disabled. Bogo updates use the exact new repository catalog at
`https://raw.githubusercontent.com/qptywoei-sudo/bogo-native-apps/refs/heads/codex/bogo-native-rebrand-20261026/manifests/bogo-native-downloads.json`.
Its initial empty program list claims no published installers. Exact old KIO
releases remain available only from the existing legacy repository/feed.

Each ephemeral Windows job additionally runs `smoke_bogo_windows.py` after its
real package checks. It authenticates the exact published legacy MSI against
`bogo-legacy-upgrade-inputs.json`, installs that MSI into the runner's private
temporary directory and performs the new MSI upgrade. It checks old/new product
state, unchanged UpgradeCode, authored Bogo desktop/Start Menu links and their cached
icons, actual installed EXE version/architecture and all PE icon frame bytes,
then starts both the installed and extracted portable GUI executables. It
requires a visible Bogo window owned by each new process and uninstalls only
products created by the test. Reports and logs are retained even on failure.
The script refuses other operating systems, non-GitHub-hosted runners, missing explicit
opt-in, existing installations and an output outside the fresh runner directory.
These are prepared CI checks until an actual Windows job succeeds.

GitHub's [manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow?tool=cli)
defines `--ref` for nondefault branches; [same-repository reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
resolve from the same commit as their caller. No push/schedule trigger, main merge,
secrets inheritance, automatic release or production promotion is added here.
Mac development packages remain ad-hoc signed and not notarized. Windows
development packages have no publisher certificate. Passing source checks is
not a claim of a completed native build, installation or interactive GUI test.

Technical KIO identities and historical copyright/source notices are retained
for compatibility and legal provenance. Existing KIO Releases keep their actual
names, URLs, versions and SHA-256 values until new Bogo files are accessible.
