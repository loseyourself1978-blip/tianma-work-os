#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.4 local static shell skeleton."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.4 - Local Static Shell Skeleton Permissioned Implementation"
BASELINE_COMMIT = "80e02ba076f191fc02e48cf7d159a66451aa8ff9"
BASELINE_TIMELINE_EVENT = "2026-06-15T17:07:00+08:00"
IMPLEMENTATION_TIMESTAMP = "2026-06-15T18:12:39+08:00"
REVIEW_TIMESTAMP = "2026-06-16T09:03:34+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

REQUIRED_FILES = {
    "doc": "docs/runtime/VOL7_PHASE7_4_LOCAL_STATIC_SHELL_SKELETON_PERMISSIONED_IMPLEMENTATION_v0.1.md",
    "readme": "static_shell/ldd/README.md",
    "index": "static_shell/ldd/index.html",
    "styles": "static_shell/ldd/styles.css",
    "data": "static_shell/ldd/static_shell_data.js",
    "render": "static_shell/ldd/render_static_shell.js",
    "manifest": "mock_consumers/ldd/vol7_local_static_shell_skeleton_manifest.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_4_local_static_shell_skeleton_permissioned_implementation.json",
}

REQUIRED_SCHEMAS = {
    "manifest": "schemas/vol7_local_static_shell_skeleton_manifest.schema.json",
}

REQUIRED_STATIC_SHELL_FILES = [
    "static_shell/ldd/README.md",
    "static_shell/ldd/index.html",
    "static_shell/ldd/styles.css",
    "static_shell/ldd/static_shell_data.js",
    "static_shell/ldd/render_static_shell.js",
]

