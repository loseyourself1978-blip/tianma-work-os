# Roadmap Phase vs Runtime Volume Taxonomy

## 1. Why This Clarification Exists

The repository uses the word "Phase" in two different contexts: the public-facing product roadmap and the internal runtime execution stream used by Codex instructions. Phase 9.9 makes those layers explicit so future work does not confuse roadmap maturity with repository execution substeps.

## 2. Roadmap Phase Layer

`roadmap_phase` means the product roadmap stage described in `ROADMAP.md`:

| Roadmap phase | Label | Current Phase 9.9 interpretation |
| --- | --- | --- |
| Phase 0 | Open-Source Foundation and Product Thesis | Repository foundation and thesis work exist. |
| Phase 1 | Product Blueprint and MVP Scope | Product blueprint artifacts exist. |
| Phase 2 | Manual Prototype and Real Scenario Validation | Current Vol.9 work primarily supports this layer. |
| Phase 3 | MVP Build | Not active. |
| Phase 4 | Multi-Model Professional Execution Layer | Not active. |
| Phase 5 | Public Collaboration and Ecosystem | Not active. |

## 3. Runtime Volume Layer

`runtime_volume` means an operational execution cycle / work volume, such as Vol.5, Vol.6, Vol.7, Vol.8, or Vol.9. A runtime Volume can support one or more roadmap phases without being identical to them.

## 4. Volume Internal Phase Layer

`volume_internal_phase` means a subphase inside a runtime volume, such as Vol.9 Phase 9.1, Vol.9 Phase 9.2, or Vol.9 Phase 9.9. These phases are implementation/documentation substeps inside a Volume.

```text
Roadmap Phase 0–5 and runtime Vol.1–Vol.9 are not the same taxonomy layer.
Roadmap phases describe product maturity and strategic roadmap stages.
Runtime volumes describe iterative execution cycles inside the repository and project workflow.
Volume internal phases describe implementation/documentation substeps inside a runtime volume.
```

## 5. Current Mapping

Current Vol.9 work primarily supports Roadmap Phase 2 — Manual Prototype and Real Scenario Validation, while preparing validation-backed planning evidence for later roadmap phases. It does not activate Phase 3 MVP Build, Phase 4 Multi-Model Professional Execution Layer, or Phase 5 Public Collaboration and Ecosystem.

Current status remains:

```text
customer_facing_readiness: false
live_runtime_execution_frameworks: 0
future_gate_activation: false
```

## 6. Non-Activation Boundary

This taxonomy map does not create production UI, customer-facing UI, hosted app, API server, live endpoint, external API, broker/Binance connection, live market data, trading automation, credential handling, login/auth, runtime mutation, execution trigger, order placement, portfolio modification, background worker, scheduler, notification dispatcher, package manager files, build tools, frontend framework, network dependency, external integration, or production deployment capability.
