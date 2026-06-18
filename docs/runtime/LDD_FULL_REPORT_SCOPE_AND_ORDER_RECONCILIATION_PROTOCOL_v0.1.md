# LDD Full Report Scope and Order Reconciliation Protocol v0.1

## Purpose

This protocol defines static/read-only requirements for preserving full LDD report scope, full standalone LDD -> TWOS sync regeneration, order-detail reconciliation, zero-fill separation, Dream Sleeve monitoring boundaries, quote-type tagging, and static cockpit panel requirements.

It is not live implementation.

## Definitions

`ldd_full_report_scope`: The required report surface for LDD premarket and post-close reviews, including full-market scan, sector rotation, non-position candidate radar, forbidden chase list, current holdings/risk rules, execution ledger, Dream Sleeve monitoring, product feedback, and TWOS sync block.

`full_market_scan_layer`: The report layer that examines the broader market beyond current holdings, former holdings, and residual positions.

`full_standalone_sync_regeneration_rule`: The rule requiring a fully regenerated latest LDD report and full LDD -> TWOS Sync Block after user corrections unless the user explicitly says otherwise.

`scope_regression_guard`: The static guard that detects holdings-only, current-position-only, former-position-only, missing candidate radar, missing sector heatmap, missing forbidden chase list, missing Dream Sleeve panel, missing execution ledger, missing order reconciliation, missing TWOS sync block, or missing full regeneration rule.

`order_count_anomaly_detector`: The static requirement that an apparent current-day order count discrepancy cannot be classified as filled/canceled/expired without order-detail evidence.

`order_detail_reconciliation`: The evidence requirement that order details are checked before trade direction, filled quantity, cash impact, or portfolio change is classified.

`execution_ledger_gap_detector`: The static state that remains open until order-detail evidence resolves execution-ledger ambiguity.

`zero_fill_order_separation`: The rule that expired zero-fill orders are separate from actual filled trades and do not create position or cash impact.

`dream_sleeve_monitoring_only`: The rule that Dream Sleeve is monitoring and recommendation only, not main-strategy execution authority.

`quote_type_tagging`: The requirement to preserve watchlist, premarket, after-hours, holding valuation, order-page executable, and final filled price distinctions.

`twos_sync_block`: The static backfeed block used to carry LDD report outcomes into TWOS product/runtime planning without mutating LDD trading facts.

## Non-Regression Rules

1. LDD premarket/post-close reviews must not collapse into holdings-only reviews.
2. LDD premarket/post-close reviews must not collapse into current-position-only reviews.
3. LDD premarket/post-close reviews must not collapse into former-position-only reviews.
4. Current holdings analysis must be separated from full-market candidate radar.
5. Dream Sleeve monitoring-only must be separated from LDD rational main strategy.
6. Forbidden Chase List must be visible and explicit.
7. Sector Rotation Heatmap must be visible and explicit.
8. Non-Position Candidate Radar must be visible and explicit.
9. Execution Ledger and Order State must be visible and explicit.
10. Order count anomalies must require order-detail evidence before trade/cash/position classification.
11. Zero-fill expired orders must remain separated from actual filled trades.
12. Quote-type tagging must preserve watchlist, premarket, after-hours, holding valuation, order-page executable, and final filled price distinctions.
13. User correction to report scope, assumptions, screenshots, order details, source-of-truth priority, execution classification, rules, or format requires regenerating the full latest LDD report and full LDD -> TWOS Sync Block unless the user explicitly says otherwise.

## Non-Activation Rules

1. Static report-scope requirements do not create customer-facing readiness.
2. Static cockpit panel requirements do not create live UI.
3. Static cockpit panel requirements do not create live runtime readiness.
4. Static cockpit panel requirements do not create execution readiness.
5. Static cockpit panel requirements do not create market data connectivity.
6. Static cockpit panel requirements do not create broker/Binance connectivity.
7. Static cockpit panel requirements do not create credential handling readiness.
8. Static cockpit panel requirements do not create scheduler or notification dispatcher readiness.
9. Static cockpit panel requirements do not mutate trading facts, portfolio state, account state, cash state, or execution ledger state.
10. Static cockpit panel requirements only define planning, fixture, static shell, and validation requirements.

## Source-of-Truth Separation

TWOS runtime/product SoT must never override LDD trading/execution SoT.

LDD trading/execution SoT must never override TWOS runtime/product SoT.

Static cockpit panel requirements must never mutate trading facts, portfolio state, execution ledger state, account state, or cash state.

TWOS product/runtime SoT may hold phase, commit, runtime record count, framework index count, static shell readiness, validation state, customer-facing readiness, live/runtime readiness, and static cockpit/report panel requirements.

LDD trading/execution SoT may hold broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

## Full Standalone Sync Rule

Corrected LDD sync blocks must be regenerated as full standalone reports by default:

```text
incremental_patch_not_allowed_by_default
full_standalone_regeneration_required
```

Allowed states:

```text
full_sync_block_valid
incremental_patch_detected
prior_draft_superseded
full_regeneration_required
full_regeneration_completed
```

## Order Reconciliation Rules

```text
A screenshot showing current-day orders 0/1 is not enough to infer a filled trade.
Order-detail evidence is required before classifying trade direction, filled quantity, cash impact, or portfolio change.
Expired zero-fill orders must not be counted as actual filled trades.
Expired zero-fill orders must not create portfolio changes.
Expired zero-fill orders must not create cash impact.
```

## Dream Sleeve Boundary

Dream Sleeve is monitoring and recommendation only. It does not affect rational main strategy decisions for building, holding, reducing, clearing, or risk control decisions. It does not justify main-strategy chase, does not affect GOOG/NVDA holdings, and does not affect cash-defense rules.

SPCX may remain on the Dream Sleeve watchlist for symbolic frontier-tech support. SPCX deep-limit symbolic orders must remain separated from LDD main strategy scoring. Main strategy must not chase SPCX at 190-200+. SPCH / SSPC remain prohibited.

## Quote-Type Tagging

```text
Holding valuation price is not necessarily executable.
Watchlist price is not necessarily executable.
Premarket price is not necessarily executable during regular session.
After-hours price is not necessarily executable during regular session.
Order-page executable price is the closest broker-visible execution reference before final fill.
Final filled price is the only actual execution price.
```

## Forbidden Scope

This protocol does not create production UI, customer-facing UI, hosted app, API server, live endpoint, external API, broker connection, Binance connection, live market data, trading automation, credential handling, login/auth, runtime mutation, execution trigger, order placement, portfolio modification, background worker, scheduler, notification dispatcher, GitHub Issues, GitHub Projects board, package manager files, build tools, frontend framework, network dependency, external integration, or production deployment capability.
