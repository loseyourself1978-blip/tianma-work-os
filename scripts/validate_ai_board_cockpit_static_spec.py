#!/usr/bin/env python3
"""Validate the Vol.6 AI Board cockpit static spec contracts."""

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

SPEC_PATH = MOCK_DIR / "ai_board_cockpit_static_spec.json"
ROLE_TAXONOMY_PATH = MOCK_DIR / "ai_board_role_taxonomy.json"
ROLE_PANEL_MAP_PATH = MOCK_DIR / "ai_board_role_panel_map.json"
EVIDENCE_POLICY_PATH = MOCK_DIR / "ai_board_evidence_policy.json"
DISAGREEMENT_POLICY_PATH = MOCK_DIR / "ai_board_disagreement_policy.json"
ARBITRATION_POLICY_PATH = MOCK_DIR / "ai_board_arbitration_policy.json"
DECISION_TRACE_POLICY_PATH = MOCK_DIR / "ai_board_decision_trace_policy.json"
BLOCKED_ACTION_PATH = MOCK_DIR / "ai_board_blocked_action_policy.json"

REQUIRED_FILES = [
    SPEC_PATH,
    ROLE_TAXONOMY_PATH,
    ROLE_PANEL_MAP_PATH,
    EVIDENCE_POLICY_PATH,
    DISAGREEMENT_POLICY_PATH,
    ARBITRATION_POLICY_PATH,
    DECISION_TRACE_POLICY_PATH,
    BLOCKED_ACTION_PATH,
]

REQUIRED_SCHEMAS = [
    SCHEMA_DIR / "ai_board_cockpit_static_spec.schema.json",
    SCHEMA_DIR / "ai_board_cockpit_static_spec_review.schema.json",
]

EXPECTED_CHECKPOINT = "2026-06-12T09:18:00+08:00"
EXPECTED_OPERATING_MODE = "cash_defense_core_position_survival_mode"
EXPECTED_PORTFOLIO_MODE = "residual_core_position_mode"

REQUIRED_ROLES = {
    "market_analyst",
    "risk_officer",
    "data_verifier",
    "strategist_meta_strategist",
    "review_officer",
    "final_commander",
}

REQUIRED_PANELS = {
    "market_analyst_panel",
    "risk_officer_panel",
    "data_verifier_panel",
    "strategist_meta_strategist_panel",
    "review_officer_panel",
    "final_commander_panel",
    "board_disagreement_summary_panel",
    "final_decision_trace_panel",
}

REQUIRED_EVIDENCE = {
    "user_longbridge_broker_screenshots",
    "user_order_detail_screenshots",
    "user_binance_spot_screenshots",
    "ldd_review_sync_block",
    "active_checkpoint_record",
    "cockpit_view_model",
    "read_only_api_contract",
    "permission_privacy_masking_contract",
    "internal_operator_cockpit_static_spec",
    "external_market_data_for_validation_only",
}

SOURCE_OF_TRUTH_EVIDENCE = {
    "user_longbridge_broker_screenshots",
    "user_order_detail_screenshots",
    "user_binance_spot_screenshots",
}

REQUIRED_DISAGREEMENTS = {
    "market_rebound_vs_no_reentry",
    "rule_compliance_vs_opportunity_cost",
    "cash_defense_vs_redeployment",
    "core_position_hold_vs_reduce",
    "data_missing_vs_resolved",
    "external_validation_vs_broker_sot",
    "short_term_price_quality_vs_account_structure_improvement",
}

REQUIRED_ARBITRATION_RULES = {
    "final_commander_arbitrates_disagreement",
    "source_of_truth_overrides_external_validation",
    "rule_compliance_separated_from_opportunity_cost",
    "account_structure_improvement_can_override_short_term_regret",
    "no_reentry_requires_new_approved_rule",
    "execution_requires_user_manual_action_outside_system",
    "customer_facing_output_remains_blocked",
    "runtime_mutation_ui_remains_blocked",
}

REQUIRED_TRACE_ITEMS = {
    "source_priority_trace",
    "account_state_trace",
    "execution_ledger_trace",
    "active_rule_trace",
    "role_output_trace",
    "disagreement_trace",
    "arbitration_trace",
    "final_commander_trace",
    "blocked_action_trace",
    "customer_facing_blocked_trace",
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
    "override_final_commander_without_trace",
    "hide_ai_board_disagreement",
    "convert_recommendation_to_execution",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_6_AI_BOARD_COCKPIT_STATIC_SPEC_v0.1.md",
    "schemas/ai_board_cockpit_static_spec.schema.json",
    "schemas/ai_board_cockpit_static_spec_review.schema.json",
    "mock_consumers/ldd/ai_board_cockpit_static_spec.json",
    "mock_consumers/ldd/ai_board_role_taxonomy.json",
    "mock_consumers/ldd/ai_board_role_panel_map.json",
    "mock_consumers/ldd/ai_board_evidence_policy.json",
    "mock_consumers/ldd/ai_board_disagreement_policy.json",
    "mock_consumers/ldd/ai_board_arbitration_policy.json",
    "mock_consumers/ldd/ai_board_decision_trace_policy.json",
    "mock_consumers/ldd/ai_board_blocked_action_policy.json",
    "scripts/validate_ai_board_cockpit_static_spec.py",
    "scripts/validate_ai_board_cockpit_static_spec.sh",
    "records/ldd/2026-06-12/vol6_phase6_6_ai_board_cockpit_static_spec_review_0918_sgt.json",
    "reports/ldd/vol6_phase6_6_ai_board_cockpit_static_spec.md",
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


def by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get(key)): item for item in items if isinstance(item, dict)}


