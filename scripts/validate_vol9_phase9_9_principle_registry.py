#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.9 principle registry and Volume protocol artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.9"
PHASE9_8_COMMIT = "6180d40315879f44fd9731c5504a0a07006df51a"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

PHASE_DOC = "docs/runtime/VOL9_PHASE9_9_PRINCIPLE_REGISTRY_ROADMAP_VOLUME_TAXONOMY_AND_VOLUME_ENTRY_EXIT_PROTOCOL_v0.1.md"
PRINCIPLE_DOC = "docs/runtime/PRINCIPLE_REGISTRY_v0.1.md"
TAXONOMY_DOC = "docs/runtime/ROADMAP_PHASE_AND_RUNTIME_VOLUME_TAXONOMY_v0.1.md"
ENTRY_EXIT_DOC = "docs/runtime/VOLUME_ENTRY_EXIT_REVIEW_PROTOCOL_v0.1.md"
PRINCIPLE_SCHEMA = "schemas/principle_registry.schema.json"
TAXONOMY_SCHEMA = "schemas/roadmap_phase_runtime_volume_taxonomy.schema.json"
ENTRY_EXIT_SCHEMA = "schemas/volume_entry_exit_review_protocol.schema.json"
PRINCIPLE_FIXTURE = "mock_consumers/ldd/principle_registry.json"
TAXONOMY_FIXTURE = "mock_consumers/ldd/roadmap_phase_runtime_volume_taxonomy.json"
ENTRY_EXIT_FIXTURE = "mock_consumers/ldd/volume_entry_exit_review_protocol.json"
STATUS_UPDATE = "mock_consumers/ldd/twos_ldd_post_phase9_9_principle_registry_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_9_principle_registry_roadmap_volume_taxonomy_and_volume_entry_exit_protocol.json"
VALIDATOR_PATH = "scripts/validate_vol9_phase9_9_principle_registry.py"
WRAPPER_PATH = "scripts/validate_vol9_phase9_9_principle_registry.sh"
FEATURE_INVENTORY_DOC = "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md"

REQUIRED_FILES = [
    PHASE_DOC,
    PRINCIPLE_DOC,
    TAXONOMY_DOC,
    ENTRY_EXIT_DOC,
    PRINCIPLE_SCHEMA,
    TAXONOMY_SCHEMA,
    ENTRY_EXIT_SCHEMA,
    PRINCIPLE_FIXTURE,
    TAXONOMY_FIXTURE,
    ENTRY_EXIT_FIXTURE,
    STATUS_UPDATE,
    RECORD_PATH,
    VALIDATOR_PATH,
    WRAPPER_PATH,
]

JSON_PATHS = [
    PRINCIPLE_FIXTURE,
    TAXONOMY_FIXTURE,
    ENTRY_EXIT_FIXTURE,
    STATUS_UPDATE,
    RECORD_PATH,
]

SCHEMA_PATHS = [
    PRINCIPLE_SCHEMA,
    TAXONOMY_SCHEMA,
    ENTRY_EXIT_SCHEMA,
]

MOCK_FIXTURES = [
    PRINCIPLE_FIXTURE,
    TAXONOMY_FIXTURE,
    ENTRY_EXIT_FIXTURE,
    STATUS_UPDATE,
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
    "full_standalone_sync_after_correction",
    "ldd_full_market_scope",
    "execution_ledger_evidence_before_classification",
    "zero_fill_order_separation",
    "quote_type_tagging",
    "dream_sleeve_monitoring_only_boundary",
    "roadmap_phase_vs_runtime_volume_taxonomy",
]

ROADMAP_PHASE_LABELS = [
    "Phase 0",
    "Phase 1",
    "Phase 2",
    "Phase 3",
    "Phase 4",
    "Phase 5",
]

