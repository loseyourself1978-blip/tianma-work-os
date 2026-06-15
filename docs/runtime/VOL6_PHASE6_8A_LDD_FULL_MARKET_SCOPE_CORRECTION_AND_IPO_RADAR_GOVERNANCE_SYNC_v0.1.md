# Vol.6 Phase 6.8a LDD Full-Market Scope Correction and IPO Radar Governance Sync v0.1

## 1. Purpose

This Phase 6.8a package records the 2026-06-12 17:02-17:20 SGT/BJT LDD premarket review scope update as non-promoted governance evidence. It corrects the LDD review scope so future reviews scan the entire U.S. equity market instead of only current or former holdings.

This is not an execution reconciliation, UI task, API task, connector task, or trading automation task.

## 2. Source Priority

1. `user_broker_screenshots`
2. `user_binance_screenshots`
3. `user_instruction_scope_correction`
4. `external_market_data_for_validation_only`

External market data remains validation-only and must not become source of truth.

## 3. Runtime Baseline Correction

The LDD sync referenced stale TWOS runtime status: `Vol.6 Phase 6.7 - Cockpit Static Spec Integration Review` at `c2a2a06edba6216eed64998caba018c3a3adf03d`.

The correct implementation baseline is `Vol.6 Phase 6.8 - Static Consumer Fixture Integration and Handoff` at `704f006b52461459ccc995ee0b6de7a53bbb0de2`.

The market/account facts from the LDD sync are accepted as user-provided source input, while the product/runtime baseline is corrected to Phase 6.8.

## 4. Premarket Scope Update Window

- Sync type: `ldd_premarket_review_scope_update`
- Sync window: `2026-06-12 17:02-17:20 SGT/BJT`
- Timestamp: `2026-06-12T17:20:00+08:00`
- Market session: `2026-06-12_us_premarket`
- Operating mode: `cash_defense_core_position_survival_mode`
- Portfolio mode: `residual_core_position_mode`
- Previous active checkpoint: `2026-06-12T09:18:00+08:00`
- Checkpoint promoted: `false`
- Promotion block reason: `scope_correction_and_premarket_observation_no_execution`

## 5. Non-promoted Governance Evidence Rationale

The review contains premarket observation and scope correction, not confirmed execution. It should enter runtime history as governance evidence and timeline context, but it must not advance the active checkpoint or overwrite promoted post-close holdings.

## 6. LDD Full-market Review Scope Correction

Recent LDD reviews over-focused on current and historical positions. The corrected scope is the entire U.S. equity market, including sectors, new listings, IPO candidates, and non-position opportunities.

LDD must keep account risk management, but account risk management is only one layer. It must not crowd out full-market opportunity scanning.

## 7. Account Risk Management Layer

The existing account risk layer remains active:

- preserve cash as the main U.S. position;
- keep GOOG 9 and NVDA 10 as residual core positions;
- keep closed leveraged and cleaned-up positions closed unless a new approved rule exists;
- maintain Binance USDT defense above 70%;
- keep ZEC grid closed.

## 8. Full-market Opportunity Scan Layer

Every LDD market review should include a market-wide scan layer covering:

1. `AI_semiconductor`
2. `software_cloud_cybersecurity`
3. `aerospace_defense_space`
4. `robotics_autonomous_driving`
5. `energy_oil_nuclear_power`
6. `financials_crypto_related_equities`
7. `healthcare_glp1`
8. `consumer_platform_tech`
9. `IPO_new_listings`
10. `ETF_index_leveraged_tools`

## 9. Sector Rotation Heatmap

The sector rotation heatmap is a static review contract. It requires each covered sector to show whether it contains current positions, non-position candidates, both, or neither. It does not fetch live data.

## 10. New Listing / IPO Radar

The IPO radar records user/LDD-provided candidate radar items. `SPCX / SpaceX` is recorded only as a user-provided candidate and rule proposal. TWOS does not independently assert listing facts, fetch quotes, or enable order execution.

## 11. Non-position Candidate Watchlist

The non-position candidate watchlist includes `SPCX`, `MU`, `DRAM`, `ASML`, `TSM`, `AMD`, and `ORCL`. These entries are static candidate radar items, not live recommendations or automated order instructions.

## 12. Candidate-to-position Pipeline

Candidate promotion requires:

1. market scan detection;
2. candidate watchlist addition;
3. external verification before execution;
4. real executable quote confirmation;
5. rule review;
6. manual user order only;
7. post-execution reconciliation;
8. checkpoint promotion only after confirmed execution.

System execution is blocked at every stage.

## 13. Forbidden Chase List

The forbidden chase list blocks emotional or rebound-driven entries in `SPCX`, `SOXL`, `GLD`, `GGLL`, `UGL`, `INTC`, `BTC`, and `ZEC` scenarios where confirmation gates are not satisfied.

