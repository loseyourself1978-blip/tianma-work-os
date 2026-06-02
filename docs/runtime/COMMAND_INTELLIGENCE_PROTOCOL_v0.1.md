# Command Intelligence Protocol v0.1

Status: Draft for Vol.3 Phase 2.5

## Purpose

Command Intelligence is the runtime layer that decides whether, when, where, by whom, in what sequence, with what safeguards, and under what validation criteria a command should be executed.

It prevents Tianma Work OS from blindly executing stale or unsafe command drafts.

## Runtime Position

```text
Signal Intake
-> AI Board Decision
-> Decision-to-Command
-> Command Intelligence Check
-> Smart Execution Plan
-> Execution
-> Validation
-> Feedback Reconciliation
-> Memory / Rule / Backlog Update
```

## Core Principle

```text
Pending command is not final command.
Tianma Work OS should execute the latest valid command, not stale command drafts.
Execution should be intelligent, context-aware, adaptive, and accountable.
```

## Real Vol.3 Phase 2 Sample

During Vol.3 Phase 2 planning:

- Phase 2 v1 was drafted using earlier 2026-06-01 data, but it was not executed.
- A newer 2026-06-01 16:37-16:38 LDD Sync Block arrived, so v1 became stale and was superseded by v2.
- Phase 2 v2 was also not executed.
- A newer 2026-06-02 08:22 post-U.S.-session LDD Sync Block arrived, so v2 was superseded by v3.
- Phase 2 v3 was executed successfully and produced commit `757a467`.

This proves that command drafts must remain editable until they are executed, acknowledged, cancelled, or superseded.

## 1. Freshness Check

The runtime checks whether a command is still based on the latest valid context.

Freshness inputs can include:

- Newer user instructions.
- Newer sync blocks.
- Newer Codex feedback.
- Newer market, account, project, or repository data.
- Superseded command drafts.
- Updated validation results.
- Updated issue, backlog, or memory records.

Freshness outcomes:

- `fresh`
- `stale`
- `superseded`
- `needs_review`
- `unknown`

If a newer source-of-truth signal invalidates the command draft, the command should not execute as written.

## 2. Priority Check

The runtime compares the command against:

- User urgency.
- Project priority.
- Risk severity.
- Resource constraints.
- Workstream interruption status.
- Existing pending reviews.

A high-urgency user correction can override a lower-priority prepared plan. A low-risk documentation command can proceed sooner than a high-risk integration command.

## 3. Resource Check

The runtime verifies whether the intended executor is available and appropriate.

Executors may include:

- User.
- ChatGPT.
- Codex.
- Local scripts.
- GitHub.
- Future agents.
- Manual external tools.

Resource checks should confirm that the executor has the required context, permissions, tools, and time window.

## 4. Dependency Check

The runtime checks preconditions before execution.

Examples:

- Repository is clean before editing.
- Current validation passes before schema hardening.
- Latest source data is confirmed.
- Required local files exist.
- No higher-priority pending review blocks execution.
- The command does not depend on a missing approval, credential, API connection, or external tool.

Failed dependencies should produce a blocked or revise-before-execution recommendation.

## 5. Risk And Reversibility Check

Commands should be classified as low, medium, or high risk.

Low-risk examples:

- Add docs.
- Add examples.
- Add schema drafts.
- Run local validation.

Medium-risk examples:

- Modify shared schemas.
- Change validator behavior.
- Reorganize documentation references.
- Create a small number of explicitly requested GitHub issues.

High-risk examples:

- Delete files.
- Rewrite core schemas.
- Create many issues.
- Create GitHub Projects.
- Connect APIs.
- Execute trades.
- Modify production systems.

High-risk commands usually require explicit human approval, staged execution, or cancellation.

## 6. Execution Granularity Planning

The runtime decides whether a command should execute in one block or be split into stages.

Staged execution is preferred when:

- The command touches multiple record families.
- Validation may fail and require repair.
- Push or external publishing may fail.
- Human approval may be needed between stages.
- The command has irreversible or hard-to-reverse effects.

## 7. Validation Planning

Every executable command should define:

- Expected output.
- Validation method.
- Success criteria.
- Failure criteria.
- Recovery path.
- Required feedback format.

For Vol.3 runtime records, the minimum validation method is local JSON validation with no external network calls.

## 8. Feedback Reconciliation

After execution, the runtime captures:

- Files created.
- Files modified.
- Validation result.
- Commit hash.
- Push result.
- Error messages.
- Remaining blockers.
- Next recommended actions.

Feedback should be reconciled into:

- Project memory.
- Runtime records.
- Pending command ledger.
- Requirements backlog.
- Decision log.
- Related issue status.

## Non-Goals

This protocol does not implement:

- UI.
- GitHub Projects board creation.
- New GitHub issue creation without explicit request.
- External API connections.
- Automated trading.
- Production system automation.
