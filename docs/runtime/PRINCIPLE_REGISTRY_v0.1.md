# Tianma Work OS Principle Registry

## 1. Purpose

This registry is the canonical repository entry point for Tianma Work OS principles. It gathers principles that were previously spread across product vision, DUXD, roadmap, memory/index, runtime protocol, and LDD boundary artifacts.

The registry is static and validation-backed. It does not create customer-facing readiness, live runtime readiness, execution readiness, trading automation, broker/Binance connectivity, credential handling, runtime mutation, or production deployment.

## 2. Source Discovery Summary

Phase 9.9 scanned repository-local files for principle terms including first principles, product thesis, DUXD, source of truth, human approval, static/read-only, no live implementation, customer-facing readiness, memory, index, roadmap, MVP, and AI team.

Repository-supported principle sources found:

- `PRODUCT_VISION.md`
- `DUXD.md`
- `MVP_SCOPE.md`
- `PROJECT_MEMORY_AND_INDEX_SYSTEM.md`
- `ROADMAP.md`
- `templates/DUXD_FEEDBACK_TEMPLATE.md`
- `docs/runtime/TWOS_LDD_RUNTIME_STATUS_BACKFEED_PROTOCOL_v0.1.md`
- `docs/runtime/FUTURE_IMPLEMENTATION_BOUNDARY_PROTOCOL_v0.1.md`
- `docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md`
- `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`
- `mock_consumers/ldd/ldd_full_report_scope_requirements.json`
- `mock_consumers/ldd/ldd_order_reconciliation_and_zero_fill_separation.json`
- `mock_consumers/ldd/ldd_static_cockpit_panel_requirement_gate.json`
- `docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md`
- `INDEX.md`

If future reviews identify principle references outside this list, they must update this registry and the machine-readable fixture.

## 3. Canonical Principles

