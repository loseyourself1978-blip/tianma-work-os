# Vol.6 Phase 6.6 AI Board Cockpit Static Spec v0.1

## 1. Purpose

Phase 6.6 defines the AI Board cockpit static specification for LLM Daredevil Desk. It describes the read-only information architecture for multi-role AI review panels, evidence display, disagreement visualization, arbitration, decision traceability, and blocked actions.

This is a static specification only. It does not implement a cockpit UI.

## 2. Relationship to Phase 6.1 UI Boundary

Phase 6.1 defined the read-only UI boundary and blocked customer-facing surfaces. Phase 6.6 applies that boundary to the `ai_board_review_static` surface and keeps AI Board review as a contract-only cockpit consumer.

## 3. Relationship to Phase 6.2 Permission and Privacy Masking

Phase 6.2 established deny-by-default permissions, field classes, masking actions, and customer-facing blocked criteria. Phase 6.6 requires AI Board panels to respect those field classes and to reject never-expose data before render.

## 4. Relationship to Phase 6.3 Read-only API Contract

Phase 6.3 defined static read-only API contracts without creating an API server. Phase 6.6 may reference those contracts as source boundaries, but it creates no endpoint, route, handler, listener, controller, or service process.

## 5. Relationship to Phase 6.4 Static Cockpit Prototype Boundary Review

Phase 6.4 established static surfaces, cards, interactions, blocked controls, and data-quality display policies. Phase 6.6 specializes the `ai_board_review_static` surface for role-based review and arbitration.

## 6. Relationship to Phase 6.5 Internal Operator Cockpit Static Spec

Phase 6.5 defined the internal operator cockpit static spec. Phase 6.6 complements it with a multi-role board review structure. The AI Board surface reads the same checkpoint and source contracts, but organizes the information by role, evidence, disagreement, and final arbitration.

## 7. Relationship to Phase 6.5a Residual Core Checkpoint Update

Phase 6.5a promoted the active checkpoint to `2026-06-12T09:18:00+08:00`, with `cash_defense_core_position_survival_mode` and `residual_core_position_mode`. Phase 6.6 uses that checkpoint as the source state and does not mutate it.

## 8. AI Board Cockpit Scope

The AI Board cockpit static spec covers:

- Market Analyst review
- Risk Officer review
- Data Verifier review
- Strategist / Meta Strategist review
- Review Officer review
- Final Commander arbitration
- disagreement summary
- final decision trace
- blocked action policy

The scope is read-only and non-customer-facing.

## 9. AI Board Role Taxonomy

The static role taxonomy includes:

- `market_analyst`
- `risk_officer`
- `data_verifier`
- `strategist_meta_strategist`
- `review_officer`
- `final_commander`

Only `final_commander` may arbitrate disagreements. No role may trigger execution or mutate runtime.

## 10. Static Role Panel Map

Each AI Board role has one static panel. The static spec also defines:

- `board_disagreement_summary_panel`
- `final_decision_trace_panel`

Panels are static-spec-only. They may display evidence, role outputs, disagreements, and final decision traces, but may not expose order controls or runtime mutation controls.

## 11. Evidence and Source-of-Truth Policy

Evidence priority is:

1. user Longbridge broker screenshots
2. user order-detail screenshots
3. user Binance spot screenshots
4. LDD review sync block
5. active checkpoint record
6. cockpit view model
7. read-only API contract
8. permission/privacy/masking contract
9. internal operator cockpit static spec
10. external market data for validation only

Broker screenshots, order-detail screenshots, and Binance screenshots are Source of Truth. External market data is validation-only.

## 12. Disagreement Display Policy

The AI Board cockpit must display role disagreements instead of hiding them. Required disagreement types include market rebound versus no re-entry, rule compliance versus opportunity cost, cash defense versus redeployment, core hold versus reduce, missing data versus resolved data, external validation versus broker Source of Truth, and short-term price quality versus account-structure improvement.

Disagreements are review artifacts, not executable instructions.

