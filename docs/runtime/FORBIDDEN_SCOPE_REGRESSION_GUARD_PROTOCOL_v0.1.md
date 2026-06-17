# Forbidden Scope Regression Guard Protocol v0.1

## Purpose

This protocol defines how Tianma Work OS records a static forbidden scope regression guard and future gate non-activation audit without creating any live, customer-facing, runtime mutation, external integration, execution, credential, scheduler, notification, or production deployment capability.

It is local, static, read-only, fixture-only, no-network, and no-execution.

## Protocol Terms

| Term | Definition |
|---|---|
| `forbidden_scope_regression_guard` | A validation-backed static guard that checks forbidden capability classes are not present or activated. |
| `future_gate_non_activation_audit` | A validation-backed static audit confirming that future gates remain blocked unless a future validated activation phase changes them. |
| `forbidden_capability_class` | A capability class that is out of scope for Phase 9.5 and must remain not present and not activated. |
| `evidence_classification_guard` | A guard that blocks static evidence categories from being upgraded to live/customer/production/execution/credential/integration/deployment readiness. |
| `activation_regression` | Any accidental transition from static/read-only evidence to enabled capability, readiness, live runtime, mutation, integration, or execution. |
| `non_activation_statement` | A required statement that the guard validates non-activation only and does not activate capability. |

## Core Principle

```text
A regression guard prevents accidental capability activation.
A regression guard is not a capability.
A non-activation audit is not an activation.
A blocked future gate remains blocked until a future validated activation phase explicitly changes it.
```

## Required Non-Activation Rules

1. A regression guard does not activate customer-facing readiness.
2. A regression guard does not activate live runtime readiness.
3. A regression guard does not activate execution readiness.
4. A regression guard does not activate trading automation readiness.
5. A regression guard does not activate broker/Binance connectivity.
6. A regression guard does not activate credential handling readiness.
7. A regression guard does not activate scheduler or notification dispatcher readiness.
8. A regression guard does not activate production deployment readiness.
9. A regression guard does not mutate trading facts, portfolio state, account state, cash state, or execution ledger state.
10. A regression guard only prevents accidental capability activation and validates non-activation.

## Forbidden Capability Classes

Phase 9.5 guards these forbidden capability classes:

| Capability class | Required Phase 9.5 state |
|---|---|
| `production_ui` | `not_present`, not allowed, not requested, not granted, guard passed |
| `customer_facing_ui` | `not_present`, not allowed, not requested, not granted, guard passed |
| `hosted_app` | `not_present`, not allowed, not requested, not granted, guard passed |
| `api_server` | `not_present`, not allowed, not requested, not granted, guard passed |
| `live_endpoint` | `not_present`, not allowed, not requested, not granted, guard passed |
| `external_api` | `not_present`, not allowed, not requested, not granted, guard passed |
| `broker_connection` | `not_present`, not allowed, not requested, not granted, guard passed |
| `binance_connection` | `not_present`, not allowed, not requested, not granted, guard passed |
| `live_market_data` | `not_present`, not allowed, not requested, not granted, guard passed |
| `trading_automation` | `not_present`, not allowed, not requested, not granted, guard passed |
| `credential_handling` | `not_present`, not allowed, not requested, not granted, guard passed |
| `login_auth` | `not_present`, not allowed, not requested, not granted, guard passed |
| `runtime_mutation` | `not_present`, not allowed, not requested, not granted, guard passed |
| `execution_trigger` | `not_present`, not allowed, not requested, not granted, guard passed |
| `order_placement` | `not_present`, not allowed, not requested, not granted, guard passed |
| `portfolio_modification` | `not_present`, not allowed, not requested, not granted, guard passed |
| `background_worker` | `not_present`, not allowed, not requested, not granted, guard passed |
| `scheduler` | `not_present`, not allowed, not requested, not granted, guard passed |
| `notification_dispatcher` | `not_present`, not allowed, not requested, not granted, guard passed |
| `github_issues` | `not_present`, not allowed, not requested, not granted, guard passed |
| `github_projects_board` | `not_present`, not allowed, not requested, not granted, guard passed |
| `package_manager_files` | `not_present`, not allowed, not requested, not granted, guard passed |
| `build_tools` | `not_present`, not allowed, not requested, not granted, guard passed |
| `frontend_framework` | `not_present`, not allowed, not requested, not granted, guard passed |
| `network_dependency` | `not_present`, not allowed, not requested, not granted, guard passed |
| `external_integration` | `not_present`, not allowed, not requested, not granted, guard passed |
| `production_deployment` | `not_present`, not allowed, not requested, not granted, guard passed |

## Future Gate Audit Targets

Phase 9.5 audits these future gate targets:

- `static_prototype_gate`
- `customer_facing_readiness_gate`
- `live_read_only_runtime_gate`
- `runtime_mutation_gate`
- `external_integration_gate`
- `trading_execution_gate`
- `credential_handling_gate`
- `notification_scheduler_gate`
- `production_deployment_gate`

The `static_prototype_gate` remains `active_static_only` and allowed for the current phase. Every non-static gate remains `not_activated`, not allowed, not requested, not granted, and regression-guard passed.

## Evidence Classification Guard

The evidence classification guard allows only:

- `static_planning_evidence_available`
- `static_fixture_evidence_available`
- `not_provided_in_current_phase`
- `future_live_evidence_required`

The evidence classification guard blocks:

- `live_ready`
- `production_ready`
- `customer_ready`
- `execution_ready`
- `credential_ready`
- `integration_ready`
- `deployment_ready`

## Source-of-Truth Separation

TWOS runtime/product Source of Truth is used only for product/runtime baseline state, including current TWOS volume and phase, repository commit, runtime record count, framework index count, static shell readiness, validation state, customer-facing readiness, and live/runtime implementation readiness.

LDD trading/execution Source of Truth is used only for trading/account/execution facts, including broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

```text
TWOS runtime/product SoT must never override LDD trading/execution SoT.
LDD trading/execution SoT must never override TWOS runtime/product SoT.
Regression guards and non-activation audits must never mutate trading facts, portfolio state, execution ledger state, account state, or cash state.
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
