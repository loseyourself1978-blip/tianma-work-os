#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.10 handoff and Vol.10 readiness artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.10"
PHASE9_9_COMMIT = "f81351507c7775be6fdb034dcc34a5117a0788db"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

PHASE_DOC = "docs/runtime/VOL9_PHASE9_10_HANDOFF_SUMMARY_PRINCIPLE_ADHERENCE_REVIEW_AND_VOL10_READINESS_GATE_v0.1.md"
HANDOFF_DOC = "docs/runtime/VOL9_HANDOFF_SUMMARY_v0.1.md"
PRINCIPLE_DOC = "docs/runtime/VOL9_PRINCIPLE_ADHERENCE_REVIEW_v0.1.md"
VOL10_DOC = "docs/runtime/VOL10_ENTRY_READINESS_GATE_v0.1.md"
HANDOFF_SCHEMA = "schemas/vol9_handoff_summary.schema.json"
PRINCIPLE_SCHEMA = "schemas/vol9_principle_adherence_review.schema.json"
VOL10_SCHEMA = "schemas/vol10_entry_readiness_gate.schema.json"
HANDOFF_FIXTURE = "mock_consumers/ldd/vol9_handoff_summary.json"
PRINCIPLE_FIXTURE = "mock_consumers/ldd/vol9_principle_adherence_review.json"
VOL10_FIXTURE = "mock_consumers/ldd/vol10_entry_readiness_gate.json"
STATUS_UPDATE = "mock_consumers/ldd/twos_ldd_post_vol9_handoff_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_10_handoff_summary_principle_adherence_review_and_vol10_readiness_gate.json"
VALIDATOR_PATH = "scripts/validate_vol9_phase9_10_handoff_and_vol10_readiness.py"
WRAPPER_PATH = "scripts/validate_vol9_phase9_10_handoff_and_vol10_readiness.sh"
FEATURE_INVENTORY_DOC = "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md"

REQUIRED_FILES = [
    PHASE_DOC,
    HANDOFF_DOC,
    PRINCIPLE_DOC,
    VOL10_DOC,
    HANDOFF_SCHEMA,
    PRINCIPLE_SCHEMA,
    VOL10_SCHEMA,
    HANDOFF_FIXTURE,
    PRINCIPLE_FIXTURE,
    VOL10_FIXTURE,
    STATUS_UPDATE,
    RECORD_PATH,
    VALIDATOR_PATH,
    WRAPPER_PATH,
]

JSON_PATHS = [HANDOFF_FIXTURE, PRINCIPLE_FIXTURE, VOL10_FIXTURE, STATUS_UPDATE, RECORD_PATH]
SCHEMA_PATHS = [HANDOFF_SCHEMA, PRINCIPLE_SCHEMA, VOL10_SCHEMA]
MOCK_FIXTURES = [HANDOFF_FIXTURE, PRINCIPLE_FIXTURE, VOL10_FIXTURE, STATUS_UPDATE]

REQUIRED_PHASE_NUMBERS = [f"Vol.9 Phase 9.{index}" for index in range(1, 11)]

REQUIRED_PRINCIPLE_GROUPS = [
    "first_principles_and_product_thesis",
    "duxd_real_scenario_feedback_loop",
    "human_strategy_ai_execution_boundary",
    "source_of_truth_separation",
    "static_before_live_boundary",
    "no_live_implementation_without_gate",
    "customer_facing_readiness_false_until_gate",
    "memory_index_and_handoff_continuity",
    "volume_based_execution_and_handoff",
    "full_standalone_sync_after_correction",
    "ldd_full_market_scope",
    "execution_ledger_evidence_before_classification",
    "zero_fill_order_separation",
    "quote_type_tagging",
    "dream_sleeve_monitoring_only_boundary",
    "roadmap_phase_vs_runtime_volume_taxonomy",
]

REQUIRED_UPDATE_DECISIONS = {
    "full_standalone_sync_after_correction": "clarified_existing_principle",
    "roadmap_phase_vs_runtime_volume_taxonomy": "introduced_new_principle",
    "volume_entry_exit_review_protocol": "introduced_new_principle",
    "implemented_feature_inventory_visibility": "introduced_new_principle",
    "zero_fill_order_separation": "clarified_existing_principle",
    "dream_sleeve_monitoring_only_boundary": "clarified_existing_principle",
}

