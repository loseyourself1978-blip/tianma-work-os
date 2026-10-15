# TWOS-V20.1-GUI-PUSH-REVIEW-01

Scope: installed Owner product Push Plan review; no Owner approval or Push,
no repeat Run/Apply/Commit, no remote configuration, no public release.

The observed 101.2 Owner instance had a successful local Commit but no origin.
Its current JavaScript matched the installed bundle. Review returned “The origin
remote is unavailable” at the top of the page, while the current Push section
returned to READY TO REVIEW PUSH PLAN. No Push Plan was persisted. This differs
from the earlier stale 101.1 JavaScript identity-form incident.

The review control now exposes checking, the returned plan, or an actionable
failure next to the button. Errors survive the final render; duplicate requests
are suppressed while in flight. A manual retry is read-only review, never Push.
Responses must match the selected Run and exact local Commit before they can
replace the displayed projection. Session expiry returns to login. A canonical
reload can reconcile a saved plan after a response was lost.

The normal plan view includes its ID/version, the authenticated Owner's exact
validated destination, branch, parent/remote baseline, proposed SHA, one-Commit
file scope and checks. Exact destination display is transient: existing persisted
receipts/audit records retain their redacted descriptors and URL digests. Missing
origin can be explained on reload using local inspection only; this does not
create a plan or contact an external destination.

The existing supported transport boundary remains file, HTTPS or SSH with one
matching fetch/push destination and the approved configuration. Review never
changes it. An absent remote, unsupported URL, changed approved configuration,
missing main branch or moved baseline remains a blocker. This change does not
add initial-empty-remote or forced-push semantics, a remote setup form, automatic
approval, or an exception to the exact Commit/plan/approval bindings.

For the actual Owner project, keep Push NOT_EXECUTED. A missing destination must
be resolved by an explicitly authorized supported setup/continuation workflow;
do not guess GitHub, bind the TWOS public source repository, or modify a remote
to bypass this Commit's approved configuration. An error displayed correctly
does not mean that this project's Push has passed.

The /twos entry is no-store and now references each packaged CSS/JS file by its
SHA-256. Different content gets a different URL even when the release version is
still 1.0.1. A normal reload during upgrade selects current assets. Forced cache
refresh is not an installation requirement. Local candidate build: 101.5.

Validation includes new review-controller/boundary regression plus related Push
authorization, drift, receipt, timeout and lifecycle tests. The real frozen-App
GUI gate uses a private synthetic account/repository and a local bare target:
Review → visible plan → Approve → separate Confirm → verified target SHA.
Upgrade, ordinary browser reload, restart and rollback are checked on this
isolated data. Execution receipts and screenshots belong to the local evidence
package; historical test counts are not substituted for current results.

The prior 101.2 identity repair stopped its real-GUI acceptance at identity and
local Commit. Its report explicitly left Push unexecuted because origin was
absent. The missing-origin backend rejection did not have a real current-step
GUI assertion, so passing identity tests did not establish Push error visibility.
This repair adds that failure/retry controller regression and frozen-App GUI
evidence, as well as the separate complete local-target Push regression.

The decorative overlay was not observed intercepting the real Review click;
that click returned a product error. No unrelated page/mascot redesign is made.
TWOS-UX-20260926-01/02/03 remain RECORDED_FOR_CONSOLIDATED_REDESIGN;
TWOS-UX-20260926-04 remains PROPOSED. The earlier same-page identity retry issue
is retained in its own record; successful Owner identity/Commit acceptance is
not reopened by this Push issue.

Owner patch flow: use Backup & Recovery → Create Backup in the existing App,
quit normally, drag the separately identified patch App to Applications and
replace only the application, then launch and log in to the same account.
Keep all data and prior DMGs. Select LDD Review → Review Run Result → Review Push
Plan. Inspect the current blocker or plan; no approval/Push is authorized by this
remediation. No registration, initialization, Run, Apply or Commit repetition.

## Local test destination continuation — build 101.6

Owner explicitly selected an independent local test repository on 2026-09-28.
The 101.5 screenshot confirmed ORIGIN_UNAVAILABLE, not a malfunctioning retry:
Managed Workspace intentionally creates no origin. Showing the rejection did
not close the product continuation gap. The same Task/Commit must continue.

