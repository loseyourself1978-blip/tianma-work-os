# Vol.6 Phase 6.1 UI Boundary Architecture v0.1

## 1. Purpose

Vol.6 Phase 6.1 defines the read-only boundary between the LDD Cockpit data
layer and any future interface.

The primary consumer artifact remains:

```text
cockpit/ldd/view_model.json
```

Raw records under `records/ldd/` remain audit and debugging inputs. A future
interface must not reconstruct current state from raw records.

## 2. Data Readiness Is Not UI Readiness

Cockpit data readiness means that the view model is generated, validated,
source-traceable, and internally consistent.

UI readiness additionally requires:

- a defined consumer surface;
- field-level visibility policy;
- warning and stale-state behavior;
- privacy masking;
- role permissions;
- accessibility and rendering specifications;
- explicit prohibition of execution behavior.

The current cockpit data is ready for approved internal read-only consumers.
It is not ready for customer-facing rendering.

## 3. Allowed UI Surfaces

The following conceptual surfaces are allowed:

- `internal_operator_cockpit`: internal read-only operational review.
- `ai_board_review`: role-based analysis and review without execution.
- `audit_debug_view`: source tracing and validation for approved maintainers.

Allowed does not mean implemented. No interface is created by this phase.

## 4. Blocked UI Surfaces

The following surfaces remain blocked:

- `public_demo_view`: blocked until deterministic masking and demo-data policy
  exist.
- `customer_facing_view_blocked`: blocked until permission, privacy, masking,
  disclosure, and customer safety policies exist.

Order tickets, trade controls, credential forms, live quote streams, account
connection dialogs, and runtime record editors are prohibited surfaces.

## 5. Field Classification Model

| Class | Meaning |
|---|---|
| `public_safe` | Generic product concepts and non-sensitive state vocabulary |
| `internal_read_only` | Internal operational context that approved roles may inspect |
| `sensitive_account_value` | Account values, quantities, P/L, and screenshot-derived financial data |
| `execution_sensitive` | Thresholds, executable quote context, pending instructions, and execution evidence |
| `audit_only` | Source paths, record identifiers, validation details, and reconciliation evidence |
| `never_expose` | Credentials, secrets, exact account identifiers, and raw personal identifiers |

## 6. Rendering Rules

### Public Safe

- May be rendered after content review.
- Must not imply live data or a customer account connection.

### Internal Read-Only

- Render only to approved internal roles.
- Keep source checkpoint and data-quality context visible.
- Do not provide mutation controls.

### Sensitive Account Value

- Require explicit permission.
- Mask or aggregate outside approved internal contexts.
- Do not combine account sections or P/L scopes.

### Execution Sensitive

- Render as restricted read-only guidance.
- Label rules as non-automated.
- Never attach submit, buy, sell, cancel, or execution controls.

### Audit Only

- Restrict to approved audit and debugging roles.
- Preserve exact source references and validation context.
- Do not expose in public or customer-facing surfaces.

### Never Expose

- Reject before rendering.
- Do not log, cache, transmit, or place in consumer payloads.

## 7. Warning And Stale-State Policy

- Non-empty warnings must remain visible.
- `stale`, `superseded`, `unknown`, and `blocked` states must retain their
  labels.
- Consumers must not normalize stale or unknown data into current state.
- Missing optional data must render as unavailable, not as zero.
- Missing required data blocks the affected surface.
- The latest checkpoint must be displayed with any current-state view.

## 8. Quote-Type Display Policy

Any displayed price must retain its quote context where available:

- close price;
- after-hours price;
- broker holding valuation;
- executable quote;
- active-position valuation.

Static or screenshot-derived values must not be presented as live or
execution-valid prices. An untagged or conflicting quote must display a
data-quality warning.

## 9. Execution-Sensitive Rule Policy

Active rules are monitoring and decision-support records. They are not
automated order instructions.

A rule display must:

- show rule status and source checkpoint;
- distinguish watch, risk-line, prohibition, and executed states;
- preserve quote and execution-validity context;
- show no-reentry restrictions;
- separate rule compliance from price outcome;
- provide no execution control or live order path.

## 10. Customer-Facing Block Conditions

Customer-facing rendering remains blocked while any of these are absent:

- role and permission matrix;
- field-level masking policy;
- customer disclosure policy;
- authentication and authorization boundary;
- account identifier masking;
- P/L and position disclosure rules;
- execution-sensitive field suppression;
- warning and stale-state rendering guarantees;
- privacy review and approval.

## 11. Static Contracts

- `mock_consumers/ldd/ui_boundary_surface_map.json`
- `mock_consumers/ldd/ui_visibility_matrix.json`
- `mock_consumers/ldd/ui_boundary_contract.json`
- `mock_consumers/ldd/ui_state_taxonomy.json`

These files are specifications and fixtures only. They are not frontend code.

## 12. Validation

Run:

```bash
bash scripts/validate_ui_boundary_contract.sh
```

The validator confirms:

- JSON artifacts load successfully;
- every consumer surface is explicitly `allowed` or `blocked`;
- every field class has a rendering policy;
- `customer_facing_view_blocked` remains blocked;
- the view model remains the source artifact;
- prohibited execution and connection capabilities remain absent;
- validation does not mutate source artifacts.

## 13. Phase 6.2 Dependency

Phase 6.2 must define the Permission and Privacy Masking Model before any
customer-facing interface work begins.

Required Phase 6.2 outputs include:

- role definitions;
- field-class-to-role permissions;
- deterministic masking rules;
- audit access policy;
- customer disclosure policy;
- deny-by-default behavior for unmapped fields.

## 14. Non-Goals

- No frontend application.
- No customer-facing UI.
- No API server or live endpoint.
- No external, broker, Binance, or live market-data connection.
- No trading automation.
- No runtime or trading fact changes.
