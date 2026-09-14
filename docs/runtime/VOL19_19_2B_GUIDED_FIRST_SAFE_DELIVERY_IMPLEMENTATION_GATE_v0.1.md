# Vol.19 19.2B — Guided Tool Setup + First Safe Delivery

Status: IMPLEMENTATION PASS / OWNER ACCEPTANCE PENDING.
Only the Owner may declare 19.2B Owner Acceptance PASS. Vol.19 19.2 remains
open; TWOS 1.0 RC is not complete and version 1.0.0 is not released.

## Accepted baseline and routing

The accepted starting implementation is `e51e1c4cd092fd992749c69f83999f994f7faeb4`,
following runtime stabilization `f22bfb3c10472c0f667ebc7050755a417638c964`.
The 19.2A Owner-accepted closeout is recorded separately in
`VOL19_19_2A_FRESH_INSTALL_FIRST_RUN_CLOSEOUT_v0.1.md`, committed as
`2210e89bf2b7e724fc522118dfa82b96ba91d959`. The verified completed 19.2A
acceptance runtime and its temporary installation were retired without
touching unrelated processes or directories.

The primary owns all edits, integration, validation and commits. Read-only
auditors inspected setup and delivery architecture and independently reviewed
the new configuration and approval boundaries. No writing subagent was used.

## Existing-path audit before implementation

| Capability | Baseline status | Existing evidence | 19.2B gap addressed |
| --- | --- | --- | --- |
| Codex discovery | IMPLEMENTED | `codex_adapter.py`, `test_self_hosting.py` | One guided entry with safe fixed executable identity |
| CLI version truth | PARTIAL | `CodexAdapter.detect`, existing CLI setup tests | Explicit minimum version and Needs Upgrade presentation |
| Explicit readiness check | IMPLEMENTED | `codex_connectivity.py`, `test_vol18_codex_connectivity.py` | Integrate the existing explicit probe into First Run's passive tool path |
| Auth readiness without secret exposure | IMPLEMENTED | Canonical connectivity evidence and redaction tests | Display the persisted auth result without copying credentials |
| Model configuration | PARTIAL | `AIModel`, model routing and Codex setup endpoints | Exact installed-client model and reasoning selection; no fallback |
| Tool config persistence | PARTIAL | Model registry and immutable connectivity evidence | Owner confirmation, versioned configuration snapshot and Pack binding |
| Task → Pack | IMPLEMENTED | `self_hosting.build_instruction_pack`, `ai_orchestration.py` | One guided preparation action reusing composition and routing |
| Pack approval | IMPLEMENTED | Existing Pack approval and immutable Run admission | Invalidate future approval after material configuration drift |
| First real Run | IMPLEMENTED | `codex_adapter.py`, sealed `codex_exec_bridge.py` | Reuse explicit confirmation and frozen model/reasoning |
| Verification | IMPLEMENTED | `test_vol19_verification_truth_remediation.py` | Bind the existing independent local backend without claiming a model invocation |
| Result → delivery | IMPLEMENTED | `result_intake.py`, Candidate/Apply services, 19.1C tests | Project a single current next action across accepted services |
| Commit/Push | IMPLEMENTED | `owner_commit_delivery.py`, `push_delivery.py`, 19.1D tests | Reuse separate approvals, confirmations and verified delivery receipt |

## Implementation boundaries

`guided_delivery.py` is an integration layer. It creates no second execution,
Verification, Result, Candidate, Apply, Commit or Push pipeline.

Opening Tool Setup performs only installed-client metadata discovery. The
model list comes from `codex debug models --bundled`, not a provider request.
The development client reports `codex-cli 0.153.4`; the accepted adapter minimum
is `0.144.4`. Its bundled `gpt-6-astra` catalogue explicitly names `xhigh` as
Extra high and also exposes `max`. The guide defaults to `xhigh`. It excludes
`ultra`, whose installed description includes automatic task delegation.
No CLI installation, upgrade, automatic readiness request, or model fallback
is performed.

Check Codex Readiness is an explicit Owner POST using the existing connectivity
service. Missing CLI, unsupported version, auth failure, provider connectivity
failure and unavailable requested model remain separate outcomes. Save Tool
Setup confirms that exact successful configuration. Credentials remain with
Codex; configuration stores only non-secret settings and evidence references.

The operator-configured local Verification command remains the accepted
`Settings.local_verification_command` backend. It is not a shell-command field
in the Owner UI. The Pack binds the exact command, executable and referenced
file identities, limits, workspace, model, reasoning and execution boundary.
The Run's existing sealed Verification attempt proves the local process;
it does not invent provider invocation evidence for a deterministic verifier.

