#!/usr/bin/env python3
"""Validate Vol.8 Phase 8.5 future implementation readiness ladder artifacts."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.5 - Future Implementation Readiness Ladder"
BASELINE_COMMIT = "59401955f861af4c1313b2973d1528278474cc18"
EXPECTED_RUNTIME_RECORDS = 112
STATIC_SHELL_PATH = "static_shell/ldd/"

ITEM_SCHEMA_PATH = "schemas/vol8_future_implementation_readiness_item.schema.json"
LADDER_SCHEMA_PATH = "schemas/vol8_future_implementation_readiness_ladder.schema.json"
ITEMS_PATH = "mock_consumers/ldd/vol8_future_implementation_readiness_items.json"
LADDER_PATH = "mock_consumers/ldd/vol8_future_implementation_readiness_ladder.json"
LADDER_MARKDOWN_PATH = "docs/runtime/VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER_v0.1.md"

REQUIRED_FILES = [
    "docs/runtime/VOL8_PHASE8_5_FUTURE_IMPLEMENTATION_READINESS_LADDER_v0.1.md",
    "docs/runtime/VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER_GUIDE_v0.1.md",
    LADDER_MARKDOWN_PATH,
    ITEM_SCHEMA_PATH,
    LADDER_SCHEMA_PATH,
    ITEMS_PATH,
    LADDER_PATH,
    "records/ldd/2026-06-16/vol8_phase8_5_future_implementation_readiness_ladder.json",
    "scripts/generate_vol8_future_implementation_readiness_ladder.py",
    "scripts/validate_vol8_future_implementation_readiness_ladder.py",
    "scripts/validate_vol8_future_implementation_readiness_ladder.sh"
]

IMPLEMENTATION_ALLOWED_LEVELS = {"L1_static_doc_refinement_ready", "L2_static_fixture_refinement_ready"}
FUTURE_GATE_LEVELS = {
    "L5_future_runtime_candidate_requires_gate",
    "L6_future_network_api_candidate_requires_gate",
    "L7_future_customer_facing_candidate_requires_gate",
    "L8_future_security_credential_candidate_requires_gate",
    "L9_future_execution_candidate_requires_governance",
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
    require(not missing, "required_files", "all Phase 8.5 docs, schemas, fixtures, record, generator, and validators exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    item_schema = load_json_any(ITEM_SCHEMA_PATH)
    ladder_schema = load_json_any(LADDER_SCHEMA_PATH)
    items = load_json_any(ITEMS_PATH)
    ladder = load_json_any(LADDER_PATH)
    markdown = (REPO_ROOT / LADDER_MARKDOWN_PATH).read_text(encoding="utf-8")

    if not isinstance(item_schema, dict) or not isinstance(ladder_schema, dict):
        print("FAIL schema_type: schemas must be JSON objects")
        return 1

    item_errors = validate_schema_subset(items, item_schema)
    ladder_errors = validate_schema_subset(ladder, ladder_schema)
    require(not item_errors, "item_schema_validation", "readiness item fixture validates against item schema", failures)
    for error in item_errors:
        print(f"  - {error}")
    require(not ladder_errors, "ladder_schema_validation", "readiness ladder fixture validates against ladder schema", failures)
    for error in ladder_errors:
        print(f"  - {error}")

    require(isinstance(items, list) and bool(items), "readiness_items_present", "readiness item list is present", failures)
    require(isinstance(ladder, dict), "ladder_object", "readiness ladder fixture is a JSON object", failures)

    require(ladder.get("phase") == PHASE, "ladder_phase", "ladder phase matches Phase 8.5", failures)
    require(ladder.get("baseline_commit") == BASELINE_COMMIT, "baseline_commit", "baseline commit matches Phase 8.5 commit", failures)
    require(ladder.get("runtime_records") == EXPECTED_RUNTIME_RECORDS, "runtime_records", "runtime records baseline equals 112", failures)
    require(ladder.get("static_shell_path") == STATIC_SHELL_PATH, "static_shell_path", "static shell path is static_shell/ldd/", failures)
    require(ladder.get("customer_facing_readiness") is False, "customer_facing_readiness", "customer-facing readiness remains false", failures)

    allowed_levels = set(item_schema.get("items", {}).get("properties", {}).get("readiness_level", {}).get("enum", []))
    allowed_gates = set(item_schema.get("items", {}).get("properties", {}).get("required_gate_type", {}).get("enum", []))

    level_counts: Counter[str] = Counter()
    gate_counts: Counter[str] = Counter()
    static_ready_count = 0
    roadmap_only_count = 0
    future_gate_count = 0
    rejected_count = 0
    deferred_count = 0
    execution_gate_count = 0
    network_gate_count = 0
    customer_gate_count = 0
    security_gate_count = 0

    for index, item in enumerate(as_list(items), start=1):
        if not isinstance(item, dict):
            require(False, f"item_{index}_type", f"readiness item {index} is an object", failures)
            continue

        item_id = str(item.get("readiness_item_id", f"item_{index}"))
        level = str(item.get("readiness_level"))
        gate = str(item.get("required_gate_type"))

        require(non_empty_string(item.get("candidate_title")), f"{item_id}_title", f"{item_id} has a non-empty candidate title", failures)
        require(level in allowed_levels, f"{item_id}_level", f"{item_id} has a valid readiness level", failures)
        require(gate in allowed_gates, f"{item_id}_gate", f"{item_id} has a valid required gate type", failures)
        require(non_empty_string(item.get("allowed_current_action")), f"{item_id}_allowed_action", f"{item_id} has allowed current action", failures)
        require(non_empty_string(item.get("disallowed_current_action")), f"{item_id}_disallowed_action", f"{item_id} has disallowed current action", failures)
        require(isinstance(item.get("affected_artifacts"), list), f"{item_id}_affected_artifacts", f"{item_id} has affected artifacts array", failures)
        require(non_empty_string(item.get("recommended_next_action")), f"{item_id}_recommended_next_action", f"{item_id} has recommended next action", failures)

        implementation_allowed = item.get("implementation_allowed_now")
        if level in IMPLEMENTATION_ALLOWED_LEVELS:
            require(isinstance(implementation_allowed, bool), f"{item_id}_implementation_bool", f"{item_id} implementation_allowed_now is boolean", failures)
        else:
            require(implementation_allowed is False, f"{item_id}_implementation_false", f"{item_id} does not allow current implementation", failures)

        for key in ["customer_facing_allowed_now", "network_or_api_allowed_now", "execution_or_mutation_allowed_now", "credential_or_auth_allowed_now"]:
            require(item.get(key) is False, f"{item_id}_{key}_false", f"{item_id} keeps {key} false", failures)

        if level in FUTURE_GATE_LEVELS:
            require(item.get("requires_future_gate") is True, f"{item_id}_future_gate_true", f"{item_id} requires a future gate", failures)
        if level == "L0_forbidden_rejected":
            require(gate == "reject_forbidden_scope", f"{item_id}_reject_gate", f"{item_id} uses reject_forbidden_scope", failures)
        if level == "L3_roadmap_only_no_implementation":
            require(item.get("implementation_allowed_now") is False, f"{item_id}_roadmap_no_implementation", f"{item_id} roadmap-only item has no implementation approval", failures)

        level_counts[level] += 1
        gate_counts[gate] += 1
        if level in IMPLEMENTATION_ALLOWED_LEVELS:
            static_ready_count += 1
        if item.get("roadmap_only") is True:
            roadmap_only_count += 1
        if item.get("requires_future_gate") is True:
            future_gate_count += 1
        if level == "L0_forbidden_rejected":
            rejected_count += 1
        if level == "L10_out_of_scope_deferred":
            deferred_count += 1
        if gate == "execution_governance_gate":
            execution_gate_count += 1
        if gate == "network_api_integration_gate":
            network_gate_count += 1
        if gate == "customer_facing_readiness_gate":
            customer_gate_count += 1
        if gate == "security_credential_gate":
            security_gate_count += 1

    summary = ladder.get("summary") if isinstance(ladder.get("summary"), dict) else {}
    require(summary.get("total_ladder_items") == len(as_list(items)), "summary_total", "ladder total matches readiness item count", failures)
    require(summary.get("count_by_readiness_level") == dict(level_counts), "summary_level_counts", "ladder readiness level counts match items", failures)
    require(summary.get("count_by_required_gate_type") == dict(gate_counts), "summary_gate_counts", "ladder required gate counts match items", failures)
    require(summary.get("static_ready_count") == static_ready_count, "summary_static_ready", "static-ready count matches items", failures)
    require(summary.get("roadmap_only_count") == roadmap_only_count, "summary_roadmap_only", "roadmap-only count matches items", failures)
    require(summary.get("future_gate_required_count") == future_gate_count, "summary_future_gate", "future gate count matches items", failures)
    require(summary.get("rejected_forbidden_scope_count") == rejected_count, "summary_rejected", "rejected forbidden-scope count matches items", failures)
    require(summary.get("deferred_out_of_scope_count") == deferred_count, "summary_deferred", "deferred/out-of-scope count matches items", failures)
    require(summary.get("execution_governance_required_count") == execution_gate_count, "summary_execution_gate", "execution governance count matches items", failures)
    require(summary.get("network_api_gate_required_count") == network_gate_count, "summary_network_gate", "network/API gate count matches items", failures)
    require(summary.get("customer_facing_gate_required_count") == customer_gate_count, "summary_customer_gate", "customer-facing gate count matches items", failures)
    require(summary.get("security_credential_gate_required_count") == security_gate_count, "summary_security_gate", "security/credential gate count matches items", failures)

    require("# Vol.8 Future Implementation Readiness Ladder v0.1" in markdown, "ladder_markdown_title", "generated readiness ladder markdown has expected title", failures)
    require(f"Total ladder items: `{len(as_list(items))}`" in markdown, "ladder_markdown_total", "generated readiness ladder markdown includes item count", failures)

    print()
    if failures:
        print("Vol.8 future implementation readiness ladder validation failed.")
    else:
        print("Vol.8 future implementation readiness ladder validation passed.")
    print(f"Readiness items: {len(as_list(items))}")
    print(f"Static-ready items: {static_ready_count}")
    print(f"Roadmap-only items: {roadmap_only_count}")
    print(f"Future-gate-required items: {future_gate_count}")
    print(f"Rejected forbidden-scope items: {rejected_count}")
    print(f"Deferred/out-of-scope items: {deferred_count}")
    print(f"Execution governance required: {execution_gate_count}")
    print(f"Network/API gate required: {network_gate_count}")
    print(f"Customer-facing gate required: {customer_gate_count}")
    print(f"Security/credential gate required: {security_gate_count}")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
