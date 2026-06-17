#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.6 static shell traceability artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.6"
PHASE9_5_COMMIT = "69eeaa8711d3d8c0cf583750734a77148fbe724e"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

MATRIX_SCHEMA_PATH = "schemas/static_shell_fixture_coverage_matrix.schema.json"
TRACEABILITY_SCHEMA_PATH = "schemas/prototype_to_gate_traceability_map.schema.json"
MATRIX_FIXTURE_PATH = "mock_consumers/ldd/static_shell_fixture_coverage_matrix.json"
TRACEABILITY_FIXTURE_PATH = "mock_consumers/ldd/prototype_to_gate_traceability_map.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_6_traceability_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_6_static_shell_fixture_coverage_matrix_and_prototype_to_gate_traceability_map.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_6_STATIC_SHELL_FIXTURE_COVERAGE_MATRIX_AND_PROTOTYPE_TO_GATE_TRACEABILITY_MAP_v0.1.md",
    "docs/runtime/STATIC_SHELL_PROTOTYPE_TRACEABILITY_PROTOCOL_v0.1.md",
    MATRIX_SCHEMA_PATH,
    TRACEABILITY_SCHEMA_PATH,
    MATRIX_FIXTURE_PATH,
    TRACEABILITY_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_6_static_shell_traceability.py",
    "scripts/validate_vol9_phase9_6_static_shell_traceability.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_6_STATIC_SHELL_FIXTURE_COVERAGE_MATRIX_AND_PROTOTYPE_TO_GATE_TRACEABILITY_MAP_v0.1.md",
    "docs/runtime/STATIC_SHELL_PROTOTYPE_TRACEABILITY_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/static_shell_fixture_coverage_matrix.json",
    "mock_consumers/ldd/prototype_to_gate_traceability_map.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_6_traceability_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_6_static_shell_fixture_coverage_matrix_and_prototype_to_gate_traceability_map.json",
    "scripts/validate_vol9_phase9_6_static_shell_traceability.py",
]

MOCK_FIXTURES = [
    MATRIX_FIXTURE_PATH,
    TRACEABILITY_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
]

REQUIRED_COVERAGE_DOMAINS = [
    "static_shell_artifacts",
    "mock_consumer_fixtures",
    "runtime_protocol_documents",
    "json_schemas",
    "validation_scripts",
    "runtime_records",
    "index_references",
]

REQUIRED_COVERAGE_ITEM_PATHS = [
    "static_shell/ldd/",
    "mock_consumers/ldd/",
    "docs/runtime/",
    "schemas/",
    "scripts/",
    "records/ldd/2026-06-17/",
    "INDEX.md",
]

COVERAGE_ITEM_FIELDS = [
    "artifact_path",
    "artifact_type",
    "coverage_domain",
    "related_phase",
    "related_future_gate",
    "coverage_classification",
    "activation_status",
    "coverage_limit",
    "non_activation_statement",
]

FORBIDDEN_COVERAGE_CLASSIFICATIONS = [
    "customer_ready_coverage",
    "live_ready_coverage",
    "production_ready_coverage",
    "execution_ready_coverage",
    "integration_ready_coverage",
    "credential_ready_coverage",
    "deployment_ready_coverage",
]

GATES = [
    "static_prototype_gate",
    "customer_facing_readiness_gate",
    "live_read_only_runtime_gate",
    "runtime_mutation_gate",
    "external_integration_gate",
    "trading_execution_gate",
    "credential_handling_gate",
    "notification_scheduler_gate",
    "production_deployment_gate",
]

