# Six-language native application verification

The required order is `vi`, `en`, `ko`, `ja`, `zh-TW`, `zh-CN`. Native package
availability and complete localization are separate properties. A successful
installer/engine build must never be described as complete six-language GUI QA.

Run with Python 3.11+ after preparing the actual sources:

```sh
python3 scripts/audit_localization.py --output qa/localization.json
python3 scripts/audit_localization.py --app launcher --require-complete --output qa/launcher-localization.json
python3 -m unittest discover -s tests -p test_localization_audit.py -v
```

The audit reads the real TSV, JSON, TOML and applicable Rust catalogs. It records
missing languages/keys, empty values, duplicates, mismatched placeholder counts,
untranslated English for review, and direct UI literals for contextual review.
Command IDs, paths, extensions, URLs, user document text and official product
names must remain unchanged. Only explicit, per-application official-name
exceptions suppress an untranslated-English finding. Traditional and Simplified
Chinese always remain independent catalogs.

Counts use the union of existing catalog keys plus literal translation calls.
This is an actionable static inventory; dynamic labels and direct widget calls
need source review and actual screen checks. A zero-key application is not
localized: Sound and Deck have no translation infrastructure in the pinned
workspaces and contain direct English UI strings. The audit must not give those
applications a false green result.

On 2026-10-18 all 14 public native applications had both operating-system
packages and matching source releases. The static audit found incomplete
six-language localization in every pinned editor; publishing their existing
installers did not establish localization completeness.

Launcher revision `0.4.1-kio.2` adds 308 matching keys for each required language,
including Vietnamese, Korean, Taiwan Traditional Chinese, tray text, messages,
plural forms and font recovery instructions. The original native locale API,
automatic preference, device settings, downloads, checksum validation and KIO
bundle identity are retained. Chinese region/script normalization now selects
Traditional Chinese for Taiwan, Hong Kong, Macau and Hant. Native font selection
uses installed regional Chinese/Korean fonts without redistributing them.
The selected language appears first; the other five retain the required order.

`scripts/launcher_six_languages.py` reproduces the authored additions from a
fixed key inventory. The six-language audit is a blocking native CI step for this
revision. Original full native core/backend/UI tests still run. Completion of a
source/catalog check alone must not claim native compilation, installation,
all-screen layout inspection, signing/notarization, or real account login.

KIO Tools is maintained in its own Python/C++/WebView repository. Studio remains
in its existing private owner-only distribution; never add its private installer,
source or credentials to this public repository or the public Launcher feed.
