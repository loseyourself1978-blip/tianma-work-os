#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.2 LDD acknowledgement and strict sync gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.2"
PHASE9_1_COMMIT = "c88ba02fcea3328b85061ab7d7f4f0b240b3ba33"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

ACK_SCHEMA_PATH = "schemas/ldd_consumer_acknowledgement.schema.json"
GATE_SCHEMA_PATH = "schemas/strict_baseline_sync_ready_gate.schema.json"
ACK_FIXTURE_PATH = "mock_consumers/ldd/ldd_consumer_acknowledgement_packet.json"
GATE_FIXTURE_PATH = "mock_consumers/ldd/strict_baseline_sync_ready_gate.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_2_strict_sync_ready_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_2_ldd_consumer_acknowledgement_and_strict_baseline_sync_ready_gate.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_2_LDD_CONSUMER_ACKNOWLEDGEMENT_AND_STRICT_BASELINE_SYNC_READY_GATE_v0.1.md",
    "docs/runtime/LDD_CONSUMER_ACKNOWLEDGEMENT_PROTOCOL_v0.1.md",
    ACK_SCHEMA_PATH,
    GATE_SCHEMA_PATH,
    ACK_FIXTURE_PATH,
    GATE_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_2_ldd_consumer_acknowledgement.py",
    "scripts/validate_vol9_phase9_2_ldd_consumer_acknowledgement.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_2_LDD_CONSUMER_ACKNOWLEDGEMENT_AND_STRICT_BASELINE_SYNC_READY_GATE_v0.1.md",
    "docs/runtime/LDD_CONSUMER_ACKNOWLEDGEMENT_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/ldd_consumer_acknowledgement_packet.json",
    "mock_consumers/ldd/strict_baseline_sync_ready_gate.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_2_strict_sync_ready_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_2_ldd_consumer_acknowledgement_and_strict_baseline_sync_ready_gate.json",
    "scripts/validate_vol9_phase9_2_ldd_consumer_acknowledgement.py",
]

MOCK_FIXTURES = [
    ACK_FIXTURE_PATH,
    GATE_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
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


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.2 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        ack_schema = load_json(ACK_SCHEMA_PATH)
        gate_schema = load_json(GATE_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(isinstance(ack_schema, dict) and isinstance(gate_schema, dict), "schema_parse", "schema files are parseable JSON objects", failures)

    parsed_json: dict[str, Any] = {}
    for path in [ACK_FIXTURE_PATH, GATE_FIXTURE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    ack_packet = parsed_json[ACK_FIXTURE_PATH]
    gate = parsed_json[GATE_FIXTURE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    ack_errors = validate_schema_subset(ack_packet, ack_schema)
    require(not ack_errors, "ack_schema_validation", "LDD acknowledgement packet validates against schema subset", failures)
    for error in ack_errors:
        print(f"  - {error}")

    gate_errors = validate_schema_subset(gate, gate_schema)
    require(not gate_errors, "gate_schema_validation", "strict baseline sync-ready gate validates against schema subset", failures)
    for error in gate_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, gate_schema)
    require(not record_errors, "record_gate_schema_validation", "runtime record validates against strict sync-ready gate schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.2 name", failures)
        require(PHASE9_1_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.1 commit hash", failures)

    ack_state = ack_packet.get("acknowledgement_state", {})
    require(ack_state.get("consumer_acknowledgement_status") == "acknowledged", "ack_status", "LDD acknowledgement status is acknowledged", failures)
    require(ack_state.get("consumer_ack_required") is False, "ack_required_false", "LDD acknowledgement consumer_ack_required is false", failures)
    require(ack_state.get("strict_baseline_sync_ready") is True, "ack_strict_ready", "LDD acknowledgement strict_baseline_sync_ready is true", failures)

    require(gate.get("state_name") == "strict_baseline_sync_ready", "gate_state", "strict sync-ready gate state is strict_baseline_sync_ready", failures)
    require(gate.get("consumer_acknowledged") is True, "gate_acknowledged", "strict sync-ready gate has consumer_acknowledged true", failures)
    require(gate.get("consumer_ack_required") is False, "gate_ack_required_false", "strict sync-ready gate consumer_ack_required is false", failures)
    require(gate.get("strict_baseline_sync_ready") is True, "gate_strict_ready", "strict sync-ready gate strict_baseline_sync_ready is true", failures)

    require(record.get("runtime_records_baseline_before_phase") == 114, "record_runtime_before", "runtime record baseline before phase is 114", failures)
    require(record.get("runtime_records_baseline_after_phase") == 115, "record_runtime_after", "runtime record baseline after phase is 115", failures)
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
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.2 documents and fixtures", failures)
    for item in missing_index_refs:
        print(f"Missing INDEX reference: {item}")

    required_status_lines = [
        "LDD has statically acknowledged the Phase 9.1 TWOS Runtime Status Backfeed packet.",
        "The TWOS/LDD baseline state is now strict_baseline_sync_ready.",
        "Previous LDD-visible formal TWOS baseline Vol.7 Phase 7.8 remains stale/superseded for TWOS runtime baseline purposes.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No cash state is changed by this update.",
        "No broker/Binance connection is changed by this update.",
        "No customer-facing readiness is created.",
        "No live/runtime/execution capability is created.",
    ]
    status_text = as_text(status_update)
    missing_status_lines = [line for line in required_status_lines if line not in status_text]
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.2 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"Missing status line: {line}")

    print()
    if failures:
        print("Vol.9 Phase 9.2 LDD consumer acknowledgement validation failed.")
        return 1

    print("Vol.9 Phase 9.2 LDD consumer acknowledgement validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
