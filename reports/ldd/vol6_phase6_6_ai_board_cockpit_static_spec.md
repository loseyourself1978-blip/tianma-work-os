# Vol.6 Phase 6.6 AI Board Cockpit Static Spec

Generated for the LDD cockpit boundary workstream.

## Baseline

- Phase: Vol.6 Phase 6.6
- Active checkpoint: `2026-06-12T09:18:00+08:00`
- Timeline events before review: `93`
- Timeline warnings: `0`
- Active rules: `11`
- Strategy states: `16`
- Operating mode: `cash_defense_core_position_survival_mode`
- Portfolio mode: `residual_core_position_mode`
- Consumer readiness: `ready_with_limits`
- Customer-facing readiness: `false`

## Artifacts Created

- `docs/runtime/VOL6_PHASE6_6_AI_BOARD_COCKPIT_STATIC_SPEC_v0.1.md`
- `schemas/ai_board_cockpit_static_spec.schema.json`
- `schemas/ai_board_cockpit_static_spec_review.schema.json`
- `mock_consumers/ldd/ai_board_cockpit_static_spec.json`
- `mock_consumers/ldd/ai_board_role_taxonomy.json`
- `mock_consumers/ldd/ai_board_role_panel_map.json`
- `mock_consumers/ldd/ai_board_evidence_policy.json`
- `mock_consumers/ldd/ai_board_disagreement_policy.json`
- `mock_consumers/ldd/ai_board_arbitration_policy.json`
- `mock_consumers/ldd/ai_board_decision_trace_policy.json`
- `mock_consumers/ldd/ai_board_blocked_action_policy.json`
- `scripts/validate_ai_board_cockpit_static_spec.py`
- `scripts/validate_ai_board_cockpit_static_spec.sh`
- `records/ldd/2026-06-12/vol6_phase6_6_ai_board_cockpit_static_spec_review_0918_sgt.json`

## No-implementation Boundary

Phase 6.6 creates an AI Board static specification only. It creates no frontend app, customer-facing UI, HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, API server, live endpoint, route handler, controller, server daemon, HTTP listener, external connector, broker connector, Binance connector, credential store, runtime mutation UI, execution trigger, or trading automation.

## AI Board Cockpit Purpose

The AI Board static cockpit organizes LDD state into role-based read-only review panels. It helps future consumers reason about evidence, disagreement, arbitration, and traceability without turning any rule or recommendation into execution.

## Role Taxonomy

The role taxonomy defines Market Analyst, Risk Officer, Data Verifier, Strategist / Meta Strategist, Review Officer, and Final Commander. Only Final Commander may arbitrate. No role may trigger execution or mutate runtime.

## Role Panel Map

The role panel map defines six role panels plus a board disagreement summary panel and a final decision trace panel. Panels are static-spec-only, non-customer-facing, read-only, and source-linked.

## Evidence Policy

User Longbridge broker screenshots, user order-detail screenshots, and user Binance spot screenshots are Source of Truth. The LDD review sync block is displayed as synthesized structured input. External market data is validation-only and cannot override user Source-of-Truth evidence.

## Disagreement Policy

Required disagreements include market rebound versus no re-entry, rule compliance versus opportunity cost, cash defense versus redeployment, core hold versus reduce, missing data versus resolved data, external validation versus broker Source of Truth, and short-term price quality versus account-structure improvement. Disagreements are visible and non-executing.

## Arbitration Policy

Final Commander arbitration preserves Source-of-Truth priority, separates rule compliance from opportunity cost, allows account-structure improvement to outweigh short-term regret in review, blocks re-entry without a new approved rule, and keeps execution as user manual action outside the system.

## Decision Trace Policy

Decision traces include source priority, account state, execution ledger, active rules, role outputs, disagreements, arbitration, Final Commander judgement, blocked actions, and customer-facing blocked state.

## Blocked Action Policy

The AI Board blocks 23 actions, including order placement, cancellation, modification, trade execution, bot control, connector creation, live price refresh, runtime mutation, checkpoint promotion from UI, warning hiding, sensitive reveal, disagreement hiding, and recommendation-to-execution conversion.

## Active Checkpoint Display

The active checkpoint remains `2026-06-12T09:18:00+08:00`.

## Residual Core Position Mode

The AI Board static spec reflects `residual_core_position_mode`. GOOG 9, NVDA 10, and tiny TSLA residual are the remaining active U.S. positions. GGLL, GLD, SOXL, UGL, INTC, SOXS, TSLQ, and GDXU remain closed or prohibited.

## Cash Defense Operating Mode

The operating mode remains `cash_defense_core_position_survival_mode`. U.S. cash defense and Binance USDT defense remain top-level review signals.

## Rule Compliance vs Opportunity Cost Separation

The AI Board must display opportunity cost separately from rule compliance. Closed-instrument rebounds do not automatically imply rule failure, and imperfect price quality is distinct from account-structure improvement.

## Final Commander Arbitration Model

Final Commander may arbitrate disagreements and produce a read-only final judgement trace. Final Commander cannot place trades, mutate records, promote checkpoints from UI, connect APIs, or expose customer-facing output.

## Customer-facing Blocked State

Customer-facing readiness remains `false`. The AI Board static spec is internal and non-customer-facing.

## Validation Result

Expected validator:

`bash scripts/validate_ai_board_cockpit_static_spec.sh`

Expected result:

- AI Board cockpit static spec validation passed
- blocking failures: `0`
- warnings: `0`
- active checkpoint: `2026-06-12T09:18:00+08:00`
- operating mode: `cash_defense_core_position_survival_mode`
- portfolio mode: `residual_core_position_mode`
- actual UI created: `false`
- frontend app created: `false`
- HTML/CSS/JS UI created: `false`
- API server created: `false`
- live endpoint created: `false`
- customer-facing ready: `false`
- trading automation enabled: `false`

## Remaining Gaps Before Phase 6.7

- Static spec integration across internal operator and AI Board surfaces is not yet reviewed.
- No permission-enforced renderer exists.
- No customer-facing masking runtime exists.
- No API server or live endpoint exists.
- No UI exists.

Recommended next phase:

`Vol.6 Phase 6.7 - Cockpit Static Spec Integration Review`
