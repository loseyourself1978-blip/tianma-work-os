#!/usr/bin/env python3
"""Validate Vol.10 Phase 10.1 static product blueprint consolidation map artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.10 Phase 10.1"
BASELINE_COMMIT = "8cca3a6f1eeb230b74db6c593833089138775b26"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

BLUEPRINT_DOC = "docs/runtime/VOL10_STATIC_PRODUCT_BLUEPRINT_CONSOLIDATION_MAP_v0.1.md"
BLUEPRINT_SCHEMA = "schemas/vol10_static_product_blueprint_consolidation_map.schema.json"
BLUEPRINT_FIXTURE = "mock_consumers/ldd/vol10_static_product_blueprint_consolidation_map.json"
RECORD_PATH = "records/ldd/2026-06-18/vol10_phase10_1_static_product_blueprint_consolidation_map.json"
VALIDATOR_PATH = "scripts/validate_vol10_phase10_1_static_product_blueprint_map.py"
WRAPPER_PATH = "scripts/validate_vol10_phase10_1_static_product_blueprint_map.sh"
INDEX_PATH = "INDEX.md"
FEATURE_INVENTORY_DOC = "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md"

REQUIRED_FILES = [
    BLUEPRINT_DOC,
    BLUEPRINT_SCHEMA,
    BLUEPRINT_FIXTURE,
    RECORD_PATH,
    VALIDATOR_PATH,
    WRAPPER_PATH,
]

JSON_PATHS = [BLUEPRINT_FIXTURE, RECORD_PATH]
SCHEMA_PATHS = [BLUEPRINT_SCHEMA]

REQUIRED_CLUSTERS = [
    "product_thesis_and_first_principles",
    "duxd_real_scenario_feedback_loop",
    "ldd_seed_battlefield_feedback",
    "ai_team_command_model",
    "human_strategy_ai_execution_boundary",
    "memory_index_and_handoff_continuity",
    "source_of_truth_separation",
    "static_cockpit_and_fixture_consumer_layer",
    "permission_privacy_and_read_only_boundary",
    "roadmap_phase_vs_runtime_volume_taxonomy",
    "implemented_feature_inventory_and_timeline",
    "validation_and_regression_guard_layer",
    "future_codex_execution_planning_boundary",
]

REQUIRED_CLUSTER_FIELDS = [
    "purpose",
    "source_documents",
    "related_principles",
    "related_volumes_phases",
    "implemented_static_artifacts",
    "not_yet_implemented_capabilities",
    "forbidden_live_customer_facing_execution_interpretation",
    "validation_expectations",
    "open_planning_questions",
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
    "phase10_2_started",
    "live_runtime_execution_capability",
    "roadmap_phase_3_mvp_build_activated",
    "roadmap_phase_4_multi_model_execution_layer_activated",
    "roadmap_phase_5_ecosystem_public_collaboration_activated",
    "product_runtime_records_override_trading_facts",
    "ldd_trading_facts_imply_product_readiness",
}

FORBIDDEN_POSITIVE_SNIPPETS = [
    '"customer_facing_readiness": true',
    "customer_facing_readiness = true",
    "customer-facing readiness: true",
    '"live_runtime_execution_frameworks": 1',
    '"live_runtime_execution_capability": true',
    '"future_gate_activation": true',
    '"phase10_2_started": true',
    '"roadmap_phase_3_mvp_build_activated": true',
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
            if key == "phase10_2_started" and child is not False:
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
    emit("required_files", not missing, "all Phase 10.1 required files exist" if not missing else f"missing {missing}", errors)

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

    fixture_text = read_text(BLUEPRINT_FIXTURE)
    emit("mock_phase", PHASE in fixture_text, "fixture contains required Phase 10.1 name", errors)
    emit("mock_commit", BASELINE_COMMIT in fixture_text, "fixture contains required Phase 10.0 commit hash", errors)

    fixture = parsed_json.get(BLUEPRINT_FIXTURE, {})
    baseline = fixture.get("baseline", {})
    baseline_ok = (
        baseline.get("latest_completed_phase_before_phase") == "Vol.10 Phase 10.0"
        and baseline.get("latest_commit_before_phase") == BASELINE_COMMIT
        and baseline.get("runtime_records_baseline_before_phase") == 124
        and baseline.get("vol10_entry_protocol") == "completed"
    )
    emit("baseline", baseline_ok, "blueprint fixture records baseline commit, runtime baseline 124, and Phase 10.0 completion", errors)

    clusters = fixture.get("blueprint_clusters", [])
    cluster_by_id = {
        cluster.get("cluster_id"): cluster
        for cluster in clusters
        if isinstance(cluster, dict)
    }
    missing_clusters = [cluster_id for cluster_id in REQUIRED_CLUSTERS if cluster_id not in cluster_by_id]
    emit("blueprint_clusters_present", not missing_clusters, "all required blueprint clusters are present" if not missing_clusters else f"missing {missing_clusters}", errors)

    malformed_clusters = []
    for cluster_id, cluster in cluster_by_id.items():
        for field in REQUIRED_CLUSTER_FIELDS:
            value = cluster.get(field)
            if value in (None, "", []):
                malformed_clusters.append(f"{cluster_id}.{field}")
    emit("cluster_required_fields", not malformed_clusters, "each cluster has required source documents and boundary interpretation fields" if not malformed_clusters else f"missing {malformed_clusters}", errors)

    separation = fixture.get("required_separation", {})
    separation_ok = (
        separation.get("product_blueprint_facts_separate_from_ldd_trading_account_execution_facts") is True
        and separation.get("ldd_seed_battlefield_feedback_source_not_product_runtime_execution_authority") is True
        and separation.get("static_artifacts_may_describe_future_behavior_but_not_live_readiness") is True
        and separation.get("product_runtime_records_override_trading_facts") is False
        and separation.get("ldd_trading_facts_imply_product_readiness") is False
    )
    emit("sot_separation", separation_ok, "product blueprint facts remain separate from LDD trading/account/execution facts", errors)

    roadmap = fixture.get("roadmap_activation_state", {})
    roadmap_ok = (
        roadmap.get("supports_roadmap_phase_1_static_blueprint") is True
        and roadmap.get("supports_roadmap_phase_2_manual_prototype_validation") is True
        and roadmap.get("roadmap_phase_3_mvp_build_activated") is False
        and roadmap.get("roadmap_phase_4_multi_model_execution_layer_activated") is False
        and roadmap.get("roadmap_phase_5_ecosystem_public_collaboration_activated") is False
    )
    emit("roadmap_activation_state", roadmap_ok, "Roadmap Phase 3/4/5 remain not activated", errors)

    phase_ladder = fixture.get("phase_ladder_state", {})
    phase_ladder_ok = (
        phase_ladder.get("phase10_1_status") == "current_static_blueprint_map_only"
        and phase_ladder.get("phase10_2_status") == "planned_only"
        and phase_ladder.get("phase10_2_started") is False
    )
    emit("phase10_2_planned_only", phase_ladder_ok, "Phase 10.2 remains planned-only", errors)

    readiness_ok = (
        fixture.get("customer_facing_readiness") is False
        and fixture.get("live_runtime_execution_frameworks") == 0
        and fixture.get("live_runtime_execution_capability") is False
        and fixture.get("future_gate_activation") is False
    )
    emit("readiness_flags", readiness_ok, "customer-facing and live execution readiness remain false", errors)

    forbidden = fixture.get("forbidden_scope", {})
    bad_forbidden = [field for field in FORBIDDEN_SCOPE_FIELDS if forbidden.get(field) is not False]
    emit("forbidden_scope_blocked", forbidden.get("all_forbidden_capabilities_blocked") is True and not bad_forbidden, "all forbidden scope fields are explicitly blocked" if not bad_forbidden else f"not false {bad_forbidden}", errors)

    record = parsed_json.get(RECORD_PATH, {})
    record_ok = (
        record.get("record_type") == "vol10_phase10_1_static_product_blueprint_consolidation_map"
        and record.get("runtime_records_baseline_before_phase") == 124
        and record.get("runtime_records_baseline_after_phase") == 125
        and record.get("vol10_static_product_blueprint_consolidation_map_created") is True
        and record.get("blueprint_cluster_count") == 13
        and record.get("all_blueprint_clusters_present") is True
        and record.get("phase10_2_status") == "planned_only"
        and record.get("phase10_2_started") is False
        and record.get("customer_facing_readiness") is False
        and record.get("live_runtime_execution_frameworks") == 0
        and record.get("live_runtime_execution_capability") is False
        and record.get("future_gate_activation") is False
    )
    emit("runtime_record", record_ok, "runtime record advances baseline 124 to 125 and preserves non-activation", errors)

    record_clusters = set(record.get("required_blueprint_clusters", []))
    missing_record_clusters = [cluster_id for cluster_id in REQUIRED_CLUSTERS if cluster_id not in record_clusters]
    emit("record_clusters", not missing_record_clusters, "runtime record lists all required blueprint clusters" if not missing_record_clusters else f"missing {missing_record_clusters}", errors)

    trading_flags_ok = all(record.get(flag) is False for flag in TRADING_IMPACT_FLAGS)
    emit("record_trading_impact_flags", trading_flags_ok, "runtime record has all trading impact flags set to false", errors)

    json_forbidden_errors = []
    for path, document in parsed_json.items():
        json_forbidden_errors.extend(f"{path}: {error}" for error in nested_forbidden_true_errors(document))
    emit("forbidden_enabled_json_flags", not json_forbidden_errors, "JSON artifacts do not enable forbidden capabilities" if not json_forbidden_errors else "; ".join(json_forbidden_errors), errors)

    scan_paths = [
        BLUEPRINT_DOC,
        BLUEPRINT_SCHEMA,
        BLUEPRINT_FIXTURE,
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

    phase10_2_files = [
        path
        for pattern in [
            "docs/runtime/*10_2*",
            "mock_consumers/ldd/*10_2*",
            "schemas/*10_2*",
            "records/ldd/**/*10_2*",
        ]
        for path in REPO_ROOT.glob(pattern)
    ]
    emit("phase10_2_not_started", not phase10_2_files, "no Phase 10.2 artifacts exist" if not phase10_2_files else f"Phase 10.2 artifacts found: {phase10_2_files}", errors)

    index_text = read_text(INDEX_PATH)
    index_required = [
        BLUEPRINT_DOC,
        BLUEPRINT_FIXTURE,
        RECORD_PATH,
        VALIDATOR_PATH,
    ]
    index_missing = [item for item in index_required if item not in index_text]
    emit("index_references", not index_missing, "INDEX.md references Phase 10.1 blueprint docs, fixture, record, and validator" if not index_missing else f"missing {index_missing}", errors)

    inventory_text = read_text(FEATURE_INVENTORY_DOC)
    inventory_ok = BLUEPRINT_DOC in inventory_text
    emit("feature_inventory_visibility", inventory_ok, "feature inventory reading path references the blueprint map", errors)

    doc_text = read_text(BLUEPRINT_DOC)
    doc_missing = [
        snippet
        for snippet in [
            "Product blueprint facts remain separate from LDD trading/account/execution facts.",
            "Roadmap Phase 3 MVP Build remains not activated.",
            "customer_facing_readiness: false",
            "live_runtime_execution_capability: false",
            "phase10_2_started: false",
        ]
        if snippet not in doc_text
    ]
    missing_doc_clusters = [cluster_id for cluster_id in REQUIRED_CLUSTERS if cluster_id not in doc_text]
    emit("required_doc_content", not doc_missing and not missing_doc_clusters, "required blueprint doc content is present" if not doc_missing and not missing_doc_clusters else f"missing snippets {doc_missing}; missing clusters {missing_doc_clusters}", errors)

    if errors:
        print("\nVol.10 Phase 10.1 static product blueprint map validation failed.")
        for error in errors:
            print(f"- {error}")
        return 1

    print("\nVol.10 Phase 10.1 static product blueprint map validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
