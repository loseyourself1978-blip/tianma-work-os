# Vol.6 Phase 6.2 Permission Privacy Masking Model v0.1

## 1. Purpose

Phase 6.2 defines who may see each class of LDD Cockpit data and what must be
visible, masked, omitted, blocked, or rejected before rendering.

This is a static governance contract. It does not implement authentication,
authorization, UI, APIs, live data, account connections, or execution.

## 2. Relationship to Phase 6.1 UI Boundary Architecture

Phase 6.1 defined the permitted and blocked consumer surfaces and established
`cockpit/ldd/view_model.json` as the primary read-only consumer artifact.

Phase 6.2 applies role decisions and privacy actions to those surfaces and to
the six Phase 6.1 field classes. Raw records remain audit and debugging inputs
only.

## 3. Data Readiness vs UI Readiness vs Permission Readiness

- Data readiness means the view model is generated, valid, source-traceable,
  and internally consistent.
- UI readiness means a surface has deterministic rendering, warning,
  stale-state, quote-type, and interaction rules.
- Permission readiness means every role, field class, export path, and blocked
  condition has an explicit deny-by-default decision.

The cockpit is data-ready and internally consumable with limits. It is not
customer-facing ready.

## 4. Deny-by-default Principle

- An unmapped role receives no access.
- An unmapped field receives no rendering permission.
- An unmapped surface remains blocked.
- Missing permission context blocks rendering.
- `never_expose` data is rejected for every role, including system
  administrators.
- No role may mutate runtime state or trigger execution.

## 5. Role Taxonomy

The static role taxonomy defines:

- `system_admin`
- `internal_operator`
- `ai_board_reviewer`
- `audit_reviewer`
- `demo_viewer`
- `customer_facing_viewer_blocked`

Roles describe future policy boundaries only. They are not real identities,
accounts, login roles, or authentication claims.

## 6. Field Permission Model

The permission matrix maps:

- `public_safe`
- `internal_read_only`
- `sensitive_account_value`
- `execution_sensitive`
- `audit_only`
- `never_expose`

Each class has explicit access, masking, customer-facing, export, mutation,
and validator decisions.

## 7. Privacy Masking Policy

The masking actions are:

- `visible`
- `masked_partial`
- `masked_full`
- `omitted`
- `blocked`
- `reject_before_render`

Masking is deterministic policy, not best-effort copy editing. The strictest
applicable action wins.

## 8. Customer-facing Blocked State

`customer_facing_viewer_blocked` has no allowed cockpit surface.

Customer-facing readiness remains false. Public demo and customer-facing
surfaces stay blocked until all Phase 6.2 and future governance criteria are
met and explicitly approved.

## 9. Customer-facing Unblock Criteria

Unblocking requires:

- governance approval;
- complete permission and masking contracts;
- never-expose rejection;
- non-interactive execution-sensitive fields;
- visible warnings and data quality;
- controlled source traceability;
- absence of credentials and account identifiers;
- absence of live API, broker, Binance, trading automation, and runtime
  mutation paths;
- future authentication, authorization, privacy review, and disclosure
  policy.

The current criteria record intentionally reports `customer_facing_ready:
false`.

## 10. Audit and Debug Access Policy

- Audit access is read-only and least-privilege.
- `audit_only` fields are restricted to `system_admin` and `audit_reviewer`.
- Source paths and validation evidence remain internal.
- Audit access does not grant `never_expose`, runtime mutation, execution, or
  live connection privileges.
- Audit exports require separate approval and must preserve masking rules.

## 11. Execution-sensitive Field Policy

- Execution-sensitive fields are restricted read-only context.
- They must display non-automation labels.
- They must not become order controls.
- They must not call broker, Binance, market-data, or execution services.
- Export is blocked by default.
- Quote type and execution validity must remain visible where applicable.

## 12. Never-expose Field Policy

Never-expose fields include credentials, secrets, tokens, exact account
identifiers, and raw personal identifiers.

They must:

- use `reject_before_render`;
- be inaccessible to every role;
- never be exported;
- never be logged or cached in consumer fixtures;
- fail validation if an access path is granted.

## 13. Explicit Non-goals

- No frontend application.
- No customer-facing UI.
- No API server or live endpoint.
- No external, broker, Binance, or live market-data connection.
- No trading automation.
- No real authentication or authorization implementation.
- No credential, token, password, account-number, or live-identifier
  handling.
- No runtime, checkpoint, timeline, or trading-record changes.

## 14. Validation Strategy

Run:

```bash
bash scripts/validate_permission_privacy_masking.sh
```

The validator checks required artifacts, JSON syntax, all roles, masking
actions, field classes, explicit decisions, never-expose denial, blocked
customer access, read-only execution-sensitive policy, false customer-facing
readiness, and absence of live connection, credential, mutation, or execution
permissions.

It also verifies that validation does not mutate the contract artifacts.

## 15. Phase 6.3 Entry Criteria

Phase 6.3 may define a read-only API contract only after:

- this permission and masking validator passes;
- customer-facing readiness remains blocked;
- view-model and UI-boundary quality gates remain green;
- API resources inherit field-class decisions;
- no live server or external connector is introduced;
- authorization and error-boundary requirements are documented.