FUTURE_GAPS = [
    "security_review_gap",
    "privacy_review_gap",
    "credential_handling_gap",
    "read_only_runtime_contract_gap",
    "mutation_safety_contract_gap",
    "external_integration_contract_gap",
    "customer_facing_ux_gap",
    "production_deployment_gap",
    "rollback_plan_gap",
    "audit_log_contract_gap",
    "trading_execution_safety_gap",
    "source_of_truth_arbitration_gap",
    "live_data_contract_gap",
    "operator_review_gap",
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
    "customer-facing readiness: `true`",
    '"network_allowed": true',
    "network_allowed = true",
    "network allowed: true",
    '"execution_allowed": true',
    "execution_allowed = true",
    "execution allowed: true",
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


def load_json(path: str) -> Any:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def matches_type(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return False


def validate_schema_subset(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(matches_type(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected_types}, got {type_name(value)}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum {schema['enum']!r}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")

        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_schema_subset(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(validate_schema_subset(item, schema["items"], f"{path}[{index}]"))

    return errors


def as_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def require(condition: bool, check_id: str, message: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {message}")
    else:
        print(f"FAIL {check_id}: {message}")
        failures.append(check_id)


def nested_forbidden_flag_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_TRUE_FIELDS and child is True:
                errors.append(f"{child_path} is true")
            if key == "customer_facing_readiness" and child is not False:
                errors.append(f"{child_path} must be false")
            if key == "live_runtime_execution_frameworks" and child != 0:
                errors.append(f"{child_path} must be 0")
            if key == "static_shell_mode" and child != STATIC_SHELL_MODE:
                errors.append(f"{child_path} must equal {STATIC_SHELL_MODE}")
            errors.extend(nested_forbidden_flag_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(nested_forbidden_flag_errors(child, f"{path}[{index}]"))
    return errors


def coverage_item_errors(item: Any, index: int) -> list[str]:
    if not isinstance(item, dict):
        return [f"coverage_items[{index}] must be an object"]

    errors: list[str] = []
    for field in COVERAGE_ITEM_FIELDS:
        if field not in item:
            errors.append(f"coverage_items[{index}].{field} missing")

    classification = item.get("coverage_classification")
    if classification in FORBIDDEN_COVERAGE_CLASSIFICATIONS:
        errors.append(f"coverage_items[{index}].coverage_classification uses forbidden value {classification}")

    text = as_text(item)
    for classification in FORBIDDEN_COVERAGE_CLASSIFICATIONS:
        if classification in text:
            errors.append(f"coverage_items[{index}] contains forbidden coverage classification {classification}")

    return errors


def gate_state_errors(gate_name: str, gate: Any) -> list[str]:
    if not isinstance(gate, dict):
        return [f"{gate_name} must be an object"]

    if gate_name == "static_prototype_gate":
        expected = {
            "status": "active_static_only",
            "traceability_status": "static_trace_only",
            "current_phase_allowed": True,
            "activation_requested": False,
            "activation_granted": True,
        }
    else:
        expected = {
            "status": "not_activated",
            "traceability_status": "planning_trace_only",
            "current_phase_allowed": False,
            "activation_requested": False,
            "activation_granted": False,
        }

    errors: list[str] = []
    for key, expected_value in expected.items():
        if gate.get(key) != expected_value:
            errors.append(f"{gate_name}.{key} must be {expected_value!r}")
    return errors


def future_gap_errors(name: str, gap: Any) -> list[str]:
    if not isinstance(gap, dict):
        return [f"{name} must be an object"]

    expected = {
        "status": "open_future_gap",
        "current_phase_resolved": False,
        "activation_blocker": True,
    }
    errors: list[str] = []
    for key, expected_value in expected.items():
        if gap.get(key) != expected_value:
            errors.append(f"{name}.{key} must be {expected_value!r}")
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.6 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        matrix_schema = load_json(MATRIX_SCHEMA_PATH)
        traceability_schema = load_json(TRACEABILITY_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(
        isinstance(matrix_schema, dict) and isinstance(traceability_schema, dict),
        "schema_parse",
        "schema files are parseable JSON objects",
        failures,
    )

    parsed_json: dict[str, Any] = {}
    for path in [MATRIX_FIXTURE_PATH, TRACEABILITY_FIXTURE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    matrix = parsed_json[MATRIX_FIXTURE_PATH]
    traceability = parsed_json[TRACEABILITY_FIXTURE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    matrix_errors = validate_schema_subset(matrix, matrix_schema)
    require(not matrix_errors, "matrix_schema_validation", "static shell fixture coverage matrix validates against schema subset", failures)
    for error in matrix_errors:
        print(f"  - {error}")

    traceability_errors = validate_schema_subset(traceability, traceability_schema)
    require(not traceability_errors, "traceability_schema_validation", "prototype-to-gate traceability map validates against schema subset", failures)
    for error in traceability_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, traceability_schema)
    require(not record_errors, "record_traceability_schema_validation", "runtime record validates against prototype-to-gate traceability schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.6 name", failures)
        require(PHASE9_5_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.5 commit hash", failures)

    require(matrix.get("static_shell_fixture_coverage_matrix_created") is True, "matrix_created", "coverage matrix marks static shell fixture coverage matrix created", failures)

    domains = matrix.get("coverage_domains")
    require(isinstance(domains, list) and set(REQUIRED_COVERAGE_DOMAINS).issubset(set(domains)), "coverage_domains", "coverage matrix contains all required coverage domains", failures)

    items = matrix.get("coverage_items")
    if isinstance(items, list):
        item_paths = [item.get("artifact_path") for item in items if isinstance(item, dict)]
    else:
        item_paths = []
    missing_item_paths = sorted(path for path in REQUIRED_COVERAGE_ITEM_PATHS if path not in item_paths)
    require(not missing_item_paths, "coverage_item_paths", "coverage matrix contains required coverage item paths", failures)
    for path in missing_item_paths:
        print(f"  - missing {path}")

    coverage_errors: list[str] = []
    if isinstance(items, list):
        for index, item in enumerate(items):
            coverage_errors.extend(coverage_item_errors(item, index))
    else:
        coverage_errors.append("coverage_items must be an array")
    require(not coverage_errors, "coverage_item_fields", "every coverage item has required fields and no forbidden classification", failures)
    for error in coverage_errors:
        print(f"  - {error}")

    require(traceability.get("prototype_to_gate_traceability_map_created") is True, "traceability_created", "prototype-to-gate traceability map is created", failures)
    require(traceability.get("future_gate_activation") is False, "traceability_activation_false", "future gate activation remains false", failures)
    require(traceability.get("state_name") == "static_shell_traceability_map_created", "traceability_state", "traceability state is static_shell_traceability_map_created", failures)

    gates = traceability.get("future_gates", {})
    missing_gates = sorted(gate for gate in GATES if gate not in gates)
    require(not missing_gates, "future_gates_present", "traceability map contains all required future gates", failures)
    for gate in missing_gates:
        print(f"  - missing {gate}")

    gate_errors: list[str] = []
    if isinstance(gates, dict):
        for gate_name in GATES:
            if gate_name in gates:
                gate_errors.extend(gate_state_errors(gate_name, gates[gate_name]))
    else:
        gate_errors.append("future_gates must be object")
    require(not gate_errors, "future_gate_states", "static gate is static_trace_only and all non-static gates remain planning_trace_only/not_activated", failures)
    for error in gate_errors:
        print(f"  - {error}")

    gap_errors: list[str] = []
    gaps = traceability.get("future_gaps", {})
    if isinstance(gaps, dict):
        for gap_name in FUTURE_GAPS:
            if gap_name not in gaps:
                gap_errors.append(f"{gap_name} missing")
            else:
                gap_errors.extend(future_gap_errors(gap_name, gaps[gap_name]))
    else:
        gap_errors.append("future_gaps must be object")
    require(not gap_errors, "future_gaps_open", "all future gaps remain open future gaps and activation blockers", failures)
    for error in gap_errors:
        print(f"  - {error}")

    require(record.get("runtime_records_baseline_before_phase") == 118, "record_runtime_before", "runtime record baseline before phase is 118", failures)
    require(record.get("runtime_records_baseline_after_phase") == 119, "record_runtime_after", "runtime record baseline after phase is 119", failures)
    require(record.get("customer_facing_readiness") is False, "record_customer_facing", "runtime record customer-facing readiness is false", failures)
    require(record.get("live_runtime_execution_frameworks") == 0, "record_live_runtime_frameworks", "runtime record live/runtime/execution frameworks equal 0", failures)
    require(record.get("static_shell_mode") == STATIC_SHELL_MODE, "record_static_shell_mode", "runtime record static shell mode is locked", failures)

    missing_false_flags = [flag for flag in TRADING_IMPACT_FLAGS if record.get(flag) is not False]
    require(not missing_false_flags, "record_trading_impact_flags", "runtime record trading impact flags are all false", failures)
    for flag in missing_false_flags:
        print(f"  - {flag} must be false")

    text_scan_paths = [
        path for path in REQUIRED_FILES
        if not path.endswith(".py") and not path.endswith(".sh")
    ]
    all_documents: list[tuple[str, str]] = []
    for path in text_scan_paths + ["INDEX.md"]:
        try:
            all_documents.append((path, (REPO_ROOT / path).read_text(encoding="utf-8")))
        except OSError as exc:
            print(f"FAIL text_read: {path}: {exc}")
            failures.append(f"text_read:{path}")

    enabled_snippet_hits: list[str] = []
    for path, text in all_documents:
        lowered = text.lower()
        for snippet in FORBIDDEN_POSITIVE_SNIPPETS:
            if snippet in lowered:
                enabled_snippet_hits.append(f"{path}: {snippet}")
    require(not enabled_snippet_hits, "forbidden_enabled_snippets", "no forbidden live/runtime/customer-facing capability appears as enabled", failures)
    for hit in enabled_snippet_hits:
        print(f"  - {hit}")

    flag_errors: list[str] = []
    for path, document in parsed_json.items():
        flag_errors.extend(f"{path}: {error}" for error in nested_forbidden_flag_errors(document))
    require(not flag_errors, "forbidden_enabled_json_flags", "JSON artifacts do not enable forbidden capabilities", failures)
    for error in flag_errors:
        print(f"  - {error}")

    index_text = (REPO_ROOT / "INDEX.md").read_text(encoding="utf-8")
    missing_index_refs = [item for item in INDEX_REQUIRED_REFERENCES if item not in index_text]
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.6 documents and fixtures", failures)
    for item in missing_index_refs:
        print(f"Missing INDEX reference: {item}")

    required_status_lines = [
        "Vol.9 Phase 9.6 creates a static shell fixture coverage matrix and prototype-to-gate traceability map.",
        "Traceability is planning evidence only.",
        "Future gate activation remains blocked.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No cash state is changed by this update.",
        "No broker/Binance connection is changed by this update.",
        "No external API, network dependency, scheduler, notification dispatcher, credential handling, runtime mutation, order placement, trading automation, external integration, or production deployment is created.",
    ]
    status_text = as_text(status_update)
    missing_status_lines = [line for line in required_status_lines if line not in status_text]
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.6 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"Missing status line: {line}")

    print()
    if failures:
        print("Vol.9 Phase 9.6 static shell traceability validation failed.")
        return 1

    print("Vol.9 Phase 9.6 static shell traceability validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
