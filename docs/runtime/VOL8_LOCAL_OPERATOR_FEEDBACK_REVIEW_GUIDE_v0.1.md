# Vol.8 Local Operator Feedback Review Guide

Use this guide when reviewing the local static shell under `static_shell/ldd/`.

## 1. What To Review

Review:

- static-shell clarity
- information architecture
- visual hierarchy
- fixture readability
- terminology consistency
- missing context
- operator trust risks
- static/read-only boundary clarity
- QA checklist gaps
- documentation refinements
- roadmap-only product candidates

## 2. What Not To Review As Implemented Capability

Do not review these as available capabilities:

- live data
- API access
- broker connectivity
- Binance connectivity
- credentials or auth
- execution
- order placement
- portfolio mutation
- runtime mutation
- scheduling
- notifications
- customer-facing readiness

If a feedback item asks for one of these, mark it as forbidden scope or defer it until a future readiness gate.

## 3. How To Write A Feedback Item

Each item should include:

- short title
- concise summary
- affected artifact paths
- category
- severity
- routing
- boundary-risk flag
- recommended action
- status

Use concrete artifact paths where possible. Avoid implying that a future feature is already approved.

## 4. How To Assign Category

Choose one category:

- `blocking_clarity_issue`
- `non_blocking_ux_improvement`
- `information_architecture_issue`
- `visual_hierarchy_issue`
- `fixture_readability_issue`
- `terminology_drift`
- `operator_trust_risk`
- `missing_context`
- `documentation_refinement`
- `future_product_candidate`
- `boundary_question`
- `forbidden_scope_request`
- `live_runtime_request`
- `execution_related_request`
- `out_of_scope_for_vol8`

Use the most specific category that captures the operator concern.

## 5. How To Assign Severity

Use:

- `critical` if the issue could imply live, execution, or customer-facing capability
- `high` if it could mislead product boundary or LDD decision interpretation
- `medium` if it affects comprehension without boundary risk
- `low` for wording or visual polish
- `note` for observations only

## 6. How To Assign Routing

Route each item to one of:

- `static_shell_doc_refinement`
- `static_shell_fixture_refinement`
- `qa_checklist_update`
- `implemented_framework_index_update`
- `future_roadmap_backlog`
- `boundary_guardrail_review`
- `reject_forbidden_scope`
- `defer_until_future_readiness_gate`

Use rejection or deferral for any request involving live data, network, credentials, auth, mutation, execution, broker, Binance, scheduler, notification, hosted app, or customer-facing release.

## 7. How To Mark Feedback As Roadmap-Only

Set `roadmap_only` to `true` when the feedback may be useful later but should not be implemented now.

Roadmap-only feedback still requires a future readiness gate if it touches live/runtime/customer-facing scope.

## 8. How To Flag Boundary Risk

Set `boundary_risk` to `true` if a reviewer could misunderstand the shell as:

- live
- executable
- connected to APIs
- connected to broker or Binance
- credential-enabled
- mutable
- customer-facing

Boundary-risk feedback must route to `boundary_guardrail_review`, `reject_forbidden_scope`, or `defer_until_future_readiness_gate`.

## 9. Final Reviewer Note Template

Reviewer role:

Review date:

Static shell path:

Overall static-shell comprehension:

Boundary clarity:

Accepted static-shell feedback:

Documentation refinements:

Roadmap-only candidates:

Forbidden-scope requests rejected:

Requests deferred until future readiness gate:

Boundary-risk notes:

Recommended next action:
