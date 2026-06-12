# Vol.6 Phase 6.7 Cockpit Static Spec Integration Review v0.1

## 1. Purpose

Phase 6.7 integrates the Vol.6 cockpit static specifications and validates consistency across the static cockpit prototype boundary, internal operator cockpit static spec, AI Board cockpit static spec, permission/privacy/masking model, read-only API contract, and residual core checkpoint update.

This is an integration review only. It does not implement a UI.

## 2. Integration Scope

The review covers static contracts and governance artifacts created through Phase 6.6. It checks that all consumer-facing, execution, mutation, credential, connector, and live-data capabilities remain blocked while preserving the active checkpoint and residual-core mode.

## 3. Relationship to Phase 6.1 UI Boundary

Phase 6.1 defined the read-only UI boundary and blocked customer-facing surfaces. Phase 6.7 verifies that later static specs still obey those boundaries.

## 4. Relationship to Phase 6.2 Permission and Privacy Masking

Phase 6.2 defined deny-by-default permissions, field classes, masking actions, and customer-facing blocked criteria. Phase 6.7 checks that surfaces, roles, cards, panels, and trace categories still respect those constraints.

## 5. Relationship to Phase 6.3 Read-only API Contract

Phase 6.3 defined static read-only API contracts and forbidden capabilities without creating an API server. Phase 6.7 crosschecks the static cockpit specs against those read-only constraints.

## 6. Relationship to Phase 6.4 Static Cockpit Prototype Boundary

Phase 6.4 defined static surfaces, cards, interactions, blocked controls, and display policies. Phase 6.7 integrates those surfaces with internal operator and AI Board role mappings.

## 7. Relationship to Phase 6.5 Internal Operator Cockpit Static Spec

Phase 6.5 defined the internal operator cockpit information architecture and read-only card field map. Phase 6.7 checks that the internal operator surface remains read-only and source-traceable.

## 8. Relationship to Phase 6.6 AI Board Cockpit Static Spec

Phase 6.6 defined AI Board roles, role panels, evidence policies, disagreement display, arbitration, decision tracing, and blocked actions. Phase 6.7 checks that AI Board outputs stay static, traceable, and non-executing.

## 9. Relationship to Phase 6.5a Residual Core Checkpoint Update

Phase 6.5a promoted the active checkpoint to `2026-06-12T09:18:00+08:00`, with `cash_defense_core_position_survival_mode` and `residual_core_position_mode`. Phase 6.7 validates that all static specs align to those values where applicable.

## 10. Integration Matrix

The integration matrix links seven artifacts:

1. UI Boundary Architecture
2. Permission and Privacy Masking Model
3. Read-only API Contract
4. Static Cockpit Prototype Boundary
5. Internal Operator Cockpit Static Spec
6. AI Board Cockpit Static Spec
7. Residual Core Checkpoint Update

Every integrated spec must remain read-only, non-customer-facing, non-mutating, non-executing, and static-contract-only or governance-record-only.

## 11. Surface and Role Consistency

The surface-role matrix checks internal operator, AI Board, audit/debug, public demo blocked, and customer-facing blocked surfaces against system, operator, AI Board, audit, demo, and customer-facing roles.

Customer-facing viewer access remains blocked for every cockpit surface.

## 12. Card and Field Traceability

The card traceability matrix links account, cash, position, execution, rule, strategy, warning, source, checkpoint, non-promoted evidence, customer-facing blocked, AI Board role output, disagreement, arbitration, and decision trace categories to their source contracts.

No trace category may use `never_expose`.

## 13. Evidence and Source-of-Truth Consistency

The review preserves user broker screenshots, user order-detail screenshots, and user Binance screenshots as Source of Truth. External market data remains validation-only.

## 14. Permission and Masking Consistency

Permission and masking remain deny-by-default. Sensitive account values are internal-only, execution-sensitive fields are non-interactive, audit-only fields remain restricted, and never-expose fields must be rejected before render.

## 15. Blocked Action Crosscheck

Blocked actions are unified across read-only API forbidden capabilities, static cockpit blocked controls, internal operator blocked actions, and AI Board blocked actions. Place/cancel/modify/execute order actions, bot control, connector actions, live price refresh, runtime mutation, checkpoint promotion from UI, warning hiding, data-quality hiding, sensitive reveal, customer-facing enablement, disagreement hiding, and recommendation-to-execution conversion remain blocked.

## 16. Read-only API Contract Alignment

The read-only API contract remains static and non-implemented. No endpoint, server, route, listener, connector, credential handler, runtime mutation capability, or execution trigger is created.

## 17. Customer-facing Readiness Gate

Customer-facing readiness remains `false`. Customer-facing UI remains blocked until governance approval, permission enforcement, masking runtime, privacy policy, live connector approvals, and explicit product decisions exist.

## 18. Residual Core Mode Alignment

The active checkpoint remains in `residual_core_position_mode`. The operating mode remains `cash_defense_core_position_survival_mode`. The static specs must continue to show residual GOOG/NVDA/TSLA positions, closed/prohibited leveraged positions, U.S. cash defense, Binance USDT defense, no-reentry discipline, and rule-compliance versus opportunity-cost separation.

## 19. No-implementation Boundary

This phase creates no UI implementation and no new cockpit surface. It creates no frontend app, customer-facing UI, HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, frontend routing, UI components, API server, live endpoint, route handlers, controllers, server daemons, HTTP listeners, external connectors, broker connectors, Binance connectors, credential stores, runtime mutation UI, execution triggers, or trading automation.

## 20. Explicit Non-goals

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
- No order placement, cancellation, execution, bot control, runtime mutation UI, or execution trigger.
- No mutation of prior runtime records.
- No GitHub Issues.
- No GitHub Projects board.

## 21. Validation Strategy

The integration validator checks:

- required files and schema exist
- JSON syntax is valid
- all seven integrated specs exist and remain read-only
- all fifteen consistency checks exist and are blocking
- active checkpoint, operating mode, and portfolio mode match the current runtime
- customer-facing readiness remains false
- all required surfaces and roles are represented
- customer-facing viewer has no cockpit access
- internal operator and AI Board access is static/read-only
- all sixteen card trace categories exist
- no trace category uses `never_expose`
- all unified blocked actions are blocked with no allowed roles
- readiness gate values remain conservative
- no Phase 6.7 artifact appears to implement frontend, API, live endpoint, connector, credential, runtime mutation, or execution capability

## 22. Phase 6.8 Entry Criteria

Phase 6.8 may begin only if:

- active checkpoint remains `2026-06-12T09:18:00+08:00`
- operating mode remains `cash_defense_core_position_survival_mode`
- portfolio mode remains `residual_core_position_mode`
- all static spec integration checks pass
- customer-facing readiness remains `false`
- no UI/API/live endpoint/automation/credential path exists

Recommended next phase:

`Vol.6 Phase 6.8 - Static Consumer Fixture Integration and Handoff`
