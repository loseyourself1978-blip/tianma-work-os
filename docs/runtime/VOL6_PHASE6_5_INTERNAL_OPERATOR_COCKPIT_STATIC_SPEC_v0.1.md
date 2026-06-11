# Vol.6 Phase 6.5 Internal Operator Cockpit Static Spec v0.1

## 1. Purpose

Phase 6.5 defines the internal operator cockpit static specification for LDD. It describes the information architecture, section order, card field map, warning and data-quality policy, source traceability policy, and blocked action policy that a future internal cockpit may follow.

This is a static specification only. It does not implement a cockpit UI.

## 2. Relationship to Phase 6.1 UI Boundary

Phase 6.1 separated cockpit data readiness from UI readiness. Phase 6.5 applies that boundary to the internal operator surface only. The static spec describes what an internal operator may read from `cockpit/ldd/view_model.json`, while preserving the rule that raw records are audit/debug inputs rather than the primary UI source.

## 3. Relationship to Phase 6.2 Permission and Privacy Masking

Phase 6.2 defined deny-by-default roles, field classes, masking actions, and customer-facing blocked criteria. Phase 6.5 uses those contracts to define which cards require masking, which fields are internal read-only, which fields are execution-sensitive, and which fields remain audit-only.

The internal operator surface is not customer-facing. Customer-facing readiness remains `false`.

## 4. Relationship to Phase 6.3 Read-only API Contract

Phase 6.3 defined a read-only API contract without creating a live API server. Phase 6.5 references those static endpoint contracts as future source boundaries only. It does not create HTTP routes, controllers, handlers, listeners, or endpoint code.

## 5. Relationship to Phase 6.4 Static Prototype Boundary Review

Phase 6.4 defined allowed static surfaces, cards, interactions, blocked controls, and data-quality display requirements. Phase 6.5 narrows that boundary to the `internal_operator_cockpit_static` surface and defines a concrete read-only card order for that surface.

## 6. Internal Operator Cockpit Scope

The scope is an internal read-only cockpit specification for operators reviewing the LDD pilot. It may describe:

- checkpoint and system status
- account snapshot
- cash and stablecoin defense ratios
- active positions
- closed positions
- confirmed execution ledger
- active rules
- strategy states
- warnings and data quality
- source traceability
- non-promoted evidence
- customer-facing blocked status

It must not describe executable controls.

## 7. Static Information Architecture

The internal operator cockpit starts with status and checkpoint context, then moves from account overview to position/rule details, then ends with quality, source, and blocked-state information. This sequence keeps the operator anchored in the latest checkpoint before exposing execution-sensitive rules.

## 8. Section Order

The required static section order is:

1. `system_status_header`
2. `active_checkpoint_banner`
3. `account_snapshot_section`
4. `cash_defense_section`
5. `active_positions_section`
6. `execution_ledger_section`
7. `active_rules_section`
8. `strategy_states_section`
9. `warning_data_quality_section`
10. `source_traceability_section`
11. `non_promoted_evidence_section`
12. `customer_facing_blocked_status_section`

Each section is required, static-spec-only, non-customer-facing, and read-only.

## 9. Card Field Map

The card field map defines fourteen read-only cards:

- `system_status_header_card`
- `active_checkpoint_card`
- `account_snapshot_card`
- `us_cash_defense_card`
- `binance_usdt_defense_card`
- `active_us_positions_card`
- `closed_positions_card`
- `confirmed_execution_ledger_card`
- `active_rules_card`
- `strategy_states_card`
- `warning_data_quality_card`
- `source_traceability_card`
- `non_promoted_evidence_card`
- `customer_facing_blocked_status_card`

Cards use view-model and cockpit summary fields. They do not reconstruct state from raw records unless the card is explicitly audit/source traceability oriented.

## 10. Warning and Data-quality Display

Warnings and data-quality indicators are mandatory. The internal operator cockpit must display:

- customer-facing blocked status
- absence of live API, broker, Binance, and trading automation connections
- visible checkpoint timestamp
- visible source priority
- visible quote type
- labeled non-promoted evidence
- read-only execution ledger status
- sensitive-field masking
- never-expose field rejection

No warning or data-quality item may be hidden.

## 11. Source Traceability Display

Source traceability must identify source priority:

