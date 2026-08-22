# Vol.19 RC Gap Register v0.1

Statuses are based on executable repository evidence in the current recorded Vol.19 state, rooted in accepted baseline `5e4d79af20988aef6e1f88ab144b6dd119742aa6`, not on mock UI or documentation claims.

| Capability | Status | Repository evidence / remaining gap |
| --- | --- | --- |
| Goal, task context, and file scope | IMPLEMENTED | Persisted Task/Project records and source-snapshot boundaries in `twos_runtime/models.py`, `self_hosting.py`, and APIs. |
| AI Team / AI Board and role assignment | IMPLEMENTED | Versioned assignments and evidence validation in `ai_orchestration.py`; exercised by Vol.17 tests. |
| Owner approval and accepted instruction pack | IMPLEMENTED | Immutable pack approval bindings and stale-approval gates in `self_hosting.py` and `app.py`. |
| Codex execution and visible progress | IMPLEMENTED / OWNER ACCEPTANCE PENDING | Explicit Owner confirmation binds the exact approved Pack version and stable start identity; the existing direct process bridge now exposes verified process truth, persisted chronological activity, reload state, and restart reconciliation through Owner-scoped APIs/UI. One isolated live Owner run remains the acceptance gate. |
| Automatic Codex result intake | IMPLEMENTED / OWNER ACCEPTANCE PENDING | Terminal settlement automatically persists bounded, sanitized process and workspace evidence, explicit completion classification, validation evidence when present, and honest structured-handoff availability. Manual copy/paste is not required for a terminal Run Result; live Owner acceptance remains pending. |
| Independent validation | IMPLEMENTED | Separate Verification evidence and post-Apply verification records; coding completion is not validation. |
| Review Candidate and drift classification | IMPLEMENTED | Immutable Candidate and semantic drift gate in `delivery_candidates.py`; unrelated source drift is disclosed, excluded, and may remain Apply-eligible, while plan-impacting drift and Conflict are blocking. The active contract is `VOL19_RELEASE_CONTRACT_v0.2.md`. |
| Immutable/versioned Apply Plan | IMPLEMENTED | Exact INCLUDED/EXCLUDED/BLOCKED classifications, bindings, freshness checks, and immutable DB guards in `apply_plans.py`/`db.py`. |
| Owner-controlled Apply | IMPLEMENTED / OWNER ACCEPTED | Literal final confirmation, fresh preflight, repository lock, exact-path journal, compensation, persistence, and idempotency in `apply_sessions.py` and APIs. Vol.19 19.1A Owner Acceptance is PASS / CLOSED. |
| Owner-controlled Revert | IMPLEMENTED / OWNER ACCEPTED | Separate confirmation, exact snapshot restore, unsafe-later-change blocking, phase audit, compensation, and idempotency in `apply_sessions.py`. Vol.19 19.1A Owner Acceptance is PASS / CLOSED. |
| Primary Apply/Revert state summary | IMPLEMENTED | Persisted API projection and Owner UI show approval, readiness, normalized state, result, changed count, validation, and recovery. Technical evidence remains Advanced. |
| Workspace/path/symlink security | IMPLEMENTED | Canonical repository identity, containment, parent-chain, file-type, symlink, Git/index, and immutable-binding checks in Apply/Plan services. |
| Local version management | IMPLEMENTED | Separate immutable Commit Plan, exact staging, and local Commit execution in `commit_builder.py`; never automatic after Apply. |
| Owner-approved Push and delivery record | IMPLEMENTED | Separate preflight/confirmation, exact fast-forward refspec, reconciliation, and persisted delivery result in `push_delivery.py`; never automatic after Apply. |
| Live multi-model aggregation | PARTIAL | Deterministic multi-model assignment/evidence exists; this segment does not introduce live aggregation across external model providers. |
| Connector execution beyond current Codex path | PARTIAL | Provider/connector abstractions and evidence exist, but this segment adds no new live provider integration. |
| Email and calendar actions | DEFERRED | No live action is activated by this segment. |
| Fresh-install and first-run acceptance | MISSING | Readiness documentation identifies it, but this segment provides no new executable fresh-machine proof. |
| Backup, restore, and migration recovery acceptance | PARTIAL | Schema migrations and runtime recovery paths exist; a Vol.19 release-level backup/restore acceptance artifact is not present. |
| Release packaging and TWOS 1.0 candidate metadata | MISSING | No reproducible Vol.19 package or 1.0.0 release candidate is produced here. |
| External release authorization | BLOCKED | Commit/Push/tag/release actions require separate Owner authorization and are outside this instruction. |

## Acceptance Focus

Vol.19 19.1A exact-path Apply/Revert is Owner accepted and closed. Vol.19 19.1B Codex Run Truth + Progress + Automatic Result Capture is implemented and awaits isolated live Owner Acceptance; it is not Owner accepted or closed. A completed Codex Run does not automatically Apply, Stage, Commit, or Push. Release packaging, fresh-install proof, external delivery, and TWOS 1.0 RC remain open gates.
