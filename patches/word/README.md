# KIO Word reproducible branding patch

Input is the original GitHub source archive for `storytold/wordcraft` commit `fc41918814f62645b6746ed68e71e8c2c2e85d6f` (v0.7.0). Verify its SHA-256 against manifest.json before safe extraction. In the extracted source root run:

```sh
git apply --check /absolute/path/wordcraft-v0.7.0-kio-word.patch
git apply --binary /absolute/path/wordcraft-v0.7.0-kio-word.patch
```

The patch includes binary icons and all new provenance files; no separate icon copy step is required. It has been applied to a fresh extraction and verified against every fork file hash. Source remains a complete native Rust workspace. Cargo package names and lockfile stay unchanged. The complete original MIT/Apache licenses, NOTICE, credits and all engine files are byte-identical. See manifest.json for the changed-path allowlist and exact before/after hashes, and KIO-FORK.md in the patched source for known upstream limits. Use the original upstream font pin before the full desktop/CLI build. No GitHub push, dispatch, installation or compile was performed by the branding agent.
