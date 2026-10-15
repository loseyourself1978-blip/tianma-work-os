# Risk-tiered delegated review — TWOS-UX-20260926-03

Status: DESIGN_ONLY / DISABLED. Linked to TWOS-UX-20260929-01.
This document is a proposed design, not Owner authorization to activate it.

An Owner-granted policy would specify task classes, repository/file boundaries,
allowed tools, network destinations, monetary/token/time budgets, expiration
and maximum actions. Absent a matching grant, the existing human gates apply.
The executor cannot grant or expand its own authority by declaring work low risk.

The reviewer must be distinct from the executor, with independently obtained
inputs and verification evidence. Review checks exact artifacts, hashes, parent
state, destination, remaining budget and policy version. Invalid or incomplete
evidence, excessive scope/cost, failed verification, disagreement, uncertainty,
medical decisions, financial orders and any irreversible high-risk action
escalate to a human. Reviewer unavailability fails closed.

A delegated decision is recorded as AI_APPROVED with actor/model, policy grant,
artifact binding, reasons, independent checks, budget accounting and timestamp.
It is never recorded as OWNER_APPROVED. Human decisions retain their actual
actor. Execution is still separately bound to the exact approved state, with
idempotency, no automatic transport retry and stale-approval invalidation.

Owner can revoke a grant at any time. Revocation is checked before every action
and prevents queued actions from beginning; active operations follow their safe
cancellation protocol. Audit is append-only and shows attempted, denied,
revoked and completed actions, including budget usage and escalation outcome.

Activation would require its own product/security design gate, adversarial
cross-task/scope/budget tests and explicit Owner acceptance. This work adds no
runtime policy switch and enables no delegation. LDD order authority remains
NONE; medical human approval gates remain mandatory.
