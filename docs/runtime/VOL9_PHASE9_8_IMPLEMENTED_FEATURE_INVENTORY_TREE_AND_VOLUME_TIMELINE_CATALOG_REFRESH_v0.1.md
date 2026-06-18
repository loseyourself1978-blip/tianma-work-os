# Vol.9 Phase 9.8 - Implemented Feature Inventory Tree and Volume Timeline Catalog Refresh v0.1

## Scope

Vol.9 Phase 9.8 creates a product-readable implemented feature inventory tree and volume timeline catalog. It upgrades visibility for Codex and repository readers by showing implemented modules, submodules, concrete feature descriptions, introduction timing, validation coverage, and static/non-live readiness boundaries.

This is a documentation, schema, fixture, index, and validation phase only. It does not create live implementation.

## Repository Baseline Snapshot

| Field                                     | Value                                                       |
| ----------------------------------------- | ----------------------------------------------------------- |
| Latest completed phase before Phase 9.8   | Vol.9 Phase 9.7                                             |
| Latest commit before Phase 9.8            | 10f0c3e419378df8033bdfd594cbf2a163351ecb                    |
| Runtime records baseline before Phase 9.8 | 120                                                         |
| Frameworks indexed                        | 24                                                          |
| Customer-facing frameworks                | 0                                                           |
| Live/runtime/execution frameworks         | 0                                                           |
| Fixture/static/read-only frameworks       | 24                                                          |
| Validation-backed frameworks              | 24                                                          |
| Baseline state                            | ldd_full_report_scope_gate_created                          |
| Future gate activation                    | false                                                       |
| Customer-facing readiness                 | false                                                       |
| Static shell mode                         | local_static_read_only_fixture_only_no_network_no_execution |

## User Correction / Product Feedback Input

```text
在 Codex 怎么没有看到已经实现的功能清单了。
将已实现功能清单内容更新：
首先以树状结构展示已实现的功能模块以及子功能模块，
然后再以表格形式展示具体的功能介绍以及实现的时间轴（卷编号）。
在给到 Codex 的下一个指令更新。
```

Phase 9.8 satisfies this by creating the main user-facing and Codex-facing feature catalog at:

```text
docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md
```

The existing implemented function framework index remains valid and now links forward to the product-readable inventory.

## Phase 9.7 Input State

```text
Before Phase 9.8:
state_name: ldd_full_report_scope_gate_created
implemented_feature_inventory_tree_created: false
implemented_feature_timeline_catalog_created: false
```

## Phase 9.8 Output State

```text
After Phase 9.8:
state_name: implemented_feature_inventory_catalog_created
implemented_feature_inventory_tree_created: true
implemented_feature_timeline_catalog_created: true
feature_inventory_codex_visible: true
future_gate_activation: false
customer_facing_readiness: false
live_runtime_execution_frameworks: 0
```

Phase 9.8 upgrades implemented feature visibility by creating a product-readable implemented feature inventory tree and volume timeline catalog. It does not create or activate customer-facing readiness, live runtime readiness, runtime mutation, external integrations, market data connections, trading automation, broker/Binance connectivity, credential handling, notification dispatching, scheduling, or production deployment.

## Implemented Feature Inventory Purpose

The inventory answers:

1. What modules have already been implemented?
2. What submodules exist under each module?
3. Which Vol./Phase introduced or matured each feature?
4. Which features are static-only?
5. Which features are mock consumer fixtures?
6. Which features are validation-backed?
7. Which features are protocols or planning artifacts only?
8. Which features are explicitly not customer-facing, not live, and not execution-capable?
9. Which artifacts should Codex read first to understand existing functionality?

## Required Tree Structure

The implemented feature inventory tree must start the main catalog document and include these top-level modules:

```text
Tianma Work OS Runtime Governance
LDD Runtime Records & Execution Ledger Support
Static Shell / LDD Cockpit Planning
Mock Consumer Fixtures
Framework Index & Feature Inventory
Cross-Workspace Baseline Sync
Future Implementation Boundary & Gate System
LDD Full-Market Review Scope System
Order Reconciliation & Zero-Fill Separation
Source-of-Truth / Quote-Type / Execution Event Boundaries
Validation & Regression Guard Harness
DUXD Product Feedback Backfeed
```

Every tree node carries:

```text
module_name
module_type
introduced_in
current_status
readiness_classification
validation_status
primary_artifacts
non_activation_statement
```

## Required Feature Timeline Table

The timeline table follows the tree and includes:

```text
Feature ID
Feature Module
Submodule / Capability
Feature Description
Introduced In
Updated In
Primary Artifacts
Validation Coverage
Readiness Classification
Customer-Facing Readiness
Live / Runtime / Execution Capability
Notes
```

