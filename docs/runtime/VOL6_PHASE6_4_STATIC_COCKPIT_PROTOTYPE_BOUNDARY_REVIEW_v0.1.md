# Vol.6 Phase 6.4 Static Cockpit Prototype Boundary Review v0.1

## 1. Purpose

Phase 6.4 defines the static boundary for a future LDD Cockpit prototype without implementing a prototype. It describes which cockpit surfaces, cards, read-only interactions, blocked controls, warning banners, source-traceability fields, and customer-facing blocked-state messages a future implementation may reference.

This package keeps `cockpit/ldd/view_model.json` as the primary read-only consumer artifact. Raw runtime records remain audit and debug inputs only.

## 2. Relationship to Phase 6.1 UI Boundary

Phase 6.1 established that cockpit data readiness is not the same as UI readiness. Phase 6.4 applies that boundary to a static prototype vocabulary: surfaces, cards, interactions, and blocked controls are specified as contracts only.

The Phase 6.1 rule still holds: customer-facing views remain blocked until permission, masking, privacy, and governance criteria are satisfied.

## 3. Relationship to Phase 6.2 Permission and Privacy Masking

Phase 6.2 defines deny-by-default access, role taxonomy, field classes, and masking policy. Phase 6.4 maps those decisions into display-level rules:

- public-safe fields may appear only in reviewed demo contexts.
- internal-read-only fields may appear in internal static cockpit specs.
- sensitive account values require masking or omission unless viewed by authorized internal roles.
- execution-sensitive fields must be non-interactive.
- audit-only fields remain restricted to audit/debug surfaces.
- never-expose fields must be rejected before render.

## 4. Relationship to Phase 6.3 Read-only API Contract

Phase 6.3 defined contract-only read endpoints and response envelopes without creating a server. Phase 6.4 treats those endpoint contracts as future data-source references for static cards, not as runnable routes.

No HTTP listener, route handler, controller, API server, or live endpoint is created in this phase.

## 5. Relationship to Phase 6.3a Active Checkpoint Update

Phase 6.3a promoted the latest active checkpoint to `2026-06-11T08:10:00+08:00` after confirmed execution reconciliation. Phase 6.4 uses that checkpoint as the static prototype source checkpoint.

The earlier Phase 6.2a premarket governance evidence remains non-promoted and non-executing. Static cockpit surfaces may show it only as labeled governance evidence, never as an active checkpoint overwrite.

## 6. Static Prototype Boundary Scope

The scope is limited to static Markdown and JSON contracts plus a validator. It defines:

- surface map
- card catalog
- allowed read-only interactions
- blocked controls
- warning, data-quality, quote-type, source-of-truth, and checkpoint display policies
- validation expectations

It does not render any UI.

## 7. Allowed Static Cockpit Surfaces

Allowed static surfaces are contract-only:

- `internal_operator_cockpit_static`
- `ai_board_review_static`
- `audit_debug_static`

These surfaces may be described for future internal review. They are not implemented, not customer-facing, and not connected to live data.

## 8. Blocked Customer-facing Surfaces

The following surfaces remain blocked:

- `public_demo_static_blocked`
- `customer_facing_static_blocked`

Customer-facing display remains blocked because no production permission system, privacy masking runtime, user/role enforcement, customer copy review, or customer-facing governance approval exists.

## 9. Static Card Catalog

The card catalog defines static specifications for:

- account snapshot
- cash defense ratio
- active positions
- closed positions
- active rules
- execution ledger
- strategy state
- warning and data quality
- source traceability
- checkpoint status
- non-promoted evidence
- customer-facing blocked status

Cards are not UI components. They are JSON contract entries that describe what a future renderer may show after permission and masking enforcement.

## 10. Allowed Read-only Interactions

Allowed interactions are static and read-only:

- read static snapshot
- expand or collapse card details
- filter or sort static tables
- switch read-only surfaces
- inspect source traceability
- inspect data-quality warnings
- inspect checkpoint status
- inspect non-promoted evidence banners

No interaction may mutate runtime data, execute a trade, collect credentials, connect to APIs, or suppress warnings.

## 11. Blocked Controls and Forbidden UI Actions

The blocked control catalog explicitly forbids:

- buy, sell, modify, cancel, and execute trade buttons
- bot start/stop and grid reopen controls
- broker, Binance, or external market-data connection controls
- live price refresh controls
- checkpoint promotion controls
- runtime record editing controls
- warning suppression and data-quality hiding controls
- sensitive-value reveal controls
- customer-facing enablement controls

These controls are blocked for every role.

## 12. Data Quality, Warning, and Source Traceability Display

Future static cockpit specifications must display:

- active checkpoint timestamp
- source priority
- quote type
- source of truth
- warnings
- timeline warning count
- stale checkpoint evidence
- non-promoted governance evidence
- execution reconciliation status
- customer-facing blocked status
- permission and masking profile
- data freshness label

Warnings, source of truth, quote type, and customer-facing blocked status may not be hidden.

## 13. Active Checkpoint and Evidence Display Policy

The active checkpoint is `2026-06-11T08:10:00+08:00`.

Non-promoted governance evidence must be displayed as non-promoted evidence with a banner or label. It must not silently overwrite active checkpoint values. If a future cockpit shows active checkpoint values alongside newer non-promoted evidence, it must make the distinction visible.

## 14. Permission and Masking Display Policy

Every surface and card must declare a masking profile and field classes used. Cards using sensitive account values must declare masking requirements. Execution-sensitive cards must be non-interactive. Never-expose field classes are not allowed in any static card.

Customer-facing cards remain blocked except for a blocked-status explanation.

## 15. No-implementation Boundary

This phase creates no runnable UI and no API. It creates no HTML, CSS, JavaScript, React, Vue, Next.js, Svelte, frontend routing, UI components, server code, API endpoints, route handlers, controllers, server daemons, HTTP listeners, broker connectors, Binance connectors, external data connectors, credential stores, or automation triggers.

## 16. Explicit Non-goals

- No frontend app.
- No customer-facing UI.
- No HTML/CSS/JS UI files.
- No React/Vue/Next/Svelte app or components.
- No API server.
- No live endpoint.
- No external API connection.
- No broker/Binance API connection.
- No live market data.
- No trading automation.
- No authentication implementation.
- No credential, token, password, account-number, or live identifier handling.
- No order placement, cancellation, execution, bot control, or runtime mutation capability.
- No mutation of prior runtime records.
- No GitHub Issues.
- No GitHub Projects board.

## 17. Validation Strategy

The static prototype boundary validator checks:

- required files and schemas exist
- JSON syntax is valid
- all required surfaces, cards, interactions, blocked controls, and display policy items exist
- all surfaces are contract-only and customer-facing disabled
- all cards are static specs with mutation and execution disabled
- execution-sensitive cards are non-interactive
- all allowed interactions are read-only
- all blocked controls are blocked for every role
- warning, source-of-truth, quote-type, customer-facing blocked status, and active checkpoint display are required
- no Phase 6.4 artifact appears to implement a frontend app, API server, live endpoint, connector, credential store, trading executor, or automation trigger

## 18. Phase 6.5 Entry Criteria

Phase 6.5 may start only if:

- active checkpoint remains `2026-06-11T08:10:00+08:00`
- timeline warnings remain `0`
- customer-facing readiness remains `false`
- static cockpit prototype boundary validation passes
- read-only API contract validation still passes
- permission and masking validation still passes
- future work remains static spec or internal-only until explicit UI implementation approval is given

Recommended next phase:

`Vol.6 Phase 6.5 - Internal Operator Cockpit Static Spec`
