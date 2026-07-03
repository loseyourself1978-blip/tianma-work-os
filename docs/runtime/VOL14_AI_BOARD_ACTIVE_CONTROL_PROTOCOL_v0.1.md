# Vol.14 AI Board Active Control Protocol v0.1

| Field | Standard |
|---|---|
| Purpose | Define AI Board as an active control and veto layer, not a decorative review table |
| Scope | Docs-only operating protocol for pre-Codex, during-execution, and post-Codex control |
| Baseline | Vol.14 starts from the accepted memory gate and readiness gate baseline |
| Authority | Commander verdict is valid only when the AI Board control checks are evidenced |
| Non-Activation | This protocol does not approve implementation, UI, backend, API, scheduler, live execution, dashboard, schema, validator, or fixture work |

## Purpose

| Control Need | AI Board Function | Required Outcome |
|---|---|---|
| Prevent decorative review | Board must block, redirect, or approve with cited evidence | Review becomes operational control |
| Prevent scope drift | Board checks every request against explicit scope and source of truth | Scope creep defaults to BLOCK |
| Prevent false closure | Board separates local completion from remote and evidence closure | Local clean is not remote closed |
| Prevent unsafe inference | Board rejects unsupported claims, missing evidence, and vague SoT | Missing evidence cannot be overridden |

## Pre-Codex Redlines

| Redline | Board Test | Default Result |
|---|---|---|
| Missing source of truth | SoT is not named, current, or branch-specific | BLOCK |
| Hidden implementation | Request implies code, UI, backend, API, schema, validator, fixture, scheduler, dashboard, or live execution without separate approval | BLOCK |
| Future-step dumping in stepwise mode | Instruction includes later segments before current feedback is received | BLOCK |
| Prediction treated as realized outcome | Correct market or product prediction is used as proof of P/L or delivery success | BLOCK |
| Hedge treated as no-risk | Risk-reduction language hides residual exposure or downside | BLOCK |

## Execution Modes

| Mode | Instruction Shape | Board Control |
|---|---|---|
| Single-phase Codex | One compact instruction covers preflight, edit, validate, commit, and push | Allowed only when scope is narrow, files are explicit, and validation is fully specified |
| Stepwise Codex | Give only the current segment, wait for feedback, then generate the next segment | Do not dump future step instructions when using stepwise mode |

## During-Execution Watch Rules

| Watch Rule | Trigger | Required Action |
|---|---|---|
| File boundary drift | Changed files exceed the allowed list | STOP and report before proceeding |
| Mode drift | Stepwise work starts anticipating future instructions | STOP and request next-step feedback |
| Evidence gap | Command output, diff, status, or remote proof is missing | HOLD until evidence is produced |
| Local-only closure | Worktree is clean but remote state is not verified | Continue verification; do not claim closure |
| Implementation pressure | Docs-only task starts creating executable assets | BLOCK and return to approved scope |

## Post-Codex Evidence Intake

| Evidence Type | Required Proof | PASS Condition |
|---|---|---|
| Local state | `git status -sb` or equivalent | Clean or expected changes only |
| File scope | `git diff --name-only`, staged file list, or status evidence | Exactly the approved files changed |
| Markdown quality | Read-back plus `git diff --check` | Readable Markdown and no diff hygiene errors |
| Commit closure | Commit hash and latest log line | Commit matches approved message and files |
| Remote closure | Remote head check after push | `origin/main` contains the target commit |

## AI Board Veto Rules

| Veto Rule | Meaning | Result |
|---|---|---|
| Scope creep defaults to BLOCK | Any unapproved expansion is blocked by default | BLOCK |
| PASS must cite evidence | Approval without command, diff, status, or source evidence is invalid | HOLD or BLOCK |
| Missing evidence cannot be overridden | Commander confidence cannot replace absent proof | HOLD |
| SoT must be explicit | Source of truth must be named before control decisions | BLOCK if missing |
| Implementation requires separate approval | Protocol, docs, and planning do not authorize build work | BLOCK |

## Commander Verdict Standards

| Verdict | Required Evidence | Allowed Next Step |
|---|---|---|
| PASS | Scope, file boundary, validation, and remote or local closure evidence are cited | Proceed within approved limits |
| PASS WITH HARD LIMITS | PASS evidence exists, but expansion risks remain | Proceed only on the named allowed files or actions |
| HOLD | Evidence is missing, remote state is unclear, or feedback is required | Stop and request or produce the missing evidence |
| BLOCK | Redline, scope creep, hidden implementation, or SoT failure is present | Do not proceed |

## Learned Controls

| Learned Control | Operational Rule |
|---|---|
| Local clean is not remote closed | Always verify remote state before claiming final sync |
| Prediction correct is not P/L correct | Separate directional accuracy from realized financial result |
| Hedge is not no-risk | State remaining downside and exposure |
| SoT must be explicit | Name the governing source before enforcing or passing a decision |
| Implementation requires separate approval | Docs approval does not unlock build execution |