## 13. Arbitration and Final Commander Policy

The Final Commander arbitrates disagreements after reviewing role outputs and evidence. Arbitration must preserve:

- Source of Truth over external validation
- rule compliance separated from opportunity cost
- account-structure improvement separated from short-term regret
- no re-entry unless a new approved rule exists
- execution requiring user manual action outside the system
- customer-facing output blocked
- runtime mutation UI blocked

## 14. Decision Traceability Policy

Decision traceability must show:

- source priority
- account state
- execution ledger
- active rules
- role outputs
- disagreements
- arbitration
- final commander judgement
- blocked actions
- customer-facing blocked state

Trace items are mandatory and may not be hidden.

## 15. Risk and Data-quality Display

Risk and data-quality display must keep warnings, quote type, Source of Truth, checkpoint timestamp, non-promoted evidence labels, and customer-facing blocked status visible. Risk rules remain non-interactive.

## 16. Rule Compliance vs Opportunity Cost Separation

The AI Board must show that one-day rebounds in closed instruments are opportunity-cost observations, not automatic rule failures. Rule compliance, price quality, execution discipline, account-structure improvement, and opportunity cost are separate review dimensions.

## 17. Residual Core Position Review Requirements

The active checkpoint is in `residual_core_position_mode`. Review panels must treat GOOG 9, NVDA 10, and tiny TSLA residual as the remaining U.S. active positions, while GLD, GGLL, SOXL, UGL, INTC, SOXS, TSLQ, and GDXU remain closed or prohibited. U.S. cash and Binance USDT defense ratios are top-level defense indicators.

## 18. Blocked Actions and Non-interactive Controls

The AI Board cockpit must block order placement, order cancellation, order modification, trade execution, bot control, broker/Binance/external market API connection, live price refresh, runtime mutation, checkpoint promotion from UI, warning suppression, data-quality hiding, sensitive reveal, customer-facing enablement, disagreement hiding, and recommendation-to-execution conversion.

## 19. Permission and Masking Requirements

AI Board panels are internal read-only surfaces. Sensitive account values remain internal-only. Execution-sensitive fields must be non-interactive. Audit-only data must be traceable. Never-expose fields must be rejected before render.

## 20. No-implementation Boundary

This phase creates no UI implementation. It creates no frontend app, customer-facing UI, HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, frontend routing, UI components, API server, live endpoint, route handlers, controllers, server daemons, HTTP listeners, external connectors, broker connectors, Binance connectors, credential stores, runtime mutation UI, execution triggers, or trading automation.

## 21. Explicit Non-goals

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

## 22. Validation Strategy

The AI Board static spec validator checks:

- required files and schemas exist
- JSON syntax is valid
- actual UI and customer-facing readiness remain false
- source checkpoint is `2026-06-12T09:18:00+08:00`
- operating mode is `cash_defense_core_position_survival_mode`
- portfolio mode is `residual_core_position_mode`
- all six roles exist and are static-spec-only
- no role can trigger execution or mutate runtime
- Final Commander is the only arbitrating role
- all panels are static-spec-only, read-only, non-customer-facing, and non-mutating
- never-expose fields are absent from panels
- evidence policy ranks user Source-of-Truth evidence above external validation-only data
- all disagreements, arbitration rules, decision traces, and blocked actions exist
- blocked actions have `blocked: true` and `allowed_roles: []`
- no Phase 6.6 artifact appears to implement frontend, API, live endpoint, connector, credential, runtime mutation, or execution capability

## 23. Phase 6.7 Entry Criteria

Phase 6.7 may begin only if:

- active checkpoint remains `2026-06-12T09:18:00+08:00`
- operating mode remains `cash_defense_core_position_survival_mode`
- portfolio mode remains `residual_core_position_mode`
- AI Board static spec validation passes
- customer-facing readiness remains `false`
- no UI/API/live endpoint/automation/credential path exists

Recommended next phase:

`Vol.6 Phase 6.7 - Cockpit Static Spec Integration Review`
