# Vol.6 Phase 6.3 Read-only API Contract

## Baseline

- Starting commit: `244986a25007884f2518639ea1f8871acbfb0ea5`
- Active checkpoint: `2026-06-10T08:49:00+08:00`
- Timeline: `84` events, `0` warnings
- Consumer readiness: `ready_with_limits`
- Customer-facing readiness: `false`

## Artifacts Created

- Read-only API contract document
- Contract, response-envelope, and review schemas
- Static contract fixture
- Seven-entry endpoint catalog
- Four response examples
- Twenty-entry forbidden capability catalog
- Semantic validator and shell wrapper
- Governance review record

## Read-only Contract Scope

The package defines endpoint IDs and response shapes only. It contains no
server, route, listener, controller, daemon, live URL, or network connector.

## Source Layers

- Promoted active checkpoint
- Non-promoted Phase 6.2a governance evidence
- Permission/privacy/masking policy
- UI boundary policy

## Active Checkpoint vs Non-promoted Evidence

The `08:49` checkpoint remains active. The `17:06` GLD/NVDA evidence remains
non-promoted, non-executing reconciliation context and is displayed with a
newer-evidence banner.

## Endpoint Catalog

Seven static read contracts cover snapshot, positions, rules, governance
evidence, warnings, permission policy, and blocked customer-facing status.

Every entry is contract-only and denies mutation, execution, external
connections, credentials, and customer-facing access.

## Response Envelope

Every example includes checkpoint and evidence metadata, Source-of-Truth,
quote type, permission role, masking profile, warnings, data quality, stale
overrides, payload, and forbidden actions.

## Stale-checkpoint Override Metadata

GLD 20 to 10, NVDA 20 to 15, and closed-position evidence are represented
without silently overwriting the active checkpoint.

## Permission and Masking Integration

The contract inherits Phase 6.2 deny-by-default roles, masking actions,
execution-sensitive restrictions, and never-expose rejection.

## Forbidden Capabilities

Twenty capabilities are explicitly blocked, including trading, bot control,
checkpoint promotion, warning suppression, live connections, credential
handling, sensitive customer exports, and customer-facing UI enablement.

## Validation Result

The read-only API contract validator passed with zero blocking failures and
zero warnings.

## Remaining Gaps Before Phase 6.4

- Define a static prototype boundary using contract fixtures only.
- Preserve warning and data-quality visibility.
- Keep customer-facing rendering blocked.
- Do not introduce a server, endpoint, connector, authentication flow, or
  execution control.
