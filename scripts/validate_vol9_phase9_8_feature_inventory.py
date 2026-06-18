#!/usr/bin/env python3
"""Validate Vol.9 Phase 9.8 implemented feature inventory artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.9 Phase 9.8"
PHASE9_7_COMMIT = "10f0c3e419378df8033bdfd594cbf2a163351ecb"
STATIC_SHELL_MODE = "local_static_read_only_fixture_only_no_network_no_execution"

TREE_SCHEMA_PATH = "schemas/implemented_feature_inventory_tree.schema.json"
TIMELINE_SCHEMA_PATH = "schemas/implemented_feature_timeline_catalog.schema.json"
TREE_FIXTURE_PATH = "mock_consumers/ldd/implemented_feature_inventory_tree.json"
TIMELINE_FIXTURE_PATH = "mock_consumers/ldd/implemented_feature_timeline_catalog.json"
STATUS_UPDATE_PATH = "mock_consumers/ldd/twos_ldd_post_phase9_8_feature_inventory_status_update.json"
RECORD_PATH = "records/ldd/2026-06-17/vol9_phase9_8_implemented_feature_inventory_tree_and_volume_timeline_catalog_refresh.json"
INVENTORY_DOC_PATH = "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md"
FRAMEWORK_INDEX_DOC_PATH = "docs/runtime/IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX_v0.1.md"

REQUIRED_FILES = [
    "docs/runtime/VOL9_PHASE9_8_IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_VOLUME_TIMELINE_CATALOG_REFRESH_v0.1.md",
    INVENTORY_DOC_PATH,
    TREE_SCHEMA_PATH,
    TIMELINE_SCHEMA_PATH,
    TREE_FIXTURE_PATH,
    TIMELINE_FIXTURE_PATH,
    STATUS_UPDATE_PATH,
    RECORD_PATH,
    "scripts/validate_vol9_phase9_8_feature_inventory.py",
    "scripts/validate_vol9_phase9_8_feature_inventory.sh",
]

INDEX_REQUIRED_REFERENCES = [
    "docs/runtime/VOL9_PHASE9_8_IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_VOLUME_TIMELINE_CATALOG_REFRESH_v0.1.md",
    "docs/runtime/IMPLEMENTED_FEATURE_INVENTORY_TREE_AND_TIMELINE_v0.1.md",
    "mock_consumers/ldd/implemented_feature_inventory_tree.json",
    "mock_consumers/ldd/implemented_feature_timeline_catalog.json",
    "mock_consumers/ldd/twos_ldd_post_phase9_8_feature_inventory_status_update.json",
    "records/ldd/2026-06-17/vol9_phase9_8_implemented_feature_inventory_tree_and_volume_timeline_catalog_refresh.json",
    "scripts/validate_vol9_phase9_8_feature_inventory.py",
]

MOCK_FIXTURES = [TREE_FIXTURE_PATH, TIMELINE_FIXTURE_PATH, STATUS_UPDATE_PATH]
JSON_PATHS = [TREE_FIXTURE_PATH, TIMELINE_FIXTURE_PATH, STATUS_UPDATE_PATH, RECORD_PATH]

REQUIRED_TOP_LEVEL_MODULES = [
    "Tianma Work OS Runtime Governance",
    "LDD Runtime Records & Execution Ledger Support",
    "Static Shell / LDD Cockpit Planning",
    "Mock Consumer Fixtures",
    "Framework Index & Feature Inventory",
    "Cross-Workspace Baseline Sync",
    "Future Implementation Boundary & Gate System",
    "LDD Full-Market Review Scope System",
    "Order Reconciliation & Zero-Fill Separation",
    "Source-of-Truth / Quote-Type / Execution Event Boundaries",
    "Validation & Regression Guard Harness",
    "DUXD Product Feedback Backfeed",
]

REQUIRED_SUBMODULES = [
    "runtime_record_schema_support",
    "runtime_record_validation",
    "runtime_status_arbitration",
    "handoff_summary_and_readiness_gate",
    "implemented_function_framework_index",
    "static_shell_fixture_matrix",
    "static_cockpit_panel_requirements",
    "ldd_full_market_scope_requirements",
    "sector_rotation_heatmap_requirement",
    "non_position_candidate_radar_requirement",
    "forbidden_chase_list_requirement",
    "dream_sleeve_monitoring_only_requirement",
    "full_standalone_sync_regeneration_rule",
    "order_count_anomaly_detector",
    "execution_ledger_gap_detector",
    "spcx_zero_fill_order_reference",
    "quote_type_tagging_boundary",
    "actual_vs_expired_vs_canceled_event_distinction",
    "twos_ldd_runtime_status_backfeed_protocol",
    "ldd_consumer_acknowledgement_gate",
    "strict_baseline_sync_ready_gate",
    "future_implementation_boundary_matrix",
    "static_prototype_gate",
    "future_gate_readiness_checklist",
    "forbidden_scope_regression_guard",
    "future_gate_non_activation_audit",
    "prototype_to_gate_traceability_map",
]

FORBIDDEN_READINESS_CLASSIFICATIONS = [
    "customer_facing_ready",
    "live_runtime_ready",
    "execution_ready",
    "broker_connected",
    "binance_connected",
    "market_data_connected",
    "production_ready",
]

REQUIRED_VOL9_TIMELINE_ENTRIES = [
    "vol9_phase9_1_runtime_status_backfeed_protocol",
    "vol9_phase9_2_ldd_consumer_acknowledgement_gate",
    "vol9_phase9_3_future_implementation_boundary_matrix",
    "vol9_phase9_4_static_prototype_evidence_pack",
    "vol9_phase9_5_forbidden_scope_regression_guard",
    "vol9_phase9_6_static_shell_traceability_map",
    "vol9_phase9_7_ldd_full_report_scope_order_reconciliation_gate",
]

REQUIRED_PHASE9_7_FEATURE_ENTRIES = [
    "full_report_scope_regression_guard",
    "full_standalone_sync_regeneration_rule",
    "order_reconciliation_gate",
    "zero_fill_order_separation",
    "static_cockpit_panel_requirement_gate",
    "ldd_latest_post_close_sync_reference",
]

TABLE_COLUMNS = [
    "Feature ID",
    "Feature Module",
    "Submodule / Capability",
    "Feature Description",
    "Introduced In",
    "Updated In",
    "Primary Artifacts",
    "Validation Coverage",
    "Readiness Classification",
    "Customer-Facing Readiness",
    "Live / Runtime / Execution Capability",
    "Notes",
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


def tree_errors(tree: Any) -> list[str]:
    modules = tree.get("tree_modules")
    if not isinstance(modules, list):
        return ["tree_modules must be an array"]

    errors: list[str] = []
    module_names = []
    submodule_names = []
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            errors.append(f"tree_modules[{index}] must be an object")
            continue
        module_names.append(module.get("module_name"))
        if module.get("readiness_classification") in FORBIDDEN_READINESS_CLASSIFICATIONS:
            errors.append(f"tree_modules[{index}] uses forbidden readiness classification")
        submodules = module.get("submodules")
        if not isinstance(submodules, list) or not submodules:
            errors.append(f"{module.get('module_name', index)} must have at least one submodule")
            continue
        for sub_index, submodule in enumerate(submodules):
            if not isinstance(submodule, dict):
                errors.append(f"tree_modules[{index}].submodules[{sub_index}] must be an object")
                continue
            submodule_names.append(submodule.get("module_name"))
            if submodule.get("readiness_classification") in FORBIDDEN_READINESS_CLASSIFICATIONS:
                errors.append(f"{submodule.get('module_name')} uses forbidden readiness classification")

    for module in sorted(set(REQUIRED_TOP_LEVEL_MODULES) - set(module_names)):
        errors.append(f"missing required top-level module {module}")
    for submodule in sorted(set(REQUIRED_SUBMODULES) - set(submodule_names)):
        errors.append(f"missing required submodule {submodule}")
    return errors


def timeline_errors(catalog: Any) -> list[str]:
    entries = catalog.get("timeline_entries")
    if not isinstance(entries, list):
        return ["timeline_entries must be an array"]

    errors: list[str] = []
    entry_ids = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"timeline_entries[{index}] must be an object")
            continue
        entry_ids.append(entry.get("feature_id"))
        if entry.get("customer_facing_readiness") is not False:
            errors.append(f"{entry.get('feature_id', index)} customer_facing_readiness must be false")
        if entry.get("live_runtime_execution_capability") is not False:
            errors.append(f"{entry.get('feature_id', index)} live_runtime_execution_capability must be false")
        if entry.get("readiness_classification") in FORBIDDEN_READINESS_CLASSIFICATIONS:
            errors.append(f"{entry.get('feature_id', index)} uses forbidden readiness classification")

    for feature_id in sorted(set(REQUIRED_VOL9_TIMELINE_ENTRIES) - set(entry_ids)):
        errors.append(f"missing required Vol.9 timeline entry {feature_id}")
    for feature_id in sorted(set(REQUIRED_PHASE9_7_FEATURE_ENTRIES) - set(entry_ids)):
        errors.append(f"missing required Phase 9.7 feature entry {feature_id}")
    return errors


def main() -> int:
    failures: list[str] = []

    missing = sorted(path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists())
    require(not missing, "required_files", "all Phase 9.8 required files exist", failures)
    for path in missing:
        print(f"Missing: {path}")
    if missing:
        return 1

    try:
        tree_schema = load_json(TREE_SCHEMA_PATH)
        timeline_schema = load_json(TIMELINE_SCHEMA_PATH)
    except json.JSONDecodeError as exc:
        print(f"FAIL schema_parse: schema JSON is invalid: {exc}")
        return 1
    require(isinstance(tree_schema, dict) and isinstance(timeline_schema, dict), "schema_parse", "schema files are parseable JSON objects", failures)

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

    tree = parsed_json[TREE_FIXTURE_PATH]
    catalog = parsed_json[TIMELINE_FIXTURE_PATH]
    status_update = parsed_json[STATUS_UPDATE_PATH]
    record = parsed_json[RECORD_PATH]

    for check_id, document, schema, message in [
        ("tree_schema_validation", tree, tree_schema, "implemented feature inventory tree validates against schema subset"),
        ("timeline_schema_validation", catalog, timeline_schema, "implemented feature timeline catalog validates against schema subset"),
        ("record_timeline_schema_validation", record, timeline_schema, "runtime record validates against timeline catalog schema subset"),
    ]:
        errors = validate_schema_subset(document, schema)
        require(not errors, check_id, message, failures)
        for error in errors:
            print(f"  - {error}")

    for path in MOCK_FIXTURES:
        text = as_text(parsed_json[path])
        require(PHASE in text, f"mock_phase_{Path(path).name}", f"{path} contains required Phase 9.8 name", failures)
        require(PHASE9_7_COMMIT in text, f"mock_commit_{Path(path).name}", f"{path} contains required Phase 9.7 commit hash", failures)

    require(tree.get("implemented_feature_inventory_tree_created") is True, "tree_created", "feature inventory tree is created", failures)
    require(tree.get("feature_inventory_codex_visible") is True, "tree_codex_visible", "feature inventory tree is Codex-visible", failures)
    tree_validation_errors = tree_errors(tree)
    require(not tree_validation_errors, "tree_modules", "feature inventory tree contains required modules, submodules, and allowed readiness classifications", failures)
    for error in tree_validation_errors:
        print(f"  - {error}")

    require(catalog.get("implemented_feature_timeline_catalog_created") is True, "timeline_created", "timeline catalog is created", failures)
    require(catalog.get("feature_inventory_codex_visible") is True, "timeline_codex_visible", "timeline catalog is Codex-visible", failures)
    timeline_validation_errors = timeline_errors(catalog)
    require(not timeline_validation_errors, "timeline_entries", "timeline catalog contains required entries with false customer/live readiness", failures)
    for error in timeline_validation_errors:
        print(f"  - {error}")

    inventory_doc = (REPO_ROOT / INVENTORY_DOC_PATH).read_text(encoding="utf-8")
    require("## 1. Implemented Feature Tree" in inventory_doc, "inventory_doc_tree_heading", "inventory document contains tree heading", failures)
    require("## 2. Implemented Feature Timeline Table" in inventory_doc, "inventory_doc_timeline_heading", "inventory document contains timeline heading", failures)
    missing_columns = sorted(column for column in TABLE_COLUMNS if column not in inventory_doc)
    require(not missing_columns, "inventory_doc_table_columns", "inventory document contains required timeline table columns", failures)
    for column in missing_columns:
        print(f"  - missing column {column}")

    require(record.get("record_type") == "vol9_phase9_8_implemented_feature_inventory_catalog", "record_type", "runtime record has Phase 9.8 record type", failures)
    require(record.get("runtime_records_baseline_before_phase") == 120, "record_runtime_before", "runtime record baseline before phase is 120", failures)
    require(record.get("runtime_records_baseline_after_phase") == 121, "record_runtime_after", "runtime record baseline after phase is 121", failures)
    require(record.get("customer_facing_readiness") is False, "record_customer_facing", "runtime record customer-facing readiness is false", failures)
    require(record.get("live_runtime_execution_frameworks") == 0, "record_live_runtime_frameworks", "runtime record live/runtime/execution frameworks equal 0", failures)
    require(record.get("static_shell_mode") == STATIC_SHELL_MODE, "record_static_shell_mode", "runtime record static shell mode is locked", failures)
    missing_false_flags = [flag for flag in TRADING_IMPACT_FLAGS if record.get(flag) is not False]
    require(not missing_false_flags, "record_trading_impact_flags", "runtime record trading impact flags are all false", failures)
    for flag in missing_false_flags:
        print(f"  - {flag} must be false")

    text_scan_paths = [path for path in REQUIRED_FILES if not path.endswith(".py") and not path.endswith(".sh")]
    all_documents: list[tuple[str, str]] = []
    for path in text_scan_paths + ["INDEX.md", FRAMEWORK_INDEX_DOC_PATH]:
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
    require(not missing_index_refs, "index_references", "INDEX.md references the new Phase 9.8 documents and fixtures", failures)
    for reference in missing_index_refs:
        print(f"  - missing {reference}")

    framework_index_exists = (REPO_ROOT / FRAMEWORK_INDEX_DOC_PATH).exists()
    framework_index_text = (REPO_ROOT / FRAMEWORK_INDEX_DOC_PATH).read_text(encoding="utf-8") if framework_index_exists else ""
    linked_from_framework_index = INVENTORY_DOC_PATH in framework_index_text
    linked_from_index = INVENTORY_DOC_PATH in index_text and "Implemented Function Framework Index" in index_text
    require((not framework_index_exists) or linked_from_framework_index or linked_from_index, "framework_index_forward_reference", "existing framework index points to the new product-readable feature inventory or is linked beside it from INDEX.md", failures)

    status_text = as_text(status_update)
    required_status_lines = [
        "Vol.9 Phase 9.8 creates a product-readable implemented feature inventory tree and volume timeline catalog.",
        "The feature inventory first shows implemented modules and submodules in a tree structure.",
        "The feature inventory then shows concrete feature descriptions and implementation timeline by Vol./Phase in table form.",
        "This update improves Codex visibility into implemented features.",
        "Customer-facing readiness remains false.",
        "Live/runtime/execution framework count remains 0.",
        "Future gate activation remains blocked.",
        "No trading facts are changed by this update.",
        "No portfolio state is changed by this update.",
        "No execution ledger state is changed by this update.",
        "No cash state is changed by this update.",
        "No broker/Binance connection is changed by this update.",
        "No external API, network dependency, scheduler, notification dispatcher, credential handling, runtime mutation, order placement, trading automation, external integration, or production deployment is created.",
    ]
    missing_status_lines = sorted(line for line in required_status_lines if line not in status_text)
    require(not missing_status_lines, "status_update_lines", "post-Phase 9.8 status update contains required LDD sync lines", failures)
    for line in missing_status_lines:
        print(f"  - missing line: {line}")

    if failures:
        print("\nVol.9 Phase 9.8 validation failed.")
        return 1

    print("\nVol.9 Phase 9.8 implemented feature inventory validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
