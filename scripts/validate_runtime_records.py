#!/usr/bin/env python3
"""Validate Vol.3 runtime JSON examples and records against local schemas.

This validator intentionally uses only the Python standard library. It supports
the small JSON Schema subset used by this repository: type, required,
properties, additionalProperties, enum, and items.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIRS = [
    REPO_ROOT / "examples" / "ldd",
    REPO_ROOT / "examples" / "runtime"
]
RECORD_DIRS = [
    REPO_ROOT / "records" / "ldd"
]
SCHEMAS_DIR = REPO_ROOT / "schemas"


@dataclass(frozen=True)
class ValidationTarget:
    path: Path
    bucket: str
    schema_name: str
    schema_key: str


SCHEMA_FILES = {
    "trigger_execution_rule": "trigger_execution_rule.schema.json",
    "strategy_state": "strategy_state.schema.json",
    "portfolio_state": "portfolio_state.schema.json",
    "account_structure_review": "account_structure_review.schema.json",
    "pending_command": "pending_command.schema.json",
    "command_intelligence_check": "command_intelligence_check.schema.json",
    "smart_execution_plan": "smart_execution_plan.schema.json",
    "command_execution_feedback": "command_execution_feedback.schema.json",
    "rule_based_execution_review": "rule_based_execution_review.schema.json",
    "volatility_execution_split": "volatility_execution_split.schema.json",
    "sync_delta_update": "sync_delta_update.schema.json",
    "rule_ledger_snapshot": "rule_ledger_snapshot.schema.json",
    "execution_event": "execution_event.schema.json",
    "memory_retention_policy": "memory_retention_policy.schema.json",
    "memory_cleanup_recommendation": "memory_cleanup_recommendation.schema.json",
    "active_memory_checkpoint": "active_memory_checkpoint.schema.json"
}


def schema_for_filename(filename: str) -> tuple[str, str] | None:
    if "memory_retention_policy" in filename:
        return "memory_retention_policy", SCHEMA_FILES["memory_retention_policy"]
    if "memory_cleanup_recommendation" in filename:
        return "memory_cleanup_recommendation", SCHEMA_FILES["memory_cleanup_recommendation"]
    if "active_memory_checkpoint" in filename:
        return "active_memory_checkpoint", SCHEMA_FILES["active_memory_checkpoint"]
    if "command_intelligence_check" in filename or "superseded_check" in filename:
        return "command_intelligence_check", SCHEMA_FILES["command_intelligence_check"]
    if "smart_execution_plan" in filename:
        return "smart_execution_plan", SCHEMA_FILES["smart_execution_plan"]
    if "execution_feedback" in filename:
        return "command_execution_feedback", SCHEMA_FILES["command_execution_feedback"]
    if "rule_based_execution_review" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "volatility_execution_split" in filename:
        return "volatility_execution_split", SCHEMA_FILES["volatility_execution_split"]
    if "sync_block_delta" in filename or "sync_delta" in filename or "delta_protocol" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "rule_ledger_snapshot" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "closure_execution" in filename:
        return "execution_event", SCHEMA_FILES["execution_event"]
    if "trigger_rule" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "trigger_execution" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "strategy_state" in filename:
        return "strategy_state", SCHEMA_FILES["strategy_state"]
    if "portfolio_state" in filename:
        return "portfolio_state", SCHEMA_FILES["portfolio_state"]
    if "account_structure_review" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "account_structure_score" in filename or "account_structure_update" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if filename.startswith("pending_") or "pending_command" in filename:
        return "pending_command", SCHEMA_FILES["pending_command"]
    return None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
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
                errors.extend(validate(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(validate(item, item_schema, f"{path}[{index}]"))

    return errors


def collect_targets() -> tuple[list[ValidationTarget], list[Path]]:
    targets: list[ValidationTarget] = []
    unmapped: list[Path] = []

    roots = [(root, "examples") for root in EXAMPLE_DIRS]
    roots.extend((root, "records") for root in RECORD_DIRS)

    for root, bucket in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            schema_match = schema_for_filename(path.name)
            if schema_match is None:
                unmapped.append(path)
                continue
            schema_key, schema_name = schema_match
            targets.append(ValidationTarget(path, bucket, schema_name, schema_key))

    return targets, unmapped


def main() -> int:
    targets, unmapped = collect_targets()
    failures = 0
    examples_checked = 0
    records_checked = 0
    coverage: Counter[str] = Counter()

    if unmapped:
        for path in unmapped:
            print(f"FAIL {path.relative_to(REPO_ROOT)} has no schema mapping")
        failures += len(unmapped)

    for target in targets:
        schema_path = SCHEMAS_DIR / target.schema_name
        try:
            document = load_json(target.path)
            schema = load_json(schema_path)
        except json.JSONDecodeError as exc:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} invalid JSON: {exc}")
            failures += 1
            continue
        except OSError as exc:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} cannot load file: {exc}")
            failures += 1
            continue

        errors = validate(document, schema)
        coverage[target.schema_key] += 1

        if target.bucket == "examples":
            examples_checked += 1
        elif target.bucket == "records":
            records_checked += 1

        if errors:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} against {target.schema_name}")
            for error in errors:
                print(f"  - {error}")
            failures += 1
        else:
            print(f"PASS {target.path.relative_to(REPO_ROOT)} against {target.schema_name}")

    total_checked = examples_checked + records_checked

    print()
    if failures:
        print("Runtime validation failed.")
    else:
        print("Runtime validation passed.")

    print(f"Examples checked: {examples_checked}")
    print(f"Records checked: {records_checked}")
    print(f"Total JSON files checked: {total_checked}")
    print("Schema coverage:")
    for schema_key in sorted(SCHEMA_FILES):
        print(f"- {schema_key}: {coverage.get(schema_key, 0)}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
