# Cockpit View Model Contract v0.1

## 1. Purpose

Vol.5 Phase 5.2 defines a stable cockpit view model contract for future UI, generated reports, and downstream consumers. It translates the current LDD cockpit JSON files into a documented data contract: what can be read, what each field means, which fields are required, which fields are optional, and how state vocabularies should be interpreted.

This is a non-UI phase. The contract prepares future rendering work without creating frontend files, connecting external APIs, or adding trading automation.

## 2. Scope

The contract covers the current LDD runtime cockpit layer:

- latest checkpoint and portfolio mode
- account overview and section-level structure
- active and closed positions
- risk summary
- active rules
- strategy states
- runtime timeline
- pending command status
- memory checkpoint
- warnings and data quality

It is designed for file-based consumers that read `cockpit/ldd/manifest.json` first, then load the referenced cockpit JSON files.

## 3. Non-Goals

- No UI is built.
- No frontend app files are created.
- No brokerage, Binance, market-data, GitHub, or external API connection is added.
- No trading automation is added.
- No GitHub Projects board is created.
- No new GitHub Issues are created.
- The 2026-06-08 checkpoint is not re-ingested.
- Historical runtime facts are not changed.

## 4. Source Cockpit Files

Future consumers should treat these as source files for the view model:

- `cockpit/ldd/manifest.json`
- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/account_structure.json`
- `cockpit/ldd/active_rules.json`
- `cockpit/ldd/strategy_states.json`
- `cockpit/ldd/pending_commands.json`
- `cockpit/ldd/memory_checkpoint.json`
- `cockpit/ldd/runtime_timeline.json`

Supporting context:

- `docs/runtime/COCKPIT_READY_SUMMARY_LAYER_v0.1.md`
- `docs/runtime/DEFENSE_COCKPIT_CONSISTENCY_REVIEW_v0.1.md`
- `records/ldd/2026-06-08/cockpit_consistency_review_0844_sgt.json`

## 5. View Model Design Principles

- Read `manifest.json` first.
- Use `latest_active_checkpoint` as the current-state anchor.
- Treat older records as history unless they are explicitly referenced by the latest checkpoint.
- Render state from generated cockpit JSON instead of parsing raw records directly.
- Preserve source file references on every panel, row, and timeline event.
- Do not turn watchlist, night-session, or non-executable quotes into execution-valid triggers.
- Separate current positions from closed or historical positions.
- Render prohibitions and no-reentry rules as first-class rule states.
- Keep warnings visible and never silently hide data-quality issues.
- User-provided broker and Binance screenshots remain the execution source of truth.

## 6. Top-Level View Model Structure

The conceptual top-level view model should contain:

```json
{
  "meta": {},
  "checkpoint": {},
  "portfolio_mode": {},
  "account_overview": {},
  "account_sections": {},
  "positions": [],
  "closed_positions": [],
  "risk_summary": {},
  "active_rules": [],
  "strategy_states": [],
  "timeline": {},
  "pending_commands": {},
  "memory_checkpoint": {},
  "warnings": [],
  "data_quality": {}
}
```

## 7. Required Fields

Required fields for a future view model:

- `meta.project`: project name.
- `meta.contract_version`: contract version.
- `checkpoint.latest_active_checkpoint`: active checkpoint used for current-state display.
- `portfolio_mode.current`: current portfolio operating mode.
- `account_overview.total_account`: total account state from the latest cockpit summary.
- `account_sections.us_equities`: U.S. equity section state.
- `account_sections.crypto_spot`: Binance / crypto section state.
- `positions`: current open positions or current-position groups.
- `closed_positions`: closed or historical positions that must not render as active.
- `risk_summary.open_risks`: current risk items.
- `active_rules`: active, watch, triggered, executed, prohibited, and risk-line rules.
- `strategy_states`: current strategy states.
- `timeline.events`: chronological runtime events.
- `warnings`: cockpit and data-quality warnings.
- `data_quality.execution_source_of_truth`: source-of-truth statement.

## 8. Optional Fields

Optional fields:

- `account_sections.hong_kong_equities`: present when latest checkpoint includes updated Hong Kong equity detail.
- `positions.by_account`: grouped positions by U.S., Hong Kong, crypto, cash, or stablecoin section.
- `risk_summary.near_triggers`: compact list of rules near a trigger.
- `pending_commands.commands`: command rows when command records exist.
- `memory_checkpoint.superseded_snapshot_candidates`: memory cleanup candidates.
- `data_quality.quote_type_tags`: quote type categories and execution-validity hints.
- `timeline.filters`: future filter metadata derived from timeline event tags and priorities.

## 9. Field Semantics

- `generated_at`: generation timestamp for the source file; not always a market event time.
- `latest_active_checkpoint`: latest checkpoint used for current LDD state.
- `source_files`: local files supporting the field or payload.
- `cockpit_priority`: UI attention level, not a trading instruction.
- `tags`: machine-readable labels for filtering, grouping, and display.
- `warnings`: issues that should remain visible to the user or future agent.
- `requires_execution_price_confirmation`: true when a rule must not execute from non-order-ticket quotes.

## 10. Risk State Vocabulary

Recommended risk states:

- `normal`: no current action needed.
- `watch`: monitor, but no trigger is near.
- `near_trigger`: approaching a trigger or risk line.
- `triggered`: trigger condition appears active in the record.
- `protect`: defense or reduction may be needed.
- `reduce`: reduction is the intended rule action.
- `closed`: risk has been closed or retired.
- `prohibited`: add, reopen, or chase behavior is prohibited.
- `unknown`: insufficient information.

## 11. Position State Vocabulary

Recommended position states:

- `active_position`
- `core_position`
- `watch_position`
- `risk_valve`
- `residual_watch_position`
- `closed_position`
- `historical_position`
- `prohibited_reentry`
- `unknown`

Closed positions must not render as active opportunities. For the current LDD checkpoint, SOXL, UGL, and INTC are `closed_position` with no re-add.

## 12. Rule State Vocabulary

Rule states:

- `active`
- `near_trigger`
- `triggered`
- `awaiting_execution_confirmation`
- `executed`
- `stale`
- `superseded`
- `historical`
- `prohibited`

Rule type examples:

- execution rule
- watch rule
- prohibition / no-reentry rule
- risk-line rule
- concentration-risk rule
- staged buyback rule
- quote-validation rule

## 13. Strategy State Vocabulary

Strategy states:

- `active`
- `monitoring`
- `closed`
- `superseded`
- `historical`
- `waiting_for_trigger`
- `not_opened`

For current LDD defense mode:

- NVDA: `monitoring`, main core-risk watch.
- GOOG / GGLL: GGLL is the main remaining leveraged ETF risk valve.
- GLD: ordinary concentration / risk-line protection.
- BTC: `waiting_for_trigger`.
- ETH / SOL / DOGE: no-add defense.
- ZEC grid: `closed`, profit-locked, no reopen.
- SOXL / UGL / INTC: `closed`.

## 14. Timeline Event Vocabulary

Timeline event types:

- `portfolio_snapshot`
- `strategy_state_update`
- `trigger_rule_update`
- `execution_event`
- `rule_review`
- `account_structure_review`
- `sync_delta`
- `pending_command`
- `command_intelligence`
- `memory_checkpoint`
- `report_generation`
- `unknown`

Future UI should group by event date, then sort by `event_time`, and display `title`, `summary`, `event_type`, `cockpit_priority`, `source_file`, `state_before`, `state_after`, and `tags`.

## 15. UI-Readiness Notes Without Building UI

The current cockpit files are conceptually UI-ready, but they are not yet a final UI API. A future non-UI generator should produce a single `cockpit/ldd/view_model.json` that conforms to this contract and removes the need for a frontend to merge multiple source files itself.

Until that exists, a future UI prototype should:

- load `manifest.json`;
- load the seven cockpit summary files and `runtime_timeline.json`;
- merge them according to this contract;
- show warnings and source files;
- avoid any execution control or API connection.

## 16. Current LDD Defense-Mode Example

Current checkpoint:

```text
2026-06-08T08:44:00+08:00
```

Current defense-mode facts:

- Portfolio mode remains `core_position_defense_mode`.
- SOXL, UGL, and INTC are `closed_position`; no re-add.
- GGLL is the main remaining leveraged ETF risk valve.
- NVDA is the main core-risk watch.
- GLD is ordinary GLD concentration / risk-line protection.
- Binance remains USDT-dominant defense.
- BTC buyback trigger at 75,500-76,000 remains inactive.
- ZEC grid is closed / profit-locked / do not reopen.
- No new execution was reported at the 2026-06-08 08:43-08:44 checkpoint.

## 17. Validation Expectations

Validation should confirm:

- contract record validates against `schemas/cockpit_view_model_contract.schema.json`;
- latest active checkpoint remains `2026-06-08T08:44:00+08:00`;
- timeline warnings remain `0`;
- timeline event count increases by one when the contract record is included;
- cockpit remains in `core_position_defense_mode`;
- active rule count remains `6`;
- strategy state count remains `16`;
- no UI, frontend app, external API connection, or trading automation is added.

## 18. Known Limitations

- The contract is conceptual; it does not yet produce a single normalized `view_model.json`.
- No UI rendering has been implemented.
- No live quote, broker, Binance, or market-data verification is performed.
- Quote Type Tagging is represented but not programmatically enforced.
- Future consumers must still handle missing optional fields gracefully.

## 19. Recommended Next Phase

Recommended next phase:

```text
Vol.5 Phase 5.3 - Cockpit View Model Generator
```

The next phase should generate a single local, deterministic `cockpit/ldd/view_model.json` from existing cockpit summaries and the runtime timeline, still without building UI or connecting external APIs.
