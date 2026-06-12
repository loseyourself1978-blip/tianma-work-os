#!/usr/bin/env python3
"""Validate the Vol.6 cockpit static spec integration contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "mock_consumers" / "ldd"
SCHEMA_DIR = REPO_ROOT / "schemas"

INTEGRATION_MATRIX_PATH = MOCK_DIR / "cockpit_static_spec_integration_matrix.json"
CONSISTENCY_CHECKS_PATH = MOCK_DIR / "cockpit_static_spec_consistency_checks.json"
SURFACE_ROLE_MATRIX_PATH = MOCK_DIR / "cockpit_static_spec_surface_role_matrix.json"
CARD_TRACEABILITY_MATRIX_PATH = MOCK_DIR / "cockpit_static_spec_card_traceability_matrix.json"
BLOCKED_ACTION_CROSSCHECK_PATH = MOCK_DIR / "cockpit_static_spec_blocked_action_crosscheck.json"
READINESS_GATE_PATH = MOCK_DIR / "cockpit_static_spec_readiness_gate.json"

REQUIRED_FILES = [
    INTEGRATION_MATRIX_PATH,
    CONSISTENCY_CHECKS_PATH,
    SURFACE_ROLE_MATRIX_PATH,
    CARD_TRACEABILITY_MATRIX_PATH,
    BLOCKED_ACTION_CROSSCHECK_PATH,
    READINESS_GATE_PATH,
]

REQUIRED_SCHEMA = SCHEMA_DIR / "cockpit_static_spec_integration_review.schema.json"

EXPECTED_CHECKPOINT = "2026-06-12T09:18:00+08:00"
EXPECTED_OPERATING_MODE = "cash_defense_core_position_survival_mode"
EXPECTED_PORTFOLIO_MODE = "residual_core_position_mode"
EXPECTED_NEXT_PHASE = "Vol.6 Phase 6.8 - Static Consumer Fixture Integration and Handoff"

REQUIRED_INTEGRATED_SPECS = {
    "ui_boundary_architecture",
    "permission_privacy_masking_model",
    "read_only_api_contract",
    "static_cockpit_prototype_boundary",
    "internal_operator_cockpit_static_spec",
    "ai_board_cockpit_static_spec",
    "residual_core_checkpoint_update",
}

REQUIRED_CHECKS = {
    "active_checkpoint_consistency",
    "operating_mode_consistency",
    "portfolio_mode_consistency",
    "customer_facing_ready_consistency",
    "read_only_contract_consistency",
    "permission_masking_consistency",
    "blocked_action_consistency",
    "source_traceability_consistency",
    "warning_data_quality_consistency",
    "evidence_priority_consistency",
    "role_surface_consistency",
    "card_field_consistency",
    "residual_core_position_consistency",
    "active_rules_consistency",
    "no_implementation_boundary_consistency",
}

REQUIRED_SURFACES = {
    "internal_operator_cockpit_static",
    "ai_board_review_static",
    "audit_debug_static",
    "public_demo_static_blocked",
    "customer_facing_static_blocked",
}

REQUIRED_ROLES = {
    "system_admin",
    "internal_operator",
    "ai_board_reviewer",
    "audit_reviewer",
    "demo_viewer",
    "customer_facing_viewer_blocked",
    "market_analyst",
    "risk_officer",
    "data_verifier",
    "strategist_meta_strategist",
    "review_officer",
    "final_commander",
}

AI_BOARD_ROLES = {
    "market_analyst",
    "risk_officer",
    "data_verifier",
    "strategist_meta_strategist",
    "review_officer",
    "final_commander",
}

REQUIRED_TRACE_CATEGORIES = {
    "account_snapshot",
    "cash_defense_ratio",
    "active_positions",
    "closed_positions",
    "execution_ledger",
    "active_rules",
    "strategy_states",
    "warnings_data_quality",
    "source_traceability",
    "checkpoint_status",
    "non_promoted_evidence",
    "customer_facing_blocked_status",
    "ai_board_role_outputs",
    "ai_board_disagreements",
    "ai_board_arbitration",
    "ai_board_decision_trace",
}

SOURCE_TRACE_REQUIRED_CATEGORIES = {
    "source_traceability",
    "execution_ledger",
    "ai_board_decision_trace",
    "non_promoted_evidence",
}

REQUIRED_BLOCKED_ACTIONS = {
    "place_order",
    "cancel_order",
    "modify_order",
    "execute_trade",
    "start_bot",
    "stop_bot",
    "reopen_grid",
    "connect_broker_api",
    "connect_binance_api",
    "connect_external_market_api",
    "fetch_live_market_data",
    "refresh_live_price",
    "mutate_runtime_record",
    "promote_checkpoint_from_ui",
    "suppress_warning",
    "hide_data_quality_flag",
    "reveal_sensitive_value",
    "reveal_never_expose_field",
    "enable_customer_facing_view",
    "export_sensitive_customer_data",
    "convert_recommendation_to_execution",
    "hide_ai_board_disagreement",
    "override_final_commander_without_trace",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_7_COCKPIT_STATIC_SPEC_INTEGRATION_REVIEW_v0.1.md",
    "schemas/cockpit_static_spec_integration_review.schema.json",
    "mock_consumers/ldd/cockpit_static_spec_integration_matrix.json",
    "mock_consumers/ldd/cockpit_static_spec_consistency_checks.json",
    "mock_consumers/ldd/cockpit_static_spec_surface_role_matrix.json",
    "mock_consumers/ldd/cockpit_static_spec_card_traceability_matrix.json",
    "mock_consumers/ldd/cockpit_static_spec_blocked_action_crosscheck.json",
    "mock_consumers/ldd/cockpit_static_spec_readiness_gate.json",
    "scripts/validate_cockpit_static_spec_integration.py",
    "scripts/validate_cockpit_static_spec_integration.sh",
    "records/ldd/2026-06-12/vol6_phase6_7_cockpit_static_spec_integration_review_0918_sgt.json",
    "reports/ldd/vol6_phase6_7_cockpit_static_spec_integration_review.md",
]

FORBIDDEN_IMPLEMENTATION_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}

FORBIDDEN_IMPLEMENTATION_PATH_PARTS = {
    "app",
    "web",
    "frontend",
    "ui",
    "components",
    "pages",
    "routes",
    "server",
    "api",
    "src",
    "public",
}

FORBIDDEN_FILENAMES = {
    "package.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.ts",
    "svelte.config.js",
}

FORBIDDEN_PYTHON_IMPORTS = {
    "aiohttp",
    "bottle",
    "django",
    "fastapi",
    "flask",
    "http.server",
    "requests",
    "socket",
    "starlette",
    "tornado",
    "uvicorn",
}


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative(path)} must contain a JSON object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Results:
    def __init__(self) -> None:
        self.checked = 0
        self.passes: list[str] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, condition: bool, detail: str) -> None:
        self.checked += 1
        target = self.passes if condition else self.failures
        target.append(f"{name}: {detail}")


def by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get(key)): item for item in items if isinstance(item, dict)}


def implementation_problems() -> list[str]:
    problems: list[str] = []
    for artifact in PHASE_ARTIFACTS:
        path = REPO_ROOT / artifact
        if not path.exists():
            problems.append(f"missing phase artifact: {artifact}")
            continue
        parts = set(path.relative_to(REPO_ROOT).parts)
        if path.suffix in FORBIDDEN_IMPLEMENTATION_SUFFIXES:
            problems.append(f"forbidden implementation suffix: {artifact}")
        if parts & FORBIDDEN_IMPLEMENTATION_PATH_PARTS:
            problems.append(f"forbidden implementation path segment: {artifact}")
        if path.name in FORBIDDEN_FILENAMES:
            problems.append(f"forbidden implementation filename: {artifact}")
        if path.suffix == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                problems.append(f"python parse failed for {artifact}: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in FORBIDDEN_PYTHON_IMPORTS:
                            problems.append(f"forbidden python import {alias.name} in {artifact}")
                if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_PYTHON_IMPORTS:
                    problems.append(f"forbidden python import {node.module} in {artifact}")
    return problems


def main() -> int:
    results = Results()

    missing = [relative(path) for path in REQUIRED_FILES if not path.exists()]
    results.check("required_files", not missing, f"{len(REQUIRED_FILES) - len(missing)}/{len(REQUIRED_FILES)} required integration files exist")
    if missing:
        for item in missing:
            results.failures.append(f"missing required file: {item}")
        return finish(results)

    before_hashes = {path: digest(path) for path in REQUIRED_FILES}

    loaded: dict[Path, dict[str, Any]] = {}
    json_errors: list[str] = []
    for path in REQUIRED_FILES:
        try:
            loaded[path] = load_json(path)
        except (json.JSONDecodeError, ValueError) as exc:
            json_errors.append(f"{relative(path)}: {exc}")
    results.check("json_syntax", not json_errors, "all cockpit static spec integration JSON contracts are valid")
    for error in json_errors:
        results.failures.append(f"json_syntax: {error}")

    results.check("required_schema", REQUIRED_SCHEMA.exists(), "cockpit static spec integration review schema exists")

    integration = loaded.get(INTEGRATION_MATRIX_PATH, {})
    checks = by_id(loaded.get(CONSISTENCY_CHECKS_PATH, {}).get("checks", []), "check_id")
    surface_entries = loaded.get(SURFACE_ROLE_MATRIX_PATH, {}).get("entries", [])
    trace_categories = by_id(loaded.get(CARD_TRACEABILITY_MATRIX_PATH, {}).get("trace_categories", []), "trace_category_id")
    blocked_actions = by_id(loaded.get(BLOCKED_ACTION_CROSSCHECK_PATH, {}).get("blocked_actions", []), "action_id")
    readiness = loaded.get(READINESS_GATE_PATH, {})
    specs = by_id(integration.get("integrated_specs", []), "spec_id")

    results.check("integrated_specs_present", REQUIRED_INTEGRATED_SPECS <= set(specs), f"required integrated specs present: {len(REQUIRED_INTEGRATED_SPECS & set(specs))}/{len(REQUIRED_INTEGRATED_SPECS)}")
    results.check("integrated_specs_read_only", all(spec.get("must_remain_read_only") is True for spec in specs.values()), "every integrated spec is read-only")
    results.check("integrated_specs_customer_blocked", all(spec.get("customer_facing_allowed") is False for spec in specs.values()), "every integrated spec has customer_facing_allowed false")
    results.check("integrated_specs_no_mutation", all(spec.get("mutation_allowed") is False for spec in specs.values()), "every integrated spec has mutation_allowed false")
    results.check("integrated_specs_no_execution", all(spec.get("execution_allowed") is False for spec in specs.values()), "every integrated spec has execution_allowed false")

    check_ids = set(checks)
    results.check("required_consistency_checks", REQUIRED_CHECKS <= check_ids, f"required checks present: {len(REQUIRED_CHECKS & check_ids)}/{len(REQUIRED_CHECKS)}")
    results.check("checks_blocking", all(check.get("blocking") is True for check in checks.values()), "all consistency checks are blocking")
    results.check("checkpoint_consistency", checks.get("active_checkpoint_consistency", {}).get("expected_result") == EXPECTED_CHECKPOINT and integration.get("active_checkpoint") == EXPECTED_CHECKPOINT, f"active checkpoint is {EXPECTED_CHECKPOINT}")
    results.check("operating_mode_consistency", checks.get("operating_mode_consistency", {}).get("expected_result") == EXPECTED_OPERATING_MODE and integration.get("operating_mode") == EXPECTED_OPERATING_MODE, f"operating mode is {EXPECTED_OPERATING_MODE}")
    results.check("portfolio_mode_consistency", checks.get("portfolio_mode_consistency", {}).get("expected_result") == EXPECTED_PORTFOLIO_MODE and integration.get("portfolio_mode") == EXPECTED_PORTFOLIO_MODE, f"portfolio mode is {EXPECTED_PORTFOLIO_MODE}")
    results.check("customer_facing_false", integration.get("customer_facing_ready") is False and readiness.get("customer_facing_ready") is False, "customer-facing readiness is false across integration artifacts")

    surfaces = {str(entry.get("surface_id")) for entry in surface_entries}
    roles = {str(entry.get("role_id")) for entry in surface_entries}
    results.check("required_surfaces", REQUIRED_SURFACES <= surfaces, f"required surfaces present: {len(REQUIRED_SURFACES & surfaces)}/{len(REQUIRED_SURFACES)}")
    results.check("required_roles", REQUIRED_ROLES <= roles, f"required roles present: {len(REQUIRED_ROLES & roles)}/{len(REQUIRED_ROLES)}")
    all_entries_safe = all(entry.get("mutation_allowed") is False and entry.get("execution_allowed") is False and entry.get("customer_facing_allowed") is False for entry in surface_entries)
    results.check("surface_entries_no_mutation_execution_customer", all_entries_safe, "all surface-role entries deny mutation, execution, and customer-facing access")
    customer_entries = [entry for entry in surface_entries if entry.get("role_id") == "customer_facing_viewer_blocked"]
    results.check("customer_role_blocked", customer_entries and all(entry.get("access_allowed") is False for entry in customer_entries), "customer_facing_viewer_blocked has no cockpit access")
    internal_entry = [entry for entry in surface_entries if entry.get("surface_id") == "internal_operator_cockpit_static" and entry.get("role_id") == "internal_operator"]
    results.check("internal_operator_read_only", bool(internal_entry) and internal_entry[0].get("access_allowed") is True and internal_entry[0].get("read_only") is True, "internal_operator access is read-only")
    ai_board_bad = [entry for entry in surface_entries if entry.get("role_id") in AI_BOARD_ROLES and entry.get("access_allowed") is True and entry.get("surface_id") != "ai_board_review_static"]
    ai_board_good = [entry for entry in surface_entries if entry.get("role_id") in AI_BOARD_ROLES and entry.get("surface_id") == "ai_board_review_static" and entry.get("access_allowed") is True and entry.get("read_only") is True]
    results.check("ai_board_roles_read_only", not ai_board_bad and len(ai_board_good) == len(AI_BOARD_ROLES), "AI Board roles access only ai_board_review_static as read-only")

    trace_ids = set(trace_categories)
    results.check("required_trace_categories", REQUIRED_TRACE_CATEGORIES <= trace_ids, f"required trace categories present: {len(REQUIRED_TRACE_CATEGORIES & trace_ids)}/{len(REQUIRED_TRACE_CATEGORIES)}")
    no_never_expose = all("never_expose" not in category.get("field_classes_used", []) for category in trace_categories.values())
    results.check("trace_no_never_expose", no_never_expose, "no trace category uses never_expose field class")
    trace_safe = all(category.get("mutation_allowed") is False and category.get("execution_allowed") is False and category.get("customer_facing_allowed") is False for category in trace_categories.values())
    results.check("trace_no_mutation_execution_customer", trace_safe, "all trace categories deny mutation, execution, and customer-facing access")
    source_trace_ok = all(trace_categories.get(category_id, {}).get("source_traceability_visible") is True for category_id in SOURCE_TRACE_REQUIRED_CATEGORIES)
    results.check("source_traceability_required_categories", source_trace_ok, "source traceability is visible for source, execution ledger, decision trace, and non-promoted evidence")

    blocked_ids = set(blocked_actions)
    results.check("required_blocked_actions", REQUIRED_BLOCKED_ACTIONS <= blocked_ids, f"required blocked actions present: {len(REQUIRED_BLOCKED_ACTIONS & blocked_ids)}/{len(REQUIRED_BLOCKED_ACTIONS)}")
    results.check("blocked_across_all_specs", all(action.get("blocked_across_all_specs") is True for action in blocked_actions.values()), "every blocked action is blocked across all specs")
    results.check("blocked_actions_no_roles", all(action.get("allowed_roles") == [] for action in blocked_actions.values()), "every blocked action has allowed_roles []")
    blocked_safe = all(action.get("mutation_allowed") is False and action.get("execution_allowed") is False and action.get("customer_facing_allowed") is False for action in blocked_actions.values())
    results.check("blocked_actions_no_mutation_execution_customer", blocked_safe, "blocked actions deny mutation, execution, and customer-facing access")

    results.check("readiness_internal_ready", readiness.get("internal_static_spec_ready") is True, "readiness gate marks internal_static_spec_ready true")
    results.check("readiness_ai_board_ready", readiness.get("ai_board_static_spec_ready") is True, "readiness gate marks ai_board_static_spec_ready true")
    results.check("readiness_customer_false", readiness.get("customer_facing_ready") is False, "readiness gate marks customer_facing_ready false")
    results.check("readiness_ui_false", readiness.get("actual_ui_ready") is False, "readiness gate marks actual_ui_ready false")
    results.check("readiness_api_false", readiness.get("api_server_ready") is False, "readiness gate marks api_server_ready false")
    results.check("readiness_trading_false", readiness.get("trading_automation_ready") is False, "readiness gate marks trading_automation_ready false")
    results.check("readiness_next_phase", readiness.get("next_phase") == EXPECTED_NEXT_PHASE and readiness.get("next_phase_allowed") is True, f"next phase is {EXPECTED_NEXT_PHASE}")

    problems = implementation_problems()
    results.check("no_implementation_files", not problems, "no frontend, API, live endpoint, connector, trading executor, credential store, runtime mutation UI, or automation trigger artifacts found")
    for problem in problems:
        results.failures.append(f"no_implementation_files: {problem}")

    after_hashes = {path: digest(path) for path in REQUIRED_FILES}
    results.check("read_only_integrity", before_hashes == after_hashes, "validator did not modify cockpit static spec integration files")

    return finish(results)


def finish(results: Results) -> int:
    for item in results.passes:
        name, detail = item.split(": ", 1)
        print(f"PASS {name}: {detail}")
    for item in results.warnings:
        print(f"WARNING {item}")
    for item in results.failures:
        name, detail = item.split(": ", 1) if ": " in item else ("failure", item)
        print(f"FAIL {name}: {detail}")

    if results.failures:
        print("\nCockpit static spec integration validation failed.")
        print(f"Checks: {results.checked}")
        print(f"Blocking failures: {len(results.failures)}")
        print(f"Warnings: {len(results.warnings)}")
        return 1

    print("\nCockpit static spec integration validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Contract files checked: {len(REQUIRED_FILES)}")
    print("Blocking failures: 0")
    print(f"Warnings: {len(results.warnings)}")
    print(f"Active checkpoint: {EXPECTED_CHECKPOINT}")
    print(f"Operating mode: {EXPECTED_OPERATING_MODE}")
    print(f"Portfolio mode: {EXPECTED_PORTFOLIO_MODE}")
    print("Actual UI created: false")
    print("Frontend app created: false")
    print("HTML/CSS/JS UI created: false")
    print("API server created: false")
    print("Live endpoint created: false")
    print("Customer-facing ready: false")
    print("Trading automation enabled: false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
