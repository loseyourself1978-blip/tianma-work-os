# Vol.19 19.1B Codex Run Truth Implementation Gate v0.1

| Field | Value |
| --- | --- |
| Status | REMEDIATED / OWNER REMEDIATION ACCEPTANCE PENDING |
| Segment | 19.1B — Codex Run Truth + Progress + Automatic Result Capture |
| Active release contract | `VOL19_RELEASE_CONTRACT_v0.2.md` (unchanged) |
| Prior accepted gate | 19.1A — PASS / CLOSED |
| Owner Acceptance | The first live Run exposed a terminal-truth defect; remediation acceptance is pending |

## Implemented Owner Journey

The repository now provides the bounded 19.1B journey:

```text
Task
-> current approved Instruction Pack
-> explicit Owner Run confirmation
-> truthful Codex readiness
-> verified process launch
-> persisted progress
-> automatic process and workspace evidence capture
-> persisted Run Result
-> Owner review
```

The start request binds the exact approved Pack identity and version, approved-instruction digest, authorized workspace, and a stable idempotency identity. A Run becomes `running` only after the launched child process is authoritatively bound. Duplicate accepted requests return the same Run, and conflicting active workspace Runs remain blocked.

Persisted lifecycle and activity evidence survives reload and supports restart reconciliation, cancellation, timeout, interruption, and failure truth. Terminal settlement automatically records bounded sanitized process evidence, baseline-aware workspace evidence, validation evidence when available, structured-handoff availability, and an explicit completion classification. Missing or uncertain evidence remains unavailable, incomplete, or unverified rather than being invented.

The Owner surface presents readiness, explicit Start confirmation, persisted Run state, current activity, terminal classification, changed-file count, validation summary, and Review Run Result. Process identifiers, executable identity, detailed events, log references, digests, and full evidence remain under Advanced and remain subject to redaction.

## Terminal-Truth Remediation

The first live Owner Acceptance Run did not pass acceptance. Its raw persisted evidence was captured before remediation or runtime cleanup:

| Evidence | Persisted truth |
| --- | --- |
| Run | `#1`; Coding process exit `0`; no timeout or cancellation |
| Coding | Completed with one intended unstaged change to `codex_target.txt`; local validation reported one pass |
| Independent Verification | Required by a separate Verification assignment; never started; no Verification process or sidecar existed |
| Workspace | HEAD, branch, index, source repository, and remote state were unchanged; the intended file was attributed to the Run |
| Result envelope | Available and internally `VERIFIED`; this integrity label described the stored evidence envelope, not objective Verification |
| Incorrect conflict | `GIT_REMOTE_ATTEMPTED` from a read-only `git remote -v` command caused `workspace_evidence_conflict` |
| Original persisted Run label | `failed`, despite Coding exit `0`, because the false boundary finding blocked Verification |

The primary defect was command classification: exact read-only `git remote -v` and `git config --local --list` inspection was treated as a Git mutation. That false boundary signal prevented the required Verification phase from launching. Independent API/UI projections then exposed `Result Available`, raw Run `Failed`, and unconditional “Coding and Verification completed” copy at the same time.

The remediation keeps these authoritative dimensions separate in one server projection used by Run detail, Run Activity, and Run Result:

| Dimension | Values |
| --- | --- |
| Coding/process outcome | pending, starting, running, succeeded, failed, cancelled, timed out, interrupted |
| Independent Verification | not required, pending, running, passed, failed, unavailable, interrupted |
| Result availability | unavailable, incomplete, available |
| Workspace evidence | no change, captured, incomplete, conflict |
| Evidence-envelope integrity | verified, unverified, invalid |
| Owner review | pending, reviewed |

A nonzero Coding exit remains Coding Failed even when partial evidence is available. Coding exit `0` remains Coding succeeded when a separate Verification gate or genuine workspace conflict requires review. Result availability and evidence-envelope integrity do not imply objective Verification. Copy may say that Coding and Verification completed only when both phases actually did.

Exact read-only remote/config inspection is now distinguished from prohibited Git mutation commands without weakening detection of remote/config changes or any other forbidden Git operation. A default-disabled deterministic local Verification backend uses the existing Verification phase, immutable Run/Pack/assignment/workspace/command bindings, explicit argv with no shell interpolation, a secret-free child environment, bounded execution/output, protected launch and receipt evidence, and persisted process identity, exit code, test result, and verdict. It never invokes another model or provider.

## Safety Boundary

- An approved Pack never starts automatically.
- The authorized workspace and Pack bindings are revalidated before launch.
- Process launch uses the existing explicit argument-vector bridge and bounded environment allowlist.
- Result capture does not silently attribute unrelated baseline changes to the Run.
- A successful process exit does not by itself assert that the task objective was achieved.
- Automatic provider fallback is blocked, including a configured same-provider alternate; the exact primary target remains bound and disclosed.
- Run completion does not automatically approve a result, create an accepted Candidate, Apply, Stage, Commit, Push, reset, clean, or discard workspace changes.
- This segment does not add email, calendar, GitHub, external multi-model orchestration, a scheduler, or a generic workflow engine.

## Evidence and Acceptance Gate

Implementation evidence resides in the Codex Run persistence and additive migration, Owner-scoped start/cancel/result APIs, direct process adapter, lifecycle reconciliation, automatic result intake, Owner command-center UI, and focused Vol.19 tests. Required focused, Vol.18/19 regression, full-suite, migration, containment, redaction, and diff validation remain mandatory commit and handoff gates; their exact results belong in the implementation execution report.

Automated validation does not substitute for Owner Acceptance. Before 19.1B can close, the Owner must explicitly start the focused remediation task in one isolated temporary runtime, observe truthful Coding and deterministic independent Verification progress, review the automatically captured terminal result, and confirm that no automatic Apply, Stage, Commit, or Push occurred. Only the Owner may declare 19.1B PASS.

## Remaining Volume Gates

Vol.19 19.1 and TWOS 1.0 RC remain in progress. Live multi-model aggregation, fresh-install proof, backup/restore release acceptance, release packaging, external delivery authorization, and final 1.0 candidate metadata remain open, partial, deferred, or blocked as classified in `VOL19_RC_GAP_REGISTER_v0.1.md`.
