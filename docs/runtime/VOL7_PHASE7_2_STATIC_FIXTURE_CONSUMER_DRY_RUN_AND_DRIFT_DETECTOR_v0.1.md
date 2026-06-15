# Vol.7 Phase 7.2 Static Fixture Consumer Dry-Run and Drift Detector v0.1

## 1. Phase Summary

Vol.7 Phase 7.2 validates the static consumer chain through a dry-run and drift detector. It checks whether the Phase 7.1 static fixture consumer contract can safely consume existing static fixtures according to the Phase 7.0 static UI shell boundary map and the current cockpit artifacts.

This phase does not create a UI implementation. It only checks whether the existing static fixtures can be safely consumed according to the Phase 7.0 and Phase 7.1 contracts.

## 2. Dry-Run Definition

A dry-run means:

- Loading allowed static fixture files.
- Checking required fields.
- Checking read-only flags.
- Resolving allowed panels.
- Checking panel source fixtures.
- Checking required safety labels.
- Checking forbidden actions.
- Checking forbidden integrations.
- Producing a static dry-run result JSON.
- Producing a drift report JSON.

No UI rendering is allowed. No HTML/CSS/JS output is allowed. No network access is allowed. No mutation is allowed.

## 3. Drift Detector Definition

Drift is any mismatch between:

- Phase 7.0 static UI shell boundary map.
- Phase 7.1 static fixture consumer contract.
- Phase 7.1 read-only panel layout.
- Phase 7.1 normalized static view model example.
- Current cockpit static fixtures.
- Current runtime timeline metadata.
- Current latest state metadata.

Drift categories:

- `baseline_drift`
- `count_drift`
- `flag_drift`
- `panel_drift`
- `forbidden_action_drift`
- `forbidden_integration_drift`
- `scope_reminder_drift`
- `read_only_guard_drift`
- `customer_readiness_drift`
- `fixture_source_drift`

## 4. Required Static Flags

The dry-run verifies:

- `fixture_only: true`
- `read_only: true`
- `mutation_allowed: false`
- `execution_allowed: false`
- `credential_handling_allowed: false`
- `live_data_allowed: false`
- `customer_facing_readiness: false`

These flags must appear consistently in the boundary map, consumer contract, panel layout, normalized view model example, dry-run result, and drift report.

## 5. Required Safety Labels

The dry-run verifies that these labels are represented:

- `STATIC FIXTURE`
- `READ ONLY`
- `NOT EXECUTABLE`
- `NO LIVE DATA`
- `NO BROKER CONNECTION`
- `NO BINANCE CONNECTION`
- `NO CREDENTIAL HANDLING`
- `NO RUNTIME MUTATION`
- `CUSTOMER-FACING READINESS: FALSE`

## 6. Forbidden Actions and Integrations

Forbidden actions:

- Buy button.
- Sell button.
- Rebalance button.
- Connect broker button.
- Connect Binance button.
- Sync broker button.
- Sync Binance button.
- Live refresh button.
- API key input.
- Credential form.
- Login/auth form.
- Auto-trade toggle.
- Runtime edit form.
- Rule mutation editor.
- Portfolio edit form.
- Alert dispatch toggle.
- Scheduler toggle.
- Background worker trigger.
- Production publish button.
- Customer-facing publish flag.

Forbidden integrations:

- Broker integration.
- Binance integration.
- Live market data integration.
- API server.
- Live endpoint.
- Credential handling.
- Trading execution.
- Order placement.
- Portfolio mutation.
- Background worker.
- Scheduler.
- Notification dispatcher.
- Customer-facing deployment.

## 7. LDD Full-Market Scope Guard

The dry-run and drift detector verify this exact scope principle:

`LDD scope is the entire U.S. equity market, not only existing or former positions.`

This appears in the boundary map, consumer contract, panel layout, normalized view model example, dry-run result, and drift report.

## 8. Dry-Run Result Requirements

The dry-run result fixture includes:

- `phase`
- `baseline_commit`
- `dry_run_timestamp`
- `input_fixtures_checked`
- `input_fixture_count`
- `all_required_fixtures_present`
- `all_required_fields_present`
- `all_static_flags_valid`
- `all_panels_read_only`
- `all_forbidden_actions_disabled`
- `all_forbidden_integrations_absent`
- `ldd_scope_reminder_present`
- `customer_facing_readiness`
- `dry_run_status`
- `warnings`
- `errors`
- `fixture_only`
- `read_only`
- `mutation_allowed`
- `execution_allowed`
- `credential_handling_allowed`
- `live_data_allowed`

Expected dry-run status: `passed`.

Expected warnings: empty array.

Expected errors: empty array.

## 9. Drift Report Requirements

The drift report fixture includes:

- `phase`
- `baseline_commit`
- `drift_check_timestamp`
- `drift_status`
- `drift_categories_checked`
- `drift_findings`
- `critical_drift_count`
- `warning_drift_count`
- `info_drift_count`
- `scope_reminder_valid`
- `read_only_guards_valid`
- `customer_facing_readiness`
- `fixture_only`
- `read_only`
- `mutation_allowed`
- `execution_allowed`
- `credential_handling_allowed`
- `live_data_allowed`

Expected drift status: `no_drift_detected`.

Expected critical drift count: `0`.

Expected warning drift count: `0`.

## 10. Validator Requirements

The validator must:

- Load all allowed input fixtures.
- Validate dry-run result against schema.
- Validate drift report against schema.
- Verify all required static flags.
- Verify all required safety labels.
- Verify all forbidden actions are disabled or absent.
- Verify all forbidden integrations are absent.
- Verify all allowed panels are read-only.
- Verify no panel allows mutation, execution, credential handling, or live data.
- Verify customer-facing readiness remains false.
- Verify the LDD full-market scope reminder exists.
- Verify no frontend app files were created.
- Verify no HTML/CSS/JS UI files were created.
- Verify no API server files were created.
- Verify no live endpoint files were created.
- Verify no credential files were created.
- Verify no broker/Binance integration files were created.
- Verify no scheduler or background worker files were created.

## 11. Phase 7.2 Exit Criteria

Phase 7.2 is complete only if:

- All required files are created.
- Dry-run result schema validates.
- Drift report schema validates.
- Validator passes.
- Runtime record count increments from 101 to 102.
- Timeline events increment from 101 to 102.
- Timeline warnings remain 0.
- Customer-facing readiness remains false.
- Dry-run status is `passed`.
- Drift status is `no_drift_detected`.
- No forbidden implementation is introduced.

## 12. Handoff to Phase 7.3

Next recommended phase:

`Vol.7 Phase 7.3 - Static Shell Implementation Readiness Gate`

Phase 7.3 should decide whether the repository is ready to allow a strictly static local UI shell implementation in a later phase. Phase 7.3 must still not create the UI implementation itself unless explicitly approved in a later phase.
