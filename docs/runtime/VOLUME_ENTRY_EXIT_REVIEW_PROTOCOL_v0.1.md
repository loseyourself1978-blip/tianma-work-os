# Volume Entry / Exit Review Protocol

## 1. Purpose

This protocol makes milestone planning and principle review mandatory at the beginning and end of every future runtime Volume.

Every future runtime Volume must begin with milestone planning and principle review.
Every future runtime Volume must end with milestone review and principle adherence review.
If principles are missing, ambiguous, outdated, or contradicted by new DUXD feedback, the Volume must record an update decision.

## 2. Volume Entry Checklist

Each future runtime Volume must begin with:

- `volume_milestone_plan`
- `principle_registry_review`
- `roadmap_alignment_review`
- `prior_volume_handoff_review`
- `scope_boundary_review`
- `forbidden_scope_review`
- `source_of_truth_review`
- `validation_plan`
- `open_questions_and_update_candidates`

## 3. Volume Exit Checklist

Each future runtime Volume must end with:

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

## 4. Milestone Planning Requirements

At Volume entry, Codex must state the planned milestone, runtime baseline, intended artifact set, validation plan, forbidden scope, and expected handoff state.

At Volume exit, Codex must state whether the milestone was met, which artifacts were completed, what validation passed, what remains open, and what the next Volume inherits.

## 5. Principle Review Requirements

At Volume entry, Codex must read `docs/runtime/PRINCIPLE_REGISTRY_v0.1.md`, list relevant principles, identify drift risk, and record update candidates.

At Volume exit, Codex must review adherence, record any drift, and decide whether each update candidate becomes a principle addition, clarification, supersession, deprecation, or no-change.

## 6. Roadmap Alignment Requirements

Each Volume must identify which `roadmap_phase` it supports and must not confuse roadmap phases with runtime volumes or volume internal phases.

Current Vol.9 supports Roadmap Phase 2 manual prototype / real scenario validation and prepares planning evidence for later phases only.

## 7. Drift and Update Handling

Principle drift, missing principles, ambiguous principles, and user corrections must be recorded as explicit update decisions. A drift decision must include the affected principle group, evidence source, decision, changed artifacts, validation impact, and handoff impact.

## 8. Required Future Use

Future runtime Volumes must use this protocol before implementation work begins and before a Volume is marked complete. A Volume cannot close cleanly without a milestone review, principle adherence review, roadmap alignment review, runtime baseline review, and next-Volume readiness gate.

## 9. Non-Activation Boundary

This protocol does not create live implementation, customer-facing readiness, trading automation, broker/Binance connection, live market data, runtime execution capability, network dependency, scheduler, notification dispatcher, background worker, credential handling, runtime mutation, external integration, or production deployment.
