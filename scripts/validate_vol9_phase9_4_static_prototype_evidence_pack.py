#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.4 static prototype evidence pack artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.4"
PHASE9_3_COMMIT = "0bf392e98ae0b4f3ea7236af03f563983d7dfa5b"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

EVIDENCE_SCHEMA_PATH = "schemas/static_prototype_evidence_pack.schema.json"
CHECKLIST_SCHEMA_PATH = "schemas/future_gate_readiness_checklist.schema.json"
EVIDENCE_FIXTURE_PATH = "mock_consumers/ldd/static_prototype_evidence_pack.json"
CHECKLIST_FIXTURE_PATH = "mock_consumers/ldd/future_gate_readiness_checklist.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_4_evidence_pack_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_4_static_prototype_evidence_pack_and_future_gate_readiness_checklist.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_4_STATIC_PROTOTYPE_EVIDENCE_PACK_AND_FUTURE_GATE_READINESS_CHECKLIST_v0.1.md",
    "docs/runtime/FUTURE_GATE_EVIDENCE_READINESS_PROTOCOL_v0.1.md",
    EVIDENCE_SCHEMA_PATH,
    CHECKLIST_SCHEMA_PATH,
    EVIDENCE_FIXTURE_PATH,
    CHECKLIST_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_4_static_prototype_evidence_pack.py",
    "scripts/validate_vol9_phase9_4_static_prototype_evidence_pack.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_4_STATIC_PROTOTYPE_EVIDENCE_PACK_AND_FUTURE_GATE_READINESS_CHECKLIST_v0.1.md",
    "docs/runtime/FUTURE_GATE_EVIDENCE_READINESS_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/static_prototype_evidence_pack.json",
    "mock_consumers/ldd/future_gate_readiness_checklist.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_4_evidence_pack_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_4_static_prototype_evidence_pack_and_future_gate_readiness_checklist.json",
    "scripts/validate_vol9_phase9_4_static_prototype_evidence_pack.py",
]

MOCK_FIXTURES = [
    EVIDENCE_FIXTURE_PATH,
    CHECKLIST_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
]

EVIDENCE_CATEGORIES = [
    "security_review_evidence",
    "privacy_review_evidence",
    "credential_handling_design",
    "read_only_runtime_contract",
    "mutation_safety_contract",
    "external_integration_contract",
    "customer_facing_ux_review",
    "production_deployment_review",
    "rollback_plan",
    "audit_log_contract",
    "trading_execution_safety_review",
    "source_of_truth_arbitration_review",
]

EVIDENCE_CATEGORY_FIELDS = [
    "current_status",
    "current_phase_classification",
    "future_gate_dependency",
    "missing_evidence",
    "activation_blocker",
    "non_activation_statement",
]

ALLOWED_EVIDENCE_CLASSIFICATIONS = {
    "static_planning_evidence_available",
    "static_fixture_evidence_available",
    "not_provided_in_current_phase",
    "future_live_evidence_required",
}

DISALLOWED_READINESS_VALUES = {
    "live_ready",
    "production_ready",
    "customer_ready",
    "execution_ready",
}

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

