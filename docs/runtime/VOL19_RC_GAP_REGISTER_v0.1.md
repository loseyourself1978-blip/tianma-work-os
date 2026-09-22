# Vol.19 RC Gap Register v0.1

Statuses record explicit Owner acceptance and executable repository evidence in the current Vol.19 state, rooted in accepted baseline `5e4d79af20988aef6e1f88ab144b6dd119742aa6`, not on mock UI or unverified documentation claims.

| Capability | Status | Repository evidence / remaining gap |
| --- | --- | --- |
| Goal, task context, and file scope | IMPLEMENTED | Persisted Task/Project records and source-snapshot boundaries in `twos_runtime/models.py`, `self_hosting.py`, and APIs. |
| AI Team / AI Board and role assignment | IMPLEMENTED | Versioned assignments and evidence validation in `ai_orchestration.py`; exercised by Vol.17 tests. |
| Owner approval and accepted instruction pack | IMPLEMENTED | Immutable pack approval bindings and stale-approval gates in `self_hosting.py` and `app.py`. |
| Simplified Owner Delivery | IMPLEMENTED / OWNER ACCEPTED | Vol.19 19.1 is PASS / OWNER ACCEPTED / CLOSED. The accepted journey connects explicit Run, independent Verification, automatic Result capture and Candidate materialization, explicit Result review, immutable Apply Plan, explicit Apply/Revert, explicit local Commit, separate Push Plan approval, explicit Push, and an exact delivery receipt. See `VOL19_19_1_SIMPLIFIED_OWNER_DELIVERY_CLOSEOUT_v0.1.md`. |
| Codex Run and Verification | IMPLEMENTED / OWNER ACCEPTED | Explicit Owner confirmation binds the exact approved Pack version and stable start identity; the direct process bridge exposes verified process truth, persisted chronological activity, reload state, restart reconciliation, and independent Verification through one canonical terminal projection. Vol.19 19.1B is PASS / OWNER ACCEPTED / CLOSED. |
| Truthful progress | IMPLEMENTED / OWNER ACCEPTED | Coding, Verification, Result availability, workspace evidence, envelope integrity, and Owner review remain separate and consistent across the Run and Result surfaces. Vol.19 19.1B focused remediation acceptance is PASS / CLOSED. |
| Automatic final-result capture | IMPLEMENTED / OWNER ACCEPTED | Terminal settlement automatically persists bounded, sanitized process and workspace evidence, explicit completion classification, validation evidence when present, and honest structured-handoff availability. Manual copy/paste is not required to capture the Result. Vol.19 19.1B is PASS / CLOSED. |
| Independent Verification truth | IMPLEMENTED / OWNER ACCEPTED | Required Verification start, process receipt, exit, verdict, and result-envelope evidence are persisted independently from Coding outcome. The focused deterministic Verification acceptance passed. |
| Run Result to accepted Review Candidate | IMPLEMENTED / OWNER ACCEPTED | On the canonical 19.1C path, terminal settlement idempotently materializes one versioned, read-only Candidate from the immutable Result envelope, Coding attempt, Verification evidence when required or present, workspace identities, and attributed actions. Historical legacy Candidates are preserved and are not silently upgraded. The exact-bound, explicit Result decision is persisted without mutating source. Automated and Owner browser acceptance are recorded in `VOL19_19_1C_RUN_RESULT_OWNER_DELIVERY_IMPLEMENTATION_GATE_v0.1.md` and `VOL19_19_1C_RUN_RESULT_OWNER_DELIVERY_CLOSEOUT_v0.1.md`; 19.1C is PASS / CLOSED. |
| Continuous captured-result Apply/Revert | IMPLEMENTED / OWNER ACCEPTED | An accepted eligible Result Candidate produces an immutable lineage-bound Apply Plan, a separate immutable Plan approval, and an ApplySession retaining Run, Result, review, Candidate version, Plan, approval, and source-workspace bindings through explicit Apply and Revert. Owner acceptance proved correct source delivery, historical Run and Result preservation, exact Revert restoration, refresh persistence, and no automatic Stage, Commit, or Push. |
| Result → Candidate → Apply/Revert | IMPLEMENTED / OWNER ACCEPTED | Vol.19 19.1C accepted the exact Result lineage, automatic read-only Candidate materialization, explicit Result decision, immutable Apply Plan, separate approval, explicit Apply, exact Revert, refresh persistence, and historical Run/Result preservation. See `VOL19_19_1_SIMPLIFIED_OWNER_DELIVERY_CLOSEOUT_v0.1.md`. |
| Review Candidate and drift classification | IMPLEMENTED | Immutable Candidate and semantic drift gate in `delivery_candidates.py`; unrelated source drift is disclosed, excluded, and may remain Apply-eligible, while plan-impacting drift and Conflict are blocking. The active contract is `VOL19_RELEASE_CONTRACT_v0.2.md`. |
| Immutable/versioned Apply Plan | IMPLEMENTED | Exact INCLUDED/EXCLUDED/BLOCKED classifications, Result/Run/Candidate lineage, separate approval for Result-bound 19.1C Plans, freshness checks, and immutable DB guards in `apply_plans.py`/`db.py`; grandfathered legacy Plans retain their accepted confirmation-only compatibility behavior. |
| Owner-controlled Apply | IMPLEMENTED / OWNER ACCEPTED | Literal final confirmation, fresh preflight, repository lock, exact-path journal, compensation, persistence, and idempotency in `apply_sessions.py` and APIs. Vol.19 19.1A Owner Acceptance is PASS / CLOSED. |
| Owner-controlled Revert | IMPLEMENTED / OWNER ACCEPTED | Separate confirmation, exact snapshot restore, unsafe-later-change blocking, phase audit, compensation, and idempotency in `apply_sessions.py`. Vol.19 19.1A Owner Acceptance is PASS / CLOSED. |
| Primary Apply/Revert state summary | IMPLEMENTED | Persisted API projection and Owner UI show approval, readiness, normalized state, result, changed count, validation, and recovery. Technical evidence remains Advanced. |
| Workspace/path/symlink security | IMPLEMENTED | Canonical repository identity, containment, parent-chain, file-type, symlink, Git/index, and immutable-binding checks in Apply/Plan services. |
| Owner-controlled Commit | IMPLEMENTED / OWNER ACCEPTED | A versioned immutable Commit proposal, separate proposal approval, separate final confirmation, exact ApplySession-owned alternate index, configured hook execution, verified commit object/tree, actual-index and unrelated-change preservation, reconciliation, and idempotency are implemented and Owner accepted. Commit is never automatic after Apply and never starts Push. See `VOL19_19_1D_OWNER_COMMIT_PUSH_CLOSEOUT_v0.1.md`. |
| Separately confirmed Push and delivery record | IMPLEMENTED / OWNER ACCEPTED | A versioned immutable Push Plan binds the exact local Commit, `origin`, target branch, remote old SHA, proposed new SHA, fixed non-force/no-tag refspec, expiry, and remote configuration evidence. Separate Plan approval and final confirmation gate one standard transport attempt; exact read-only remote-SHA verification, receipts, drift truth, and idempotency are implemented and Owner accepted using a local-only bare remote. This does not establish live credentialed hosting-provider acceptance. See `VOL19_19_1D_OWNER_COMMIT_PUSH_CLOSEOUT_v0.1.md`. |
| Live credentialed hosting-provider Push | NOT ACCEPTED / DEFERRED | 19.1D acceptance used an isolated local-only bare remote. GitHub, GitLab, Bitbucket, network credential, and hosting-provider behavior remain outside accepted scope. |
| Live multi-model aggregation | PARTIAL | Deterministic multi-model assignment/evidence exists; this segment does not introduce live aggregation across external model providers. |
| Connector execution beyond current Codex path | PARTIAL | Provider/connector abstractions and evidence exist, but this segment adds no new live provider integration. |
| Email and calendar actions | DEFERRED | No live action is activated by this segment. |
| Fresh Install | IMPLEMENTED / OWNER ACCEPTED | The canonical `./start-twos` bootstrap, isolated runtime/data/log boundaries, loopback-only startup, installation-bound health, duplicate-start admission, and clean-copy proof are Owner accepted. See `VOL19_19_2A_FRESH_INSTALL_FIRST_RUN_CLOSEOUT_v0.1.md`. |
| First Run | IMPLEMENTED / OWNER ACCEPTED | First Owner creation, workspace authorization, passive optional tools, explicit Finish Setup, first Task, refresh and logout/login persistence, and 1280px/390px usability passed Owner acceptance. No automatic Pack, Run, provider, Apply, Commit, or Push occurred. |
| Guided Tool Setup | IMPLEMENTED / OWNER ACCEPTED | Owner acceptance passed explicit readiness, Astra (`gpt-6-astra`) / `xhigh` configuration and persistence. Versioned Owner confirmation and immutable future Pack binding reuse the existing tool path. See `VOL19_19_2B_GUIDED_FIRST_SAFE_DELIVERY_CLOSEOUT_v0.1.md`. |
| First Safe Delivery | IMPLEMENTED / OWNER ACCEPTED | Owner acceptance passed Task → Pack, explicit Pack approval and Codex Run, independent Verification, Result acceptance, Candidate, Apply Plan, explicit Apply, post-Apply validation, explicit Commit/Push and exact local-only remote SHA verification. The guide reuses accepted 19.1 services; final complete validation is 999 passed / 0 failed / 0 skipped / 0 xfail. |
| VOL19-19.2B-UI-01 | CLOSED / VERIFIED | The Owner accepted completed/neutral Review Commit, canonical material invalidation, successful re-review and completed-state persistence across refresh. See [19.4 closeout](VOL19_19_4_SECURITY_RELEASE_HARDENING_CLOSEOUT_v0.1.md). |
| Backup / Restore | OWNER ACCEPTED | The Owner accepted TWOS_BACKUP_V1, explicit backup, restore inspection/planning/approval/confirmation, staged restore with atomic activation, recovery point protection and restored-state persistence. Scenario A is PASS. See `VOL19_19_3_BACKUP_RESTORE_MIGRATION_RECOVERY_CLOSEOUT_v0.1.md`. |
| Migration | OWNER ACCEPTED | Scenario B accepted authentic vol19.004 → vol19.005 migration, MIGRATION_COMPLETE, historical Task and Pack / Run / Result / Apply / Commit / Push preservation, explicit workspace reauthorization and restart persistence. Automated authentic .003/.004 coverage remains recorded in the implementation gate. No provider request or external action replay occurred. |
| Failure Recovery | OWNER ACCEPTED | Scenario C Inspect and Restore Plan both returned 400 / BACKUP_HASH_MISMATCH; no plan or activation occurred and healthy database/maintenance state remained unchanged. A/B restart persistence passed. The temporary restart blocker was ACCEPTANCE_HARNESS_ONLY; its helper correction preserved strict process ownership checks without changing production code or the runtime identity contract. |
| VOL19-19.3-UX-01 | CLOSED / VERIFIED | MINIMAL_DISCOVERABILITY_IMPROVEMENT accepted: existing single-action dropdown retained, with concise helper text and Owner recovery documentation. |
| macOS source release packaging | PASS / OWNER ACCEPTED | Exact-commit reproducible 0.17.0 RC source artifact, manifest, SHA and fresh-artifact installation accepted. Artifact `twos-0.17.0-rc19.4-f951e4c335db.tar.gz` remains tied to implementation `f951e4c335dbbbb1d316c54fbddc42eb93a24aea`; this documentation closeout does not rebuild it. Signed/notarized DMG remains outside the accepted RC boundary. |
| External release authorization | BLOCKED | Local-only Push acceptance does not authorize or accept tag, release, pull request, merge, deployment, or a live credentialed hosting-service Push. Those remain separate gates. |
| Vol.19 19.1 overall | PASS / OWNER ACCEPTED / CLOSED | 19.1A, 19.1B, 19.1C, and 19.1D are PASS / OWNER ACCEPTED / CLOSED / SYNCED. The complete accepted chain is recorded in `VOL19_19_1_SIMPLIFIED_OWNER_DELIVERY_CLOSEOUT_v0.1.md`. |
| Vol.19 19.2A | PASS / OWNER ACCEPTED / CLOSED | Accepted commits and 935 passed / 0 failed / 0 skipped are recorded in `VOL19_19_2A_FRESH_INSTALL_FIRST_RUN_CLOSEOUT_v0.1.md`. |
| Vol.19 19.2B | PASS / OWNER ACCEPTED / CLOSED | The Owner accepted Guided Tool Setup + First Safe Delivery, including 1280px/390px usability. Accepted implementation/correction commits, 999 passed / 0 failed / 0 skipped / 0 xfail and the non-blocking follow-up are recorded in `VOL19_19_2B_GUIDED_FIRST_SAFE_DELIVERY_CLOSEOUT_v0.1.md`. |
| Vol.19 19.2 | PASS / OWNER ACCEPTED / CLOSED | 19.2A and 19.2B are closed. The repository's 19.2B gate required Owner acceptance and closeout for 19.2 completion; both are now recorded. The 19.2 contract excludes older-install migration and assigns backup/restore to 19.3. See the phase-scope rationale in the 19.2B closeout. |
| Vol.19 19.3 | PASS / OWNER ACCEPTED / CLOSED | The Owner accepted Scenarios A/B/C and restart persistence. Implementation `fb84f8497a2ae3fd476d98097dcbdec19673b84a`, 1092 passed / 0 failed / 0 skipped / 0 xfail, the acceptance-harness note and non-blocking UX follow-up are recorded in `VOL19_19_3_BACKUP_RESTORE_MIGRATION_RECOVERY_CLOSEOUT_v0.1.md`. |
| Vol.19 19.4 | PASS / OWNER ACCEPTED / CLOSED | The Owner accepted security audit, Owner Guide, Maintenance discoverability, release artifact/manifest, fresh installation and Scenario B re-review. Implementation `f951e4c335dbbbb1d316c54fbddc42eb93a24aea`; accepted suite 1171 passed / 0 failed / 0 skipped / 0 xfail. See [19.4 closeout](VOL19_19_4_SECURITY_RELEASE_HARDENING_CLOSEOUT_v0.1.md). |
| E2E-19.5-01 | FIX VALIDATED / OWNER ACCEPTED / CLOSED | `abca10d649ab1aa33c6b1a48a43e944675209514` explicitly allowlists `TWOS_LOCAL_VERIFICATION_COMMAND_JSON` through the standard bootstrap and documents its use. Missing/invalid configuration stays fail-closed. Validated in source and the accepted replacement package. |
| E2E-19.5-02 | FIX VALIDATED / OWNER ACCEPTED / CLOSED | The same remediation identifies the gap register as a repository-only historical record instead of a broken package-relative Markdown link. Package inclusion and link validation were not weakened. |
| E2E-19.5-03 | FIX VALIDATED / OWNER ACCEPTED / CLOSED | R2 corrects the shared fixed-size step label so Step 07 of 07 stays on one line without overlapping Create First Task; original/narrow viewports and enlarged display were checked. |
| E2E-19.5-04 | FIX VALIDATED / OWNER ACCEPTED / CLOSED | R2 exposes the safe missing Guided binding reason and Prepare First Delivery action, implements read-only actual Pack review, and restores the primary button after Prepare completes. Exact Pack approval, stale-approval invalidation, independent Verification and explicit Run/Apply boundaries remain intact. Owner completed the corrected normal Guided path. |
| OWNER_HANDOFF_INSTRUCTION_DEFECT | CORRECTED / OWNER ACCEPTED / CLOSED | The original handoff did not prominently provide the complete task body and spread essential setup instructions across outputs. This is a handoff defect, not Owner noncompliance. R2 supplied one complete private response with the real field/control names, full task intent and temporary setup authorization; no credential is recorded here. |
| FIXED_WORKFLOW_UI / STABLE_ACTION_LOCATION | OWNER_FEEDBACK_ACCEPTED / NON_BLOCKING / POST_1.0_BACKLOG | The dynamic top card still makes the Owner search for actions. Record fixed overview/navigation/action locations without collapsing independent authorization. See the repository-only `GITHUB_ISSUES_BACKLOG.md`; this does not reopen 19.5 or modify the accepted candidate. |
| Vol.19 19.5 | PASS / OWNER ACCEPTED / CLOSED | Explicit final Owner PASS on 2026-09-22, accepted implementation `94c026a2f3e1624aa991de9cc0757dfbbc633f4b`, exact RC and evidence recorded below. |
| Vol.19 19.6 | RELEASE CONTRACT PREPARATION / NOT AUTHORIZED FOR RELEASE | The 19.5 prerequisite is closed. Define the version, artifact, validation, synchronization and publication contract before execution. |
| TWOS 1.0 RC | ACCEPTANCE CANDIDATE COMPLETE | Packaged engineering E2E and final Owner acceptance are complete; 19.6 release execution remains pending. |
| TWOS version 1.0.0 | NOT RELEASED | The accepted artifact remains 0.17.0 / vol19.005. Owner acceptance does not authorize source Push, tag, merge, deployment or publication. |

