# Static Shell Prototype Traceability Protocol v0.1

## Purpose

This protocol defines how Tianma Work OS maps static shell artifacts and mock consumer fixtures to future gates without activating any future gate or implying live/customer-facing/runtime/execution readiness.

It is local, static, read-only, fixture-only, no-network, and no-execution.

## Protocol Terms

| Term | Definition |
|---|---|
| `static_shell_fixture_coverage_matrix` | A validation-backed static matrix listing artifact coverage across shell, fixture, document, schema, script, record, and index domains. |
| `prototype_to_gate_traceability_map` | A validation-backed static map from prototype artifacts to future gates as planning/static evidence only. |
| `coverage_domain` | The repository-local artifact family being covered. |
| `coverage_classification` | The static coverage class assigned to an artifact. |
| `planning_evidence_only` | A trace support class that may inform future review but cannot activate a gate. |
| `static_fixture_evidence_only` | A fixture support class that may validate mock data shape but cannot activate a gate. |
| `static_validation_evidence_only` | A validator support class that may validate local artifacts but cannot activate a gate. |
| `future_gap` | Missing future evidence required before any future activation phase. |
| `non_activation_statement` | A required statement that mapped coverage remains static/planning/fixture/validation evidence only. |

## Required Non-Activation Rules

1. Traceability mapping does not activate customer-facing readiness.
2. Traceability mapping does not activate live runtime readiness.
3. Traceability mapping does not activate execution readiness.
4. Traceability mapping does not activate trading automation readiness.
5. Traceability mapping does not activate broker/Binance connectivity.
6. Traceability mapping does not activate credential handling readiness.
7. Traceability mapping does not activate scheduler or notification dispatcher readiness.
8. Traceability mapping does not activate production deployment readiness.
9. Traceability mapping does not mutate trading facts, portfolio state, account state, cash state, or execution ledger state.
10. Traceability mapping only classifies static/planning/fixture/validation coverage.

## Coverage Domains

- `static_shell_artifacts`
- `mock_consumer_fixtures`
- `runtime_protocol_documents`
- `json_schemas`
- `validation_scripts`
- `runtime_records`
- `index_references`

## Future Gate Trace Targets

- `static_prototype_gate`
- `customer_facing_readiness_gate`
- `live_read_only_runtime_gate`
- `runtime_mutation_gate`
- `external_integration_gate`
- `trading_execution_gate`
- `credential_handling_gate`
- `notification_scheduler_gate`
- `production_deployment_gate`

The `static_prototype_gate` remains `active_static_only` with `traceability_status: static_trace_only`.

All non-static gates remain `not_activated` with `traceability_status: planning_trace_only`, `current_phase_allowed: false`, `activation_requested: false`, and `activation_granted: false`.

## Artifact Traceability Rules

Artifacts may support one or more future gates only as:

- `planning_evidence_only`
- `static_fixture_evidence_only`
- `static_validation_evidence_only`

Artifacts may not support any future gate as:

- `activation_evidence`
- `production_evidence`
- `customer_facing_evidence`
- `live_runtime_evidence`
- `execution_evidence`
- `credential_handling_evidence`
- `external_integration_evidence`
- `deployment_evidence`

## Coverage Classifications

Allowed coverage classifications:

- `static_planning_coverage`
- `static_fixture_coverage`
- `static_shell_coverage`
- `static_validation_coverage`
- `runtime_record_coverage`
- `index_trace_coverage`

Forbidden coverage classifications:

- `customer_ready_coverage`
- `live_ready_coverage`
- `production_ready_coverage`
- `execution_ready_coverage`
- `integration_ready_coverage`
- `credential_ready_coverage`
- `deployment_ready_coverage`

## Future Gap Categories

For Phase 9.6, every gap category remains `open_future_gap`, `current_phase_resolved: false`, and `activation_blocker: true`.

- `security_review_gap`
- `privacy_review_gap`
- `credential_handling_gap`
- `read_only_runtime_contract_gap`
- `mutation_safety_contract_gap`
- `external_integration_contract_gap`
- `customer_facing_ux_gap`
- `production_deployment_gap`
- `rollback_plan_gap`
- `audit_log_contract_gap`
- `trading_execution_safety_gap`
- `source_of_truth_arbitration_gap`
- `live_data_contract_gap`
- `operator_review_gap`

## Source-of-Truth Separation

TWOS runtime/product Source of Truth is used only for product/runtime baseline state, including current TWOS volume and phase, repository commit, runtime record count, framework index count, static shell readiness, validation state, customer-facing readiness, and live/runtime implementation readiness.

LDD trading/execution Source of Truth is used only for trading/account/execution facts, including broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

```text
TWOS runtime/product SoT must never override LDD trading/execution SoT.
LDD trading/execution SoT must never override TWOS runtime/product SoT.
Static traceability maps must never mutate trading facts, portfolio state, execution ledger state, account state, or cash state.
```

## Preserved Trading Tags

The protocol preserves, but does not execute against, these quote types:

- `watchlist_price`
- `premarket_price`
- `holding_valuation_price`
- `order_page_executable_price`
- `final_filled_price`

The protocol preserves, but does not implement live classification for, these event types:

- `actual_filled_trade`
- `expired_zero_fill_order`
- `canceled_order`
- `portfolio_change`
- `no_cash_impact_event`

Future DUXD queue item retained: `Execution Ledger Evidence Classifier / Zero-Fill Order Separation Protocol`.
