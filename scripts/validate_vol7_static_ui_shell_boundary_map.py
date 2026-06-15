#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.0 static UI shell boundary map artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKPOINT = "2026-06-12T09:18:00+08:00"
LATEST_TIMELINE_EVENT = "2026-06-12T17:20:00+08:00"
BASELINE_COMMIT = "b1892a50a56d33944be9f5a6a55cb49f3ae06329"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"

REQUIRED_FILES = {
    "boundary_map": "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "allowed_panels": "mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json",
    "forbidden_actions": "mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_0_static_ui_shell_boundary_map.json",
}

REQUIRED_SCHEMAS = [
    "schemas/vol7_static_ui_shell_boundary_map.schema.json",
]

PHASE_ARTIFACTS = [
    "docs/runtime/VOL7_PHASE7_0_STATIC_UI_SHELL_BOUNDARY_MAP_v0.1.md",
    "schemas/vol7_static_ui_shell_boundary_map.schema.json",
    "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json",
    "records/ldd/2026-06-15/vol7_phase7_0_static_ui_shell_boundary_map.json",
    "scripts/validate_vol7_static_ui_shell_boundary_map.py",
    "scripts/validate_vol7_static_ui_shell_boundary_map.sh",
]

REQUIRED_PANELS = [
    "runtime_status_panel",
    "readiness_gate_panel",
    "active_rules_panel",
    "timeline_health_panel",
    "static_fixture_source_panel",
    "ldd_scope_reminder_panel",
    "forbidden_actions_panel",
    "stale_data_warning_panel",
]

REQUIRED_ACTIONS = [
    "buy_button",
    "sell_button",
    "rebalance_button",
    "sync_broker_button",
    "sync_binance_button",
    "connect_account_button",
    "api_key_input",
    "credential_form",
    "live_refresh_button",
    "auto_trade_toggle",
    "runtime_edit_form",
    "rule_mutation_editor",
    "alert_dispatch_toggle",
    "production_publish_button",
]

REQUIRED_INTEGRATIONS = [
    "production_ui",
    "customer_facing_ui",
    "api_server",
    "live_endpoint",
    "broker_connection",
    "binance_connection",
    "live_market_data",
    "trading_automation",
    "credential_handling",
    "runtime_mutation_ui",
    "execution_trigger",
    "order_placement",
    "portfolio_modification",
    "background_worker",
    "scheduler",
    "notification_dispatcher",
]

FALSE_FLAGS = [
    "customer_facing_readiness",
    "mutation_allowed",
    "execution_allowed",
    "credential_handling_allowed",
    "live_data_allowed",
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


def action_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    values: set[str] = set()
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("action_id"), str):
            values.add(item["action_id"])
        elif isinstance(item, str):
            values.add(item)
    return values


