# Vol.6 Phase 6.3 Read-only API Contract v0.1

## 1. Purpose

Phase 6.3 defines a static read-only API contract for future LDD Cockpit
consumers. It describes data layers, endpoint identifiers, response envelopes,
permission and masking behavior, warnings, errors, and prohibited actions.

This phase creates no API server, route, listener, live endpoint, connector,
authentication system, frontend application, or execution path.

## 2. Relationship to Phase 6.1 UI Boundary

Phase 6.1 defines which internal surfaces may consume cockpit data and keeps
the customer-facing surface blocked. The API contract inherits those
read-only surface boundaries and does not create a new consumer surface.

## 3. Relationship to Phase 6.2 Permission and Privacy Masking

Phase 6.2 defines the role taxonomy, field permission matrix, masking actions,
never-expose policy, and customer-facing unblock criteria.

Every response contract must carry a permission role and masking profile.
Unmapped roles or fields are denied by default.

## 4. Relationship to Phase 6.2a Non-promoted Governance Evidence

The 2026-06-10 17:06 SGT/BJT governance record contains newer screenshot
evidence but is not an active checkpoint and is not an execution event.

The API contract may expose it only as non-promoted evidence with an explicit
banner and reconciliation metadata. It must not silently overwrite the active
checkpoint.

## 5. Read-only API Contract Scope

The contract defines:

- static endpoint identifiers;
- approved source layers;
- standard response envelopes;
- warning and data-quality behavior;
- stale-checkpoint override metadata;
- role and masking references;
- forbidden capabilities.

All endpoint entries are contract-only and use `READ_CONTRACT_ONLY`. No
runnable URL, HTTP method, route handler, or server implementation exists.

## 6. Data Source Layers

### active_checkpoint

- Source: `cockpit/ldd/view_model.json`
- Checkpoint: `2026-06-10T08:49:00+08:00`
- Timeline events: `84`
- Timeline warnings: `0`
- Promoted: `true`

### non_promoted_governance_evidence

- Source:
  `records/ldd/2026-06-10/vol6_phase6_2a_ldd_premarket_runtime_sync_governance_patch_1706_sgt.json`
- Timestamp: `2026-06-10T17:06:00+08:00`
- Promoted: `false`
- Execution event: `false`
- Purpose: stale-checkpoint override evidence and future reconciliation
  context

### permission_privacy_masking_contract

- Source: Phase 6.2 permission, privacy, and masking artifacts
- Customer-facing ready: `false`
- Deny by default: `true`

### ui_boundary_contract

- Source: Phase 6.1 UI boundary artifacts
- Customer-facing view: `blocked`
- Internal read-only: `allowed`

## 7. Active Checkpoint vs Non-promoted Evidence

Active checkpoint data remains the promoted current-state contract.

Non-promoted evidence:

- may be returned only with `promoted_to_checkpoint: false`;
- must identify its source and timestamp;
- must state whether it is an execution event;
- must show affected fields and reconciliation status;
- must not silently replace active checkpoint fields;
- must not change timeline counts or cockpit state.

## 8. Response Envelope Model

Every response example contains:

- contract version and endpoint identifier;
- generation metadata;
- data source layer;
- active checkpoint timestamp;
- non-promoted evidence availability and timestamp;
- promotion status;
- Source-of-Truth and quote type;
- permission role and masking profile;
- customer-facing readiness;
- warnings and data quality;
- stale-checkpoint overrides;
- payload;
- forbidden actions.

## 9. Endpoint Catalog Model

The static catalog defines:

- cockpit snapshot read;
- positions read;
- rules read;
- governance evidence read;
- warnings read;
- permission and masking policy read;
- customer-facing blocked-status read.

Endpoint IDs are contract labels, not live paths.

## 10. Permission and Masking Enforcement

- Every endpoint lists allowed and blocked roles.
- Sensitive account fields require masking.
- Execution-sensitive rules remain non-interactive.
- Audit evidence is restricted to audit/debug roles.
- `never_expose` content is rejected before rendering.
- Customer-facing access remains false.

## 11. Stale-checkpoint Override Metadata

The contract represents newer evidence without promoting it:

- GLD active checkpoint value may show 20; newer evidence shows 10.
- NVDA active checkpoint value may show 20; newer evidence shows 15.
- SOXL, UGL, and INTC are closed in newer evidence.

Consumer display policy:

```text
Show active checkpoint with a newer-evidence banner.
Do not silently overwrite promoted state.
Require reconciliation before checkpoint promotion.
```

## 12. Source-of-truth and Quote-type Metadata

Responses must preserve:

- user broker screenshots;
- user Binance screenshots;
- user-provided LDD Review Sync;
- external data as cross-check only;
- quote type, including the premarket broker-platform Source-of-Truth tag.

Static values must never be presented as live or executable quotes.

## 13. Forbidden Capabilities

The contract blocks order placement, cancellation, modification, trade
execution, bot control, grid reopening, external connections, live data,
runtime mutation, checkpoint promotion, warning suppression, data-quality
hiding, never-expose disclosure, credential handling, sensitive customer
exports, and customer-facing UI enablement.

## 14. Consumer Error and Warning Model

- Missing required contract fields are blocking errors.
- Stale or non-promoted evidence produces visible warnings.
- Data-quality flags cannot be hidden.
- Masked or omitted fields retain a policy explanation.
- Permission denial does not return the protected source value.
- No error response may suggest retrying through a live connection.

## 15. Explicit Non-goals

- No frontend application or customer-facing UI.
- No API server, HTTP listener, route, controller, or live endpoint.
- No external, broker, Binance, or market-data connection.
- No authentication or credential handling.
- No order, trade, bot, grid, or execution capability.
- No runtime mutation or checkpoint promotion.
- No historical record changes.
- No GitHub Issue or Projects board.

## 16. Validation Strategy

Run:

```bash
bash scripts/validate_read_only_api_contract.sh
```

The validator checks required artifacts, schemas, safety booleans, endpoint
IDs, endpoint immutability, response metadata, stale overrides, forbidden
actions, all forbidden capabilities, and absence of server, connector,
executor, credential-store, or frontend implementation patterns.

## 17. Phase 6.4 Entry Criteria

Phase 6.4 may review a static cockpit prototype boundary only after:

- this contract validator passes;
- active and non-promoted layers remain distinct;
- customer-facing readiness remains false;
- permissions and masking remain deny-by-default;
- no server or live endpoint exists;
- static prototype inputs use response examples or the view model only;
- execution-sensitive fields remain non-interactive.
