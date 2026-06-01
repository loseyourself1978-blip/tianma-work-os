#!/usr/bin/env python3
"""Validate Vol.3 runtime JSON examples against local schemas.

This validator intentionally uses only the Python standard library. It supports
the small JSON Schema subset used by this repository: type, required,
properties, additionalProperties, enum, and items.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples" / "ldd"
SCHEMAS_DIR = REPO_ROOT / "schemas"

SCHEMA_BY_EXAMPLE = {
    "btc_buyback_trigger_rule.example.json": "trigger_execution_rule.schema.json",
    "soxl_trigger_rule.example.json": "trigger_execution_rule.schema.json",
    "zec_bot_strategy_state.example.json": "strategy_state.schema.json"
}


class ValidationError(Exception):
    pass


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


def main() -> int:
    if not EXAMPLES_DIR.exists():
        print(f"FAIL examples directory not found: {EXAMPLES_DIR}")
        return 1

    failures = 0
    checked = 0

    for example_path in sorted(EXAMPLES_DIR.glob("*.json")):
        schema_name = SCHEMA_BY_EXAMPLE.get(example_path.name)
        if not schema_name:
            print(f"SKIP {example_path.relative_to(REPO_ROOT)} no schema mapping")
            continue

        schema_path = SCHEMAS_DIR / schema_name
        try:
            example = load_json(example_path)
            schema = load_json(schema_path)
        except json.JSONDecodeError as exc:
            print(f"FAIL {example_path.relative_to(REPO_ROOT)} invalid JSON: {exc}")
            failures += 1
            continue
        except OSError as exc:
            print(f"FAIL {example_path.relative_to(REPO_ROOT)} cannot load file: {exc}")
            failures += 1
            continue

        errors = validate(example, schema)
        checked += 1

        if errors:
            print(f"FAIL {example_path.relative_to(REPO_ROOT)} against {schema_name}")
            for error in errors:
                print(f"  - {error}")
            failures += 1
        else:
            print(f"PASS {example_path.relative_to(REPO_ROOT)} against {schema_name}")

    if failures:
        print(f"\nRuntime validation failed: {failures} failure(s), {checked} checked.")
        return 1

    print(f"\nRuntime validation passed: {checked} JSON example(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