| Principle ID | Principle Group | Principle Statement | Source Status | Source Files | Introduced / Confirmed In | Applies To | Drift Risk | Review At Volume Start | Review At Volume End | Update Policy |
| ------------ | --------------- | ------------------- | ------------- | ------------ | ------------------------- | ---------- | ---------- | ---------------------- | -------------------- | ------------- |
| `principle_first_principles_product_thesis` | `first_principles_and_product_thesis` | Tianma Work OS starts from product thesis and first-principles analysis: AI work should move from answer generation to goal execution, and project knowledge must become durable, retrievable, structured memory. | `repository_supported` | `PRODUCT_VISION.md`; `MVP_SCOPE.md`; `PROJECT_MEMORY_AND_INDEX_SYSTEM.md` | Vol.9 Phase 9.9 | Product thesis, memory system, roadmap planning | medium | true | true | Update only through a validated principle registry revision. |
| `principle_duxd_feedback_loop` | `duxd_real_scenario_feedback_loop` | Real usage becomes product intelligence; DUXD converts real scenario pressure, pain points, and corrections into product requirements and iteration. | `repository_supported` | `DUXD.md`; `templates/DUXD_FEEDBACK_TEMPLATE.md`; `MVP_SCOPE.md` | Vol.9 Phase 9.9 | Product discovery, LDD feedback, roadmap updates | medium | true | true | New DUXD findings must be mapped to requirement, principle, or roadmap update decisions. |
| `principle_human_strategy_ai_execution` | `human_strategy_ai_execution_boundary` | The user owns strategy, direction, judgment, approval, and accountability; AI supports research, structuring, drafting, verification, execution support, memory retrieval, review, and improvement. | `repository_supported` | `PRODUCT_VISION.md`; `ROADMAP.md` | Vol.9 Phase 9.9 | AI roles, approval boundaries, risk review | high | true | true | Any automation expansion must preserve human approval and accountability boundaries. |
| `principle_sot_separation` | `source_of_truth_separation` | TWOS runtime/product Source of Truth must never override LDD trading/execution Source of Truth, and LDD trading/execution Source of Truth must never override TWOS runtime/product Source of Truth. | `repository_supported` | `docs/runtime/TWOS_LDD_RUNTIME_STATUS_BACKFEED_PROTOCOL_v0.1.md`; `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `MVP_SCOPE.md` | Vol.9 Phase 9.9 | TWOS baseline, LDD trading facts, runtime records | high | true | true | Source precedence changes require explicit schema, fixture, and validator updates. |
| `principle_static_before_live` | `static_before_live_boundary` | Static planning, fixtures, and read-only shells must precede any live/runtime/customer-facing capability claim. | `repository_supported` | `docs/runtime/FUTURE_IMPLEMENTATION_BOUNDARY_PROTOCOL_v0.1.md`; `docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md` | Vol.9 Phase 9.9 | Prototype planning, future gates, validators | high | true | true | Static artifacts may only support planning, fixture, static shell, and validation evidence. |
| `principle_no_live_without_gate` | `no_live_implementation_without_gate` | No live implementation, integration, runtime mutation, execution capability, credential handling, scheduler, notification dispatcher, or production deployment may be introduced without a future validated activation gate. | `repository_supported` | `docs/runtime/FUTURE_IMPLEMENTATION_BOUNDARY_PROTOCOL_v0.1.md`; `docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md` | Vol.9 Phase 9.9 | Future implementation levels, forbidden scope, CI-style validation | high | true | true | Activation requires a dedicated future phase with evidence, schemas, fixtures, and validation. |
| `principle_customer_readiness_false_until_gate` | `customer_facing_readiness_false_until_gate` | Customer-facing readiness remains false until a future customer-facing readiness gate is explicitly validated and activated. | `repository_supported` | `docs/runtime/FUTURE_IMPLEMENTATION_BOUNDARY_PROTOCOL_v0.1.md`; `docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md`; `docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md` | Vol.9 Phase 9.9 | Static shell, future gate system, runtime records | high | true | true | Any change to customer readiness must be intentional, isolated, and validator-backed. |
| `principle_memory_index_handoff` | `memory_index_and_handoff_continuity` | Long-running work must preserve continuity through durable memory, indexes, handoff summaries, explicit document updates, and cross-project sync blocks. | `repository_supported` | `PROJECT_MEMORY_AND_INDEX_SYSTEM.md`; `INDEX.md` | Vol.9 Phase 9.9 | Runtime handoff, Codex reading order, project memory | medium | true | true | Every Volume must update or confirm memory/index/handoff references. |
| `principle_volume_execution_handoff` | `volume_based_execution_and_handoff` | Runtime Volumes are iterative execution cycles that must carry milestone planning, handoff summaries, and readiness gates across work sessions. | `repository_supported` | `PROJECT_MEMORY_AND_INDEX_SYSTEM.md`; `INDEX.md`; `records/ldd/2026-06-15/vol7_phase7_8_handoff_summary_and_vol8_readiness_gate.json`; `records/ldd/2026-06-16/vol8_phase8_6_handoff_summary_and_vol9_readiness_gate.json` | Vol.9 Phase 9.9 | Volume planning, Volume exit, readiness gates | medium | true | true | Future Volumes must use the entry/exit protocol created in Phase 9.9. |
| `principle_full_standalone_sync` | `full_standalone_sync_after_correction` | After user correction to LDD scope, assumptions, screenshots, order details, source-of-truth priority, execution classification, rules, or format, regenerate the full latest LDD report and full LDD -> TWOS Sync Block unless the user explicitly says otherwise. | `repository_supported` | `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `mock_consumers/ldd/ldd_full_report_scope_requirements.json` | Vol.9 Phase 9.9 | LDD report correction, TWOS sync block | high | true | true | Corrections must not be reduced to incremental patches by default. |
| `principle_ldd_full_market_scope` | `ldd_full_market_scope` | LDD premarket and post-close reviews must preserve full-market scope and must not collapse into holdings-only, current-position-only, or former-position-only reviews. | `repository_supported` | `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `mock_consumers/ldd/ldd_full_report_scope_requirements.json` | Vol.9 Phase 9.9 | LDD report scope, cockpit panel requirements | high | true | true | Missing full-market sections require regeneration or explicit user override. |
| `principle_execution_evidence_before_classification` | `execution_ledger_evidence_before_classification` | Order-detail evidence is required before classifying trade direction, filled quantity, cash impact, or portfolio change. | `repository_supported` | `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `mock_consumers/ldd/ldd_order_reconciliation_and_zero_fill_separation.json` | Vol.9 Phase 9.9 | Execution ledger, order reconciliation, LDD report facts | high | true | true | Do not infer execution state from order-count screenshots alone. |
| `principle_zero_fill_separation` | `zero_fill_order_separation` | Expired zero-fill orders are separate from actual filled trades and must not create portfolio changes or cash impact. | `repository_supported` | `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `mock_consumers/ldd/ldd_order_reconciliation_and_zero_fill_separation.json` | Vol.9 Phase 9.9 | Execution ledger, SPCX correction, future classifier seed | high | true | true | Zero-fill separation remains static until a future classifier is explicitly implemented. |
| `principle_quote_type_tagging` | `quote_type_tagging` | Preserve quote-source distinctions, including watchlist, premarket, holding valuation, order-page executable, and final filled prices. | `repository_supported` | `docs/runtime/TWOS_LDD_RUNTIME_STATUS_BACKFEED_PROTOCOL_v0.1.md`; `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md` | Vol.9 Phase 9.9 | LDD trading facts, execution evidence, report writing | medium | true | true | Only final filled price is actual execution price; other quote types must remain tagged. |
| `principle_dream_sleeve_monitoring_only` | `dream_sleeve_monitoring_only_boundary` | Dream Sleeve is monitoring and recommendation only; it must not override LDD rational main strategy, risk controls, cash-defense rules, or execution authority. | `repository_supported` | `docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md`; `mock_consumers/ldd/ldd_full_report_scope_requirements.json`; `mock_consumers/ldd/ldd_static_cockpit_panel_requirement_gate.json` | Vol.9 Phase 9.9 | LDD strategy boundaries, symbolic watchlist, cockpit requirements | medium | true | true | Dream Sleeve changes require explicit separation from main-strategy decisions. |
| `principle_roadmap_runtime_taxonomy` | `roadmap_phase_vs_runtime_volume_taxonomy` | Roadmap Phase 0-5, runtime Vol.1-Vol.9, and volume-internal phases are separate taxonomy layers and must not be treated as the same planning unit. | `introduced_in_phase9_9` | `ROADMAP.md`; `docs/runtime/ROADMAP_PHASE_AND_RUNTIME_VOLUME_TAXONOMY_v0.1.md` | Vol.9 Phase 9.9 | Roadmap planning, Codex instructions, Volume entry/exit review | high | true | true | Any future roadmap or Volume instruction must name the taxonomy layer it uses. |

## 4. Principles Needing Canonicalization

Phase 9.9 canonicalizes all required principle groups listed above. If a future principle is known from project history but no source file is found, record it with:

```text
source_status: needs_canonicalization
Source file not found during Phase 9.9 repository scan; retained as project principle and added to canonical registry.
```

## 5. Principle Review Policy

Every principle entry must preserve:

```text
review_required_at_volume_start: true
review_required_at_volume_end: true
customer_facing_readiness: false
live_runtime_execution_capability: false
```

Principle changes must be recorded as add, clarify, supersede, deprecate, or no-change decisions.

## 6. Volume Start Principle Review

At the start of each runtime Volume, Codex must review this registry, identify the principles relevant to the planned milestone, check whether user corrections created update candidates, and record any ambiguity before implementation work begins.

## 7. Volume End Principle Review

At the end of each runtime Volume, Codex must review principle adherence, identify drift, decide whether any principle should be updated, and carry unresolved updates into the next Volume handoff.

## 8. Non-Activation Boundary

This registry does not activate live implementation, customer-facing readiness, trading automation, broker/Binance connection, live market data, runtime execution capability, network dependency, scheduler, notification dispatcher, background worker, credential handling, runtime mutation, external integration, or production deployment.
