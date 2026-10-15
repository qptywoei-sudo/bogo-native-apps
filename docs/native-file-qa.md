# Manual QA of actual native CI packages

`native-file-qa.yml` is separate from compilation and publication. Manually select
a successful native build run ID, one of the 13 Craft applications and its actual
Mac arm64 or Windows x64 platform. It checks out this repository's current main.
It never builds, installs, launches the GUI, downloads models, changes a release,
or accepts a custom repository, URL, command or executable path.

The first step calls the existing `collect_ci_artifact.py` implementation. Its
read-only token performs only fixed-repository artifact GETs. It requires the
selected current-attempt native job to have succeeded and verifies the actual
artifact bytes, hashes, package provenance and exact current source lock. The
whole workflow need not have completed. Old commits with a different source or
branding lock are rejected. These 13 apps must come from `full-native-apps.yml`;
the older dedicated `full-native-word.yml` is not accepted by that collector.

The tokenless second step rechecks the collection, validates the entire inner
portable ZIP, then extracts its whole bundle into a new temporary folder. ZIP
traversal, links, special files, duplicate/case/Unicode aliases, file/directory
collisions, unsupported encryption/compression and excessive expansion fail
before any extraction. GUI and CLI paths are fixed by the selected package
contract and authenticated by the release manifest's whole-ZIP SHA. Embedded
build provenance and architecture are checked too. On Windows the unsigned
executable bytes must also match the compiled binary manifest. On Mac the
existing ad-hoc signature is verified; no re-signing or xattr changes occur.

Only the matching CLI runs, with isolated profile/temp folders and no GitHub,
Actions or user credentials in its environment. Ten editors use
`smoke_craft.py`; Grid and Deck use the existing `smoke_office.py`; Word uses
`smoke_word.py`. The scenarios create synthetic files, edit/save/reopen them,
export supported formats, and assert content, structure, pixels or calculations.
They make no claim of complete commercial application compatibility. Launcher
is excluded because its full original application has no document CLI.

An actual successful scenario must produce a matching CLI hash, multiple
successful native command steps and passing content assertions. A plan cannot
pass this workflow. Any collection, archive, command, timeout or assertion error
fails the job and records a failed QA report. No application scenario has been
executed merely by adding or unit-testing this workflow.

The QA artifact contains reports, the extracted-bundle hash inventory, command
logs and generated synthetic files. It does not re-upload the downloaded native
packages or install them. `report.json` identifies the native run, job, artifact,
source commit, CLI hash and actual outcome. Existing build/release workflows and
their source locks remain unchanged.
