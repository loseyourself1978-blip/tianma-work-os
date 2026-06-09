# Cockpit Consumer Readiness Review v0.1

## Purpose

Vol.5 Phase 5.5 reviews whether future consumers can safely and consistently
use `cockpit/ldd/view_model.json`.

Consumers include future UI, generated reports, API layer, mobile display, AI
Board / role-based review, and future customer-facing cockpit modules. This
phase defines boundaries and readiness status only. It does not build a UI,
create an API, connect external services, or add trading automation.

## Scope

Reviewed source files:

- `cockpit/ldd/view_model.json`
- `cockpit/ldd/manifest.json`
- `docs/runtime/COCKPIT_VIEW_MODEL_CONTRACT_v0.1.md`
- `docs/runtime/COCKPIT_VIEW_MODEL_GENERATOR_v0.1.md`
- `docs/runtime/VIEW_MODEL_QUALITY_GATES_v0.1.md`
- `schemas/cockpit_view_model.schema.json`
- `scripts/validate_cockpit_view_model_quality.py`
- `reports/ldd/cockpit_view_model_summary.md`
- `reports/ldd/view_model_quality_gates.md`

## Consumer Map

- UI consumer
- Report consumer
- API consumer
- Mobile consumer
- AI Board / role-based review consumer
- Future customer-facing cockpit consumer

## Contract Boundaries

- Consumers should read `cockpit/ldd/view_model.json` first.
- Consumers should use raw records only for audit or debug workflows.
- Consumers should not infer live prices.
- Consumers should not execute trades.
- Consumers should not treat watch, risk, prohibition, no-reentry, or
  source-quality rules as automation.
- Consumers must respect `warnings`, `data_quality`, `source_files`, and
  `portfolio_mode`.
- User-provided broker/Binance screenshots remain the execution source of truth.

## Required Safety Fields

The current view model exposes the required fields for safe read-only rendering:

- latest checkpoint
- portfolio mode
- account overview
- account sections
- positions
- closed positions
- risk summary
- active rules
- strategy states
- timeline
- pending commands
- memory checkpoint
- warnings
- data quality

## Consumer-Specific Readiness

| Consumer | Status | Notes |
|---|---|---|
| Generated reports | `ready` | Reports can safely consume the view model as a local read-only source. |
| Future UI | `ready_with_limits` | Read-only UI can be designed from the model, but no masking or interaction policy exists yet. |
| API layer | `ready_with_limits` | Static read-only serving is plausible, but no endpoint, auth, or permission model exists. |
| Mobile display | `ready_with_limits` | Sections can compress into mobile cards, but no mobile-specific summary/masking exists. |
| AI Board review layer | `ready_with_limits` | Roles can review current state and risk context, but no AI Board automation exists. |
| Customer-facing cockpit | `ready_with_limits` | Shape is usable, but privacy masking and role-based display are required first. |

## Privacy And Safety Review

- No credentials or API keys are present in the view model.
- No external API connection is present.
- No trading automation instruction is present.
- No live order execution path exists.
- No customer-facing privacy layer exists yet.
- No UI masking policy exists yet.

The current payload is safe for local read-only development consumers. It is not
yet a customer-facing product payload.

## Current LDD Defense-Mode Interpretation

Consumers should render:

- Portfolio mode: `core_position_defense_mode`
- Latest checkpoint: `2026-06-09T08:28:00+08:00`
- SOXL / UGL / INTC: `closed_position`
- GGLL: main remaining leveraged ETF risk valve
- NVDA: main core-risk watch
- GLD: ordinary GLD concentration / risk-line protection; compliant non-execution after recovery above 395; full repair remains 400-405
- Binance: USDT-dominant defense
- BTC buyback trigger: inactive below 75,500-76,000
- ZEC grid: closed / no reopen
- Timeline warnings: `0`
- Quality gate blocking failures: `0`

## Known Limitations

- No live market connection exists.
- No UI exists yet.
- No API endpoint exists yet.
- No user or role permission system exists yet.
- No customer-facing privacy masking layer exists yet.
- Current view model is single-project / LDD pilot focused.
- Multi-project cockpit consumption remains future work.

## Non-Goals

- No UI is built.
- No frontend app files are created.
- No external APIs are connected.
- No trading automation is added.
- No GitHub Projects board is created.
- No GitHub Issues are created.
- The 2026-06-08 checkpoint is not re-ingested.

## Phase 5.6b Implementation

The recommended static boundary package is implemented in:

- `docs/runtime/MOCK_CONSUMER_PACKAGE_AND_UI_BOUNDARY_SAMPLE_v0.1.md`
- `mock_consumers/ldd/`
- `records/ldd/2026-06-09/mock_consumer_package_review_0828_sgt.json`
- `reports/ldd/mock_consumer_package_review.md`

Consumer readiness remains `ready_with_limits`; the package adds examples, not
a UI, API, permission system, or customer-facing privacy layer.

Phase 5.7 adds the static test matrix and privacy categories in:

- `docs/runtime/CONSUMER_CONTRACT_TEST_MATRIX_AND_PRIVACY_BOUNDARY_v0.1.md`
- `mock_consumers/ldd/consumer_contract_test_matrix.json`
- `mock_consumers/ldd/privacy_boundary_sample.json`

## Recommended Next Phase

```text
Vol.5 Phase 5.8 - Read-Only Consumer Fixture Validator
```
