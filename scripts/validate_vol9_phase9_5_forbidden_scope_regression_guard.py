#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.5 forbidden scope regression guard artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.5"
PHASE9_4_COMMIT = "d070c0a7b4a1d858526daa08f1c04ffd665ed970"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

GUARD_SCHEMA_PATH = "schemas/forbidden_scope_regression_guard.schema.json"
AUDIT_SCHEMA_PATH = "schemas/future_gate_non_activation_audit.schema.json"
GUARD_FIXTURE_PATH = "mock_consumers/ldd/forbidden_scope_regression_guard.json"
AUDIT_FIXTURE_PATH = "mock_consumers/ldd/future_gate_non_activation_audit.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_5_regression_guard_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_5_forbidden_scope_regression_guard_and_non_activation_audit_harness.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_5_FORBIDDEN_SCOPE_REGRESSION_GUARD_AND_NON_ACTIVATION_AUDIT_HARNESS_v0.1.md",
    "docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md",
    GUARD_SCHEMA_PATH,
    AUDIT_SCHEMA_PATH,
    GUARD_FIXTURE_PATH,
    AUDIT_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_5_forbidden_scope_regression_guard.py",
    "scripts/validate_vol9_phase9_5_forbidden_scope_regression_guard.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_5_FORBIDDEN_SCOPE_REGRESSION_GUARD_AND_NON_ACTIVATION_AUDIT_HARNESS_v0.1.md",
    "docs/runtime/FORBIDDEN_SCOPE_REGRESSION_GUARD_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/forbidden_scope_regression_guard.json",
    "mock_consumers/ldd/future_gate_non_activation_audit.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_5_regression_guard_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_5_forbidden_scope_regression_guard_and_non_activation_audit_harness.json",
    "scripts/validate_vol9_phase9_5_forbidden_scope_regression_guard.py",
]

MOCK_FIXTURES = [
    GUARD_FIXTURE_PATH,
    AUDIT_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
]

FORBIDDEN_CAPABILITIES = [
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
]

BLOCKED_EVIDENCE_CLASSIFICATIONS = [
    "live_ready",
    "production_ready",
    "customer_ready",
    "execution_ready",
    "credential_ready",
    "integration_ready",
    "deployment_ready",
]

