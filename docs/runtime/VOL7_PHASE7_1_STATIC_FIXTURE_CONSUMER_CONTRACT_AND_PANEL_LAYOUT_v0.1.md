# Vol.7 Phase 7.1 Static Fixture Consumer Contract and Read-Only Panel Layout v0.1

## 1. Phase Summary

Vol.7 Phase 7.1 converts the Phase 7.0 static UI shell boundary map into a specific static fixture consumer contract and read-only panel layout. It defines which existing fixtures may be read, what normalized static view model a future shell should expect, which panels are allowed, which fields each panel may display, and which labels must prevent confusion.

This phase does not create UI implementation. It only defines the contract and layout.

## 2. Static Fixture Consumer Contract

Allowed input fixtures:

- `cockpit/ldd/latest_state.json`
- `cockpit/ldd/runtime_timeline.json`
- `cockpit/ldd/view_model.json`
- `mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json`
- `mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json`
- `mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json`

If a future static consumer cannot read one of these files, it must fail closed in static planning mode. It must not fetch live data, connect an API, mutate a runtime record, or silently infer missing fields.

## 3. Normalized Static View Model

The normalized static view model contains:

- `metadata`
- `baseline`
- `runtime_status`
- `readiness`
- `timeline_health`
- `active_rules_summary`
- `strategy_state_summary`
- `allowed_panels`
- `forbidden_actions`
- `forbidden_integrations`
- `scope_reminders`
- `stale_data_warnings`
- `fixture_labels`
- `read_only_guards`

Minimum required top-level flags:

- `fixture_only: true`
- `read_only: true`
- `mutation_allowed: false`
- `execution_allowed: false`
- `credential_handling_allowed: false`
- `live_data_allowed: false`
- `customer_facing_readiness: false`

## 4. Read-Only Panel Layout

Initial panels:

1. Runtime Status Panel
2. Readiness Gate Panel
3. Timeline Health Panel
4. Active Rules Panel
5. Strategy States Panel
6. Static Fixture Source Panel
7. LDD Scope Reminder Panel
8. Stale Data Warning Panel
9. Forbidden Actions Panel
10. Non-Executable Guardrail Panel

Each panel defines:

- `panel_id`
- `title`
- `purpose`
- `source_fixtures`
- `display_fields`
- `required_labels`
- `read_only`
- `mutation_allowed`
- `execution_allowed`
- `credential_handling_allowed`
- `live_data_allowed`
- `forbidden_affordances`

Panels are specifications only. They are not components, pages, routes, or UI implementation files.

## 5. Required Labels

Every future static shell must clearly show:

- `STATIC FIXTURE`
- `READ ONLY`
- `NOT EXECUTABLE`
- `NO LIVE DATA`
- `NO BROKER CONNECTION`
- `NO BINANCE CONNECTION`
- `NO CREDENTIAL HANDLING`
- `NO RUNTIME MUTATION`
- `CUSTOMER-FACING READINESS: FALSE`

## 6. Forbidden UI Affordances

Forbidden affordances:

- Buy button
- Sell button
- Rebalance button
- Connect broker button
- Connect Binance button
- Sync broker button
- Sync Binance button
- Live refresh button
- API key input
- Credential form
- Login/auth form
- Auto-trade toggle
- Runtime edit form
- Rule mutation editor
- Portfolio edit form
- Alert dispatch toggle
- Scheduler toggle
- Background worker trigger
- Production publish button
- Customer-facing publish flag

## 7. LDD Full-Market Scope

The static consumer must include this scope reminder:

`LDD scope is the entire U.S. equity market, not only existing or former positions.`

This reminder must appear in both the static fixture consumer contract and the read-only panel layout.

## 8. Validation Rules

The validator must confirm:

- Required files exist.
- Fixture contract conforms to schema.
- Panel layout conforms to schema.
- Normalized view model example conforms to the required static-only flags.
- `fixture_only` is true.
- `read_only` is true.
- `mutation_allowed` is false.
- `execution_allowed` is false.
- `credential_handling_allowed` is false.
- `live_data_allowed` is false.
- `customer_facing_readiness` is false.
- All panels are read-only.
- No panel allows mutation.
- No panel allows execution.
- No panel allows credential handling.
- No panel allows live data.
- Forbidden affordances are represented.
- LDD full-market scope reminder exists.
- No production UI files were created.
- No frontend app files were created.
- No API server files were created.

## 9. Phase 7.1 Exit Criteria

Phase 7.1 is complete only if:

- All required files are created.
- Schemas validate.
- Static contract fixture validates.
- Read-only panel layout fixture validates.
- Normalized view model example validates.
- Runtime record count increments by 1.
- Timeline warning count remains 0.
- Customer-facing readiness remains false.
- No forbidden implementation is introduced.

## 10. Handoff to Phase 7.2

Next recommended phase:

`Vol.7 Phase 7.2 - Static Fixture Consumer Dry-Run and Drift Detector`

Phase 7.2 should test whether the static fixture consumer contract can be dry-run validated against existing fixtures without creating any UI implementation or live integration.
