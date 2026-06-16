#!/usr/bin/env python3
"""Validate Vol.8 Phase 8.4 feedback-to-roadmap boundary mapping artifacts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.4 - Feedback-to-Roadmap Product Boundary Mapping"
BASELINE_COMMIT = "5a13f54bd36a81f4ba39530c63899ec4529807d5"
EXPECTED_RUNTIME_RECORDS = 111
STATIC_SHELL_PATH = "static_shell/ldd/"

MAPPING_SCHEMA_PATH = "schemas/vol8_feedback_to_roadmap_mapping.schema.json"
BOUNDARY_MAP_SCHEMA_PATH = "schemas/vol8_feedback_to_roadmap_boundary_map.schema.json"
ITEMS_PATH = "mock_consumers/ldd/vol8_feedback_to_roadmap_mapping_sample.json"
BOUNDARY_MAP_PATH = "mock_consumers/ldd/vol8_feedback_to_roadmap_boundary_map.json"
BOUNDARY_MAP_MARKDOWN_PATH = "docs/runtime/VOL8_FEEDBACK_TO_ROADMAP_BOUNDARY_MAP_v0.1.md"

REQUIRED_FILES = [
    "docs/runtime/VOL8_PHASE8_4_FEEDBACK_TO_ROADMAP_PRODUCT_BOUNDARY_MAPPING_v0.1.md",
    "docs/runtime/VOL8_FEEDBACK_TO_ROADMAP_MAPPING_GUIDE_v0.1.md",
    BOUNDARY_MAP_MARKDOWN_PATH,
    MAPPING_SCHEMA_PATH,
    BOUNDARY_MAP_SCHEMA_PATH,
    ITEMS_PATH,
    BOUNDARY_MAP_PATH,
    "records/ldd/2026-06-16/vol8_phase8_4_feedback_to_roadmap_product_boundary_mapping.json",
    "scripts/generate_vol8_feedback_to_roadmap_boundary_map.py",
    "scripts/validate_vol8_feedback_to_roadmap_mapping.py",
    "scripts/validate_vol8_feedback_to_roadmap_mapping.sh"
]

DEFERRED_CATEGORIES = {
    "live_runtime_request_deferred",
    "execution_request_deferred",
    "credential_or_auth_request_deferred",
    "customer_facing_request_deferred",
}


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


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 8.4 docs, schemas, fixtures, record, generator, and validators exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    mapping_schema = load_json_any(MAPPING_SCHEMA_PATH)
    boundary_map_schema = load_json_any(BOUNDARY_MAP_SCHEMA_PATH)
    items = load_json_any(ITEMS_PATH)
    boundary_map = load_json_any(BOUNDARY_MAP_PATH)
    markdown = (REPO_ROOT / BOUNDARY_MAP_MARKDOWN_PATH).read_text(encoding="utf-8")

    if not isinstance(mapping_schema, dict) or not isinstance(boundary_map_schema, dict):
        print("FAIL schema_type: schemas must be JSON objects")
        return 1

    item_errors = validate_schema_subset(items, mapping_schema)
    map_errors = validate_schema_subset(boundary_map, boundary_map_schema)
    require(not item_errors, "mapping_schema_validation", "mapping sample items validate against mapping schema", failures)
    for error in item_errors:
        print(f"  - {error}")
    require(not map_errors, "boundary_map_schema_validation", "boundary map validates against boundary map schema", failures)
    for error in map_errors:
        print(f"  - {error}")

    require(isinstance(items, list) and bool(items), "mapped_items_present", "mapping sample item list is present", failures)
    require(isinstance(boundary_map, dict), "boundary_map_object", "boundary map fixture is a JSON object", failures)

    require(boundary_map.get("phase") == PHASE, "boundary_map_phase", "boundary map phase matches Phase 8.4", failures)
    require(boundary_map.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", "baseline commit matches Phase 8.4 commit", failures)
    require(boundary_map.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "runtime_records", "runtime records baseline equals 111", failures)
    require(boundary_map.get("static_shell_path") == STATIC_SHELL_PATH, "static_shell_path", "static shell path is static_shell/ldd/", failures)
    require(boundary_map.get("customer_facing_readiness") is False, "customer_facing_readiness", "customer-facing readiness remains false", failures)

    allowed_categories = set(mapping_schema.get("items", {}).get("properties", {}).get("mapping_category", {}).get("enum", []))
    allowed_decisions = set(mapping_schema.get("items", {}).get("properties", {}).get("boundary_decision", {}).get("enum", []))

    category_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    safe_static_count = 0
    roadmap_only_count = 0
    future_gate_count = 0
    rejected_count = 0
    deferred_count = 0

    for index, item in enumerate(as_list(items), start=1):
        if not isinstance(item, dict):
            require(False, f"item_{index}_type", f"mapping item {index} is an object", failures)
            continue

        mapping_id = str(item.get("mapping_id", f"item_{index}"))
        require(non_empty_string(item.get("source_feedback_id")), f"{mapping_id}_source_id", f"{mapping_id} has source feedback reference", failures)
        require(non_empty_string(item.get("source_feedback_title")), f"{mapping_id}_source_title", f"{mapping_id} has source feedback title", failures)
        require(item.get("mapping_category") in allowed_categories, f"{mapping_id}_category", f"{mapping_id} has valid mapping category", failures)
        require(item.get("boundary_decision") in allowed_decisions, f"{mapping_id}_decision", f"{mapping_id} has valid boundary decision", failures)
        require(non_empty_string(item.get("allowed_current_action")), f"{mapping_id}_allowed_action", f"{mapping_id} has allowed current action", failures)
        require(non_empty_string(item.get("disallowed_current_action")), f"{mapping_id}_disallowed_action", f"{mapping_id} has disallowed current action", failures)
        require(isinstance(item.get("affected_artifacts"), list), f"{mapping_id}_affected_artifacts", f"{mapping_id} has affected artifacts array", failures)
        require(non_empty_string(item.get("recommended_next_action")), f"{mapping_id}_recommended_next_action", f"{mapping_id} has recommended next action", failures)

        for key in ["customer_facing_allowed", "network_or_api_allowed", "execution_or_mutation_allowed", "credential_or_auth_allowed"]:
            require(item.get(key) is False, f"{mapping_id}_{key}_false", f"{mapping_id} keeps {key} false", failures)

        category = str(item.get("mapping_category"))
        decision = str(item.get("boundary_decision"))
        category_counts[category] += 1
        decision_counts[decision] += 1
        if decision == "safe_to_refine_now_static_only":
            safe_static_count += 1
        if item.get("roadmap_only") is True:
            roadmap_only_count += 1
        if item.get("requires_future_gate") is True:
            future_gate_count += 1
        if category == "forbidden_scope_rejected":
            rejected_count += 1
        if category in DEFERRED_CATEGORIES:
            deferred_count += 1

    summary = boundary_map.get("summary") if isinstance(boundary_map.get("summary"), dict) else {}
    require(summary.get("total_mapped_items") == len(as_list(items)), "summary_total", "boundary map total matches mapped item count", failures)
    require(summary.get("count_by_mapping_category") == dict(category_counts), "summary_category_counts", "boundary map category counts match items", failures)
    require(summary.get("count_by_boundary_decision") == dict(decision_counts), "summary_decision_counts", "boundary map decision counts match items", failures)
    require(summary.get("safe_static_only_refinements_count") == safe_static_count, "summary_safe_static", "safe static-only count matches items", failures)
    require(summary.get("roadmap_only_candidates_count") == roadmap_only_count, "summary_roadmap", "roadmap-only count matches items", failures)
    require(summary.get("future_readiness_gate_required_count") == future_gate_count, "summary_future_gate", "future gate count matches items", failures)
    require(summary.get("rejected_forbidden_scope_count") == rejected_count, "summary_rejected", "rejected forbidden-scope count matches items", failures)
    require(summary.get("deferred_live_runtime_execution_count") == deferred_count, "summary_deferred", "deferred live/runtime/execution count matches items", failures)

    require("# Vol.8 Feedback-to-Roadmap Boundary Map v0.1" in markdown, "boundary_map_markdown_title", "generated boundary map markdown has expected title", failures)
    require(f"Total mapped items: `{len(as_list(items))}`" in markdown, "boundary_map_markdown_total", "generated boundary map markdown includes mapped item count", failures)

    print()
    if failures:
        print("Vol.8 feedback-to-roadmap mapping validation failed.")
    else:
        print("Vol.8 feedback-to-roadmap mapping validation passed.")
    print(f"Mapped items: {len(as_list(items))}")
    print(f"Safe static-only refinements: {safe_static_count}")
    print(f"Roadmap-only candidates: {roadmap_only_count}")
    print(f"Future readiness gates required: {future_gate_count}")
    print(f"Rejected forbidden-scope requests: {rejected_count}")
    print(f"Deferred live/runtime/execution requests: {deferred_count}")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
