# Rule Ledger And Strategy-State Monitor v0.1

Status: Draft for Vol.3 Phase 3

## Purpose

This document defines how Tianma Work OS tracks operational rules and strategy states after a signal becomes a monitored runtime obligation.

The Phase 3 runtime chain is:

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

The goal is not to automate trading. The goal is to preserve accountable rule memory so future execution support can distinguish valid rules, stale rules, executed rules, and superseded strategy assumptions.

## 1. Trigger-to-Execution Rule Ledger

The rule ledger records active operational rules before an execution happens.

Each rule should track:

- Asset, strategy, and account.
- Trigger condition.
- Trigger level.
- Current observed value.
- Trigger status.
- Intended action.
- Execution status.
- Execution evidence requirement.
- Next review time.
- Rule drift prevention.

Rule drift prevention matters because a rule should not quietly change after market movement or emotional pressure. If the rule changes, the runtime should record a new rule, a supersession reason, or a delta update.

## 2. Strategy-State Risk Monitor

The strategy-state monitor records whether a strategy is healthy, deteriorating, in profit protection, or closed.

It should track:

- Strategy health.
- Profit-protection mode.
- Lock-profit execution.
- Closed / profit-locked state.
- Downside risk mode.
- Rule compliance.
- Soft threshold.
- Hard threshold.
- Recommended action.
- Status transition history.

The ZEC 500U / 60-grid bot demonstrates this lifecycle:

```text
profit_protection_mode
-> profit_surge_triggered
-> close_bot_and_auto_sell
-> closed_profit_locked
```

## 3. Account Structure Quality Score

Account structure review evaluates whether execution improved the account, not only whether the price moved favorably afterward.

The score should consider:

- Cash pressure.
- Leverage exposure.
- Weak-position drag.
- Long-short conflict.
- Historical-position cleanup.
- New-strategy separation.
- Bot / robot strategy state.
- Cash dominance.
- Redeployment readiness.

For LDD, closing a profitable bot can be positive even if the asset rises later, because floating risk was converted into a more defensive USDT posture.

## 4. Rule-Based Execution Review

Execution correctness should be judged by:

- Rule compliance.
- Evidence quality.
- Account-risk improvement.
- Strategy-state improvement.
- Consistency with the current phase.

It should not be judged only by short-term post-execution price movement.

For example, the ZEC bot closure should be reviewed against Profit Surge Protection and defensive account structure, not against whether ZEC later trades higher or lower.

## 5. Volatility-Aware Execution Splitter

The execution splitter records how a position should be entered, reduced, exited, or cleaned up under volatile conditions.

It can represent:

- Staged entry.
- Staged exit.
- Confirmation zone.
- Soft trigger.
- Hard stop.
- Rebound exit.
- Final cleanup.

The splitter is a planning record. It does not execute trades or connect to external systems.

## 6. LDD To TWOS Sync Block Versioning / Delta Sync Protocol

LDD sync blocks should include:

- `sync_time`
- `source_cutoff_time`
- `included_events`
- `pending_events`
- `supersedes_or_updates`
- `sync_status`

When new execution evidence arrives after a prior sync block:

- If the prior sync was not written, replace it with the new complete version.
- If the prior sync was written, append a delta update.
- Actual execution data has higher priority than prior strategy-state assumptions.

Priority order:

```text
actual execution
-> account screenshot
-> bot state
-> market interpretation
-> strategy forecast
```

## Phase 3 ZEC Delta Sync

Phase 3 v1 assumed the 2026-06-02 ZEC bot was still running in profit-protection mode. A newer real execution event arrived before Phase 3 was implemented.

At 2026-06-03 08:38-08:39 SGT/BJT, the remaining 500U / 60-grid ZEC/USDT Binance spot grid bot was closed and ZEC was auto-sold back into USDT to lock profit.

Phase 3 v2 therefore treats the closed / profit-locked ZEC state as the latest source of truth.

## Non-Goals

Phase 3 does not include:

- UI.
- New GitHub issues.
- GitHub Projects.
- Brokerage or Binance API connections.
- External market data connections.
- Automated trading.
- Invented trades.
