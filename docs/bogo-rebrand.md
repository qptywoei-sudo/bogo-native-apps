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

The manual `bogo-native-apps.yml` workflow builds both OS targets and full source
with pinned actions and read-only permissions. It uploads workflow artifacts
without publishing a GitHub Release. Publishing requires measured successful
packages, repository write access and the existing explicit release policy.
Mac development packages remain ad-hoc signed and not notarized. Windows
development packages have no publisher certificate. Passing source checks is
not a claim of a completed native build, installation or interactive GUI test.

Technical KIO identities and historical copyright/source notices are retained
for compatibility and legal provenance. Existing KIO Releases keep their actual
names, URLs, versions and SHA-256 values until new Bogo files are accessible.