def integration_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    values: set[str] = set()
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("integration_id"), str):
            values.add(item["integration_id"])
        elif isinstance(item, str):
            values.add(item)
    return values


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

    for key, relpath in REQUIRED_FILES.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        loaded[key] = data

    require(len(loaded) == len(REQUIRED_FILES), "required_files", f"{len(loaded)}/{len(REQUIRED_FILES)} required JSON files loaded", failures)
    schema_count = sum(1 for relpath in REQUIRED_SCHEMAS if (REPO_ROOT / relpath).exists())
    require(schema_count == len(REQUIRED_SCHEMAS), "required_schema", "static UI shell boundary schema exists", failures)
    require(len(loaded) == len(REQUIRED_FILES), "json_syntax", "all required JSON files are valid objects", failures)

    boundary = loaded.get("boundary_map", {})
    panels_doc = loaded.get("allowed_panels", {})
    forbidden_doc = loaded.get("forbidden_actions", {})
    record = loaded.get("record", {})

    require(boundary.get("phase") == "Vol.7 Phase 7.0 - Static UI Shell Boundary Map", "phase", "boundary map uses the Phase 7.0 phase label", failures)
    require(boundary.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", f"baseline commit is {BASELINE_COMMIT}", failures)
    require(boundary.get("origin_status") == "synchronized", "origin_status", "origin status remains synchronized", failures)
    require(boundary.get("working_tree_status") == "clean", "working_tree_status", "working tree status baseline is clean", failures)
    require(boundary.get("active_checkpoint") == CHECKPOINT and record.get("active_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    require(boundary.get("latest_timeline_event") == LATEST_TIMELINE_EVENT, "latest_timeline_event", f"latest Vol.6 timeline event remains {LATEST_TIMELINE_EVENT}", failures)
    require(boundary.get("runtime_records_count") == 99, "runtime_records_count", "baseline runtime record count is 99", failures)
    require(boundary.get("timeline_event_count") == 99, "timeline_event_count", "baseline timeline event count is 99", failures)
    require(boundary.get("timeline_warning_count") == 0, "timeline_warning_count", "timeline warning count is 0", failures)
    require(boundary.get("active_rules_count") == 11, "active_rules_count", "active rule count is 11", failures)
    require(boundary.get("operating_mode") == OPERATING_MODE and record.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(boundary.get("portfolio_mode") == PORTFOLIO_MODE and record.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    require(boundary.get("fixture_only") is True and record.get("fixture_only") is True, "fixture_only", "boundary map and record are fixture-only", failures)
    require(boundary.get("read_only") is True and record.get("read_only") is True, "read_only", "boundary map and record are read-only", failures)
    for flag in FALSE_FLAGS:
        require(boundary.get(flag) is False and record.get(flag) is False, flag, f"{flag} remains false", failures)

    boundary_panels = set(boundary.get("allowed_panels", []))
    panel_ids = {item.get("panel_id") for item in panels_doc.get("panels", []) if isinstance(item, dict)}
    require(all(item in boundary_panels for item in REQUIRED_PANELS), "boundary_allowed_panels", "boundary map includes all required allowed panels", failures)
    require(all(item in panel_ids for item in REQUIRED_PANELS), "panel_catalog", "allowed panel catalog includes all required panels", failures)

    panel_failures = [
        item.get("panel_id", "unknown")
        for item in panels_doc.get("panels", [])
        if isinstance(item, dict)
        and not (
            item.get("read_only") is True
            and item.get("fixture_only") is True
            and item.get("mutation_allowed") is False
            and item.get("execution_allowed") is False
            and item.get("credential_handling_allowed") is False
            and item.get("live_data_allowed") is False
        )
    ]
    require(not panel_failures, "panel_read_only_contract", "all allowed panels are fixture-only, read-only, non-executable, no-credential, and no-live-data", failures)

    boundary_actions = set(boundary.get("forbidden_actions", []))
    forbidden_actions = action_ids(forbidden_doc.get("forbidden_actions"))
    require(all(item in boundary_actions for item in REQUIRED_ACTIONS), "boundary_forbidden_actions", "boundary map includes all required forbidden UI affordances", failures)
    require(all(item in forbidden_actions for item in REQUIRED_ACTIONS), "forbidden_action_catalog", "forbidden action catalog includes all required UI affordances", failures)

    blocked_action_failures = [
        item.get("action_id", "unknown")
        for item in forbidden_doc.get("forbidden_actions", [])
        if isinstance(item, dict) and not (item.get("blocked") is True and item.get("allowed_roles") == [])
    ]
    require(not blocked_action_failures, "forbidden_actions_blocked", "all forbidden actions are blocked with no allowed roles", failures)

    boundary_integrations = set(boundary.get("forbidden_integrations", []))
    forbidden_integrations = integration_ids(forbidden_doc.get("forbidden_integrations"))
    require(all(item in boundary_integrations for item in REQUIRED_INTEGRATIONS), "boundary_forbidden_integrations", "boundary map includes all required forbidden integrations", failures)
    require(all(item in forbidden_integrations for item in ["api_server", "live_market_data_fetch", "scheduler", "background_process", "production_deployment"]), "forbidden_integration_catalog", "forbidden integration catalog includes core blocked system integrations", failures)

    scope_text = str(boundary.get("ldd_scope_reminder", "")).lower()
    require("entire u.s. equity market" in scope_text and "not only existing or former positions" in scope_text, "ldd_scope_reminder", "LDD scope remains entire U.S. equity market, not only existing or former positions", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all implementation/live/trading/credential non-goals as false", failures)

    clean, violations = no_implementation_files()
    require(clean, "no_implementation_files", "no Phase 7.0 artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    if violations:
        for violation in violations:
            fail(f"implementation-like artifact path: {violation}", failures)

    print()
    if failures:
        print("Vol.7 static UI shell boundary map validation failed.")
    else:
        print("Vol.7 static UI shell boundary map validation passed.")
    print("Checks: 29")
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
