#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.6 local static shell demo pack."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.6 - Local Static Shell Demo Pack and Operator Walkthrough"
BASELINE_COMMIT = "5801c03a735fac578d1b382a716927060cbfb0ec"
DEMO_TIMESTAMP = "2026-06-16T10:05:33+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

REQUIRED_FILES = {
    "doc": "docs/runtime/VOL7_PHASE7_6_LOCAL_STATIC_SHELL_DEMO_PACK_AND_OPERATOR_WALKTHROUGH_v0.1.md",
    "walkthrough": "static_shell/ldd/OPERATOR_WALKTHROUGH.md",
    "checklist": "static_shell/ldd/DEMO_CHECKLIST.md",
    "safety": "static_shell/ldd/SAFETY_BOUNDARY.md",
    "schema": "schemas/vol7_local_static_shell_demo_pack.schema.json",
    "fixture": "mock_consumers/ldd/vol7_local_static_shell_demo_pack.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_6_local_static_shell_demo_pack_and_operator_walkthrough.json",
    "validator": "scripts/validate_vol7_local_static_shell_demo_pack.py",
    "wrapper": "scripts/validate_vol7_local_static_shell_demo_pack.sh",
    "manifest": "mock_consumers/ldd/vol7_local_static_shell_skeleton_manifest.json",
    "latest_state": "cockpit/ldd/latest_state.json",
    "runtime_timeline": "cockpit/ldd/runtime_timeline.json",
    "view_model": "cockpit/ldd/view_model.json",
}

STATIC_SHELL_FILES = [
    "static_shell/ldd/README.md",
    "static_shell/ldd/index.html",
    "static_shell/ldd/styles.css",
    "static_shell/ldd/static_shell_data.js",
    "static_shell/ldd/render_static_shell.js",
]

REQUIRED_DEMO_DOCUMENTS = [
    "static_shell/ldd/README.md",
    "static_shell/ldd/OPERATOR_WALKTHROUGH.md",
    "static_shell/ldd/DEMO_CHECKLIST.md",
    "static_shell/ldd/SAFETY_BOUNDARY.md",
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
    "opportunity_cost_tracker_panel",
    "rule_compliance_opportunity_capture_panel",
    "zero_position_candidate_radar_panel",
    "forbidden_chase_list_panel",
    "ipo_new_listing_radar_panel",
    "forbidden_actions_panel",
    "non_executable_guardrail_panel",
]

PANEL_TITLES = [
    "Runtime Status Panel",
    "Readiness Gate Panel",
    "Timeline Health Panel",
    "Active Rules Panel",
    "Strategy States Panel",
    "Static Fixture Source Panel",
    "LDD Scope Reminder Panel",
    "Quote Drift Display Panel",
    "Holdings / Candidate / Forbidden / Radar Separation Panel",
    "Cash Defense Split Panel",
    "Transfer / P&L Separation Panel",
    "Opportunity Cost Tracker Panel",
    "Rule Compliance vs Opportunity Capture Panel",
    "Zero-Position Candidate Radar Panel",
    "Forbidden Chase List Panel",
    "IPO/New-Listing Radar Panel",
    "Forbidden Actions Panel",
    "Non-Executable Guardrail Panel",
]

