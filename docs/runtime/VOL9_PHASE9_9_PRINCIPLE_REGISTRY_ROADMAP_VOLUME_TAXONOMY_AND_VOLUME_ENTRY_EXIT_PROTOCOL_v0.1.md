# Vol.9 Phase 9.9 - Principle Registry, Roadmap Volume Taxonomy, and Volume Entry/Exit Protocol v0.1

## Scope

Vol.9 Phase 9.9 creates validation-backed static artifacts that make Tianma Work OS foundational principles, roadmap taxonomy, runtime volume taxonomy, and future Volume entry/exit review rules visible to Codex and repository readers.

This phase is documentation, taxonomy, schema, fixture, protocol, and validation only. It does not introduce live implementation.

## Repository Baseline Snapshot

| Field | Value |
| --- | --- |
| Latest completed phase before Phase 9.9 | Vol.9 Phase 9.8 |
| Latest commit before Phase 9.9 | 6180d40315879f44fd9731c5504a0a07006df51a |
| Runtime records baseline before Phase 9.9 | 121 |
| Frameworks indexed | 24 |
| Customer-facing frameworks | 0 |
| Live/runtime/execution frameworks | 0 |
| Fixture/static/read-only frameworks | 24 |
| Validation-backed frameworks | 24 |
| Baseline state | implemented_feature_inventory_catalog_created |
| Future gate activation | false |
| Customer-facing readiness | false |
| Static shell mode | local_static_read_only_fixture_only_no_network_no_execution |

## User Correction / Product Feedback Input

```text
我刚才看了 GitHub 的内容，之前我们定义的一些原则，比如第一性原理等，在哪个文件？
还有我发现 roadmap 里是这样定义的：
Tianma Work OS Roadmap v0.1
Phase 0 — Open-Source Foundation and Product Thesis
Phase 1 — Product Blueprint and MVP Scope
Phase 2 — Manual Prototype and Real Scenario Validation
Phase 3 — MVP Build
Phase 4 — Multi-Model Professional Execution Layer
Phase 5 — Public Collaboration and Ecosystem

这里的 phase 和我们现在给到 codex 的 phase 是否一致？
我们已经开了 9 个 volume 了，因此对于每一个 volume，现在增加：
1. 每个 volume 的开头：计划本卷的 milestone，并重新回顾之前设定的原则，确认没有偏离以及是否需要补充更新
2. 每个 volume 结尾：复盘总结本卷的 milestone，并重新回顾之前设定的原则，确认没有偏离以及是否需要补充更新
```

## Phase 9.8 Input State

```text
state_name: implemented_feature_inventory_catalog_created
principle_registry_created: false
roadmap_runtime_taxonomy_created: false
volume_entry_exit_review_protocol_created: false
```

## Phase 9.9 Output State

```text
state_name: principle_registry_and_volume_protocol_created
principle_registry_created: true
roadmap_runtime_taxonomy_created: true
volume_entry_exit_review_protocol_created: true
future_volume_entry_review_required: true
future_volume_exit_review_required: true
future_gate_activation: false
customer_facing_readiness: false
live_runtime_execution_frameworks: 0
```

Phase 9.9 creates a validation-backed principle registry, roadmap phase vs runtime volume taxonomy map, and mandatory volume entry/exit review protocol. It does not activate customer-facing readiness, live runtime readiness, runtime mutation, external integrations, market data connections, trading automation, broker/Binance connectivity, credential handling, notification dispatching, scheduling, or production deployment.

## Principle Registry Purpose

The canonical registry is `docs/runtime/PRINCIPLE_REGISTRY_v0.1.md`.

It answers where principles are currently defined, whether principles are scattered, which principles are repository-supported, which need canonicalization, and which were introduced or confirmed by Phase 9.9. Each principle must be reviewed at the start and end of every future runtime Volume.

## Roadmap Phase vs Runtime Volume Clarification

Phase 9.9 defines three taxonomy layers:

