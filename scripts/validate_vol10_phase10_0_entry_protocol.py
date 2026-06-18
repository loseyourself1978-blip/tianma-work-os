#!/usr/bin/env python3
"""Validate Vol.10 Phase 10.0 entry protocol and milestone plan artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.10 Phase 10.0"
BASELINE_COMMIT = "a183735f7afe68b768143d2455990cbea75c9056"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

MILESTONE_DOC = "docs/runtime/VOL10_MILESTONE_PLAN_v0.1.md"
ENTRY_DOC = "docs/runtime/VOL10_VOLUME_ENTRY_PROTOCOL_REVIEW_v0.1.md"
MILESTONE_SCHEMA = "schemas/vol10_milestone_plan.schema.json"
ENTRY_SCHEMA = "schemas/vol10_volume_entry_protocol_review.schema.json"
MILESTONE_FIXTURE = "mock_consumers/ldd/vol10_milestone_plan.json"
ENTRY_FIXTURE = "mock_consumers/ldd/vol10_volume_entry_protocol_review.json"
RECORD_PATH = "records/ldd/2026-06-18/vol10_phase10_0_volume_entry_protocol_and_milestone_plan.json"
VALIDATOR_PATH = "scripts/validate_vol10_phase10_0_entry_protocol.py"
WRAPPER_PATH = "scripts/validate_vol10_phase10_0_entry_protocol.sh"
INDEX_PATH = "INDEX.md"
FEATURE_INVENTORY_DOC = "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md"

REQUIRED_FILES = [
    MILESTONE_DOC,
    ENTRY_DOC,
    MILESTONE_SCHEMA,
    ENTRY_SCHEMA,
    MILESTONE_FIXTURE,
    ENTRY_FIXTURE,
    RECORD_PATH,
    VALIDATOR_PATH,
    WRAPPER_PATH,
]

JSON_PATHS = [MILESTONE_FIXTURE, ENTRY_FIXTURE, RECORD_PATH]
SCHEMA_PATHS = [MILESTONE_SCHEMA, ENTRY_SCHEMA]
MOCK_FIXTURES = [MILESTONE_FIXTURE, ENTRY_FIXTURE]

REQUIRED_ENTRY_CHECKS = [
    "volume_milestone_plan",
    "principle_registry_review",
    "roadmap_alignment_review",
    "prior_volume_handoff_review",
    "scope_boundary_review",
    "forbidden_scope_review",
    "source_of_truth_review",
    "validation_plan",
    "open_questions_and_update_candidates",
]

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
    "roadmap_phase_vs_runtime_volume_taxonomy",
]

REQUIRED_PHASE_LADDER = [
    "Vol.10 Phase 10.0",
    "Vol.10 Phase 10.1",
    "Vol.10 Phase 10.2",
    "Vol.10 Phase 10.3",
    "Vol.10 Phase 10.4",
    "Vol.10 Phase 10.5",
    "Vol.10 Phase 10.x",
]

TRADING_IMPACT_FLAGS = [
    "trading_facts_changed",
    "portfolio_state_changed",
    "execution_ledger_changed",
    "cash_state_changed",
    "broker_connection_changed",
    "binance_connection_changed",
]

FORBIDDEN_SCOPE_FIELDS = [
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
    "production_deployment_capability",
]

FORBIDDEN_TRUE_FIELDS = set(FORBIDDEN_SCOPE_FIELDS) | {
    "production_deployment",
    "network_allowed",
    "execution_allowed",
    "future_gate_activation",
    "phase10_1_started",
    "live_runtime_execution_capability",
}

FORBIDDEN_POSITIVE_SNIPPETS = [
    '"customer_facing_readiness": true',
    "customer_facing_readiness = true",
    "customer-facing readiness: true",
    '"live_runtime_execution_frameworks": 1',
    '"live_runtime_execution_capability": true',
    '"future_gate_activation": true',
    '"phase10_1_started": true',
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
            if key == "phase10_1_started" and child is not False:
                errors.append(f"{child_path} is not false")
            if key == "live_runtime_execution_capability" and child is not False:
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
    emit("required_files", not missing, "all Phase 10.0 required files exist" if not missing else f"missing {missing}", errors)

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
        emit(f"mock_phase_{Path(path).name}", PHASE in text, f"{path} contains required Phase 10.0 name", errors)
        emit(f"mock_commit_{Path(path).name}", BASELINE_COMMIT in text, f"{path} contains required Vol.9 Phase 9.10 commit hash", errors)

    milestone = parsed_json.get(MILESTONE_FIXTURE, {})
    milestone_baseline = milestone.get("baseline", {})
    baseline_ok = (
        milestone_baseline.get("latest_commit_before_phase") == BASELINE_COMMIT
        and milestone_baseline.get("runtime_records_baseline_before_phase") == 123
        and milestone_baseline.get("vol9_status") == "completed"
        and milestone_baseline.get("vol10_entry_readiness") == "ready_with_limits"
    )
    emit("milestone_baseline", baseline_ok, "milestone plan records required baseline commit and runtime baseline 123", errors)

    phase_ladder = milestone.get("phase_ladder", [])
    ladder_phases = [entry.get("phase") for entry in phase_ladder if isinstance(entry, dict)]
    missing_ladder = [phase for phase in REQUIRED_PHASE_LADDER if phase not in ladder_phases]
    later_phase_errors = [
        entry.get("phase")
        for entry in phase_ladder
        if isinstance(entry, dict)
        and entry.get("phase") != "Vol.10 Phase 10.0"
        and (entry.get("status") != "planned_only" or entry.get("phase_started") is not False)
    ]
    emit("phase_ladder_present", not missing_ladder, "Vol.10 phase ladder includes required planned phases" if not missing_ladder else f"missing {missing_ladder}", errors)
    emit("future_phases_planned_only", not later_phase_errors, "future Vol.10 phases are planned_only and not started" if not later_phase_errors else f"bad future phase entries {later_phase_errors}", errors)

    roadmap = milestone.get("roadmap_alignment", {})
    roadmap_ok = (
        "Roadmap Phase 1 - Product Blueprint and MVP Scope" in roadmap.get("supports_roadmap_phases", [])
        and "Roadmap Phase 2 - Manual Prototype and Real Scenario Validation" in roadmap.get("supports_roadmap_phases", [])
        and roadmap.get("roadmap_phase_3_mvp_build_activated") is False
        and roadmap.get("roadmap_phase_4_multi_model_execution_layer_activated") is False
        and roadmap.get("roadmap_phase_5_ecosystem_public_collaboration_activated") is False
    )
    emit("roadmap_alignment", roadmap_ok, "Vol.10 supports Roadmap Phase 1/2 only and does not activate Phase 3/4/5", errors)

    entry = parsed_json.get(ENTRY_FIXTURE, {})
    entry_checks = entry.get("volume_entry_checks", {})
    missing_checks = [check for check in REQUIRED_ENTRY_CHECKS if entry_checks.get(check) is not True]
    emit("volume_entry_checks", not missing_checks, "all required Volume Entry Protocol checks are present" if not missing_checks else f"missing or false {missing_checks}", errors)

    principle_groups = {
        item.get("principle_group")
        for item in entry.get("principle_review", [])
        if isinstance(item, dict)
    }
    missing_groups = [group for group in REQUIRED_PRINCIPLE_GROUPS if group not in principle_groups]
    malformed_principles = [
        item.get("principle_group", "<missing>")
        for item in entry.get("principle_review", [])
        if isinstance(item, dict)
        and not all(key in item for key in ["drift_risk", "ambiguity", "update_candidate", "entry_decision"])
    ]
    emit("principle_review_present", not missing_groups, "required principle groups are reviewed" if not missing_groups else f"missing {missing_groups}", errors)
    emit("principle_review_fields", not malformed_principles, "principle review records drift risk, ambiguity, update candidate, and decision" if not malformed_principles else f"malformed {malformed_principles}", errors)

    entry_roadmap = entry.get("roadmap_alignment_review", {})
    entry_roadmap_ok = (
        entry_roadmap.get("supports_roadmap_phase_1_static_blueprint") is True
        and entry_roadmap.get("supports_roadmap_phase_2_manual_prototype_validation") is True
        and entry_roadmap.get("roadmap_phase_3_mvp_build_activated") is False
        and entry_roadmap.get("roadmap_phase_4_multi_model_execution_layer_activated") is False
        and entry_roadmap.get("roadmap_phase_5_ecosystem_public_collaboration_activated") is False
        and entry_roadmap.get("taxonomy_layers_distinct") is True
    )
    emit("entry_roadmap_review", entry_roadmap_ok, "entry review preserves roadmap alignment and taxonomy separation", errors)

    sot = entry.get("source_of_truth_review", {})
    sot_ok = (
        sot.get("twos_runtime_product_sot_must_never_override_ldd_trading_execution_sot") is True
        and sot.get("ldd_trading_execution_sot_must_never_override_twos_runtime_product_sot") is True
        and sot.get("product_runtime_records_override_trading_facts") is False
        and sot.get("ldd_trading_facts_imply_product_readiness") is False
        and sot.get("quote_type_boundaries_preserved_as_future_static_requirements_only") is True
        and sot.get("execution_evidence_boundaries_preserved_as_future_static_requirements_only") is True
    )
    emit("source_of_truth_separation", sot_ok, "TWOS runtime/product SoT remains separate from LDD trading/execution SoT", errors)

    forbidden = entry.get("forbidden_scope_review", {})
    bad_forbidden = [field for field in FORBIDDEN_SCOPE_FIELDS if forbidden.get(field) is not False]
    emit("forbidden_scope_blocked", forbidden.get("all_forbidden_scope_blocked") is True and not bad_forbidden, "all forbidden scope fields are explicitly blocked" if not bad_forbidden else f"not false {bad_forbidden}", errors)

    validation_plan = entry.get("validation_plan", {})
    commands = validation_plan.get("required_commands", [])
    validation_plan_ok = (
        "bash scripts/validate_runtime_records.sh" in commands
        and "bash scripts/validate_vol10_phase10_0_entry_protocol.sh" in commands
        and "bash scripts/validate_vol9_phase9_10_handoff_and_vol10_readiness.sh" in commands
        and validation_plan.get("phase10_1_not_started_required") is True
    )
    emit("validation_plan", validation_plan_ok, "validation plan includes required runtime, Phase 10.0, and Vol.9 closeout validators", errors)

    phase10_1_not_started = (
        milestone.get("phase10_1_started") is False
        and entry.get("phase10_1_started") is False
    )
    emit("phase10_1_not_started", phase10_1_not_started, "Phase 10.0 artifacts record Phase 10.1 as not started", errors)

    record = parsed_json.get(RECORD_PATH, {})
    record_ok = (
        record.get("record_type") == "vol10_phase10_0_volume_entry_protocol_milestone_plan"
        and record.get("runtime_records_baseline_before_phase") == 123
        and record.get("runtime_records_baseline_after_phase") == 124
        and record.get("vol10_milestone_plan_created") is True
        and record.get("vol10_volume_entry_protocol_review_created") is True
        and record.get("vol10_validation_plan_created") is True
        and record.get("phase10_1_started") is False
        and record.get("customer_facing_readiness") is False
        and record.get("live_runtime_execution_frameworks") == 0
        and record.get("live_runtime_execution_capability") is False
        and record.get("static_shell_mode") == STATIC_SHELL_MODE
    )
    emit("runtime_record", record_ok, "runtime record advances baseline 123 to 124 and preserves non-activation", errors)

    trading_flags_ok = all(record.get(flag) is False for flag in TRADING_IMPACT_FLAGS)
    emit("record_trading_impact_flags", trading_flags_ok, "runtime record has all trading impact flags set to false", errors)

    json_forbidden_errors = []
    for path, document in parsed_json.items():
        json_forbidden_errors.extend(f"{path}: {error}" for error in nested_forbidden_true_errors(document))
    emit("forbidden_enabled_json_flags", not json_forbidden_errors, "JSON artifacts do not enable forbidden capabilities" if not json_forbidden_errors else "; ".join(json_forbidden_errors), errors)

    scan_paths = [
        MILESTONE_DOC,
        ENTRY_DOC,
        MILESTONE_SCHEMA,
        ENTRY_SCHEMA,
        MILESTONE_FIXTURE,
        ENTRY_FIXTURE,
        RECORD_PATH,
        INDEX_PATH,
        FEATURE_INVENTORY_DOC,
    ]
    snippet_hits = []
    for path in scan_paths:
        if not (REPO_ROOT / path).exists():
            continue
        text = read_text(path)
        for snippet in FORBIDDEN_POSITIVE_SNIPPETS:
            if snippet in text:
                snippet_hits.append(f"{path}: {snippet}")
    emit("forbidden_enabled_snippets", not snippet_hits, "no forbidden live/runtime/customer-facing capability appears as enabled" if not snippet_hits else "; ".join(snippet_hits), errors)

    index_text = read_text(INDEX_PATH)
    index_required = [
        MILESTONE_DOC,
        ENTRY_DOC,
        MILESTONE_FIXTURE,
        ENTRY_FIXTURE,
        RECORD_PATH,
        VALIDATOR_PATH,
    ]
    index_missing = [item for item in index_required if item not in index_text]
    emit("index_references", not index_missing, "INDEX.md references the new Phase 10.0 documents, fixtures, record, and validator" if not index_missing else f"missing {index_missing}", errors)

    inventory_text = read_text(FEATURE_INVENTORY_DOC)
    inventory_ok = MILESTONE_DOC in inventory_text and ENTRY_DOC in inventory_text
    emit("feature_inventory_entry_visibility", inventory_ok, "feature inventory reading path references Vol.10 entry docs", errors)

    docs_required = {
        MILESTONE_DOC: [
            "Static Product Blueprint Consolidation & Codex Execution Planning Layer",
            "Vol.10 remains static/read-only/no-live by default.",
            "Vol.10 does not activate Roadmap Phase 3 MVP Build",
        ],
        ENTRY_DOC: [
            "Phase 10.1 is not started in Phase 10.0.",
            "TWOS runtime/product SoT must never override LDD trading/execution SoT.",
            "LDD trading/execution SoT must never override TWOS runtime/product SoT.",
        ],
    }
    doc_missing = []
    for path, snippets in docs_required.items():
        text = read_text(path)
        doc_missing.extend(f"{path}: {snippet}" for snippet in snippets if snippet not in text)
    emit("required_doc_content", not doc_missing, "required Vol.10 entry doc content is present" if not doc_missing else "; ".join(doc_missing), errors)

    if errors:
        print("\nVol.10 Phase 10.0 entry protocol validation failed.")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\nVol.10 Phase 10.0 entry protocol validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
