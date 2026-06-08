# Cockpit View Model Generator v0.1

## Purpose

Vol.5 Phase 5.3 adds a non-UI generator that reads the existing cockpit summary files and produces one stable frontend-ready JSON artifact:

```text
cockpit/ldd/view_model.json
```

The view model follows the Phase 5.2 contract and gives future UI, reports, and downstream consumers one file to read after `cockpit/ldd/manifest.json`.

## Scope

The generator reads local cockpit files only:

- `cockpit/ldd/manifest.json`
- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/account_structure.json`
- `cockpit/ldd/active_rules.json`
- `cockpit/ldd/strategy_states.json`
- `cockpit/ldd/pending_commands.json`
- `cockpit/ldd/memory_checkpoint.json`
- `cockpit/ldd/runtime_timeline.json`

It writes:

- `cockpit/ldd/view_model.json`

Supporting artifacts:

- `schemas/cockpit_view_model.schema.json`
- `scripts/generate_cockpit_view_model.py`
- `scripts/generate_cockpit_view_model.sh`
- `records/ldd/2026-06-08/cockpit_view_model_generation_0844_sgt.json`
- `reports/ldd/cockpit_view_model_summary.md`

## Non-Goals

- No UI is built.
- No frontend app files are created.
- No external APIs are connected.
- No trading automation is added.
- No GitHub Projects board is created.
- No GitHub Issues are created.
- The 2026-06-08 checkpoint is not re-ingested.
- Historical runtime facts are not modified.

## Generated View Model Sections

`cockpit/ldd/view_model.json` includes:

- `meta`
- `checkpoint`
- `portfolio_mode`
- `account_overview`
- `account_sections`
- `positions`
- `closed_positions`
- `risk_summary`
- `active_rules`
- `strategy_states`
- `timeline`
- `pending_commands`
- `memory_checkpoint`
- `warnings`
- `data_quality`

## Current LDD Defense-Mode State

The generated view model preserves the current defense-mode facts:

- Latest active checkpoint remains `2026-06-08T08:44:00+08:00`.
- Portfolio mode remains `core_position_defense_mode`.
- SOXL, UGL, and INTC remain `closed_position`, 0 shares, no re-add.
- GGLL remains the main remaining leveraged ETF risk valve.
- NVDA remains the main core-risk watch.
- GLD remains ordinary GLD concentration / risk-line protection.
- Binance remains USDT-dominant defense.
- BTC buyback trigger 75,500-76,000 remains inactive.
- ZEC grid remains closed / profit-locked / do not reopen.
- No new execution was reported at the 2026-06-08 08:43-08:44 checkpoint.

## Data Quality Rules

The generator records these data-quality flags:

- no external API connected
- no trading automation enabled
- no UI or frontend app created
- user-provided broker/Binance screenshots remain execution source of truth
- latest active checkpoint confirmed from cockpit files
- timeline warning count
- active rule count
- strategy state count
- Quote Type Tagging remains required before executable-trigger use

## Validation

Validation should include:

- `cockpit/ldd/view_model.json` against `schemas/cockpit_view_model.schema.json`
- generation record against `schemas/cockpit_view_model_generation.schema.json`
- existing cockpit summary files
- existing runtime records

Expected current results:

- Latest active checkpoint: `2026-06-08T08:44:00+08:00`
- Portfolio mode: `core_position_defense_mode`
- Active rules: `6`
- Strategy states: `16`
- Timeline warnings: `0`

## Recommended Next Phase

Recommended next phase:

```text
Vol.5 Phase 5.4 - View Model Quality Gates
```

That phase should add deterministic checks for required view-model sections, status vocabularies, source-file availability, stale-state prevention, and UI-readiness assertions before any frontend prototype is built.
