#!/usr/bin/env python3
"""Validate Vol.8 Phase 8.1 static shell QA handoff intake artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.8 Phase 8.1 - Static Shell QA Handoff Intake and Boundary Freeze"
BASELINE_COMMIT = "47d9a7d542cd4df96188f100d61d31a206417e5c"
STATIC_SHELL_PATH = "static_shell/ldd/"
EXPECTED_RUNTIME_RECORDS = 108
EXPECTED_TIMELINE_EVENTS = 108
EXPECTED_TIMELINE_WARNINGS = 0

REQUIRED_FILES = {
    "phase_doc": "docs/runtime/VOL8_PHASE8_1_STATIC_SHELL_QA_HANDOFF_INTAKE_AND_BOUNDARY_FREEZE_v0.1.md",
    "checklist": "docs/runtime/VOL8_STATIC_SHELL_QA_HANDOFF_CHECKLIST_v0.1.md",
    "handoff_schema": "schemas/vol8_static_shell_qa_handoff_intake.schema.json",
    "boundary_schema": "schemas/vol8_boundary_freeze.schema.json",
    "handoff_fixture": "mock_consumers/ldd/vol8_static_shell_qa_handoff_intake.json",
    "boundary_fixture": "mock_consumers/ldd/vol8_boundary_freeze.json",
    "record": "records/ldd/2026-06-16/vol8_phase8_1_static_shell_qa_handoff_intake_and_boundary_freeze.json",
    "validator": "scripts/validate_vol8_phase8_1_static_shell_qa_handoff.py",
    "wrapper": "scripts/validate_vol8_phase8_1_static_shell_qa_handoff.sh"
}

ALLOWED_REVIEW_CATEGORIES = [
    "information architecture",
    "visual hierarchy",
    "fixture readability",
    "missing context",
    "role clarity",
    "boundary clarity",
    "confusing states",
    "terminology drift",
    "operator trust risks"
]

FEEDBACK_INTAKE_CATEGORIES = [
    "blocking clarity issue",
    "non-blocking UX improvement",
    "documentation refinement",
    "future product candidate",
    "forbidden-scope request",
    "out-of-scope live/runtime request"
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
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def read_text(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


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


def contains_all(values: Any, expected: list[str]) -> bool:
    if not isinstance(values, list):
        return False
    actual = {str(value) for value in values}
    return all(item in actual for item in expected)


def baseline_valid(document: dict[str, Any]) -> bool:
    return (
        document.get("phase") == PHASE
        and document.get("baseline_commit") == BASELINE_COMMIT
        and document.get("runtime_records") == EXPECTED_RUNTIME_RECORDS
        and document.get("timeline_events") == EXPECTED_TIMELINE_EVENTS
        and document.get("timeline_warnings") == EXPECTED_TIMELINE_WARNINGS
        and document.get("static_shell_path") == STATIC_SHELL_PATH
    )


def static_flags_valid(document: dict[str, Any]) -> bool:
    return (
        document.get("fixture_only") is True
        and document.get("read_only") is True
        and document.get("network_allowed") is False
        and document.get("execution_allowed") is False
        and document.get("customer_facing_readiness") is False
    )


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES.values() if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 8.1 docs, schemas, fixtures, record, and validators exist", failures)
    if missing:
        for path in missing:
            print(f"Missing: {path}")
        return 1

    handoff_schema = load_json(REQUIRED_FILES["handoff_schema"])
    boundary_schema = load_json(REQUIRED_FILES["boundary_schema"])
    handoff = load_json(REQUIRED_FILES["handoff_fixture"])
    boundary = load_json(REQUIRED_FILES["boundary_fixture"])
    record = load_json(REQUIRED_FILES["record"])
    phase_doc = read_text(REQUIRED_FILES["phase_doc"])
    checklist = read_text(REQUIRED_FILES["checklist"])

    handoff_errors = validate_schema_subset(handoff, handoff_schema)
    boundary_errors = validate_schema_subset(boundary, boundary_schema)
    require(not handoff_errors, "handoff_schema_validation", "QA handoff intake fixture validates against schema", failures)
    for error in handoff_errors:
        print(f"  - {error}")
    require(not boundary_errors, "boundary_schema_validation", "boundary freeze fixture validates against schema", failures)
    for error in boundary_errors:
        print(f"  - {error}")

    require(baseline_valid(handoff), "handoff_baseline", "handoff fixture preserves baseline commit and 108/108/0 counts", failures)
    require(baseline_valid(record), "record_baseline", "runtime record preserves required baseline commit and 108/108/0 counts", failures)
    require(static_flags_valid(handoff), "handoff_static_flags", "handoff fixture remains fixture-only/read-only/no-network/no-execution/not-customer-facing", failures)
    require(static_flags_valid(record), "record_static_flags", "runtime record remains fixture-only/read-only/no-network/no-execution/not-customer-facing", failures)

    require(boundary.get("phase") == PHASE, "boundary_phase", "boundary fixture uses Phase 8.1 label", failures)
    require(boundary.get("boundary_status") == "frozen_for_phase_8_1", "boundary_status", "boundary status is frozen_for_phase_8_1", failures)
    require(boundary.get("implementation_readiness") == "not_ready_for_implementation", "implementation_readiness", "implementation readiness remains not_ready_for_implementation", failures)
    require(boundary.get("customer_facing_readiness") is False, "boundary_customer_readiness", "boundary customer-facing readiness remains false", failures)
    require(boundary.get("requires_future_gate_before_implementation") is True, "future_gate_required", "future gate is required before implementation", failures)

    require(handoff.get("qa_review_status") == "ready_for_local_static_review", "qa_review_status", "handoff fixture is ready_for_local_static_review", failures)
    require(contains_all(handoff.get("allowed_review_categories"), ALLOWED_REVIEW_CATEGORIES), "allowed_review_categories", "all allowed QA review categories are present", failures)
    require(contains_all(handoff.get("feedback_intake_categories"), FEEDBACK_INTAKE_CATEGORIES), "feedback_categories", "all feedback intake categories are present", failures)
    require(contains_all(handoff.get("forbidden_scope_confirmed_absent"), FORBIDDEN_SCOPE), "handoff_forbidden_scope_absent", "handoff fixture confirms all forbidden scope absent", failures)
    require(contains_all(boundary.get("forbidden_scope"), FORBIDDEN_SCOPE), "boundary_forbidden_scope", "boundary fixture lists all forbidden scope", failures)

    record_non_goals = record.get("explicit_non_goals_confirmed", {})
    require(isinstance(record_non_goals, dict) and record_non_goals and all(value is False for value in record_non_goals.values()), "record_non_goals", "runtime record confirms forbidden non-goals as false", failures)
    require(record.get("boundary_status") == "frozen_for_phase_8_1", "record_boundary_status", "runtime record carries frozen boundary status", failures)
    require(record.get("implementation_readiness") == "not_ready_for_implementation", "record_implementation_readiness", "runtime record carries not-ready implementation status", failures)
    require(record.get("requires_future_gate_before_implementation") is True, "record_future_gate", "runtime record requires a future gate before implementation", failures)

    doc_text = f"{phase_doc}\n{checklist}"
    for phrase in [
        "QA handoff may generate observations only",
        "QA handoff may not change runtime state",
        "QA handoff may not imply implementation approval",
        "Any future implementation must pass a new readiness gate",
        "LDD scope is the entire U.S. equity market, not only existing or former positions."
    ]:
        require(phrase in doc_text, f"doc_phrase_{phrase[:18].lower().replace(' ', '_')}", f"documentation includes: {phrase}", failures)

    print()
    if failures:
        print("Vol.8 Phase 8.1 static shell QA handoff validation failed.")
    else:
        print("Vol.8 Phase 8.1 static shell QA handoff validation passed.")
    print(f"Checks: {20 + 5}")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Phase: {PHASE}")
    print(f"Baseline commit: {BASELINE_COMMIT}")
    print("Baseline counts: runtime_records=108, timeline_events=108, timeline_warnings=0")
    print("Static shell boundary: local/static/read-only/fixture-only/no-network/no-execution")
    print("Customer-facing readiness: false")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
