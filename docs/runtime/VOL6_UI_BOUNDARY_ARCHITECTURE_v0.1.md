# Vol.6 UI Boundary Architecture v0.1

## 1. Purpose

Vol.6 Phase 6.1 defines the read-only Cockpit UI boundary before any
customer-facing interface exists.

The boundary specifies what a future interface may read, how it may organize
the data, which states it may display, and which capabilities remain
prohibited.

This phase creates contracts only. It does not create a frontend application,
rendered interface, API server, live endpoint, external connection, or
execution path.

## 2. Source Contract

The primary consumer artifact is:

```text
cockpit/ldd/view_model.json
```

The UI boundary must not reconstruct current state from `records/ldd/**`.
Raw records remain audit and debugging inputs.

The active runtime anchor remains:

```text
2026-06-10T08:49:00+08:00
```

## 3. Boundary Artifacts

- `mock_consumers/ldd/ui_boundary_contract.json`
- `mock_consumers/ldd/ui_field_visibility_matrix.json`
- `mock_consumers/ldd/ui_surface_map.json`
- `mock_consumers/ldd/ui_state_taxonomy.json`
- `scripts/validate_ui_boundary_contract.py`
- `scripts/validate_ui_boundary_contract.sh`

These are static specifications. They are not UI code.

## 4. Design Principles

- Read the generated view model first.
- Keep the interface read-only.
- Preserve checkpoint, source, warning, and data-quality context.
- Separate active, closed, historical, prohibited, and unknown states.
- Separate rule guidance from execution.
- Keep quote type and execution validity visible when price-related state is
  shown.
- Keep account sections and P/L scopes separate.
- Apply field visibility before customer-facing rendering.
- Never render credentials, tokens, account numbers, or personal identifiers.
- Do not imply live data, live refresh, or order connectivity.

## 5. UI Surface Map

The future cockpit may contain these conceptual surfaces:

| Surface | View-model source | Purpose |
|---|---|---|
| Header status | `meta`, `checkpoint`, `portfolio_mode` | Show identity, checkpoint, and operating posture |
| Data-quality banner | `warnings`, `data_quality` | Keep limitations and warnings visible |
| Account overview | `account_overview` | Show high-level section summaries |
| Account sections | `account_sections` | Separate U.S., Hong Kong, crypto, cash, and stablecoin state |
| Active positions | `positions` | Show current open positions only |
| Closed positions | `closed_positions` | Show closed, historical, and no-reentry state |
| Risk summary | `risk_summary` | Show current watches and concentration risks |
| Active rules | `active_rules` | Show monitored conditions without execution controls |
| Strategy states | `strategy_states` | Show current strategy posture and next review |
| Timeline | `timeline` | Show chronological audit history, not a live feed |
| Pending commands | `pending_commands` | Show command status without execution controls |
| Memory checkpoint | `memory_checkpoint` | Show current memory and retention context |
| Source trace | `source_files` fields | Support audit and debugging |

No surface may submit, mutate, acknowledge, cancel, or execute an order.

## 6. Field Visibility Matrix

Phase 6.1 defines five field classes:

### Public-Safe

Generic product concepts, version labels, generic state names, and generic
portfolio-mode examples. These may become externally visible after copy and
privacy review.

### Internal-Only

Detailed account values, quantities, P/L values, internal rules, source paths,
and operational notes. These remain available only to approved internal roles.

### Sensitive Account

Screenshot-derived financial values, account identifiers, broker or Binance
identifiers, and source evidence. These require masking and explicit
permission.

### Execution-Sensitive

Thresholds, executable quote context, pending order content, and action
boundaries. These are read-only restricted context and must never become
interactive execution controls.

### Never Expose

API keys, tokens, passwords, login credentials, exact account numbers, raw
personal identifiers, and secrets. These fields are prohibited from all
consumer payloads and surfaces.

## 7. UI State Taxonomy

### Data States

- `current`
- `stale`
- `superseded`
- `unknown`
- `warning`
- `blocked`

### Position States

- `active_position`
- `core_position`
- `watch_position`
- `risk_valve`
- `residual_watch_position`
- `closed_position`
- `historical_position`
- `prohibited_reentry`
- `unknown`

### Rule States

- `active`
- `near_trigger`
- `triggered`
- `awaiting_execution_confirmation`
- `executed`
- `stale`
- `superseded`
- `historical`
- `prohibited`

### Strategy States

- `active`
- `monitoring`
- `closed`
- `superseded`
- `historical`
- `waiting_for_trigger`
- `not_opened`
- `unknown`

### Interaction States

- `read_only`
- `filterable`
- `sortable`
- `expandable`
- `source_traceable`
- `disabled`
- `unavailable`

There is no `execute`, `submit`, `trade`, `buy`, or `sell` interaction state.

## 8. Allowed Interactions

- Filter a local list.
- Sort a local list.
- Expand or collapse details.
- Select a timeline range.
- Inspect source references.
- Display warning and data-quality detail.
- Switch between approved read-only account sections.

Allowed interactions must not modify runtime files or external state.

## 9. Prohibited Interactions

- Submit, place, cancel, or amend an order.
- Buy, sell, reduce, add, or close a position.
- Connect to broker, Binance, or market-data services.
- Enter or store credentials.
- Hide warnings or data-quality limitations.
- Promote static prices to live or executable prices.
- Reconstruct current state from raw records.
- Write back to runtime records.
- Mutate command or execution status.

## 10. Warning And Data-Quality Behavior

- Non-empty warnings must remain visible.
- Unknown or stale state must not be silently normalized into current state.
- Quote type must accompany price-related rendering.
- Execution-sensitive rules must show that they are guidance, not automation.
- Missing optional fields may use an explicit unavailable state.
- Missing required fields block the consumer boundary validation.

## 11. Permission And Privacy Boundary

Phase 6.1 does not implement permissions. It defines the point where permission
and masking decisions must be applied.

Before customer-facing work:

- roles must be defined;
- field classes must map to role permissions;
- masking rules must be deterministic;
- source evidence visibility must be controlled;
- account and P/L disclosure must require explicit policy;
- never-expose fields must be rejected before rendering.

Customer-facing readiness remains false.

## 12. Validation

Run:

```bash
bash scripts/validate_ui_boundary_contract.sh
```

The validator checks:

- checkpoint and view-model source integrity;
- required boundary artifacts;
- approved view-model sections only;
- visibility-class completeness;
- required state vocabularies;
- read-only interaction rules;
- absence of live-service and execution capabilities;
- customer-facing readiness remains false;
- no raw-record reconstruction;
- no credential-bearing fields.

A blocking failure returns a non-zero exit code.

## 13. Known Gaps

- No permission model.
- No role matrix.
- No masking engine.
- No customer-facing disclosure policy.
- No UI component contract.
- No responsive or accessibility specification.
- No API resource contract.
- No authentication or authorization contract.
- No live update or subscription boundary.

## 14. Recommended Next Phase

```text
Vol.6 Phase 6.2 - Permission and Privacy Masking Model
```

Phase 6.2 should map the field visibility classes to explicit roles, masking
rules, and deny-by-default behavior before any customer-facing interface or
read-only API implementation.
