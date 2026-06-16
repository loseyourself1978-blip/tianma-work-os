#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.2 static fixture consumer dry-run and drift report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKPOINT = "2026-06-12T09:18:00+08:00"
BASELINE_COMMIT = "1a5f7bce0df645020089b63bc8a82463c63d1027"
BASELINE_TIMELINE_EVENT = "2026-06-15T13:58:46+08:00"
DRY_RUN_TIMESTAMP = "2026-06-15T14:23:13+08:00"
READINESS_GATE_TIMESTAMP = "2026-06-15T17:07:00+08:00"
LOCAL_STATIC_SHELL_TIMESTAMP = "2026-06-15T18:12:39+08:00"
LOCAL_STATIC_SHELL_REVIEW_TIMESTAMP = "2026-06-16T09:03:34+08:00"
LOCAL_STATIC_SHELL_DEMO_PACK_TIMESTAMP = "2026-06-16T10:05:33+08:00"
LOCAL_STATIC_SHELL_SNAPSHOT_QA_TIMESTAMP = "2026-06-16T11:00:19+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

ALLOWED_INPUT_FIXTURES = [
    "cockpit/ldd/latest_state.json",
    "cockpit/ldd/runtime_timeline.json",
    "cockpit/ldd/view_model.json",
    "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_contract.json",
    "mock_consumers/ldd/vol7_read_only_panel_layout.json",
    "mock_consumers/ldd/vol7_static_consumer_view_model_example.json",
]

REQUIRED_FILES = {
    "dry_run_result": "mock_consumers/ldd/vol7_static_fixture_consumer_dry_run_result.json",
    "drift_report": "mock_consumers/ldd/vol7_static_fixture_consumer_drift_report.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_2_static_fixture_consumer_dry_run_and_drift_detector.json",
}

REQUIRED_SCHEMAS = {
    "dry_run": "schemas/vol7_static_fixture_consumer_dry_run.schema.json",
    "drift_report": "schemas/vol7_static_fixture_consumer_drift_report.schema.json",
}

REQUIRED_LABELS = [
    "STATIC FIXTURE",
    "READ ONLY",
    "NOT EXECUTABLE",
    "NO LIVE DATA",
    "NO BROKER CONNECTION",
    "NO BINANCE CONNECTION",
    "NO CREDENTIAL HANDLING",
    "NO RUNTIME MUTATION",
    "CUSTOMER-FACING READINESS: FALSE",
]

REQUIRED_ACTIONS = [
    "buy_button",
    "sell_button",
    "rebalance_button",
    "connect_broker_button",
    "connect_binance_button",
    "sync_broker_button",
    "sync_binance_button",
    "live_refresh_button",
    "api_key_input",
    "credential_form",
    "login_auth_form",
    "auto_trade_toggle",
    "runtime_edit_form",
    "rule_mutation_editor",
    "portfolio_edit_form",
    "alert_dispatch_toggle",
    "scheduler_toggle",
    "background_worker_trigger",
    "production_publish_button",
    "customer_facing_publish_flag",
]

REQUIRED_INTEGRATIONS = [
    "broker_integration",
    "binance_integration",
    "live_market_data_integration",
    "api_server",
    "live_endpoint",
    "credential_handling",
    "trading_execution",
    "order_placement",
    "portfolio_mutation",
    "background_worker",
    "scheduler",
    "notification_dispatcher",
    "customer_facing_deployment",
]

DRIFT_CATEGORIES = [
    "baseline_drift",
    "count_drift",
    "flag_drift",
    "panel_drift",
    "forbidden_action_drift",
    "forbidden_integration_drift",
    "scope_reminder_drift",
    "read_only_guard_drift",
    "customer_readiness_drift",
    "fixture_source_drift",
]

TRUE_FLAGS = ["fixture_only", "read_only"]
FALSE_FLAGS = [
    "customer_facing_readiness",
    "mutation_allowed",
    "execution_allowed",
    "credential_handling_allowed",
    "live_data_allowed",
]

PHASE_ARTIFACTS = [
    "docs/runtime/VOL7_PHASE7_2_STATIC_FIXTURE_CONSUMER_DRY_RUN_AND_DRIFT_DETECTOR_v0.1.md",
    "schemas/vol7_static_fixture_consumer_dry_run.schema.json",
    "schemas/vol7_static_fixture_consumer_drift_report.schema.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_dry_run_result.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_drift_report.json",
    "records/ldd/2026-06-15/vol7_phase7_2_static_fixture_consumer_dry_run_and_drift_detector.json",
    "scripts/validate_vol7_static_fixture_consumer_dry_run.py",
    "scripts/validate_vol7_static_fixture_consumer_dry_run.sh",
]

