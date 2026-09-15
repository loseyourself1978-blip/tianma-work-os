# Vol.19 19.2B — Owner Acceptance corrections

Owner Acceptance is NOT PASS. The prior acceptance is paused and preserved.
Only the Owner may accept the refreshed installation.

Baseline: `f7f13c6675a7f4cfa3b252e1008da9f62b517567`, local `main`, five
commits ahead of `origin/main` at `3cf914b6c5667059923ab209f8e9008b33a05cef`.
The index and worktree were clean. Routing: SINGLE_PRIMARY; the primary is
the only writer, integrator and validation runner.

## Preserved acceptance and diagnosis

Before any source edit, the primary preserved a consistent SQLite backup,
the complete isolated acceptance filesystem, a file-hash inventory and an
ownership/stop receipt. The verified installation's runtime was then stopped
and its listener released. Normal Owner data and unrelated processes were
untouched. Evidence locations and temporary credentials remain outside Git.

The persisted sequence on 2026-09-15 establishes **Case B**:

| Event | UTC time / persisted result |
| --- | --- |
| Apply Plan approval | 03:10:09, APPROVED |
| Apply completion | 03:11:51, APPLIED |
| Post-Apply verification | 03:15:54, PASSED |
| Source target | Exact required PASS text with one newline |
| Commit proposal, Stage, Commit, Push | Zero executions/plans |

The subsequent delivery GET failed with 409. A read-only replay reproduced
`GIT_ENVIRONMENT_BLOCKED`: the inherited process contained a Git override.
The delivery projection propagated the downstream Commit error and lost its
Apply/validation presentation. The browser then selected the legacy Commit
panel, whose initial labels said Not applied / Not verified. The canonical
panel also failed to unwrap the persisted post-Apply verification envelope.
The database had retained the completed evidence throughout.

The host's system Git currently stops at an unaccepted Xcode license. After
removing inherited Git overrides from the inspection subprocess and selecting
the already installed bundled Git, the same preserved evidence projected
READY_FOR_PROPOSAL. No license was accepted and no software was installed or
upgraded. The refreshed acceptance launcher uses the existing working tools
and a clean Git process environment. Product Git security guards remain intact.

## Corrections

- Tool Setup renders initial, checking, completed and invalidated states from
  its current explicit selection and persisted readiness. A successful Check
  becomes neutral and disabled; Save is enabled only for an unsaved, checked
  configuration. Rechecking a materially identical saved configuration keeps
  its existing Owner confirmation, without changing any bound Pack snapshot.
- The guide exposes the authorized workspace, current source repository and
  target paths as selectable text under Advanced. Before Apply, path hints are
  labeled as requests from Task scope; after Apply, exact targets and outcomes
  come from the persisted Apply journal. Paths cannot escape the authorized
  root. No acceptance path is hard-coded into product UI or this guide.
- Delivery GET preserves Apply and validation when Commit preflight is blocked
  and returns that blocker with no Commit action. Canonical UI reads the actual
  verification envelope, retains truthful state labels, and requires APPLIED
  plus PASSED before Review Commit. Failed status loads cannot enable legacy
  staging/Commit controls. Apply, Validate Applied Changes and Review Commit
  remain distinct explicit actions.

No Run, readiness request, Stage, Commit or Push is triggered by these
projections. Existing execution, verification, immutable binding, authorization
and Git mutation services remain the accepted pipeline. First Owner remains
one-time; no accepted 19.2A behavior or test contract is changed.

## Validation

Status: IMPLEMENTATION PASS / READY FOR OWNER ACCEPTANCE.

| Final serial gate | Result |
| --- | --- |
| New correction cases | 25 passed |
| Complete 19.2B group | 64 passed, including the 25 correction cases |
| Focused group plus legacy Commit UI compatibility | 72 passed in 176.54 seconds |
| Accepted 19.2A | 54 passed in 74.38 seconds |
| Accepted 19.1 | 124 passed in 773.88 seconds |
| Runtime/self-hosting | 124 passed in 360.24 seconds |
| Complete repository suite | 999 passed / 0 failed / 0 skipped / 0 xfail in 3262.45 seconds |
| Syntax / whitespace | Node syntax, Python compileall and Git diff checks passed |
| Resource reconciliation | No remaining test processes or fixture file/SQLite handles; no active source Git operation |

The implementation and test file hashes matched the frozen validation
candidate. The only final warning was the existing Starlette deprecation of
its httpx TestClient integration. No real Codex capacity was used.

An earlier full run identified two legacy UI compatibility assertions and was
gracefully interrupted after preserving its diagnostics. The correction keeps
the established Commit diagnostic prefix while requiring resolution of the
specific blocker, and names the scoped source-file field `source_target_path`.
Both original assertions passed unchanged; all mandatory groups and the
complete suite then passed on the final candidate. No accepted test or safety
requirement was weakened.

The public-action integration proves independent Verification, explicit Apply
and post-Apply validation, preservation through Commit preflight failure,
refresh and restart, eligible explicit Commit review, and no automatic Stage,
Commit or Push. The complete deterministic delivery fixture also proves the
exact local-only remote SHA. Real-browser geometry passes at 1280px and 390px,
including expanded long source/target paths.

## Refreshed acceptance boundary

The refreshed persistent installation must be created from the corrective
commit, with one temporary Owner, one authorized workspace, one Task and zero
readiness checks, Packs, Runs, Apply, Commit or Push executions. The handoff
must read current paths and counts from that installation. Use the updated
browser guide; do not reuse the retired acceptance source path.

19.2 remains open pending Owner acceptance and closeout. Older-install
migration, backup/restore, signed installer/DMG, credentialed external Git-host
Push, live multi-model aggregation, email/calendar, release packaging,
TWOS 1.0 RC and version 1.0.0 remain outside this gate.
