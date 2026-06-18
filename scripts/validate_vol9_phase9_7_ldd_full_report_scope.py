#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.7 LDD full-report scope artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.7"
PHASE9_6_COMMIT = "157b28a66239b16d73acc15962007465a388773f"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

SCOPE_SCHEMA_PATH = "schemas/ldd_full_report_scope_requirements.schema.json"
ORDER_SCHEMA_PATH = "schemas/ldd_order_reconciliation_and_zero_fill_separation.schema.json"
PANEL_SCHEMA_PATH = "schemas/ldd_static_cockpit_panel_requirement_gate.schema.json"
SCOPE_FIXTURE_PATH = "mock_consumers/ldd/ldd_full_report_scope_requirements.json"
ORDER_FIXTURE_PATH = "mock_consumers/ldd/ldd_order_reconciliation_and_zero_fill_separation.json"
PANEL_FIXTURE_PATH = "mock_consumers/ldd/ldd_static_cockpit_panel_requirement_gate.json"
LATEST_REFERENCE_PATH = "mock_consumers/ldd/ldd_latest_post_close_sync_reference.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_7_full_report_scope_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_7_ldd_full_report_scope_regression_guard_order_reconciliation_and_static_cockpit_panel_requirements.json"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_7_LDD_FULL_REPORT_SCOPE_REGRESSION_GUARD_ORDER_RECONCILIATION_AND_STATIC_COCKPIT_PANEL_REQUIREMENTS_v0.1.md",
    "docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md",
    SCOPE_SCHEMA_PATH,
    ORDER_SCHEMA_PATH,
    PANEL_SCHEMA_PATH,
    SCOPE_FIXTURE_PATH,
    ORDER_FIXTURE_PATH,
    PANEL_FIXTURE_PATH,
    LATEST_REFERENCE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_7_ldd_full_report_scope.py",
    "scripts/validate_vol9_phase9_7_ldd_full_report_scope.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_7_LDD_FULL_REPORT_SCOPE_REGRESSION_GUARD_ORDER_RECONCILIATION_AND_STATIC_COCKPIT_PANEL_REQUIREMENTS_v0.1.md",
    "docs/runtime/LDD_FULL_REPORT_SCOPE_AND_ORDER_RECONCILIATION_PROTOCOL_v0.1.md",
    "mock_consumers/ldd/ldd_full_report_scope_requirements.json",
    "mock_consumers/ldd/ldd_order_reconciliation_and_zero_fill_separation.json",
    "mock_consumers/ldd/ldd_static_cockpit_panel_requirement_gate.json",
    "mock_consumers/ldd/ldd_latest_post_close_sync_reference.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_7_full_report_scope_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_7_ldd_full_report_scope_regression_guard_order_reconciliation_and_static_cockpit_panel_requirements.json",
    "scripts/validate_vol9_phase9_7_ldd_full_report_scope.py",
]

SCHEMA_PATHS = [SCOPE_SCHEMA_PATH, ORDER_SCHEMA_PATH, PANEL_SCHEMA_PATH]
JSON_PATHS = [SCOPE_FIXTURE_PATH, ORDER_FIXTURE_PATH, PANEL_FIXTURE_PATH, LATEST_REFERENCE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]
MOCK_FIXTURES = [SCOPE_FIXTURE_PATH, ORDER_FIXTURE_PATH, PANEL_FIXTURE_PATH, LATEST_REFERENCE_PATH, STATUS_UPDATE_PATH]

REQUIRED_REPORT_SECTIONS = [
    "sync_rule_and_baseline",
    "source_of_truth",
    "longbridge_account_update",
    "hk_holding_update",
    "us_holdings_update",
    "zero_position_states",
    "execution_ledger_and_order_state",
    "order_detail_reconciliation",
    "spcx_zero_fill_order_separation",
    "broad_market_structure",
    "sector_rotation_heatmap",
    "ai_semiconductors",
    "mega_cap_tech",
    "cloud_software_enterprise_ai",
    "gold_miners",
    "energy_oil",
    "crypto_crypto_linked_equities",
    "quantum_speculative_tech",
    "space_ipo_new_listings",
    "power_data_center_infrastructure",
    "full_market_candidate_radar",
    "forbidden_chase_list",
    "binance_account_update",
    "strategy_judgment",
    "current_risk_rules",
    "dream_sleeve_monitoring_only",
    "review_score",
    "duxd_product_feedback",
    "final_ldd_instruction",
    "twos_sync_block",
]

