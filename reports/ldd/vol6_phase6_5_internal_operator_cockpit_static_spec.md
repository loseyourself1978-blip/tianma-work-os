# Vol.6 Phase 6.5 Internal Operator Cockpit Static Spec

Generated for the LDD cockpit boundary workstream.

## Baseline

- Phase: Vol.6 Phase 6.5
- Active checkpoint: `2026-06-11T08:10:00+08:00`
- Timeline events before review: `91`
- Timeline warnings: `0`
- Active rules: `10`
- Strategy states: `16`
- Consumer readiness: `ready_with_limits`
- Customer-facing readiness: `false`

## Artifacts Created

- `docs/runtime/VOL6_PHASE6_5_INTERNAL_OPERATOR_COCKPIT_STATIC_SPEC_v0.1.md`
- `schemas/internal_operator_cockpit_static_spec.schema.json`
- `schemas/internal_operator_cockpit_static_spec_review.schema.json`
- `mock_consumers/ldd/internal_operator_cockpit_static_spec.json`
- `mock_consumers/ldd/internal_operator_cockpit_section_order.json`
- `mock_consumers/ldd/internal_operator_cockpit_card_field_map.json`
- `mock_consumers/ldd/internal_operator_cockpit_warning_policy.json`
- `mock_consumers/ldd/internal_operator_cockpit_source_traceability_policy.json`
- `mock_consumers/ldd/internal_operator_cockpit_blocked_action_policy.json`
- `scripts/validate_internal_operator_cockpit_static_spec.py`
- `scripts/validate_internal_operator_cockpit_static_spec.sh`
- `records/ldd/2026-06-11/vol6_phase6_5_internal_operator_cockpit_static_spec_review_0810_sgt.json`

## No-implementation Boundary

Phase 6.5 creates an internal operator static specification only. It creates no frontend app, customer-facing UI, HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, API server, live endpoint, route handler, controller, server daemon, HTTP listener, external connector, broker connector, Binance connector, credential store, runtime mutation UI, execution trigger, or trading automation.

## Internal Operator Cockpit Purpose

The static spec defines how a future internal operator cockpit should arrange and label read-only LDD state from `cockpit/ldd/view_model.json`. It keeps raw records as audit/debug inputs and keeps all execution-sensitive data non-interactive.

## Section Order

The required internal operator section order is:

1. system status header
2. active checkpoint banner
3. account snapshot
4. cash defense
5. active positions
6. execution ledger
7. active rules
8. strategy states
9. warning and data quality
10. source traceability
11. non-promoted evidence
12. customer-facing blocked status

Every section is required, static-spec-only, read-only, and non-customer-facing.

## Card Field Map

The card field map defines fourteen static cards. Required coverage includes:

- account snapshot fields: total assets, U.S. section, holding value, implied U.S. cash, cash ratio, day P/L, holding P/L
- U.S. cash defense and Binance USDT defense fields
- active positions: GOOG, NVDA, GGLL, TSLA, GLD
- closed/no-reentry positions
- confirmed execution ledger: sell GGLL, sell NVDA, sell GLD, canceled sell GLD
- all 10 active checkpoint rules
- 16 strategy states
- warning/data-quality fields
- source traceability fields
- Phase 6.2a non-promoted evidence label
- customer-facing blocked status

## Warning/Data-quality Policy

The warning policy requires display of customer-facing blocked status, no live API/broker/Binance/trading automation status, checkpoint timestamp, source priority, quote type, non-promoted evidence labels, read-only execution ledger status, sensitive masking, and never-expose rejection.

Every warning item is required and may not be hidden.

## Source Traceability Policy

The source policy ranks user broker screenshots, user Binance screenshots, and actual order screenshots above external market validation data. External market data is labeled `validation_only`. Phase 6.2a evidence is labeled `non_promoted`.

## Blocked Action Policy

The blocked action policy forbids 20 internal operator actions, including order placement, cancellation, modification, trade execution, bot control, broker/Binance/external API connection, live market data, runtime mutation, checkpoint promotion through UI, warning suppression, data-quality hiding, sensitive reveal, never-expose reveal, customer-facing enablement, and sensitive customer export.

Every blocked action has `blocked: true` and `allowed_roles: []`.

## Active Checkpoint Display

The active checkpoint remains `2026-06-11T08:10:00+08:00`. This timestamp must be visible in the system header and checkpoint card.

## Execution Ledger Display

The execution ledger is read-only. It may show confirmed/canceled order reconciliation, but it must not include trade, cancel, modify, retry, replay, or execution controls.

## Active Rule Display

The active-rules card includes all 10 active rules from checkpoint `2026-06-11T08:10:00+08:00`. The rules remain non-interactive risk guidance, not automated order instructions.

## Customer-facing Blocked State

Customer-facing readiness remains `false`. The internal operator cockpit static spec must continue showing the blocked customer-facing state and must not expose customer-facing account data.

## Validation Result

Expected validator:

`bash scripts/validate_internal_operator_cockpit_static_spec.sh`

Expected result:

- internal operator cockpit static spec validation passed
- blocking failures: `0`
- warnings: `0`
- active checkpoint: `2026-06-11T08:10:00+08:00`
- actual UI created: `false`
- frontend app created: `false`
- HTML/CSS/JS UI created: `false`
- API server created: `false`
- live endpoint created: `false`
- customer-facing ready: `false`
- trading automation enabled: `false`

## Remaining Gaps Before Phase 6.6

- AI Board cockpit static spec is not yet defined.
- No permission-enforced renderer exists.
- No customer-facing masking runtime exists.
- No API server or live endpoint exists.
- No UI exists.

Recommended next phase:

`Vol.6 Phase 6.6 - AI Board Cockpit Static Spec`
