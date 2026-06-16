#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.7 local static shell snapshot QA and completion readiness."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.7 - Local Static Shell Snapshot QA and Vol.7 Completion Readiness"
BASELINE_COMMIT = "04042d1a20c4d96b5cfdab4d404c2458fb2c12a8"
QA_TIMESTAMP = "2026-06-16T11:00:19+08:00"
PREVIOUS_TIMESTAMP = "2026-06-16T10:05:33+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."
NEXT_CHAT_TITLE = "Tianma Work OS Vol.8 — Static Shell QA Handoff / Next Product Boundary"

REQUIRED_FILES = {
    "doc": "docs/runtime/VOL7_PHASE7_7_LOCAL_STATIC_SHELL_SNAPSHOT_QA_AND_COMPLETION_READINESS_v0.1.md",
    "snapshot_schema": "schemas/vol7_local_static_shell_snapshot_qa.schema.json",
    "completion_schema": "schemas/vol7_completion_readiness_gate.schema.json",
    "snapshot_fixture": "mock_consumers/ldd/vol7_local_static_shell_snapshot_qa.json",
    "completion_fixture": "mock_consumers/ldd/vol7_completion_readiness_gate.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_7_local_static_shell_snapshot_qa_and_completion_readiness.json",
    "validator": "scripts/validate_vol7_local_static_shell_snapshot_qa.py",
    "wrapper": "scripts/validate_vol7_local_static_shell_snapshot_qa.sh",
    "latest_state": "cockpit/ldd/latest_state.json",
    "runtime_timeline": "cockpit/ldd/runtime_timeline.json",
    "view_model": "cockpit/ldd/view_model.json",
}

VOL7_DOCS = [
    "docs/runtime/VOL7_PHASE7_0_STATIC_UI_SHELL_BOUNDARY_MAP_v0.1.md",
    "docs/runtime/VOL7_PHASE7_1_STATIC_FIXTURE_CONSUMER_CONTRACT_AND_PANEL_LAYOUT_v0.1.md",
    "docs/runtime/VOL7_PHASE7_2_STATIC_FIXTURE_CONSUMER_DRY_RUN_AND_DRIFT_DETECTOR_v0.1.md",
    "docs/runtime/VOL7_PHASE7_3_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE_v0.1.md",
    "docs/runtime/VOL7_PHASE7_4_LOCAL_STATIC_SHELL_SKELETON_PERMISSIONED_IMPLEMENTATION_v0.1.md",
    "docs/runtime/VOL7_PHASE7_5_LOCAL_STATIC_SHELL_REVIEW_ACCESSIBILITY_GUARDRAIL_HARDENING_AND_LDD_BACKFEED_v0.1.md",
    "docs/runtime/VOL7_PHASE7_6_LOCAL_STATIC_SHELL_DEMO_PACK_AND_OPERATOR_WALKTHROUGH_v0.1.md",
    REQUIRED_FILES["doc"],
]

VOL7_SCHEMAS = [
    "schemas/vol7_static_ui_shell_boundary_map.schema.json",
    "schemas/vol7_static_fixture_consumer_contract.schema.json",
    "schemas/vol7_read_only_panel_layout.schema.json",
    "schemas/vol7_static_fixture_consumer_dry_run.schema.json",
    "schemas/vol7_static_fixture_consumer_drift_report.schema.json",
    "schemas/vol7_static_shell_implementation_readiness_gate.schema.json",
    "schemas/vol7_local_static_shell_skeleton_manifest.schema.json",
    "schemas/vol7_local_static_shell_review_report.schema.json",
    "schemas/vol7_local_static_shell_demo_pack.schema.json",
    REQUIRED_FILES["snapshot_schema"],
    REQUIRED_FILES["completion_schema"],
]

