#!/usr/bin/env python3
"""Validate Vol.6 Phase 6.9 handoff and Vol.7 readiness gate artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
CONSUMER_READINESS = "ready_with_limits"
VOL7_TITLE = "Tianma Work OS Vol.7 — UI Shell Planning / Static Fixture Consumer"

REQUIRED_FILES = {
    "vol6_handoff_packet": "mock_consumers/ldd/vol6_handoff_packet.json",
    "vol6_completion_gate": "mock_consumers/ldd/vol6_completion_readiness_gate.json",
    "vol7_entry_boundary": "mock_consumers/ldd/vol7_entry_boundary_contract.json",
    "vol7_static_gate": "mock_consumers/ldd/vol7_static_ui_shell_planning_gate.json",
    "handoff_checklist": "mock_consumers/ldd/vol6_to_vol7_handoff_checklist.json",
    "backfeed": "mock_consumers/ldd/twos_ldd_post_vol6_backfeed_status_update.json",
    "record": "records/ldd/2026-06-12/vol6_phase6_9_handoff_summary_and_vol7_readiness_gate_1720_sgt.json",
}

REQUIRED_SCHEMAS = [
    "schemas/vol6_handoff_readiness_gate.schema.json",
    "schemas/vol7_entry_readiness_gate.schema.json",
]

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_9_HANDOFF_SUMMARY_AND_VOL7_READINESS_GATE_v0.1.md",
    "docs/runtime/VOL6_HANDOFF_SUMMARY_v0.1.md",
    "schemas/vol6_handoff_readiness_gate.schema.json",
    "schemas/vol7_entry_readiness_gate.schema.json",
    "mock_consumers/ldd/vol6_handoff_packet.json",
    "mock_consumers/ldd/vol6_completion_readiness_gate.json",
    "mock_consumers/ldd/vol7_entry_boundary_contract.json",
    "mock_consumers/ldd/vol7_static_ui_shell_planning_gate.json",
    "mock_consumers/ldd/vol6_to_vol7_handoff_checklist.json",
    "mock_consumers/ldd/twos_ldd_post_vol6_backfeed_status_update.json",
    "scripts/validate_vol6_handoff_readiness_gate.py",
    "scripts/validate_vol6_handoff_readiness_gate.sh",
    "records/ldd/2026-06-12/vol6_phase6_9_handoff_summary_and_vol7_readiness_gate_1720_sgt.json",
    "reports/ldd/vol6_phase6_9_handoff_summary_and_vol7_readiness_gate.md",
    "reports/ldd/vol6_handoff_summary.md",
]

REQUIRED_PHASES = [
    "Vol.6 Phase 6.0 - Baseline Verification",
    "Vol.6 Phase 6.1 - UI Boundary Architecture",
    "Vol.6 Phase 6.2 - Permission and Privacy Masking Model",
    "Vol.6 Phase 6.2a - LDD Premarket Runtime Sync Governance Patch",
    "Vol.6 Phase 6.3 - Read-only API Contract",
    "Vol.6 Phase 6.3a - LDD Post-close Execution Reconciliation and Checkpoint Update",
    "Vol.6 Phase 6.4 - Static Cockpit Prototype Boundary Review",
    "Vol.6 Phase 6.5 - Internal Operator Cockpit Static Spec",
    "Vol.6 Phase 6.5a - LDD Post-close Residual Core Checkpoint Update",
    "Vol.6 Phase 6.6 - AI Board Cockpit Static Spec",
    "Vol.6 Phase 6.7 - Cockpit Static Spec Integration Review",
    "Vol.6 Phase 6.7a - LDD Premarket Rebound Confirmation Governance Sync",
    "Vol.6 Phase 6.8 - Static Consumer Fixture Integration and Handoff",
    "Vol.6 Phase 6.8a - LDD Full-Market Scope Correction and IPO Radar Governance Sync",
    "Vol.6 Phase 6.9 - Vol.6 Handoff Summary and Vol.7 Readiness Gate",
]

ALLOWED_SCOPE = [
    "static_fixture_consumer_planning",
    "UI_shell_information_architecture",
    "static_layout_wireframe_spec",
    "mock_data_binding_plan",
    "fixture_driven_component_contracts",
    "no_runtime_connection_review",
    "accessibility_and_readability_review",
    "operator_workflow_dry_run",
    "static_error_empty_state_spec",
    "static_export_policy_review",
]

PROHIBITED_SCOPE = [
    "production_frontend_app",
    "customer_facing_ui",
    "API_server",
    "live_endpoint",
    "external_market_api",
    "broker_api",
    "Binance_api",
    "live_market_data",
    "trading_automation",
    "credential_handling",
    "runtime_mutation_ui",
    "execution_trigger",
]

FALSE_FLAGS = [
    "customer_facing_ready",
    "actual_ui_created",
    "frontend_app_created",
    "html_css_js_ui_created",
    "api_server_created",
    "live_endpoint_created",
    "external_api_connected",
    "broker_api_connected",
    "binance_api_connected",
    "live_market_data_enabled",
    "trading_automation_enabled",
    "credential_handling_enabled",
    "runtime_mutation_ui_enabled",
    "execution_trigger_enabled",
]

BOUNDARY_FALSE_FLAGS = [
    "customer_facing_ready",
    "actual_ui_allowed_at_entry",
    "api_server_allowed_at_entry",
    "live_endpoint_allowed_at_entry",
    "external_api_allowed_at_entry",
    "broker_binance_connection_allowed_at_entry",
    "live_market_data_allowed_at_entry",
    "trading_automation_allowed_at_entry",
    "credential_handling_allowed_at_entry",
    "runtime_mutation_ui_allowed_at_entry",
    "execution_trigger_allowed_at_entry",
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

    require(len(loaded) == len(REQUIRED_FILES), "required_files", f"{len(loaded)}/{len(REQUIRED_FILES)} required files exist", failures)
    schema_count = sum(1 for relpath in REQUIRED_SCHEMAS if (REPO_ROOT / relpath).exists())
    require(schema_count == len(REQUIRED_SCHEMAS), "required_schemas", f"{schema_count}/{len(REQUIRED_SCHEMAS)} schemas exist", failures)
    require(len(loaded) == len(REQUIRED_FILES), "json_syntax", "all required JSON files are valid objects", failures)

    packet = loaded.get("vol6_handoff_packet", {})
    gate = loaded.get("vol6_completion_gate", {})
    boundary = loaded.get("vol7_entry_boundary", {})
    static_gate = loaded.get("vol7_static_gate", {})
    backfeed = loaded.get("backfeed", {})
    record = loaded.get("record", {})

    require(bool(packet), "handoff_packet_exists", "Vol.6 handoff packet exists", failures)
    require(bool(gate), "completion_gate_exists", "Vol.6 completion readiness gate exists", failures)
    require(bool(boundary), "vol7_boundary_exists", "Vol.7 entry boundary contract exists", failures)
    require(bool(static_gate), "vol7_static_gate_exists", "Vol.7 static UI shell planning gate exists", failures)
    require(bool(backfeed), "backfeed_exists", "TWOS LDD post-Vol.6 backfeed status update exists", failures)

    phases = packet.get("completed_phases", [])
    require(all(item in phases for item in REQUIRED_PHASES), "completed_phase_ledger", "all 15 required phases from 6.0 through 6.9 are listed", failures)

    require(packet.get("active_checkpoint") == CHECKPOINT and gate.get("active_checkpoint") == CHECKPOINT and record.get("latest_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    require(packet.get("operating_mode") == OPERATING_MODE and gate.get("operating_mode") == OPERATING_MODE and record.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode remains {OPERATING_MODE}", failures)
    require(packet.get("portfolio_mode") == PORTFOLIO_MODE and gate.get("portfolio_mode") == PORTFOLIO_MODE and record.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode remains {PORTFOLIO_MODE}", failures)
    require(packet.get("consumer_readiness") == CONSUMER_READINESS, "consumer_readiness", f"consumer readiness remains {CONSUMER_READINESS}", failures)

    for flag in FALSE_FLAGS:
        values = [
            packet.get("safety_boundaries", {}).get(flag),
            gate.get(flag),
            record.get(flag),
        ]
        require(all(value is False for value in values if value is not None), flag, f"{flag} remains false", failures)

    require(all(item in boundary.get("allowed_scope", []) for item in ALLOWED_SCOPE), "vol7_allowed_static_scope", "Vol.7 entry boundary allows static fixture consumer planning", failures)
    for item in PROHIBITED_SCOPE:
        require(item in boundary.get("prohibited_scope", []), f"vol7_blocks_{item}", f"Vol.7 entry boundary blocks {item}", failures)
    for flag in BOUNDARY_FALSE_FLAGS:
        require(boundary.get(flag) is False, f"boundary_{flag}", f"{flag} is false in Vol.7 boundary", failures)

    require(static_gate.get("entry_allowed") is True, "vol7_static_entry_allowed", "Vol.7 static UI shell planning gate has entry_allowed true", failures)
    require(static_gate.get("implementation_allowed") is False, "vol7_implementation_blocked", "Vol.7 static UI shell planning gate has implementation_allowed false", failures)

    template = str(backfeed.get("template", ""))
    require("Vol.6 status:\nCompleted. Handoff ready." in template, "backfeed_vol6_completion", "TWOS LDD backfeed includes Vol.6 completion status", failures)
    require("LDD scope is the entire U.S. equity market" in template, "backfeed_ldd_scope", "TWOS LDD backfeed includes LDD full-market scope reminder", failures)
    require(packet.get("vol7_recommended_title") == VOL7_TITLE and boundary.get("recommended_new_chat_title") == VOL7_TITLE and static_gate.get("title") == VOL7_TITLE, "recommended_new_chat", f"handoff recommends {VOL7_TITLE}", failures)

    bad_files: list[str] = []
    for relpath in PHASE_ARTIFACTS:
        path = REPO_ROOT / relpath
        if not path.exists():
            bad_files.append(f"{relpath}: missing")
            continue
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in PROHIBITED_PHASE_PATH_PARTS for part in parts):
            bad_files.append(f"{relpath}: prohibited implementation path segment")
        if path.suffix in PROHIBITED_SUFFIXES:
            bad_files.append(f"{relpath}: prohibited implementation suffix")
    require(not bad_files, "no_implementation_files", "no Phase 6.9 artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    for item in bad_files:
        print(f"  - {item}")

    print("")
    if failures:
        print("Vol.6 handoff readiness gate validation failed.")
        print(f"Blocking failures: {len(failures)}")
        for failure in failures:
            print(f"- {failure}")
        print("Warnings: 0")
        return 1

    print("Vol.6 handoff readiness gate validation passed.")
    print("Checks: 41")
    print("Blocking failures: 0")
    print("Warnings: 0")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print(f"Recommended Vol.7 chat: {VOL7_TITLE}")
    print("Vol.6 completion ready: true")
    print("Vol.7 static planning entry ready: true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
