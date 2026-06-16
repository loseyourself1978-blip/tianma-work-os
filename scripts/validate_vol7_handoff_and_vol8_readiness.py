#!/usr/bin/env python3
"""Validate Vol.7 handoff summary and Vol.8 readiness gate."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.8 - Vol.7 Handoff Summary and Vol.8 Readiness Gate"
BASELINE_COMMIT = "e31014b9fbb56d37c8ad566a3c637e995befcbe0"
PHASE78_TIMESTAMP = "2026-06-16T13:00:56+08:00"
PHASE77_TIMESTAMP = "2026-06-16T11:00:19+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
NEXT_CHAT_TITLE = "Tianma Work OS Vol.8 — Static Shell QA Handoff / Next Product Boundary"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

REQUIRED_FILES = {
    "handoff_doc": "docs/runtime/VOL7_HANDOFF_SUMMARY_v0.1.md",
    "phase_doc": "docs/runtime/VOL7_PHASE7_8_HANDOFF_SUMMARY_AND_VOL8_READINESS_GATE_v0.1.md",
    "handoff_schema": "schemas/vol7_handoff_summary.schema.json",
    "vol8_schema": "schemas/vol8_entry_readiness_gate.schema.json",
    "handoff_fixture": "mock_consumers/ldd/vol7_handoff_summary.json",
    "vol8_fixture": "mock_consumers/ldd/vol8_entry_readiness_gate.json",
    "backfeed_fixture": "mock_consumers/ldd/twos_ldd_post_vol7_backfeed_status_update.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_8_handoff_summary_and_vol8_readiness_gate.json",
    "validator": "scripts/validate_vol7_handoff_and_vol8_readiness.py",
    "wrapper": "scripts/validate_vol7_handoff_and_vol8_readiness.sh",
    "latest_state": "cockpit/ldd/latest_state.json",
    "runtime_timeline": "cockpit/ldd/runtime_timeline.json",
    "view_model": "cockpit/ldd/view_model.json",
    "snapshot_qa": "mock_consumers/ldd/vol7_local_static_shell_snapshot_qa.json",
    "completion_gate": "mock_consumers/ldd/vol7_completion_readiness_gate.json",
}

VOL7_DOCS = [
    "docs/runtime/VOL7_PHASE7_0_STATIC_UI_SHELL_BOUNDARY_MAP_v0.1.md",
    "docs/runtime/VOL7_PHASE7_1_STATIC_FIXTURE_CONSUMER_CONTRACT_AND_PANEL_LAYOUT_v0.1.md",
    "docs/runtime/VOL7_PHASE7_2_STATIC_FIXTURE_CONSUMER_DRY_RUN_AND_DRIFT_DETECTOR_v0.1.md",
    "docs/runtime/VOL7_PHASE7_3_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE_v0.1.md",
    "docs/runtime/VOL7_PHASE7_4_LOCAL_STATIC_SHELL_SKELETON_PERMISSIONED_IMPLEMENTATION_v0.1.md",
    "docs/runtime/VOL7_PHASE7_5_LOCAL_STATIC_SHELL_REVIEW_ACCESSIBILITY_GUARDRAIL_HARDENING_AND_LDD_BACKFEED_v0.1.md",
    "docs/runtime/VOL7_PHASE7_6_LOCAL_STATIC_SHELL_DEMO_PACK_AND_OPERATOR_WALKTHROUGH_v0.1.md",
    "docs/runtime/VOL7_PHASE7_7_LOCAL_STATIC_SHELL_SNAPSHOT_QA_AND_COMPLETION_READINESS_v0.1.md",
    REQUIRED_FILES["phase_doc"],
    REQUIRED_FILES["handoff_doc"],
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
    "schemas/vol7_local_static_shell_snapshot_qa.schema.json",
    "schemas/vol7_completion_readiness_gate.schema.json",
    REQUIRED_FILES["handoff_schema"],
    REQUIRED_FILES["vol8_schema"],
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
    REQUIRED_FILES["snapshot_qa"],
    REQUIRED_FILES["completion_gate"],
    REQUIRED_FILES["handoff_fixture"],
    REQUIRED_FILES["vol8_fixture"],
    REQUIRED_FILES["backfeed_fixture"],
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
    "scripts/validate_vol7_local_static_shell_snapshot_qa.py",
    "scripts/validate_vol7_local_static_shell_snapshot_qa.sh",
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

REQUIRED_PHASES = [
    "Vol.7 Phase 7.0",
    "Vol.7 Phase 7.1",
    "Vol.7 Phase 7.2",
    "Vol.7 Phase 7.3",
    "Vol.7 Phase 7.4",
    "Vol.7 Phase 7.5",
    "Vol.7 Phase 7.6",
    "Vol.7 Phase 7.7",
    "Vol.7 Phase 7.8",
]

LDD_BACKFEED_ITEMS = [
    "quote drift clarity",
    "quote-type tagging",
    "U.S. cash defense split",
    "Binance USDT defense split",
    "HK exposure split",
    "total cross-account risk placeholder",
    "49.99 USDT transfer/P&L separation",
    "GGLL zero-position correction",
    "ZEC grid closed/no-reopen",
    "USDT 70% floor",
    "Opportunity Cost Tracker",
    "rule compliance vs opportunity capture separation",
    "zero-position candidate radar",
    "forbidden chase list",
    "IPO/new-listing radar",
    "LDD full-market scope reminder",
]

VOL8_FORBIDDEN_SCOPE = [
    "production UI",
    "customer-facing UI",
    "hosted app",
    "API server",
    "live endpoint",
    "external API",
    "broker connection",
    "Binance connection",
    "live market data",
    "trading automation",
    "credential handling",
    "login/auth",
    "runtime mutation",
    "execution trigger",
    "order placement",
    "portfolio modification",
    "background worker",
    "scheduler",
    "notification dispatcher",
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


def required_fields_present(document: dict[str, Any], schema: dict[str, Any]) -> bool:
    required = schema.get("required", [])
    return isinstance(required, list) and all(isinstance(field, str) and field in document for field in required)


def contains_all(values: Any, required: list[str]) -> bool:
    return isinstance(values, list) and all(item in {str(value) for value in values} for item in required)


def contains_all_substrings(values: Any, required: list[str]) -> bool:
    if not isinstance(values, list):
        return False
    haystack = [str(value) for value in values]
    return all(any(item in value for value in haystack) for item in required)


def flags_valid(document: dict[str, Any]) -> bool:
    return all(document.get(flag) is True for flag in TRUE_FLAGS) and all(document.get(flag) is False for flag in FALSE_FLAGS)


def timeline_counts(timeline: dict[str, Any]) -> tuple[int, int, str]:
    events = timeline.get("events")
    warnings = timeline.get("warnings")
    event_count = timeline.get("event_count")
    if not isinstance(event_count, int) and isinstance(events, list):
        event_count = len(events)
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    latest_event = ""
    if isinstance(events, list) and events:
        latest = events[-1]
        if isinstance(latest, dict):
            latest_event = str(latest.get("event_time", ""))
    if not latest_event:
        latest_event = str(timeline.get("generated_at", ""))
    return int(event_count or 0), warning_count, latest_event


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
    required_paths = (
        list(REQUIRED_FILES.values())
        + VOL7_DOCS
        + VOL7_SCHEMAS
        + VOL7_FIXTURES
        + VOL7_VALIDATORS
        + STATIC_SHELL_FILES
    )
    missing = sorted({path for path in required_paths if not (REPO_ROOT / path).exists()})
    require(not missing, "required_files", "all Phase 7.8, Vol.7 artifact, validator, cockpit, and static shell files exist", failures)
    if missing:
        for path in missing:
            print(f"Missing: {path}")
        return 1

    handoff_schema = load_json(REQUIRED_FILES["handoff_schema"])
    vol8_schema = load_json(REQUIRED_FILES["vol8_schema"])
    handoff = load_json(REQUIRED_FILES["handoff_fixture"])
    vol8 = load_json(REQUIRED_FILES["vol8_fixture"])
    backfeed = load_json(REQUIRED_FILES["backfeed_fixture"])
    record = load_json(REQUIRED_FILES["record"])
    snapshot = load_json(REQUIRED_FILES["snapshot_qa"])
    completion = load_json(REQUIRED_FILES["completion_gate"])
    latest_state = load_json(REQUIRED_FILES["latest_state"])
    runtime_timeline = load_json(REQUIRED_FILES["runtime_timeline"])
    view_model = load_json(REQUIRED_FILES["view_model"])
    shell_texts = {path: read_text(path) for path in STATIC_SHELL_FILES}
    shell_text = "\n".join(shell_texts.values())
    handoff_doc = read_text(REQUIRED_FILES["handoff_doc"])
    phase_doc = read_text(REQUIRED_FILES["phase_doc"])

    require(required_fields_present(handoff, handoff_schema), "handoff_schema_fields", "Vol.7 handoff summary fixture includes all schema-required fields", failures)
    require(required_fields_present(vol8, vol8_schema), "vol8_schema_fields", "Vol.8 entry readiness fixture includes all schema-required fields", failures)
    require(required_fields_present(record, handoff_schema), "record_handoff_schema_fields", "runtime record includes all handoff schema-required fields", failures)

    for name, document in [("handoff", handoff), ("record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses Phase 7.8 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("vol7_status") == "completed", f"{name}_vol7_status", f"{name} marks Vol.7 completed", failures)
        require(document.get("handoff_status") == "ready", f"{name}_handoff_status", f"{name} handoff status is ready", failures)
        require(document.get("completed_phase_count") == 9, f"{name}_completed_phase_count", f"{name} completed phase count is 9", failures)
        require(contains_all_substrings(document.get("completed_phases"), REQUIRED_PHASES), f"{name}_completed_phases", f"{name} lists all nine Vol.7 phases", failures)
        require(document.get("timeline_warning_count") == 0, f"{name}_timeline_warnings", f"{name} timeline warnings remain 0", failures)
        require(document.get("snapshot_qa_status") == "passed", f"{name}_snapshot_qa", f"{name} carries passed snapshot QA", failures)
        require(document.get("completion_readiness") == "ready_for_handoff", f"{name}_completion_readiness", f"{name} carries ready_for_handoff completion readiness", failures)
        require(document.get("ldd_backfeed_coverage") == "passed", f"{name}_ldd_backfeed", f"{name} marks LDD backfeed coverage passed", failures)
        require(document.get("forbidden_scope_absence_status") == "passed", f"{name}_forbidden_absence", f"{name} marks forbidden scope absence passed", failures)
        require(document.get("warnings") == [] and document.get("errors") == [], f"{name}_warnings_errors", f"{name} warnings and errors are empty", failures)
        require(flags_valid(document), f"{name}_flags", f"{name} preserves required static flags", failures)

    require(vol8.get("phase") == PHASE, "vol8_phase", "Vol.8 readiness fixture uses Phase 7.8 phase label", failures)
    require(vol8.get("baseline_commit") == BASELINE_COMMIT, "vol8_baseline", "Vol.8 readiness fixture baseline commit matches Phase 7.7", failures)
    require(vol8.get("vol8_entry_readiness") == "ready_with_limits", "vol8_readiness", "Vol.8 entry readiness is ready_with_limits", failures)
    require(vol8.get("recommended_next_volume") == "Vol.8", "vol8_next_volume", "recommended next volume is Vol.8", failures)
    require(vol8.get("recommended_next_chat_title") == NEXT_CHAT_TITLE, "vol8_next_chat", "recommended next chat title is exact", failures)
    require(vol8.get("inherits_static_shell_boundary") is True, "vol8_inherits_boundary", "Vol.8 inherits the static shell boundary", failures)
    require(vol8.get("requires_explicit_approval_for_expansion") is True, "vol8_expansion_approval", "Vol.8 expansion requires explicit approval", failures)
    require(contains_all(vol8.get("forbidden_scope"), VOL8_FORBIDDEN_SCOPE), "vol8_forbidden_scope", "Vol.8 readiness fixture lists all forbidden scopes", failures)
    require(vol8.get("warnings") == [] and vol8.get("errors") == [], "vol8_warnings_errors", "Vol.8 readiness warnings and errors are empty", failures)
    require(flags_valid(vol8), "vol8_flags", "Vol.8 readiness fixture preserves required static flags", failures)

    require(backfeed.get("latest_twos_phase") == PHASE, "backfeed_phase", "final TWOS/LDD status update uses Phase 7.8 phase label", failures)
    require(backfeed.get("latest_commit_after_push") == "<PHASE_7_8_COMMIT_SHA_AFTER_PUSH>", "backfeed_commit_placeholder", "final TWOS/LDD status update carries the post-push commit placeholder", failures)
    require(backfeed.get("origin_main_status") == "synchronized", "backfeed_origin", "origin/main status is synchronized", failures)
    require(backfeed.get("working_tree_status") == "clean", "backfeed_worktree", "working tree status is clean", failures)
    require(backfeed.get("runtime_records") == 108 and backfeed.get("timeline_events") == 108, "backfeed_counts", "backfeed records/timeline counts are 108", failures)
    require(backfeed.get("timeline_warnings") == 0, "backfeed_warnings", "backfeed timeline warnings are 0", failures)
    require(backfeed.get("vol7_status") == "completed", "backfeed_vol7_completed", "backfeed marks Vol.7 completed", failures)
    require(backfeed.get("vol8_recommended_chat") == NEXT_CHAT_TITLE, "backfeed_next_chat", "backfeed carries recommended Vol.8 chat title", failures)
    require(contains_all(backfeed.get("ldd_duxd_backfeed_coverage"), LDD_BACKFEED_ITEMS), "backfeed_coverage_items", "backfeed carries all LDD DUXD coverage items", failures)
    require(contains_all(backfeed.get("forbidden_scope"), VOL8_FORBIDDEN_SCOPE), "backfeed_forbidden_scope", "backfeed carries all forbidden scopes", failures)
    require(flags_valid(backfeed), "backfeed_flags", "backfeed preserves required static flags", failures)

    require(snapshot.get("snapshot_qa_status") == "passed", "snapshot_qa_baseline", "Phase 7.7 snapshot QA remains passed", failures)
    require(completion.get("vol7_completion_readiness") == "ready_for_handoff", "completion_gate_baseline", "Phase 7.7 completion readiness remains ready_for_handoff", failures)

    require(all((REPO_ROOT / path).exists() for path in VOL7_DOCS), "vol7_documents", "all Vol.7 documents from 7.0 through 7.8 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_SCHEMAS), "vol7_schemas", "all Vol.7 schemas from 7.0 through 7.8 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_FIXTURES), "vol7_fixtures", "all Vol.7 fixtures from 7.0 through 7.8 exist", failures)
    require(all((REPO_ROOT / path).exists() for path in VOL7_VALIDATORS), "vol7_validators", "all Vol.7 validators from 7.0 through 7.8 exist", failures)

    shell_dirs = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "static_shell").glob("*") if path.is_dir())
    require(shell_dirs == ["static_shell/ldd"], "static_shell_isolation", "local static shell remains isolated under static_shell/ldd/", failures)

    doc_text = f"{handoff_doc}\n{phase_doc}"
    require(SCOPE_REMINDER in shell_text and SCOPE_REMINDER in doc_text, "ldd_scope", "LDD full-market scope reminder remains explicit", failures)
    require(all(item in str(handoff.get("ldd_backfeed_coverage_items", [])) for item in LDD_BACKFEED_ITEMS), "ldd_backfeed_fixture", "handoff fixture represents all LDD DUXD coverage items", failures)
    require(NEXT_CHAT_TITLE in doc_text and NEXT_CHAT_TITLE in str(vol8) and NEXT_CHAT_TITLE in str(backfeed), "recommended_next_chat", "recommended next chat title is present in docs and fixtures", failures)

    forbidden_findings = scan_static_shell(shell_texts)
    require(not forbidden_findings, "no_forbidden_static_patterns", "no fetch, XHR, WebSocket, EventSource, remote import, endpoint, credential form, executable control, mutation control, publish control, package, server, scheduler, or worker pattern appears", failures)
    for finding in forbidden_findings:
        print(f"Forbidden finding: {finding}")
        failures.append(finding)

    event_count, warning_count, latest_event = timeline_counts(runtime_timeline)
    require(event_count in {107, 108}, "current_timeline_count", "current timeline count is baseline 107 or post-handoff 108", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {PHASE77_TIMESTAMP, PHASE78_TIMESTAMP}, "current_latest_event", "current latest event is Phase 7.7 or Phase 7.8 timestamp", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint remains unchanged", failures)
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint remains unchanged", failures)
    require(view_model.get("portfolio_mode", {}).get("operating_mode") == OPERATING_MODE and view_model.get("portfolio_mode", {}).get("current") == PORTFOLIO_MODE, "view_model_modes", "view model modes remain unchanged", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all forbidden implementation/live/trading/credential non-goals as false", failures)

    print()
    if failures:
        print("Vol.7 handoff and Vol.8 readiness validation failed.")
    else:
        print("Vol.7 handoff and Vol.8 readiness validation passed.")
    print("Checks: 50")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Vol.7 status: {handoff.get('vol7_status')}")
    print(f"Vol.7 handoff status: {handoff.get('handoff_status')}")
    print(f"Vol.8 entry readiness: {vol8.get('vol8_entry_readiness')}")
    print(f"Final TWOS/LDD backfeed fixture: {backfeed.get('backfeed_id')}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Customer-facing readiness: false")
    print("Local static shell remains fixture-only/read-only/no-network.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
