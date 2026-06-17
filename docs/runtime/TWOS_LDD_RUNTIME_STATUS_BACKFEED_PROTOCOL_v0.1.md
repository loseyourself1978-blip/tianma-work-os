# TWOS/LDD Runtime Status Backfeed Protocol v0.1

## Purpose

This protocol defines how TWOS emits a static runtime/product baseline update for LDD when cross-workspace baseline drift is detected.

It is static, local, read-only, fixture-only, no-network, and no-execution. It does not create a live endpoint, API, UI, broker/Binance connection, trading automation, credential flow, scheduler, dispatcher, or runtime mutation path.

## Source Classes

| Source class | Definition |
|---|---|
| `latest_formal_twos_runtime_status_update` | The newest formal TWOS status block visible in the LDD thread. |
| `repository_validated_twos_baseline` | The TWOS baseline proven by repository files, commit state, runtime records, schemas, fixtures, and validation scripts. |
| `project_memory_inferred_baseline` | Baseline inferred from project memory, prior summaries, or thread context. |
| `user_provided_ldd_anchor_baseline` | Baseline supplied by the user as an LDD anchor for cross-thread orientation. |
| `stale_superseded_baseline` | A baseline that was once valid or visible but has been superseded for current TWOS runtime/product purposes. |

## State Classes

| State class | Definition |
|---|---|
| `strict_baseline_sync_ready` | LDD has consumed the newest backfeed packet and no newer repository baseline is pending. |
| `baseline_drift_detected` | LDD-visible baseline and repository-validated baseline disagree. |
| `backfeed_required` | TWOS must emit a static packet before LDD uses TWOS product/runtime baseline. |
| `backfeed_packet_ready` | Static packet exists and is ready for LDD consumption. |
| `consumer_ack_pending` | LDD has not yet acknowledged packet consumption. |
| `consumer_acknowledged` | LDD has acknowledged packet consumption. |

## Required Action

When `baseline_drift_detected` is true:

1. Do not mutate runtime state.
2. Do not infer live readiness.
3. Do not create customer-facing readiness.
4. Emit static backfeed packet.
5. Mark older visible baseline as stale/superseded.
6. Require LDD to consume the newest backfeed packet before using TWOS product/runtime baseline.

## TWOS Runtime/Product Source Precedence

1. Repository-validated TWOS baseline
2. Latest formal TWOS Runtime Status Update
3. Project-memory inferred baseline
4. User-provided LDD anchor baseline
5. Stale/superseded baseline

TWOS runtime/product baseline covers product and runtime metadata only, including current TWOS volume and phase, repository commit, runtime record count, framework index count, static shell readiness, validation state, customer-facing readiness, and live/runtime implementation readiness.

## LDD Trading/Execution Source Precedence

1. User broker screenshots
2. Order detail screenshots
3. Filled execution records
4. Broker/Binance account screenshots
5. External market data as background only

LDD trading/execution facts cover broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

These two precedence chains are separate and must not override each other:

```text
TWOS runtime/product SoT must never override LDD trading/execution SoT.
LDD trading/execution SoT must never override TWOS runtime/product SoT.
```

## Backfeed Packet Requirements

A static TWOS/LDD Runtime Status Backfeed packet must include:

- schema version
- protocol name
- phase
- generated-at timestamp in SGT
- repository-validated TWOS runtime/product baseline
- LDD-visible baseline
- drift detection result
- source taxonomy
- source precedence
- required action
- forbidden scope
- DUXD queue
- acceptance state

The packet must preserve:

- `customer_facing_readiness = false`
- `live_runtime_execution_frameworks = 0`
- `static_shell_mode = local_static_read_only_fixture_only_no_network_no_execution`

## Quote-Type Preservation

The protocol preserves quote-source tags for trading-facing artifacts:

- `watchlist_price`
- `premarket_price`
- `holding_valuation_price`
- `order_page_executable_price`
- `final_filled_price`

Phase 9.1 does not fetch, infer, update, or execute against any market data.

## Execution-Event Distinction

The protocol preserves the distinction between:

- `actual_filled_trade`
- `expired_zero_fill_order`
- `canceled_order`
- `portfolio_change`
- `no_cash_impact_event`

This is a future DUXD seed for `Execution Ledger Evidence Classifier / Zero-Fill Order Separation Protocol`. Phase 9.1 records the seed only and does not implement the classifier.

## Strict Baseline Sync-Ready Conditions

`strict_baseline_sync_ready` requires all of the following:

- LDD has consumed the newest static backfeed packet.
- LDD marks older visible TWOS baseline references as stale/superseded for TWOS runtime/product baseline purposes.
- Repository-validated TWOS baseline is not older than the latest formal TWOS Runtime Status Update.
- Customer-facing readiness remains `false`.
- Live/runtime/execution framework count remains `0`.
- Trading/account/execution facts remain governed by LDD trading/execution Source of Truth.
