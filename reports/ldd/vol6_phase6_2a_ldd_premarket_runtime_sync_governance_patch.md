# Vol.6 Phase 6.2a LDD Premarket Runtime Sync Governance Patch

## Baseline

- Starting commit: `1ee23ba0c9078a735d47287e2300528ff0d7427e`
- Active checkpoint remains `2026-06-10T08:49:00+08:00`
- Timeline remains `84` events with `0` warnings
- Operating mode remains `core_position_defense_mode`

## Source-of-Truth Rule

User-provided Longbridge and Binance screenshots plus the user-provided LDD
Review Sync are the Source of Truth. External market data is cross-check
context only.

## Stale-checkpoint Override

The latest broker screenshots supersede stale holding quantities that still
showed GLD 20 and NVDA 20. This patch records GLD 10 and NVDA 15 without
editing prior records or promoting a new active checkpoint.

## Account Delta

- U.S. assets: `24,317.94 USD`
- U.S. holding value: `13,097.80 USD`
- U.S. cash: approximately `11,220.14 USD`
- U.S. cash ratio: approximately `46.1%`
- HK holding value: `104,800 HKD`
- Binance assets: `8,171.46 USDT`
- Binance USDT defense ratio: approximately `72.6%`

## Active Positions

- GOOG 14
- GLD 10
- NVDA 15
- GGLL 10
- Tiny TSLA residual

## Closed Positions

SOXL, UGL, INTC, SOXS, TSLQ, and GDXU remain closed with no reentry.

## Updated Rules

- GLD rules rebase to 10 shares; the next risk-control reduction is recorded
  as non-automated guidance.
- NVDA rules rebase to 15 shares with
  `partial_risk_already_executed`.
- GGLL remains the leveraged-risk valve for GOOG weakness.
- BTC buyback remains inactive.
- ETH, SOL, DOGE, and ZEC remain no-add; ZEC grid remains closed.

## DUXD / TWOS Feedback

- Stale-checkpoint override logic
- Post-execution rule rebase
- Partial-risk-already-executed state
- HK Profit Surge Protection upgrade
- Section-level cash quality score

## Validation Result

The governance sync record validates without changing cockpit state, active
checkpoint, timeline, UI boundary, permission boundary, or customer-facing
readiness.

## Remaining Gap Before Phase 6.3

The read-only API contract must distinguish active checkpoint data from newer
non-promoted governance sync evidence and preserve Source-of-Truth,
quote-type, rule-base quantity, and stale-field override metadata.
