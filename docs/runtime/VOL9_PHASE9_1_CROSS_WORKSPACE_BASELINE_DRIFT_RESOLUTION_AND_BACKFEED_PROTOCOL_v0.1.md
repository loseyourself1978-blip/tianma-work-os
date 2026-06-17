# Vol.9 Phase 9.1 - Cross-Workspace Baseline Drift Resolution and Runtime Status Backfeed Protocol v0.1

## Scope

Vol.9 Phase 9.1 creates a static, read-only protocol for resolving TWOS/LDD baseline drift when LDD-visible TWOS runtime status trails the repository-validated TWOS baseline.

This phase is planning, protocol, schema, fixture, and validation only. It does not introduce live implementation, runtime mutation, trading automation, broker/Binance connectivity, market-data access, customer-facing readiness, or execution capability.

Static shell path: `static_shell/ldd/`

Static shell mode: `local / static / read-only / fixture-only / no-network / no-execution`

## Baseline Snapshot

| Field                               | Value                                    |
| ----------------------------------- | ---------------------------------------- |
| Latest completed phase              | Vol.8 Phase 8.6                          |
| Latest commit                       | c58243df6f9685f13c0017e4f87798f844d53277 |
| Runtime records baseline            | 113                                      |
| Frameworks indexed                  | 24                                       |
| Customer-facing frameworks          | 0                                        |
| Live/runtime/execution frameworks   | 0                                        |
| Fixture/static/read-only frameworks | 24                                       |
| Validation-backed frameworks        | 24                                       |
| Vol.9 entry readiness               | ready_with_limits                        |
| Customer-facing readiness           | false                                    |

## Drift Reason

LDD detected `cross_workspace_baseline_drift_detected` because the latest formal TWOS Runtime Status Update visible in the LDD thread referenced `Vol.7 Phase 7.8`, while the repository-validated TWOS baseline has advanced to `Vol.8 Phase 8.6`.

Current drift classification:

```text
State: baseline_drift_detected
Cause: LDD-visible formal TWOS Runtime Status Update referenced Vol.7 Phase 7.8 while repository-validated baseline is Vol.8 Phase 8.6.
Resolution: emit a static TWOS/LDD Runtime Status Backfeed packet and mark Vol.7 Phase 7.8 as stale/superseded for TWOS runtime baseline purposes.
```

## Source Taxonomy

| Source class | Role | Phase 9.1 classification |
|---|---|---|
| `latest_formal_twos_runtime_status_update` | Last formal TWOS status block visible to LDD. | Stale when it references `Vol.7 Phase 7.8`. |
| `repository_validated_twos_baseline` | Repository-backed TWOS product/runtime baseline after validation. | Authoritative for TWOS product/runtime state. |
| `project_memory_inferred_baseline` | Context inferred from project memory or prior summaries. | Secondary support only; cannot outrank repository validation. |
| `user_provided_ldd_anchor_baseline` | User-stated LDD anchor for cross-thread orientation. | Useful as intake context; cannot outrank repository validation. |
| `stale_superseded_baseline` | Older visible baseline once a newer repository baseline is validated. | May be cited historically but must not drive current TWOS runtime/product baseline. |

## Source Precedence Rules

For TWOS runtime/product baseline:

1. `repository_validated_twos_baseline`
2. `latest_formal_twos_runtime_status_update`
3. `project_memory_inferred_baseline`
4. `user_provided_ldd_anchor_baseline`
5. `stale_superseded_baseline`

For LDD trading/execution facts:

1. User broker screenshots
2. Order detail screenshots
3. Filled execution records
4. Broker/Binance account screenshots
5. External market data as background only

The two source-of-truth chains are separate:

```text
TWOS runtime/product SoT must never override LDD trading/execution SoT.
LDD trading/execution SoT must never override TWOS runtime/product SoT.
```

TWOS runtime/product Source of Truth is limited to product/runtime state such as current TWOS volume and phase, repository commit, runtime record count, framework index count, static shell readiness, validation state, customer-facing readiness, and live/runtime implementation readiness.

LDD trading/execution Source of Truth is limited to trading/account/execution facts such as broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

