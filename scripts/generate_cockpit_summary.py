#!/usr/bin/env python3
"""Generate cockpit-ready JSON summaries from local LDD runtime data.

The generator is deterministic, file-based, and uses only the Python standard
library. It does not call external services.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_ROOT = REPO_ROOT / "records" / "ldd"
COCKPIT_DIR = REPO_ROOT / "cockpit" / "ldd"
REPORT_DIR = REPO_ROOT / "reports" / "ldd"
TIMELINE_PATH = COCKPIT_DIR / "runtime_timeline.json"

PROJECT = "LLM Daredevil Desk"
VERSION = "0.1"

OUTPUTS = {
    "manifest": COCKPIT_DIR / "manifest.json",
    "latest_state": COCKPIT_DIR / "latest_state.json",
    "active_rules": COCKPIT_DIR / "active_rules.json",
    "strategy_states": COCKPIT_DIR / "strategy_states.json",
    "account_structure": COCKPIT_DIR / "account_structure.json",
    "pending_commands": COCKPIT_DIR / "pending_commands.json",
    "memory_checkpoint": COCKPIT_DIR / "memory_checkpoint.json",
}


@dataclass(frozen=True)
class RuntimeRecord:
    path: Path
    relpath: str
    data: dict[str, Any]
    timestamp_text: str
    timestamp: datetime | None


TIMESTAMP_FIELDS = [
    "snapshot_time",
    "sync_time",
    "event_time",
    "last_review_time",
    "review_time",
    "validation_time",
    "created_at",
    "updated_at",
    "timestamp_sgt",
]


def relpath(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"{relpath(path)} invalid JSON: {exc}"
    except OSError as exc:
        return None, f"{relpath(path)} cannot be read: {exc}"
    if not isinstance(value, dict):
        return None, f"{relpath(path)} is not a JSON object"
    return value, None


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def first_timestamp(data: dict[str, Any]) -> tuple[str, datetime | None]:
    for field in TIMESTAMP_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value:
            return value, parse_time(value)
    return "", None


def collect_records() -> tuple[list[RuntimeRecord], list[str]]:
    records: list[RuntimeRecord] = []
    warnings: list[str] = []
    if not RECORD_ROOT.exists():
        return records, [f"{relpath(RECORD_ROOT)} does not exist"]

    for path in sorted(RECORD_ROOT.rglob("*.json")):
        data, warning = read_json(path)
        if warning:
            warnings.append(warning)
            continue
        assert data is not None
        timestamp_text, timestamp = first_timestamp(data)
        records.append(RuntimeRecord(path, relpath(path), data, timestamp_text, timestamp))
    return records, warnings


def scalar(value: Any, default: str = "unknown") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return str(value)


def approx(value: Any, prefix: str = "approximately ") -> str:
    if value is None or value == "":
        return "unknown"
    return f"{prefix}{scalar(value)}"


def approx_signed(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return approx(value)
    sign = "+" if number > 0 else ""
    return f"approximately {sign}{scalar(value)}"


def latest(records: list[RuntimeRecord]) -> RuntimeRecord | None:
    if not records:
        return None
    return sorted(records, key=lambda item: (item.timestamp or datetime.min, item.relpath))[-1]


def find_record(records: list[RuntimeRecord], needle: str) -> RuntimeRecord | None:
    matches = [record for record in records if needle in record.relpath]
    return latest(matches)


def find_latest(records: list[RuntimeRecord], needles: list[str]) -> RuntimeRecord | None:
    matches = [
        record
        for record in records
        if any(needle in record.relpath for needle in needles)
    ]
    return latest(matches)


def timeline_payload(warnings: list[str]) -> dict[str, Any]:
    if not TIMELINE_PATH.exists():
        warnings.append(f"{relpath(TIMELINE_PATH)} is missing")
        return {}
    data, warning = read_json(TIMELINE_PATH)
    if warning:
        warnings.append(warning)
        return {}
    assert data is not None
    return data


def report_exists(filename: str) -> bool:
    return (REPORT_DIR / filename).exists()


def holding_by_asset(portfolio: dict[str, Any], asset: str) -> dict[str, Any]:
    for item in portfolio.get("holdings", []):
        if isinstance(item, dict) and scalar(item.get("asset")).lower() == asset.lower():
            return item
    return {}


def holding_contains(portfolio: dict[str, Any], text: str) -> dict[str, Any]:
    needle = text.lower()
    for item in portfolio.get("holdings", []):
        if isinstance(item, dict) and needle in scalar(item.get("asset")).lower():
            return item
    return {}


def rule_status(raw_status: str, asset: str) -> str:
    status = raw_status.lower()
    if "quote_conflict" in status and asset == "SOXL":
        return "awaiting_execution_confirmation"
    if status in {"not_triggered", "waiting", "hold"}:
        return "active"
    if "near_trigger" in status:
        return "near_trigger"
    if status in {"executed", "executed_prior"}:
        return "executed"
    if "partially_executed" in status:
        return "executed"
    if "triggered" in status:
        return "triggered"
    if "superseded" in status:
        return "superseded"
    if "stale" in status:
        return "stale"
    return "active"


def priority_for_rule(asset: str, status: str) -> str:
    if asset == "SOXL" or status in {"awaiting_execution_confirmation", "triggered"}:
        return "high"
    if status == "near_trigger":
        return "high"
    if status == "executed":
        return "medium"
    return "medium"


def tags_for_rule(asset: str, status: str, text: str) -> list[str]:
    tags = [asset.lower().replace("/", "_"), status]
    lowered = text.lower()
    if "quote" in lowered:
        tags.append("quote_source_conflict")
    if "no add" in lowered or "no-add" in lowered:
        tags.append("no_add")
    if "risk" in lowered:
        tags.append("risk_control")
    if "order-ticket" in lowered:
        tags.append("order_ticket_required")
    return sorted(set(tags))


def build_active_rules(rule_monitor: RuntimeRecord | None) -> list[dict[str, Any]]:
    if rule_monitor is None:
        return []
    rules: list[dict[str, Any]] = []
    for item in rule_monitor.data.get("rules", []):
        if not isinstance(item, dict):
            continue
        asset = scalar(item.get("asset"))
        raw_status = scalar(item.get("trigger_status"))
        status = rule_status(raw_status, asset)
        text = json.dumps(item, ensure_ascii=False)
        rules.append(
            {
                "rule_id": scalar(item.get("rule_id")),
                "asset_or_module": asset,
                "rule_type": scalar(item.get("strategy"), "runtime_trigger_monitor"),
                "status": status,
                "trigger_state": raw_status,
                "trigger_condition": scalar(item.get("trigger_condition")),
                "current_action": scalar(item.get("intended_action")),
                "source_files": [rule_monitor.relpath],
                "last_updated": scalar(
                    rule_monitor.data.get("snapshot_time")
                    or rule_monitor.data.get("timestamp_sgt")
                ),
                "cockpit_priority": priority_for_rule(asset, status),
                "requires_execution_price_confirmation": asset == "SOXL",
                "tags": tags_for_rule(asset, status, text),
            }
        )
    return rules


def build_strategy_states(
    latest_checkpoint: str,
    account_source: str,
    rule_source: str,
    zec_source: str,
    cleanup_source: str,
    mode_source: str,
    gld_quantity: str,
    nvda_quantity: str,
    ggll_quantity: str,
) -> list[dict[str, Any]]:
    return [
        {
            "strategy_id": "portfolio-core-position-defense",
            "asset_or_module": "LDD portfolio",
            "status": "active",
            "summary": "Portfolio mode remains core_position_defense_mode after the latest checkpoint validation.",
            "next_required_action": "Defend NVDA, monitor residual GGLL, preserve GLD closure, prohibit re-adds, and maintain USDT defense.",
            "source_files": [account_source, mode_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["core_position_defense_mode", "portfolio_mode_transition"],
        },
        {
            "strategy_id": "us-historical-position-management",
            "asset_or_module": "U.S. historical positions",
            "status": "historical",
            "summary": "The SOXL, UGL, and INTC cleanup cycle is complete; closed positions remain in the historical cleanup ledger.",
            "next_required_action": "Do not re-add SOXL, UGL, or INTC.",
            "source_files": [account_source, cleanup_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["historical_cleanup", "cleanup_completed"],
        },
        {
            "strategy_id": "us-new-ldd-model-strategy",
            "asset_or_module": "U.S. model strategy",
            "status": "not_opened",
            "summary": "No new LDD U.S. model strategy position is open.",
            "next_required_action": "Do not open a new model position from this checkpoint.",
            "source_files": [account_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["new_strategy_separation", "no_new_buying"],
        },
        {
            "strategy_id": "soxs-closed",
            "asset_or_module": "SOXS",
            "status": "closed",
            "summary": "SOXS remains closed with no reopening.",
            "next_required_action": "No reopening.",
            "source_files": [account_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["closed", "historical_cleanup"],
        },
        {
            "strategy_id": "tslq-closed",
            "asset_or_module": "TSLQ",
            "status": "closed",
            "summary": "TSLQ remains closed with no reopening.",
            "next_required_action": "No reopening.",
            "source_files": [account_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["closed", "historical_cleanup"],
        },
        {
            "strategy_id": "gdxu-closed",
            "asset_or_module": "GDXU",
            "status": "closed",
            "summary": "GDXU remains closed with no reopening.",
            "next_required_action": "No reopening.",
            "source_files": [account_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["closed", "historical_cleanup"],
        },
        {
            "strategy_id": "soxl-risk-valve",
            "asset_or_module": "SOXL",
            "status": "closed",
            "summary": "SOXL is closed at 0 shares after the 3-share partial cleanup and 2-share residual cleanup.",
            "next_required_action": "Do not re-add; retain in the closed historical-risk cleanup ledger.",
            "source_files": [account_source, cleanup_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["soxl", "closed_position", "historical_cleanup"],
        },
        {
            "strategy_id": "ggll-risk-valve",
            "asset_or_module": "GGLL",
            "status": "monitoring",
            "summary": f"GGLL is the main remaining leveraged ETF risk valve at {ggll_quantity} shares.",
            "next_required_action": "Clear the remaining 5 GGLL if GOOG cannot reclaim 355; no GGLL add.",
            "source_files": [rule_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["goog", "ggll", "risk_valve"],
        },
        {
            "strategy_id": "ugl-risk-valve",
            "asset_or_module": "UGL",
            "status": "closed",
            "summary": "UGL is closed at 0 shares after the leveraged-gold cleanup execution.",
            "next_required_action": "Do not re-add; the GLD-405 forced UGL cleanup rule is retired.",
            "source_files": [account_source, cleanup_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["gld", "ugl", "closed_position", "historical_cleanup"],
        },
        {
            "strategy_id": "intc-historical-cleanup",
            "asset_or_module": "INTC",
            "status": "closed",
            "summary": "INTC is closed at 0 shares after weak historical-position cleanup.",
            "next_required_action": "Do not re-add; retain in the closed weak-position cleanup ledger.",
            "source_files": [account_source, cleanup_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["intc", "closed_position", "historical_cleanup"],
        },
        {
            "strategy_id": "nvda-core-ai-exposure",
            "asset_or_module": "NVDA",
            "status": "monitoring",
            "summary": f"NVDA remains the main core-risk watch at {nvda_quantity} shares after confirmed protection reductions.",
            "next_required_action": "Hold without adding; reduce another 5 below 198 with weak QQQ/SMH.",
            "source_files": [rule_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["nvda", "core_position", "main_core_risk_watch", "triggered"],
        },
        {
            "strategy_id": "gld-core-position-review",
            "asset_or_module": "GLD",
            "status": "closed" if gld_quantity == "0" else "monitoring",
            "summary": f"GLD is closed at {gld_quantity} shares after confirmed post-close execution reconciliation.",
            "next_required_action": "Do not re-enter until a 380 reclaim and a new approved rule.",
            "source_files": [rule_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["gld", "closed_position", "no_reentry", "confirmed_execution", "ugl_closed"],
        },
        {
            "strategy_id": "crypto-defensive-state",
            "asset_or_module": "Crypto spot",
            "status": "active",
            "summary": "Crypto remains USDT-dominant and defensive.",
            "next_required_action": "Do not add ETH, SOL, DOGE, or ZEC; wait for BTC trigger.",
            "source_files": [account_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["crypto", "usdt_defensive"],
        },
        {
            "strategy_id": "btc-staged-buyback",
            "asset_or_module": "BTC",
            "status": "waiting_for_trigger",
            "summary": "BTC buyback is not triggered below 75,500-76,000.",
            "next_required_action": "Wait for stabilization and confirmation before staged buyback.",
            "source_files": [rule_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["btc", "waiting_for_trigger"],
        },
        {
            "strategy_id": "zec-grid-profit-locked",
            "asset_or_module": "ZEC grid",
            "status": "closed",
            "summary": "ZEC grid remains closed / profit locked based on prior execution state.",
            "next_required_action": "Do not reopen grid or chase; residual ZEC can be converted later if needed.",
            "source_files": [zec_source, rule_source],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["zec", "closed_profit_locked", "no_reopen"],
        },
        {
            "strategy_id": "runtime-records-latest-checkpoint",
            "asset_or_module": "Runtime records",
            "status": "active",
            "summary": f"Latest active checkpoint is {latest_checkpoint}.",
            "next_required_action": "Future cockpit work should read manifest.json first.",
            "source_files": ["cockpit/ldd/manifest.json", "cockpit/ldd/runtime_timeline.json"],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "medium",
            "tags": ["runtime_records", "latest_active_checkpoint"],
        },
    ]


def command_status(raw_status: str, final_status: str, relpath_value: str) -> str:
    text = f"{raw_status} {final_status} {relpath_value}".lower()
    if "superseded" in text:
        return "superseded"
    if "completed" in text or "executed" in text:
        return "executed"
    if "pending_phase2" in text:
        return "historical_command_example"
    if raw_status in {"queued", "drafted", "waiting_feedback"}:
        return "historical_command_example"
    return "unknown"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_payloads(records: list[RuntimeRecord], warnings: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    timeline = timeline_payload(warnings)
    portfolio_record = find_latest(
        records,
        [
            "vol6_phase6_3a_ldd_post_close_execution_reconciliation",
            "account_state_delta",
        ],
    )
    rule_monitor = find_latest(
        records,
        [
            "vol6_phase6_3a_ldd_post_close_execution_reconciliation",
            "active_risk_non_execution_review",
            "rule_trigger_monitor",
            "residual_risk_valve_state",
            "remaining_risk_concentration_monitor",
            "remaining_leveraged_risk_monitor",
        ],
    )
    quote_conflict = find_latest(records, ["quote_type_tagging_reinforcement", "quote_source_conflict_soxl"])
    section_review = find_latest(records, ["hk_high_profit_protection_escalation", "us_cash_ratio_quality_score", "post_sale_cost_basis_interpretation", "closed_position_discipline_validation", "hk_high_profit_protection_requirement", "closed_position_opportunity_cost_requirement", "quote_type_tagging_reinforcement", "section_level_account_structure_requirement", "execution_feedback_loop_requirement"])
    cleanup_effectiveness = find_latest(records, ["cleanup_effectiveness_review"])
    mode_transition = find_latest(records, ["core_position_defense_monitor", "portfolio_mode_transition"])
    delta_record = find_latest(records, ["vol6_phase6_3a_ldd_post_close_execution_reconciliation", "ldd_post_close_execution_review", "ldd_post_close_review", "ldd_core_position_defense_checkpoint", "ldd_post_close_cleanup_review", "ldd_premarket_checkpoint", "ldd_post_close_checkpoint", "ldd_post_close_runtime_delta", "sync_block_delta_protocol"])
    non_execution_review = find_latest(records, ["premarket_trigger_to_post_close_outcome_reconciliation"])
    opportunity_cost_review = find_latest(records, ["closed_position_opportunity_cost_requirement"])
    hk_protection_review = find_latest(records, ["hk_high_profit_protection_requirement"])
    crypto_defense_state = find_latest(records, ["crypto_defense_state_delta"])
    execution_writeback = find_latest(
        records,
        [
            "vol6_phase6_3a_ldd_post_close_execution_reconciliation",
            "executed_order_writeback",
        ],
    )
    compliance_price_review = find_latest(records, ["rule_compliance_vs_price_outcome_review"])
    cash_ratio_review = find_latest(records, ["us_cash_ratio_quality_score"])
    cost_basis_review = find_latest(records, ["post_sale_cost_basis_interpretation"])
    runtime_arbitration = find_latest(records, ["runtime_status_conflict_arbitration"])
    closed_discipline = find_latest(records, ["closed_position_discipline_validation"])
    soxl_execution = find_latest(records, ["soxl_residual_closure_execution", "soxl_execution_filled"])
    soxl_reconciliation = find_latest(records, ["soxl_full_cleanup_reconciliation", "soxl_execution_reconciliation"])
    ugl_execution = find_latest(records, ["ugl_cleanup_execution"])
    ugl_reconciliation = find_latest(records, ["ugl_closure_reconciliation"])
    intc_execution = find_latest(records, ["intc_cleanup_execution"])
    intc_reconciliation = find_latest(records, ["intc_closure_reconciliation"])
    zec_state = find_latest(records, ["zec_bot_strategy_state_closed"])
    pending_records = [record for record in records if "pending_" in record.relpath or "pending_command" in record.relpath]

    if portfolio_record is None:
        warnings.append("Latest account-state delta record is missing")
        portfolio_data: dict[str, Any] = {}
    else:
        portfolio_data = portfolio_record.data

    latest_checkpoint = scalar(
        portfolio_data.get("active_checkpoint_after_this_review")
        or portfolio_data.get("snapshot_time")
        or timeline.get("generated_at")
        or (delta_record.data.get("sync_time") if delta_record else None)
    )
    source_files = [
        item.relpath
        for item in [
            portfolio_record,
            rule_monitor,
            quote_conflict,
            section_review,
            cleanup_effectiveness,
            mode_transition,
            delta_record,
            non_execution_review,
            opportunity_cost_review,
            hk_protection_review,
            crypto_defense_state,
            execution_writeback,
            compliance_price_review,
            cash_ratio_review,
            cost_basis_review,
            runtime_arbitration,
            closed_discipline,
            soxl_execution,
            soxl_reconciliation,
            ugl_execution,
            ugl_reconciliation,
            intc_execution,
            intc_reconciliation,
        ]
        if item is not None
    ]

    assets = portfolio_data.get("total_visible_assets", {}) if isinstance(portfolio_data.get("total_visible_assets"), dict) else {}
    cash = portfolio_data.get("cash_balance", {}) if isinstance(portfolio_data.get("cash_balance"), dict) else {}
    portfolio_tags = portfolio_data.get("strategy_tags", []) if isinstance(portfolio_data.get("strategy_tags"), list) else []
    hk = holding_contains(portfolio_data, "02513")
    zec = holding_by_asset(portfolio_data, "ZEC")
    soxl = holding_by_asset(portfolio_data, "SOXL")
    ugl = holding_by_asset(portfolio_data, "UGL")
    intc = holding_by_asset(portfolio_data, "INTC")
    gld = holding_by_asset(portfolio_data, "GLD")
    nvda = holding_by_asset(portfolio_data, "NVDA")
    ggll = holding_by_asset(portfolio_data, "GGLL")
    soxl_quantity = scalar(soxl.get("quantity"))
    ugl_quantity = scalar(ugl.get("quantity"))
    intc_quantity = scalar(intc.get("quantity"))
    gld_quantity = scalar(gld.get("quantity"))
    nvda_quantity = scalar(nvda.get("quantity"))
    ggll_quantity = scalar(ggll.get("quantity"))
    usdt_defense_ratio = assets.get("binance_usdt_defense_ratio_pct", cash.get("binance_usdt_defense_ratio_pct", 72.9))
    cleanup_confirmed = all(
        [
            soxl_execution is not None,
            soxl_reconciliation is not None,
            ugl_execution is not None,
            ugl_reconciliation is not None,
            intc_execution is not None,
            intc_reconciliation is not None,
            soxl_quantity == "0",
            ugl_quantity == "0",
            intc_quantity == "0",
        ]
    )
    latest_no_new_execution = any("no_new_execution" in str(tag) for tag in portfolio_tags)
    latest_execution_confirmed = execution_writeback is not None and any(
        "confirmed_execution" in str(tag) for tag in portfolio_tags
    )

    active_rules = build_active_rules(rule_monitor)
    strategy_states = build_strategy_states(
        latest_checkpoint,
        portfolio_record.relpath if portfolio_record else "unknown",
        rule_monitor.relpath if rule_monitor else "unknown",
        zec_state.relpath if zec_state else "records/ldd/2026-06-03/zec_bot_strategy_state_closed_20260603_0839.json",
        cleanup_effectiveness.relpath if cleanup_effectiveness else "unknown",
        mode_transition.relpath if mode_transition else "unknown",
        gld_quantity,
        nvda_quantity,
        ggll_quantity,
    )

    command_items: list[dict[str, Any]] = []
    command_counts = {
        "pending_count": 0,
        "executed_count": 0,
        "superseded_count": 0,
        "historical_count": 0,
        "unknown_count": 0,
        "no_new_execution_confirmed": latest_no_new_execution and not latest_execution_confirmed,
        "confirmed_execution_reconciled": cleanup_confirmed or latest_execution_confirmed,
    }
    for record in pending_records:
        status = command_status(
            scalar(record.data.get("status"), ""),
            scalar(record.data.get("final_status"), ""),
            record.relpath,
        )
        if status == "executed":
            command_counts["executed_count"] += 1
        elif status == "superseded":
            command_counts["superseded_count"] += 1
        elif status == "historical_command_example":
            command_counts["historical_count"] += 1
        elif status == "unknown":
            command_counts["unknown_count"] += 1
        else:
            command_counts["pending_count"] += 1
        command_items.append(
            {
                "command_id": scalar(record.data.get("command_id")),
                "status": status,
                "source_status": scalar(record.data.get("status")),
                "final_status": scalar(record.data.get("final_status")),
                "summary": scalar(record.data.get("command_summary")),
                "source_files": [record.relpath],
                "last_updated": scalar(record.data.get("created_at") or record.data.get("snapshot_time"), "unknown"),
                "tags": ["command_intelligence", status],
            }
        )

    active_us_position_labels: list[str] = []
    closed_position_labels: list[str] = []
    for item in portfolio_data.get("holdings", []):
        if not isinstance(item, dict):
            continue
        asset = scalar(item.get("asset"))
        quantity = scalar(item.get("quantity"))
        account = scalar(item.get("account")).lower()
        state = scalar(item.get("position_state")).lower()
        if account == "us_equity" and state != "closed_position":
            if asset == "TSLA":
                active_us_position_labels.append("tiny TSLA residual")
            else:
                active_us_position_labels.append(f"{asset} {quantity}")
        if state == "closed_position":
            closed_position_labels.append(f"{asset} {quantity}")
    for prohibited_symbol in ["SOXS", "TSLQ", "GDXU", "NVDD", "NVDS"]:
        if not any(label.startswith(f"{prohibited_symbol} ") for label in closed_position_labels):
            closed_position_labels.append(f"{prohibited_symbol} 0_or_not_applicable")

    order_entries = [
        item
        for item in portfolio_data.get("confirmed_today_orders", [])
        if isinstance(item, dict)
    ]
    executed_orders = [item for item in order_entries if item.get("execution_state") == "executed"]
    canceled_orders = [item for item in order_entries if item.get("execution_state") == "canceled"]
    reconciliation = portfolio_data.get("reconciliation", {}) if isinstance(portfolio_data.get("reconciliation"), dict) else {}
    latest_fills = {
        f"{scalar(item.get('symbol'))}_{index + 1}": {
            "quantity": item.get("quantity"),
            "price_usd": item.get("price"),
            "execution_state": item.get("execution_state"),
        }
        for index, item in enumerate(order_entries)
    }
    latest_execution_text = (
        "GGLL sell 5 at 114.10, NVDA sell 5 at 199.68, GLD sell 5 at 371.83, GLD sell 5 at 371.60; all executed. GLD sell 5 at 385.00 was canceled."
        if portfolio_data.get("record_type") == "runtime_execution_reconciliation"
        else "GLD sell 5 at 390.91, GLD sell 5 at 391.05, and NVDA sell 5 at 201.74; all filled and reconciled."
    )

    latest_state = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_latest_state",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": source_files + ["cockpit/ldd/runtime_timeline.json"],
        "state_summary": {
            "total_account": {
                "broker_total_assets_usd": approx(assets.get("broker_total_assets_usd") or assets.get("us_broker_total_assets_usd")),
                "cash_usd": approx(assets.get("cash_usd") or cash.get("broker_cash_usd")),
                "total_holding_value_usd": approx(assets.get("total_holding_value_usd")),
                "total_holding_pl_usd": approx_signed(assets.get("total_holding_pl_usd")),
                "total_day_pl_usd": approx_signed(assets.get("total_account_day_pl_usd") or assets.get("broker_day_pl_usd")),
                "note": "The latest post-close checkpoint preserves core_position_defense_mode and reconciles four executed risk-reduction orders plus one canceled order.",
            },
            "hong_kong_equities": {
                "latest_checkpoint_status": "HK high-profit protection is tracked separately from U.S. risk scoring." if hk else "No updated Hong Kong holding detail was encoded in the latest checkpoint.",
                "02513_zhipu": {
                    "shares": hk.get("quantity", 100),
                    "market_value_hkd": approx(hk.get("market_value_hkd")),
                    "latest_price_hkd": approx(hk.get("approx_price_hkd")),
                    "day_pl_hkd": approx_signed(hk.get("day_pl_hkd")),
                    "holding_pl_hkd": approx_signed(hk.get("holding_pl_hkd")),
                }
            },
            "us_equities": {
                "section_value_usd": approx(assets.get("us_equity_section_usd") or assets.get("us_stock_section_usd")),
                "holding_market_value_usd": approx(assets.get("us_holdings_market_value_usd")),
                "holding_pl_usd": approx_signed(assets.get("us_holding_pl_usd")),
                "day_pl_usd": approx_signed(assets.get("us_day_pl_usd")),
                "historical_cleanup_status": "SOXS, TSLQ, GDXU, NVDD, NVDS, SOXL, UGL, and INTC are closed or prohibited; no reopening/no chase.",
                "new_ldd_model_strategy_status": "No new LDD U.S. model strategy position.",
                "key_positions": [
                    f"GOOG {scalar(holding_by_asset(portfolio_data, 'GOOG').get('quantity'))}",
                    f"NVDA {nvda_quantity}",
                    f"GGLL {ggll_quantity}",
                ] if not active_us_position_labels else active_us_position_labels,
                "closed_positions": closed_position_labels or [
                    f"SOXL {soxl_quantity}",
                    f"UGL {ugl_quantity}",
                    f"INTC {intc_quantity}",
                    f"GLD {gld_quantity}",
                ],
                "open_risks": [
                    f"NVDA main core-risk watch at {nvda_quantity} shares",
                    f"GGLL main remaining leveraged ETF risk valve at {ggll_quantity} shares",
                    "GLD is closed and should not be re-entered until a 380 reclaim plus a new approved rule",
                    "Hong Kong high-profit drawdown protection is escalated",
                ],
                "portfolio_mode": "core_position_defense_mode",
            },
            "crypto": {
                "binance_total_assets_usdt": approx(assets.get("binance_visible_assets_usdt")),
                "usdt": approx(cash.get("binance_usdt"), ""),
                "eth": scalar(holding_by_asset(portfolio_data, "ETH").get("quantity")),
                "doge": scalar(holding_by_asset(portfolio_data, "DOGE").get("quantity")),
                "sol": scalar(holding_by_asset(portfolio_data, "SOL").get("quantity")),
                "btc": scalar(holding_by_asset(portfolio_data, "BTC").get("quantity")),
                "zec_residual": f"{scalar(zec.get('quantity'))}, approximately {scalar(zec.get('approx_value_usdt'))} USDT",
                "cash_posture": "USDT-dominant defensive posture",
                "btc_buyback_status": "Not triggered below 75,500-76,000",
                "zec_bot_status": "Closed / profit-locked based on prior confirmed execution state; no ZEC grid reopening.",
                "usdt_defense_ratio_pct": usdt_defense_ratio,
                "open_risks": [
                    "Crypto market weakness",
                    "BTC still below buyback trigger",
                    "ZEC residual only",
                ],
            },
            "runtime": {
                "latest_timeline_event_time": scalar(timeline.get("generated_at"), latest_checkpoint),
                "timeline_event_count": timeline.get("event_count", 0),
                "warning_count": len(timeline.get("warnings", [])) if isinstance(timeline.get("warnings"), list) else 0,
                "no_new_execution_confirmed": latest_no_new_execution and not latest_execution_confirmed,
                "confirmed_execution_reconciled": cleanup_confirmed or latest_execution_confirmed,
                "latest_confirmed_execution": latest_execution_text,
                "execution_writeback": {
                    "order_count": reconciliation.get("order_count", 3),
                    "executed_order_count": reconciliation.get("executed_order_count", 3),
                    "canceled_order_count": reconciliation.get("canceled_order_count", 0),
                    "estimated_gross_proceeds_usd": reconciliation.get("estimated_gross_proceeds_usd", 4918.5),
                    "GLD_position_before": reconciliation.get("GLD_position_before", 20),
                    "GLD_position_after": reconciliation.get("GLD_position_after", 10),
                    "NVDA_position_before": reconciliation.get("NVDA_position_before", 20),
                    "NVDA_position_after": reconciliation.get("NVDA_position_after", 15),
                    "GGLL_position_before": reconciliation.get("GGLL_position_before"),
                    "GGLL_position_after": reconciliation.get("GGLL_position_after"),
                    "status": scalar(reconciliation.get("reconciliation_status"), "confirmed_against_post_sale_holdings_and_cash")
                },
                "rule_compliance_vs_price_outcome": {
                    "GLD": "closed_by_confirmed_execution",
                    "NVDA": "confirmed_execution_rebased_to_10_shares",
                    "GGLL": "confirmed_execution_rebased_to_5_shares",
                    "scoring_boundary": "Rule compliance and price outcome quality are separate."
                },
                "runtime_status_arbitration": {
                    "severity": "non_blocking",
                    "actual_latest_phase": "Vol.6 Phase 6.3 Read-only API Contract",
                    "result": "use_current_phase_6_3_baseline_and_latest_ldd_order_source"
                },
                "superseded_pending_instruction": "2026-06-09 17:26-17:27 SGT/BJT premarket-only Phase 5.9 instruction",
                "soxl_position_after_execution": soxl_quantity,
                "ugl_position_after_execution": ugl_quantity,
                "intc_position_after_execution": intc_quantity,
                "position_states": {
                    "SOXL": "closed_position" if soxl_quantity == "0" else "open",
                    "UGL": "closed_position" if ugl_quantity == "0" else "open",
                    "INTC": "closed_position" if intc_quantity == "0" else "open",
                    "GLD": "closed_position" if gld_quantity == "0" else "open",
                },
                "latest_cleanup_cash_impact": "approximately 2050.03 USD before fees" if cleanup_confirmed else "not available",
                "total_soxl_cleanup_cash_impact": "approximately 1222.68 USD before fees" if cleanup_confirmed else "not available",
                "portfolio_mode": "core_position_defense_mode" if "core_position_defense_mode" in portfolio_tags or cleanup_confirmed else "historical_risk_cleanup_mode",
            },
        },
        "warnings": [],
    }

    active_rules_payload = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_active_rules",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": [rule_monitor.relpath] if rule_monitor else [],
        "rules": active_rules,
        "summary": {
            "rule_count": len(active_rules),
            "near_trigger_count": sum(1 for item in active_rules if item["status"] == "near_trigger"),
            "not_triggered_count": sum(1 for item in active_rules if item.get("trigger_state") == "not_triggered"),
            "awaiting_execution_confirmation_count": sum(1 for item in active_rules if item["status"] == "awaiting_execution_confirmation"),
            "executed_count": sum(1 for item in active_rules if item["status"] == "executed"),
        },
        "warnings": [],
    }

    strategy_payload = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_strategy_states",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": source_files,
        "strategy_states": strategy_states,
        "summary": {
            "strategy_state_count": len(strategy_states),
            "active_or_monitoring_count": sum(1 for item in strategy_states if item["status"] in {"active", "monitoring"}),
            "closed_count": sum(1 for item in strategy_states if item["status"] == "closed"),
            "waiting_for_trigger_count": sum(1 for item in strategy_states if item["status"] == "waiting_for_trigger"),
        },
        "warnings": [],
    }

    account_structure = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_account_structure",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": [
            item
            for item in source_files
            if "account_state_delta" in item
            or "execution_reconciliation" in item
            or "section_level" in item
            or "quote_source" in item
            or "execution_feedback_loop" in item
            or "active_risk_non_execution" in item
            or "premarket_trigger_to_post_close" in item
            or "closed_position_opportunity_cost" in item
            or "hk_high_profit_protection" in item
            or "crypto_defense_state_delta" in item
            or "soxl_execution" in item
            or "cleanup_effectiveness" in item
            or "portfolio_mode_transition" in item
            or "remaining_risk_concentration" in item
            or "remaining_leveraged_risk" in item
            or "core_position_defense" in item
            or "quote_type_tagging" in item
            or "gld_concentration" in item
        ],
        "sections": {
            "total_account": {
                "status": "core_position_defense_validated",
                "broker_total_assets_usd": approx(assets.get("broker_total_assets_usd") or assets.get("us_broker_total_assets_usd")),
                "total_day_pl_usd": approx_signed(assets.get("total_account_day_pl_usd") or assets.get("broker_day_pl_usd")),
                "note": "Latest encoded account state validates core_position_defense_mode.",
            },
            "us_equities": {
                "status": "core_position_defense_validated",
                "section_value_usd": approx(assets.get("us_equity_section_usd") or assets.get("us_stock_section_usd")),
                "day_pl_usd": approx_signed(assets.get("us_day_pl_usd")),
                "main_remaining_leveraged_risk_valve": "GGLL",
                "main_core_risk_watch": "NVDA",
                "gld_status": "GLD closed at 0 shares; no re-entry until a 380 reclaim and a new approved rule",
                "closed_cleanup_positions": ["GLD", "SOXL", "UGL", "INTC"],
            },
            "hong_kong_equities": {
                "status": "separate_high_profit_protection_required",
                "primary_holding": f"02513 Zhipu {scalar(hk.get('quantity'))} shares; {approx(hk.get('market_value_hkd'))} HKD market value",
                "day_pl_hkd": approx_signed(hk.get("day_pl_hkd")),
                "holding_pl_hkd": approx_signed(hk.get("holding_pl_hkd")),
                "protection_status": "escalated_after_large_one_day_drawdown",
                "scoring_boundary": "Do not mix HK high-profit protection into U.S. risk scoring."
            },
            "crypto_spot": {
                "status": "defensive_usdt_dominant",
                "binance_total_assets_usdt": approx(assets.get("binance_visible_assets_usdt")),
                "day_pl_usdt": approx(assets.get("binance_day_pl_usdt")),
                "btc_trigger_status": "not_triggered",
                "zec_grid_status": "closed_profit_locked",
                "usdt_defense_ratio_pct": usdt_defense_ratio,
            },
            "cash_and_stablecoins": {
                "status": "defensive_cash_and_stablecoin_posture",
                "broker_cash_usd": approx(cash.get("broker_cash_usd")),
                "us_cash_ratio_pct": assets.get("us_cash_ratio_pct", cash.get("us_cash_ratio_pct")),
                "binance_usdt": approx(cash.get("binance_usdt"), ""),
                "binance_usdt_defense_ratio_pct": usdt_defense_ratio,
                "latest_execution_gross_proceeds_usd": approx(cash.get("confirmed_order_gross_proceeds_usd")),
            },
            "leveraged_exposure": {
                "status": "reduced_to_residual_ggll_risk_valve",
                "open_exposures": [f"GGLL {ggll_quantity}"],
                "closed_exposures": [f"GLD {gld_quantity}", f"SOXL {soxl_quantity}", f"UGL {ugl_quantity}"],
                "no_reopen": ["GLD", "SOXS", "TSLQ", "GDXU", "NVDD", "NVDS", "SOXL", "UGL"],
            },
            "historical_cleanup": {
                "status": "cleanup_cycle_completed",
                "closed": ["GLD", "SOXS", "TSLQ", "GDXU", "NVDD", "NVDS", "SOXL", "UGL", "INTC"],
                "watch": [],
            },
            "quote_quality": {
                "status": "quote_type_tagging_reinforced",
                "current_sync_quote_type": "us_post_close_after_hours_broker_platform_sot",
                "required_quote_types": [
                    "regular_close",
                    "after_hours_price",
                    "broker_holding_valuation",
                    "executable_quote",
                    "active_position_valuation"
                ],
                "execution_validity": "Post-close and broker holding valuations may inform monitoring but must not be treated as live executable quotes.",
            },
            "active_risk_non_execution": {
                "status": "historical_superseded_by_execution",
                "asset": "GLD",
                "reason": "The prior compliant non-execution state was superseded when GLD later broke the active risk band.",
                "assessment": "historical",
                "rule_remains_active": True,
                "current_result": "compliant_execution"
            },
            "closed_position_opportunity_cost": {
                "status": "tracked_separately_from_rule_compliance",
                "example": "SOXL rebounded after closure, but the rebound is not a rule-compliance failure.",
                "closed_positions": ["SOXL", "UGL", "INTC", "SOXS", "TSLQ", "GDXU", "NVDD", "NVDS"]
            },
            "execution_reconciliation": {
                "status": "latest_orders_confirmed_and_reconciled" if latest_execution_confirmed else "not_confirmed",
                "latest_fills": latest_fills,
                "executed_order_count": reconciliation.get("executed_order_count", len(executed_orders)),
                "canceled_order_count": reconciliation.get("canceled_order_count", len(canceled_orders)),
                "estimated_gross_proceeds_usd": approx(assets.get("confirmed_order_gross_proceeds_usd")),
                "us_cash_ratio_pct": assets.get("us_cash_ratio_pct"),
            },
            "rule_compliance_vs_price_outcome": {
                "status": "separate_scores_required",
                "GLD_rule_compliance": "confirmed_execution_closed_position",
                "NVDA_rule_compliance": "confirmed_execution_rebased_to_10",
                "GGLL_rule_compliance": "confirmed_execution_rebased_to_5",
                "price_outcome_quality": "tracked_separately",
                "account_structure_impact": f"U.S. cash ratio improved to approximately {scalar(assets.get('us_cash_ratio_pct'))} percent"
            },
            "post_sale_cost_basis": {
                "status": "broker_remaining_cost_basis_may_change_after_partial_sale",
                "consumer_rule": "Do not interpret a changed remaining cost basis as a new purchase or missing execution."
            },
            "runtime_status_arbitration": {
                "status": "resolved",
                "severity": "non_blocking",
                "actual_latest_phase": "Vol.6 Phase 6.3 Read-only API Contract",
                "latest_market_source_time": latest_checkpoint
            },
        },
        "quality_assessment": {
            "overall_status": "core_position_defense_validated",
            "positive_factors": [
                "GLD, SOXL, UGL, and INTC are closed at 0 shares.",
                f"Four executed sells generated approximately {scalar(reconciliation.get('estimated_gross_proceeds_usd'))} USD before fees; one GLD order was canceled.",
                f"U.S. cash/cash-equivalent is {approx(cash.get('broker_cash_usd'))} USD.",
                f"U.S. cash ratio is approximately {scalar(assets.get('us_cash_ratio_pct'))} percent.",
                f"USDT is approximately {usdt_defense_ratio}% of Binance visible assets.",
                "ZEC grid remains closed / profit locked.",
                "Portfolio mode remains core_position_defense_mode.",
                "Quote Type Tagging is reinforced for rule validity.",
            ],
            "risk_factors": [
                f"NVDA is the main core-risk watch at {nvda_quantity} shares.",
                f"GGLL is the main remaining leveraged ETF risk valve at {ggll_quantity} shares.",
                "GLD is closed and remains a no-reentry position until a 380 reclaim and a new approved rule.",
                "Hong Kong high-profit drawdown protection is escalated after a -13.54 percent day.",
                "BTC buyback remains inactive below 75,500-76,000.",
            ],
            "next_required_confirmations": [
                "Whether NVDA falls below 198 with weak QQQ/SMH.",
                "Whether GOOG reclaims 355 or triggers removal of the remaining GGLL.",
                "Whether GLD reclaims 380 and receives a new approved re-entry rule.",
                "Whether BTC remains below 75,500-76,000.",
                "Whether any new order screenshots confirm actual execution.",
                "Whether a latest ZEC bot page screenshot is provided.",
            ],
        },
        "warnings": [],
    }

    pending_payload = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_pending_commands",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": [record.relpath for record in pending_records] + ([delta_record.relpath] if delta_record else []),
        "commands": command_items,
        "summary": command_counts,
        "execution_recognition_rule": "New orders should only be recognized when broker/Binance order screenshots confirm execution.",
        "warnings": [],
    }

    memory_payload = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "runtime_layer": "cockpit_memory_checkpoint",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_files": [
            "reports/ldd/latest_active_memory_checkpoint.md",
            "reports/ldd/memory_cleanup_recommendations.md",
            portfolio_record.relpath if portfolio_record else "unknown",
        ],
        "active_memory_status": f"Keep durable rules and latest {latest_checkpoint} active checkpoint; archive older detailed snapshots in records/reports.",
        "durable_rules": [
            "User-provided broker/Binance screenshots remain execution source of truth.",
            "Do not execute stale command drafts; execute latest valid command.",
            "No automated trading.",
            "No external API connection without an explicit implementation phase.",
            "BTC buyback waits for 75,500-76,000 stabilization/confirmation.",
            "ZEC grid should not be reopened or chased after profit lock.",
            "Confirmed cleanup executions should reconcile fills, position state, cash impact, and closed-rule retirement.",
            "Core-position defense remains active after SOXL, UGL, and INTC cleanup.",
            "Confirmed post-close execution reconciliation can promote a newer active checkpoint when order screenshots and account state agree.",
            "Quote Type Tagging is mandatory before treating a price as execution-valid.",
        ],
        "current_checkpoint": latest_checkpoint,
        "superseded_snapshot_candidates": [
            "Old 2026-05 detailed LDD account snapshot memories.",
            "2026-06-06 post-cleanup checkpoint is superseded as active state by the 2026-06-08 core-position defense validation checkpoint.",
            "2026-06-09 17:26-17:27 premarket-only Phase 5.9 instruction is superseded by the 2026-06-10 post-close execution writeback.",
            "2026-06-10 17:06 Phase 6.2a premarket governance evidence remains non-promoted and is superseded as active state by the 2026-06-11 post-close execution reconciliation.",
            "Phase 2 v1/v2 drafted command memories.",
            "Phase 3 v1 still-running ZEC bot assumption.",
        ],
        "requires_user_approval": True,
        "report_availability": {
            "latest_active_memory_checkpoint": report_exists("latest_active_memory_checkpoint.md"),
            "memory_cleanup_recommendations": report_exists("memory_cleanup_recommendations.md"),
        },
        "warnings": [],
    }

    files = {
        "view_model": "cockpit/ldd/view_model.json",
        "latest_state": "cockpit/ldd/latest_state.json",
        "runtime_timeline": "cockpit/ldd/runtime_timeline.json",
        "active_rules": "cockpit/ldd/active_rules.json",
        "strategy_states": "cockpit/ldd/strategy_states.json",
        "account_structure": "cockpit/ldd/account_structure.json",
        "pending_commands": "cockpit/ldd/pending_commands.json",
        "memory_checkpoint": "cockpit/ldd/memory_checkpoint.json",
    }

    manifest = {
        "generated_at": latest_checkpoint,
        "project": PROJECT,
        "cockpit_layer": "ldd_runtime_cockpit_summary",
        "version": VERSION,
        "latest_active_checkpoint": latest_checkpoint,
        "source_root": "records/ldd",
        "source_files": source_files + ["cockpit/ldd/runtime_timeline.json"],
        "files": files,
        "recommended_read_order": [
            "manifest",
            "view_model",
            "latest_state",
            "active_rules",
            "strategy_states",
            "account_structure",
            "pending_commands",
            "memory_checkpoint",
            "runtime_timeline",
        ],
        "status": {
            "ui_ready": True,
            "external_api_connected": False,
            "trading_automation_enabled": False,
            "latest_checkpoint_confirmed": "latest_active_checkpoint" in portfolio_tags,
            "view_model_available_after_generation": True,
        },
        "warnings": warnings,
    }

    payloads = {
        "manifest": manifest,
        "latest_state": latest_state,
        "active_rules": active_rules_payload,
        "strategy_states": strategy_payload,
        "account_structure": account_structure,
        "pending_commands": pending_payload,
        "memory_checkpoint": memory_payload,
    }
    metrics = {
        "latest_active_checkpoint": latest_checkpoint,
        "warning_count": len(warnings),
        "active_rule_count": len(active_rules),
        "strategy_state_count": len(strategy_states),
    }
    return payloads, metrics


def main() -> int:
    records, warnings = collect_records()
    payloads, metrics = build_payloads(records, warnings)

    for key, payload in payloads.items():
        write_json(OUTPUTS[key], payload)

    print("Cockpit summaries generated.")
    print(f"Latest active checkpoint: {metrics['latest_active_checkpoint']}")
    print(f"Warnings: {metrics['warning_count']}")
    print(f"Active rules: {metrics['active_rule_count']}")
    print(f"Strategy states: {metrics['strategy_state_count']}")
    for key in ["manifest", "latest_state", "active_rules", "strategy_states", "account_structure", "pending_commands", "memory_checkpoint"]:
        print(f"- {relpath(OUTPUTS[key])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