The Push section now offers **Set up local test destination**. Opening it is
read-only and displays Project/Task, source repository, private destination,
parent and delivery SHA. Only **Create and bind local test destination** creates
a bare repository under the installation data root's `local-push-tests` directory
and adds the exact repository-local `remote.origin.url`. It does not select an
external destination or accept a caller-supplied path. Existing remotes are not
replaced. Parent history is explicitly disclosed and copied locally without
config, credentials, hooks, hardlinks or the delivery Commit. Main begins at the
actual Commit parent; this does not weaken initial-empty-remote or fast-forward
rules. Review / Approve / independent Confirm remain required.

A durable audit intent binds the immutable local Commit receipt, repository
identity, old/new config fingerprints, exact destination identity and confirmed
preview digest. It authorizes this exact transition without rewriting the Run,
Apply, Commit receipt or existing approvals. Changed config, destination, HEAD,
index, worktree or refs still fail closed. An exclusive Git config lock and
atomic replacement prevent partial config publication. Other processes' locks
and partial target directories are preserved. A matching interrupted intent can
be retried; an unreceipted partial directory reports a specific preserved-path
blocker instead of being overwritten. No new database table/schema migration.

Upgrade from 101.5 preserves account, Task, Run, Apply and Commit. Reverting only
the binary to 101.5 still permits reading these records; that older version does
not recognize the new authorization receipt, so Push after destination setup
must remain blocked there. Do not undo the new config or rewrite historical
receipts to make the old binary push. Retain backups and use 101.6 to continue.

This continuation does not implement task-type local-only completion, external
repository configuration, automatic approval, public release or GA acceptance.
Owner setup and Push approval/confirmation in the real Project remain manual.

## Owner local Push retest — 2026-09-29

Owner explicitly reported that the normal GUI local Push test passed on build
101.6 (source `21408218ff5c3ba64ef5af045cb3caeea2b4c98d`). Read-only reconciliation
of the installed product confirmed Project 1 / Task 1, the existing LDD Review
Commit `b5d54a4e236cd6fb338bf33b75768af1ba1784f2`, Push Plan
`pushplan_95e5f1864d1b69e42488e786d8b2af15a60231d0` v1, APPROVED status, and one
PUSHED execution with exit code 0. The installation's private local test target
`refs/heads/main` equals that Commit. HEAD, index and first_delivery.txt remain
unchanged from the captured business baseline. No configuration, approval or
Push was performed by Codex during this reconciliation.

**Owner local Push functional retest: PASS.** This records only the explicitly
reported local test outcome. It does not accept the permanent UI/UX, validate
external distribution, establish LDD automation readiness, or grant final GA
Owner Acceptance. Owner relaunch/persistence remains the next manual checkpoint;
the preceding engineering restart tests are not substituted for it.

## TWOS-UX-20260929-01 — RECORDED_FOR_CONSOLIDATED_REDESIGN

Owner requirement: make destination setup a permanent product UI/UX flow,
not a detached button added only to make a test pass. This extends
TWOS-UX-20260926-01 and -02. On 2026-09-29 Owner permitted pausing individual
repairs for a consolidated change; the chosen course is to record this item
and avoid another isolated patch/build now. Implementation remains pending.

Acceptance requirements for the consolidated change:

- Integrate destination configuration and its current status into the Project's
  delivery flow. When the destination is missing, explain the prerequisite in
  plain language and make configuration the visible primary action in both
  the current step and its overview. Do not require a failed Review first or
  present Retry as the primary way to resolve missing configuration.
- Make the destination's purpose explicit. Local test is a clearly labelled
  use option within the product flow; it must not masquerade as an external
  delivery destination. This requirement does not authorize adding arbitrary
  network destinations, silently binding a remote, or expanding permissions.
- Before saving, show the exact Project/repository, destination, copied scope
  and required Owner confirmation. After saving, transition visibly to Review;
  preserve separate review, approval and final Push confirmation.
- Render only guidance appropriate to the current state. After a verified
  delivery, show the verified destination/SHA and receipt; remove obsolete
  instructions such as "No Push occurred. Select Review Push Plan." Preserve
  audit history as history, not contradictory current instructions.
- Keep the correct task and state through refresh, task switching and restart.
  Show actionable failures in the same visible area, with safe retry only when
  applicable. Controls must remain visible and unobstructed.
