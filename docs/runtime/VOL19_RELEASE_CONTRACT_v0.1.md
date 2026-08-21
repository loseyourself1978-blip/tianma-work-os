# Vol.19 Release Contract v0.1

> **Status: SUPERSEDED**
>
> **Superseded by:** `VOL19_RELEASE_CONTRACT_v0.2.md`
>
> **Reason:** v0.1 incorrectly treated every Changed state as an Apply blocker.
>
> This version is retained for audit history and is not the active Vol.19 Release Contract.

## Purpose

Vol.19 preserves the Owner-controlled TWOS 1.0 delivery chain already established by Vol.17 and Vol.18 and exposes Apply/Revert truth more directly. An approval or review step never implies that a later mutation occurred.

## Required Owner Journey

```text
Goal
-> context and files
-> AI Team / AI Board
-> plan and role assignment
-> Owner approval
-> Codex or connector execution
-> visible progress and result capture
-> validation
-> Review Candidate
-> Apply Plan
-> Apply or Revert
-> local version management
-> Owner-approved Commit / Push
-> delivery record
```

Each transition is separately authorized and durably represented. Apply, Revert, Stage, Commit, and Push are distinct actions. Apply and Revert never automatically Stage, Commit, Push, invoke a provider, send email, update a calendar, or schedule background work.

## Apply Contract

Apply is admitted only for the current immutable Apply Plan bound to an eligible Ready Candidate, matching plan/candidate digests, a safe current repository observation, passing plan preconditions, an authorized workspace root, and no Conflict or Changed state. The final confirmation shows exact INCLUDED paths, operations, blockers, preconditions, reversibility, unrelated paths, and index state. The literal Owner confirmation is the explicit approval for that exact plan identity and version; it is not preselected.

Before the first mutation, TWOS records the immutable session binding and captures each owned path's exact pre-Apply material, metadata, and reverse operation. Path mutations occur under the repository lock with temporary-file replacement where practical. Failures are compensated when safe and otherwise reported as partial; success is never inferred while the operation is running. The unique Apply-session-to-plan binding makes retries idempotent.

## Revert Contract

Revert requires a separate literal Owner confirmation and is eligible only for one exact successful Apply session. It restores only execution-owned paths from the durable reverse journal. Fresh preflight compares every current owned path with the captured post-Apply state and blocks on later changes, missing evidence, path/symlink escape, index change, repository change, or malformed journal data. Revert has its own durable phase audit and is idempotent. It never uses Git reset, checkout, clean, Commit, or Push.

## Owner Surface

The primary Apply/Revert area shows candidate and plan context, Owner approval, Apply readiness, one eligible primary action, normalized execution state (`Pending`, `Running`, `Applied`, `Reverted`, `Blocked`, or `Failed`), concise result, changed-file count, validation result, and recovery availability. Exact paths and blockers remain visible before confirmation. Internal IDs, hashes, journal and snapshot identity, raw evidence, and detailed diagnostics remain under Advanced. Reload reconstructs the surface from persisted server state.

## Safety and Data Boundaries

- The configured source repository is the only authorized workspace.
- Canonical containment and parent-chain checks reject traversal, absolute escape, symlink escape, unsupported file types, and unsafe parent replacement.
- Plan, Candidate, repository, branch, HEAD, index, source, policy, and operation-order bindings are revalidated server-side.
- Audit evidence uses identities, bounded state, and sanitized errors; it does not store tokens, environment dumps, or unrelated sensitive contents.
- No autonomous execution is introduced.

## Recovery Limitations

Recovery is exact-path recovery, not whole-repository rollback. Revert blocks if later changes make exact restoration unsafe. A partial failure may require focused Owner remediation. Revert cannot recover unrelated paths, external side effects, Git history changes, removed/corrupt database records, or missing/corrupt snapshot material. Apply does not Commit or Push.

## Release Boundary

This segment does not add live multi-model aggregation, a new Codex process launcher or progress protocol, automatic Codex result retrieval, email/calendar actions, Owner-approved Git Commit/Push, fresh-install validation, or release packaging. Some of those capabilities have earlier repository implementations; they are outside the changes authorized by this Vol.19 segment.
