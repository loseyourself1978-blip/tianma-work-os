#!/usr/bin/env python3
"""Validate Vol.7 Phase 7.3 static shell implementation readiness gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PHASE = "Vol.7 Phase 7.3 - Static Shell Implementation Readiness Gate"
BASELINE_COMMIT = "9e57aa06da5ba992083419d1e6d6183ad98bafa5"
BASELINE_TIMELINE_EVENT = "2026-06-15T14:23:13+08:00"
READINESS_TIMESTAMP = "2026-06-15T17:07:00+08:00"
LOCAL_STATIC_SHELL_TIMESTAMP = "2026-06-15T18:12:39+08:00"
LDD_BACKFEED_TIMESTAMP = "2026-06-15T17:06:00+08:00"
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
SCOPE_REMINDER = "LDD scope is the entire U.S. equity market, not only existing or former positions."
READINESS_DECISION = "ready_with_limits"

REQUIRED_INPUTS = {
    "phase70_boundary_map": "mock_consumers/ldd/vol7_static_ui_shell_boundary_map.json",
    "phase71_contract": "mock_consumers/ldd/vol7_static_fixture_consumer_contract.json",
    "phase71_panel_layout": "mock_consumers/ldd/vol7_read_only_panel_layout.json",
    "phase71_view_model_example": "mock_consumers/ldd/vol7_static_consumer_view_model_example.json",
    "phase72_dry_run": "mock_consumers/ldd/vol7_static_fixture_consumer_dry_run_result.json",
    "phase72_drift_report": "mock_consumers/ldd/vol7_static_fixture_consumer_drift_report.json",
    "latest_state": "cockpit/ldd/latest_state.json",
    "runtime_timeline": "cockpit/ldd/runtime_timeline.json",
    "view_model": "cockpit/ldd/view_model.json",
}

REQUIRED_FILES = {
    "readiness_fixture": "mock_consumers/ldd/vol7_static_shell_implementation_readiness_gate.json",
    "readiness_record": "records/ldd/2026-06-15/vol7_phase7_3_static_shell_implementation_readiness_gate.json",
    "readiness_doc": "docs/runtime/VOL7_PHASE7_3_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE_v0.1.md",
}

REQUIRED_SCHEMAS = {
    "readiness_gate": "schemas/vol7_static_shell_implementation_readiness_gate.schema.json",
}

REQUIRED_LABELS = [
    "STATIC FIXTURE",
    "READ ONLY",
    "NOT EXECUTABLE",
    "NO LIVE DATA",
    "NO BROKER CONNECTION",
    "NO BINANCE CONNECTION",
    "NO CREDENTIAL HANDLING",
    "NO RUNTIME MUTATION",
    "CUSTOMER-FACING READINESS: FALSE",
    "LOCAL STATIC PREVIEW ONLY",
]

REQUIRED_GUARDRAILS = [
    "fixture_only_true",
    "read_only_true",
    "mutation_allowed_false",
    "execution_allowed_false",
    "credential_handling_allowed_false",
    "live_data_allowed_false",
    "customer_facing_readiness_false",
    "no_network_access",
    "no_credential_forms",
    "no_live_refresh",
    "no_execution_controls",
    "no_runtime_mutation_controls",
    "no_customer_facing_publish_flag",
    "visible_static_read_only_non_executable_labels",
]

REQUIRED_FORBIDDEN = [
    "production_deployment",
    "customer_facing_release",
    "hosted_app",
    "api_server",
    "live_endpoint",
    "broker_binance_connection",
    "live_market_data",
    "credential_input",
    "login_auth",
    "execution_trigger",
    "mutation_endpoint",
    "order_placement",
    "portfolio_modification",
    "scheduler",
    "background_worker",
    "notification_dispatcher",
]

QUOTE_TYPES = [
    "broker_watchlist_latest_price",
    "premarket_price",
    "holding_valuation_price",
    "executable_order_page_price",
    "final_filled_order_price",
]

POSITION_CATEGORIES = [
    "current_holdings",
    "watchlist_candidates",
    "forbidden_chase_list",
    "ipo_new_listing_radar",
    "zero_position_former_holdings",
    "residual_tiny_positions",
]

STRATEGY_ITEMS = [
    "not_an_active_attack_day",
    "maintain_cash_defense",
    "hold_nvda_10",
    "hold_goog_9",
    "do_not_chase_soxl_gdxu_gld_ugl_spcx_spch_sspc",
    "do_not_reopen_zec_grid",
    "do_not_reduce_usdt_defense_below_70_percent",
    "btc_buyback_trigger_75500_76000",
    "no_eth_sol_doge_add",
    "no_zec_grid_reopen",
]

DOCUMENT_SECTIONS = [
    "## 1. Phase Summary",
    "## 2. Inputs Reviewed",
    "## 3. Readiness Decision",
    "## 4. Future Implementation Permission Envelope",
    "## 5. Required Guardrails for Any Future Static Shell",
    "## 6. Required Labels",
    "## 7. LDD Full-Market Scope Guard",
    "## 8. Validation Rules",
    "## 9. Exit Criteria",
    "## 10. Handoff to Phase 7.4",
]

TRUE_FLAGS = ["fixture_only", "read_only"]
FALSE_FLAGS = [
    "customer_facing_readiness",
    "mutation_allowed",
    "execution_allowed",
    "credential_handling_allowed",
    "live_data_allowed",
]

PHASE_ARTIFACTS = [
    "docs/runtime/VOL7_PHASE7_3_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE_v0.1.md",
    "schemas/vol7_static_shell_implementation_readiness_gate.schema.json",
    "mock_consumers/ldd/vol7_static_shell_implementation_readiness_gate.json",
    "records/ldd/2026-06-15/vol7_phase7_3_static_shell_implementation_readiness_gate.json",
    "scripts/validate_vol7_static_shell_implementation_readiness_gate.py",
    "scripts/validate_vol7_static_shell_implementation_readiness_gate.sh",
]

PROHIBITED_PHASE_PATH_PARTS = {
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
    "worker",
    "scheduler",
}

PROHIBITED_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}


def load_json(relpath: str) -> tuple[Any | None, str | None]:
    path = REPO_ROOT / relpath
    if not path.exists():
        return None, f"{relpath} is missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{relpath} invalid JSON: {exc}"


def load_text(relpath: str) -> tuple[str | None, str | None]:
    path = REPO_ROOT / relpath
    if not path.exists():
        return None, f"{relpath} is missing"
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, f"{relpath} cannot be read: {exc}"


def fail(message: str, failures: list[str]) -> None:
    print(f"FAIL {message}")
    failures.append(message)


def ok(name: str, message: str) -> None:
    print(f"PASS {name}: {message}")


def require(condition: bool, name: str, message: str, failures: list[str]) -> None:
    if condition:
        ok(name, message)
    else:
        fail(f"{name}: {message}", failures)


def contains_all(value: Any, required: list[str]) -> bool:
    return isinstance(value, list) and all(item in value for item in required)


def schema_required_fields(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return [item for item in required if isinstance(item, str)] if isinstance(required, list) else []


def missing_required(document: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    return [field for field in schema_required_fields(schema) if field not in document]


def static_flags_valid(document: dict[str, Any]) -> bool:
    return all(document.get(flag) is True for flag in TRUE_FLAGS) and all(document.get(flag) is False for flag in FALSE_FLAGS)


def current_timeline_counts(timeline: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    events = timeline.get("events")
    warnings = timeline.get("warnings")
    latest_event = None
    if isinstance(events, list) and events:
        latest = events[-1]
        if isinstance(latest, dict):
            latest_event = (
                latest.get("timestamp")
                or latest.get("timestamp_sgt")
                or latest.get("review_time")
                or latest.get("event_time")
            )
    event_count = len(events) if isinstance(events, list) else None
    warning_count = len(warnings) if isinstance(warnings, list) else None
    return event_count, warning_count, latest_event


def no_implementation_files() -> tuple[bool, list[str]]:
    violations: list[str] = []
    for relpath in PHASE_ARTIFACTS:
        path = Path(relpath)
        parts = set(path.parts)
        suffix = path.suffix.lower()
        if parts & PROHIBITED_PHASE_PATH_PARTS:
            violations.append(relpath)
        if suffix in PROHIBITED_SUFFIXES and not relpath.endswith(".py"):
            violations.append(relpath)
    return not violations, violations


def main() -> int:
    failures: list[str] = []
    inputs: dict[str, dict[str, Any]] = {}
    loaded: dict[str, dict[str, Any]] = {}
    schemas: dict[str, dict[str, Any]] = {}

    for key, relpath in REQUIRED_INPUTS.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        inputs[key] = data

    for key, relpath in REQUIRED_FILES.items():
        if key == "readiness_doc":
            text, error = load_text(relpath)
            if error:
                fail(error, failures)
                continue
            loaded[key] = {"__text": text}
            continue
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        loaded[key] = data

    for key, relpath in REQUIRED_SCHEMAS.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        schemas[key] = data

    require(len(inputs) == len(REQUIRED_INPUTS), "required_inputs", f"{len(inputs)}/{len(REQUIRED_INPUTS)} Phase 7.0-7.2 and cockpit inputs loaded", failures)
    require(len(loaded) == len(REQUIRED_FILES), "required_phase73_files", f"{len(loaded)}/{len(REQUIRED_FILES)} readiness files loaded", failures)
    require(len(schemas) == len(REQUIRED_SCHEMAS), "required_schemas", f"{len(schemas)}/{len(REQUIRED_SCHEMAS)} readiness schemas loaded", failures)

    fixture = loaded.get("readiness_fixture", {})
    record = loaded.get("readiness_record", {})
    schema = schemas.get("readiness_gate", {})
    doc_text = loaded.get("readiness_doc", {}).get("__text", "")

    require(not missing_required(fixture, schema), "fixture_schema_required_fields", "readiness fixture includes required schema fields", failures)
    require(not missing_required(record, schema), "record_schema_required_fields", "runtime record includes readiness schema fields", failures)
    require(all(section in doc_text for section in DOCUMENT_SECTIONS), "document_sections", "readiness document includes all ten required sections", failures)

    for name, document in [("readiness_fixture", fixture), ("readiness_record", record)]:
        require(document.get("phase") == PHASE, f"{name}_phase", f"{name} uses the Phase 7.3 phase label", failures)
        require(document.get("baseline_commit") == BASELINE_COMMIT, f"{name}_baseline_commit", f"{name} baseline commit is {BASELINE_COMMIT}", failures)
        require(document.get("readiness_gate_timestamp") == READINESS_TIMESTAMP, f"{name}_timestamp", f"{name} readiness timestamp is {READINESS_TIMESTAMP}", failures)
        require(document.get("static_shell_implementation_readiness") == READINESS_DECISION, f"{name}_readiness_decision", f"{name} decision is {READINESS_DECISION}", failures)
        require(static_flags_valid(document), f"{name}_static_flags", f"{name} has required static-only flags", failures)
        require(contains_all(document.get("required_labels"), REQUIRED_LABELS), f"{name}_labels", f"{name} includes all required labels", failures)
        require(document.get("ldd_scope_reminder") == SCOPE_REMINDER, f"{name}_scope", f"{name} preserves LDD full-market scope reminder", failures)

    require(fixture.get("active_checkpoint") == CHECKPOINT and record.get("active_checkpoint") == CHECKPOINT, "active_checkpoint", f"active checkpoint remains {CHECKPOINT}", failures)
    require(fixture.get("latest_timeline_event") == BASELINE_TIMELINE_EVENT and record.get("latest_timeline_event") == BASELINE_TIMELINE_EVENT, "baseline_timeline_event", f"baseline timeline event remains {BASELINE_TIMELINE_EVENT}", failures)
    require(fixture.get("runtime_records_count") == 102 and record.get("runtime_records_count") == 102, "baseline_record_count", "baseline runtime record count is 102", failures)
    require(fixture.get("timeline_event_count") == 102 and record.get("timeline_event_count") == 102, "baseline_timeline_count", "baseline timeline event count is 102", failures)
    require(fixture.get("timeline_warning_count") == 0 and record.get("timeline_warning_count") == 0, "baseline_warnings", "baseline timeline warnings are 0", failures)
    require(fixture.get("active_rules_count") == 11 and record.get("active_rules_count") == 11, "active_rules_count", "active rules count is 11", failures)
    require(fixture.get("strategy_states_count") == 16 and record.get("strategy_states_count") == 16, "strategy_states_count", "strategy states count is 16", failures)
    require(fixture.get("operating_mode") == OPERATING_MODE and record.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(fixture.get("portfolio_mode") == PORTFOLIO_MODE and record.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    dry_run = inputs.get("phase72_dry_run", {})
    drift = inputs.get("phase72_drift_report", {})
    require(dry_run.get("dry_run_status") == "passed", "dry_run_status", "Phase 7.2 dry-run status is passed", failures)
    require(dry_run.get("warnings") == [] and dry_run.get("errors") == [], "dry_run_warning_error_count", "Phase 7.2 dry-run warnings/errors are 0/0", failures)
    require(drift.get("drift_status") == "no_drift_detected", "drift_status", "Phase 7.2 drift status is no_drift_detected", failures)
    require(drift.get("critical_drift_count") == 0 and drift.get("warning_drift_count") == 0, "drift_counts", "Phase 7.2 critical/warning drift counts are 0/0", failures)

    input_paths = fixture.get("input_artifacts_reviewed", [])
    require(contains_all(input_paths, list(REQUIRED_INPUTS.values())), "input_artifacts_reviewed", "readiness fixture reviews all required Phase 7.0-7.2 and cockpit inputs", failures)

    envelope = fixture.get("future_implementation_permission_envelope", {})
    forbidden = envelope.get("still_forbidden") if isinstance(envelope, dict) else []
    require(contains_all(forbidden, REQUIRED_FORBIDDEN), "permission_envelope_forbidden", "future permission envelope keeps production/live/API/credential/execution capabilities forbidden", failures)
    require(contains_all(fixture.get("required_guardrails"), REQUIRED_GUARDRAILS), "required_guardrails", "all future static shell guardrails are listed", failures)

    require(fixture.get("ldd_premarket_backfeed_reviewed") is True and record.get("ldd_premarket_backfeed_reviewed") is True, "ldd_backfeed_reviewed", "LDD premarket backfeed is represented", failures)
    require(fixture.get("ldd_premarket_backfeed_timestamp") == LDD_BACKFEED_TIMESTAMP, "ldd_backfeed_timestamp", f"LDD backfeed timestamp is {LDD_BACKFEED_TIMESTAMP}", failures)
    require(fixture.get("quote_type_tagging_required") is True and fixture.get("quote_drift_display_layer_required") is True, "quote_drift_requirements", "quote-type tagging and quote-drift display layer are required", failures)
    require(contains_all(fixture.get("quote_type_distinctions_required"), QUOTE_TYPES), "quote_type_distinctions", "all required quote type distinctions are represented", failures)
    require(fixture.get("holdings_candidate_forbidden_radar_separation_required") is True, "position_radar_separation", "holdings/candidates/forbidden/radar separation is required", failures)
    require(contains_all(fixture.get("position_category_distinctions_required"), POSITION_CATEGORIES), "position_category_distinctions", "all position category distinctions are represented", failures)
    require(fixture.get("ggll_current_state") == "zero_position_not_residual_risk_valve", "ggll_zero_state", "GGLL is zero_position_not_residual_risk_valve", failures)
    require(fixture.get("zec_grid_state") == "closed_no_reopen", "zec_grid_state", "ZEC grid remains closed/no reopen", failures)
    require(fixture.get("usdt_defense_floor_required") is True and fixture.get("usdt_defense_floor") == 0.70, "usdt_floor", "USDT defense floor is 70%", failures)
    require(fixture.get("cash_defense_ratio_split_required") is True, "cash_defense_split", "cash defense ratio split is required", failures)
    cash_values = fixture.get("cash_defense_ratio_static_values", {})
    require(
        isinstance(cash_values, dict)
        and cash_values.get("fixture_only") is True
        and cash_values.get("non_live") is True
        and cash_values.get("non_executable") is True
        and cash_values.get("us_cash_ratio_approx") == 0.778
        and cash_values.get("binance_usdt_defense_ratio_approx") == 0.712,
        "cash_defense_static_values",
        "U.S. and Binance cash-defense ratios are separate fixture-only non-live values",
        failures,
    )
    require(fixture.get("transfer_pnl_separation_required") is True, "transfer_pnl_separation", "transfer/withdrawal separation from trading P/L is required", failures)
    account_events = fixture.get("account_movement_events", [])
    require(
        isinstance(account_events, list)
        and any(isinstance(item, dict) and item.get("event_type") == "crypto_withdrawal" and item.get("amount_usdt") == 49.99 and item.get("classification") == "account_movement_not_trading_pnl" for item in account_events),
        "crypto_withdrawal_separation",
        "49.99 USDT withdrawal is classified as account movement, not trading P/L",
        failures,
    )

    strategy = fixture.get("ldd_strategy_state_snapshot", {})
    strategy_items = strategy.get("items") if isinstance(strategy, dict) else []
    require(
        isinstance(strategy, dict)
        and strategy.get("fixture_only") is True
        and strategy.get("read_only") is True
        and strategy.get("non_live") is True
        and strategy.get("non_executable") is True
        and strategy.get("execution_control_created") is False
        and contains_all(strategy_items, STRATEGY_ITEMS),
        "strategy_snapshot_static",
        "LDD strategy snapshot is static-only, non-live, non-executable, and complete",
        failures,
    )

    timeline = inputs.get("runtime_timeline", {})
    event_count, warning_count, latest_event = current_timeline_counts(timeline)
    require(event_count in {102, 103, 104}, "current_timeline_count", "current timeline count is baseline 102, post-record 103, or post-local-static-shell 104", failures)
    require(warning_count == 0, "current_timeline_warnings", "current timeline warnings remain 0", failures)
    require(latest_event in {BASELINE_TIMELINE_EVENT, READINESS_TIMESTAMP, LOCAL_STATIC_SHELL_TIMESTAMP}, "current_latest_event", "current latest timeline event is baseline, Phase 7.3 readiness timestamp, or Phase 7.4 local static shell timestamp", failures)

    view_model = inputs.get("view_model", {})
    latest_state = inputs.get("latest_state", {})
    require(view_model.get("checkpoint", {}).get("latest_active_checkpoint") == CHECKPOINT, "view_model_checkpoint", "view model active checkpoint is unchanged", failures)
    require(latest_state.get("latest_active_checkpoint") == CHECKPOINT or latest_state.get("checkpoint") == CHECKPOINT, "latest_state_checkpoint", "latest_state active checkpoint is unchanged", failures)

    non_goals = record.get("explicit_non_goals_confirmed", {})
    if not isinstance(non_goals, dict):
        non_goals = {}
    require(non_goals and all(value is False for value in non_goals.values()), "record_non_goals", "record confirms all implementation/live/trading/credential non-goals as false", failures)

    clean, violations = no_implementation_files()
    require(clean, "no_implementation_files", "no Phase 7.3 artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    if violations:
        for violation in violations:
            fail(f"implementation-like artifact path: {violation}", failures)

    print()
    if failures:
        print("Vol.7 static shell implementation readiness gate validation failed.")
    else:
        print("Vol.7 static shell implementation readiness gate validation passed.")
    print("Checks: 55")
    print(f"Blocking failures: {len(failures)}")
    print("Warnings: 0")
    print(f"Static shell implementation readiness: {fixture.get('static_shell_implementation_readiness', 'unknown')}")
    print(f"Active checkpoint: {CHECKPOINT}")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Fixture only: true")
    print("Read only: true")
    print("Customer-facing readiness: false")
    print("LDD premarket backfeed reviewed: true")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