Schema `vol19.005` adds configuration history and Task ownership. Configuration
identity/history and Task ownership have SQLite mutation guards. A material
configuration change invalidates affected future Packs; an active Run retains
its approved configuration. Fresh initialization and exact-schema restart are
supported. Migration of older installations is outside this gate.

The normal fresh-install workbench shows eleven stages and one current action.
Preparation, approval, Run confirmation, Result acceptance, Apply, Commit and
Push remain distinct. Post-Apply validation remains explicit before Commit.
The Pack review presents workspace, deliverable, source binding, model,
reasoning and boundaries; raw Pack/receipt/process evidence stays Advanced.
Guided actions also require the displayed Task and Run identities to match the
current selection. Selecting an older Run cannot dispatch a newer Run's guide
action against that older Run. Pre-Run stages remain available for a newly
prepared Pack after a historical delivery.

## Regression corrections and evidence rules

First Owner remains one-time. Isolation tests reuse the accepted test-only
`User` plus `SessionToken` provisioning pattern; this adds no multi-account
signup or administration feature. Signed and whitespace Task IDs receive the
same ownership check as ordinary IDs. The accepted Owner-filtered Run collection
retains its empty-list response for foreign Runs; Task detail/mutation access
and individual foreign Run access remain denied.

The first complete-chain fixture initially observed Run completion before
sealed evidence settlement. Database inspection proved Verification was bound,
admitted, invoked, exited zero and persisted a passing local result. The
fixture now follows the accepted 19.1 wait-for-envelope boundary, then requires
`passed`, verified independent process evidence and agreement between Run and
Result projections. No accepted Verification requirement or test was weakened.

The real bootstrap test launches the current checkout. Its historical literal
`vol19.004` assertion was replaced with the launcher's current schema constant,
already used by its other health tests. A new focused test independently checks
both the `vol19.004` history and `vol19.005` marker and immutable persistence.
First Owner behavior assertions are unchanged.

## Validation

| Gate | Final evidence |
| --- | --- |
| Focused 19.2B | 35 passed, zero failures or skips; final focused run 141.09 seconds |
| Accepted 19.2A | 54 passed; also included in the final complete pass |
| Accepted 19.1 regression group | All 124 tests passed in the final complete suite; the Owner-filtered collection correction also passed its exact regression before that run |
| Runtime/self-hosting regression group | 124 passed, also included in the final complete pass |
| Complete repository suite | `.venv/bin/python -m pytest -q`: 970 passed / 0 failed / 0 skipped in 3529.92 seconds |
| Syntax and whitespace | Node syntax check, Python compileall and Git diff checks passed |
| Fresh initialization and persistence | Schema through `vol19.005`, immutable configuration, canonical First Run to approved Pack, and restart persistence passed |
| UI geometry | 1280px and 390px real-browser geometry checks passed for guide, Tool Setup and Pack review |
| Cleanup | No remaining processes or open file/SQLite handles under the final test run's temporary root; no active source Git operation |

The only complete-suite warning is the existing Starlette deprecation warning
about its `httpx` TestClient integration. No skips or xfail were introduced.
The primary ran diagnostic and final test suites serially. The final complete
pass used the frozen implementation, including both Task and Run selection
guards. An earlier interrupted run is not counted as validation.

The deterministic complete-chain fixture uses a temporary source
repository and local-only bare `origin/main`, exact BEFORE/PASS file contents,
one independent verifier, explicit delivery actions and exact remote-SHA proof.
It seeds no terminal Run, Verification, Result or delivery states.
Secret-redaction, explicit-only readiness/execution, immutable binding,
cross-owner and cross-task isolation, fixed non-force/no-tag `origin/main`
delivery, exact remote-SHA verification and no silent model fallback passed.
No real Codex capacity was used by automated tests.

## Remaining acceptance boundary

Live Owner Acceptance must use the real installed Codex CLI after explicit
Owner readiness and Run actions. Preparation must contain one setup-complete
temporary Owner, authorized workspace and Task, with Tool Setup unconfirmed
and zero Packs, Runs, Apply, Commit or Push executions.

This gate does not establish older-install migration, backup/restore, signed
installer/DMG, external credentialed Git-host Push acceptance, live multi-model
aggregation, email/calendar integration, release packaging, TWOS 1.0 RC or
version 1.0.0. 19.2 completion still requires Owner acceptance and closeout.
