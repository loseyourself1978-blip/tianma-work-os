#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.1 static fixture consumer contract artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKPOINT = "2026-06-12T09:18:00+08:00"
LATEST_TIMELINE_EVENT = "2026-06-15T13:41:45+08:00"
BASELINE_COMMIT = "3f8d1703b8cae4fa47e6846667bea03cd8330f67"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

REQUIRED_FILES = {
    "contract": "mock_consumers/ldd/vol7_static_fixture_consumer_contract.json",
    "layout": "mock_consumers/ldd/vol7_read_only_panel_layout.json",
    "view_model_example": "mock_consumers/ldd/vol7_static_consumer_view_model_example.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_1_static_fixture_consumer_contract_and_panel_layout.json",
}

REQUIRED_INPUT_FIXTURES = [
    "cockpit/ldd/latest_state.json",
    "cockpit/ldd/runtime_timeline.json",
    "cockpit/ldd/view_model.json",
    "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json",
]

REQUIRED_SCHEMAS = {
    "contract": "schemas/vol7_static_fixture_consumer_contract.schema.json",
    "layout": "schemas/vol7_read_only_panel_layout.schema.json",
}

REQUIRED_VIEW_MODEL_SECTIONS = [
    "metadata",
    "baseline",
    "runtime_status",
    "readiness",
    "timeline_health",
    "active_rules_summary",
    "strategy_state_summary",
    "allowed_panels",
    "forbidden_actions",
    "forbidden_integrations",
    "scope_reminders",
    "stale_data_warnings",
    "fixture_labels",
    "read_only_guards",
]

REQUIRED_PANELS = [
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
]

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