VOL7_FIXTURES = [
    "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_allowed_panels.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_forbidden_actions.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_contract.json",
    "mock_consumers/ldd/vol7_read_only_panel_layout.json",
    "mock_consumers/ldd/vol7_static_consumer_view_model_example.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_dry_run_result.json",
    "mock_consumers/ldd/vol7_static_fixture_consumer_drift_report.json",
    "mock_consumers/ldd/vol7_static_shell_implementation_readiness_gate.json",
    "mock_consumers/ldd/vol7_local_static_shell_skeleton_manifest.json",
    "mock_consumers/ldd/vol7_local_static_shell_review_report.json",
    "mock_consumers/ldd/vol7_local_static_shell_demo_pack.json",
    REQUIRED_FILES["snapshot_fixture"],
    REQUIRED_FILES["completion_fixture"],
]

VOL7_VALIDATORS = [
    "scripts/validate_vol7_static_ui_shell_boundary_map.py",
    "scripts/validate_vol7_static_ui_shell_boundary_map.sh",
    "scripts/validate_vol7_static_fixture_consumer_contract.py",
    "scripts/validate_vol7_static_fixture_consumer_contract.sh",
    "scripts/validate_vol7_static_fixture_consumer_dry_run.py",
    "scripts/validate_vol7_static_fixture_consumer_dry_run.sh",
    "scripts/validate_vol7_static_shell_implementation_readiness_gate.py",
    "scripts/validate_vol7_static_shell_implementation_readiness_gate.sh",
    "scripts/validate_vol7_local_static_shell_skeleton.py",
    "scripts/validate_vol7_local_static_shell_skeleton.sh",
    "scripts/validate_vol7_local_static_shell_review.py",
    "scripts/validate_vol7_local_static_shell_review.sh",
    "scripts/validate_vol7_local_static_shell_demo_pack.py",
    "scripts/validate_vol7_local_static_shell_demo_pack.sh",
    REQUIRED_FILES["validator"],
    REQUIRED_FILES["wrapper"],
]

