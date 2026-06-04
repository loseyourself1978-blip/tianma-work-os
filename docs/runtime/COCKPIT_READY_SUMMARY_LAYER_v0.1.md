# Cockpit-Ready Summary Layer v0.1

Status: Vol.4 Phase 4.2b draft

## Purpose

The Cockpit-Ready Summary Layer turns local runtime records, generated reports, and the runtime timeline into stable JSON files that a future LDD cockpit can read first.

Runtime records are detailed and audit-friendly. Reports are human-readable. The runtime timeline is chronological. Cockpit summary JSON is the current-state layer: it answers what is active now, what needs attention, and which source files support the view.

## Why This Follows Timeline And Delta Ingestion

The cockpit summary layer depends on two earlier steps:

- Runtime Timeline Layer: provides chronological event context and a cockpit-readable timeline file.
- Delta ingestion: ensures the latest active checkpoint is current before any cockpit summary is generated.

For the current LDD pilot, the summary layer uses `2026-06-04T08:13:00+08:00` as the latest active checkpoint. Older records remain available as history, but they should not override the latest post-close state.

## Data Layers

- Runtime records: source JSON under `records/ldd/**/*.json`.
- Generated reports: Markdown summaries under `reports/ldd/`.
- Runtime timeline: chronological cockpit data in `cockpit/ldd/runtime_timeline.json`.
- Cockpit summary JSON: current-state summary files under `cockpit/ldd/`.
- Future UI: not implemented in this phase; it should read the cockpit JSON rather than parse raw records directly.

## Inputs

The generator reads local files only:

- `records/ldd/**/*.json`
- `cockpit/ldd/runtime_timeline.json`
- `reports/ldd/latest_runtime_report.md`
- `reports/ldd/latest_active_memory_checkpoint.md`
- `reports/ldd/memory_cleanup_recommendations.md`

It does not call brokerage APIs, Binance APIs, market data APIs, GitHub APIs, or external services.

## Outputs

Generated cockpit files:

- `cockpit/ldd/manifest.json`
- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/active_rules.json`
- `cockpit/ldd/strategy_states.json`
- `cockpit/ldd/account_structure.json`
- `cockpit/ldd/pending_commands.json`
- `cockpit/ldd/memory_checkpoint.json`

`manifest.json` is the entrypoint. Future cockpit prototypes should read it first, then follow the recommended read order.

## Non-Goals

Vol.4 Phase 4.2b does not implement:

- UI.
- External APIs.
- Brokerage or Binance connection.
- Real-time market data.
- Trading automation.
- GitHub Projects board.
- GitHub Issue creation.

## Next Phase

Recommended next phase:

```text
Vol.4 Phase 4.3 - Lightweight LDD Cockpit Prototype
```

The prototype should read `cockpit/ldd/manifest.json` and summary JSON files instead of rebuilding runtime parsing logic inside the UI.