SECTION_FIELDS = [
    "section_name",
    "required_in_premarket_review",
    "required_in_post_close_review",
    "scope_classification",
    "source_of_truth_boundary",
    "missing_section_regression_level",
    "non_activation_statement",
]

FORBIDDEN_SCOPE_CLASSIFICATIONS = [
    "holdings_only",
    "current_positions_only",
    "former_positions_only",
    "live_trading_signal",
    "execution_instruction",
    "customer_facing_ui_ready",
    "live_runtime_ready",
    "broker_connection_ready",
    "market_data_ready",
]

REQUIRED_EVENT_CLASSES = [
    "actual_filled_trade",
    "expired_zero_fill_order",
    "canceled_order",
    "portfolio_change",
    "no_cash_impact_event",
    "order_count_anomaly",
    "order_detail_reconciled",
    "execution_ledger_gap_open",
    "execution_ledger_gap_closed",
]

REQUIRED_STATIC_PANELS = [
    "full_market_scan_panel",
    "sector_rotation_heatmap_panel",
    "non_position_candidate_radar_panel",
    "forbidden_chase_list_panel",
    "dream_sleeve_monitoring_only_panel",
    "current_holdings_risk_rules_panel",
    "execution_ledger_order_reconciliation_panel",
    "zero_fill_order_separation_panel",
    "quote_type_tagging_panel",
    "cash_defense_floor_panel",
    "crypto_usdt_defense_panel",
    "full_sync_regeneration_rule_panel",
    "twos_sync_block_panel",
]

PANEL_FIELDS = [
    "panel_name",
    "panel_purpose",
    "required_inputs",
    "static_only_status",
    "related_ldd_report_sections",
    "source_of_truth_boundary",
    "forbidden_interpretations",
    "future_gate_dependency",
    "activation_status",
]

LATEST_REFERENCE_FALSE_FLAGS = [
    "trading_state_mutation",
    "portfolio_state_mutation",
    "cash_state_mutation",
    "execution_ledger_mutation",
    "broker_connection_mutation",
    "binance_connection_mutation",
]

TRADING_IMPACT_FLAGS = [
    "trading_facts_changed",
    "portfolio_state_changed",
    "execution_ledger_changed",
    "cash_state_changed",
    "broker_connection_changed",
    "binance_connection_changed",
]

FORBIDDEN_TRUE_FIELDS = {
    "production_ui",
    "customer_facing_ui",
    "hosted_app",
    "api_server",
    "live_endpoint",
    "external_api",
    "broker_connection",
    "binance_connection",
    "live_market_data",
    "trading_automation",
    "credential_handling",
    "login_auth",
    "runtime_mutation",
    "execution_trigger",
    "order_placement",
    "portfolio_modification",
    "background_worker",
    "scheduler",
    "notification_dispatcher",
    "github_issues",
    "github_projects_board",
    "package_manager_files",
    "build_tools",
    "frontend_framework",
    "network_dependency",
    "external_integration",
    "production_deployment",
    "production_deployment_capability",
    "network_allowed",
    "execution_allowed",
}

FORBIDDEN_POSITIVE_SNIPPETS = [
    '"customer_facing_readiness": true',
    "customer_facing_readiness = true",
    "customer-facing readiness: true",
    "customer-facing readiness: `true`",
    '"network_allowed": true',
    "network_allowed = true",
    "network allowed: true",
    '"execution_allowed": true',
    "execution_allowed = true",
    "execution allowed: true",
    '"production_ui": true',
    '"customer_facing_ui": true',
    '"hosted_app": true',
    '"api_server": true',
    '"live_endpoint": true',
    '"external_api": true',
    '"broker_connection": true',
    '"binance_connection": true',
    '"live_market_data": true',
    '"trading_automation": true',
    '"credential_handling": true',
    '"login_auth": true',
    '"runtime_mutation": true',
    '"execution_trigger": true',
    '"order_placement": true',
    '"portfolio_modification": true',
    '"background_worker": true',
    '"scheduler": true',
    '"notification_dispatcher": true',
    '"github_issues": true',
    '"github_projects_board": true',
    '"package_manager_files": true',
    '"build_tools": true',
    '"frontend_framework": true',
    '"network_dependency": true',
    '"external_integration": true',
    '"production_deployment": true',
    '"production_deployment_capability": true',
]