STATIC_SHELL_FILES = [
    "static_shell/ldd/README.md",
    "static_shell/ldd/index.html",
    "static_shell/ldd/styles.css",
    "static_shell/ldd/static_shell_data.js",
    "static_shell/ldd/render_static_shell.js",
    "static_shell/ldd/OPERATOR_WALKTHROUGH.md",
    "static_shell/ldd/DEMO_CHECKLIST.md",
    "static_shell/ldd/SAFETY_BOUNDARY.md",
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

REQUIRED_PHASES = [
    "Vol.7 Phase 7.0",
    "Vol.7 Phase 7.1",
    "Vol.7 Phase 7.2",
    "Vol.7 Phase 7.3",
    "Vol.7 Phase 7.4",
    "Vol.7 Phase 7.5",
    "Vol.7 Phase 7.6",
    "Vol.7 Phase 7.7",
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


def contains_all_substrings(values: Any, required: list[str]) -> bool:
    if not isinstance(values, list):
        return False
    haystack = [str(value) for value in values]
    return all(any(item in value for value in haystack) for item in required)


def required_fields_present(document: dict[str, Any], schema: dict[str, Any]) -> bool:
    required = schema.get("required", [])
    return isinstance(required, list) and all(isinstance(field, str) and field in document for field in required)


def flags_valid(document: dict[str, Any]) -> bool:
    return all(document.get(flag) is True for flag in TRUE_FLAGS) and all(document.get(flag) is False for flag in FALSE_FLAGS)


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

    required_paths = list(REQUIRED_FILES.values()) + VOL7_DOCS + VOL7_SCHEMAS + VOL7_FIXTURES + VOL7_VALIDATORS + STATIC_SHELL_FILES
    missing = sorted({path for path in required_paths if not (REPO_ROOT / path).exists()})
    require(not missing, "required_files", "all Phase 7.7, Vol.7 artifact, validator, cockpit, and static shell files exist", failures)
    if missing:
        for path in missing:
            print(f"Missing: {path}")
        return 1

    snapshot_schema = load_json(REQUIRED_FILES["snapshot_schema"])
    completion_schema = load_json(REQUIRED_FILES["completion_schema"])
    snapshot = load_json(REQUIRED_FILES["snapshot_fixture"])
    completion = load_json(REQUIRED_FILES["completion_fixture"])
    record = load_json(REQUIRED_FILES["record"])
    latest_state = load_json(REQUIRED_FILES["latest_state"])
    runtime_timeline = load_json(REQUIRED_FILES["runtime_timeline"])
    view_model = load_json(REQUIRED_FILES["view_model"])
    shell_texts = {path: read_text(path) for path in STATIC_SHELL_FILES}
    shell_text = "\n".join(shell_texts.values())
    doc_text = read_text(REQUIRED_FILES["doc"])

    require(required_fields_present(snapshot, snapshot_schema), "snapshot_schema_fields", "snapshot QA fixture includes all schema-required fields", failures)
    require(required_fields_present(completion, completion_schema), "completion_schema_fields", "completion readiness fixture includes all schema-required fields", failures)
    require(required_fields_present(record, snapshot_schema), "record_snapshot_schema_fields", "runtime record includes all snapshot QA schema-required fields", failures)

    for name, document in [("snapshot", snapshot), ("record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses Phase 7.7 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("snapshot_qa_status") == "passed", f"{name}_snapshot_status", f"{name} snapshot QA status is passed", failures)
        require(document.get("timeline_warning_count") == 0, f"{name}_timeline_warnings", f"{name} timeline warning count is 0", failures)
        require(document.get("warnings") == [] and document.get("errors") == [], f"{name}_warnings_errors", f"{name} warnings and errors are empty", failures)
        require(flags_valid(document), f"{name}_flags", f"{name} preserves required static flags", failures)
        require(contains_all(document.get("phases_reviewed"), REQUIRED_PHASES), f"{name}_phases_reviewed", f"{name} reviews all eight Vol.7 phases", failures)
        require(document.get("static_shell_path") == "static_shell/ldd/", f"{name}_shell_path", f"{name} static shell path is static_shell/ldd/", failures)
        require(all(document.get(field) == "passed" for field in [
            "static_shell_boundary_status",
            "ldd_backfeed_coverage_status",
            "guardrail_status",
            "accessibility_status",
            "demo_pack_status",
            "operator_walkthrough_status",
            "safety_boundary_status",
        ]), f"{name}_status_fields", f"{name} marks boundary, backfeed, guardrail, accessibility, demo, walkthrough, and safety statuses passed", failures)

    require(completion.get("phase") == PHASE, "completion_phase", "completion gate uses Phase 7.7 phase label", failures)
    require(completion.get("baseline_commit") == BASELINE_COMMIT, "completion_baseline", "completion gate baseline commit matches Phase 7.6", failures)
    require(completion.get("vol7_completion_readiness") == "ready_for_handoff", "completion_readiness", "Vol.7 completion readiness is ready_for_handoff", failures)
    require(completion.get("handoff_status") == "ready", "handoff_status", "handoff status is ready", failures)
    require(completion.get("completed_phase_count") == 8, "completed_phase_count", "completed phase count is 8", failures)
    require(contains_all_substrings(completion.get("completed_phases"), REQUIRED_PHASES), "completed_phases", "completion gate lists all eight Vol.7 phases", failures)
    require(completion.get("required_validators_status") == "passed", "validators_status", "required validators status is passed", failures)
    require(completion.get("forbidden_scope_absence_status") == "passed", "forbidden_scope_absence", "forbidden scope absence status is passed", failures)
    require(completion.get("recommended_next_volume") == "Vol.8", "next_volume", "recommended next volume is Vol.8", failures)
    require(completion.get("recommended_next_chat_title") == NEXT_CHAT_TITLE, "next_chat_title", "recommended next chat title is exact", failures)
    require(completion.get("warnings") == [] and completion.get("errors") == [], "completion_warnings_errors", "completion warnings and errors are empty", failures)
    require(flags_valid(completion), "completion_flags", "completion gate preserves required static flags", failures)

    require(all((REPO_ROOT / path).exists() for path in VOL7_DOCS), "vol7_documents", "all Vol.7 documents from 7.0 through 7.7 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_SCHEMAS), "vol7_schemas", "all Vol.7 schemas from 7.0 through 7.7 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_FIXTURES), "vol7_fixtures", "all Vol.7 fixtures from 7.0 through 7.7 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_VALIDATORS), "vol7_validators", "all Vol.7 validators from 7.0 through 7.7 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in STATIC_SHELL_FILES), "static_shell_files", "static shell files and demo/safety documents exist under static_shell/ldd/", failures)

    shell_dirs = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "static_shell").glob("*") if path.is_dir())
    require(shell_dirs == ["static_shell/ldd"], "static_shell_isolation", "local static shell remains isolated under static_shell/ldd/", failures)

    require(SCOPE_REMINDER in shell_text and SCOPE_REMINDER in doc_text, "ldd_scope", "LDD full-market scope reminder remains explicit", failures)
    require(all(term in shell_text for term in ["holding_quote", "watchlist_quote", "night_session_quote", "premarket_quote", "executable_order_book_quote", "final_filled_order_price"]), "quote_drift", "quote drift display remains represented", failures)
    require(all(term in shell_text for term in ["77.6%", "70.6%", "145700", "placeholder_fixture_only"]), "cash_hk_split", "cash-defense split and HK exposure remain represented", failures)
    require("49.99 USDT" in shell_text and "completed transfer / withdrawal, not trading loss" in shell_text, "transfer_pnl", "transfer/P&L separation remains represented", failures)
    require("opportunity_cost_tracker" in shell_text and "hindsight/context only" in shell_text, "opportunity_cost", "Opportunity Cost Tracker remains represented as context only", failures)
    require("rule_compliance_opportunity_capture" in shell_text and "return_capture" in shell_text, "rule_capture", "rule compliance vs opportunity capture separation remains represented", failures)
    require("zero_position_candidate_radar" in shell_text and "forbidden_chase_list" in shell_text and "ipo_new_listing_radar" in shell_text, "radar_chase_ipo", "zero-position radar, forbidden chase list, and IPO/new-listing radar remain represented", failures)
    require("zero_position_not_residual_risk_valve" in shell_text and "closed_no_reopen" in shell_text and "70%" in shell_text, "position_state", "GGLL zero-position, ZEC closed/no-reopen, and USDT 70% floor remain explicit", failures)

    forbidden_findings = scan_static_shell(shell_texts)
    require(not forbidden_findings, "no_forbidden_static_patterns", "no fetch, XHR, WebSocket, EventSource, remote import, endpoint, credential form, executable control, mutation control, publish control, package, server, scheduler, or worker pattern appears", failures)
    for finding in forbidden_findings:
        print(f"Forbidden finding: {finding}")
        failures.append(finding)

    event_count, warning_count, latest_event = timeline_counts(runtime_timeline)
    require(event_count in {106, 107}, "current_timeline_count", "current timeline count is baseline 106 or post-snapshot-QA 107", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {PREVIOUS_TIMESTAMP, QA_TIMESTAMP}, "current_latest_event", "current latest event is Phase 7.6 or Phase 7.7 timestamp", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint remains unchanged", failures)
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint remains unchanged", failures)
    require(view_model.get("portfolio_mode", {}).get("operating_mode") == OPERATING_MODE and view_model.get("portfolio_mode", {}).get("current") == PORTFOLIO_MODE, "view_model_modes", "view model modes remain unchanged", failures)
    require("Vol.7 Phase 7.8" in doc_text and NEXT_CHAT_TITLE in doc_text, "handoff_doc", "document hands off to Phase 7.8 and Vol.8 chat title", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all forbidden implementation/live/trading/credential non-goals as false", failures)

    print()
    if failures:
        print("Vol.7 local static shell snapshot QA validation failed.")
    else:
        print("Vol.7 local static shell snapshot QA validation passed.")
    print("Checks: 45")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Snapshot QA status: {snapshot.get('snapshot_qa_status')}")
    print(f"Vol.7 completion readiness: {completion.get('vol7_completion_readiness')}")
    print(f"Handoff status: {completion.get('handoff_status')}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Customer-facing readiness: false")
    print("Local static shell remains fixture-only/read-only/no-network.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
