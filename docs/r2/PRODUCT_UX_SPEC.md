# R2 implementation contract and data boundary

## 2026-10-09 Owner follow-up — deferred interaction work

Parent requirement: TWOS-UX-20260929-01. The Owner accepted the 101.22
non-sensitive document result, export and reopen persistence, and explicitly
deferred these interaction improvements to a later integrated release:

- **TWOS-UX-20261009-SAVE-FEEDBACK-01 — NON_BLOCKING_DEFERRED.** Team settings
  persist, but the Owner sees no confirmation near Save and no button change.
  The 101.22 save handler refreshes the project; a saved-state notice is above
  the long form. Do not claim the off-screen notice was observed in the supplied
  screenshot or that the save failed. A later change must show pending, success
  or a specific failure next to the action, with an accessible status message,
  while preserving form context and entered values. Success must depend on the
  server response; saving never implies successful provider readiness.
- Modal close placement remains deferred for Owner handoff. The internal
  101.23 shared-shell work and MODAL_INTERACTION_CONTRACT.md remain evidence of
  engineering work, not an installed 101.22 fix or Owner acceptance of it.

Required future save-feedback coverage: ordinary and restricted viewports;
keyboard focus and status announcement; both interface languages; success and
persisted readback; rejected save, timeout and lock conflict; duplicate-click
suppression; task/project switch during a request; and zero model invocations
from Save or language changes. Use actual visible behavior, not only text/DOM
presence. Do not weaken existing permissions, binding or backend validation.

No runtime implementation, new artifact or new full regression is performed
for this documentation-only acceptance closeout. The previous artificial
aggregate model-call cap below remains historical; the Owner's later
existing-quota/audit-only policy supersedes it. Per-environment product settings
and exact action approvals still apply.

---

R2 replaces the delivery-goal R1 contract. The supplied HTML is a visual reference;
its demo outputs and approvals are never migrated into product data.

The installed baseline is 1.0.1 / 101.10, source
9c73d6e70402d63055b57ffe5ff5d44bb7b174ec. Owner reports startup recovery passed.
101.6 local delivery and restart acceptance stays closed. Neither receipt grants GA.

## Product surfaces

- Project home and optional LDD, Dashu, Development starting points, plus blank project.
- Each actual Project has separate sources, role settings, ordinary tasks and results.
- An ordinary task has one canonical body, selected source hashes, output language,
  immutable plan revision, explicit approval/start, durable execution and result.
- The Development project has a same-page iteration thread. Planner, executor,
  independent reviewer, deterministic checks, local commit and candidate are separate
  actions and evidence. No external Push or automatic approval is enabled.
- Existing advanced code-delivery records remain available without rerunning them.

## Storage and migration

Additive r2_* tables use a separately recorded extension version. Existing schema
and legacy Task/Run/Commit/Push records are not rewritten. The old application can
read its own records after rollback, but cannot display or execute R2 objects.
Backup/restore must include all extension tables. No downgrade deletes new data.

## Language

Default en-US independent of system language. Explicit en-US/zh-CN selection is
persisted and shared with native setup. Canonical user content, source bytes,
plans, approval hashes and output_locale never change on UI translation.
Errors have stable codes and paired explanations. Raw provider/user text retains
its source language. Approval records retain UI locale and displayed summary.

## Execution boundary

No provider request on navigation, import, configuration display or locale change.
Real engineering requests are capped at ten across this R2 scope, including failures.
No new subscriptions, credential copying, external Push, trading or clinical work.
Running controller, development snapshot and candidate are different locations.
Only the approved candidate workspace is writable by the code executor. Review is
read-only. Candidate readiness, installed identity and Owner acceptance are distinct.

## Evidence

New tests and continuous packaged GUI journeys are required. Prior 1354/1 and
1336/7 results retain their historical scope; they cannot certify R2 code.
Engineering substitutes are identified separately from actual Codex calls.