NON_STATIC_GATES = [
    gate for gate in GATES if gate != "static_prototype_gate"
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


def category_readiness_errors(category: Any, category_name: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(category, dict):
        return [f"{category_name} must be an object"]

    for field in EVIDENCE_CATEGORY_FIELDS:
        if field not in category:
            errors.append(f"{category_name}.{field} missing")

    classification = category.get("current_phase_classification")
    if classification not in ALLOWED_EVIDENCE_CLASSIFICATIONS:
        errors.append(f"{category_name}.current_phase_classification is not an allowed Phase 9.4 classification")

    category_text = as_text(category)
    for value in DISALLOWED_READINESS_VALUES:
        if value in category_text:
            errors.append(f"{category_name} contains disallowed readiness value {value}")

    return errors


def gate_state_errors(gate_name: str, gate: Any) -> list[str]:
    if not isinstance(gate, dict):
        return [f"{gate_name} must be an object"]

    if gate_name == "static_prototype_gate":
        expected = {
            "status": "active_static_only",
            "current_phase_allowed": True,
            "activation_requested": False,
            "activation_granted": True,
        }
    else:
        expected = {
            "status": "not_activated",
            "current_phase_allowed": False,
            "activation_requested": False,
            "activation_granted": False,
        }

    errors = []
    for key, expected_value in expected.items():
        if gate.get(key) != expected_value:
            errors.append(f"{gate_name}.{key} must be {expected_value!r}")
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.4 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        evidence_schema = load_json(EVIDENCE_SCHEMA_PATH)
        checklist_schema = load_json(CHECKLIST_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(
        isinstance(evidence_schema, dict) and isinstance(checklist_schema, dict),
        "schema_parse",
        "schema files are parseable JSON objects",
        failures,
    )

    parsed_json: dict[str, Any] = {}
    for path in [EVIDENCE_FIXTURE_PATH, CHECKLIST_FIXTURE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    evidence_pack = parsed_json[EVIDENCE_FIXTURE_PATH]
    checklist = parsed_json[CHECKLIST_FIXTURE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    evidence_errors = validate_schema_subset(evidence_pack, evidence_schema)
    require(not evidence_errors, "evidence_schema_validation", "static prototype evidence pack validates against schema subset", failures)
    for error in evidence_errors:
        print(f"  - {error}")

    checklist_errors = validate_schema_subset(checklist, checklist_schema)
    require(not checklist_errors, "checklist_schema_validation", "future gate readiness checklist validates against schema subset", failures)
    for error in checklist_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, checklist_schema)
    require(not record_errors, "record_checklist_schema_validation", "runtime record validates against future gate checklist schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.4 name", failures)
        require(PHASE9_3_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.3 commit hash", failures)

    require(evidence_pack.get("static_evidence_pack_created") is True, "evidence_pack_created", "evidence pack marks static evidence pack created", failures)

    categories = evidence_pack.get("evidence_categories", {})
    category_missing = sorted(category for category in EVIDENCE_CATEGORIES if category not in categories)
    require(not category_missing, "evidence_categories_present", "evidence pack has all required evidence categories", failures)
    for category in category_missing:
        print(f"  - missing {category}")

    category_errors: list[str] = []
    if isinstance(categories, dict):
        for category_name in EVIDENCE_CATEGORIES:
            if category_name in categories:
                category_errors.extend(category_readiness_errors(categories[category_name], category_name))
    else:
        category_errors.append("evidence_categories must be object")
    require(not category_errors, "evidence_category_fields", "each evidence category has required fields and no disallowed readiness class", failures)
    for error in category_errors:
        print(f"  - {error}")

    require(checklist.get("future_gate_checklist_created") is True, "checklist_created", "future gate checklist is created", failures)
    require(checklist.get("future_gate_activation") is False, "checklist_activation_false", "future gate activation remains false", failures)
    require(checklist.get("state_name") == "future_gate_activation_blocked", "checklist_state", "checklist state is future_gate_activation_blocked", failures)

    gates = checklist.get("gates", {})
    missing_gates = sorted(gate for gate in GATES if gate not in gates)
    require(not missing_gates, "checklist_gates_present", "checklist contains all required gates", failures)
    for gate in missing_gates:
        print(f"  - missing {gate}")

    gate_errors: list[str] = []
    if isinstance(gates, dict):
        for gate_name in GATES:
            if gate_name in gates:
                gate_errors.extend(gate_state_errors(gate_name, gates[gate_name]))
    else:
        gate_errors.append("gates must be object")
    require(not gate_errors, "gate_states", "static gate is active_static_only and all non-static gates remain not_activated", failures)
    for error in gate_errors:
        print(f"  - {error}")

    require(record.get("runtime_records_baseline_before_phase") == 116, "record_runtime_before", "runtime record baseline before phase is 116", failures)
    require(record.get("runtime_records_baseline_after_phase") == 117, "record_runtime_after", "runtime record baseline after phase is 117", failures)
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
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.4 documents and fixtures", failures)
    for item in missing_index_refs:
        print(f"Missing INDEX reference: {item}")

    required_status_lines = [
        "Vol.9 Phase 9.4 creates a static prototype evidence pack and future gate readiness checklist.",
        "The future gate activation state remains blocked.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No cash state is changed by this update.",
        "No broker/Binance connection is changed by this update.",
        "No external API, network dependency, scheduler, notification dispatcher, credential handling, runtime mutation, order placement, trading automation, or production deployment is created.",
        "Evidence readiness is not capability readiness.",
    ]
    status_text = as_text(status_update)
    missing_status_lines = [line for line in required_status_lines if line not in status_text]
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.4 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"Missing status line: {line}")

    print()
    if failures:
        print("Vol.9 Phase 9.4 static prototype evidence pack validation failed.")
        return 1

    print("Vol.9 Phase 9.4 static prototype evidence pack validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
