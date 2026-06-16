#!/usr/bin/env python3
"""Validate the implemented function framework index output module."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.4 - Feedback-to-Roadmap Product Boundary Mapping"
BASELINE_COMMIT = "5a13f54bd36a81f4ba39530c63899ec4529807d5"
EXPECTED_RUNTIME_RECORDS = 111
EXPECTED_INDEX_VERSION = "v0.1"

SCHEMA_PATH = "schemas/implemented_function_framework_index.schema.json"
FIXTURE_PATH = "mock_consumers/ldd/implemented_function_framework_index.json"
MARKDOWN_PATH = "docs/runtime/IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX_v0.1.md"
RECORD_PATH = "records/ldd/2026-06-16/vol8_phase8_4_feedback_to_roadmap_product_boundary_mapping.json"

REQUIRED_FILES = [
    "docs/runtime/VOL8_PHASE8_2_IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX_OUTPUT_MODULE_v0.1.md",
    "docs/runtime/VOL8_PHASE8_3_LOCAL_OPERATOR_FEEDBACK_REVIEW_MODEL_v0.1.md",
    "docs/runtime/VOL8_PHASE8_4_FEEDBACK_TO_ROADMAP_PRODUCT_BOUNDARY_MAPPING_v0.1.md",
    SCHEMA_PATH,
    FIXTURE_PATH,
    MARKDOWN_PATH,
    RECORD_PATH,
    "scripts/generate_implemented_function_framework_index.py",
    "scripts/validate_implemented_function_framework_index.py",
    "scripts/validate_implemented_function_framework_index.sh"
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
    "GitHub Issues",
    "GitHub Projects board",
    "package manager files",
    "build tools",
    "frontend framework",
    "network dependency"
]


def load_json(path: str) -> dict[str, Any]:
    value = json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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


def require(condition: bool, check_id: str, message: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {message}")
    else:
        print(f"FAIL {check_id}: {message}")
        failures.append(check_id)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def path_exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not path_exists(path))
    require(not missing, "required_files", "all Phase 8.4 documents, schema, fixture, record, generator, and validators exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    schema = load_json(SCHEMA_PATH)
    index = load_json(FIXTURE_PATH)
    record = load_json(RECORD_PATH)
    markdown = (REPO_ROOT / MARKDOWN_PATH).read_text(encoding="utf-8")

    schema_errors = validate_schema_subset(index, schema)
    require(not schema_errors, "schema_validation", "implemented function framework index fixture validates against schema", failures)
    for error in schema_errors:
        print(f"  - {error}")

    require(index.get("index_version") == EXPECTED_INDEX_VERSION, "index_version", "index version is v0.1", failures)
    require(index.get("generated_for_phase") == PHASE, "phase", "generated phase matches Phase 8.4", failures)
    require(index.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", "baseline commit matches Phase 8.4 commit", failures)
    require(index.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "runtime_records", "runtime records baseline equals 111", failures)
    require(index.get("customer_facing_readiness") is False, "customer_facing_readiness", "customer-facing readiness remains false", failures)

    frameworks = as_list(index.get("frameworks"))
    require(bool(frameworks), "frameworks_present", "framework entries are present", failures)
    seen_ids: set[str] = set()
    validation_backed = 0
    fixture_static_read_only = 0

    for item in frameworks:
        if not isinstance(item, dict):
            failures.append("framework_item_type")
            print("FAIL framework_item_type: framework entry must be an object")
            continue

        framework_id = str(item.get("framework_id", "missing"))
        require(non_empty_string(item.get("framework_name")), f"{framework_id}_name", f"{framework_id} has a non-empty name", failures)
        require(non_empty_string(item.get("implemented_since_phase")), f"{framework_id}_implemented_phase", f"{framework_id} has implemented phase", failures)
        require(non_empty_string(item.get("implemented_since_version")), f"{framework_id}_implemented_version", f"{framework_id} has implemented version", failures)
        require(non_empty_string(item.get("latest_verified_phase")), f"{framework_id}_latest_phase", f"{framework_id} has latest verified phase", failures)

        artifact_paths = [str(path) for path in as_list(item.get("artifact_paths"))]
        validation_paths = [str(path) for path in as_list(item.get("validation_paths"))]
        runtime_record_paths = [str(path) for path in as_list(item.get("runtime_record_paths"))]

        require(bool(artifact_paths), f"{framework_id}_artifact_paths", f"{framework_id} has artifact paths", failures)
        require(all(path_exists(path) for path in artifact_paths), f"{framework_id}_artifact_paths_exist", f"{framework_id} artifact paths exist", failures)
        require(bool(validation_paths), f"{framework_id}_validation_paths", f"{framework_id} has validation paths", failures)
        require(all(path_exists(path) for path in validation_paths), f"{framework_id}_validation_paths_exist", f"{framework_id} validation paths exist", failures)
        require(isinstance(item.get("customer_facing"), bool), f"{framework_id}_customer_bool", f"{framework_id} customer_facing is boolean", failures)
        require(isinstance(item.get("fixture_only"), bool), f"{framework_id}_fixture_bool", f"{framework_id} fixture_only is boolean", failures)
        require(isinstance(item.get("read_only"), bool), f"{framework_id}_read_only_bool", f"{framework_id} read_only is boolean", failures)
        require(isinstance(item.get("network_allowed"), bool), f"{framework_id}_network_bool", f"{framework_id} network_allowed is boolean", failures)
        require(isinstance(item.get("execution_allowed"), bool), f"{framework_id}_execution_bool", f"{framework_id} execution_allowed is boolean", failures)
        require(item.get("customer_facing") is False, f"{framework_id}_customer_false", f"{framework_id} is not customer-facing", failures)
        require(item.get("network_allowed") is False, f"{framework_id}_network_false", f"{framework_id} has no network", failures)
        require(item.get("execution_allowed") is False, f"{framework_id}_execution_false", f"{framework_id} has no execution", failures)
        require(item.get("fixture_only") is True, f"{framework_id}_fixture_true", f"{framework_id} is fixture/static only", failures)
        require(item.get("read_only") is True, f"{framework_id}_read_only_true", f"{framework_id} is read-only", failures)
        require(non_empty_string(item.get("next_improvement")), f"{framework_id}_next_improvement", f"{framework_id} has next improvement note", failures)

        if validation_paths:
            validation_backed += 1
        if item.get("fixture_only") is True and item.get("read_only") is True and item.get("network_allowed") is False and item.get("execution_allowed") is False:
            fixture_static_read_only += 1
        if framework_id in seen_ids:
            print(f"FAIL duplicate_framework_id: {framework_id}")
            failures.append(f"duplicate_{framework_id}")
        seen_ids.add(framework_id)

        missing_records = [path for path in runtime_record_paths if not path_exists(path)]
        require(not missing_records, f"{framework_id}_runtime_records_exist", f"{framework_id} runtime record paths exist when listed", failures)

    summary = index.get("summary") if isinstance(index.get("summary"), dict) else {}
    require(summary.get("total_implemented_frameworks") == len(frameworks), "summary_total", "summary total matches framework count", failures)
    require(summary.get("customer_facing_frameworks") == 0, "summary_customer", "summary customer-facing frameworks equals 0", failures)
    require(summary.get("live_runtime_execution_frameworks") == 0, "summary_live_execution", "summary live/runtime/execution frameworks equals 0", failures)
    require(summary.get("fixture_static_read_only_frameworks") == fixture_static_read_only, "summary_fixture_static", "summary fixture/static/read-only count matches entries", failures)
    require(summary.get("validation_backed_frameworks") == validation_backed, "summary_validation", "summary validation-backed count matches entries", failures)
    require(all(item in as_list(index.get("forbidden_scope_confirmed_absent")) for item in FORBIDDEN_SCOPE), "forbidden_scope", "all forbidden scope is confirmed absent", failures)

    require("# Implemented Function Framework Index v0.1" in markdown, "markdown_title", "generated markdown has expected title", failures)
    require(str(len(frameworks)) in markdown, "markdown_count", "generated markdown includes framework count", failures)
    require(record.get("baseline_commit") == BASELINE_COMMIT and record.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "record_baseline", "runtime record preserves Phase 8.4 baseline metadata", failures)
    require(record.get("network_allowed") is False and record.get("execution_allowed") is False and record.get("customer_facing") is False, "record_boundaries", "runtime record keeps no-network/no-execution/not-customer-facing boundaries", failures)

    print()
    if failures:
        print("Implemented function framework index validation failed.")
    else:
        print("Implemented function framework index validation passed.")
    print(f"Frameworks indexed: {len(frameworks)}")
    print(f"Validation-backed frameworks: {validation_backed}")
    print(f"Fixture/static/read-only frameworks: {fixture_static_read_only}")
    print(f"Customer-facing frameworks: {summary.get('customer_facing_frameworks')}")
    print(f"Live/runtime/execution frameworks: {summary.get('live_runtime_execution_frameworks')}")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