INDEX_REQUIRED_REFERENCES = [
    PHASE_DOC,
    HANDOFF_DOC,
    PRINCIPLE_DOC,
    VOL10_DOC,
    HANDOFF_FIXTURE,
    PRINCIPLE_FIXTURE,
    VOL10_FIXTURE,
    STATUS_UPDATE,
    RECORD_PATH,
    VALIDATOR_PATH,
]

TRADING_IMPACT_FLAGS = [
    "trading_facts_changed",
    "portfolio_state_changed",
    "execution_ledger_changed",
    "cash_state_changed",
    "broker_connection_changed",
    "binance_connection_changed",
]

FORBIDDEN_TRUE_FIELDS = {
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
    "login_auth",
    "runtime_mutation",
    "execution_trigger",
    "order_placement",
    "portfolio_modification",
    "background_worker",
    "scheduler",
    "notification_dispatcher",
    "github_issues",
    "github_projects_board",
    "package_manager_files",
    "build_tools",
    "frontend_framework",
    "network_dependency",
    "external_integration",
    "production_deployment",
    "production_deployment_capability",
    "network_allowed",
    "execution_allowed",
}

FORBIDDEN_POSITIVE_SNIPPETS = [
    '"customer_facing_readiness": true',
    "customer_facing_readiness = true",
    "customer-facing readiness: true",
    '"live_runtime_execution_frameworks": 1',
    '"future_gate_activation": true',
    '"network_allowed": true',
    '"execution_allowed": true',
    '"production_ui": true',
    '"customer_facing_ui": true',
    '"hosted_app": true',
    '"api_server": true',
    '"live_endpoint": true',
    '"external_api": true',
    '"broker_connection": true',
    '"binance_connection": true',
    '"live_market_data": true',
    '"trading_automation": true',
    '"credential_handling": true',
    '"login_auth": true',
    '"runtime_mutation": true',
    '"execution_trigger": true',
    '"order_placement": true',
    '"portfolio_modification": true',
    '"background_worker": true',
    '"scheduler": true',
    '"notification_dispatcher": true',
    '"github_issues": true',
    '"github_projects_board": true',
    '"package_manager_files": true',
    '"build_tools": true',
    '"frontend_framework": true',
    '"network_dependency": true',
    '"external_integration": true',
    '"production_deployment": true',
    '"production_deployment_capability": true',
]


def load_json(path_text: str) -> Any:
    with (REPO_ROOT / path_text).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path_text: str) -> str:
    return (REPO_ROOT / path_text).read_text(encoding="utf-8")


def emit(name: str, ok: bool, detail: str, errors: list[str]) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"{status} {name}: {detail}")
    if not ok:
        errors.append(f"{name}: {detail}")


