# Vol.19 19.1B Codex Run Truth Implementation Gate v0.1

| Field | Value |
| --- | --- |
| Status | IMPLEMENTED / OWNER ACCEPTANCE PENDING |
| Segment | 19.1B — Codex Run Truth + Progress + Automatic Result Capture |
| Active release contract | `VOL19_RELEASE_CONTRACT_v0.2.md` (unchanged) |
| Prior accepted gate | 19.1A — PASS / CLOSED |
| Owner Acceptance | Not yet performed |

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

Automated validation does not substitute for Owner Acceptance. Before 19.1B can close, the Owner must explicitly start the prepared real-Codex task in one isolated temporary runtime, observe truthful progress, review the automatically captured terminal result, and confirm that no automatic Apply, Stage, Commit, or Push occurred. Only the Owner may declare 19.1B PASS.

## Remaining Volume Gates

Vol.19 19.1 and TWOS 1.0 RC remain in progress. Live multi-model aggregation, fresh-install proof, backup/restore release acceptance, release packaging, external delivery authorization, and final 1.0 candidate metadata remain open, partial, deferred, or blocked as classified in `VOL19_RC_GAP_REGISTER_v0.1.md`.