## Acceptance Focus

Vol.19 19.1A, 19.1B, 19.1C, 19.1D, and 19.1 overall are Owner accepted, closed, and synced. A completed Codex Run may automatically capture a Result and materialize read-only Candidate metadata, but it does not automatically accept the Result, approve a Plan, Apply, Revert, Commit, or Push. Every mutating step remains separately Owner-controlled. The accepted Push evidence is limited to an isolated local-only bare remote; no Force, tag, external Git remote or TWOS source-repository Push occurred in 19.2B acceptance.

19.2A Fresh Install and First Run, 19.2B Guided Tool Setup and First Safe Delivery,
19.2 overall, 19.3 Backup / Restore / Migration / Failure Recovery and 19.4
Security / Documentation / Release Hardening are PASS / OWNER ACCEPTED / CLOSED.
Prior Owner Acceptance is not reopened. The [19.4 closeout](VOL19_19_4_SECURITY_RELEASE_HARDENING_CLOSEOUT_v0.1.md)
records the accepted artifact identity, security disposition and helper-only
Scenario B correction. Both VOL19-19.2B-UI-01 and VOL19-19.3-UX-01 are
CLOSED / VERIFIED. The latter retains the safe single-action dropdown through
MINIMAL_DISCOVERABILITY_IMPROVEMENT. Current distribution remains macOS source;
signed/notarized DMG is out of scope for this accepted RC boundary.
Application 0.17.0 and schema vol19.005 are unchanged. Live credentialed external
Git-host Push is not established. 19.5 End-to-End Acceptance is now PASS /
OWNER ACCEPTED / CLOSED. The acceptance candidate is complete; 19.6 is limited
to release-contract preparation. Version 1.0.0 is NOT RELEASED. No source Push,
tag or publication is authorized by this closeout.