## Drift States

| State | Meaning |
|---|---|
| `strict_baseline_sync_ready` | LDD has consumed the newest static backfeed packet and no newer repository baseline is pending. |
| `baseline_drift_detected` | A visible LDD TWOS baseline conflicts with the repository-validated TWOS baseline. |
| `backfeed_required` | A static backfeed packet must be emitted before LDD uses TWOS runtime/product baseline. |
| `backfeed_packet_ready` | The repository has emitted the static packet; LDD acknowledgement is still pending. |
| `consumer_ack_pending` | LDD has not yet confirmed consumption of the newest backfeed packet. |
| `consumer_acknowledged` | LDD has acknowledged the newest static backfeed packet. |

Phase 9.1 after-state is `backfeed_packet_ready`.

## Resolution Workflow

1. Compare the LDD-visible formal TWOS Runtime Status Update against the repository-validated TWOS baseline.
2. If the visible baseline is older, classify it as `stale_superseded_baseline` for TWOS runtime baseline purposes.
3. Preserve all LDD trading/account/execution facts under the LDD trading/execution Source of Truth.
4. Emit a static TWOS/LDD Runtime Status Backfeed packet.
5. Require LDD to consume the newest packet before using TWOS runtime/product baseline.
6. Move to `strict_baseline_sync_ready` only after LDD acknowledgement confirms the packet is consumed and no newer repository baseline is pending.

## Required LDD Action When Drift Exists

When `baseline_drift_detected` is true:

1. Do not mutate runtime state.
2. Do not infer live readiness.
3. Do not create customer-facing readiness.
4. Emit static backfeed packet.
5. Mark older visible baseline as stale/superseded.
6. Require LDD to consume the newest backfeed packet before using TWOS product/runtime baseline.

## Quote-Type Preservation

Trading-facing artifacts must preserve quote-source tagging even though Phase 9.1 performs no trading or market-data action:

- `watchlist_price`
- `premarket_price`
- `holding_valuation_price`
- `order_page_executable_price`
- `final_filled_price`

## Execution-Event Distinction

Trading-facing artifacts must preserve the distinction between:

- `actual_filled_trade`
- `expired_zero_fill_order`
- `canceled_order`
- `portfolio_change`
- `no_cash_impact_event`

This distinction is retained because the SPCX correction from Vol.8/LDD becomes a future protocol seed named `Execution Ledger Evidence Classifier / Zero-Fill Order Separation Protocol`.

Phase 9.1 does not implement that future classifier.

## Forbidden Scope

Phase 9.1 does not create or modify:

- production UI
- customer-facing UI
- hosted app
- API server
- live endpoint
- external API
- broker connection
- Binance connection
- live market data
- trading automation
- credential handling
- login/auth
- runtime mutation
- execution trigger
- order placement
- portfolio modification
- background worker
- scheduler
- notification dispatcher
- GitHub Issues
- GitHub Projects board
- package manager files
- build tools
- frontend framework
- network dependency

## Acceptance Criteria

Phase 9.1 is accepted when:

- Static/read-only protocol documentation exists.
- Backfeed packet schema and drift-state schema exist.
- LDD mock consumer fixtures exist and remain parseable JSON.
- Runtime record advances the baseline from `113` to `114`.
- Drift state advances from `baseline_drift_detected` to `backfeed_packet_ready`.
- Customer-facing readiness remains `false`.
- Live/runtime/execution framework count remains `0`.
- Static shell mode remains `local_static_read_only_fixture_only_no_network_no_execution`.
- Validation passes using only repository-local files and Python standard library.

## DUXD Queue Carried Into Later Vol.9 Phases

| Queue item | Status | Phase 9.1 handling |
|---|---|---|
| `Execution Ledger Evidence Classifier / Zero-Fill Order Separation Protocol` | Future protocol seed | Recorded only; not implemented. |
| Strict LDD consumer acknowledgement workflow | Future protocol refinement | Deferred until LDD can acknowledge packet consumption. |
| Current TWOS status pointer for LDD review sync | Future index improvement | Deferred; Phase 9.1 emits a packet but does not create live status routing. |
