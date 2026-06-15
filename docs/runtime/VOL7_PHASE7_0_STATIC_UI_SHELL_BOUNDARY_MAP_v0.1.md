# Vol.7 Phase 7.0 Static UI Shell Boundary Map v0.1

## 1. Phase Summary

Vol.7 Phase 7.0 converts the Vol.6 handoff and readiness gate into a static UI shell planning boundary. The phase defines how a future static fixture consumer may read existing cockpit and mock-consumer fixtures without creating runtime, trading, credential, customer-facing, API, or production risk.

This is a planning map only. It does not create UI code, API code, live data connections, execution controls, or customer-facing capability.

## 2. Allowed Static Consumer Scope

Allowed static consumer behavior:

- Read static JSON fixtures.
- Render read-only cockpit summaries.
- Display runtime status.
- Display active checkpoint.
- Display timeline count.
- Display warning count.
- Display active rule count.
- Display readiness state.
- Display operating mode.
- Display portfolio mode.
- Display LDD scope reminder.
- Display fixture timestamp and source metadata.
- Display stale-data warnings.
- Display "not executable" labels.
- Display "fixture only" labels.

## 3. Forbidden Scope

Forbidden scope:

- Runtime mutation.
- Order execution.
- Broker/Binance integration.
- Live market-data fetch.
- API server.
- Credential storage.
- Credential input field.
- Login/auth system.
- Real alert dispatch.
- Scheduler.
- Production deployment.
- Customer-facing feature flag.
- Portfolio-edit form.
- Trade button.
- Mutation endpoint.
- Webhook receiver.
- Background process.

## 4. Allowed Panels

Initial allowed read-only panels:

- Runtime Status Panel.
- Readiness Gate Panel.
- Active Rules Panel.
- Timeline Health Panel.
- Static Fixture Source Panel.
- LDD Scope Reminder Panel.
- Forbidden Actions Panel.
- Stale Data Warning Panel.

Every allowed panel must be fixture-only, read-only, non-executable, and visibly labeled as static planning data.

## 5. Forbidden UI Affordances

Forbidden UI affordances:

- Buy button.
- Sell button.
- Rebalance button.
- Sync broker button.
- Sync Binance button.
- Connect account button.
- API key input.
- Credential form.
- Live refresh button.
- Auto-trade toggle.
- Runtime edit form.
- Rule mutation editor.
- Alert dispatch toggle.
- Production publish button.

## 6. Fixture Contract

The minimum static UI shell boundary map fixture fields are:

- `phase`
- `baseline_commit`
- `origin_status`
- `working_tree_status`
- `active_checkpoint`
- `latest_timeline_event`
- `runtime_records_count`
- `timeline_event_count`
- `timeline_warning_count`
- `active_rules_count`
- `customer_facing_readiness`
- `operating_mode`
- `portfolio_mode`
- `allowed_panels`
- `forbidden_actions`
- `forbidden_integrations`
- `fixture_only`
- `read_only`
- `mutation_allowed`
- `execution_allowed`
- `credential_handling_allowed`
- `live_data_allowed`
- `ldd_scope_reminder`

The fixture exists to guide static shell planning. It is not a runtime source of truth and must not override `cockpit/ldd/view_model.json`.

## 7. Validation Rules

Validation rules:

- `fixture_only` must be true.
- `read_only` must be true.
- `mutation_allowed` must be false.
- `execution_allowed` must be false.
- `credential_handling_allowed` must be false.
- `live_data_allowed` must be false.
- `customer_facing_readiness` must be false.
- All forbidden actions must remain disabled.
- All allowed panels must be read-only.
- LDD scope must explicitly say the entire U.S. equity market, not only existing or former positions.

## 8. Handoff to Phase 7.1

Recommended next phase:

`Vol.7 Phase 7.1 - Static Fixture Consumer Contract and Read-Only Panel Layout`

Phase 7.1 should remain static-only. It may define fixture-to-panel contracts and read-only panel layout rules, but it must not implement a production UI, customer-facing UI, API server, live endpoint, broker/Binance connection, live market data, trading automation, credential handling, runtime mutation UI, or execution trigger.