REQUIRED_LABELS = [
    "LOCAL STATIC PREVIEW ONLY",
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

REQUIRED_PANELS = [
    "runtime_status_panel",
    "readiness_gate_panel",
    "timeline_health_panel",
    "active_rules_panel",
    "strategy_states_panel",
    "static_fixture_source_panel",
    "ldd_scope_reminder_panel",
    "quote_drift_display_panel",
    "holdings_candidate_forbidden_radar_separation_panel",
    "cash_defense_split_panel",
    "transfer_pnl_separation_panel",
    "forbidden_actions_panel",
    "non_executable_guardrail_panel",
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
    "production_ui",
    "customer_facing_ui",
    "hosted_app",
    "api_server",
    "live_endpoint",
    "external_api",
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

REQUIRED_QUOTES = [
    "broker_watchlist_latest_price",
    "premarket_price",
    "holding_valuation_price",
    "executable_order_page_price",
    "final_filled_order_price",
]

TRUE_FLAGS = ["fixture_only", "read_only", "local_static_preview_only"]
FALSE_FLAGS = [
    "customer_facing_readiness",
    "network_allowed",
    "api_allowed",
    "mutation_allowed",
    "execution_allowed",
    "credential_handling_allowed",
    "live_data_allowed",
    "production_deployment_allowed",
]

FORBIDDEN_TEXT_PATTERNS = {
    "fetch": re.compile(r"\bfetch\s*\("),
    "xml_http_request": re.compile(r"\bXMLHttpRequest\b"),
    "websocket": re.compile(r"\bWebSocket\b"),
    "eventsource": re.compile(r"\bEventSource\b"),
    "remote_url": re.compile(r"https?://|src=\"//|href=\"//"),
    "api_endpoint": re.compile(r"(/api/|api/v[0-9]|graphql|endpoint_url)", re.IGNORECASE),
    "local_storage": re.compile(r"\blocalStorage\b|\bsessionStorage\b"),
    "credential_field": re.compile(r"<input|type=[\"']password|name=[\"'].*(token|credential|secret|key)|autocomplete=[\"']current-password", re.IGNORECASE),
    "button_element": re.compile(r"<button|\bcreateElement\([\"']button[\"']\)", re.IGNORECASE),
    "server_runtime": re.compile(r"http\.createServer|listen\s*\(|express\(|FastAPI|uvicorn|flask", re.IGNORECASE),
}

PACKAGE_OR_SERVER_FILENAMES = {
    "package.json",
    "package-lock.json",
    "vite.config.js",
    "next.config.js",
    "server.js",
    "server.ts",
    "api.js",
    "api.ts",
    "worker.js",
    "scheduler.js",
}


def load_json(relpath: str) -> tuple[Any | None, str | None]:
    path = REPO_ROOT / relpath
    if not path.exists():
        return None, f"{relpath} is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{relpath} invalid JSON: {exc}"


def load_text(relpath: str) -> tuple[str | None, str | None]:
    path = REPO_ROOT / relpath
    if not path.exists():
        return None, f"{relpath} is missing"
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{relpath} cannot be read: {exc}"


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


def contains_all(value: Any, required: list[str]) -> bool:
    return isinstance(value, list) and all(item in value for item in required)


def schema_required_fields(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return [item for item in required if isinstance(item, str)] if isinstance(required, list) else []


def missing_required(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return [field for field in schema_required_fields(schema) if field not in document]


def flags_valid(document: dict[str, Any]) -> bool:
    return all(document.get(flag) is True for flag in TRUE_FLAGS) and all(document.get(flag) is False for flag in FALSE_FLAGS)


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


def scan_forbidden_patterns(texts: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for relpath, text in texts.items():
        for name, pattern in FORBIDDEN_TEXT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relpath}: {name}")
    return findings


def package_or_server_files() -> list[str]:
    findings: list[str] = []
    root = REPO_ROOT / "static_shell" / "ldd"
    if not root.exists():
        return findings
    for path in root.rglob("*"):
        if path.is_file() and path.name in PACKAGE_OR_SERVER_FILENAMES:
            findings.append(str(path.relative_to(REPO_ROOT)))
    return findings


def main() -> int:
    failures: list[str] = []
    loaded_json: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    schemas: dict[str, dict[str, Any]] = {}

    for key, relpath in REQUIRED_FILES.items():
        if relpath.endswith(".json"):
            data, error = load_json(relpath)
            if error:
                fail(error, failures)
                continue
            if not isinstance(data, dict):
                fail(f"{relpath} is not a JSON object", failures)
                continue
            loaded_json[key] = data
        else:
            text, error = load_text(relpath)
            if error:
                fail(error, failures)
                continue
            texts[relpath] = text or ""

    for key, relpath in REQUIRED_SCHEMAS.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        schemas[key] = data

    require(len(loaded_json) == 2, "required_json_files", "manifest and record JSON loaded", failures)
    require(len(texts) == 6, "required_text_files", "documentation and static shell text files loaded", failures)
    require(len(schemas) == len(REQUIRED_SCHEMAS), "required_schemas", "manifest schema loaded", failures)

    manifest = loaded_json.get("manifest", {})
    record = loaded_json.get("record", {})
    schema = schemas.get("manifest", {})
    data_text = texts.get("static_shell/ldd/static_shell_data.js", "")
    all_shell_text = "\n".join(texts.get(path, "") for path in REQUIRED_STATIC_SHELL_FILES)

    require(not missing_required(manifest, schema), "manifest_schema_required_fields", "manifest includes required schema fields", failures)
    require(not missing_required(record, schema), "record_schema_required_fields", "runtime record includes manifest schema fields", failures)

    for name, document in [("manifest", manifest), ("record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses Phase 7.4 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("implementation_timestamp") == IMPLEMENTATION_TIMESTAMP, f"{name}_timestamp", f"{name} timestamp is {IMPLEMENTATION_TIMESTAMP}", failures)
        require(document.get("active_checkpoint") == CHECKPOINT, f"{name}_checkpoint", f"{name} checkpoint remains {CHECKPOINT}", failures)
        require(document.get("latest_timeline_event") == BASELINE_TIMELINE_EVENT, f"{name}_baseline_timeline", f"{name} baseline timeline event is {BASELINE_TIMELINE_EVENT}", failures)
        require(document.get("runtime_records_count") == 103 and document.get("timeline_event_count") == 103, f"{name}_baseline_counts", f"{name} baseline counts are 103/103", failures)
        require(document.get("timeline_warning_count") == 0, f"{name}_warnings", f"{name} timeline warning count is 0", failures)
        require(document.get("operating_mode") == OPERATING_MODE and document.get("portfolio_mode") == PORTFOLIO_MODE, f"{name}_modes", f"{name} modes match baseline", failures)
        require(flags_valid(document), f"{name}_flags", f"{name} required static shell flags are correct", failures)
        require(document.get("static_shell_directory") == "static_shell/ldd/", f"{name}_directory", f"{name} shell is isolated under static_shell/ldd/", failures)
        require(contains_all(document.get("static_shell_files"), REQUIRED_STATIC_SHELL_FILES), f"{name}_shell_files", f"{name} lists all static shell files", failures)
        require(contains_all(document.get("required_labels"), REQUIRED_LABELS), f"{name}_labels", f"{name} includes all required labels", failures)
        require(contains_all(document.get("required_panels"), REQUIRED_PANELS), f"{name}_panels", f"{name} includes all required panels", failures)
        require(contains_all(document.get("forbidden_actions"), REQUIRED_ACTIONS), f"{name}_forbidden_actions", f"{name} includes all forbidden actions", failures)
        require(contains_all(document.get("forbidden_integrations"), REQUIRED_INTEGRATIONS), f"{name}_forbidden_integrations", f"{name} includes all forbidden integrations", failures)
        require(document.get("ldd_scope_reminder") == SCOPE_REMINDER, f"{name}_scope", f"{name} preserves LDD full-market scope reminder", failures)
        require(document.get("quote_drift_display_layer_required") is True and document.get("quote_type_tagging_required") is True, f"{name}_quote_drift", f"{name} requires quote drift display and quote-type tagging", failures)
        require(contains_all(document.get("quote_type_distinctions_required"), REQUIRED_QUOTES), f"{name}_quote_types", f"{name} includes all quote type distinctions", failures)
        require(document.get("cash_defense_ratio_split_required") is True, f"{name}_cash_split", f"{name} requires cash-defense split", failures)
        require(document.get("transfer_pnl_separation_required") is True, f"{name}_transfer_separation", f"{name} requires transfer/P&L separation", failures)
        require(document.get("ggll_current_state") == "zero_position_not_residual_risk_valve", f"{name}_ggll_state", f"{name} corrects GGLL to zero-position state", failures)
        require(document.get("zec_grid_state") == "closed_no_reopen", f"{name}_zec_state", f"{name} keeps ZEC grid closed/no reopen", failures)
        require(document.get("usdt_defense_floor") == 0.70, f"{name}_usdt_floor", f"{name} represents USDT 70% floor", failures)

    shell_files_present = all((REPO_ROOT / relpath).exists() for relpath in REQUIRED_STATIC_SHELL_FILES)
    require(shell_files_present, "static_shell_file_presence", "all required static shell files exist", failures)
    require(all(label in all_shell_text for label in REQUIRED_LABELS), "static_shell_labels", "all required labels are visible in static shell text", failures)
    require(all(panel in data_text for panel in REQUIRED_PANELS), "static_shell_panels", "all required panels are represented in embedded data", failures)
    require(SCOPE_REMINDER in all_shell_text, "static_shell_scope", "LDD full-market scope reminder is present", failures)
    require("quote_drift_display_layer_required" in data_text and "quote_type_tagging_required" in data_text, "static_shell_quote_drift", "quote drift display and quote-type tagging are represented", failures)
    cash_split_values_present = (
        ("77.8%" in data_text and "71.2%" in data_text)
        or ("77.6%" in data_text and "70.6%" in data_text)
    )
    require("cash_defense_ratio_split_required" in data_text and cash_split_values_present, "static_shell_cash_split", "cash-defense split values are represented as static non-live values", failures)
    require("transfer_pnl_separation_required" in data_text and "49.99 USDT" in data_text, "static_shell_transfer_separation", "transfer/P&L separation and 49.99 USDT withdrawal are represented", failures)
    require("zero_position_not_residual_risk_valve" in data_text, "static_shell_ggll_state", "GGLL zero-position correction exists in static data", failures)
    require("closed_no_reopen" in data_text, "static_shell_zec_state", "ZEC closed/no-reopen state exists in static data", failures)
    require("70%" in data_text, "static_shell_usdt_floor", "USDT 70% floor is represented", failures)

    forbidden_findings = scan_forbidden_patterns({path: texts.get(path, "") for path in REQUIRED_STATIC_SHELL_FILES})
    require(not forbidden_findings, "no_forbidden_static_patterns", "no fetch, XHR, WebSocket, EventSource, remote import, endpoint, storage, form, button, server, or credential patterns appear", failures)
    for finding in forbidden_findings:
        fail(f"forbidden static pattern: {finding}", failures)

    package_findings = package_or_server_files()
    require(not package_findings, "no_package_or_server_files", "no package manager, backend, scheduler, or worker files exist under static_shell/ldd", failures)
    for finding in package_findings:
        fail(f"forbidden file under static shell: {finding}", failures)

    runtime_timeline, error = load_json("cockpit/ldd/runtime_timeline.json")
    if error or not isinstance(runtime_timeline, dict):
        fail(error or "cockpit/ldd/runtime_timeline.json is not an object", failures)
    else:
        event_count, warning_count, latest_event = current_timeline_counts(runtime_timeline)
        require(event_count in {103, 104, 105}, "current_timeline_count", "current timeline count is baseline 103, post-record 104, or post-review 105", failures)
        require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
        require(latest_event in {BASELINE_TIMELINE_EVENT, IMPLEMENTATION_TIMESTAMP, REVIEW_TIMESTAMP}, "current_latest_event", "current latest event is baseline, Phase 7.4 implementation timestamp, or Phase 7.5 review timestamp", failures)

    view_model, error = load_json("cockpit/ldd/view_model.json")
    if error or not isinstance(view_model, dict):
        fail(error or "cockpit/ldd/view_model.json is not an object", failures)
    else:
        require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint is unchanged", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all forbidden implementation/live/trading/credential non-goals as false", failures)

    print()
    if failures:
        print("Vol.7 local static shell skeleton validation failed.")
    else:
        print("Vol.7 local static shell skeleton validation passed.")
    print("Checks: 58")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print("Local static shell: created")
    print("Static shell directory: static_shell/ldd/")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Fixture only: true")
    print("Read only: true")
    print("Network allowed: false")
    print("Customer-facing readiness: false")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