## 19.5 Final Owner Acceptance Receipt — 2026-09-22

Authority: `TWOS-V19.5-OWNER-PASS-CLOSEOUT`. The Owner explicitly reports
`OWNER_TEST = PASS` and closes 19.5. This is the Owner's decision, not an
automated test declaring human acceptance. The normal Guided journey completed
Run, independent Verification, Result review, explicit Apply and post-Apply
validation, stopping at Review Commit. The fixed-workflow UI feedback above
is non-blocking and does not revoke this acceptance.

### Accepted identity

- Accepted implementation HEAD: `94c026a2f3e1624aa991de9cc0757dfbbc633f4b`.
- Accepted RC: `twos-0.17.0-rc19.4-94c026a2f3e1.tar.gz`.
- Accepted RC SHA-256: `4a58e68b155c0406cc79dee1f6de79e46be5740b53a4e813507bd00bf9e2dbe8`.
- Application: `0.17.0`; schema: `vol19.005`.
- Accepted regression: 1187 collected / 1187 passed / 0 failed / 0 skipped /
  0 xfail, 3456.51 seconds. Inherited for this documentation-only closeout,
  not rerun. R2 targeted validation: 129 passed.
- Exact artifact inspection reconfirmed 57 files, matching manifest and source
  identity, allowed permissions and zero forbidden content. The earlier
  package receipt also records 14 valid packaged Markdown links.