def main() -> int:
    results = Results()

    missing = [relative(path) for path in REQUIRED_FILES if not path.exists()]
    results.check("required_files", not missing, f"{len(REQUIRED_FILES) - len(missing)}/{len(REQUIRED_FILES)} required contract files exist")
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
    results.check("json_syntax", not json_errors, "all AI Board static spec JSON contracts are valid")
    for error in json_errors:
        results.failures.append(f"json_syntax: {error}")

    missing_schemas = [relative(path) for path in REQUIRED_SCHEMAS if not path.exists()]
    results.check("required_schemas", not missing_schemas, f"{len(REQUIRED_SCHEMAS) - len(missing_schemas)}/{len(REQUIRED_SCHEMAS)} required schemas exist")

    spec = loaded.get(SPEC_PATH, {})
    roles = by_id(loaded.get(ROLE_TAXONOMY_PATH, {}).get("roles", []), "role_id")
    panels = by_id(loaded.get(ROLE_PANEL_MAP_PATH, {}).get("panels", []), "panel_id")
    evidence = by_id(loaded.get(EVIDENCE_POLICY_PATH, {}).get("evidence_sources", []), "evidence_id")
    disagreements = by_id(loaded.get(DISAGREEMENT_POLICY_PATH, {}).get("disagreement_types", []), "disagreement_id")
    arbitration = by_id(loaded.get(ARBITRATION_POLICY_PATH, {}).get("arbitration_rules", []), "rule_id")
    trace_items = by_id(loaded.get(DECISION_TRACE_POLICY_PATH, {}).get("trace_items", []), "trace_id")
    blocked_actions = by_id(loaded.get(BLOCKED_ACTION_PATH, {}).get("blocked_actions", []), "action_id")

    results.check("spec_actual_ui_false", spec.get("actual_ui_created") is False, "ai_board_cockpit_static_spec actual_ui_created is false")
    results.check("spec_customer_facing_false", spec.get("customer_facing_ready") is False, "ai_board_cockpit_static_spec customer_facing_ready is false")
    results.check("spec_checkpoint", spec.get("source_checkpoint") == EXPECTED_CHECKPOINT, f"spec source checkpoint is {EXPECTED_CHECKPOINT}")
    results.check("spec_operating_mode", spec.get("operating_mode") == EXPECTED_OPERATING_MODE, f"operating mode is {EXPECTED_OPERATING_MODE}")
    results.check("spec_portfolio_mode", spec.get("portfolio_mode") == EXPECTED_PORTFOLIO_MODE, f"portfolio mode is {EXPECTED_PORTFOLIO_MODE}")

    role_ids = set(roles)
    results.check("required_roles", REQUIRED_ROLES <= role_ids, f"required roles present: {len(REQUIRED_ROLES & role_ids)}/{len(REQUIRED_ROLES)}")
    results.check("role_static_spec_only", all(role.get("implementation_status") == "static_spec_only" for role in roles.values()), "all roles are static_spec_only")
    results.check("role_no_execution", all(role.get("can_trigger_execution") is False for role in roles.values()), "all roles have can_trigger_execution false")
    results.check("role_no_mutation", all(role.get("can_mutate_runtime") is False for role in roles.values()), "all roles have can_mutate_runtime false")
    final_commander = roles.get("final_commander", {})
    non_final_arbiters = [role_id for role_id, role in roles.items() if role_id != "final_commander" and role.get("can_arbitrate") is not False]
    results.check("final_commander_arbitrates", final_commander.get("can_arbitrate") is True and not non_final_arbiters, "Final Commander is the only arbitrating role")

    panel_ids = set(panels)
    results.check("required_panels", REQUIRED_PANELS <= panel_ids, f"required panels present: {len(REQUIRED_PANELS & panel_ids)}/{len(REQUIRED_PANELS)}")
    results.check("panel_static_spec_only", all(panel.get("implementation_status") == "static_spec_only" for panel in panels.values()), "all panels are static_spec_only")
    results.check("panel_no_mutation", all(panel.get("mutation_allowed") is False for panel in panels.values()), "all panels have mutation_allowed false")
    results.check("panel_no_execution", all(panel.get("execution_allowed") is False for panel in panels.values()), "all panels have execution_allowed false")
    results.check("panel_no_customer_facing", all(panel.get("customer_facing_allowed") is False for panel in panels.values()), "all panels have customer_facing_allowed false")
    panel_field_classes = [field for panel in panels.values() for field in panel.get("field_classes_used", [])]
    results.check("panel_no_never_expose", "never_expose" not in panel_field_classes, "never_expose field class is absent from all panels")

    evidence_ids = set(evidence)
    results.check("required_evidence", REQUIRED_EVIDENCE <= evidence_ids, f"required evidence sources present: {len(REQUIRED_EVIDENCE & evidence_ids)}/{len(REQUIRED_EVIDENCE)}")
    sot_ok = all(evidence.get(item, {}).get("source_of_truth") is True for item in SOURCE_OF_TRUTH_EVIDENCE)
    results.check("source_of_truth_evidence", sot_ok, "user broker/order/Binance screenshots are source_of_truth true")
    external = evidence.get("external_market_data_for_validation_only", {})
    results.check("external_validation_only", external.get("validation_only") is True and external.get("source_of_truth") is False, "external market data is validation_only true and source_of_truth false")

    disagreement_ids = set(disagreements)
    results.check("required_disagreements", REQUIRED_DISAGREEMENTS <= disagreement_ids, f"required disagreements present: {len(REQUIRED_DISAGREEMENTS & disagreement_ids)}/{len(REQUIRED_DISAGREEMENTS)}")
    disagreements_visible = all(item.get("display_required") is True and item.get("may_hide") is False for item in disagreements.values())
    results.check("disagreements_visible", disagreements_visible, "every disagreement type is required and cannot be hidden")
    disagreements_safe = all(item.get("execution_allowed") is False and item.get("mutation_allowed") is False for item in disagreements.values())
    results.check("disagreements_no_execution_or_mutation", disagreements_safe, "every disagreement denies execution and mutation")

    arbitration_ids = set(arbitration)
    results.check("required_arbitration_rules", REQUIRED_ARBITRATION_RULES <= arbitration_ids, f"required arbitration rules present: {len(REQUIRED_ARBITRATION_RULES & arbitration_ids)}/{len(REQUIRED_ARBITRATION_RULES)}")
    arbitration_final = all(item.get("final_commander_decision_required") is True for item in arbitration.values())
    results.check("arbitration_final_commander_required", arbitration_final, "every arbitration rule requires Final Commander decision")
    arbitration_safe = all(item.get("execution_allowed") is False and item.get("runtime_mutation_allowed") is False for item in arbitration.values())
    results.check("arbitration_no_execution_or_mutation", arbitration_safe, "every arbitration rule denies execution and runtime mutation")

    trace_ids = set(trace_items)
    results.check("required_trace_items", REQUIRED_TRACE_ITEMS <= trace_ids, f"required trace items present: {len(REQUIRED_TRACE_ITEMS & trace_ids)}/{len(REQUIRED_TRACE_ITEMS)}")
    traces_visible = all(item.get("display_required") is True and item.get("may_hide") is False for item in trace_items.values())
    results.check("trace_items_visible", traces_visible, "every decision trace item is required and cannot be hidden")

    blocked_ids = set(blocked_actions)
    results.check("required_blocked_actions", REQUIRED_BLOCKED_ACTIONS <= blocked_ids, f"required blocked actions present: {len(REQUIRED_BLOCKED_ACTIONS & blocked_ids)}/{len(REQUIRED_BLOCKED_ACTIONS)}")
    blocked_true = all(item.get("blocked") is True for item in blocked_actions.values())
    results.check("blocked_actions_true", blocked_true, "every blocked action has blocked true")
    no_roles = all(item.get("allowed_roles") == [] for item in blocked_actions.values())
    results.check("blocked_actions_no_roles", no_roles, "every blocked action has empty allowed_roles")
    recommendation_blocked = blocked_actions.get("convert_recommendation_to_execution", {}).get("blocked") is True
    results.check("recommendation_to_execution_blocked", recommendation_blocked, "convert_recommendation_to_execution is blocked")

    results.check("customer_facing_ready_false", spec.get("customer_facing_ready") is False, "customer-facing readiness remains false")
    problems = implementation_problems()
    results.check("no_implementation_files", not problems, "no frontend, API, live endpoint, connector, trading executor, credential store, runtime mutation UI, or automation trigger artifacts found")
    for problem in problems:
        results.failures.append(f"no_implementation_files: {problem}")

    after_hashes = {path: digest(path) for path in REQUIRED_FILES}
    results.check("read_only_integrity", before_hashes == after_hashes, "validator did not modify AI Board static spec files")

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
        print("\nAI Board cockpit static spec validation failed.")
        print(f"Checks: {results.checked}")
        print(f"Blocking failures: {len(results.failures)}")
        print(f"Warnings: {len(results.warnings)}")
        return 1

    print("\nAI Board cockpit static spec validation passed.")
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
