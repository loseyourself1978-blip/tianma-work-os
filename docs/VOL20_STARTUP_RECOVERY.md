# TWOS-V20.1-GUI-UX-STARTUP-01

Continuation of TWOS-V20.1-GUI-UX-CONSOLIDATION-R1, not another UX redesign.

## Owner failure supersedes the handoff readiness

The 101.8 engineering report remains a historical result for its recorded
environment (1,336 passed, 7 skipped, separate artifact and browser checks).
The Owner's Finder replacement reached the native launcher but failed before
the web service became available. Current Owner handoff is BLOCKED_AT_STARTUP,
UX acceptance BLOCKED_BEFORE_UI; prior 101.6 local delivery/restart acceptance
remains CLOSED_AND_PRESERVED. Public distribution is deferred and final GA is
not granted. The immutable 101.8 DMG and evidence must not be replaced.

## Cause and test gap

The installed bundle's manifest and local signature match 101.8. The original
workspace path and inode survived, but its saved `st_dev` differs from the
current mounted filesystem. Legacy authorization hashes path, device and inode.
The exact read-only invariant throws WORKSPACE_IDENTITY_CHANGED; desktop startup
previously hid that FirstRunError behind DESKTOP_RUNTIME_FAILED. Optional missing
Codex and changed verifier state are a separate new-execution blocker.

Prior packaged lifecycle tests ran the frozen service with diagnostic-root and
restarted processes in one mount session. They did not prove a native
LaunchServices cold start after a mount device number changed. A Mac reboot was
observed before the Owner failure; the old volume UUID was not recorded, so equal
path/inode is not treated as automatic authority to adopt a volume.

## Bounded implementation

- Keep the legacy identity failure; desktop routes that exact failure to a
  standalone authenticated workspace recovery page. No scheduler, intake worker,
  provider or delivery mutation is started in this mode.
- Show existing task/run summaries and cryptographically verified stored Push
  receipts. No filesystem payload import or remote read is needed.
- Existing Owner login, same-origin JSON, exact preview digest, unchanged
  directory, private path and one SQLite transaction are required to confirm.
  Confirmation updates only current workspace authorization and appends an audit
  receipt; history is not rewritten. No arbitrary path input is added.
- After explicit confirmation, an available APFS volume UUID, same path and same
  inode may establish continuity across later device renumbering. A different
  volume, replaced inode, unsafe path, missing proof or changed preview fails
  closed. Legacy records without a receipt never receive this fallback.
- Old execution approvals stay historical; a new recovery epoch requires an
  explicit tool check and new Pack for future work. Completed Push receipts are
  displayed as recorded evidence, without re-execution or a live remote check.
- Native UI includes build; bounded per-launch diagnostics retain stage,
  product error code and child exit/signal. No exception text, credentials,
  provider output or environment dump is persisted.

No schema migration, global Git change, automatic approval, publication or real
provider call is part of this repair. The installed Owner App is not hot edited.
Owner alone confirms the original workspace and replaces the candidate App.

## Validation contract

Reproduce legacy device drift before repair; verify explicit review/cancel,
authorization/CSRF, stale preview, lock failure, directory/volume replacement,
idempotent confirmation, old approval invalidation and preserved history.
Exercise the exact final bundle through LaunchServices in an isolated fixture,
including unavailable saved executable, changed verifier, completed delivery,
cold start, normal shutdown/relaunch and content-fingerprinted consolidated UI.
Record deployment path and diagnostic-root differences; final /Applications
Owner launch remains one necessary Owner retest, not an engineering claim.

Status: implementation and validation in progress. The private startup-recovery
receipt carries actual results and artifact identities after validation.

The internal 101.9 native GUI test reached recovery and restarted successfully,
but exposed a missing confirmation/status-label contract in the archived Push
projection. The replacement preserves the complete stored DELIVERED contract
and bypasses live Push reconciliation for that archived receipt. A regression
checks frontend state, exact SHA, single attempt and no transport. Internal
101.9 is not an Owner handoff; the replacement uses unique build 101.10.

## 2026-09-30 — engineering verification and bounded local handoff

The preceding in-progress status is a historical checkpoint. Final runtime
source is `9c73d6e70402d63055b57ffe5ff5d44bb7b174ec`, App 1.0.1 / 101.10.
The frozen complete gate passed: **1,354 passed, 0 failed, 1 skipped** in
5,708.00 seconds; tracked input fingerprint remained unchanged. This run included
the six current packaged-artifact tests. The one skip is the historical
101.1-to-101.2 artifact pair, not evidence for the current upgrade.

Two early diagnostic full attempts were interrupted after polling-timeout
failures; they remain failed/incomplete records. Targeted old/current-source
comparisons and the final full run passed without changing assertions, deadlines
or runtime code. Final execution followed closure of the agent's completed GUI
test tabs and automation connection. Timing sensitivity is documented; no causal
claim that tab cleanup fixes a product bug is made.

Exact final App, copied with Finder into an isolated user Applications directory,
passed native LaunchServices startup, existing synthetic Owner login, visible
lock failure/retry, explicit workspace confirmation, normal quit/relaunch and
preserved DELIVERED history. Missing executable/changed verifier affected only
future execution eligibility. One original synthetic Push/target remained;
no Owner business action was repeated. Original installation/data/Git hashes
were checked again after the complete gate and remained unchanged.

Candidate: `Tianma-Work-OS-1.0.1-build-101.10.dmg`, 23,695,469 bytes,
SHA256 `b9899aa0801cca72ac396e9a324a88a42c99dbd5316a4a5e0fe7e246fa6a5f21`.
Source-input SHA256:
`914fb6e9b1bf0e13cd5088c9e19d05535a82d215e69ce9ce9d0d56ab655927fc`.
The failed 101.8 candidate is superseded for handoff, with its bytes and historical
reports preserved. Internal 101.9 is not a deliverable. No schema migration.

Engineering: PASS. Candidate: READY_FOR_OWNER_PATCH_INSTALL. Original installed
101.8 remains BLOCKED_AT_STARTUP until Owner replaces it and performs the single
startup/history retest. Defect: ENGINEERING_VERIFIED / OWNER_RETEST_PENDING.
This is not Owner UX/GA acceptance, public distribution, external Push validation
or LDD/Dashu formal admission. Owner need not replay the closed 101.6 delivery.