Every feature row keeps:

```text
Customer-Facing Readiness = false
Live / Runtime / Execution Capability = false
```

## Volume Timeline Coverage

The catalog covers repository-supported Vol.5 through Vol.9 feature history, with Vol.3 and Vol.4 references where the existing framework index already supports them.

Required Vol.9 entries:

```text
Vol.9 Phase 9.1 - Cross-Workspace Baseline Drift Resolution & Runtime Status Backfeed Protocol
Vol.9 Phase 9.2 - LDD Consumer Acknowledgement Fixture & Strict Baseline Sync-Ready Gate
Vol.9 Phase 9.3 - Future Implementation Boundary Matrix & Static Prototype Gate
Vol.9 Phase 9.4 - Static Prototype Evidence Pack & Future Gate Readiness Checklist
Vol.9 Phase 9.5 - Forbidden Scope Regression Guard & Future Gate Non-Activation Audit Harness
Vol.9 Phase 9.6 - Static Shell Fixture Coverage Matrix & Prototype-to-Gate Traceability Map
Vol.9 Phase 9.7 - LDD Full-Report Scope Regression Guard, Order Reconciliation Evidence Gate & Static Cockpit Panel Requirements
```

Required historical coverage:

```text
Vol.8 Phase 8.2 - Implemented Function Framework Index
Vol.8 Phase 8.6 - Vol.8 Handoff Summary and Vol.9 Readiness Gate
Vol.7 static shell planning / static fixture consumer work
Vol.7 handoff and Vol.8 readiness gate
Vol.6 UI boundary / permission / API boundary / static cockpit planning work
Vol.5 core position defense and cockpit validation work
```

## Readiness Classification Rules

Allowed readiness classifications:

```text
static_planning
static_fixture
static_read_only_shell
mock_consumer_fixture
validation_backed
protocol_only
runtime_record_only
index_only
```

Forbidden readiness classifications:

```text
customer_facing_ready
live_runtime_ready
execution_ready
broker_connected
binance_connected
market_data_connected
production_ready
```

## Non-Activation Rules

```text
Implemented feature inventory is a visibility and traceability artifact.
It does not create new runtime capability.
It does not activate customer-facing readiness.
It does not activate live runtime readiness.
It does not activate trading execution readiness.
It must clearly distinguish implemented static frameworks from future live capabilities.
```

## Source-of-Truth Separation

TWOS runtime/product Source of Truth remains limited to product/runtime baseline state, implemented static feature inventory, static shell readiness, validation state, readiness gates, and future implementation boundaries.

LDD trading/execution Source of Truth remains limited to trading/account/execution facts such as broker screenshots, Binance screenshots, order screenshots, filled trades, expired zero-fill orders, canceled orders, portfolio changes, cash impact, and quote type.

```text
TWOS runtime/product SoT must never override LDD trading/execution SoT.
LDD trading/execution SoT must never override TWOS runtime/product SoT.
Implemented feature inventory must never mutate trading facts, portfolio state, execution ledger state, account state, or cash state.
```

## Forbidden Scope

Phase 9.8 does not create or modify:

```text
Production UI
Customer-facing UI
Hosted app
API server
Live endpoint
External API
Broker connection
Binance connection
Live market data
Trading automation
Credential handling
Login/auth
Runtime mutation
Execution trigger
Order placement
Portfolio modification
Background worker
Scheduler
Notification dispatcher
GitHub Issues
GitHub Projects board
Package manager files
Build tools
Frontend framework
Network dependency
External integration
Production deployment capability
```

## Acceptance Criteria

Phase 9.8 is accepted when:

1. Required Phase 9.8 documents, schemas, fixtures, runtime record, and validators exist.
2. The implemented feature inventory tree shows modules and submodules first.
3. The timeline table follows the tree and includes concrete feature descriptions and Vol./Phase timing.
4. Phase 9.8 validation passes.
5. Runtime record validation accepts the new record type.
6. The existing implemented function framework index remains valid.
7. `INDEX.md` references the new feature inventory clearly.
8. Forbidden scope remains non-activated.

## DUXD Queue Carried Into Later Vol.9 Phases

| Queue item | Status | Phase 9.8 handling |
| ---------- | ------ | ------------------ |
| Product-readable implemented feature visibility | completed_static_catalog | Implemented as tree plus timeline table. |
| Feature inventory maintenance workflow | future_seed | Future phases should update the inventory when new static features are added. |
| Customer-facing feature catalog | blocked_future_gate | Not activated; requires future customer-facing readiness gate. |
