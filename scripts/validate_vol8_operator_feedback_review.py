#!/usr/bin/env python3
"""Validate Vol.8 Phase 8.3 local operator feedback review artifacts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.3 - Local Operator Feedback Review Model"
BASELINE_COMMIT = "2cc8a93885c0d8254189d3237153113135508529"
EXPECTED_RUNTIME_RECORDS = 110
STATIC_SHELL_PATH = "static_shell/ldd/"

REVIEW_SCHEMA_PATH = "schemas/vol8_operator_feedback_review.schema.json"
ROLLUP_SCHEMA_PATH = "schemas/vol8_operator_feedback_rollup.schema.json"
ITEMS_PATH = "mock_consumers/ldd/vol8_operator_feedback_review_sample.json"
ROLLUP_PATH = "mock_consumers/ldd/vol8_operator_feedback_rollup.json"
ROLLUP_MARKDOWN_PATH = "docs/runtime/VOL8_LOCAL_OPERATOR_FEEDBACK_ROLLUP_v0.1.md"

REQUIRED_FILES = [
    "docs/runtime/VOL8_PHASE8_3_LOCAL_OPERATOR_FEEDBACK_REVIEW_MODEL_v0.1.md",
    "docs/runtime/VOL8_LOCAL_OPERATOR_FEEDBACK_REVIEW_GUIDE_v0.1.md",
    ROLLUP_MARKDOWN_PATH,
    REVIEW_SCHEMA_PATH,
    ROLLUP_SCHEMA_PATH,
    ITEMS_PATH,
    ROLLUP_PATH,
    "records/ldd/2026-06-16/vol8_phase8_3_local_operator_feedback_review_model.json",
    "scripts/generate_vol8_operator_feedback_rollup.py",
    "scripts/validate_vol8_operator_feedback_review.py",
    "scripts/validate_vol8_operator_feedback_review.sh"
]

SAFE_EXCEPTION_ROUTES = {"reject_forbidden_scope", "defer_until_future_readiness_gate"}


def load_json_any(path: str) -> Any:
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
        for index, item in enumerate(value):
            errors.extend(validate_schema_subset(item, schema["items"], f"{path}[{index}]"))

    return errors


def require(condition: bool, check_id: str, message: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {message}")
    else:
        print(f"FAIL {check_id}: {message}")
        failures.append(check_id)


def non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def route_allows_claim(item: dict[str, Any], key: str) -> bool:
    if item.get(key) is False:
        return True
    return item.get("routing") in SAFE_EXCEPTION_ROUTES


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 8.3 docs, schemas, fixtures, record, generator, and validators exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    review_schema = load_json_any(REVIEW_SCHEMA_PATH)
    rollup_schema = load_json_any(ROLLUP_SCHEMA_PATH)
    items = load_json_any(ITEMS_PATH)
    rollup = load_json_any(ROLLUP_PATH)
    markdown = (REPO_ROOT / ROLLUP_MARKDOWN_PATH).read_text(encoding="utf-8")

    if not isinstance(review_schema, dict) or not isinstance(rollup_schema, dict):
        print("FAIL schema_type: schemas must be JSON objects")
        return 1

    item_errors = validate_schema_subset(items, review_schema)
    rollup_errors = validate_schema_subset(rollup, rollup_schema)
    require(not item_errors, "feedback_schema_validation", "sample feedback items validate against review schema", failures)
    for error in item_errors:
        print(f"  - {error}")
    require(not rollup_errors, "rollup_schema_validation", "feedback rollup validates against rollup schema", failures)
    for error in rollup_errors:
        print(f"  - {error}")

    require(isinstance(items, list) and bool(items), "feedback_items_present", "sample feedback item list is present", failures)
    require(isinstance(rollup, dict), "rollup_object", "rollup fixture is a JSON object", failures)

    require(rollup.get("phase") == PHASE, "rollup_phase", "rollup phase matches Phase 8.3", failures)
    require(rollup.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", "baseline commit matches Phase 8.2 commit", failures)
    require(rollup.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "runtime_records", "runtime records baseline equals 110", failures)
    require(rollup.get("static_shell_path") == STATIC_SHELL_PATH, "static_shell_path", "static shell path is static_shell/ldd/", failures)
    require(rollup.get("customer_facing_readiness") is False, "customer_facing_readiness", "customer-facing readiness remains false", failures)

    allowed_categories = set(review_schema.get("items", {}).get("properties", {}).get("category", {}).get("enum", []))
    allowed_severities = set(review_schema.get("items", {}).get("properties", {}).get("severity", {}).get("enum", []))
    allowed_routing = set(review_schema.get("items", {}).get("properties", {}).get("routing", {}).get("enum", []))

    category_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    routing_counts: Counter[str] = Counter()
    forbidden_count = 0
    live_runtime_execution_count = 0
    accepted_static_count = 0
    roadmap_only_count = 0

    for index, item in enumerate(as_list(items), start=1):
        if not isinstance(item, dict):
            require(False, f"item_{index}_type", f"feedback item {index} is an object", failures)
            continue

        feedback_id = str(item.get("feedback_id", f"item_{index}"))
        require(non_empty_string(item.get("feedback_title")), f"{feedback_id}_title", f"{feedback_id} has a non-empty title", failures)
        require(item.get("category") in allowed_categories, f"{feedback_id}_category", f"{feedback_id} has a valid category", failures)
        require(item.get("severity") in allowed_severities, f"{feedback_id}_severity", f"{feedback_id} has a valid severity", failures)
        require(item.get("routing") in allowed_routing, f"{feedback_id}_routing", f"{feedback_id} has a valid routing", failures)
        require(isinstance(item.get("affected_artifacts"), list), f"{feedback_id}_affected_artifacts", f"{feedback_id} has affected artifacts array", failures)
        require(non_empty_string(item.get("recommended_action")), f"{feedback_id}_recommended_action", f"{feedback_id} has recommended action", failures)

        for key in ["customer_facing_claim", "network_or_api_claim", "execution_or_mutation_claim", "credential_or_auth_claim"]:
            require(isinstance(item.get(key), bool), f"{feedback_id}_{key}_bool", f"{feedback_id} {key} is boolean", failures)
            require(route_allows_claim(item, key), f"{feedback_id}_{key}_safe", f"{feedback_id} {key} is false or safely rejected/deferred", failures)

        category_counts[str(item.get("category"))] += 1
        severity_counts[str(item.get("severity"))] += 1
        routing_counts[str(item.get("routing"))] += 1
        if item.get("category") == "forbidden_scope_request":
            forbidden_count += 1
        if item.get("category") in {"live_runtime_request", "execution_related_request"} or item.get("network_or_api_claim") is True or item.get("execution_or_mutation_claim") is True:
            live_runtime_execution_count += 1
        if item.get("routing") not in {"future_roadmap_backlog", "reject_forbidden_scope", "defer_until_future_readiness_gate"}:
            accepted_static_count += 1
        if item.get("roadmap_only") is True:
            roadmap_only_count += 1

    summary = rollup.get("summary") if isinstance(rollup.get("summary"), dict) else {}
    require(summary.get("total_feedback_items") == len(as_list(items)), "summary_total", "rollup total matches feedback item count", failures)
    require(summary.get("forbidden_scope_requests_count") == forbidden_count, "summary_forbidden", "rollup forbidden-scope count matches items", failures)
    require(summary.get("live_runtime_execution_requests_count") == live_runtime_execution_count, "summary_live_execution", "rollup live/runtime/execution count matches items", failures)
    require(summary.get("accepted_static_shell_feedback_count") == accepted_static_count, "summary_accepted_static", "rollup accepted static-shell count matches items", failures)
    require(summary.get("roadmap_only_feedback_count") == roadmap_only_count, "summary_roadmap", "rollup roadmap-only count matches items", failures)
    require(summary.get("count_by_category") == dict(category_counts), "summary_category_counts", "rollup category counts match items", failures)
    require(summary.get("count_by_severity") == dict(severity_counts), "summary_severity_counts", "rollup severity counts match items", failures)
    require(summary.get("count_by_routing") == dict(routing_counts), "summary_routing_counts", "rollup routing counts match items", failures)

    require("# Vol.8 Local Operator Feedback Rollup v0.1" in markdown, "rollup_markdown_title", "generated rollup markdown has expected title", failures)
    require(f"Total feedback items: `{len(as_list(items))}`" in markdown, "rollup_markdown_total", "generated rollup markdown includes feedback count", failures)

    print()
    if failures:
        print("Vol.8 operator feedback review validation failed.")
    else:
        print("Vol.8 operator feedback review validation passed.")
    print(f"Feedback items: {len(as_list(items))}")
    print(f"Forbidden-scope requests: {forbidden_count}")
    print(f"Live/runtime/execution requests: {live_runtime_execution_count}")
    print(f"Accepted static-shell feedback: {accepted_static_count}")
    print(f"Roadmap-only feedback: {roadmap_only_count}")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
