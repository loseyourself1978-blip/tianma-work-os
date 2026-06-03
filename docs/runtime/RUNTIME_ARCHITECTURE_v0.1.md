# Runtime Architecture v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

This document defines the first lightweight runtime architecture for Tianma Work OS.

The runtime is not a trading bot, brokerage connector, or UI implementation. It is a documentation and record-validation layer that turns the product backlog into a small executable knowledge system.

## Runtime Chain

```text
Signal Intake
-> AI Board Decision
-> Decision-to-Command Routing
-> Command Intelligence
-> Smart Execution Plan
-> Execution
-> Validation
-> Feedback Reconciliation
-> Runtime Memory Update
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

### Command Intelligence

Checks whether a command should execute now, be revised, be split into stages, require human approval, or be cancelled.

Command Intelligence evaluates:

- Freshness.
- Priority.
- Resource availability.
- Dependencies.
- Risk and reversibility.
- Validation expectations.
- Feedback requirements.

### Smart Execution Plan

Turns a valid command into an execution plan:

- Executor.
- Execution mode.
- Execution steps.
- Preconditions.
- Validation steps.
- Stop conditions.
- Fallback plan.

The plan is intentionally explicit because pending commands can be superseded before execution.

### LDD Financial Cockpit Pilot

Uses LDD as the first runtime pilot. It records:

- Trigger-to-execution rules.
- Strategy-state risk.
- Rule-based execution review.
- Account quality signals.
- Sync delta updates.

### Runtime Validation

Validates example runtime JSON records against local JSON schemas.

Validation is offline and deterministic:

- No external network calls.
- No brokerage connection.
- No Binance connection.
- No automated trading.

### Feedback Reconciliation

Captures execution output and routes it back into memory, runtime records, rule ledgers, backlog notes, decision logs, and related issue status.

## Phase 2 Runtime Data Layer

Vol.3 Phase 2 introduces `records/` as the first real runtime data layer.

- `examples/` remains illustrative and stable for schema demonstrations.
- `records/` contains real project pilot records derived from current source-of-truth sync blocks.
- LDD is the first validation battlefield.
- Pending instructions must be tracked until they are executed, acknowledged, cancelled, or superseded.
- Newer incoming signals can revise or invalidate pending commands before execution.
- Command Intelligence ensures that Tianma Work OS executes the latest valid command, not stale command drafts.

The 2026-06-02 LDD pilot records demonstrate this behavior: Phase 2 v1 and v2 were drafted but superseded before execution, while Phase 2 v3 became the latest valid command.

## Phase 2.5 Command Intelligence Layer

Vol.3 Phase 2.5 adds `COMMAND_INTELLIGENCE_PROTOCOL_v0.1.md` plus local schemas and examples for command checks, smart execution plans, and execution feedback.

Command Intelligence sits between Decision-to-Command Routing and Execution. It ensures that Tianma Work OS executes the latest valid command, not stale command drafts.

## Phase 3 Rule Ledger And Strategy Monitor

Vol.3 Phase 3 expands LDD runtime from static records into operational rule-ledger and strategy-state monitoring.

The expanded chain is:

```text
Trigger Rule
-> Monitoring State
-> Trigger Event
-> Execution Decision
-> Execution Status
-> Rule-Based Review
-> Strategy-State Update
-> Account Structure Impact
-> Delta Sync / Runtime Memory Update
```

Phase 3 v2 records the 2026-06-03 ZEC bot closure as a delta sync update. The closure validates Profit Surge Protection because total return reached the 40%-42%+ lock-profit zone and the user closed the remaining 500U / 60-grid bot with automatic ZEC-to-USDT sell.

Rule correctness is judged by rule compliance and account-risk improvement, not only by short-term price movement after execution.

Strategy-state monitoring must track profit-protection mode, lock-profit execution, closed/profit-locked state, downside thresholds, and state transitions.

Account structure score evaluates cash pressure, leverage exposure, weak-position drag, historical cleanup, strategy separation, bot state, cash dominance, and redeployment readiness.

LDD sync blocks need versioning and delta update handling when new execution evidence arrives after a prior sync.

## Phase 3.5 Review And Phase 4 Direction

Vol.3 Phase 3.5 consolidates the current runtime progress into `VOL3_RUNTIME_REVIEW_AND_PHASE4_ROADMAP_v0.1.md`.

The recommended next workstream is Phase 4.1 Runtime Query & Report Layer. Before UI, API integration, or automation, Tianma Work OS should be able to read its local runtime records and generate reliable summaries.

## Non-Goals

Vol.3 does not include:

- UI implementation.
- GitHub Projects board creation.
- New GitHub issue creation.
- Automated trade execution.
- Brokerage, Binance, or exchange API integration.
- Real-time market data ingestion.
- Whole-repository restructuring.
