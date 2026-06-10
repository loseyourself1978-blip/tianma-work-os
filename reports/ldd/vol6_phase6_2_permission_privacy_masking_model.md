# Vol.6 Phase 6.2 Permission Privacy Masking Model

## Baseline

- Starting commit: `0711cfa57b42c922307388bc6972e2182d12a913`
- Latest checkpoint: `2026-06-10T08:49:00+08:00`
- Runtime timeline: `84` events
- Timeline warnings: `0`
- Customer-facing readiness: `false`

## Artifacts Created

- Phase 6.2 governance document
- Permission/privacy contract and review schemas
- Six-role taxonomy
- Six-action masking policy
- Six-class field permission matrix
- Customer-facing unblock criteria
- Read-only semantic validator and shell wrapper
- Governance review record

## Role Taxonomy

The model defines system administrator, internal operator, AI Board reviewer,
audit reviewer, demo viewer, and blocked customer-facing viewer roles.

Every role is read-only. No role may access `never_expose`, mutate runtime, or
trigger execution.

## Masking Actions

- `visible`
- `masked_partial`
- `masked_full`
- `omitted`
- `blocked`
- `reject_before_render`

## Field Permission Decisions

- Public-safe content requires copy review.
- Internal content is not customer-facing by default.
- Sensitive account values require authorization and masking.
- Execution-sensitive data remains non-interactive.
- Audit-only data is restricted to audit/debug roles.
- Never-expose data is rejected for every role.

## Customer-facing State

Customer-facing rendering remains blocked. The static contracts exist, but
governance approval, real authentication and authorization, privacy review,
and customer disclosure policy remain absent.

## Validation Result

The permission/privacy/masking validator passed with zero blocking failures
and zero warnings.

## Remaining Gaps Before Phase 6.3

- Define read-only API resources and error boundaries.
- Carry field-class decisions into API response contracts.
- Keep the API server and live endpoints unimplemented.
- Preserve deny-by-default authorization behavior.