- Validate the complete normal GUI path with a nontechnical user, including
  missing destination, cancelled setup, save failure, configured destination,
  review, separate approval/confirmation and verified delivery. Button-text or
  API-only tests do not establish this UI/UX acceptance.

This item's status is **pending consolidated implementation and Owner retest**.
The successful 101.6 local Push test does not waive it. No source-code, approval,
trading-authority or medical human-gate change is made by this record.

## Owner restart PASS closeout — 2026-09-29 (supersedes the earlier pending checkpoint)

The earlier same-day section remains a historical snapshot. Owner has now
supplied the explicit `OWNER_RESTART_PERSISTENCE_RETEST` receipt: normal quit and
relaunch PASS; original account, Project, Task, output, configuration, local
destination and DELIVERED receipt persistence PASS; no repeated Run, Apply,
Commit or Push. This completes that pending checkpoint. No repeat operation or
second signature for this limited sub-acceptance is required.

```yaml
LOCAL_GUI_DELIVERY_AND_RESTART_ACCEPTANCE:
  functional_result: PASS
  owner_retest: PASS
  local_functional_scope: CLOSED
  environment: OWNER_INSTALLED_PRODUCT
```

Read-only reconciliation found no identity difference: App 1.0.1 / 101.6,
source `21408218ff5c3ba64ef5af045cb3caeea2b4c98d`, Project 1 / Task 1, business
Commit `b5d54a4e236cd6fb338bf33b75768af1ba1784f2`, and Push Plan
`pushplan_95e5f1864d1b69e42488e786d8b2af15a60231d0` v1. The persisted approved
plan, single successful Push, complete receipt and verified local target SHA
remain consistent. HEAD, index and output fingerprints match the prior local
retest; database integrity is intact. The normal restart itself is attested by
Owner, not claimed as an agent-performed action.

Closed scope: normal GUI first delivery, Push to the explicitly configured local
test destination, exact target SHA verification and Owner normal-restart
persistence. Excluded: external Git-host Push acceptance, complete nontechnical
UX acceptance, refreshed provider readiness for a new Task, signed public
distribution, full GA Owner Acceptance, LDD Stage 1 and Dashu formal admission.

### Display semantics recorded for consolidated UX work

The confirmed tool configuration and historical successful readiness evidence
remain saved. However, the saved executable is no longer present at its recorded
location, and the current bundled verifier file identity differs from the saved
snapshot. These are real freshness failures for a future Run, not missing saved
configuration and not solely a stale label. Their upstream filesystem-change
cause has not been established here. No provider probe, authentication action,
tool rewrite or replacement executable selection was performed.

The header obtains passive application-scope `/api/codex/status` without a Task
ID. `configuration_out` combines saved configuration, current executable and
verification identities, execution context and registry evidence. Its inspected
freshness predicate has no elapsed-time TTL. A generic `Needs Setup` label fails
to explain the distinction between saved setup, current tool readiness and an
already completed delivery. The next design must surface the actual invalidation
reason and scope without retracting historical results or automatically probing.

The displayed Ahead/behind `1/0` comes from the immutable Push Plan's preflight
snapshot (`_push_plan_out` → `checks` → `pushAheadBehind` UI element). The saved
post-Push receipt instead records `0/0`, `complete=true`, and the exact target SHA.
The Plan must not be rewritten. Label the two snapshots and their observation
times; do not present preflight values as a live current measurement.

Build 101.5's implemented resource fix remains part of the baseline: `/twos` is
`no-store`, and packaged CSS/JS URLs use content SHA-256. It is not an unresolved
cache workaround or a requirement for Owner force-refresh.

### Single next handoff

`TWOS-V20.1-GUI-UX-CONSOLIDATION-R1` is **PREPARED / NOT_STARTED**.
See [consolidated scope and acceptance checklist](VOL20_GUI_UX_CONSOLIDATION_HANDOFF.md).
TWOS-UX-20260929-01 remains RECORDED_FOR_CONSOLIDATED_REDESIGN and links the
existing 20260926-01/02/03 items without replacing them. Risk-based delegation is
a separate design item, not enabled behavior. 20260926-04 remains PROPOSED.

This closeout changes documentation only. It creates no App build, business
action, local Git commit, Push, Tag or release. The records are written locally;
they have not entered a new local Git commit and have not been pushed remotely.