1. user broker screenshots
2. user Binance screenshots
3. actual order screenshots
4. external market data for validation only

The static cockpit must also reference the active checkpoint record, cockpit view model, read-only API contract, permission/privacy/masking contract, static cockpit prototype boundary, and non-promoted governance evidence.

## 12. Active Checkpoint Display

The active checkpoint is `2026-06-11T08:10:00+08:00`.

This timestamp must be visible in the header and checkpoint card. Phase 6.2a evidence remains non-promoted and may not silently overwrite the active checkpoint.

## 13. Execution Ledger Display

The execution ledger must show confirmed order reconciliation as read-only history:

- sell GGLL
- sell NVDA
- sell GLD
- canceled sell GLD

The execution ledger must not include buy, sell, cancel, modify, retry, replay, or execution controls.

## 14. Rule and Strategy State Display

The active-rules card must include the 10 active rules from the `2026-06-11T08:10:00+08:00` checkpoint. The strategy-states card must preserve the 16 strategy states and their active, monitoring, closed, prohibited, or no-reentry meanings.

Rule display is non-interactive. Risk rules are not automated order instructions.

## 15. Cash Defense Ratio Display

The cash defense cards must display:

- implied U.S. cash
- U.S. cash ratio
- Binance total assets
- Binance USDT balance
- Binance USDT defense ratio

These fields are internal account-structure indicators and must remain read-only.

## 16. Blocked Actions and Non-interactive Controls

Internal operators must not receive controls for:

- placing, canceling, modifying, or executing orders
- starting/stopping bots
- reopening grids
- connecting broker, Binance, or external market data APIs
- refreshing live prices
- mutating runtime records
- promoting checkpoints through UI
- suppressing warnings
- hiding data quality
- revealing sensitive or never-expose fields
- enabling customer-facing view
- exporting sensitive customer data

## 17. Permission and Masking Requirements

Internal operators may read internal cockpit state subject to masking policy. Sensitive account values remain internal-only and non-customer-facing. Execution-sensitive fields must be non-interactive. Audit-only data remains restricted to audit/debug contexts. Never-expose fields must be rejected before render.

## 18. No-implementation Boundary

This phase creates no UI implementation. It creates no frontend app, customer-facing UI, HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, frontend routing, UI components, API server, live endpoint, route handlers, controllers, server daemons, HTTP listeners, external connectors, broker connectors, Binance connectors, credential stores, runtime mutation UI, execution triggers, or trading automation.

## 19. Explicit Non-goals

- No frontend app.
- No customer-facing UI.
- No HTML/CSS/JS UI files.
- No React/Vue/Next/Svelte app or components.
- No API server.
- No live endpoint.
- No route handlers, controllers, server daemons, or HTTP listeners.
- No external API connection.
- No broker/Binance API connection.
- No live market data.
- No trading automation.
- No authentication implementation.
- No credential, token, password, account-number, or live identifier handling.
- No order placement, cancellation, execution, bot control, or runtime mutation capability.
- No mutation of prior runtime records.
- No GitHub Issues.
- No GitHub Projects board.

## 20. Validation Strategy

The internal operator static spec validator checks:

- required files and schemas exist
- JSON syntax is valid
- actual UI and customer-facing readiness remain false
- all required sections exist in unique sequential order
- all sections and cards are static-spec-only
- mutation, execution, and customer-facing access are disabled
- never-expose field classes are absent from cards
- the execution ledger is read-only
- the active-rules card includes all 10 active rules
- non-promoted evidence is labeled non-promoted and non-executing
- all warning, source-traceability, and blocked-action entries exist
- source priority ranks user sources above external validation-only data
- active checkpoint remains `2026-06-11T08:10:00+08:00`
- no Phase 6.5 artifact appears to implement frontend, API, live endpoint, connector, credential, runtime mutation, or execution capability

## 21. Phase 6.6 Entry Criteria

Phase 6.6 may begin only if:

- active checkpoint remains `2026-06-11T08:10:00+08:00`
- timeline warnings remain `0`
- customer-facing readiness remains `false`
- internal operator static spec validation passes
- static prototype boundary validation still passes
- read-only API, permission/privacy, UI boundary, fixture, and view-model quality validators still pass

Recommended next phase:

`Vol.6 Phase 6.6 - AI Board Cockpit Static Spec`
