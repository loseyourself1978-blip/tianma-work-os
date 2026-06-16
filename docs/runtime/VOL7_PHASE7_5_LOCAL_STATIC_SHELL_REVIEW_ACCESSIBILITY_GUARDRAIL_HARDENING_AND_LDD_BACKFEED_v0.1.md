# Vol.7 Phase 7.5 Local Static Shell Review, Accessibility, Guardrail Hardening, and LDD Backfeed v0.1

## 1. Phase Summary

Vol.7 Phase 7.5 reviews and hardens the Phase 7.4 local static shell skeleton. It improves guardrail visibility, accessibility, copy clarity, panel hierarchy, quote-drift labeling, cash-defense split display, transfer/P&L separation, opportunity-cost context, and position-state separation.

This phase remains local static preview work only. It does not create a production UI, customer-facing UI, hosted app, API server, live endpoint, account connector, credential path, runtime mutation path, or execution path.

## 2. Baseline and Correction

Baseline commit: `9de6673708ca2449701e52f41f9e2bca3787a879`

Active checkpoint remains `2026-06-12T09:18:00+08:00`.

The later LDD post-close review referenced Vol.7 Phase 7.3 as the TWOS baseline. That reference is stale. The current TWOS baseline is Vol.7 Phase 7.4, and Phase 7.5 treats the LDD post-close review as fixture-only DUXD product backfeed.

## 3. LDD Post-Close Backfeed Source

- Review: LDD Post-Close Review Sync
- Market session: 2026-06-15 U.S. regular-session post-close
- Screenshot time: 08:37-08:38 SGT/BJT
- Source of truth: user Longbridge and Binance screenshots
- Execution source of truth: broker/Binance order page and final filled order records
- External market data: cross-check only

All values are static, timestamped, fixture-only, read-only, non-live, and non-executable.

## 4. Guardrail Visibility

The shell must show these labels prominently:

- `LOCAL STATIC PREVIEW ONLY`
- `STATIC FIXTURE`
- `READ ONLY`
- `NOT EXECUTABLE`
- `NO LIVE DATA`
- `NO BROKER CONNECTION`
- `NO BINANCE CONNECTION`
- `NO CREDENTIAL HANDLING`
- `NO RUNTIME MUTATION`
- `CUSTOMER-FACING READINESS: FALSE`

Guardrails are visible as text, not color-only cues.

## 5. Accessibility Review

Phase 7.5 hardens accessibility by requiring:

- semantic headings
- panel regions
- keyboard-friendly static navigation
- clear link text
- visible critical warnings
- no color-only safety signaling
- no hover-only critical information
- readable contrast notes in this document and validator coverage

## 6. Static Safety Copy

The shell must clearly state:

- this is not production
- this is not customer-facing
- this is not live data
- this cannot trade
- this cannot connect to accounts
- this cannot accept credentials
- execution source remains broker/Binance order page and final filled order records

## 7. Quote Drift Layer

The shell separates:

- holding quote
- watchlist quote
- night-session quote
- premarket quote
- executable order-book quote
- final filled order price

Required copy:

`Execution source remains broker/Binance order page and final filled order records.`

Holding, watchlist, night-session, and premarket quotes must not be represented as executable prices.

## 8. Cash Defense and HK Exposure Split

The shell separates:

- U.S. account cash-defense ratio: approximately 77.6%
- Binance USDT defense ratio: approximately 70.6%
- HK 02513 holding value: 145,700 HKD
- total cross-account risk placeholder: fixture-only

Required field:

`cash_defense_split_extended_to_hk_required: true`

## 9. Transfer and P/L Separation

The 49.99 USDT withdrawal is represented as account movement, not trading loss.

Required copy:

`completed transfer / withdrawal, not trading loss`

Required field:

`transfer_withdrawal_pnl_separation_required: true`

## 10. Position State Corrections

Phase 7.5 preserves these corrections:

- `ggll_current_state: "zero_position_not_residual_risk_valve"`
- `zec_grid_state: "closed_no_reopen"`
- `usdt_defense_floor: 0.70`
- LDD scope remains the entire U.S. equity market, not only existing or former positions

GGLL must be zero-position and must not be displayed as an active residual risk valve.

## 11. Opportunity Cost Tracker

Required field:

`opportunity_cost_tracker_required: true`

Candidate assets:

- SOXL
- GDXU
- GGLL
- GLD
- UGL
- INTC
- SPCX
- MU
- DRAM

Rules:

- opportunity cost is hindsight/context only
- opportunity cost is separate from rule compliance score
- opportunity cost must not trigger buy/re-entry actions
- opportunity cost must not override cash-defense mode
- opportunity cost must not be treated as execution advice

## 12. Rule Compliance vs Opportunity Capture

Required field:

`rule_compliance_opportunity_capture_separation_required: true`

Latest static review scores:

- Rule compliance: 9.5/10
- Risk control: 9/10
- Return capture: 7/10
- Account structure: 9/10
- Emotional discipline: 9/10
- DUXD feedback value: 10/10
- Overall review score: 8.9/10

These scores are post-close review context only, not execution logic.

## 13. Zero-Position Candidate Radar and Forbidden Chase List

Required fields:

- `zero_position_candidate_radar_required: true`
- `forbidden_chase_list_required: true`
- `ipo_new_listing_radar_required: true`

Required corrections:

- GGLL is zero-position, not residual risk valve
- ZEC grid is closed / no reopen
- SPCX is IPO radar only, max 1 share limit order if considered later, no chase, no SPCH/SSPC, and do not sell GOOG/NVDA to fund it
- SOXL/GDXU/GLD/UGL are no-chase after high-beta rebound

## 14. LDD Full-Market Scope

Scope principle:

`LDD scope is the entire U.S. equity market, not only existing or former positions.`

This supports future inclusion of MU, DRAM, AMD, TSM, SPCX, and other market-wide candidates even when they are not current holdings.

## 15. Validation Strategy

The Phase 7.5 validator checks:

- required files and schema/report/record presence
- all expected statuses are `passed`
- warnings and errors are empty
- required static flags remain correct
- guardrail labels are visible
- accessibility basics are represented
- quote-drift types and execution SoT copy are present
- U.S./Binance/HK cash-defense split is represented
- transfer/P&L separation is represented
- opportunity cost and rule-compliance separation are represented
- no network, API, credential, execution, mutation, package, server, scheduler, worker, or publish affordance is introduced

## 16. Exit Criteria

Phase 7.5 is complete only if:

- required files are created
- allowed static shell files are reviewed/hardened
- review report validates
- full existing validation stack passes
- runtime records increment from 104 to 105
- timeline events increment from 104 to 105
- timeline warnings remain 0
- customer-facing readiness remains false
- static shell remains isolated under `static_shell/ldd/`
- Opportunity Cost Tracker, Zero-Position Candidate Radar, Forbidden Chase List, HK exposure split, and 49.99 USDT transfer/P&L separation are covered

## 17. Handoff to Phase 7.6

Next recommended phase:

`Vol.7 Phase 7.6 - Local Static Shell Demo Pack and Operator Walkthrough`

Phase 7.6 should prepare a local-only demo pack and operator walkthrough. It must remain local only, static only, read-only only, fixture-only, no network, no API, no live data, no broker/Binance connection, no credential handling, no execution, no runtime mutation, and not customer-facing.
