#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.5 local static shell review and hardening."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.5 - Local Static Shell Review, Accessibility, Guardrail Hardening, and LDD Post-Close DUXD Backfeed"
BASELINE_COMMIT = "9de6673708ca2449701e52f41f9e2bca3787a879"
REVIEW_TIMESTAMP = "2026-06-16T09:03:34+08:00"
DEMO_PACK_TIMESTAMP = "2026-06-16T10:05:33+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
BASELINE_TIMELINE_EVENT = "2026-06-15T18:12:39+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."

REQUIRED_FILES = {
    "doc": "docs/runtime/VOL7_PHASE7_5_LOCAL_STATIC_SHELL_REVIEW_ACCESSIBILITY_GUARDRAIL_HARDENING_AND_LDD_BACKFEED_v0.1.md",
    "schema": "schemas/vol7_local_static_shell_review_report.schema.json",
    "report": "mock_consumers/ldd/vol7_local_static_shell_review_report.json",
    "record": "records/ldd/2026-06-15/vol7_phase7_5_local_static_shell_review_accessibility_guardrail_hardening_and_ldd_backfeed.json",
    "validator": "scripts/validate_vol7_local_static_shell_review.py",
    "wrapper": "scripts/validate_vol7_local_static_shell_review.sh",
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

STATUS_FIELDS = [
    "review_status",
    "accessibility_review_status",
    "guardrail_visibility_status",
    "static_safety_copy_status",
    "quote_drift_clarity_status",
    "cash_defense_split_status",
    "transfer_pnl_separation_status",
    "position_state_correction_status",
    "opportunity_cost_tracker_status",
    "rule_compliance_opportunity_capture_separation_status",
    "zero_position_candidate_radar_status",
    "forbidden_chase_list_status",
    "ipo_new_listing_radar_status",
    "hk_exposure_display_status",
    "forbidden_affordance_absence_status",
    "network_absence_status",
    "credential_absence_status",
    "execution_absence_status",
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

QUOTE_TYPES = [
    "holding_quote",
    "watchlist_quote",
    "night_session_quote",
    "premarket_quote",
    "executable_order_book_quote",
    "final_filled_order_price",
]

OPPORTUNITY_CANDIDATES = ["SOXL", "GDXU", "GGLL", "GLD", "UGL", "INTC", "SPCX", "MU", "DRAM"]

FORBIDDEN_PATTERNS = {
    "fetch_call": re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    "xml_http_request": re.compile(r"XMLHttpRequest", re.IGNORECASE),
    "websocket": re.compile(r"\bWebSocket\s*\(", re.IGNORECASE),
    "event_source": re.compile(r"\bEventSource\s*\(", re.IGNORECASE),
    "remote_import_or_cdn": re.compile(r"https?://|//cdn\.|unpkg\.com|jsdelivr\.net", re.IGNORECASE),
    "api_endpoint_reference": re.compile(r"(/api/|api/v[0-9]|graphql|endpoint_url)", re.IGNORECASE),
    "credential_input": re.compile(r"<input|<form|type=[\"']password|name=[\"']?(api[_-]?key|token|password|credential)", re.IGNORECASE),
    "button_element": re.compile(r"<button|createElement\([\"']button[\"']\)", re.IGNORECASE),
}

PACKAGE_OR_SERVER_NAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "vite.config.js",
    "next.config.js",
    "server.js",
    "worker.js",
    "scheduler.js",
}


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_json(path: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def require(condition: bool, check_id: str, success: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {success}")
    else:
        print(f"FAIL {check_id}: {success}")
        fail(check_id, failures)


def contains_all(values: Any, required: list[str]) -> bool:
    if not isinstance(values, list):
        return False
    haystack = {str(item) for item in values}
    return all(item in haystack for item in required)


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
        for name, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path}: {name}")
    shell_dir = REPO_ROOT / "static_shell" / "ldd"
    for path in shell_dir.rglob("*"):
        if path.is_file() and path.name in PACKAGE_OR_SERVER_NAMES:
            findings.append(f"{rel(path)}: forbidden package/server/worker file")
    return findings


def main() -> int:
    failures: list[str] = []

    missing = [path for path in REQUIRED_FILES.values() if not (REPO_ROOT / path).exists()]
    missing.extend(path for path in STATIC_SHELL_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 7.5 review, schema, record, validator, cockpit, and static shell files exist", failures)
    if missing:
        for item in missing:
            fail(f"missing {item}", failures)
        return 1

    report = load_json(REQUIRED_FILES["report"])
    record = load_json(REQUIRED_FILES["record"])
    schema = load_json(REQUIRED_FILES["schema"])
    manifest = load_json(REQUIRED_FILES["manifest"])
    timeline = load_json(REQUIRED_FILES["runtime_timeline"])
    latest_state = load_json(REQUIRED_FILES["latest_state"])
    view_model = load_json(REQUIRED_FILES["view_model"])
    texts = {path: read_text(path) for path in STATIC_SHELL_FILES}
    doc_text = read_text(REQUIRED_FILES["doc"])
    shell_text = "\n".join(texts.values())

    required_schema_fields = schema.get("required", [])
    require(all(field in report for field in required_schema_fields), "report_schema_fields", "review report includes all schema-required fields", failures)
    require(all(field in record for field in required_schema_fields), "record_schema_fields", "runtime record includes all schema-required review fields", failures)

    for name, document in [("report", report), ("record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses Phase 7.5 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("review_timestamp") == REVIEW_TIMESTAMP, f"{name}_timestamp", f"{name} review timestamp is {REVIEW_TIMESTAMP}", failures)
        require(all(document.get(field) == "passed" for field in STATUS_FIELDS), f"{name}_statuses", f"{name} marks all required review statuses passed", failures)
        require(document.get("warnings") == [] and document.get("errors") == [], f"{name}_warning_error_empty", f"{name} warnings and errors are empty", failures)
        require(all(document.get(flag) is True for flag in TRUE_FLAGS), f"{name}_true_flags", f"{name} preserves required true static flags", failures)
        require(all(document.get(flag) is False for flag in FALSE_FLAGS), f"{name}_false_flags", f"{name} preserves required false safety flags", failures)
        require(document.get("active_checkpoint") == CHECKPOINT, f"{name}_checkpoint", f"{name} active checkpoint remains {CHECKPOINT}", failures)
        require(document.get("operating_mode") == OPERATING_MODE and document.get("portfolio_mode") == PORTFOLIO_MODE, f"{name}_modes", f"{name} modes match baseline", failures)

    require(contains_all(report.get("required_labels"), REQUIRED_LABELS), "report_required_labels", "review report includes all required guardrail labels", failures)
    require(all(label in shell_text for label in REQUIRED_LABELS), "shell_required_labels", "all required guardrail labels are visible in static shell files", failures)
    require(SCOPE_REMINDER in shell_text and report.get("ldd_scope_reminder") == SCOPE_REMINDER, "ldd_scope_reminder", "LDD full-market scope reminder remains explicit", failures)

    accessibility = report.get("accessibility_review", {})
    require(isinstance(accessibility, dict) and all(accessibility.get(key) is True for key in [
        "semantic_headings",
        "panel_landmarks",
        "keyboard_friendly_static_navigation",
        "clear_link_text",
        "no_hidden_critical_warnings",
        "no_color_only_safety_signaling",
        "no_hover_only_information",
        "readable_contrast_reviewed",
    ]), "accessibility_basics", "accessibility basics are represented", failures)
    require("skip-link" in shell_text and "aria-label" in shell_text and "role\", \"region\"" in shell_text, "shell_accessibility_markup", "static shell includes skip link, clear aria labels, and panel regions", failures)

    require("Execution source remains broker/Binance order page and final filled order records." in shell_text, "execution_sot_copy", "execution source-of-truth copy is visible", failures)
    require(all(item in shell_text for item in QUOTE_TYPES), "quote_type_tagging", "quote-drift layer includes holding, watchlist, night-session, premarket, executable order-book, and final filled order price", failures)

    cash = report.get("cash_defense_split_review", {})
    require(cash.get("cash_defense_split_extended_to_hk_required") is True, "cash_split_required", "cash-defense split extended to HK is required", failures)
    require("77.6%" in shell_text and "70.6%" in shell_text and "145700" in shell_text and "placeholder_fixture_only" in shell_text, "cash_split_values", "U.S., Binance, HK exposure, and total cross-account placeholder are represented", failures)

    transfer = report.get("transfer_pnl_separation_review", {})
    require(transfer.get("transfer_withdrawal_pnl_separation_required") is True, "transfer_split_required", "transfer/withdrawal P&L separation is required", failures)
    require("49.99 USDT" in shell_text and "completed transfer / withdrawal, not trading loss" in shell_text, "transfer_copy", "49.99 USDT withdrawal is account movement, not trading loss", failures)

    opportunity = report.get("opportunity_cost_tracker_review", {})
    require(opportunity.get("opportunity_cost_tracker_required") is True, "opportunity_tracker_required", "Opportunity Cost Tracker requirement exists", failures)
    require(contains_all(opportunity.get("candidates"), OPPORTUNITY_CANDIDATES), "opportunity_candidates", "Opportunity Cost Tracker includes all required candidates", failures)
    require(opportunity.get("separate_from_rule_compliance") is True and opportunity.get("hindsight_context_only") is True and opportunity.get("execution_advice") is False, "opportunity_boundary", "opportunity cost is hindsight/context only and separate from rule compliance", failures)

    compliance = report.get("rule_compliance_opportunity_capture_review", {})
    require(compliance.get("rule_compliance_opportunity_capture_separation_required") is True, "compliance_capture_required", "rule compliance and opportunity capture are separated", failures)
    require("9.5/10" in shell_text and "8.9/10" in shell_text and compliance.get("execution_logic") is False, "review_scores_static", "review scores are represented as static context only", failures)

    radar = report.get("zero_position_candidate_radar_review", {})
    require(radar.get("zero_position_candidate_radar_required") is True and radar.get("forbidden_chase_list_required") is True and radar.get("ipo_new_listing_radar_required") is True, "radar_requirements", "zero-position candidate radar, forbidden-chase list, and IPO/new-listing radar are required", failures)
    require("zero_position_not_residual_risk_valve" in shell_text and "closed_no_reopen" in shell_text and "70%" in shell_text, "position_corrections", "GGLL zero-position, ZEC closed/no-reopen, and USDT 70% floor remain explicit", failures)
    require("SPCX: IPO radar only" in shell_text and "do not sell GOOG/NVDA to fund it" in shell_text, "spcx_ipo_rule", "SPCX IPO radar limits are represented", failures)

    overlay = manifest.get("phase7_5_review_overlay", {})
    require(isinstance(overlay, dict) and overlay.get("review_phase") == PHASE, "manifest_overlay", "Phase 7.5 review overlay exists in skeleton manifest", failures)
    require(overlay.get("opportunity_cost_tracker_required") is True and overlay.get("cash_defense_split_extended_to_hk_required") is True, "manifest_overlay_requirements", "manifest overlay carries opportunity-cost and HK cash-defense requirements", failures)

    forbidden_findings = scan_static_shell(texts)
    require(not forbidden_findings, "no_forbidden_static_patterns", "no fetch, XHR, WebSocket, EventSource, remote import, endpoint, credential form, executable control, mutation control, publish control, package, server, scheduler, or worker pattern appears", failures)
    for finding in forbidden_findings:
        fail(finding, failures)

    event_count, warning_count, latest_event = timeline_counts(timeline)
    require(event_count in {104, 105, 106}, "current_timeline_count", "current timeline count is baseline 104, post-review 105, or post-demo-pack 106", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {BASELINE_TIMELINE_EVENT, REVIEW_TIMESTAMP, DEMO_PACK_TIMESTAMP}, "current_latest_event", "current latest event is baseline, Phase 7.5 review timestamp, or Phase 7.6 demo pack timestamp", failures)
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint is unchanged", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT or latest_state.get("checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint is unchanged", failures)
    require("Vol.7 Phase 7.6 - Local Static Shell Demo Pack and Operator Walkthrough" in doc_text, "phase76_handoff", "document hands off to Phase 7.6", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all forbidden implementation/live/trading/credential non-goals as false", failures)

    print()
    if failures:
        print("Vol.7 local static shell review validation failed.")
    else:
        print("Vol.7 local static shell review validation passed.")
    print("Checks: 49")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Review status: {report.get('review_status')}")
    print(f"Accessibility status: {report.get('accessibility_review_status')}")
    print(f"Guardrail visibility status: {report.get('guardrail_visibility_status')}")
    print(f"LDD backfeed covered: {bool(report.get('ldd_post_close_backfeed'))}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Customer-facing readiness: false")
    print("Local static shell remains fixture-only/read-only/no-network.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
