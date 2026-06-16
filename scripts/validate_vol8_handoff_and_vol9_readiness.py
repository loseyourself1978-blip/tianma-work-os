#!/usr/bin/env python3
"""Validate the Vol.8 handoff summary and Vol.9 readiness gate fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.6 - Vol.8 Handoff Summary and Vol.9 Readiness Gate"
BASELINE_COMMIT = "4836b20c373b40aa92a822ee09bb718fc953ae2d"
EXPECTED_RUNTIME_RECORDS = 113
EXPECTED_FRAMEWORKS_INDEXED = 24
EXPECTED_COMPLETED_PHASES = 6

HANDOFF_SCHEMA_PATH = "schemas/vol8_handoff_summary.schema.json"
VOL9_GATE_SCHEMA_PATH = "schemas/vol9_entry_readiness_gate.schema.json"
HANDOFF_FIXTURE_PATH = "mock_consumers/ldd/vol8_handoff_summary.json"
VOL9_GATE_FIXTURE_PATH = "mock_consumers/ldd/vol9_entry_readiness_gate.json"
BACKFEED_FIXTURE_PATH = "mock_consumers/ldd/twos_ldd_post_vol8_backfeed_status_update.json"
RECORD_PATH = "records/ldd/2026-06-16/vol8_phase8_6_handoff_summary_and_vol9_readiness_gate.json"

REQUIRED_FILES = [
    "docs/runtime/VOL8_PHASE8_6_HANDOFF_SUMMARY_AND_VOL9_READINESS_GATE_v0.1.md",
    "docs/runtime/VOL8_HANDOFF_SUMMARY_v0.1.md",
    HANDOFF_SCHEMA_PATH,
    VOL9_GATE_SCHEMA_PATH,
    HANDOFF_FIXTURE_PATH,
    VOL9_GATE_FIXTURE_PATH,
    BACKFEED_FIXTURE_PATH,
    RECORD_PATH,
    "scripts/validate_vol8_handoff_and_vol9_readiness.py",
    "scripts/validate_vol8_handoff_and_vol9_readiness.sh",
]

FORBIDDEN_SCOPE = [
    "production UI",
    "customer-facing UI",
    "hosted app",
    "API server",
    "live endpoint",
    "external API",
    "broker connection",
    "Binance connection",
    "live market data",
    "trading automation",
    "credential handling",
    "login/auth",
    "runtime mutation",
    "execution trigger",
    "order placement",
    "portfolio modification",
    "background worker",
    "scheduler",
    "notification dispatcher",
]

BACKFEED_REQUIRED_FIELDS = [
    "latest_twos_phase",
    "latest_commit",
    "origin_main_state",
    "working_tree_state",
    "operating_mode",
    "portfolio_mode",
    "runtime_records",
    "frameworks_indexed",
    "customer_facing_readiness",
    "vol8_status",
    "vol9_entry_readiness",
    "static_shell_boundary",
    "forbidden_scope_remains_absent",
    "ldd_scope_reminder",
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
        required = schema.get("required", [])
        for key in required:
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
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(validate_schema_subset(item, item_schema, f"{path}[{index}]"))

    return errors


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def require(condition: bool, check_id: str, message: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {message}")
    else:
        print(f"FAIL {check_id}: {message}")
        failures.append(check_id)


def path_exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def check_handoff_values(handoff: dict[str, Any], failures: list[str], label: str = "handoff") -> None:
    require(handoff.get("baseline_commit") == BASELINE_COMMIT, f"{label}_baseline_commit", f"{label} baseline commit matches Phase 8.6", failures)
    require(handoff.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, f"{label}_runtime_records", f"{label} runtime records equal 113", failures)
    require(handoff.get("frameworks_indexed") == EXPECTED_FRAMEWORKS_INDEXED, f"{label}_framework_count", f"{label} framework count equals 24", failures)
    require(handoff.get("customer_facing_frameworks") == 0, f"{label}_customer_frameworks", f"{label} customer-facing framework count equals 0", failures)
    require(handoff.get("live_runtime_execution_frameworks") == 0, f"{label}_live_frameworks", f"{label} live/runtime/execution framework count equals 0", failures)
    require(handoff.get("fixture_static_read_only_frameworks") == EXPECTED_FRAMEWORKS_INDEXED, f"{label}_fixture_frameworks", f"{label} fixture/static/read-only framework count equals 24", failures)
    require(handoff.get("validation_backed_frameworks") == EXPECTED_FRAMEWORKS_INDEXED, f"{label}_validation_frameworks", f"{label} validation-backed framework count equals 24", failures)
    require(handoff.get("completed_phase_count") == EXPECTED_COMPLETED_PHASES, f"{label}_completed_phase_count", f"{label} completed phase count equals 6", failures)
    require(len(as_list(handoff.get("completed_phases"))) == EXPECTED_COMPLETED_PHASES, f"{label}_completed_phase_list", f"{label} lists 6 completed phases", failures)
    require(handoff.get("vol8_status") == "completed", f"{label}_vol8_status", f"{label} Vol.8 status is completed", failures)
    require(handoff.get("handoff_status") == "ready", f"{label}_handoff_status", f"{label} handoff status is ready", failures)
    require(handoff.get("customer_facing_readiness") is False, f"{label}_customer_facing_readiness", f"{label} customer-facing readiness is false", failures)
    require(handoff.get("network_allowed") is False, f"{label}_network_allowed", f"{label} network_allowed is false", failures)
    require(handoff.get("execution_allowed") is False, f"{label}_execution_allowed", f"{label} execution_allowed is false", failures)
    require(all(item in as_list(handoff.get("forbidden_scope_confirmed_absent")) for item in FORBIDDEN_SCOPE), f"{label}_forbidden_scope", f"{label} confirms forbidden scope absent", failures)


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not path_exists(path))
    require(not missing, "required_files", "all Phase 8.6 handoff/readiness artifacts exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    handoff_schema = load_json(HANDOFF_SCHEMA_PATH)
    vol9_gate_schema = load_json(VOL9_GATE_SCHEMA_PATH)
    handoff = load_json(HANDOFF_FIXTURE_PATH)
    vol9_gate = load_json(VOL9_GATE_FIXTURE_PATH)
    backfeed = load_json(BACKFEED_FIXTURE_PATH)
    record = load_json(RECORD_PATH)

    handoff_errors = validate_schema_subset(handoff, handoff_schema)
    require(not handoff_errors, "handoff_schema_validation", "Vol.8 handoff summary fixture validates against schema", failures)
    for error in handoff_errors:
        print(f"  - {error}")

    gate_errors = validate_schema_subset(vol9_gate, vol9_gate_schema)
    require(not gate_errors, "vol9_gate_schema_validation", "Vol.9 entry readiness gate fixture validates against schema", failures)
    for error in gate_errors:
        print(f"  - {error}")

    record_errors = validate_schema_subset(record, handoff_schema)
    require(not record_errors, "record_schema_validation", "Phase 8.6 runtime record validates against handoff schema subset", failures)
    for error in record_errors:
        print(f"  - {error}")

    check_handoff_values(handoff, failures)
    check_handoff_values(record, failures, "record")

    require(vol9_gate.get("baseline_commit") == BASELINE_COMMIT, "gate_baseline_commit", "Vol.9 gate baseline commit matches Phase 8.6", failures)
    require(vol9_gate.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "gate_runtime_records", "Vol.9 gate runtime records equal 113", failures)
    require(vol9_gate.get("entry_readiness") == "ready_with_limits", "gate_entry_readiness", "Vol.9 readiness is ready_with_limits", failures)
    require(vol9_gate.get("requires_future_gate_before_implementation") is True, "gate_future_gate_required", "Vol.9 requires a future gate before implementation", failures)
    require(vol9_gate.get("customer_facing_readiness") is False, "gate_customer_facing_readiness", "Vol.9 customer-facing readiness is false", failures)
    require(vol9_gate.get("network_allowed") is False, "gate_network_allowed", "Vol.9 network_allowed is false", failures)
    require(vol9_gate.get("execution_allowed") is False, "gate_execution_allowed", "Vol.9 execution_allowed is false", failures)
    require(all(item in as_list(vol9_gate.get("default_forbidden_scope")) for item in FORBIDDEN_SCOPE), "gate_forbidden_scope", "Vol.9 default forbidden scope is preserved", failures)
    require(bool(as_list(vol9_gate.get("recommended_scope"))), "gate_recommended_scope", "Vol.9 recommended scope is present", failures)
    require(bool(as_list(vol9_gate.get("allowed_readiness_levels"))), "gate_allowed_levels", "Vol.9 allowed readiness levels are present", failures)
    require(bool(as_list(vol9_gate.get("disallowed_readiness_levels"))), "gate_disallowed_levels", "Vol.9 disallowed readiness levels are present", failures)

    if isinstance(backfeed, dict):
        missing_backfeed = [field for field in BACKFEED_REQUIRED_FIELDS if field not in backfeed]
    else:
        missing_backfeed = BACKFEED_REQUIRED_FIELDS
    require(not missing_backfeed, "backfeed_required_fields", "TWOS/LDD post-Vol.8 backfeed has required core fields", failures)
    for field in missing_backfeed:
        print(f"Missing backfeed field: {field}")

    require(backfeed.get("latest_twos_phase") == PHASE, "backfeed_phase", "backfeed latest phase matches Phase 8.6", failures)
    require(backfeed.get("latest_commit") == BASELINE_COMMIT, "backfeed_commit", "backfeed latest commit matches Phase 8.6 baseline", failures)
    require(backfeed.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "backfeed_runtime_records", "backfeed runtime records equal 113", failures)
    require(backfeed.get("frameworks_indexed") == EXPECTED_FRAMEWORKS_INDEXED, "backfeed_frameworks", "backfeed framework count equals 24", failures)
    require(backfeed.get("customer_facing_readiness") is False, "backfeed_customer_false", "backfeed customer-facing readiness is false", failures)
    require(backfeed.get("vol8_status") == "completed", "backfeed_vol8_completed", "backfeed Vol.8 status is completed", failures)
    require(backfeed.get("vol9_entry_readiness") == "ready_with_limits", "backfeed_vol9_ready", "backfeed Vol.9 readiness is ready_with_limits", failures)
    require(backfeed.get("forbidden_scope_remains_absent") is True, "backfeed_forbidden_absent", "backfeed confirms forbidden scope remains absent", failures)
    require(non_empty_string(backfeed.get("ldd_scope_reminder")), "backfeed_ldd_scope", "backfeed includes LDD full-market scope reminder", failures)
    require(record.get("fixture_only") is True and record.get("read_only") is True, "record_static_flags", "runtime record remains fixture-only and read-only", failures)
    require(record.get("customer_facing") is False, "record_customer_facing", "runtime record is not customer-facing", failures)

    print()
    if failures:
        print("Vol.8 handoff and Vol.9 readiness validation failed.")
        print(f"Failures: {', '.join(failures)}")
        return 1

    print("Vol.8 handoff and Vol.9 readiness validation passed.")
    print(f"Phase: {PHASE}")
    print(f"Baseline commit: {BASELINE_COMMIT}")
    print(f"Runtime records: {EXPECTED_RUNTIME_RECORDS}")
    print(f"Frameworks indexed: {EXPECTED_FRAMEWORKS_INDEXED}")
    print("Vol.8 status: completed")
    print("Vol.9 entry readiness: ready_with_limits")
    print("Customer-facing readiness: false")
    print("Network allowed: false")
    print("Execution allowed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