STATUS_UPDATE_REQUIRED_LINES = [
    "Vol.9 Phase 9.7 creates static LDD full-report scope requirements, full standalone sync regeneration rules, order reconciliation requirements, zero-fill order separation requirements, and static cockpit panel requirement gates.",
    "Future LDD premarket/post-close reviews must include full-market scan, sector rotation heatmap, non-position candidate radar, forbidden chase list, Dream Sleeve monitoring-only section, current holdings/risk rules, execution ledger and order state, order-detail reconciliation where required, quote-type tagging, and TWOS Sync Block.",
    "After user corrections to report scope, assumptions, screenshots, order details, source-of-truth priority, execution classification, rules, or format, LDD must regenerate the full latest report and full LDD → TWOS Sync Block unless explicitly told otherwise.",
    "Holdings-only, current-position-only, and former-position-only LDD reviews are scope-regressed.",
    "SPCX order detail is stored as static reference only: buy limit 150.00, quantity 10, filled quantity 0, status expired, no filled trade, no position created, no cash impact.",
    "Future gate activation remains blocked.",
    "Customer-facing readiness remains false.",
    "Live/runtime/execution framework count remains 0.",
    "No trading facts are changed by this update.",
    "No portfolio state is changed by this update.",
    "No execution ledger state is changed by this update.",
    "No cash state is changed by this update.",
    "No broker/Binance connection is changed by this update.",
    "No external API, network dependency, scheduler, notification dispatcher, credential handling, runtime mutation, order placement, trading automation, external integration, or production deployment is created.",
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
        for key in schema.get("required", []):
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


def as_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def require(condition: bool, check_id: str, message: str, failures: list[str]) -> None:
    if condition:
        print(f"PASS {check_id}: {message}")
    else:
        print(f"FAIL {check_id}: {message}")
        failures.append(check_id)


def nested_forbidden_flag_errors(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_TRUE_FIELDS and child is True:
                errors.append(f"{child_path} is true")
            if key == "customer_facing_readiness" and child is not False:
                errors.append(f"{child_path} must be false")
            if key == "live_runtime_execution_frameworks" and child != 0:
                errors.append(f"{child_path} must be 0")
            if key == "static_shell_mode" and child != STATIC_SHELL_MODE:
                errors.append(f"{child_path} must equal {STATIC_SHELL_MODE}")
            errors.extend(nested_forbidden_flag_errors(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(nested_forbidden_flag_errors(child, f"{path}[{index}]"))
    return errors


def report_section_errors(sections: Any) -> list[str]:
    if not isinstance(sections, list):
        return ["required_report_sections must be an array"]

    errors: list[str] = []
    names = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(f"required_report_sections[{index}] must be an object")
            continue
        names.append(section.get("section_name"))
        for field in SECTION_FIELDS:
            if field not in section:
                errors.append(f"required_report_sections[{index}].{field} missing")
        if section.get("scope_classification") in FORBIDDEN_SCOPE_CLASSIFICATIONS:
            errors.append(f"required_report_sections[{index}].scope_classification is forbidden")
        text = as_text(section)
        for classification in FORBIDDEN_SCOPE_CLASSIFICATIONS:
            if f'"scope_classification": "{classification}"' in text:
                errors.append(f"required_report_sections[{index}] uses forbidden classification {classification}")

    missing = sorted(section for section in REQUIRED_REPORT_SECTIONS if section not in names)
    for section in missing:
        errors.append(f"missing required report section {section}")
    return errors


def static_panel_errors(panels: Any) -> list[str]:
    if not isinstance(panels, list):
        return ["required_static_panels must be an array"]

    errors: list[str] = []
    names = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            errors.append(f"required_static_panels[{index}] must be an object")
            continue
        names.append(panel.get("panel_name"))
        for field in PANEL_FIELDS:
            if field not in panel:
                errors.append(f"required_static_panels[{index}].{field} missing")
        if panel.get("static_only_status") != "required_static_panel":
            errors.append(f"required_static_panels[{index}].static_only_status must be required_static_panel")
        if panel.get("activation_status") != "not_activated":
            errors.append(f"required_static_panels[{index}].activation_status must be not_activated")
        if panel.get("customer_facing_readiness") is not False:
            errors.append(f"required_static_panels[{index}].customer_facing_readiness must be false")
        if panel.get("live_runtime_execution_frameworks") != 0:
            errors.append(f"required_static_panels[{index}].live_runtime_execution_frameworks must be 0")

    missing = sorted(panel for panel in REQUIRED_STATIC_PANELS if panel not in names)
    for panel in missing:
        errors.append(f"missing required static panel {panel}")
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.7 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    schemas: dict[str, Any] = {}
    try:
        for path in SCHEMA_PATHS:
            schemas[path] = load_json(path)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(all(isinstance(schemas[path], dict) for path in SCHEMA_PATHS), "schema_parse", "schema files are parseable JSON objects", failures)

    parsed_json: dict[str, Any] = {}
    for path in JSON_PATHS:
        try:
            parsed_json[path] = load_json(path)
            print(f"PASS json_parse: {path} is parseable JSON")
        except json.JSONDecodeError as exc:
            print(f"FAIL json_parse: {path} invalid JSON: {exc}")
            failures.append(f"json_parse:{path}")

    if failures:
        return 1

    scope = parsed_json[SCOPE_FIXTURE_PATH]
    order = parsed_json[ORDER_FIXTURE_PATH]
    panel = parsed_json[PANEL_FIXTURE_PATH]
    latest = parsed_json[LATEST_REFERENCE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    schema_checks = [
        ("scope_schema_validation", scope, schemas[SCOPE_SCHEMA_PATH], "LDD full report scope requirements validates against schema subset"),
        ("order_schema_validation", order, schemas[ORDER_SCHEMA_PATH], "LDD order reconciliation validates against schema subset"),
        ("panel_schema_validation", panel, schemas[PANEL_SCHEMA_PATH], "LDD static cockpit panel gate validates against schema subset"),
        ("record_panel_schema_validation", record, schemas[PANEL_SCHEMA_PATH], "runtime record validates against static cockpit panel gate schema subset"),
    ]
    for check_id, document, schema, message in schema_checks:
        errors = validate_schema_subset(document, schema)
        require(not errors, check_id, message, failures)
        for error in errors:
            print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.7 name", failures)
        require(PHASE9_6_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.6 commit hash", failures)

    require(scope.get("ldd_full_report_scope_requirements_created") is True, "scope_created", "scope requirements fixture marks LDD full-report scope requirements created", failures)
    require(scope.get("full_standalone_sync_rule_created") is True, "scope_sync_rule_created", "scope requirements fixture marks full standalone sync rule created", failures)
    require(scope.get("full_market_scan_required") is True, "scope_full_market_required", "scope requirements fixture requires full-market scan", failures)
    require(scope.get("holdings_only_review_allowed") is False, "scope_holdings_only_false", "holdings-only LDD review is disallowed", failures)
    require(scope.get("current_positions_only_review_allowed") is False, "scope_current_positions_false", "current-position-only LDD review is disallowed", failures)
    require(scope.get("former_positions_only_review_allowed") is False, "scope_former_positions_false", "former-position-only LDD review is disallowed", failures)
    require(scope.get("incremental_patch_allowed_by_default") is False, "scope_incremental_patch_false", "incremental patch is disallowed by default", failures)

    section_errors = report_section_errors(scope.get("required_report_sections"))
    require(not section_errors, "report_sections", "scope requirements fixture contains all required report sections with allowed classifications", failures)
    for error in section_errors:
        print(f"  - {error}")

    require(order.get("order_reconciliation_gate_created") is True, "order_gate_created", "order reconciliation gate is created", failures)
    require(order.get("zero_fill_order_separation_created") is True, "zero_fill_created", "zero-fill separation is created", failures)
    require(order.get("state_name") == "execution_ledger_gap_closed", "order_state", "order reconciliation state is execution_ledger_gap_closed", failures)

    events = order.get("event_classes", [])
    missing_events = sorted(event for event in REQUIRED_EVENT_CLASSES if event not in events)
    require(not missing_events, "event_classes", "order reconciliation fixture contains all required event classes", failures)
    for event in missing_events:
        print(f"  - missing {event}")

    spcx = order.get("spcx_order_reconciliation", {})
    require(spcx.get("classification") == "expired_zero_fill_order", "spcx_classification", "SPCX order classification is expired_zero_fill_order", failures)
    require(spcx.get("filled_quantity") == 0, "spcx_filled_quantity", "SPCX filled quantity is 0", failures)
    require(spcx.get("filled_trade_occurred") is False, "spcx_filled_trade_false", "SPCX filled_trade_occurred is false", failures)
    require(spcx.get("position_created") is False, "spcx_position_created_false", "SPCX position_created is false", failures)
    require(spcx.get("cash_impact_occurred") is False, "spcx_cash_impact_false", "SPCX cash_impact_occurred is false", failures)
    require(spcx.get("confirmed_filled_us_orders") == 0, "spcx_confirmed_filled_orders", "SPCX confirmed_filled_us_orders is 0", failures)
    require(spcx.get("expired_order_count") == 1, "spcx_expired_order_count", "SPCX expired_order_count is 1", failures)

    require(panel.get("static_cockpit_panel_requirement_gate_created") is True, "panel_gate_created", "static cockpit panel requirement gate is created", failures)
    require(panel.get("scope_regression_guard_created") is True, "panel_scope_guard_created", "scope regression guard is created", failures)
    panel_errors = static_panel_errors(panel.get("required_static_panels"))
    require(not panel_errors, "static_panels", "static cockpit panel gate contains all required panels and all panels remain not activated", failures)
    for error in panel_errors:
        print(f"  - {error}")

    require(latest.get("static_ldd_reference_only") is True, "latest_reference_static_only", "latest post-close sync reference is static only", failures)
    latest_false_errors = [flag for flag in LATEST_REFERENCE_FALSE_FLAGS if latest.get(flag) is not False]
    require(not latest_false_errors, "latest_reference_mutation_flags", "latest post-close sync reference mutation flags are all false", failures)
    for flag in latest_false_errors:
        print(f"  - {flag} must be false")

    require(record.get("record_type") == "vol9_phase9_7_ldd_full_report_scope_order_reconciliation_gate", "record_type", "runtime record has Phase 9.7 record type", failures)
    require(record.get("runtime_records_baseline_before_phase") == 119, "record_runtime_before", "runtime record baseline before phase is 119", failures)
    require(record.get("runtime_records_baseline_after_phase") == 120, "record_runtime_after", "runtime record baseline after phase is 120", failures)
    require(record.get("customer_facing_readiness") is False, "record_customer_facing", "runtime record customer-facing readiness is false", failures)
    require(record.get("live_runtime_execution_frameworks") == 0, "record_live_runtime_frameworks", "runtime record live/runtime/execution frameworks equal 0", failures)
    require(record.get("static_shell_mode") == STATIC_SHELL_MODE, "record_static_shell_mode", "runtime record static shell mode is locked", failures)
    missing_false_flags = [flag for flag in TRADING_IMPACT_FLAGS if record.get(flag) is not False]
    require(not missing_false_flags, "record_trading_impact_flags", "runtime record trading impact flags are all false", failures)
    for flag in missing_false_flags:
        print(f"  - {flag} must be false")

    text_scan_paths = [path for path in REQUIRED_FILES if not path.endswith(".py") and not path.endswith(".sh")]
    all_documents: list[tuple[str, str]] = []
    for path in text_scan_paths + ["INDEX.md"]:
        try:
            all_documents.append((path, (REPO_ROOT / path).read_text(encoding="utf-8")))
        except OSError as exc:
            failures.append(f"read:{path}")
            print(f"FAIL read_{path}: {exc}")

    forbidden_snippet_hits: list[str] = []
    for path, text in all_documents:
        lowered = text.lower()
        for snippet in FORBIDDEN_POSITIVE_SNIPPETS:
            if snippet.lower() in lowered:
                forbidden_snippet_hits.append(f"{path}: {snippet}")
    require(not forbidden_snippet_hits, "forbidden_enabled_snippets", "no forbidden live/runtime/customer-facing capability appears as enabled", failures)
    for hit in forbidden_snippet_hits:
        print(f"  - {hit}")

    forbidden_json_errors: list[str] = []
    for path in JSON_PATHS:
        for error in nested_forbidden_flag_errors(parsed_json[path], "$"):
            forbidden_json_errors.append(f"{path}: {error}")
    require(not forbidden_json_errors, "forbidden_enabled_json_flags", "JSON artifacts do not enable forbidden capabilities", failures)
    for error in forbidden_json_errors:
        print(f"  - {error}")

    index_text = (REPO_ROOT / "INDEX.md").read_text(encoding="utf-8")
    missing_index_refs = sorted(reference for reference in INDEX_REQUIRED_REFERENCES if reference not in index_text)
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.7 documents and fixtures", failures)
    for reference in missing_index_refs:
        print(f"  - missing {reference}")

    status_text = as_text(status_update)
    missing_status_lines = sorted(line for line in STATUS_UPDATE_REQUIRED_LINES if line not in status_text)
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.7 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"  - missing line: {line}")

    if failures:
        print("\nVol.9 Phase 9.7 validation failed.")
        return 1

    print("\nVol.9 Phase 9.7 LDD full-report scope validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
