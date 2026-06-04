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
    "created_at",
    "updated_at",
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
                "last_updated": scalar(rule_monitor.data.get("snapshot_time")),
                "cockpit_priority": priority_for_rule(asset, status),
                "requires_execution_price_confirmation": asset == "SOXL",
                "tags": tags_for_rule(asset, status, text),
            }
        )
    return rules


def build_strategy_states(latest_checkpoint: str) -> list[dict[str, Any]]:
    source = [
        "records/ldd/2026-06-04/account_state_delta_0812_0813_sgt.json",
        "records/ldd/2026-06-04/rule_trigger_monitor_0812_0813_sgt.json",
        "records/ldd/2026-06-03/zec_bot_strategy_state_closed_20260603_0839.json",
    ]
    return [
        {
            "strategy_id": "us-historical-position-management",
            "asset_or_module": "U.S. historical positions",
            "status": "active",
            "summary": "Historical-position cleanup and risk-control phase remains active.",
            "next_required_action": "Use SOXL, GGLL, and UGL as risk-reduction valves when rules confirm.",
            "source_files": source[:2],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["historical_cleanup", "risk_control"],
        },
        {
            "strategy_id": "us-new-ldd-model-strategy",
            "asset_or_module": "U.S. model strategy",
            "status": "not_opened",
            "summary": "No new LDD U.S. model strategy position is open.",
            "next_required_action": "Do not open a new model position from this checkpoint.",
            "source_files": [source[0]],
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
            "source_files": [source[0]],
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
            "source_files": [source[0]],
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
            "source_files": [source[0]],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "low",
            "tags": ["closed", "historical_cleanup"],
        },
        {
            "strategy_id": "soxl-risk-valve",
            "asset_or_module": "SOXL",
            "status": "monitoring",
            "summary": "SOXL remains a leveraged risk valve with quote-source conflict requiring order-ticket confirmation.",
            "next_required_action": "Use executable order-ticket bid/ask before any sell or close decision.",
            "source_files": [source[1], "records/ldd/2026-06-04/quote_source_conflict_soxl_0812_0813_sgt.json"],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["soxl", "quote_source_conflict", "risk_valve"],
        },
        {
            "strategy_id": "ggll-risk-valve",
            "asset_or_module": "GGLL",
            "status": "monitoring",
            "summary": "GGLL is governed by GOOG weakness and rebound rules.",
            "next_required_action": "Prepare reduction only after GOOG confirmation lines are observed.",
            "source_files": [source[1]],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["goog", "ggll", "risk_valve"],
        },
        {
            "strategy_id": "ugl-risk-valve",
            "asset_or_module": "UGL",
            "status": "monitoring",
            "summary": "UGL is the first gold-risk valve if GLD breaks 405.",
            "next_required_action": "Monitor GLD 405 and require order evidence before action.",
            "source_files": [source[1]],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["gld", "ugl", "risk_valve"],
        },
        {
            "strategy_id": "nvda-core-ai-exposure",
            "asset_or_module": "NVDA",
            "status": "monitoring",
            "summary": "NVDA remains held but is near the 215/212 risk area.",
            "next_required_action": "Hold unless 212 break requires SOXL or NVDA risk reassessment.",
            "source_files": [source[1]],
            "last_updated": latest_checkpoint,
            "cockpit_priority": "high",
            "tags": ["nvda", "ai_exposure", "near_trigger"],
        },
        {
            "strategy_id": "crypto-defensive-state",
            "asset_or_module": "Crypto spot",
            "status": "active",
            "summary": "Crypto remains USDT-dominant and defensive.",
            "next_required_action": "Do not add ETH, SOL, DOGE, or ZEC; wait for BTC trigger.",
            "source_files": [source[0]],
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
            "source_files": [source[1]],
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
            "source_files": [source[2], source[1]],
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
    portfolio_record = find_record(records, "account_state_delta_0812_0813_sgt")
    rule_monitor = find_record(records, "rule_trigger_monitor_0812_0813_sgt")
    quote_conflict = find_record(records, "quote_source_conflict_soxl_0812_0813_sgt")
    section_review = find_record(records, "section_level_account_structure_requirement_0812_0813_sgt")
    delta_record = find_record(records, "ldd_post_close_runtime_delta_0812_0813_sgt")
    pending_records = [record for record in records if "pending_" in record.relpath or "pending_command" in record.relpath]

    if portfolio_record is None:
        warnings.append("Latest 2026-06-04 account-state delta record is missing")
        portfolio_data: dict[str, Any] = {}
    else:
        portfolio_data = portfolio_record.data

    latest_checkpoint = scalar(
        portfolio_data.get("snapshot_time")
        or timeline.get("generated_at")
        or (delta_record.data.get("sync_time") if delta_record else None)
    )
    source_files = [
        item.relpath
        for item in [portfolio_record, rule_monitor, quote_conflict, section_review, delta_record]
        if item is not None
    ]

    assets = portfolio_data.get("total_visible_assets", {}) if isinstance(portfolio_data.get("total_visible_assets"), dict) else {}
    cash = portfolio_data.get("cash_balance", {}) if isinstance(portfolio_data.get("cash_balance"), dict) else {}
    hk = holding_contains(portfolio_data, "02513")
    zec = holding_by_asset(portfolio_data, "ZEC")

    active_rules = build_active_rules(rule_monitor)
    strategy_states = build_strategy_states(latest_checkpoint)

    command_items: list[dict[str, Any]] = []
    command_counts = {
        "pending_count": 0,
        "executed_count": 0,
        "superseded_count": 0,
        "historical_count": 0,
        "unknown_count": 0,
        "no_new_execution_confirmed": True,
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
                "total_day_pl_usd": approx_signed(assets.get("total_account_day_pl_usd")),
                "note": "Total-account positive day P/L was supported by Hong Kong holding 02513 Zhipu; U.S. equity section itself was negative.",
            },
            "hong_kong_equities": {
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
                "historical_cleanup_status": "SOXS, TSLQ, and GDXU closed; no reopening.",
                "new_ldd_model_strategy_status": "No new LDD U.S. model strategy position.",
                "key_positions": [
                    "GLD 20",
                    "GOOG 14",
                    "NVDA 20",
                    "SOXL 5",
                    "GGLL 10",
                    "INTC 10",
                    "UGL 10",
                    "tiny TSLA residual",
                ],
                "open_risks": [
                    "SOXL leveraged exposure",
                    "GGLL leveraged GOOG exposure",
                    "UGL leveraged gold exposure",
                    "SOXL quote-source conflict",
                ],
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
                "zec_bot_status": "Closed / profit-locked based on prior execution state; no latest bot page screenshot in 2026-06-04 update",
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
                "no_new_execution_confirmed": True,
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
        "source_files": [item for item in source_files if "account_state_delta" in item or "section_level" in item or "quote_source" in item],
        "sections": {
            "total_account": {
                "status": "positive_total_day_pl_but_section_divergence",
                "broker_total_assets_usd": approx(assets.get("broker_total_assets_usd") or assets.get("us_broker_total_assets_usd")),
                "total_day_pl_usd": approx(assets.get("total_account_day_pl_usd")),
                "note": "Total-account day P/L was positive, but U.S. equity section was negative.",
            },
            "us_equities": {
                "status": "negative_day_pl_risk_control_active",
                "section_value_usd": approx(assets.get("us_equity_section_usd") or assets.get("us_stock_section_usd")),
                "day_pl_usd": approx(assets.get("us_day_pl_usd")),
                "main_risk_valves": ["SOXL", "GGLL", "UGL"],
            },
            "hong_kong_equities": {
                "status": "positive_contributor",
                "primary_holding": "02513 Zhipu",
                "day_pl_hkd": approx(hk.get("day_pl_hkd")),
                "holding_pl_hkd": approx(hk.get("holding_pl_hkd")),
            },
            "crypto_spot": {
                "status": "defensive_usdt_dominant",
                "binance_total_assets_usdt": approx(assets.get("binance_visible_assets_usdt")),
                "day_pl_usdt": approx(assets.get("binance_day_pl_usdt")),
                "btc_trigger_status": "not_triggered",
                "zec_grid_status": "closed_profit_locked",
            },
            "cash_and_stablecoins": {
                "status": "defensive_cash_available",
                "broker_cash_usd": approx(cash.get("broker_cash_usd")),
                "binance_usdt": approx(cash.get("binance_usdt"), ""),
            },
            "leveraged_exposure": {
                "status": "risk_controls_active",
                "open_exposures": ["SOXL 5", "GGLL 10", "UGL 10"],
                "no_reopen": ["SOXS", "TSLQ", "GDXU"],
            },
            "historical_cleanup": {
                "status": "active",
                "closed": ["SOXS", "TSLQ", "GDXU"],
                "watch": ["SOXL", "GGLL", "INTC", "UGL"],
            },
            "quote_quality": {
                "status": "quote_source_conflict_requires_confirmation",
                "symbol": "SOXL",
                "holding_page_price": "approximately 261.550",
                "watchlist_or_external_quote": "approximately 280.54",
                "execution_validity": "order-ticket bid/ask required",
            },
        },
        "quality_assessment": {
            "overall_status": "improved_but_risk_controls_active",
            "positive_factors": [
                "Hong Kong 02513 Zhipu supported total-account day P/L.",
                "USDT remains dominant in crypto.",
                "ZEC grid remains closed / profit locked.",
                "SOXS, TSLQ, and GDXU remain closed.",
            ],
            "risk_factors": [
                "U.S. equity section day P/L was negative.",
                "SOXL quote-source conflict blocks execution validity until order-ticket confirmation.",
                "GOOG, NVDA, SOXL, and GLD are close to runtime trigger lines.",
                "BTC buyback remains inactive below 75,500-76,000.",
            ],
            "next_required_confirmations": [
                "Whether GOOG reclaims 358-360 or remains below 355.",
                "Whether NVDA reclaims 218-220 or breaks below 212.",
                "Which SOXL quote is execution-valid on the order ticket.",
                "Whether GLD holds 405.",
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
            "records/ldd/2026-06-04/ldd_post_close_runtime_delta_0812_0813_sgt.json",
        ],
        "active_memory_status": "Keep durable rules and latest 2026-06-04 active checkpoint; archive older detailed snapshots in records/reports.",
        "durable_rules": [
            "User-provided broker/Binance screenshots remain execution source of truth.",
            "Do not execute stale command drafts; execute latest valid command.",
            "No automated trading.",
            "No external API connection without an explicit implementation phase.",
            "BTC buyback waits for 75,500-76,000 stabilization/confirmation.",
            "ZEC grid should not be reopened or chased after profit lock.",
            "SOXL execution requires order-ticket quote confirmation while quote conflict exists.",
        ],
        "current_checkpoint": latest_checkpoint,
        "superseded_snapshot_candidates": [
            "Old 2026-05 detailed LDD account snapshot memories.",
            "2026-06-03 premarket/intraday assumptions where superseded by 2026-06-04 post-close state.",
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
            "latest_checkpoint_confirmed": latest_checkpoint == "2026-06-04T08:13:00+08:00",
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
