# Vol.8 Feedback-to-Roadmap Mapping Guide v0.1

## What This Guide Is For

This guide helps a product owner or strategy reviewer convert Phase 8.3 local operator feedback into safe Phase 8.4 product-boundary decisions.

The guide is static-only. It does not authorize implementation, live integrations, execution, credentials, customer-facing readiness, or runtime behavior.

## How to Read Feedback Rollup

Start with `docs/runtime/VOL8_LOCAL_OPERATOR_FEEDBACK_ROLLUP_v0.1.md`.

Review:

- total feedback items
- category counts
- severity counts
- routing counts
- forbidden-scope requests
- live/runtime/execution requests
- boundary risk notes
- recommended next action

Use the rollup as source evidence. Do not treat the rollup as product approval.

## How to Map Feedback to Product Boundary Decisions

For each feedback item:

- record the source feedback ID and title
- choose one mapping category
- choose one boundary decision
- state what action is allowed now
- state what action is disallowed now
- mark whether a future gate is required
- keep forbidden capability booleans false
- add a recommended next action

Every mapping item should answer: what can be safely done now, and what must wait?

## How to Identify Safe Static-Only Refinements

Use `safe_to_refine_now_static_only` when the action is limited to:

- documentation clarification
- fixture explanation
- QA checklist refinement
- terminology cleanup
- static boundary reminder
- framework index metadata update backed by committed artifacts

The allowed current action must remain local, static, read-only, fixture-only, no-network, and no-execution.

## How to Identify Roadmap-Only Candidates

Use `roadmap_only_no_implementation` when the feedback is useful for future planning but cannot be implemented in the current phase.

Roadmap-only candidates should:

- describe the future planning idea
- avoid implementation language
- avoid customer-facing readiness claims
- avoid live/runtime/execution readiness claims
- name any future gate that would be needed before implementation planning

## How to Identify Readiness-Gate Requirements

Use `requires_future_readiness_gate` when the item cannot proceed until a future gate defines the required boundary.

Gate types may include:

- `runtime_boundary_readiness_gate`
- `customer_facing_boundary_readiness_gate`
- `security_credential_boundary_readiness_gate`
- `execution_governance_readiness_gate`
- `implementation_readiness_gate`

## How to Reject Forbidden-Scope Feedback

Use `reject_forbidden_scope` when the feedback asks for something explicitly forbidden in Vol.8 Phase 8.4.

The mapping should:

- identify the forbidden request
- restate the static-only boundary
- mark all capability booleans false
- avoid turning the rejected request into backlog work

## How to Defer Live, Runtime, Execution, or Customer-Facing Requests

Use a deferral decision when feedback may be worth future boundary study but cannot be handled now:

- `defer_until_runtime_boundary_defined`
- `defer_until_customer_facing_boundary_defined`
- `defer_until_security_and_credential_boundary_defined`
- `defer_until_execution_governance_defined`

Deferral is not acceptance. Deferral means no current implementation.

## Final Mapping Review Template

Reviewer:

Review date:

Source rollup:

Mapped item count:

Safe static-only refinements:

Roadmap-only candidates:

Future readiness gates required:

Rejected forbidden-scope requests:

Deferred live/runtime/execution requests:

Boundary risk notes:

Recommended next phase:
