# Bogo native verification checkpoint

The reviewed source snapshot is commit
`30dac08bbb8c7211f158e62947cfbf2388efa5eb`. Its 338 native orchestration,
published-source, icon, installer-compatibility and compiled QA helper checks
passed with no failures or skips. All 14 separately measured overlays retain
the pinned original engines, dependency locks, legal notices and legacy installed
identities. This checkpoint records source verification, not installer acceptance.

The owner-authorized public repository is
[`qptywoei-sudo/bogo-native-apps`](https://github.com/qptywoei-sudo/bogo-native-apps).
Its default branch is `codex/bogo-native-rebrand-20261026`. The legacy repository
and its historical releases remain unchanged. The initial public download
catalog has an empty program list and advertises no unverified files.

Windows CI has not started at this checkpoint. After the initial branch push and
default-branch selection, GitHub returned zero indexed workflows and a manual
dispatch returned HTTP 404. The workflow file is present in the reviewed default
branch. The next default-branch source update will be followed by an explicit
workflow-registration check and manual Windows dispatch. No main-branch push or
automatic publication is used.

Previously built macOS candidates are retained as measured development evidence.
Candidates superseded by the final repository, installer or UI source changes
require another source-matching build/package check. Final macOS acceptance also
requires disk-image integrity, mounted strict signature and icon readback, a copy
from that image into task-owned Applications storage, and an actual isolated
native GUI run. Windows acceptance requires the actual MSI upgrade, installed
and portable execution, PE icon readback and associated receipts. These pending
checks are not represented as passed.

The existing development signing policy remains unchanged: macOS ad-hoc signing
without notarization, and Windows packages without a publisher certificate.
Measured release files and download entries will be published only after their
required checks and actual public URL/hash readback succeed.