## 14. Position Replacement or Expansion Review

Candidates must not automatically replace or expand current positions. GOOG and NVDA must not be forcibly sold to fund candidate entries. U.S. cash defense and Binance USDT defense remain protected.

## 15. Current Account Observation

- Total assets: `38090.02 USD`
- Total day P/L: `+492.55 USD`
- Cash: `18795.68 USD`
- U.S. section: `24091.21 USD`
- U.S. holding value: `5295.53 USD`
- Implied U.S. cash: `18795.68 USD`
- U.S. cash ratio: `78.0%`
- U.S. holding P/L: `+2212.07 USD`
- U.S. day P/L: `+33.16 USD`

## 16. Current U.S. Position Observation

- GOOG: `9`, broker price `359.410`, market value `3234.69 USD`
- NVDA: `10`, broker price `205.620`, market value `2056.20 USD`
- TSLA residual: `0.0116`
- GGLL: `0`
- GLD: `0`
- SOXL: `0`
- UGL: `0`
- INTC: `0`
- SOXS: `0`
- TSLQ: `0`
- GDXU: `0`

These are non-promoted premarket observations and must not overwrite the active checkpoint.

## 17. Binance Defensive Observation

- Total assets: `8252.94 USDT`
- Day P/L: `+6.2 USDT / +0.08%`
- USDT balance: `5936.00 USDT`
- USDT defense ratio: `71.9%`
- ETH: `0.8070416`
- DOGE: `8400.535`
- SOL: `2.931163`
- BTC: `0.00055762`
- ZEC: `0.012974`
- ZEC grid status: `closed_no_reopen`

## 18. Candidate Watchlist and SPCX Observation Rule

`SPCX / SpaceX` is recorded as a user/LDD-provided candidate radar item:

- category: `IPO_new_listing_space_ai_infrastructure`
- IPO price reference: `135 USD`
- allowed initial action: manual user action outside TWOS only;
- preferred first entry: one-share observation position;
- maximum initial position: 1-2 shares;
- 135-155: allow 1-2 shares;
- 155-175: allow max 1 share;
- 175-200: wait 30-60 minutes, no chase;
- above 200: no buy today;
- no market order;
- no heavy position;
- no selling GOOG or NVDA to fund SPCX;
- real executable quote and external verification required before any user action.

TWOS does not execute or stage the order.

## 19. Active Rule Rebase

The non-promoted rule set expands to 16 active governance rules, including full-market scan scope, SPCX observation constraints, no-reentry rules, GOOG/NVDA residual-core rules, and cash/USDT defense ratios.

## 20. Quote-type Tagging and Source-of-truth Policy

Broker position prices, external validation prices, IPO references, and real executable quotes must be separated. User broker/Binance screenshots and user instruction scope correction are source input; external market data is validation-only.

## 21. Cross-workspace Progress Drift Detection

The sync contained stale TWOS phase and commit references. Phase 6.8a records this drift and requires a TWOS Runtime Status Update backfeed after completion so future LDD syncs start from the current product/runtime baseline.

## 22. LDD ↔ TWOS Baseline Backfeed Impact

After Phase 6.8a completes, LDD should be backfed that TWOS is at Phase 6.8a, with the active checkpoint unchanged at `2026-06-12T09:18:00+08:00`, latest timeline event advanced to `2026-06-12T17:20:00+08:00`, and the scope correction recorded as non-promoted governance evidence.

## 23. Final Instruction

1. LDD scope is the entire U.S. equity market, not only existing positions.
2. SPCX can only be considered as a 1-share observation position if the user manually decides outside TWOS.
3. Do not chase SPCX above 175 without 30-60 minute confirmation.
4. No SPCX buy above 200 today.
5. Keep GOOG 9 and NVDA 10.
6. Keep cash as the main position.
7. Do not reopen SOXL, GLD, GGLL, UGL, or INTC before confirmation.

## 24. Explicit Non-goals

No frontend app, customer-facing UI, HTML/CSS/JS UI, API server, live endpoint, external API, broker/Binance connection, live market data, trading automation, credential handling, runtime mutation UI, execution trigger, GitHub Issues, or GitHub Projects board were created.

## 25. Validation Strategy

Validation requires runtime record validation, report generation, existing static contract validators, and the new `validate_ldd_full_market_scope_governance_sync.sh` semantic validator.

## 26. Phase 6.9 Entry Impact

Phase 6.9 should include this full-market scope correction and IPO radar governance sync in the Vol.6 handoff. Phase 6.9 should keep the active checkpoint unchanged unless a later post-close execution reconciliation promotes a new checkpoint.