ENTRY_REQUIREMENTS = [
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

EXIT_REQUIREMENTS = [
    "volume_milestone_review",
    "completed_scope_review",
    "principle_adherence_review",
    "principle_drift_review",
    "principle_update_decision",
    "roadmap_alignment_review",
    "runtime_record_baseline_review",
    "feature_inventory_update_check",
    "handoff_summary",
    "next_volume_readiness_gate",
]

INDEX_REQUIRED_REFERENCES = [
    PHASE_DOC,
    PRINCIPLE_DOC,
    TAXONOMY_DOC,
    ENTRY_EXIT_DOC,
    PRINCIPLE_FIXTURE,
    TAXONOMY_FIXTURE,
    ENTRY_EXIT_FIXTURE,
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


def contains_required_text(path_text: str, snippets: list[str]) -> list[str]:
    text = read_text(path_text)
    return [snippet for snippet in snippets if snippet not in text]


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
    emit("required_files", not missing, "all Phase 9.9 required files exist" if not missing else f"missing {missing}", errors)

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
        emit(f"mock_phase_{Path(path).name}", PHASE in text, f"{path} contains required Phase 9.9 name", errors)
        emit(f"mock_commit_{Path(path).name}", PHASE9_8_COMMIT in text, f"{path} contains required Phase 9.8 commit hash", errors)

    registry = parsed_json.get(PRINCIPLE_FIXTURE, {})
    principles = registry.get("principles", [])
    groups = {principle.get("principle_group") for principle in principles if isinstance(principle, dict)}
    missing_groups = [group for group in REQUIRED_PRINCIPLE_GROUPS if group not in groups]
    emit("registry_created", registry.get("principle_registry_created") is True, "principle registry is created", errors)
    emit("registry_required_groups", not missing_groups, "principle registry includes all required principle groups" if not missing_groups else f"missing groups {missing_groups}", errors)

    principle_errors: list[str] = []
    for principle in principles:
        principle_id = principle.get("principle_id", "<missing>")
        if principle.get("review_required_at_volume_start") is not True:
            principle_errors.append(f"{principle_id} missing start review")
        if principle.get("review_required_at_volume_end") is not True:
            principle_errors.append(f"{principle_id} missing end review")
        if principle.get("customer_facing_readiness") is not False:
            principle_errors.append(f"{principle_id} customer readiness not false")
        if principle.get("live_runtime_execution_capability") is not False:
            principle_errors.append(f"{principle_id} live runtime execution capability not false")
    emit("registry_principle_flags", not principle_errors, "every principle has required review and non-activation flags" if not principle_errors else "; ".join(principle_errors), errors)

    taxonomy = parsed_json.get(TAXONOMY_FIXTURE, {})
    taxonomy_phases = {phase.get("roadmap_phase") for phase in taxonomy.get("roadmap_phases", []) if isinstance(phase, dict)}
    missing_roadmap_phases = [phase for phase in ROADMAP_PHASE_LABELS if phase not in taxonomy_phases]
    mapping_statement = taxonomy.get("current_mapping", {}).get("statement", "")
    mapping_ok = "Roadmap Phase 2" in mapping_statement and "planning evidence for later roadmap phases" in mapping_statement and "does not activate Phase 3" in mapping_statement
    emit("taxonomy_created", taxonomy.get("taxonomy_created") is True, "roadmap taxonomy is created", errors)
    emit("taxonomy_distinct_layers", taxonomy.get("roadmap_phase_layer_distinct_from_runtime_volume") is True and taxonomy.get("runtime_volume_layer_distinct_from_volume_internal_phase") is True, "taxonomy layers are distinct", errors)
    emit("taxonomy_roadmap_phases", not missing_roadmap_phases, "Roadmap Phase 0 through Phase 5 are present" if not missing_roadmap_phases else f"missing {missing_roadmap_phases}", errors)
    emit("taxonomy_current_mapping", mapping_ok, "taxonomy states Vol.9 supports Roadmap Phase 2 and later planning evidence only", errors)

    protocol = parsed_json.get(ENTRY_EXIT_FIXTURE, {})
    protocol_flags_ok = all(
        protocol.get(field) is True
        for field in [
            "volume_entry_exit_review_protocol_created",
            "future_volume_entry_review_required",
            "future_volume_exit_review_required",
            "principle_review_at_volume_start_required",
            "principle_review_at_volume_end_required",
            "milestone_plan_at_volume_start_required",
            "milestone_review_at_volume_end_required",
        ]
    )
    missing_entry = [item for item in ENTRY_REQUIREMENTS if item not in protocol.get("volume_entry_requirements", [])]
    missing_exit = [item for item in EXIT_REQUIREMENTS if item not in protocol.get("volume_exit_requirements", [])]
    emit("protocol_flags", protocol_flags_ok, "volume entry/exit protocol has all required true flags", errors)
    emit("protocol_entry_requirements", not missing_entry, "volume entry checklist contains all required items" if not missing_entry else f"missing {missing_entry}", errors)
    emit("protocol_exit_requirements", not missing_exit, "volume exit checklist contains all required items" if not missing_exit else f"missing {missing_exit}", errors)

    missing_principle_doc = contains_required_text(PRINCIPLE_DOC, ["# Tianma Work OS Principle Registry"])
    emit("principle_doc_title", not missing_principle_doc, "principle registry document has required title", errors)

    exact_clarification = (
        "Roadmap Phase 0–5 and runtime Vol.1–Vol.9 are not the same taxonomy layer.\n"
        "Roadmap phases describe product maturity and strategic roadmap stages.\n"
        "Runtime volumes describe iterative execution cycles inside the repository and project workflow.\n"
        "Volume internal phases describe implementation/documentation substeps inside a runtime volume."
    )
    missing_taxonomy_doc = contains_required_text(TAXONOMY_DOC, [exact_clarification])
    emit("taxonomy_doc_clarification", not missing_taxonomy_doc, "taxonomy document contains the exact required clarification", errors)

    missing_entry_exit_doc = contains_required_text(ENTRY_EXIT_DOC, ["## 2. Volume Entry Checklist", "## 3. Volume Exit Checklist"])
    emit("entry_exit_doc_sections", not missing_entry_exit_doc, "entry/exit protocol document contains required checklist sections", errors)

    record = parsed_json.get(RECORD_PATH, {})
    record_ok = (
        record.get("record_type") == "vol9_phase9_9_principle_registry_volume_protocol"
        and record.get("runtime_records_baseline_before_phase") == 121
        and record.get("runtime_records_baseline_after_phase") == 122
        and record.get("customer_facing_readiness") is False
        and record.get("live_runtime_execution_frameworks") == 0
        and record.get("static_shell_mode") == STATIC_SHELL_MODE
    )
    trading_flags_ok = all(record.get(flag) is False for flag in TRADING_IMPACT_FLAGS)
    emit("record_baseline", record_ok, "runtime record has required Phase 9.9 baseline and boundary fields", errors)
    emit("record_trading_impact_flags", trading_flags_ok, "runtime record has all trading impact flags set to false", errors)

    scan_paths = [path for path in REQUIRED_FILES if not path.startswith("scripts/")] + ["ROADMAP.md", FEATURE_INVENTORY_DOC]
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
    emit("index_references", not missing_index_refs, "INDEX.md references the new Phase 9.9 documents and fixtures" if not missing_index_refs else f"missing {missing_index_refs}", errors)

    feature_inventory_text = read_text(FEATURE_INVENTORY_DOC)
    inventory_links_ok = PRINCIPLE_DOC in feature_inventory_text and TAXONOMY_DOC in feature_inventory_text
    emit("feature_inventory_links", inventory_links_ok, "implemented feature inventory links to principle registry and roadmap taxonomy", errors)

    roadmap_path = REPO_ROOT / "ROADMAP.md"
    if roadmap_path.exists():
        roadmap_text = roadmap_path.read_text(encoding="utf-8")
        roadmap_note_ok = "Roadmap Phase 0-5 and runtime Vol.1-Vol.9 are not the same taxonomy layer." in roadmap_text
        emit("roadmap_terminology_note", roadmap_note_ok, "ROADMAP.md has runtime taxonomy terminology note", errors)
    else:
        emit("roadmap_terminology_note", True, "no ROADMAP.md exists, taxonomy cross-reference is in new docs and INDEX.md", errors)

    status_lines = [
        "TWOS/LDD Runtime Status Backfeed Update｜Vol.9 Phase 9.9 Principle Registry & Volume Protocol",
        "Roadmap Phase 0–5 and runtime Vol.1–Vol.9 are not the same taxonomy layer.",
        "Every future runtime Volume must begin with milestone planning and principle review.",
        "Every future runtime Volume must end with milestone review and principle adherence review.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "Future gate activation remains blocked.",
    ]
    status_text = read_text(STATUS_UPDATE)
    missing_status_lines = [line for line in status_lines if line not in status_text]
    emit("status_update_lines", not missing_status_lines, "post-Phase 9.9 status update contains required LDD sync lines" if not missing_status_lines else f"missing {missing_status_lines}", errors)

    if errors:
        print("\nVol.9 Phase 9.9 principle registry validation failed.")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\nVol.9 Phase 9.9 principle registry validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