ALLOWED_EVIDENCE_CLASSIFICATIONS = [
    "static_planning_evidence_available",
    "static_fixture_evidence_available",
    "not_provided_in_current_phase",
    "future_live_evidence_required",
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
    '"current_status": "active"',
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


def capability_errors(name: str, value: Any) -> list[str]:
    if not isinstance(value, dict):
        return [f"{name} must be an object"]

    expected = {
        "capability_name": name,
        "current_status": "not_present",
        "allowed_in_current_phase": False,
        "activation_requested": False,
        "activation_granted": False,
        "regression_guard_result": "passed",
    }
    errors: list[str] = []
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"{name}.{key} must be {expected_value!r}")
    if "audit_note" not in value:
        errors.append(f"{name}.audit_note missing")
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
            "regression_guard_passed": True,
        }
    else:
        expected = {
            "status": "not_activated",
            "current_phase_allowed": False,
            "activation_requested": False,
            "activation_granted": False,
            "regression_guard_passed": True,
        }

    errors: list[str] = []
    for key, expected_value in expected.items():
        if gate.get(key) != expected_value:
            errors.append(f"{gate_name}.{key} must be {expected_value!r}")
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.5 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        guard_schema = load_json(GUARD_SCHEMA_PATH)
        audit_schema = load_json(AUDIT_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(
        isinstance(guard_schema, dict) and isinstance(audit_schema, dict),
        "schema_parse",
        "schema files are parseable JSON objects",
        failures,
    )

    parsed_json: dict[str, Any] = {}
    for path in [GUARD_FIXTURE_PATH, AUDIT_FIXTURE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    guard = parsed_json[GUARD_FIXTURE_PATH]
    audit = parsed_json[AUDIT_FIXTURE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    guard_errors = validate_schema_subset(guard, guard_schema)
    require(not guard_errors, "guard_schema_validation", "forbidden scope regression guard validates against schema subset", failures)
    for error in guard_errors:
        print(f"  - {error}")

    audit_errors = validate_schema_subset(audit, audit_schema)
    require(not audit_errors, "audit_schema_validation", "future gate non-activation audit validates against schema subset", failures)
    for error in audit_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, audit_schema)
    require(not record_errors, "record_audit_schema_validation", "runtime record validates against future gate non-activation audit schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.5 name", failures)
        require(PHASE9_4_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.4 commit hash", failures)

    require(guard.get("forbidden_scope_regression_guard_created") is True, "guard_created", "regression guard marks forbidden scope regression guard created", failures)

    checks = guard.get("forbidden_capability_checks", {})
    missing_capabilities = sorted(capability for capability in FORBIDDEN_CAPABILITIES if capability not in checks)
    require(not missing_capabilities, "capability_checks_present", "regression guard has all required forbidden capability checks", failures)
    for capability in missing_capabilities:
        print(f"  - missing {capability}")

    capability_failures: list[str] = []
    if isinstance(checks, dict):
        for capability in FORBIDDEN_CAPABILITIES:
            if capability in checks:
                capability_failures.extend(capability_errors(capability, checks[capability]))
    else:
        capability_failures.append("forbidden_capability_checks must be object")
    require(not capability_failures, "capability_checks_blocked", "each forbidden capability is not present, not allowed, not requested, not granted, and guard-passed", failures)
    for error in capability_failures:
        print(f"  - {error}")

    classification_guard = guard.get("evidence_classification_guard", {})
    if isinstance(classification_guard, dict):
        allowed = classification_guard.get("allowed_classifications")
        blocked = classification_guard.get("blocked_classifications")
        upgrade_detected = classification_guard.get("classification_upgrade_detected")
    else:
        allowed = blocked = None
        upgrade_detected = None
    require(allowed == ALLOWED_EVIDENCE_CLASSIFICATIONS, "evidence_allowed_classifications", "evidence classification guard allows only static/missing/future-live-required classes", failures)
    require(blocked == BLOCKED_EVIDENCE_CLASSIFICATIONS, "evidence_blocked_classifications", "evidence classification guard blocks live/customer/production/execution/credential/integration/deployment readiness", failures)
    require(upgrade_detected is False, "evidence_upgrade_false", "evidence classification guard reports no classification upgrade", failures)

    require(audit.get("future_gate_non_activation_audit_created") is True, "audit_created", "future gate non-activation audit is created", failures)
    require(audit.get("future_gate_activation") is False, "audit_activation_false", "future gate activation remains false", failures)
    require(audit.get("state_name") == "future_gate_activation_blocked", "audit_state", "audit state is future_gate_activation_blocked", failures)

    gates = audit.get("gates", {})
    missing_gates = sorted(gate for gate in GATES if gate not in gates)
    require(not missing_gates, "audit_gates_present", "audit contains all required gates", failures)
    for gate in missing_gates:
        print(f"  - missing {gate}")

    gate_failures: list[str] = []
    if isinstance(gates, dict):
        for gate_name in GATES:
            if gate_name in gates:
                gate_failures.extend(gate_state_errors(gate_name, gates[gate_name]))
    else:
        gate_failures.append("gates must be object")
    require(not gate_failures, "gate_states", "static gate is active_static_only and all non-static gates remain not_activated with guard passed", failures)
    for error in gate_failures:
        print(f"  - {error}")

    require(record.get("runtime_records_baseline_before_phase") == 117, "record_runtime_before", "runtime record baseline before phase is 117", failures)
    require(record.get("runtime_records_baseline_after_phase") == 118, "record_runtime_after", "runtime record baseline after phase is 118", failures)
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
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.5 documents and fixtures", failures)
    for item in missing_index_refs:
        print(f"Missing INDEX reference: {item}")

    required_status_lines = [
        "Vol.9 Phase 9.5 creates a forbidden scope regression guard and future gate non-activation audit harness.",
        "Future gate activation remains blocked.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No cash state is changed by this update.",
        "No broker/Binance connection is changed by this update.",
        "No external API, network dependency, scheduler, notification dispatcher, credential handling, runtime mutation, order placement, trading automation, external integration, or production deployment is created.",
        "A regression guard prevents accidental capability activation but does not create any capability.",
    ]
    status_text = as_text(status_update)
    missing_status_lines = [line for line in required_status_lines if line not in status_text]
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.5 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"Missing status line: {line}")

    print()
    if failures:
        print("Vol.9 Phase 9.5 forbidden scope regression guard validation failed.")
        return 1

    print("Vol.9 Phase 9.5 forbidden scope regression guard validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