- Engineering packaged E2E-00 through E2E-06 passed separately from final
  Owner acceptance. Actual browser coverage was Codex In-app Browser, with
  headless Google Chrome layout checks; it is not labeled Safari human PASS.

### Owner fixture technical readback

Read-only closeout observation on 2026-09-22 UTC confirms one Task (ID 1,
version 2), approved Pack (ID 1, version 1), completed Run (ID 1), verified
Result envelope (ID 1), accepted Result decision (ID 1), Candidate (ID 1),
Apply Plan (ID 1), separate Plan approval (ID 1), ApplySession (ID 1) and
post-Apply verification (ID 1). Their Task/Pack/Run/Result/Candidate/Plan and
approval bindings agree. The two execution attempts are one CODING and one
VERIFICATION, both completed with exit 0; they are not two delivery Runs.

Independent Verification is PASS; ApplySession is APPLIED with integrity
PASSED; post-Apply verification is PASSED. Product local Commit and Push
execution counts are both zero. The retained coarse Task fields remain
`owner_review` / `needs_review`; those are not rewritten to represent this
phase closeout. The exact Result decision is accepted and the Apply/validation
records establish the permitted endpoint, not Delivered.

The only changed fixture path is `first_delivery.txt`, matching the approved
Candidate and Plan. It contains exactly `TWOS VOL19 FIRST SAFE DELIVERY PASS`
followed by one LF (36 UTF-8 bytes), SHA-256
`9f3ec4aeceb96f5daa7ebaa44a7da6bedef38604d8503cdf88dfaeb63b10ddc1`.
There are no staged paths or unexpected delivery paths. The fixture's HEAD
remains its separate initialization commit
`ad6505c29ad6658fcc87518343ac789b0abbfb8a`; its local bare origin is unchanged.
The intentional uncommitted Apply change is preserved, not reset, reverted,
staged or committed. SQLite integrity is `ok`.

