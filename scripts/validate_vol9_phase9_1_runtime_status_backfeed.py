#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.1 baseline drift backfeed artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.1"
BASELINE_COMMIT = "c58243df6f9685f13c0017e4f87798f844d53277"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

BACKFEED_SCHEMA_PATH = "schemas/twos_ldd_runtime_status_backfeed_protocol.schema.json"
DRIFT_SCHEMA_PATH = "schemas/cross_workspace_baseline_drift_state.schema.json"
BACKFEED_FIXTURE_PATH = "mock_consumers/ldd/twos_ldd_runtime_status_backfeed_protocol.json"
DRIFT_GATE_PATH = "mock_consumers/ldd/cross_workspace_baseline_drift_resolution_gate.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_vol8_to_vol9_backfeed_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_1_cross_workspace_baseline_drift_resolution_and_backfeed_protocol.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_1_CROSS_WORKSPACE_BASELINE_DRIFT_RESOLUTION_AND_BACKFEED_PROTOCOL_v0.1.md",
    "docs/runtime/TWOS_LDD_RUNTIME_STATUS_BACKFEED_PROTOCOL_v0.1.md",
    BACKFEED_SCHEMA_PATH,
    DRIFT_SCHEMA_PATH,
    BACKFEED_FIXTURE_PATH,
    DRIFT_GATE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_1_runtime_status_backfeed.py",
    "scripts/validate_vol9_phase9_1_runtime_status_backfeed.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_1_CROSS_WORKSPACE_BASELINE_DRIFT_RESOLUTION_AND_BACKFEED_PROTOCOL_v0.1.md",
    "docs/runtime/TWOS_LDD_RUNTIME_STATUS_BACKFEED_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/twos_ldd_runtime_status_backfeed_protocol.json",
    "mock_consumers/ldd/cross_workspace_baseline_drift_resolution_gate.json",
    "mock_consumers/ldd/twos_ldd_post_vol8_to_vol9_backfeed_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_1_cross_workspace_baseline_drift_resolution_and_backfeed_protocol.json",
    "scripts/validate_vol9_phase9_1_runtime_status_backfeed.py",
]

MOCK_FIXTURES = [
    BACKFEED_FIXTURE_PATH,
    DRIFT_GATE_PATH,
    STATUS_UPDATE_PATH,
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


def nested_true_forbidden_flags(value: Any, path: str = "$") -> list[str]:
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
            errors.extend(nested_true_forbidden_flags(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(nested_true_forbidden_flags(child, f"{path}[{index}]"))
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.1 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        backfeed_schema = load_json(BACKFEED_SCHEMA_PATH)
        drift_schema = load_json(DRIFT_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(isinstance(backfeed_schema, dict) and isinstance(drift_schema, dict), "schema_parse", "schema files are parseable JSON objects", failures)

    parsed_json: dict[str, Any] = {}
    for path in [BACKFEED_FIXTURE_PATH, DRIFT_GATE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    backfeed = parsed_json[BACKFEED_FIXTURE_PATH]
    drift_gate = parsed_json[DRIFT_GATE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    backfeed_errors = validate_schema_subset(backfeed, backfeed_schema)
    require(not backfeed_errors, "backfeed_schema_validation", "runtime status backfeed fixture validates against schema subset", failures)
    for error in backfeed_errors:
        print(f"  - {error}")

    drift_gate_errors = validate_schema_subset(drift_gate, drift_schema)
    require(not drift_gate_errors, "drift_gate_schema_validation", "drift gate fixture validates against schema subset", failures)
    for error in drift_gate_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, drift_schema)
    require(not record_errors, "record_drift_schema_validation", "runtime record validates against drift state schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required phase name", failures)
        require(BASELINE_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required commit hash", failures)

    require(drift_gate.get("state_name") == "backfeed_packet_ready", "drift_gate_state", "drift gate state is backfeed_packet_ready", failures)
    require(drift_gate.get("consumer_ack_required") is True, "drift_gate_consumer_ack", "drift gate requires consumer acknowledgement", failures)
    require(drift_gate.get("strict_sync_ready") is False, "drift_gate_strict_sync", "drift gate strict_sync_ready is false", failures)

    require(record.get("runtime_records_baseline_before_phase") == 113, "record_runtime_before", "runtime record baseline before phase is 113", failures)
    require(record.get("runtime_records_baseline_after_phase") == 114, "record_runtime_after", "runtime record baseline after phase is 114", failures)
    require(record.get("customer_facing_readiness") is False, "record_customer_facing", "runtime record customer-facing readiness is false", failures)
    require(record.get("live_runtime_execution_frameworks") == 0, "record_live_runtime_frameworks", "runtime record live/runtime/execution frameworks equal 0", failures)
    require(record.get("static_shell_mode") == STATIC_SHELL_MODE, "record_static_shell_mode", "runtime record static shell mode is locked", failures)

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
        flag_errors.extend(f"{path}: {error}" for error in nested_true_forbidden_flags(document))
    require(not flag_errors, "forbidden_enabled_json_flags", "JSON artifacts do not enable forbidden capabilities", failures)
    for error in flag_errors:
        print(f"  - {error}")

    index_text = (REPO_ROOT / "INDEX.md").read_text(encoding="utf-8")
    missing_index_refs = [item for item in INDEX_REQUIRED_REFERENCES if item not in index_text]
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.1 documents and fixtures", failures)
    for item in missing_index_refs:
        print(f"Missing INDEX reference: {item}")

    required_status_lines = [
        "Latest repository-validated TWOS baseline is Vol.8 Phase 8.6.",
        "Previous LDD-visible formal TWOS baseline Vol.7 Phase 7.8 is now stale/superseded for TWOS runtime baseline purposes.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No customer-facing readiness is created.",
        "No live/runtime/execution capability is created.",
    ]
    status_text = as_text(status_update)
    missing_status_lines = [line for line in required_status_lines if line not in status_text]
    require(not missing_status_lines, "status_update_lines", "post-Vol.8-to-Vol.9 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"Missing status line: {line}")

    print()
    if failures:
        print("Vol.9 Phase 9.1 runtime status backfeed validation failed.")
        return 1

    print("Vol.9 Phase 9.1 runtime status backfeed validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
