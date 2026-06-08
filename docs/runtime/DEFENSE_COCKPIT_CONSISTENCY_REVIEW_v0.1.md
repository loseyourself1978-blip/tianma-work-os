# Defense Cockpit Consistency Review v0.1

## Purpose

Vol.5 Phase 5.1 reviews whether the LDD cockpit layer is internally consistent enough to support a future UI layer. This is a review and validation phase only. It does not add a UI, external API connection, or trading automation.

## Scope

The review covers cockpit-facing JSON summaries, generated Markdown reports, and the runtime timeline produced from local records. It checks whether the current defense-mode state is clear, source-traceable, and stable for future rendering.

## Current Baseline Checkpoint

- Baseline checkpoint: `2026-06-08T08:44:00+08:00`
- Baseline commit: `838de562d2ef3febb20e052a23d44347745a3244`
- Portfolio mode: `core_position_defense_mode`
- Latest active LDD state source: `records/ldd/2026-06-08/account_state_delta_0843_0844_sgt.json`
- Runtime source of truth: user-provided broker and Binance screenshots remain authoritative.

## Cockpit Files Reviewed

- `cockpit/ldd/manifest.json`
- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/account_structure.json`
- `cockpit/ldd/active_rules.json`
- `cockpit/ldd/strategy_states.json`
- `cockpit/ldd/pending_commands.json`
- `cockpit/ldd/memory_checkpoint.json`
- `cockpit/ldd/runtime_timeline.json`

## Report Files Reviewed

- `reports/ldd/latest_runtime_report.md`
- `reports/ldd/account_structure_summary.md`
- `reports/ldd/active_trigger_rules.md`
- `reports/ldd/strategy_state_summary.md`
- `reports/ldd/runtime_timeline.md`

## Consistency Findings

- `manifest.json` points to all current cockpit summary files and provides a workable read order for a future UI.
- `latest_state.json` clearly exposes the latest active checkpoint, portfolio mode, account state, defense posture, closed cleanup positions, and Binance USDT defense ratio.
- `account_structure.json` separates U.S. equities, crypto spot, cash/stablecoin posture, leveraged exposure, closed cleanup positions, and quote quality.
- `active_rules.json` distinguishes defense-mode rule types well enough for future rendering: core-risk watch, leveraged ETF risk valve, concentration/risk-line protection, closed-position guardrail, staged buyback watch, and crypto no-add defense.
- `strategy_states.json` keeps 16 strategy states and represents NVDA, GOOG/GGLL, GLD, BTC, ETH/SOL/DOGE, ZEC, SOXL, UGL, and INTC consistently.
- `runtime_timeline.json` has a chronological event structure with stable source files, event types, summaries, tags, and zero warnings before this review record is added.
- SOXL, UGL, and INTC are consistently represented as `closed_position` or closed historical cleanup states.
- GGLL is consistently represented as the main remaining leveraged ETF risk valve.
- NVDA is consistently represented as the main core-risk watch.
- GLD is consistently represented as ordinary GLD concentration and risk-line protection, not merely UGL-linked protection.
- ZEC remains closed / no reopen, and BTC buyback remains inactive below the 75,500-76,000 trigger zone.
- Binance remains USDT-dominant, with the latest checkpoint using an approximately 71.7% USDT defense ratio.

## UI-Readiness Observations

- The cockpit layer is ready for a next non-UI phase that produces a stricter UI contract or view-model summary.
- `manifest.json` is a suitable entrypoint for a future cockpit prototype.
- `active_rules.json` and `strategy_states.json` already have enough stable IDs, statuses, priorities, tags, and source files for basic panel rendering.
- The current JSON is still hand-shaped by local generators and should not be treated as a final API contract.
- Before building UI, the next layer should define a cockpit view model with normalized cards, table rows, status badges, and sort/group keys.

## Known Limitations

- No UI exists yet.
- No database exists yet.
- No semantic search or conflict detection engine exists yet.
- No external data ingestion exists yet.
- The cockpit summaries depend on deterministic local generators and must be regenerated after new runtime records are added.
- Quote Type Tagging is represented, but executable quote validation is not automated.
- The review does not verify live broker, Binance, or market data.

## Recommended Next Phase

Recommended next phase:

```text
Vol.5 Phase 5.2 - Cockpit View Model Contract
```

This should define a stable non-UI JSON contract for future cockpit panels before any frontend is built.

Suggested outputs:

- `docs/runtime/COCKPIT_VIEW_MODEL_CONTRACT_v0.1.md`
- `schemas/cockpit_view_model_contract.schema.json`
- `records/ldd/2026-06-08/cockpit_view_model_contract_0844_sgt.json`

Vol.5 Phase 5.2 implements this recommendation as a contract-only phase. The next non-UI step should generate a concrete `cockpit/ldd/view_model.json` from the existing cockpit summaries and timeline.

## Explicit Confirmations

- No UI was created.
- No external APIs were connected.
- No trading automation was added.
- No GitHub Projects board was created.
- No new GitHub Issues were created.
- The 2026-06-08 checkpoint was not re-ingested.
