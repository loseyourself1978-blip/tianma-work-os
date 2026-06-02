# Runtime Architecture v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

This document defines the first lightweight runtime architecture for Tianma Work OS.

The runtime is not a trading bot, brokerage connector, or UI implementation. It is a documentation and record-validation layer that turns the product backlog into a small executable knowledge system.

## Runtime Chain

```text
Project Memory
-> Multi-Source Signal Intake
-> AI Board Decision
-> Decision-to-Command Routing
-> LDD Financial Cockpit Pilot
-> Runtime Validation
```

## First Implementation Focus

Vol.3 focuses on the smallest useful runtime spine:

- #1 TWOS-005 Project Memory & Index.
- #5 TWOS-029 Multi-Source Signal Intake.
- #6 TWOS-032 Decision-to-Command Routing.
- #16 TWOS-043 Trigger-to-Execution Rule Ledger.
- #12 TWOS-036 Strategy-State Risk Monitor.

These are enough to record a project state, receive a signal, route a decision, and validate LDD pilot records.

## Architecture Backlog, Not Implementation

The following remain architecture/backlog items for now:

- #2 TWOS-008 Project-Aware Reminder / Record Routing System.
- #8 TWOS-034 Project-Preserving Model Switching.

They influence the architecture, but Vol.3 does not implement reminders, model switching, UI flows, or platform integrations.

## Runtime Components

### Project Memory

Stores structured records that preserve project state across sessions:

- Summaries.
- Decisions.
- Requirements.
- Trigger rules.
- Strategy states.
- Validation results.

### Multi-Source Signal Intake

Normalizes incoming signals from:

- User instructions.
- LDD review notes.
- Codex execution results.
- GitHub issue or commit context.
- Manual external observations.

### AI Board Decision

Represents the reasoning step where multiple roles can evaluate a signal before a decision is routed.

Vol.3 records the decision output. It does not implement an AI Board engine yet.

### Decision-to-Command Routing

Converts an approved decision into a command record:

- Documentation update.
- GitHub task package.
- LDD review action.
- Manual follow-up.
- No-action decision.

### LDD Financial Cockpit Pilot

Uses LDD as the first runtime pilot. It records:

- Trigger-to-execution rules.
- Strategy-state risk.
- Rule-based execution review.
- Account quality signals.

### Runtime Validation

Validates example runtime JSON records against local JSON schemas.

Validation is offline and deterministic:

- No external network calls.
- No brokerage connection.
- No Binance connection.
- No automated trading.

## Phase 2 Runtime Data Layer

Vol.3 Phase 2 introduces `records/` as the first real runtime data layer.

- `examples/` remains illustrative and stable for schema demonstrations.
- `records/` contains real project pilot records derived from current source-of-truth sync blocks.
- LDD is the first validation battlefield.
- Pending instructions must be tracked until they are executed, acknowledged, cancelled, or superseded.
- Newer incoming signals can revise or invalidate pending commands before execution.
- Command Intelligence ensures that Tianma Work OS executes the latest valid command, not stale command drafts.

The 2026-06-02 LDD pilot records demonstrate this behavior: Phase 2 v1 and v2 were drafted but superseded before execution, while Phase 2 v3 became the latest valid command.

## Non-Goals

Vol.3 does not include:

- UI implementation.
- GitHub Projects board creation.
- New GitHub issue creation.
- Automated trade execution.
- Brokerage, Binance, or exchange API integration.
- Real-time market data ingestion.
- Whole-repository restructuring.