def nested_forbidden_true_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_TRUE_FIELDS and child is True:
                errors.append(f"{child_path} is true")
            if key == "customer_facing_readiness" and child is not False:
                errors.append(f"{child_path} is not false")
            if key == "live_runtime_execution_frameworks" and child != 0:
                errors.append(f"{child_path} is not 0")
            if key == "future_gate_activation" and child is not False:
                errors.append(f"{child_path} is not false")
            if key == "static_shell_mode" and child != STATIC_SHELL_MODE:
                errors.append(f"{child_path} has unexpected static shell mode")
            errors.extend(nested_forbidden_true_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(nested_forbidden_true_errors(child, f"{path}[{index}]"))
    return errors


def main() -> int:
    errors: list[str] = []

    missing = [path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists()]
    emit("required_files", not missing, "all Phase 9.10 required files exist" if not missing else f"missing {missing}", errors)

    parsed_json: dict[str, Any] = {}
    for path in JSON_PATHS:
        try:
            parsed_json[path] = load_json(path)
            emit(f"json_parse_{Path(path).name}", True, f"{path} is parseable JSON", errors)
        except json.JSONDecodeError as exc:
            emit(f"json_parse_{Path(path).name}", False, f"{path} JSON parse failed: {exc}", errors)

    for path in SCHEMA_PATHS:
        try:
            schema = load_json(path)
            emit(f"schema_parse_{Path(path).name}", isinstance(schema, dict), f"{path} is parseable JSON object", errors)
        except json.JSONDecodeError as exc:
            emit(f"schema_parse_{Path(path).name}", False, f"{path} JSON parse failed: {exc}", errors)

    for path in MOCK_FIXTURES:
        text = read_text(path)
        emit(f"mock_phase_{Path(path).name}", PHASE in text, f"{path} contains required Phase 9.10 name", errors)
        emit(f"mock_commit_{Path(path).name}", PHASE9_9_COMMIT in text, f"{path} contains required Phase 9.9 commit hash", errors)

    handoff = parsed_json.get(HANDOFF_FIXTURE, {})
    timeline_phases = [entry.get("phase", "") for entry in handoff.get("phase_timeline", []) if isinstance(entry, dict)]
    missing_timeline = [phase for phase in REQUIRED_PHASE_NUMBERS if not any(phase in item for item in timeline_phases)]
    emit("handoff_created", handoff.get("vol9_handoff_summary_created") is True, "Vol.9 handoff fixture is created", errors)
    emit("handoff_status", handoff.get("vol9_status") == "completed", "Vol.9 handoff fixture marks Vol.9 completed", errors)
    emit("handoff_timeline", not missing_timeline, "Vol.9 handoff fixture has timeline entries for Phase 9.1 through Phase 9.10" if not missing_timeline else f"missing {missing_timeline}", errors)
    emit("handoff_boundaries", handoff.get("customer_facing_readiness") is False and handoff.get("live_runtime_execution_frameworks") == 0 and handoff.get("future_gate_activation") is False, "Vol.9 handoff fixture preserves non-activation boundaries", errors)

    principle = parsed_json.get(PRINCIPLE_FIXTURE, {})
    principle_groups = {entry.get("principle_group") for entry in principle.get("principle_adherence_matrix", []) if isinstance(entry, dict)}
    missing_groups = [group for group in REQUIRED_PRINCIPLE_GROUPS if group not in principle_groups]
    decisions = {
        entry.get("principle_or_topic"): entry.get("decision_class")
        for entry in principle.get("principle_update_decisions", [])
        if isinstance(entry, dict)
    }
    missing_decisions = [
        f"{topic}: {decision}"
        for topic, decision in REQUIRED_UPDATE_DECISIONS.items()
        if decisions.get(topic) != decision
    ]
    emit("principle_review_created", principle.get("vol9_principle_adherence_review_created") is True, "Vol.9 principle adherence fixture is created", errors)
    emit("principle_groups", not missing_groups, "Vol.9 principle adherence fixture includes all required principle groups" if not missing_groups else f"missing {missing_groups}", errors)
    emit("principle_update_decisions", not missing_decisions, "Vol.9 principle adherence fixture includes required principle update decisions" if not missing_decisions else f"missing {missing_decisions}", errors)

    vol10 = parsed_json.get(VOL10_FIXTURE, {})
    vol10_flags_ok = (
        vol10.get("vol10_entry_readiness_gate_created") is True
        and vol10.get("vol10_entry_readiness") == "ready_with_limits"
        and vol10.get("vol10_milestone_plan_required") is True
        and vol10.get("vol10_principle_review_required") is True
        and vol10.get("vol10_live_implementation_allowed_by_default") is False
        and vol10.get("vol10_customer_facing_readiness_allowed_by_default") is False
        and vol10.get("vol10_trading_execution_allowed_by_default") is False
    )
    emit("vol10_gate_flags", vol10_flags_ok, "Vol.10 readiness gate has required ready_with_limits and default-deny flags", errors)

    record = parsed_json.get(RECORD_PATH, {})
    record_ok = (
        record.get("record_type") == "vol9_phase9_10_handoff_summary_vol10_readiness_gate"
        and record.get("runtime_records_baseline_before_phase") == 122
        and record.get("runtime_records_baseline_after_phase") == 123
        and record.get("vol9_status") == "completed"
        and record.get("vol10_entry_readiness") == "ready_with_limits"
        and record.get("customer_facing_readiness") is False
        and record.get("live_runtime_execution_frameworks") == 0
        and record.get("static_shell_mode") == STATIC_SHELL_MODE
    )
    trading_flags_ok = all(record.get(flag) is False for flag in TRADING_IMPACT_FLAGS)
    emit("record_baseline", record_ok, "runtime record has required Phase 9.10 baseline and readiness fields", errors)
    emit("record_trading_impact_flags", trading_flags_ok, "runtime record has all trading impact flags set to false", errors)

    scan_paths = [path for path in REQUIRED_FILES if not path.startswith("scripts/")] + [FEATURE_INVENTORY_DOC]
    positive_hits: list[str] = []
    for path in scan_paths:
        text = read_text(path).lower()
        for snippet in FORBIDDEN_POSITIVE_SNIPPETS:
            if snippet.lower() in text:
                positive_hits.append(f"{path}: {snippet}")
    emit("forbidden_enabled_snippets", not positive_hits, "no forbidden live/runtime/customer-facing capability appears as enabled" if not positive_hits else "; ".join(positive_hits), errors)

    nested_errors: list[str] = []
    for path, value in parsed_json.items():
        nested_errors.extend(f"{path}: {item}" for item in nested_forbidden_true_errors(value))
    emit("forbidden_enabled_json_flags", not nested_errors, "JSON artifacts do not enable forbidden capabilities" if not nested_errors else "; ".join(nested_errors), errors)

    index_text = read_text("INDEX.md")
    missing_index_refs = [ref for ref in INDEX_REQUIRED_REFERENCES if ref not in index_text]
    emit("index_references", not missing_index_refs, "INDEX.md references the new Phase 9.10 documents and fixtures" if not missing_index_refs else f"missing {missing_index_refs}", errors)

    feature_inventory_text = read_text(FEATURE_INVENTORY_DOC)
    inventory_links_ok = HANDOFF_DOC in feature_inventory_text and VOL10_DOC in feature_inventory_text
    emit("feature_inventory_links", inventory_links_ok, "implemented feature inventory links to Vol.9 handoff and Vol.10 readiness gate", errors)

    status_lines = [
        "TWOS/LDD Runtime Status Backfeed Update｜Vol.9 Handoff & Vol.10 Readiness",
        "Vol.9 is completed.",
        "Vol.10 entry readiness is ready_with_limits.",
        "Vol.10 must begin with milestone planning and principle review.",
        "Vol.10 does not allow live implementation, customer-facing readiness, or trading execution by default.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "Future gate activation remains blocked.",
    ]
    status_text = read_text(STATUS_UPDATE)
    missing_status_lines = [line for line in status_lines if line not in status_text]
    emit("status_update_lines", not missing_status_lines, "post-Vol.9 handoff status update contains required LDD sync lines" if not missing_status_lines else f"missing {missing_status_lines}", errors)

    doc_requirements = {
        HANDOFF_DOC: ["# Vol.9 Handoff Summary", "Vol.9 is completed.", "Future gate activation remains false."],
        PRINCIPLE_DOC: ["# Vol.9 Principle Adherence Review", "full_standalone_sync_after_correction", "roadmap_phase_vs_runtime_volume_taxonomy"],
        VOL10_DOC: ["# Vol.10 Entry Readiness Gate", "Vol.10 entry readiness: ready_with_limits.", "Vol.10 does not allow live implementation by default."],
    }
    doc_missing: list[str] = []
    for path, snippets in doc_requirements.items():
        text = read_text(path)
        doc_missing.extend(f"{path}: {snippet}" for snippet in snippets if snippet not in text)
    emit("required_doc_content", not doc_missing, "required handoff, principle, and Vol.10 readiness doc content is present" if not doc_missing else "; ".join(doc_missing), errors)

    if errors:
        print("\nVol.9 Phase 9.10 handoff and Vol.10 readiness validation failed.")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\nVol.9 Phase 9.10 handoff and Vol.10 readiness validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
