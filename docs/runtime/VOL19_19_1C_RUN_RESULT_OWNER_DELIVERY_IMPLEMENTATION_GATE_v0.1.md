# Vol.19 19.1C Run Result to Owner Delivery — Implementation Gate v0.1

| Field | Value |
| --- | --- |
| Status | IMPLEMENTATION VALIDATED / OWNER ACCEPTANCE PENDING |
| Application version | 0.17.0 |
| Schema | through `vol19.002` |
| Active Release Contract | `VOL19_RELEASE_CONTRACT_v0.2.md` |
| Prior gate | 19.1B PASS / OWNER ACCEPTED / CLOSED |

## Owner Journey

One terminal, reviewable Run Result on the canonical 19.1C path now follows one persisted delivery lineage. Historical legacy Candidates remain preserved and are not silently upgraded or rebound to a Result:

```text
Completed Run
-> automatically captured Run Result
-> automatically materialized, read-only Review Candidate
-> visible Candidate evidence and source-drift classification
-> explicit Owner Accept for Delivery or Reject Result
-> immutable Apply Plan
-> separate explicit Owner Apply Plan approval
-> separate explicit Apply confirmation
-> persisted Apply result
-> optional separate explicit Revert
```

Candidate materialization creates metadata only. It never changes the source workspace and never accepts the Result. Result acceptance and Apply Plan approval also do not change files. Apply is the first source mutation in this sequence.

## Immutable Lineage

The Result review binds the Owner decision to one Result envelope and digest, Task and version, approved Pack and version, Run, Candidate ID/version/digest, and decision evidence. The Candidate binds the exact Coding attempt and, when required or present, the Verification attempt and receipt, plus source and isolated Run workspace identities, source baseline, Run post-state evidence identity, and Run-attributed actions. Result-bound Apply Plan approval and ApplySession preserve this lineage through Apply and Revert. Historical legacy Candidates and Plans retain their accepted compatibility behavior rather than receiving synthesized Result bindings or Plan approval.

Identical Result decisions, Candidate materialization, Plan approval, Apply, and Revert are idempotent. A decision cannot silently transfer to another Result, Run, Candidate version, Task version, or Pack version.

## Candidate and Drift Truth

- `Ready` means the Coding, Result, integrity, Verification policy, workspace evidence, attribution, path, and source bindings permit delivery planning after exact Result acceptance. `Blocked` and `No changes` Results remain reviewable, but cannot create an Apply Plan.
- Required Verification that is failed, unavailable, interrupted, or missing remains blocking. The Owner may record a Result review decision, but acceptance never clears the blocker or permits a Plan.
- Explicitly not-required Verification is shown as not required; it is not described as passed.
- A successful Result with no attributable deliverable action is `No changes`; no fake action or Apply Plan is created.
- Unrelated pre-existing or later source changes are disclosed, excluded, and preserved. They may remain reviewable under the active v0.2 drift contract.
- Planned-target, preimage, binding, repository, containment, or symlink drift remains blocking or Conflict.

Only changes proven by the captured Run evidence enter the Candidate. Ordinary unapproved pre-launch Run-worktree contamination blocks attribution. Pre-existing source changes, uncertain-origin paths, `.git` metadata, runtime logs, spool data, credentials, and internal evidence are excluded from Candidate actions. Create, modify, delete, and bounded binary metadata reuse the accepted Candidate and Apply Plan action model.

## Owner Controls and Recovery

The primary Owner flow keeps one next action prominent. Automatically materialized Candidate evidence is visible before the explicit Result accept/reject control; Plan review, Result-bound Plan approval, Apply confirmation, and Revert confirmation remain separate controls. Exact actions, blocking reasons, preconditions, reversibility, validation, changed-file count, and recovery availability remain visible; raw identities and hashes remain under Advanced.

Apply reuses the accepted 19.1A exact-path snapshot and mutation engine. Revert restores only execution-owned paths and blocks rather than overwriting unsafe later changes. The isolated Run worktree and historical Run Result remain evidence and are never treated as the delivered source workspace.

## Explicit Boundary

No Result settlement, Candidate materialization, Result decision, Apply Plan review or approval, Apply, or Revert automatically starts another Run or performs Stage, Commit, Push, merge, tag, provider invocation, connector action, email, or calendar work. Apply and Revert do not automatically Stage, Commit, or Push.

19.1C remains open until the Owner completes the isolated browser acceptance and explicitly declares PASS. This implementation gate does not close Owner-approved Commit/Push acceptance, live multi-model aggregation, email/calendar connectors, Fresh Install and First-Run, release-level Backup/Restore/Migration acceptance, security audit, release packaging, TWOS 1.0 RC, or version 1.0.0.
