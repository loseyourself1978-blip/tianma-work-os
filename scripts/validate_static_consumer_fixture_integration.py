#!/usr/bin/env python3
"""Validate Vol.6 Phase 6.8 static consumer fixture integration contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = "2026-06-12T09:18:00+08:00"
LATEST_TIMELINE_EVENT = "2026-06-12T17:20:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
BASELINE_COMMIT = "650d60d23fd5d2957d5fe223dd84a37915dd9d3e"

REQUIRED_FILES = {
    "manifest": "mock_consumers/ldd/static_consumer_fixture_package_manifest.json",
    "dependency_map": "mock_consumers/ldd/static_consumer_fixture_dependency_map.json",
    "readiness_matrix": "mock_consumers/ldd/static_consumer_fixture_readiness_matrix.json",
    "safety_gate": "mock_consumers/ldd/static_consumer_fixture_safety_gate.json",
    "handoff_packet": "mock_consumers/ldd/static_consumer_fixture_handoff_packet.json",
    "drift_detector": "mock_consumers/ldd/cross_workspace_progress_drift_detector.json",
    "backfeed_protocol": "mock_consumers/ldd/ldd_twos_runtime_baseline_backfeed_protocol.json",
    "review_record": "records/ldd/2026-06-12/vol6_phase6_8_static_consumer_fixture_integration_and_handoff_1703_sgt.json",
}

REQUIRED_SCHEMAS = [
    "schemas/static_consumer_fixture_integration.schema.json",
    "schemas/static_consumer_fixture_handoff.schema.json",
]

REQUIRED_GROUPS = [
    "read_only_api_contract_fixtures",
    "ui_boundary_fixtures",
    "permission_privacy_masking_fixtures",
    "static_cockpit_prototype_boundary_fixtures",
    "internal_operator_cockpit_static_fixtures",
    "ai_board_cockpit_static_fixtures",
    "cockpit_static_spec_integration_fixtures",
    "ldd_premarket_governance_sync_fixtures",
    "handoff_and_backfeed_fixtures",
]

REQUIRED_DEPENDENCIES = [
    ("ui_boundary_fixtures", "permission_privacy_masking_fixtures"),
    ("permission_privacy_masking_fixtures", "read_only_api_contract_fixtures"),
    ("read_only_api_contract_fixtures", "static_cockpit_prototype_boundary_fixtures"),
    ("static_cockpit_prototype_boundary_fixtures", "internal_operator_cockpit_static_fixtures"),
    ("static_cockpit_prototype_boundary_fixtures", "ai_board_cockpit_static_fixtures"),
    ("internal_operator_cockpit_static_fixtures", "cockpit_static_spec_integration_fixtures"),
    ("ai_board_cockpit_static_fixtures", "cockpit_static_spec_integration_fixtures"),
    ("ldd_premarket_governance_sync_fixtures", "cockpit_static_spec_integration_fixtures"),
    ("cockpit_static_spec_integration_fixtures", "handoff_and_backfeed_fixtures"),
]

REQUIRED_READINESS_ROWS = [
    "ui_boundary_architecture",
    "permission_privacy_masking_model",
    "read_only_api_contract",
    "static_cockpit_prototype_boundary",
    "internal_operator_cockpit_static_spec",
    "ai_board_cockpit_static_spec",
    "cockpit_static_spec_integration_review",
    "ldd_premarket_governance_sync",
    "cross_workspace_progress_drift_detector",
    "ldd_twos_runtime_baseline_backfeed_protocol",
    "vol6_handoff_packet",
]

REQUIRED_DRIFT_RULES = [
    "stale_phase_detected",
    "stale_commit_detected",
    "stale_checkpoint_detected",
    "missing_twos_runtime_status_block",
    "ldd_review_sync_after_codex_phase_without_backfeed",
]

PROHIBITED_PHASE_PATH_PARTS = [
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
]

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
    warnings: list[str] = []
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

    require(len(loaded) == len(REQUIRED_FILES), "required_files", f"{len(loaded)}/{len(REQUIRED_FILES)} required JSON files loaded", failures)

    schemas_present = [schema for schema in REQUIRED_SCHEMAS if (REPO_ROOT / schema).exists()]
    require(len(schemas_present) == len(REQUIRED_SCHEMAS), "required_schemas", f"{len(schemas_present)}/{len(REQUIRED_SCHEMAS)} schemas exist", failures)

    manifest = loaded.get("manifest", {})
    groups = {item.get("group_id"): item for item in manifest.get("included_fixture_groups", []) if isinstance(item, dict)}
    require(all(group in groups for group in REQUIRED_GROUPS), "fixture_groups", "all nine fixture groups are present", failures)
    require(all(groups.get(group, {}).get("customer_facing_allowed") is False for group in REQUIRED_GROUPS), "fixture_groups_customer_blocked", "every fixture group has customer_facing_allowed false", failures)
    require(all(groups.get(group, {}).get("mutation_allowed") is False for group in REQUIRED_GROUPS), "fixture_groups_no_mutation", "every fixture group has mutation_allowed false", failures)
    require(all(groups.get(group, {}).get("execution_allowed") is False for group in REQUIRED_GROUPS), "fixture_groups_no_execution", "every fixture group has execution_allowed false", failures)

    dep_map = loaded.get("dependency_map", {})
    dependencies = {
        (item.get("upstream_group"), item.get("downstream_group")): item
        for item in dep_map.get("dependencies", [])
        if isinstance(item, dict)
    }
    require(all(dep in dependencies for dep in REQUIRED_DEPENDENCIES), "dependency_chains", "all nine dependency chains are present", failures)
    require(all(dependencies.get(dep, {}).get("required") is True for dep in REQUIRED_DEPENDENCIES), "dependencies_required", "every dependency is required", failures)
    require(all(dependencies.get(dep, {}).get("blocking_if_missing") is True for dep in REQUIRED_DEPENDENCIES), "dependencies_blocking", "every dependency is blocking_if_missing true", failures)

    readiness = loaded.get("readiness_matrix", {})
    rows = {item.get("item_id"): item for item in readiness.get("rows", []) if isinstance(item, dict)}
    require(all(row in rows for row in REQUIRED_READINESS_ROWS), "readiness_rows", "all eleven readiness rows are present", failures)
    for field, label in [
        ("required_for_handoff", "required_for_handoff true"),
        ("customer_facing_ready", "customer_facing_ready false"),
        ("actual_ui_created", "actual_ui_created false"),
        ("api_server_created", "api_server_created false"),
        ("live_connection_created", "live_connection_created false"),
        ("trading_automation_created", "trading_automation_created false"),
        ("credential_handling_created", "credential_handling_created false"),
        ("mutation_allowed", "mutation_allowed false"),
        ("execution_allowed", "execution_allowed false"),
    ]:
        expected = True if field == "required_for_handoff" else False
        require(all(rows.get(row, {}).get(field) is expected for row in REQUIRED_READINESS_ROWS), f"readiness_{field}", f"every readiness row has {label}", failures)

    gate = loaded.get("safety_gate", {})
    true_gate_fields = [
        "internal_static_spec_ready",
        "ai_board_static_spec_ready",
        "read_only_api_contract_ready",
        "permission_masking_ready",
        "static_integration_ready",
        "cross_workspace_drift_detection_ready",
        "ldd_twos_backfeed_ready",
    ]
    false_gate_fields = [
        "customer_facing_ready",
        "actual_ui_ready",
        "api_server_ready",
        "live_endpoint_ready",
        "broker_connection_ready",
        "binance_connection_ready",
        "external_market_api_ready",
        "live_market_data_ready",
        "trading_automation_ready",
        "credential_handling_ready",
        "runtime_mutation_ui_ready",
        "execution_trigger_ready",
    ]
    for field in true_gate_fields:
        require(gate.get(field) is True, f"safety_{field}", f"{field} is true", failures)
    for field in false_gate_fields:
        require(gate.get(field) is False, f"safety_{field}", f"{field} is false", failures)

    detector = loaded.get("drift_detector", {})
    detector_rules = {item.get("rule_id"): item for item in detector.get("detection_rules", []) if isinstance(item, dict)}
    require(all(rule in detector_rules for rule in REQUIRED_DRIFT_RULES), "drift_rules", "required drift detector rules are present", failures)
    require(detector.get("current_twos_commit") == BASELINE_COMMIT, "drift_current_commit", "drift detector current TWOS commit is the Phase 6.7a commit before Phase 6.8 commit", failures)
    require(detector_rules.get("stale_commit_detected", {}).get("expected_current_value") == BASELINE_COMMIT, "drift_stale_commit_compare", "stale_commit_detected compares against current_twos_commit", failures)

    protocol = loaded.get("backfeed_protocol", {})
    template = str(protocol.get("backfeed_block_template", ""))
    require("TWOS Runtime Status Update｜For LDD Baseline Sync" in template and "<PHASE_6_8A_COMMIT_SHA_AFTER_PUSH>" in template, "backfeed_template", "backfeed protocol contains the full TWOS Runtime Status Update template", failures)
    require(protocol.get("backfeed_required_after_phase_completion") is True, "backfeed_after_phase", "backfeed required after phase completion", failures)
    require(protocol.get("backfeed_required_after_checkpoint_promotion") is True, "backfeed_after_checkpoint", "backfeed required after checkpoint promotion", failures)
    require(protocol.get("backfeed_required_after_non_promoted_governance_sync") is True, "backfeed_after_non_promoted", "backfeed required after non-promoted governance sync", failures)
    routing_text = " ".join(str(item) for item in protocol.get("routing_policy", []))
    require("Do not send partial add-on patches to Codex" in routing_text and "regenerate complete instruction blocks" in routing_text, "backfeed_complete_blocks", "backfeed protocol blocks partial add-on patches and requires complete instruction blocks", failures)

    handoff = loaded.get("handoff_packet", {})
    require(handoff.get("recommended_next_phase") == "Vol.6 Phase 6.9 - Vol.6 Handoff Summary and Vol.7 Readiness Gate", "handoff_next_phase", "handoff packet recommends Phase 6.9", failures)
    require(handoff.get("recommended_new_chat_title") == "Tianma Work OS Vol.7 — UI Shell Planning / Static Fixture Consumer", "handoff_new_chat", "handoff packet recommends the Vol.7 chat title", failures)

    require(manifest.get("active_checkpoint") == CHECKPOINT and gate.get("active_checkpoint") == CHECKPOINT and handoff.get("active_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    latest_event_values = {manifest.get("latest_timeline_event"), gate.get("latest_timeline_event"), handoff.get("latest_timeline_event")}
    require(latest_event_values == {LATEST_TIMELINE_EVENT}, "latest_timeline_event", f"latest timeline event remains {LATEST_TIMELINE_EVENT} for fixture handoff inputs", failures)
    require(manifest.get("operating_mode") == OPERATING_MODE and gate.get("operating_mode") == OPERATING_MODE and handoff.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(manifest.get("portfolio_mode") == PORTFOLIO_MODE and gate.get("portfolio_mode") == PORTFOLIO_MODE and handoff.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    phase_files = [REPO_ROOT / relpath for relpath in REQUIRED_FILES.values()]
    phase_files.extend(REPO_ROOT / schema for schema in REQUIRED_SCHEMAS)
    phase_files.append(REPO_ROOT / "docs/runtime/VOL6_PHASE6_8_STATIC_CONSUMER_FIXTURE_INTEGRATION_AND_HANDOFF_v0.1.md")
    phase_files.append(REPO_ROOT / "reports/ldd/vol6_phase6_8_static_consumer_fixture_integration_and_handoff.md")
    phase_files.append(REPO_ROOT / "scripts/validate_static_consumer_fixture_integration.py")
    phase_files.append(REPO_ROOT / "scripts/validate_static_consumer_fixture_integration.sh")
    bad_files = []
    for path in phase_files:
        rel_parts = path.relative_to(REPO_ROOT).parts
        if any(part in PROHIBITED_PHASE_PATH_PARTS for part in rel_parts):
            bad_files.append(str(path.relative_to(REPO_ROOT)))
        if path.suffix in PROHIBITED_SUFFIXES and path.name != "validate_static_consumer_fixture_integration.py":
            bad_files.append(str(path.relative_to(REPO_ROOT)))
    require(not bad_files, "no_implementation_files", "no Phase 6.8 artifact appears to implement UI/API/server/connector/credential/mutation/execution", failures)

    print("")
    if failures:
        print("Static consumer fixture integration validation failed.")
        print(f"Blocking failures: {len(failures)}")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Static consumer fixture integration validation passed.")
    print("Checks: 48")
    print(f"Contract files checked: {len(loaded)}")
    print("Blocking failures: 0")
    print(f"Warnings: {len(warnings)}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Latest timeline event input: {LATEST_TIMELINE_EVENT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Customer-facing ready: false")
    print("Actual UI created: false")
    print("API server created: false")
    print("Live endpoint created: false")
    print("Trading automation enabled: false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
