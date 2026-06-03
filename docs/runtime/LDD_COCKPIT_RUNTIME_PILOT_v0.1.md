# LDD Cockpit Runtime Pilot v0.1

Status: Draft for Vol.3 Runtime MVP

## Purpose

LLM Daredevil Desk is the first pilot domain for Tianma Work OS runtime records.

The pilot records financial-cockpit logic without connecting to trading platforms or executing trades.

## Pilot Scope

The LDD pilot includes:

- Trigger-to-execution rule records.
- Strategy-state risk records.
- Manual sync block examples.
- Offline validation.

## Pilot Non-Goals

The pilot does not include:

- Automated trading.
- Brokerage API integration.
- Binance API integration.
- External market data API calls.
- Private account screenshots.
- Private account identifiers.

## Runtime Records

### Trigger-to-Execution Rule

Used for assets with defined trigger lines and next actions.

Examples:

- BTC staged buyback trigger.
- SOXL protection trigger.

### Strategy State

Used for ongoing bot or strategy health monitoring.

Example:

- ZEC 500U / 60-grid bot state with profit surge protection.

## LDD Pilot Examples

Files:

- `examples/ldd/ldd_sync_block_20260601.example.md`
- `examples/ldd/btc_buyback_trigger_rule.example.json`
- `examples/ldd/zec_bot_strategy_state.example.json`
- `examples/ldd/soxl_trigger_rule.example.json`

## LDD Pilot Records

Vol.3 Phase 2 introduces `records/ldd/` as the first real runtime data layer.

- `examples/ldd/` remains illustrative.
- `records/ldd/` contains real project pilot records.
- The latest pilot set is `records/ldd/2026-06-02/`.
- The 2026-06-02 08:22 post-U.S.-session sync block is the latest source of truth for that pilot set.

The records include portfolio state, strategy state, trigger rules, account-structure review, and a pending command sample.

The pending command sample demonstrates Command Intelligence: pending instructions remain editable until they are executed, acknowledged, cancelled, or superseded. Newer incoming signals can invalidate stale command drafts before execution.

## Command Intelligence In The LDD Pilot

Vol.3 Phase 2.5 adds Command Intelligence between Decision-to-Command Routing and Execution.

For LDD, this means the runtime checks whether the latest sync block, account state, strategy state, and risk rules still support the command before any execution step begins.

The Phase 2 v1, v2, and v3 sequence is the first real sample:

- v1 was drafted from older 2026-06-01 data and became stale.
- v2 was drafted from the 2026-06-01 16:37-16:38 sync block and was also superseded.
- v3 used the 2026-06-02 08:22 post-U.S.-session sync block and was executed successfully.

The LDD pilot therefore treats prepared commands as editable drafts until Command Intelligence confirms freshness, resources, dependencies, risk, validation criteria, and feedback routing.

## Phase 3 Rule Ledger And Strategy Monitor

Vol.3 Phase 3 expands LDD runtime from static records into operational rule-ledger and strategy-state monitoring.

The ZEC bot closure validates Profit Surge Protection:

- The 2026-06-02 state showed the remaining 500U / 60-grid ZEC bot running in profit-protection mode.
- On 2026-06-03 at 08:38-08:39 SGT/BJT, the bot was closed and ZEC was auto-sold into USDT.
- The strategy state is now closed / profit locked.

Execution correctness is judged by rule compliance and account-risk improvement, not only by short-term price movement after closure.

Strategy-state monitoring must track profit-protection mode, lock-profit execution, closed/profit-locked state, downside thresholds, and state transitions.

Account structure score evaluates cash pressure, leverage exposure, weak-position drag, historical cleanup, strategy separation, bot state, cash dominance, and redeployment readiness.

LDD sync blocks now require versioning and delta update handling when new execution evidence arrives after a prior sync block.

## Validation

Run:

```bash
scripts/validate_runtime_records.sh
```

The validator checks local JSON examples against local schemas. It does not call external networks.

## Relationship to Backlog Issues

The pilot primarily exercises:

- TWOS-036 Strategy-State Risk Monitor.
- TWOS-043 Trigger-to-Execution Rule Ledger.
- TWOS-039 Rule-Based Execution Review.
- TWOS-040 Volatility-Aware Execution Splitter.