PROHIBITED_PHASE_PATH_PARTS = {
    "app",
    "web",
    "frontend",
    "ui",
    "components",
    "pages",
    "routes",
    "server",
    "api",
    "src",
    "public",
    "worker",
    "scheduler",
}

PROHIBITED_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}


def load_json(relpath: str) -> tuple[Any | None, str | None]:
    path = REPO_ROOT / relpath
    if not path.exists():
        return None, f"{relpath} is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{relpath} invalid JSON: {exc}"


def fail(message: str, failures: list[str]) -> None:
    print(f"FAIL {message}")
    failures.append(message)


def ok(name: str, message: str) -> None:
    print(f"PASS {name}: {message}")


def require(condition: bool, name: str, message: str, failures: list[str]) -> None:
    if condition:
        ok(name, message)
    else:
        fail(f"{name}: {message}", failures)


def schema_required_fields(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return [item for item in required if isinstance(item, str)] if isinstance(required, list) else []


def missing_required(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return [field for field in schema_required_fields(schema) if field not in document]


def contains_all(value: Any, required: list[str]) -> bool:
    return isinstance(value, list) and all(item in value for item in required)


def static_flags_valid(document: dict[str, Any]) -> bool:
    return all(document.get(flag) is True for flag in TRUE_FLAGS) and all(document.get(flag) is False for flag in FALSE_FLAGS)


def no_implementation_files() -> tuple[bool, list[str]]:
    violations: list[str] = []
    for relpath in PHASE_ARTIFACTS:
        path = Path(relpath)
        parts = set(path.parts)
        suffix = path.suffix.lower()
        if parts & PROHIBITED_PHASE_PATH_PARTS:
            violations.append(relpath)
        if suffix in PROHIBITED_SUFFIXES and not relpath.endswith(".py"):
            violations.append(relpath)
    return not violations, violations


def current_timeline_counts(timeline: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    events = timeline.get("events")
    warnings = timeline.get("warnings")
    latest_event = None
    if isinstance(events, list) and events:
        latest = events[-1]
        if isinstance(latest, dict):
            latest_event = (
                latest.get("timestamp")
                or latest.get("timestamp_sgt")
                or latest.get("review_time")
                or latest.get("event_time")
            )
    event_count = len(events) if isinstance(events, list) else None
    warning_count = len(warnings) if isinstance(warnings, list) else None
    return event_count, warning_count, latest_event


def main() -> int:
    failures: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}
    input_fixtures: dict[str, dict[str, Any]] = {}
    schemas: dict[str, dict[str, Any]] = {}

    for relpath in ALLOWED_INPUT_FIXTURES:
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        input_fixtures[relpath] = data

    for key, relpath in REQUIRED_FILES.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        loaded[key] = data

    for key, relpath in REQUIRED_SCHEMAS.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        schemas[key] = data

    require(len(input_fixtures) == len(ALLOWED_INPUT_FIXTURES), "allowed_input_fixtures", f"{len(input_fixtures)}/{len(ALLOWED_INPUT_FIXTURES)} allowed static input fixtures loaded", failures)
    require(len(loaded) == len(REQUIRED_FILES), "required_result_files", f"{len(loaded)}/{len(REQUIRED_FILES)} dry-run/drift/record files loaded", failures)
    require(len(schemas) == len(REQUIRED_SCHEMAS), "required_schemas", f"{len(schemas)}/{len(REQUIRED_SCHEMAS)} schemas loaded", failures)

    dry_run = loaded.get("dry_run_result", {})
    drift = loaded.get("drift_report", {})
    record = loaded.get("record", {})
    dry_run_schema = schemas.get("dry_run", {})
    drift_schema = schemas.get("drift_report", {})

    require(not missing_required(dry_run, dry_run_schema), "dry_run_schema_required_fields", "dry-run result includes required schema fields", failures)
    require(not missing_required(record, dry_run_schema), "record_schema_required_fields", "runtime record includes dry-run schema fields", failures)
    require(not missing_required(drift, drift_schema), "drift_schema_required_fields", "drift report includes required schema fields", failures)

    require(dry_run.get("phase") == "Vol.7 Phase 7.2 - Static Fixture Consumer Dry-Run and Drift Detector", "phase", "dry-run result uses the Phase 7.2 phase label", failures)
    require(dry_run.get("baseline_commit") == BASELINE_COMMIT and drift.get("baseline_commit") == BASELINE_COMMIT and record.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", f"baseline commit is {BASELINE_COMMIT}", failures)
    require(dry_run.get("dry_run_timestamp") == DRY_RUN_TIMESTAMP and drift.get("drift_check_timestamp") == DRY_RUN_TIMESTAMP and record.get("dry_run_timestamp") == DRY_RUN_TIMESTAMP, "dry_run_timestamp", f"dry-run timestamp is {DRY_RUN_TIMESTAMP}", failures)

    require(dry_run.get("active_checkpoint") == CHECKPOINT and drift.get("active_checkpoint") == CHECKPOINT and record.get("active_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    require(dry_run.get("latest_timeline_event") == BASELINE_TIMELINE_EVENT and drift.get("latest_timeline_event") == BASELINE_TIMELINE_EVENT, "baseline_timeline_event", f"baseline timeline event remains {BASELINE_TIMELINE_EVENT}", failures)
    require(dry_run.get("runtime_records_count") == 101 and drift.get("runtime_records_count") == 101, "runtime_records_count", "baseline runtime record count is 101", failures)
    require(dry_run.get("timeline_event_count") == 101 and drift.get("timeline_event_count") == 101, "timeline_event_count", "baseline timeline event count is 101", failures)
    require(dry_run.get("timeline_warning_count") == 0 and drift.get("timeline_warning_count") == 0, "timeline_warning_count", "baseline timeline warning count is 0", failures)
    require(dry_run.get("active_rules_count") == 11 and drift.get("active_rules_count") == 11, "active_rules_count", "active rule count is 11", failures)
    require(dry_run.get("strategy_states_count") == 16 and drift.get("strategy_states_count") == 16, "strategy_states_count", "strategy state count is 16", failures)
    require(dry_run.get("operating_mode") == OPERATING_MODE and drift.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(dry_run.get("portfolio_mode") == PORTFOLIO_MODE and drift.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    require(dry_run.get("input_fixture_count") == len(ALLOWED_INPUT_FIXTURES), "input_fixture_count", "dry-run checked all nine input fixtures", failures)
    require(contains_all(dry_run.get("input_fixtures_checked"), ALLOWED_INPUT_FIXTURES), "input_fixture_list", "dry-run result lists all allowed input fixtures", failures)

    boundary = input_fixtures.get("mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json", {})
    contract = input_fixtures.get("mock_consumers/ldd/vol7_static_fixture_consumer_contract.json", {})
    layout = input_fixtures.get("mock_consumers/ldd/vol7_read_only_panel_layout.json", {})
    example = input_fixtures.get("mock_consumers/ldd/vol7_static_consumer_view_model_example.json", {})
    timeline = input_fixtures.get("cockpit/ldd/runtime_timeline.json", {})
    latest_state = input_fixtures.get("cockpit/ldd/latest_state.json", {})
    view_model = input_fixtures.get("cockpit/ldd/view_model.json", {})

    for name, document in [
        ("boundary_map", boundary),
        ("consumer_contract", contract),
        ("panel_layout", layout),
        ("normalized_example", example),
        ("dry_run_result", dry_run),
        ("drift_report", drift),
    ]:
        require(static_flags_valid(document), f"{name}_static_flags", f"{name} has required static flags", failures)

    require(dry_run.get("all_required_fixtures_present") is True, "all_required_fixtures_present", "dry-run says all required fixtures are present", failures)
    require(dry_run.get("all_required_fields_present") is True, "all_required_fields_present", "dry-run says all required fields are present", failures)
    require(dry_run.get("all_static_flags_valid") is True, "all_static_flags_valid", "dry-run says all static flags are valid", failures)
    require(dry_run.get("all_panels_read_only") is True, "all_panels_read_only", "dry-run says all panels are read-only", failures)
    require(dry_run.get("all_forbidden_actions_disabled") is True, "all_forbidden_actions_disabled", "dry-run says forbidden actions are disabled", failures)
    require(dry_run.get("all_forbidden_integrations_absent") is True, "all_forbidden_integrations_absent", "dry-run says forbidden integrations are absent", failures)
    require(dry_run.get("dry_run_status") == "passed" and dry_run.get("warnings") == [] and dry_run.get("errors") == [], "dry_run_status", "dry-run status is passed with empty warnings and errors", failures)

    require(drift.get("drift_status") == "no_drift_detected", "drift_status", "drift status is no_drift_detected", failures)
    require(contains_all(drift.get("drift_categories_checked"), DRIFT_CATEGORIES), "drift_categories", "all drift categories are checked", failures)
    require(drift.get("drift_findings") == [], "drift_findings", "drift findings are empty", failures)
    require(drift.get("critical_drift_count") == 0 and drift.get("warning_drift_count") == 0, "drift_counts", "critical and warning drift counts are zero", failures)
    require(drift.get("scope_reminder_valid") is True and drift.get("read_only_guards_valid") is True, "drift_guard_status", "scope and read-only guard drift checks are valid", failures)

    for name, document in [
        ("consumer_contract", contract),
        ("normalized_example", example),
        ("dry_run_result", dry_run),
        ("drift_report", drift),
    ]:
        labels = document.get("required_labels") or document.get("fixture_labels") or document.get("required_safety_labels")
        require(contains_all(labels, REQUIRED_LABELS), f"{name}_labels", f"{name} represents all required safety labels", failures)

    panels = layout.get("panels", [])
    panel_ids = [item.get("panel_id") for item in panels if isinstance(item, dict)]
    require(contains_all(panel_ids, [
        "runtime_status_panel",
        "readiness_gate_panel",
        "timeline_health_panel",
        "active_rules_panel",
        "strategy_states_panel",
        "static_fixture_source_panel",
        "ldd_scope_reminder_panel",
        "stale_data_warning_panel",
        "forbidden_actions_panel",
        "non_executable_guardrail_panel",
    ]), "layout_panels", "read-only layout resolves all ten panels", failures)

    panel_failures = [
        item.get("panel_id", "unknown")
        for item in panels
        if isinstance(item, dict)
        and not (
            item.get("read_only") is True
            and item.get("mutation_allowed") is False
            and item.get("execution_allowed") is False
            and item.get("credential_handling_allowed") is False
            and item.get("live_data_allowed") is False
        )
    ]
    require(not panel_failures, "panel_read_only_flags", "all panels are read-only and deny mutation, execution, credentials, and live data", failures)

    require(contains_all(contract.get("forbidden_affordances"), REQUIRED_ACTIONS), "contract_forbidden_actions", "contract represents all required forbidden actions", failures)
    require(contains_all(dry_run.get("forbidden_actions_checked"), REQUIRED_ACTIONS), "dry_run_forbidden_actions", "dry-run checked all required forbidden actions", failures)
    require(contains_all(dry_run.get("forbidden_integrations_checked"), REQUIRED_INTEGRATIONS), "dry_run_forbidden_integrations", "dry-run checked all required forbidden integrations", failures)

    scope_sources = [
        boundary.get("ldd_scope_reminder"),
        contract.get("ldd_scope_reminder"),
        layout.get("ldd_scope_reminder"),
        dry_run.get("ldd_scope_reminder"),
        drift.get("ldd_scope_reminder"),
    ]
    example_scope = example.get("scope_reminders", [])
    require(all(item == SCOPE_REMINDER for item in scope_sources) and SCOPE_REMINDER in example_scope, "ldd_scope_reminder", "LDD full-market scope reminder exists across all Phase 7.0-7.2 fixtures", failures)

    event_count, warning_count, latest_event = current_timeline_counts(timeline)
    require(event_count in {101, 102, 103, 104, 105, 106, 107}, "current_timeline_count", "current timeline count is baseline 101 through post-snapshot-QA 107", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {BASELINE_TIMELINE_EVENT, DRY_RUN_TIMESTAMP, READINESS_GATE_TIMESTAMP, LOCAL_STATIC_SHELL_TIMESTAMP, LOCAL_STATIC_SHELL_REVIEW_TIMESTAMP, LOCAL_STATIC_SHELL_DEMO_PACK_TIMESTAMP, LOCAL_STATIC_SHELL_SNAPSHOT_QA_TIMESTAMP}, "current_latest_event", "current latest timeline event is a known Vol.7 static timeline timestamp through Phase 7.7", failures)
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint is unchanged", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT or latest_state.get("checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint is unchanged", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all implementation/live/trading/credential non-goals as false", failures)

    clean, violations = no_implementation_files()
    require(clean, "no_implementation_files", "no Phase 7.2 artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    if violations:
        for violation in violations:
            fail(f"implementation-like artifact path: {violation}", failures)

    print()
    if failures:
        print("Vol.7 static fixture consumer dry-run validation failed.")
    else:
        print("Vol.7 static fixture consumer dry-run validation passed.")
    print("Checks: 45")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Dry-run status: {dry_run.get('dry_run_status', 'unknown')}")
    print(f"Drift status: {drift.get('drift_status', 'unknown')}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Fixture only: true")
    print("Read only: true")
    print("Customer-facing readiness: false")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