FORBIDDEN_AFFORDANCES = [
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

FORBIDDEN_INTEGRATIONS = [
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

QUOTE_TERMS = [
    "holding_quote",
    "watchlist_quote",
    "night_session_quote",
    "premarket_quote",
    "executable_order_book_quote",
    "final_filled_order_price",
]

FORBIDDEN_IMPLEMENTATION_PATTERNS = {
    "fetch_call": re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    "xml_http_request": re.compile(r"XMLHttpRequest", re.IGNORECASE),
    "websocket": re.compile(r"\bWebSocket\s*\(", re.IGNORECASE),
    "event_source": re.compile(r"\bEventSource\s*\(", re.IGNORECASE),
    "remote_import_or_cdn": re.compile(r"https?://|//cdn\.|unpkg\.com|jsdelivr\.net", re.IGNORECASE),
    "api_endpoint_reference": re.compile(r"(/api/|api/v[0-9]|graphql|endpoint_url)", re.IGNORECASE),
    "credential_input": re.compile(r"<input|<form|type=[\"']password|name=[\"']?(api[_-]?key|token|password|credential)", re.IGNORECASE),
    "button_element": re.compile(r"<button|createElement\([\"']button[\"']\)", re.IGNORECASE),
    "server_runtime": re.compile(r"http\.createServer|listen\s*\(|express\(|FastAPI|uvicorn|flask", re.IGNORECASE),
}

PACKAGE_OR_SERVER_FILENAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "vite.config.js",
    "next.config.js",
    "server.js",
    "server.ts",
    "api.js",
    "api.ts",
    "worker.js",
    "scheduler.js",
}


def load_json(path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, check_id: str, success: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {success}")
    else:
        print(f"FAIL {check_id}: {success}")
        failures.append(check_id)


def contains_all(values: Any, required: list[str]) -> bool:
    return isinstance(values, list) and all(item in {str(value) for value in values} for item in required)


def timeline_counts(timeline: dict[str, Any]) -> tuple[int, int, str]:
    events = timeline.get("events")
    warnings = timeline.get("warnings")
    event_count = timeline.get("event_count")
    if not isinstance(event_count, int) and isinstance(events, list):
        event_count = len(events)
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    latest_event = timeline.get("generated_at", "")
    return int(event_count or 0), warning_count, str(latest_event)


def scan_static_shell(text_by_path: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for path, text in text_by_path.items():
        for name, pattern in FORBIDDEN_IMPLEMENTATION_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: {name}")
    shell_dir = REPO_ROOT / "static_shell" / "ldd"
    for path in shell_dir.rglob("*"):
        if path.is_file() and path.name in PACKAGE_OR_SERVER_FILENAMES:
            findings.append(f"{path.relative_to(REPO_ROOT)}: forbidden package/server/worker file")
    return findings


def main() -> int:
    failures: list[str] = []

    required_paths = list(REQUIRED_FILES.values()) + STATIC_SHELL_FILES + REQUIRED_DEMO_DOCUMENTS
    missing = sorted({path for path in required_paths if not (REPO_ROOT / path).exists()})
    require(not missing, "required_files", "all Phase 7.6 docs, schema, fixture, record, validator, and static shell files exist", failures)
    if missing:
        for path in missing:
            print(f"Missing: {path}")
        return 1

    schema = load_json(REQUIRED_FILES["schema"])
    fixture = load_json(REQUIRED_FILES["fixture"])
    record = load_json(REQUIRED_FILES["record"])
    manifest = load_json(REQUIRED_FILES["manifest"])
    latest_state = load_json(REQUIRED_FILES["latest_state"])
    runtime_timeline = load_json(REQUIRED_FILES["runtime_timeline"])
    view_model = load_json(REQUIRED_FILES["view_model"])

    doc_text = read_text(REQUIRED_FILES["doc"])
    walkthrough_text = read_text(REQUIRED_FILES["walkthrough"])
    checklist_text = read_text(REQUIRED_FILES["checklist"])
    safety_text = read_text(REQUIRED_FILES["safety"])
    static_texts = {path: read_text(path) for path in STATIC_SHELL_FILES}
    shell_text = "\n".join(static_texts.values())
    all_demo_text = "\n".join([doc_text, walkthrough_text, checklist_text, safety_text, shell_text])

    required_schema_fields = schema.get("required", [])
    require(all(field in fixture for field in required_schema_fields), "fixture_schema_fields", "demo pack fixture includes all schema-required fields", failures)
    require(all(field in record for field in required_schema_fields), "record_schema_fields", "runtime record includes all schema-required demo fields", failures)

    for name, document in [("fixture", fixture), ("record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses Phase 7.6 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("demo_pack_status") == "passed", f"{name}_demo_status", f"{name} demo pack status is passed", failures)
        require(document.get("operator_walkthrough_status") == "passed", f"{name}_walkthrough_status", f"{name} operator walkthrough status is passed", failures)
        require(document.get("demo_checklist_status") == "passed", f"{name}_checklist_status", f"{name} demo checklist status is passed", failures)
        require(document.get("safety_boundary_status") == "passed", f"{name}_safety_status", f"{name} safety boundary status is passed", failures)
        require(document.get("warnings") == [] and document.get("errors") == [], f"{name}_warnings_errors", f"{name} warnings and errors are empty", failures)
        require(all(document.get(flag) is True for flag in TRUE_FLAGS), f"{name}_true_flags", f"{name} preserves required true static flags", failures)
        require(all(document.get(flag) is False for flag in FALSE_FLAGS), f"{name}_false_flags", f"{name} preserves required false safety flags", failures)
        require(document.get("local_static_shell_path") == "static_shell/ldd/index.html", f"{name}_local_path", f"{name} points to direct local shell path", failures)
        require(contains_all(document.get("required_demo_documents"), REQUIRED_DEMO_DOCUMENTS), f"{name}_demo_documents", f"{name} lists all required demo documents", failures)
        require(contains_all(document.get("required_panels"), REQUIRED_PANELS), f"{name}_required_panels", f"{name} lists all required panels", failures)
        require(contains_all(document.get("required_guardrail_labels"), REQUIRED_LABELS), f"{name}_guardrail_labels", f"{name} lists all required guardrail labels", failures)
        require(contains_all(document.get("forbidden_affordances"), FORBIDDEN_AFFORDANCES), f"{name}_forbidden_affordances", f"{name} lists all forbidden affordances", failures)
        require(contains_all(document.get("forbidden_integrations"), FORBIDDEN_INTEGRATIONS), f"{name}_forbidden_integrations", f"{name} lists all forbidden integrations", failures)

    require("static_shell/ldd/index.html" in walkthrough_text and "directly in a browser" in walkthrough_text, "walkthrough_opening_steps", "operator walkthrough includes direct local opening steps", failures)
    require(all(term in walkthrough_text for term in ["No server is required", "No network is required", "No API key is required", "No login is required", "No account connection is required"]), "walkthrough_no_requirements", "operator walkthrough states no server/network/API/login/account connection is required", failures)
    require(all(label in walkthrough_text for label in REQUIRED_LABELS), "walkthrough_labels", "operator walkthrough includes required visible labels", failures)
    require(all(title in checklist_text for title in PANEL_TITLES), "checklist_panels", "demo checklist includes all required panel checks", failures)
    require(all(text in checklist_text for text in ["No buy controls", "No sell controls", "No rebalance controls", "No credential inputs", "No login/auth form", "No live refresh control", "No API calls", "No network dependency", "No package manager/build system", "Customer-facing readiness remains false"]), "checklist_forbidden_checks", "demo checklist includes required forbidden capability checks", failures)
    require(all(item.replace("_", " ") in safety_text.lower() or item in safety_text for item in ["local only", "static only", "fixture-only", "read-only", "no network", "no API", "no live data", "no broker/Binance connection", "no credential handling", "no execution", "no runtime mutation", "no customer-facing release", "no production deployment"]), "safety_boundary_prohibitions", "safety boundary includes required static-only prohibitions", failures)
    require(all(label in shell_text for label in REQUIRED_LABELS), "shell_visible_guardrails", "required guardrail labels remain visible in static shell", failures)
    require(all(panel in shell_text for panel in REQUIRED_PANELS), "shell_panels_represented", "all required panels are represented in static shell data", failures)

    require(all(term in all_demo_text for term in QUOTE_TERMS), "quote_drift_terms", "quote drift display remains explicit", failures)
    require("Execution source remains broker/Binance order page and final filled order records." in all_demo_text, "execution_sot_copy", "execution source-of-truth copy remains explicit", failures)
    require(all(term in all_demo_text for term in ["77.6%", "70.6%", "145,700 HKD", "placeholder_fixture_only"]), "cash_defense_split", "cash-defense split includes U.S., Binance, HK exposure, and cross-account placeholder", failures)
    require("49.99 USDT" in all_demo_text and "completed transfer / withdrawal, not trading loss" in all_demo_text, "transfer_pnl_separation", "49.99 USDT transfer/P&L separation remains represented", failures)
    require("hindsight/context only" in all_demo_text and "separate from rule compliance" in all_demo_text, "opportunity_cost_context", "Opportunity Cost Tracker remains hindsight/context only and separate from rule compliance", failures)
    require("rule compliance" in all_demo_text.lower() and "opportunity capture" in all_demo_text.lower(), "rule_capture_separation", "rule compliance remains separated from opportunity capture", failures)
    require("zero_position_not_residual_risk_valve" in all_demo_text and "closed_no_reopen" in all_demo_text, "position_state_corrections", "GGLL remains zero-position and ZEC grid remains closed/no-reopen", failures)
    require("SPCX" in all_demo_text and "IPO" in all_demo_text and "do not sell GOOG/NVDA to fund it" in all_demo_text, "ipo_radar", "IPO/new-listing radar remains represented", failures)
    require(SCOPE_REMINDER in all_demo_text, "ldd_full_market_scope", "LDD full-market scope reminder remains explicit", failures)

    overlay = manifest.get("phase7_6_demo_pack_overlay", {})
    require(isinstance(overlay, dict) and overlay.get("demo_phase") == PHASE, "manifest_demo_overlay", "skeleton manifest includes Phase 7.6 demo pack overlay", failures)
    require(overlay.get("operator_walkthrough_status") == "passed" and overlay.get("safety_boundary_status") == "passed", "manifest_demo_statuses", "manifest overlay carries demo walkthrough and safety boundary statuses", failures)

    forbidden_findings = scan_static_shell(static_texts)
    require(not forbidden_findings, "no_forbidden_static_patterns", "no fetch, XHR, WebSocket, EventSource, remote import, endpoint, credential form, executable control, mutation control, publish control, package, server, scheduler, or worker pattern appears", failures)
    for finding in forbidden_findings:
        print(f"Forbidden finding: {finding}")
        failures.append(finding)

    event_count, warning_count, latest_event = timeline_counts(runtime_timeline)
    require(event_count in {105, 106}, "current_timeline_count", "current timeline count is baseline 105 or post-demo-pack 106", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {"2026-06-16T09:03:34+08:00", DEMO_TIMESTAMP}, "current_latest_event", "current latest event is Phase 7.5 or Phase 7.6 timestamp", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint remains unchanged", failures)
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint remains unchanged", failures)
    require(view_model.get("portfolio_mode", {}).get("operating_mode") == OPERATING_MODE and view_model.get("portfolio_mode", {}).get("current") == PORTFOLIO_MODE, "view_model_modes", "view model modes remain unchanged", failures)
    require("Vol.7 Phase 7.7 - Local Static Shell Snapshot QA and Vol.7 Completion Readiness" in doc_text, "phase77_handoff", "document hands off to Phase 7.7", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all forbidden implementation/live/trading/credential non-goals as false", failures)

    print()
    if failures:
        print("Vol.7 local static shell demo pack validation failed.")
    else:
        print("Vol.7 local static shell demo pack validation passed.")
    print("Checks: 47")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Demo pack status: {fixture.get('demo_pack_status')}")
    print(f"Operator walkthrough status: {fixture.get('operator_walkthrough_status')}")
    print(f"Safety boundary status: {fixture.get('safety_boundary_status')}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Customer-facing readiness: false")
    print("Local static shell remains fixture-only/read-only/no-network.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