Refresh/restart persistence is explicitly confirmed by the Owner. Technical
evidence limits are recorded separately: this Owner instance still has the
original backend PID started on 2026-09-21, and its retained runtime log shows
one startup; no paired before/after backend-restart receipt is available for
this instance. Current records show no duplicate Run, Result or Apply and no
replayed CODING/VERIFICATION attempt. The separate engineering packaged E2E
has a scoped restart and identical-record comparison, but is not substituted
for proof that this Owner instance's backend was restarted. No new restart or
repeat acceptance is performed by this closeout.

Private technical receipts retain the linkage, content/hash, selected audit
events and runtime observation outside the repository. No setup authorization,
password, API credential, database or raw runtime log enters this record.
The successful Owner fixture, original failed fixture and historical artifacts
are preserved.

### Repository closeout and next gate

Pre-closeout repository: clean `main`, HEAD equal to accepted implementation,
local `origin/main` `3cf914b6c5667059923ab209f8e9008b33a05cef`, raw behind/ahead
`0 / 13`. The subsequent repository closeout commit contains documentation
only and is distinct from the accepted implementation HEAD. Its exact SHA is
reported in the closeout receipt rather than made self-referential here.
These new repository records are not contained in the unchanged accepted RC;
no rebuild or re-acceptance of that historical artifact is claimed.

19.5 = PASS / OWNER ACCEPTED / CLOSED.
19.6 = RELEASE CONTRACT PREPARATION; execution requires a new release decision.
TWOS 1.0 RC = ACCEPTANCE CANDIDATE COMPLETE.
1.0.0 = NOT RELEASED.