REQUIRED_AFFORDANCES = [
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

FALSE_FLAGS = [
    "customer_facing_readiness",
    "mutation_allowed",
    "execution_allowed",
    "credential_handling_allowed",
    "live_data_allowed",
]

TRUE_FLAGS = [
    "fixture_only",
    "read_only",
]

PHASE_ARTIFACTS = [
    "docs/runtime/VOL7_PHASE7_1_STATIC_FIXTURE_CONSUMER_CONTRACT_AND_PANEL_LAYOUT_v0.1.md",
    "schemas/vol7_static_fixture_consumer_contract.schema.json",
    "schemas/vol7_read_only_panel_layout.schema.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_contract.json",
    "mock_consumers/ldd/vol7_read_only_panel_layout.json",
    "mock_consumers/ldd/vol7_static_consumer_view_model_example.json",
    "records/ldd/2026-06-15/vol7_phase7_1_static_fixture_consumer_contract_and_panel_layout.json",
    "scripts/validate_vol7_static_fixture_consumer_contract.py",
    "scripts/validate_vol7_static_fixture_consumer_contract.sh",
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


def validate_required_fields(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    missing = [field for field in schema_required_fields(schema) if field not in document]
    return missing


def values_present(container: Any, required: list[str]) -> bool:
    if not isinstance(container, list):
        return False
    return all(item in container for item in required)


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


def main() -> int:
    failures: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}
    schemas: dict[str, dict[str, Any]] = {}

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

    require(len(loaded) == len(REQUIRED_FILES), "required_files", f"{len(loaded)}/{len(REQUIRED_FILES)} required JSON files loaded", failures)
    require(len(schemas) == len(REQUIRED_SCHEMAS), "required_schemas", f"{len(schemas)}/{len(REQUIRED_SCHEMAS)} schemas loaded", failures)
    require(len(loaded) == len(REQUIRED_FILES) and len(schemas) == len(REQUIRED_SCHEMAS), "json_syntax", "all required JSON files and schemas are valid objects", failures)

    contract = loaded.get("contract", {})
    layout = loaded.get("layout", {})
    example = loaded.get("view_model_example", {})
    record = loaded.get("record", {})

    contract_missing = validate_required_fields(contract, schemas.get("contract", {}))
    layout_missing = validate_required_fields(layout, schemas.get("layout", {}))
    record_missing = validate_required_fields(record, schemas.get("contract", {}))
    require(not contract_missing, "contract_schema_required_fields", "static fixture consumer contract includes required schema fields", failures)
    require(not layout_missing, "layout_schema_required_fields", "read-only panel layout includes required schema fields", failures)
    require(not record_missing, "record_schema_required_fields", "runtime record includes static contract schema fields", failures)

    require(contract.get("phase") == "Vol.7 Phase 7.1 - Static Fixture Consumer Contract and Read-Only Panel Layout", "phase", "contract uses the Phase 7.1 phase label", failures)
    require(contract.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", f"baseline commit is {BASELINE_COMMIT}", failures)
    require(contract.get("origin_status") == "synchronized", "origin_status", "origin status remains synchronized", failures)
    require(contract.get("working_tree_status") == "clean", "working_tree_status", "working tree status baseline is clean", failures)
    require(contract.get("active_checkpoint") == CHECKPOINT and layout.get("active_checkpoint") == CHECKPOINT and record.get("active_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    require(contract.get("latest_timeline_event") == LATEST_TIMELINE_EVENT, "latest_timeline_event", f"latest baseline timeline event remains {LATEST_TIMELINE_EVENT}", failures)
    require(contract.get("runtime_records_count") == 100, "runtime_records_count", "baseline runtime record count is 100", failures)
    require(contract.get("timeline_event_count") == 100, "timeline_event_count", "baseline timeline event count is 100", failures)
    require(contract.get("timeline_warning_count") == 0, "timeline_warning_count", "timeline warning count is 0", failures)
    require(contract.get("active_rules_count") == 11, "active_rules_count", "active rule count is 11", failures)
    require(contract.get("strategy_states_count") == 16, "strategy_states_count", "strategy state count is 16", failures)
    require(contract.get("operating_mode") == OPERATING_MODE and record.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(contract.get("portfolio_mode") == PORTFOLIO_MODE and record.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    for flag in TRUE_FLAGS:
        require(contract.get(flag) is True and layout.get(flag) is True and example.get(flag) is True and record.get(flag) is True, flag, f"{flag} remains true across Phase 7.1 artifacts", failures)
    for flag in FALSE_FLAGS:
        require(contract.get(flag) is False and layout.get(flag) is False and example.get(flag) is False and record.get(flag) is False, flag, f"{flag} remains false across Phase 7.1 artifacts", failures)

    readiness = example.get("readiness", {})
    guards = example.get("read_only_guards", {})
    require(isinstance(readiness, dict) and isinstance(guards, dict), "example_guard_sections", "normalized view model example includes readiness and read_only_guards", failures)
    for flag in TRUE_FLAGS:
        require(readiness.get(flag) is True and guards.get(flag) is True, f"example_{flag}", f"normalized example {flag} remains true", failures)
    for flag in FALSE_FLAGS:
        require(readiness.get(flag) is False and guards.get(flag) is False, f"example_{flag}", f"normalized example {flag} remains false", failures)

    require(all((REPO_ROOT / relpath).exists() for relpath in REQUIRED_INPUT_FIXTURES), "input_fixture_presence", "all allowed input fixture files exist", failures)
    require(values_present(contract.get("allowed_input_fixtures"), REQUIRED_INPUT_FIXTURES), "allowed_input_fixtures", "contract lists all allowed input fixtures", failures)
    require(values_present(contract.get("normalized_view_model_contract"), REQUIRED_VIEW_MODEL_SECTIONS), "normalized_contract_sections", "contract lists all normalized view model sections", failures)
    require(all(section in example for section in REQUIRED_VIEW_MODEL_SECTIONS), "normalized_example_sections", "normalized example includes all required sections", failures)
    require(values_present(contract.get("required_labels"), REQUIRED_LABELS), "required_labels_contract", "contract lists all required labels", failures)
    require(values_present(example.get("fixture_labels"), REQUIRED_LABELS), "required_labels_example", "normalized example includes all required labels", failures)

    panels = layout.get("panels", [])
    panel_ids = [item.get("panel_id") for item in panels if isinstance(item, dict)]
    require(values_present(panel_ids, REQUIRED_PANELS), "required_panels", "read-only layout includes all ten required panels", failures)
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
    require(not panel_failures, "panel_static_flags", "all panels are read-only and deny mutation, execution, credential handling, and live data", failures)
    require(
        any(
            item.get("panel_id") == "ldd_scope_reminder_panel"
            and "ldd_scope_reminder" in item.get("display_fields", [])
            for item in panels
            if isinstance(item, dict)
        ),
        "scope_panel_field",
        "LDD scope reminder panel displays ldd_scope_reminder",
        failures,
    )

    contract_affordances = contract.get("forbidden_affordances", [])
    example_affordances = example.get("forbidden_actions", [])
    require(values_present(contract_affordances, REQUIRED_AFFORDANCES), "contract_forbidden_affordances", "contract represents all required forbidden affordances", failures)
    require(values_present(example_affordances, REQUIRED_AFFORDANCES), "example_forbidden_affordances", "normalized example represents all required forbidden affordances", failures)
    panel_affordances: set[str] = set()
    for item in panels:
        if isinstance(item, dict) and isinstance(item.get("forbidden_affordances"), list):
            panel_affordances.update(str(value) for value in item["forbidden_affordances"])
    require(all(item in panel_affordances for item in ["buy_button", "sell_button", "live_refresh_button", "api_key_input", "credential_form", "production_publish_button", "customer_facing_publish_flag"]), "panel_forbidden_affordances", "panel layout represents key forbidden affordances", failures)

    require(contract.get("ldd_scope_reminder") == SCOPE_REMINDER and layout.get("ldd_scope_reminder") == SCOPE_REMINDER and SCOPE_REMINDER in example.get("scope_reminders", []), "ldd_scope_reminder", "LDD full-market scope reminder exists in contract, layout, and normalized example", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all implementation/live/trading/credential non-goals as false", failures)

    clean, violations = no_implementation_files()
    require(clean, "no_implementation_files", "no Phase 7.1 artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    if violations:
        for violation in violations:
            fail(f"implementation-like artifact path: {violation}", failures)

    print()
    if failures:
        print("Vol.7 static fixture consumer contract validation failed.")
    else:
        print("Vol.7 static fixture consumer contract validation passed.")
    print("Checks: 42")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Fixture only: true")
    print("Read only: true")
    print("Customer-facing readiness: false")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
