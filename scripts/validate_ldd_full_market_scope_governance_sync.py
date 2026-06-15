#!/usr/bin/env python3
"""Validate Vol.6 Phase 6.8a LDD full-market scope governance sync."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = "2026-06-12T09:18:00+08:00"
OPERATING_MODE = "cash_defense_core_position_survival_mode"
PORTFOLIO_MODE = "residual_core_position_mode"
STALE_PHASE = "Vol.6 Phase 6.7 - Cockpit Static Spec Integration Review"
STALE_COMMIT = "c2a2a06edba6216eed64998caba018c3a3adf03d"
ACTUAL_PHASE = "Vol.6 Phase 6.8 - Static Consumer Fixture Integration and Handoff"
ACTUAL_COMMIT = "704f006b52461459ccc995ee0b6de7a53bbb0de2"

REQUIRED_FILES = {
    "schema": "schemas/ldd_full_market_scope_governance_sync.schema.json",
    "scope_contract": "mock_consumers/ldd/ldd_full_market_scan_scope_contract.json",
    "sector_heatmap": "mock_consumers/ldd/ldd_sector_rotation_heatmap_contract.json",
    "ipo_radar": "mock_consumers/ldd/ldd_new_listing_ipo_radar_contract.json",
    "watchlist": "mock_consumers/ldd/ldd_non_position_candidate_watchlist.json",
    "pipeline": "mock_consumers/ldd/ldd_candidate_to_position_pipeline.json",
    "forbidden_chase": "mock_consumers/ldd/ldd_forbidden_chase_list.json",
    "replacement_review": "mock_consumers/ldd/ldd_position_replacement_expansion_review_contract.json",
    "record": "records/ldd/2026-06-12/vol6_phase6_8a_ldd_full_market_scope_correction_and_ipo_radar_governance_sync_1720_sgt.json",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_8A_LDD_FULL_MARKET_SCOPE_CORRECTION_AND_IPO_RADAR_GOVERNANCE_SYNC_v0.1.md",
    "schemas/ldd_full_market_scope_governance_sync.schema.json",
    "mock_consumers/ldd/ldd_full_market_scan_scope_contract.json",
    "mock_consumers/ldd/ldd_sector_rotation_heatmap_contract.json",
    "mock_consumers/ldd/ldd_new_listing_ipo_radar_contract.json",
    "mock_consumers/ldd/ldd_non_position_candidate_watchlist.json",
    "mock_consumers/ldd/ldd_candidate_to_position_pipeline.json",
    "mock_consumers/ldd/ldd_forbidden_chase_list.json",
    "mock_consumers/ldd/ldd_position_replacement_expansion_review_contract.json",
    "scripts/validate_ldd_full_market_scope_governance_sync.py",
    "scripts/validate_ldd_full_market_scope_governance_sync.sh",
    "records/ldd/2026-06-12/vol6_phase6_8a_ldd_full_market_scope_correction_and_ipo_radar_governance_sync_1720_sgt.json",
    "reports/ldd/vol6_phase6_8a_ldd_full_market_scope_correction_and_ipo_radar_governance_sync.md",
]

REQUIRED_MODULES = [
    "account_risk_management_layer",
    "full_market_opportunity_scan_layer",
    "sector_rotation_heatmap",
    "new_listing_ipo_radar",
    "non_position_candidate_watchlist",
    "forbidden_chase_list",
    "position_replacement_or_expansion_review",
]

REQUIRED_SCAN_MODULES = [
    "AI_semiconductor",
    "software_cloud_cybersecurity",
    "aerospace_defense_space",
    "robotics_autonomous_driving",
    "energy_oil_nuclear_power",
    "financials_crypto_related_equities",
    "healthcare_glp1",
    "consumer_platform_tech",
    "IPO_new_listings",
    "ETF_index_leveraged_tools",
]

REQUIRED_CANDIDATES = ["SPCX", "MU", "DRAM", "ASML", "TSM", "AMD", "ORCL"]
CHASE_BLOCKED_CANDIDATES = ["SPCX", "MU", "DRAM", "AMD", "ORCL"]

REQUIRED_PIPELINE_STAGES = [
    "market_scan_detected",
    "candidate_watchlist_added",
    "external_verification_required",
    "real_executable_quote_required",
    "rule_review_required",
    "manual_user_order_only",
    "post_execution_reconciliation_required",
    "checkpoint_promotion_only_after_confirmed_execution",
]

REQUIRED_FORBIDDEN_ITEMS = [
    "spcx_above_200_today",
    "spcx_after_ipo_spike_without_30_60_min_confirmation",
    "soxl_rebound_after_forced_deleveraging",
    "gld_rebound_without_400_405_confirmation",
    "ggll_buyback_without_goog_370_confirmation",
    "ugl_reentry",
    "intc_reentry",
    "btc_buyback_below_75500_76000",
    "zec_grid_reopen",
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


def object_by(items: Any, key: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {
        str(item.get(key)): item
        for item in items
        if isinstance(item, dict) and item.get(key) is not None
    }


def main() -> int:
    failures: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}

    for key, relpath in REQUIRED_FILES.items():
        data, error = load_json(relpath)
        if error:
            fail(error, failures)
            continue
        if not isinstance(data, dict):
            fail(f"{relpath} is not a JSON object", failures)
            continue
        loaded[key] = data

    require(len(loaded) == len(REQUIRED_FILES), "required_files", f"{len(loaded)}/{len(REQUIRED_FILES)} required files exist", failures)
    require("schema" in loaded, "required_schema", "full-market governance schema exists", failures)
    require(len(loaded) == len(REQUIRED_FILES), "json_syntax", "all required JSON files are valid objects", failures)

    scope = loaded.get("scope_contract", {})
    require(bool(scope), "full_market_scope_contract", "full-market scope contract exists", failures)
    require(scope.get("ldd_scope") == "entire_us_equity_market", "scope_entire_market", "scope contract uses entire_us_equity_market", failures)
    require(scope.get("not_limited_to_current_or_former_positions") is True, "scope_not_limited", "scope is not limited to current/former positions", failures)
    require(all(item in scope.get("required_layers", []) for item in REQUIRED_MODULES), "permanent_modules", "all seven permanent modules exist", failures)
    require(all(item in scope.get("required_scan_modules", []) for item in REQUIRED_SCAN_MODULES), "full_market_scan_modules", "all ten full-market scan modules exist", failures)

    heatmap = loaded.get("sector_heatmap", {})
    sectors = object_by(heatmap.get("sectors"), "sector_id")
    require(all(item in sectors for item in REQUIRED_SCAN_MODULES), "sector_heatmap", "sector heatmap includes all ten sectors", failures)

    ipo = loaded.get("ipo_radar", {})
    ipo_rules = object_by(ipo.get("candidate_rules"), "ticker")
    spcx = ipo_rules.get("SPCX", {})
    require(bool(ipo), "ipo_radar_contract", "IPO radar contract exists", failures)
    require(spcx.get("status") == "candidate_watchlist_user_provided", "spcx_user_candidate", "SPCX exists as user_provided_candidate", failures)
    require(spcx.get("external_verification_required_before_execution") is True, "spcx_external_verification", "SPCX external verification required", failures)
    require(spcx.get("real_executable_quote_required") is True, "spcx_executable_quote", "SPCX real executable quote required", failures)
    require(spcx.get("no_system_execution") is True, "spcx_no_system_execution", "SPCX system execution disabled", failures)
    require(spcx.get("no_market_order") is True, "spcx_no_market_order", "SPCX market order blocked", failures)
    require(spcx.get("no_heavy_position") is True, "spcx_no_heavy_position", "SPCX heavy position blocked", failures)
    require(spcx.get("no_selling_goog_or_nvda_to_fund") is True, "spcx_no_core_funding_sale", "SPCX cannot be funded by forced GOOG/NVDA sale", failures)

    watchlist = loaded.get("watchlist", {})
    candidates = object_by(watchlist.get("candidates"), "ticker")
    require(all(item in candidates for item in REQUIRED_CANDIDATES), "candidate_watchlist", "watchlist includes SPCX, MU, DRAM, ASML, TSM, AMD, ORCL", failures)
    require(all(candidates.get(item, {}).get("execution_allowed_by_system") is False for item in REQUIRED_CANDIDATES), "candidate_no_system_execution", "every candidate has system execution disabled", failures)
    require(all(candidates.get(item, {}).get("manual_user_action_required") is True for item in REQUIRED_CANDIDATES), "candidate_manual_action", "every candidate requires manual user action", failures)
    require(all(candidates.get(item, {}).get("chase_blocked") is True for item in CHASE_BLOCKED_CANDIDATES), "candidate_chase_blocks", "required candidate chase blocks are present", failures)
    require(candidates.get("SPCX", {}).get("external_verification_required_before_execution") is True, "watchlist_spcx_external_verification", "SPCX watchlist entry requires external verification", failures)

    pipeline = loaded.get("pipeline", {})
    stages = object_by(pipeline.get("stages"), "stage_id")
    require(all(item in stages for item in REQUIRED_PIPELINE_STAGES), "pipeline_stages", "pipeline includes all eight stages", failures)
    require(all(stages.get(item, {}).get("system_execution_allowed") is False for item in REQUIRED_PIPELINE_STAGES), "pipeline_no_system_execution", "every pipeline stage disables system execution", failures)
    require(all(stages.get(item, {}).get("blocks_automation") is True for item in REQUIRED_PIPELINE_STAGES), "pipeline_blocks_automation", "every pipeline stage blocks automation", failures)
    require(stages.get("manual_user_order_only", {}).get("user_manual_action_required") is True, "pipeline_manual_order", "manual_user_order_only requires manual action", failures)

    chase = loaded.get("forbidden_chase", {})
    chase_items = object_by(chase.get("items"), "item_id")
    require(all(item in chase_items for item in REQUIRED_FORBIDDEN_ITEMS), "forbidden_chase_items", "forbidden chase list includes all nine items", failures)
    require(all(chase_items.get(item, {}).get("blocked") is True for item in REQUIRED_FORBIDDEN_ITEMS), "forbidden_chase_blocked", "every forbidden chase item is blocked", failures)
    require(all(chase_items.get(item, {}).get("system_execution_allowed") is False for item in REQUIRED_FORBIDDEN_ITEMS), "forbidden_chase_no_system_execution", "every forbidden chase item blocks system execution", failures)

    replacement = loaded.get("replacement_review", {})
    core = replacement.get("core_funding_protection", {}) if isinstance(replacement.get("core_funding_protection"), dict) else {}
    require(replacement.get("no_automatic_replacement") is True and replacement.get("no_automatic_expansion") is True, "replacement_expansion_blocked", "automatic replacement and expansion are blocked", failures)
    require(core.get("no_selling_goog_to_fund_candidate") is True and core.get("no_selling_nvda_to_fund_candidate") is True, "core_funding_protected", "GOOG/NVDA forced funding sales are blocked", failures)

    record = loaded.get("record", {})
    drift = record.get("cross_workspace_progress_drift", {}) if isinstance(record.get("cross_workspace_progress_drift"), dict) else {}
    require(record.get("checkpoint_promoted") is False, "record_checkpoint_not_promoted", "record checkpoint_promoted is false", failures)
    require(record.get("execution_event") is False, "record_no_execution_event", "record execution_event is false", failures)
    require(record.get("active_checkpoint_after_this_review") == CHECKPOINT, "record_checkpoint_unchanged", f"active checkpoint remains {CHECKPOINT}", failures)
    require(drift.get("stale_ldd_twos_phase") == STALE_PHASE and drift.get("stale_ldd_twos_commit") == STALE_COMMIT, "stale_baseline_recorded", "stale Phase 6.7/c2a2 baseline recorded", failures)
    require(drift.get("actual_twos_phase_before_this_record") == ACTUAL_PHASE and drift.get("actual_twos_commit_before_this_record") == ACTUAL_COMMIT, "actual_baseline_recorded", "actual Phase 6.8/704f baseline recorded", failures)
    require(drift.get("drift_detected") is True, "drift_detected", "cross-workspace drift_detected is true", failures)
    require(drift.get("market_account_facts_still_accepted") is True, "market_facts_accepted", "market/account facts still accepted", failures)
    require(drift.get("runtime_product_baseline_corrected") is True, "runtime_baseline_corrected", "runtime product baseline corrected", failures)
    require(drift.get("backfeed_required_after_completion") is True, "backfeed_required", "backfeed required after completion", failures)
    require(record.get("customer_facing_ready") is False, "customer_facing_false", "customer-facing readiness remains false", failures)

    safety_flags = [
        "external_api_connected",
        "broker_api_connected",
        "binance_api_connected",
        "live_market_data_enabled",
        "trading_automation_enabled",
        "credential_handling_enabled",
        "runtime_mutation_enabled_by_user_interface",
        "execution_trigger_enabled_by_system",
    ]
    require(all(record.get(flag) is False for flag in safety_flags), "safety_flags_false", "no live API/broker/Binance/live market/trading/credential/mutation/execution flag is enabled", failures)
    require(record.get("operating_mode") == OPERATING_MODE, "operating_mode", f"operating mode is {OPERATING_MODE}", failures)
    require(record.get("portfolio_mode") == PORTFOLIO_MODE, "portfolio_mode", f"portfolio mode is {PORTFOLIO_MODE}", failures)

    bad_files: list[str] = []
    for relpath in PHASE_ARTIFACTS:
        path = REPO_ROOT / relpath
        if not path.exists():
            bad_files.append(f"{relpath}: missing")
            continue
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in PROHIBITED_PHASE_PATH_PARTS for part in parts):
            bad_files.append(f"{relpath}: prohibited path segment")
        if path.suffix in PROHIBITED_SUFFIXES:
            bad_files.append(f"{relpath}: prohibited implementation suffix")
    require(not bad_files, "no_implementation_files", "no Phase 6.8a artifact implements frontend/web/API/live endpoint/connector/executor/credential/mutation/automation", failures)
    for item in bad_files:
        print(f"  - {item}")

    print("")
    if failures:
        print("LDD full-market scope governance sync validation failed.")
        print(f"Blocking failures: {len(failures)}")
        for failure in failures:
            print(f"- {failure}")
        print("Warnings: 0")
        return 1

    print("LDD full-market scope governance sync validation passed.")
    print("Checks: 37")
    print("Blocking failures: 0")
    print("Warnings: 0")
    print(f"Active checkpoint: {CHECKPOINT}")
    print("Checkpoint promoted: false")
    print("Execution event: false")
    print(f"Operating mode: {OPERATING_MODE}")
    print(f"Portfolio mode: {PORTFOLIO_MODE}")
    print("Full-market scope contract: created")
    print("New listing / IPO radar contract: created")
    print("Non-position candidate watchlist: created")
    print("Candidate-to-position pipeline: created")
    print("Forbidden chase list: created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
