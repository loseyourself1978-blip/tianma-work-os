# Mock Consumer Package And UI Boundary Sample v0.1

## Purpose

Vol.5 Phase 5.6b provides static examples showing how future consumers can read
`cockpit/ldd/view_model.json` safely and consistently.

The package turns the view-model contract into concrete read-only examples for
reports, a future UI, a future API, mobile summaries, and AI Board review. It
does not implement any of those consumers.

## Scope

This phase creates:

- consumer-boundary documentation;
- static JSON payload examples;
- privacy and masking notes;
- one validated runtime review record;
- one generated review report;
- timeline traceability for the non-trading review event.

## Non-Goals

- No UI or frontend application is built.
- No React, Vue, Next.js, Svelte, or equivalent project is created.
- No API endpoint or server is created.
- No external, broker, Binance, or market-data API is connected.
- No live prices are inferred.
- No trades are executed.
- No trading automation is added.
- No historical checkpoint is re-ingested.

## Source View Model

Primary consumer source:

```text
cockpit/ldd/view_model.json
```

The static examples under `mock_consumers/ldd/` illustrate how to read that
file. They are not a second source of truth and must not replace the generated
view model.

## Consumer Types

- generated report consumer;
- future read-only UI consumer;
- future API consumer;
- mobile summary consumer;
- AI Board / role-based review consumer;
- future customer-facing cockpit consumer.

## Mock Package Structure

```text
mock_consumers/ldd/
  README.md
  view_model_snapshot.json
  ui_boundary_sample.json
  report_consumer_sample.json
  api_consumer_sample.json
  mobile_consumer_sample.json
  ai_board_consumer_sample.json
  privacy_masking_notes.md
```

## UI Boundary Principles

- The UI boundary accepts a validated view model and does not reconstruct
  current state from raw records.
- Rendering remains read-only.
- UI zones reference stable view-model sections instead of repository-specific
  implementation details.
- Warnings and data-quality flags remain visible.
- Quote type and source-of-truth context travel with price-related state.
- Risk rules are displayed as monitored conditions, not buttons or executable
  orders.
- Closed and prohibited positions remain visually distinct from active
  positions.

## Consumer Safety Rules

- Read `cockpit/ldd/view_model.json` first.
- Use raw records only for audit or debug.
- Do not infer live prices.
- Do not execute trades.
- Do not convert active rules into automated orders.
- Preserve `warnings`, `data_quality`, `portfolio_mode`, and source references.
- Distinguish opportunity cost from rule compliance.
- Distinguish risk watch from an execution-confirmed event.
- Distinguish active positions from closed/no-reentry instruments.
- Treat user-provided broker and Binance screenshots as execution source of
  truth.

## Example Consumer Interpretations

- Reports summarize current state and cite source paths.
- A future UI renders checkpoint, portfolio mode, risks, positions, rules, and
  timeline as read-only zones.
- A future API returns a versioned snapshot with warnings and data quality but
  exposes no mutation or execution endpoint.
- Mobile consumers prioritize portfolio mode, high-priority risks, key
  positions, and recent timeline highlights.
- AI Board roles read only the sections relevant to their review role and do
  not bypass Command Intelligence or human execution control.

## Field Rendering Guidance

| View-model field | Consumer interpretation |
|---|---|
| `checkpoint` | Show the latest confirmed record time and source links. |
| `portfolio_mode` | Show the current operating posture. |
| `account_overview` | Summarize account sections without implying live values. |
| `positions` | Render active positions only. |
| `closed_positions` | Render as historical/closed with no-reentry state. |
| `risk_summary` | Prioritize high-risk watches and preserve wording boundaries. |
| `active_rules` | Render status, trigger condition, current action, and source. |
| `strategy_states` | Render active, monitoring, waiting, historical, and closed states. |
| `timeline` | Render chronological traceability, not a live event stream. |
| `warnings` | Keep visible whenever non-empty. |
| `data_quality` | Show source, freshness, and safety limitations. |

## Risk State Rendering Guidance

- `near_trigger`: attention state, not proof of execution.
- `triggered`: rule condition observed; execution still requires evidence and
  applicable approval.
- `monitoring`: active watch without automatic action.
- `compliant_non_execution`: a rule remained active but non-execution was
  justified by the recorded outcome.
- `closed` or `closed_position`: historical state, not an active risk valve.
- `prohibited_reentry`: do not present as a buy candidate.

## Position State Rendering Guidance

- Active positions belong in `positions`.
- Closed positions belong in `closed_positions`.
- Zero-share positions must never appear as active longs.
- Opportunity cost after closure is separate from execution correctness.
- Tiny residual positions should be labeled as residuals rather than normal
  target allocations.

## Rule State Rendering Guidance

- Execution rules describe conditions and evidence requirements.
- Watch rules describe monitoring state.
- Prohibition rules prevent re-entry or chasing.
- Risk-line rules show levels and required confirmation context.
- Concentration rules describe exposure management.
- Quote type determines whether a price can be used for monitoring or
  execution confirmation.

## Timeline Rendering Guidance

- Sort by event time.
- Keep source-file links available.
- Preserve supersession and delta relationships.
- Label generated reviews as non-trading runtime events.
- Do not present the timeline as a live market feed.
- Display warning count and unknown timestamps if present.

## Privacy And Masking Notes

The package is internal. Future customer-facing use requires:

- account identifier masking;
- value-disclosure policy;
- field-level permissions;
- role-based views;
- explicit handling of screenshots and source evidence;
- prevention of credentials, tokens, API keys, and login data from entering
  consumer payloads.

See `mock_consumers/ldd/privacy_masking_notes.md`.

## Current LDD Defense-Mode Sample

- Latest checkpoint: `2026-06-09T08:28:00+08:00`
- Portfolio mode: `core_position_defense_mode`
- GLD: active risk; compliant non-execution after recovery above 395; full
  repair requires 400-405.
- NVDA: hold with 204 / 200 protection.
- GOOG: 355 defense remains active.
- GGLL: main leveraged ETF risk valve.
- SOXL / UGL / INTC / SOXS / TSLQ / GDXU: closed / no reentry.
- Binance: USDT-dominant defense.
- BTC buyback: inactive below 75,500-76,000.
- ZEC grid: closed / do not reopen.
- HK Zhipu / 02513: high-profit protection is separate from U.S. risk scoring.
- Quote Type Tagging remains required.
- Consumer readiness: `ready_with_limits`.

## Known Limitations

- Samples are static and single-project.
- No privacy-masking engine exists.
- No permission model exists.
- No API contract tests exist.
- No UI interaction model exists.
- No mobile-specific data compression exists.
- No live update or subscription mechanism exists.

## Recommended Next Phase

```text
Vol.5 Phase 5.7 - Consumer Contract Test Matrix and Privacy Boundary
```

That phase should test required fields and masking expectations for each
consumer type while remaining read-only and non-UI.
