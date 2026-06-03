# Decision-to-Command Routing Spec v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

Decision-to-Command Routing converts a decision into a precise next action without losing context.

## Runtime Position

```text
AI Board Decision
-> Decision-to-Command Routing
-> Command Intelligence
-> Smart Execution Plan
-> Execution
-> Validation
-> Feedback Reconciliation
-> Runtime Memory Update
```

## Command Types

Supported command types:

- `create_doc`
- `update_doc`
- `create_issue`
- `review_strategy`
- `update_rule`
- `manual_follow_up`
- `no_action`
- `update_rule_ledger`
- `update_strategy_state`
- `append_delta_sync`

Vol.3 does not create GitHub issues automatically. `create_issue` is included as a future command type only.

## Command Fields

Each command should include:

- `command_id`
- `project_id`
- `decision_id`
- `source_signal_ids`
- `target_type`
- `command_type`
- `status`
- `command_summary`
- `constraints`
- `created_at`

## Command Status Values

Suggested status values:

- `proposed`
- `approved`
- `routed`
- `executed`
- `blocked`
- `cancelled`

## Safety Constraints

All command records must be explicit about constraints:

- No brokerage API access.
- No Binance API access.
- No automated trading.
- No GitHub Projects board creation unless explicitly requested.
- No new GitHub issues unless explicitly requested.

## Relationship to TWOS-032

This spec is the first runtime documentation surface for TWOS-032. It records routing logic and command shape; it does not implement a router service.

## Phase 2 Command Intelligence

Vol.3 Phase 2 adds a file-based pending-command record to capture command freshness.

Pending instructions must remain editable until they are:

- Executed.
- Acknowledged.
- Cancelled.
- Superseded.

Newer incoming signals can revise or invalidate pending commands before execution. The runtime should check freshness, priority, resource state, dependencies, and validation results before routing a command.

The system should execute the latest valid command, not stale command drafts.

The 2026-06-02 LDD pilot records show this pattern:

- Phase 2 v1 was drafted but not executed.
- Phase 2 v2 was drafted but not executed.
- The 2026-06-02 08:22 sync block superseded both.
- Phase 2 v3 became the latest valid command.

## Phase 2.5 Routing Boundary

Decision-to-Command Routing creates the command candidate. Command Intelligence decides whether that candidate can actually run.

Before execution, Command Intelligence should check:

- Whether newer signals supersede the command.
- Whether project priority or risk requires a delay.
- Whether dependencies and resources are available.
- Whether the command should run as one step or staged execution.
- Whether validation and feedback requirements are explicit.

Routing should pass commands to execution only after this check succeeds.

## Phase 3 Rule-Ledger Routing

Phase 3 introduces command candidates that update rule ledgers, strategy-state monitors, rule-based reviews, and sync delta records.

Routing must preserve the distinction between:

- A rule that is still waiting.
- A trigger event that occurred.
- An execution that has evidence.
- A strategy state that changed because of execution.
- A delta sync that supersedes a prior assumption.

For the 2026-06-03 ZEC bot closure, routing should send the update through Command Intelligence because actual execution evidence supersedes the prior Phase 3 v1 command draft.
