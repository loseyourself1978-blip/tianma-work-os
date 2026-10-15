# TWOS-V20.1-GUI-UX-CONSOLIDATION-R1

Status: **PREPARED / NOT_STARTED**. Scope and acceptance checklist prepared;
implementation has not begun. Owner chose to pause isolated repairs and combine
these changes in one product redesign. This document does not authorize a
release, external Push, automatic approval or a provider call.

## Baseline and completed scope

App 1.0.1 / build 101.6, source
`21408218ff5c3ba64ef5af045cb3caeea2b4c98d`.
[Owner local delivery and restart closeout](VOL20_OWNER_GUI_PUSH_REVIEW_UNBLOCK.md)
records the limited local functional acceptance as CLOSED. Preserve that
delivered history; the next work must not ask Owner to repeat it merely to
initialize redesigned UI.

TWOS-UX-20260929-01 is the consolidation requirement. Related existing records
remain in [the original requirements list](VOL20_OWNER_GUI_COMMIT_UNBLOCK.md):
20260926-01 (in-step navigation), -02 (daily workflow), -03 (delegated-review
design). All remain RECORDED_FOR_CONSOLIDATED_REDESIGN. 20260926-04 (completion
endpoints by Task type) remains **PROPOSED, not approved for implementation**.

## One consolidated product scope

| Item | Evidence / problem | Required behavior and acceptance |
| --- | --- | --- |
| Destination lifecycle | 101.6 adds a secondary local-test setup button while missing-origin Retry remains visually primary. | Integrate destination setup and status into Project/delivery flow. Detect the known missing prerequisite before inviting repeated Review. The overview and current step offer the same clear primary action. Show purpose, scope and exact destination before explicit save. Local testing is clearly labelled; no assumed external remote or silent configuration. |
| In-step action and errors | Owner repeatedly reached the same blocker; the corrective action was hard to find. | Actions, validation, errors and next steps stay visible in the current step. Handle cancel, failure, retry, saved setup, reviewed plan and completion. Do not route users through a long-page search. |
| State-coherent guidance | Delivered screen retained “No Push occurred. Select Review Push Plan.” | Derive current guidance from authoritative current state. Keep old activity in history. Completed deliveries show their verified receipt without contradictory instructions. |
| Context persistence | The accepted account/Project/Task and delivery must survive redesigned navigation. | Normal refresh, Task switching, restart, upgrade and necessary rollback preserve the correct selection and readable history. Do not reset accounts or rerun work. No approval leaks across Tasks. |
| Layout and hit areas | Cramped progress navigation and decorative overlap were reported; overlay causality for Review failure was not established. | Validate scroll position, viewport sizes, keyboard access and click hit areas. Navigation and decoration never hide or intercept essential controls. |
| First-use vs everyday flow | Current workflow exposes many internal stages as repeated manual steps. | Keep a complete first setup/acceptance guide; design daily work around request → processing → result or decision needed. Retain internal state and audit. Streamlining must respect existing explicit approval boundaries. |
| Delegated review design | 20260926-03 records risk-based delegation as a separate requirement. | Produce a separate policy/design decision within this handoff. Low-risk scope must be explicit; high risk, scope/budget excess, validation failure, review disagreement and uncertainty escalate to humans. AI_APPROVED is distinct from OWNER_APPROVED; the executor cannot enlarge authority by self-rating. Do not enable delegation in this closeout or imply the design is already approved. |
| Tool readiness semantics | Saved configuration exists, but its executable location is absent and verifier identity changed. Header passive status is application-scoped. | Distinguish “configuration saved,” “current readiness needs recheck,” and historical completed-delivery status. Display scope, last check and evidenced invalidation reason; do not mask a real missing dependency as merely visual. Rechecking remains explicit, with no automatic provider call or authentication. |
| Ahead/behind semantics | UI shows immutable plan preflight 1/0 while post-Push receipt records 0/0 and complete=true. | Label preflight and post-Push observation separately with their times. Never rewrite plan history, imply a live check when none ran, or push again to change a number. |
| Upgrade asset consistency | 101.5 already implements content-hashed assets and no-store entry HTML. | Preserve it. Normal relaunch/reload across builds must load matching packaged resources, without forced cache-clearing as a product step. |

## Evidence and implementation references

- `static_cockpit/vol12_static_mvp/twos_command_center.js`:
  `renderHeaderStatus`, base `/api/codex/status` request, destination controls,
  `renderOwnerPushReviewFeedback`, First Delivery guide and `pushAheadBehind`.
- `twos_runtime/app.py`: passive Fresh Install `codex_status`, application vs
  Task scoping, content-hashed static resources.
- `twos_runtime/guided_delivery.py`: `configuration_out`, `snapshot_is_current`.
- `twos_runtime/codex_connectivity.py`: file/executable/context identity and
  `connectivity_evidence_is_current`; the inspected predicate is not a time TTL.