| Layer | Definition | Example |
| --- | --- | --- |
| `roadmap_phase` | Product roadmap stage in Tianma Work OS Roadmap v0.1. | Roadmap Phase 2 - Manual Prototype and Real Scenario Validation |
| `runtime_volume` | Operational execution cycle / work volume in the repository and project workflow. | Vol.9 |
| `volume_internal_phase` | Subphase inside a runtime volume. | Vol.9 Phase 9.9 |

```text
Roadmap Phase 0–5 and runtime Vol.1–Vol.9 are not the same taxonomy layer.
Roadmap phases describe product maturity and strategic roadmap stages.
Runtime volumes describe iterative execution cycles inside the repository and project workflow.
Volume internal phases describe implementation/documentation substeps inside a runtime volume.
```

Current Vol.9 work primarily supports Roadmap Phase 2 - Manual Prototype and Real Scenario Validation while preparing validation-backed planning evidence for later roadmap phases. It does not activate Phase 3 MVP Build, Phase 4 Multi-Model Professional Execution Layer, or Phase 5 Public Collaboration and Ecosystem.

## Volume Entry Protocol

Every future runtime Volume must begin with:

- `volume_milestone_plan`
- `principle_registry_review`
- `roadmap_alignment_review`
- `prior_volume_handoff_review`
- `scope_boundary_review`
- `forbidden_scope_review`
- `source_of_truth_review`
- `validation_plan`
- `open_questions_and_update_candidates`

The entry review must answer what milestone the Volume targets, which roadmap phase it supports, which principles apply, whether any principles are outdated, missing, ambiguous, or conflicting, whether user correction created a principle update candidate, what is explicitly out of scope, and which validations must pass before the Volume can close.

## Volume Exit Protocol

Every future runtime Volume must end with:

- `volume_milestone_review`
- `completed_scope_review`
- `principle_adherence_review`
- `principle_drift_review`
- `principle_update_decision`
- `roadmap_alignment_review`
- `runtime_record_baseline_review`
- `feature_inventory_update_check`
- `handoff_summary`
- `next_volume_readiness_gate`

The exit review must answer whether the Volume met its milestone, which principles were followed, whether drift occurred, whether any principles were updated, added, deprecated, or clarified, whether roadmap alignment changed, whether implemented feature inventory needs updating, and what readiness state the next Volume inherits.

## Source-File Discovery Rule

Codex must search repository-local files for principle-related terms, including:

```text
first principle
first principles
第一性原理
principle
principles
product thesis
DUXD
decision protocol
source of truth
human approval
static
read-only
no live implementation
customer-facing readiness
memory
index
AI team
roadmap
MVP
```

Do not fabricate source paths. If exact principle source files exist, classify the principle as `repository_supported`. If a principle is known from project history but no clear source file is found, classify it as `needs_canonicalization`. If a principle is newly introduced by Phase 9.9, classify it as `introduced_in_phase9_9`.

## Forbidden Scope

Phase 9.9 does not create production UI, customer-facing UI, hosted app, API server, live endpoint, external API, broker connection, Binance connection, live market data, trading automation, credential handling, login/auth, runtime mutation, execution trigger, order placement, portfolio modification, background worker, scheduler, notification dispatcher, GitHub Issues, GitHub Projects board, package manager files, build tools, frontend framework, network dependency, external integration, or production deployment capability.

## Acceptance Criteria

- Required Phase 9.9 documents, schemas, fixtures, runtime record, and validator exist.
- Principle registry includes all required principle groups.
- Roadmap taxonomy distinguishes `roadmap_phase`, `runtime_volume`, and `volume_internal_phase`.
- Volume entry and exit review requirements are mandatory for future runtime Volumes.
- Customer-facing readiness remains `false`.
- Live/runtime/execution framework count remains `0`.
- Future gate activation remains `false`.
- Runtime record baseline moves from `121` to `122`.
- Phase 9.9 validator and runtime records validator pass.

## DUXD Queue Carried Into Later Phases

- Principle drift decision log and update workflow.
- Volume start template generator.
- Volume end handoff summary generator.
- Roadmap-to-runtime-volume dashboard.
- Execution Ledger Evidence Classifier / Zero-Fill Order Separation Protocol.