- `twos_runtime/push_delivery.py`: `_push_plan_out` exposes immutable preflight
  checks; post-Push reconciliation persists separate receipt facts.

Private runtime details and the exact Owner receipt stay in the local evidence
archive. Do not place credentials, account information, runtime logs or a full
database in public product documentation.

## Acceptance checklist for the future consolidated change

- [ ] Review one coherent first-use and everyday-flow design, including visible
  destination setup, current-step actions, error recovery and truthful status.
- [ ] Exercise a normal GUI missing-destination path through explicit setup,
  Review, separate approval and Confirm using synthetic data and a local target.
- [ ] Exercise cancellation, save failure, safe retry and all intermediate
  states without unintended configuration, approval or Push.
- [ ] Verify delivered views contain current receipt guidance and distinguish
  plan snapshots from post-Push evidence; no contradictory stale call to action.
- [ ] Verify saved-but-invalid tool configuration is explained accurately;
  no automatic probe, login or historical-delivery invalidation.
- [ ] Verify refresh, Task switch, restart, build upgrade/cache behavior and
  appropriate rollback on isolated data; preserve accepted business history.
- [ ] Check normal-size and constrained layouts, scroll/focus behavior, keyboard
  operation and unobstructed controls through actual GUI interaction.
- [ ] Keep security, CSRF, repository boundaries, exact Commit/target/plan
  bindings, approval invalidation and independently confirmed Push intact.
- [ ] Treat risk-based delegation as a separate design gate. No AI decision may
  be recorded as Owner approval; no scope expansion by the executing model.
- [ ] Run regression proportionate to the eventual integrated changes. Retain
  real GUI evidence; API or text-presence assertions alone are insufficient.
- [ ] Obtain Owner acceptance of the consolidated nontechnical UX. Prior local
  functional PASS does not waive this future design acceptance.

No external Git-host validation, public signing/notarization, GA declaration,
LDD Stage 1, Dashu formal validation or trading/medical authority expansion is
included. LDD order authority remains NONE and medical human gates remain intact.

## Current record status

Written to the local development repository: yes. Product code changed by this
closeout: no. New build: no. Local Git commit for this handoff: not created.
Remote Push: not performed. No isolated UX patch is being implemented now.

## 2026-09-29 — Consolidated implementation authorized

The Owner's subsequent EXECUTE NOW instruction starts the single consolidated
implementation described in [the implementation traceability record](VOL20_GUI_UX_CONSOLIDATION_IMPLEMENTATION.md).
The PREPARED / NOT_STARTED text above is the historical handoff snapshot, not
the current execution status. No completed 101.6 acceptance is reopened.
Owner UX acceptance remains pending; endpoint proposal -04 remains PROPOSED;
[delegated review](VOL20_DELEGATED_REVIEW_DESIGN.md) remains DESIGN_ONLY / DISABLED.


## Integrated implementation handoff — 2026-09-29

The earlier PREPARED receipt is historical. Authorized consolidated implementation
has now completed engineering validation as documented in
VOL20_GUI_UX_CONSOLIDATION_IMPLEMENTATION.md. The single final local candidate is
1.0.1 / 101.8; Owner differential UX acceptance is PENDING. No second patch or
new workstream is opened by this handoff, and the accepted 101.6 business delivery
must not be replayed. The parent requirement stays open for Owner UX acceptance.
Risk-tiered delegation remains DESIGN_ONLY / DISABLED, and 20260926-04 remains
PROPOSED. Public distribution and final GA remain outside this local handoff.
# 2026-09-30 Owner startup failure continuation

The previous 101.8 engineering and handoff sections above are historical.
Owner's actual Finder replacement failed before UI startup. Current state:
OWNER_HANDOFF=BLOCKED_AT_STARTUP; OWNER_UX_ACCEPTANCE=BLOCKED_BEFORE_UI.
Prior 101.6 local functional/restart acceptance stays CLOSED_AND_PRESERVED.
See VOL20_STARTUP_RECOVERY.md for TWOS-V20.1-GUI-UX-STARTUP-01 and its bounded
repair. No final GA or public-distribution acceptance is granted.

## 2026-09-30 — startup patch handoff follows the failure checkpoint

Final startup repair source `9c73d6e70402d63055b57ffe5ff5d44bb7b174ec`,
App 1.0.1 / 101.10: 1,354 passed, 0 failed, 1 historical artifact-pair skip;
exact native packaged GUI recovery and restart verified on isolated old-data
fixtures. See the dated verification in VOL20_STARTUP_RECOVERY.md and the
private startup-recovery evidence. Candidate handoff is
READY_FOR_OWNER_PATCH_INSTALL; original 101.8 remains blocked until Owner's
single startup/history retest. The 101.8 artifact is retained and superseded
for handoff. Owner UX/GA acceptance is not granted, and the accepted 101.6
business delivery must not be repeated.
