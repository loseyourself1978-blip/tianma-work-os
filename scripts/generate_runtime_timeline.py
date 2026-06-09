#!/usr/bin/env python3
"""Generate an LDD runtime timeline from local runtime records.

This script reads records/ldd/**/*.json and writes:
- reports/ldd/runtime_timeline.md
- cockpit/ldd/runtime_timeline.json

It uses only the Python standard library and does not call external services.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RECORD_ROOT = REPO_ROOT / "records" / "ldd"
REPORT_PATH = REPO_ROOT / "reports" / "ldd" / "runtime_timeline.md"
COCKPIT_PATH = REPO_ROOT / "cockpit" / "ldd" / "runtime_timeline.json"

TIMESTAMP_FIELDS = [
    "event_time",
    "execution_time",
    "sync_time",
    "source_cutoff_time",
    "review_time",
    "record_time",
    "created_at",
    "updated_at",
    "snapshot_time",
    "last_review_time",
    "contract_time",
    "generation_time",
]


@dataclass(frozen=True)
class LoadedRecord:
    path: Path
    relpath: str
    record_type: str
    data: dict[str, Any]
    event_time: str
    sort_time: datetime | None
    timestamp_source: str


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except json.JSONDecodeError as exc:
        return None, f"{path.relative_to(REPO_ROOT)} invalid JSON: {exc}"
    except OSError as exc:
        return None, f"{path.relative_to(REPO_ROOT)} cannot be read: {exc}"

    if not isinstance(value, dict):
        return None, f"{path.relative_to(REPO_ROOT)} is not a JSON object"
    return value, None


def scalar(value: Any, default: str = "unknown") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return str(value)


def list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def parse_time(value: str) -> datetime | None:
    if not value or value == "unknown":
        return None
    normalized = value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        normalized = f"{value}T00:00:00+08:00"
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None


def infer_date_from_path(path: Path) -> str | None:
    for part in path.parts:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", part):
            return part
    return None


def event_time_for(path: Path, data: dict[str, Any]) -> tuple[str, datetime | None, str]:
    for field in TIMESTAMP_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value:
            return value, parse_time(value), field
    inferred = infer_date_from_path(path)
    if inferred:
        return inferred, parse_time(inferred), "path_date"
    return "unknown", None, "unknown"


def classify_record(path: Path, data: dict[str, Any]) -> str:
    name = path.name
    if "cockpit_view_model_generation" in name:
        return "cockpit_view_model_generation"
    if "view_model_quality_gate_review" in name:
        return "view_model_quality_gate_review"
    if "cockpit_consumer_readiness_review" in name:
        return "cockpit_consumer_readiness_review"
    if "ldd_post_close_review" in name:
        return "sync_delta_update"
    if "premarket_trigger_to_post_close_outcome_reconciliation" in name:
        return "rule_based_execution_review"
    if "active_risk_non_execution_review" in name:
        return "rule_ledger_snapshot"
    if "gld_active_risk_rule_update" in name or "nvda_core_risk_trigger_update" in name or "goog_ggll_risk_valve_update" in name:
        return "trigger_execution_rule"
    if "closed_position_opportunity_cost_requirement" in name or "hk_high_profit_protection_requirement" in name:
        return "account_structure_review"
    if "crypto_defense_state_delta" in name:
        return "strategy_state"
    if "cockpit_view_model_contract" in name:
        return "cockpit_view_model_contract"
    if "cockpit_consistency_review" in name:
        return "cockpit_consistency_review"
    if "account_state_delta" in name:
        return "portfolio_state"
    if "rule_trigger_monitor" in name or "remaining_leveraged_risk_monitor" in name:
        return "rule_ledger_snapshot"
    if "post_close_runtime_delta" in name:
        return "sync_delta_update"
    if "quote_source_conflict" in name or "quote_type_tagging_reinforcement" in name or "section_level_account_structure_requirement" in name:
        return "account_structure_review"
    if "portfolio_state" in name:
        return "portfolio_state"
    if "pending_" in name or "pending_command" in name:
        return "pending_command"
    if "command_intelligence_check" in name or "superseded_check" in name:
        return "command_intelligence_check"
    if "smart_execution_plan" in name:
        return "smart_execution_plan"
    if "execution_feedback" in name:
        return "command_execution_feedback"
    if "rule_based_execution_review" in name:
        return "rule_based_execution_review"
    if "volatility_execution_split" in name:
        return "volatility_execution_split"
    if "sync_block_delta" in name or "sync_delta" in name or "delta_protocol" in name:
        return "sync_delta_update"
    if "rule_ledger_snapshot" in name:
        return "rule_ledger_snapshot"
    if "closure_execution" in name:
        return "execution_event"
    if "strategy_state" in name:
        return "strategy_state"
    if "trigger_rule" in name or "trigger_execution" in name:
        return "trigger_execution_rule"
    if "account_structure_review" in name or "account_structure_score" in name or "account_structure_update" in name:
        return "account_structure_review"
    if "active_memory_checkpoint" in name:
        return "active_memory_checkpoint"
    if "memory_cleanup_recommendation" in name:
        return "memory_cleanup_recommendation"
    if "memory_retention_policy" in name:
        return "memory_retention_policy"

    if "event_id" in data and "execution_type" in data:
        return "execution_event"
    if "delta_id" in data:
        return "sync_delta_update"
    if "strategy_id" in data and "health_state" in data:
        return "strategy_state"
    if "rule_id" in data and "trigger_condition" in data:
        return "trigger_execution_rule"
    if "review_id" in data and "structure_score" in data:
        return "account_structure_review"
    if "review_id" in data and "rule_compliance_score" in data:
        return "rule_based_execution_review"
    if "snapshot_id" in data and "rules" in data:
        return "rule_ledger_snapshot"
    if data.get("schema_type") == "cockpit_consistency_review":
        return "cockpit_consistency_review"
    if data.get("schema_type") == "cockpit_view_model_contract":
        return "cockpit_view_model_contract"
    if data.get("schema_type") == "cockpit_view_model_generation":
        return "cockpit_view_model_generation"
    if data.get("schema_type") == "view_model_quality_gate_review":
        return "view_model_quality_gate_review"
    if data.get("schema_type") == "cockpit_consumer_readiness_review":
        return "cockpit_consumer_readiness_review"
    if "command_id" in data:
        return "pending_command"
    return "unknown"


def collect_records() -> tuple[list[LoadedRecord], list[str]]:
    warnings: list[str] = []
    records: list[LoadedRecord] = []

    if not RECORD_ROOT.exists():
        return records, [f"{RECORD_ROOT.relative_to(REPO_ROOT)} does not exist"]

    for path in sorted(RECORD_ROOT.rglob("*.json")):
        data, warning = load_json(path)
        if warning:
            warnings.append(warning)
            continue
        assert data is not None
        record_type = classify_record(path, data)
        event_time, sort_time, timestamp_source = event_time_for(path, data)
        if timestamp_source == "path_date":
            warnings.append(f"{path.relative_to(REPO_ROOT)} uses date inferred from file path")
        if timestamp_source == "unknown":
            warnings.append(f"{path.relative_to(REPO_ROOT)} has unknown timestamp")
        records.append(
            LoadedRecord(
                path=path,
                relpath=str(path.relative_to(REPO_ROOT)),
                record_type=record_type,
                data=data,
                event_time=event_time,
                sort_time=sort_time,
                timestamp_source=timestamp_source,
            )
        )

    return records, warnings


def event_type(record_type: str) -> str:
    mapping = {
        "portfolio_state": "portfolio_snapshot",
        "strategy_state": "strategy_state_update",
        "trigger_execution_rule": "trigger_rule_update",
        "rule_ledger_snapshot": "trigger_rule_update",
        "volatility_execution_split": "trigger_rule_update",
        "execution_event": "execution_event",
        "rule_based_execution_review": "rule_review",
        "account_structure_review": "account_structure_review",
        "sync_delta_update": "sync_delta",
        "pending_command": "pending_command",
        "command_intelligence_check": "command_intelligence",
        "smart_execution_plan": "command_intelligence",
        "command_execution_feedback": "command_intelligence",
        "active_memory_checkpoint": "memory_checkpoint",
        "memory_cleanup_recommendation": "memory_checkpoint",
        "memory_retention_policy": "memory_checkpoint",
        "cockpit_consistency_review": "report_generation",
        "cockpit_view_model_contract": "report_generation",
        "cockpit_view_model_generation": "report_generation",
        "view_model_quality_gate_review": "report_generation",
        "cockpit_consumer_readiness_review": "report_generation",
    }
    return mapping.get(record_type, "unknown")


def evidence_level(data: dict[str, Any], record_type: str) -> str:
    source = " ".join(list_of_strings(data.get("source_of_truth"))).lower()
    if "screenshot" in source or "actual_execution" in source:
        return "user_screenshot_source_of_truth"
    if record_type in {"active_memory_checkpoint", "memory_cleanup_recommendation", "memory_retention_policy"}:
        return "generated_report"
    if record_type == "cockpit_consistency_review":
        return "runtime_record"
    if record_type == "cockpit_view_model_contract":
        return "runtime_record"
    if record_type == "cockpit_view_model_generation":
        return "runtime_record"
    if record_type == "view_model_quality_gate_review":
        return "runtime_record"
    if record_type == "cockpit_consumer_readiness_review":
        return "runtime_record"
    if record_type == "unknown":
        return "unknown"
    return "runtime_record"


def priority(record_type: str, data: dict[str, Any], tags: list[str]) -> str:
    if record_type in {"cockpit_consistency_review", "cockpit_view_model_contract", "cockpit_view_model_generation", "view_model_quality_gate_review", "cockpit_consumer_readiness_review"}:
        return "medium"
    text = json.dumps(data, ensure_ascii=False).lower()
    if record_type == "execution_event":
        return "critical"
    if record_type == "sync_delta_update":
        return "critical"
    if "quote_source_conflict" in text or "quote-source-conflict" in text or "near_trigger" in text:
        return "high"
    if "closed_profit_locked" in scalar(data.get("health_state")):
        return "high"
    if "executed" in scalar(data.get("execution_status")):
        return "high"
    if record_type in {"strategy_state", "trigger_execution_rule", "rule_based_execution_review", "account_structure_review"}:
        return "medium"
    if "superseded" in tags:
        return "low"
    return "low"


def asset_or_module(record_type: str, data: dict[str, Any]) -> str:
    for key in ["asset", "linked_asset", "account", "account_type", "subproject", "project"]:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    if record_type == "pending_command":
        return "Command Intelligence"
    if record_type.startswith("memory_"):
        return "Memory Retention"
    return "LDD Runtime"


def first_nonempty(data: dict[str, Any], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return default


def title_and_summary(record: LoadedRecord) -> tuple[str, str]:
    data = record.data
    rt = record.record_type
    if rt == "portfolio_state":
        assets = data.get("total_visible_assets", {}) if isinstance(data.get("total_visible_assets"), dict) else {}
        if "latest_active_checkpoint" in json.dumps(data, ensure_ascii=False).lower():
            return (
                "Portfolio snapshot: latest active LDD checkpoint",
                f"Post-close account state recorded with broker total assets about {scalar(assets.get('broker_total_assets_usd') or assets.get('us_broker_total_assets_usd'))} USD and Binance visible assets about {scalar(assets.get('binance_visible_assets_usdt'))} USDT.",
            )
        return (
            f"Portfolio snapshot: {scalar(data.get('account_type'))}",
            f"Visible portfolio snapshot recorded with base currency {scalar(data.get('base_currency'))}.",
        )
    if rt == "strategy_state":
        return (
            f"Strategy state: {scalar(data.get('linked_asset'))} {scalar(data.get('health_state'))}",
            scalar(data.get("market_state_context") or data.get("recommended_action")),
        )
    if rt == "trigger_execution_rule":
        return (
            f"Trigger rule: {scalar(data.get('asset'))}",
            scalar(data.get("trigger_condition")),
        )
    if rt == "rule_ledger_snapshot":
        rules = data.get("rules", [])
        count = len(rules) if isinstance(rules, list) else 0
        text = json.dumps(data, ensure_ascii=False).lower()
        if "rule-trigger-monitor" in scalar(data.get("snapshot_id")) or "near_trigger" in text:
            return (
                "Runtime rule trigger monitor",
                f"Rule trigger monitor captured {count} active rules, including near-trigger states and execution-confirmation requirements.",
            )
        return (
            "Rule ledger snapshot",
            f"Rule ledger snapshot captured {count} trigger rules.",
        )
    if rt == "volatility_execution_split":
        return (
            f"Volatility split plan: {scalar(data.get('asset'))}",
            scalar(data.get("market_context")),
        )
    if rt == "execution_event":
        trade = data.get("trade", {}) if isinstance(data.get("trade"), dict) else {}
        return (
            f"Execution event: {scalar(data.get('action'))} {scalar(data.get('asset'))}",
            f"{scalar(data.get('execution_type'))}: {scalar(trade.get('side'))} {scalar(trade.get('quantity'))} {scalar(trade.get('symbol'))} at {scalar(trade.get('price'))}.",
        )
    if rt == "rule_based_execution_review":
        if data.get("rule_compliance_result") == "compliant_non_execution":
            return (
                f"Active-risk non-execution review: {scalar(data.get('asset'))}",
                f"{scalar(data.get('non_execution_assessment'))} non-execution: {scalar(data.get('non_execution_reason'))}.",
            )
        return (
            f"Rule review: {scalar(data.get('asset'))}",
            scalar(data.get("review_conclusion")),
        )
    if rt == "account_structure_review":
        review_id = scalar(data.get("review_id")).lower()
        findings = data.get("key_findings", [])
        first_finding = str(findings[0]) if isinstance(findings, list) and findings else ""
        if "quote-source-conflict-soxl" in review_id:
            return (
                "Quote source conflict: SOXL",
                first_finding or "SOXL quote-source conflict requires order-ticket bid/ask confirmation before execution.",
            )
        if "section-level-account-structure-requirement" in review_id:
            return (
                "Section-level account structure requirement",
                first_finding or "Section-level account structure scoring separates total account, U.S. equity, Hong Kong equity, crypto, cash, stablecoin, and leveraged exposure.",
            )
        return (
            f"Account structure review: score {scalar(data.get('structure_score'))}",
            f"Cash pressure: {scalar(data.get('cash_pressure'))}; redeployment readiness: {scalar(data.get('redeployment_readiness'))}.",
        )
    if rt == "cockpit_consistency_review":
        return (
            "Cockpit consistency review",
            f"Consistency status: {scalar(data.get('consistency_status'))}; UI readiness score: {scalar(data.get('ui_readiness_score'))}.",
        )
    if rt == "cockpit_view_model_contract":
        sections = data.get("view_model_sections", [])
        count = len(sections) if isinstance(sections, list) else 0
        return (
            "Cockpit view model contract",
            f"Contract version {scalar(data.get('contract_version'))} defines {count} top-level sections for future UI and downstream consumers.",
        )
    if rt == "cockpit_view_model_generation":
        summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
        return (
            "Cockpit view model generated",
            f"Generated {scalar(data.get('output_file'))} with {scalar(summary.get('active_rule_count'))} active rules and {scalar(summary.get('strategy_state_count'))} strategy states.",
        )
    if rt == "view_model_quality_gate_review":
        counts = data.get("expected_counts", {}) if isinstance(data.get("expected_counts"), dict) else {}
        return (
            "View model quality gates",
            f"Semantic validation status: {scalar(data.get('validation_status'))}; expected timeline warnings: {scalar(counts.get('timeline_warnings'))}.",
        )
    if rt == "cockpit_consumer_readiness_review":
        consumers = data.get("consumer_specific_readiness", [])
        count = len(consumers) if isinstance(consumers, list) else 0
        return (
            "Cockpit consumer readiness review",
            f"Consumer readiness result: {scalar(data.get('consumer_readiness_result'))}; reviewed {count} consumer types.",
        )
    if rt == "sync_delta_update":
        if "post-close-runtime-delta" in scalar(data.get("delta_id")):
            return (
                "Post-close runtime delta: latest active checkpoint",
                scalar(data.get("delta_reason")),
            )
        return (
            f"Sync delta: {scalar(data.get('delta_id'))}",
            scalar(data.get("delta_reason")),
        )
    if rt == "pending_command":
        return (
            f"Pending command: {scalar(data.get('command_id'))}",
            scalar(data.get("command_summary")),
        )
    return (
        f"Runtime record: {Path(record.relpath).name}",
        first_nonempty(data, ["summary", "notes", "rationale"], "Runtime record captured."),
    )


def state_before_after(record: LoadedRecord) -> tuple[str, str]:
    data = record.data
    rt = record.record_type
    if rt == "strategy_state":
        before = scalar(data.get("previous_state"), "")
        after = scalar(data.get("new_state") or data.get("health_state"), "")
        return before, after
    if rt == "trigger_execution_rule":
        return scalar(data.get("trigger_status"), ""), scalar(data.get("execution_status"), "")
    if rt == "execution_event":
        return scalar(data.get("execution_nature"), ""), scalar(data.get("action"), "")
    if rt == "sync_delta_update":
        return "prior sync or strategy-state assumption", "; ".join(list_of_strings(data.get("changed_fields")))
    if rt == "account_structure_review":
        return "", f"structure_score={scalar(data.get('structure_score'))}"
    if rt == "cockpit_consistency_review":
        return "", f"{scalar(data.get('consistency_status'))}; ui_readiness_score={scalar(data.get('ui_readiness_score'))}"
    if rt == "cockpit_view_model_contract":
        return "", f"contract_version={scalar(data.get('contract_version'))}; validation_status={scalar(data.get('validation_status'))}"
    if rt == "cockpit_view_model_generation":
        return "", f"output={scalar(data.get('output_file'))}; validation_status={scalar(data.get('validation_status'))}"
    if rt == "view_model_quality_gate_review":
        return "", f"quality_gate_version={scalar(data.get('quality_gate_version'))}; validation_status={scalar(data.get('validation_status'))}"
    if rt == "cockpit_consumer_readiness_review":
        return "", f"consumer_readiness_result={scalar(data.get('consumer_readiness_result'))}; recommended_next_phase={scalar(data.get('recommended_next_phase'))}"
    if rt == "pending_command":
        return "", f"{scalar(data.get('status'))}/{scalar(data.get('final_status'))}"
    return "", ""


def has_zec_closure(records: list[LoadedRecord]) -> bool:
    for record in records:
        if record.record_type in {"execution_event", "sync_delta_update", "strategy_state"}:
            text = json.dumps(record.data, ensure_ascii=False).lower()
            if "zec" in text and ("closed_profit_locked" in text or "close_bot" in text or "bot closed" in text):
                return True
    return False


def tags_for(record: LoadedRecord, zec_closure_exists: bool) -> list[str]:
    tags: list[str] = [record.record_type]
    text = json.dumps(record.data, ensure_ascii=False).lower()
    if "zec" in text:
        tags.append("zec")
    if "btc" in text:
        tags.append("btc")
    if "soxl" in text:
        tags.append("soxl")
    if "goog" in text:
        tags.append("goog")
    if "nvda" in text:
        tags.append("nvda")
    if "gld" in text:
        tags.append("gld")
    if "quote_source" in text:
        tags.append("quote_source_reconciliation")
    if record.record_type == "cockpit_consistency_review":
        tags.extend(["cockpit_consistency_review", "ui_readiness_review"])
    if record.record_type == "cockpit_view_model_contract":
        tags.extend(["cockpit_view_model_contract", "frontend_ready_contract", "non_trading_runtime_event"])
    if record.record_type == "cockpit_view_model_generation":
        tags.extend(["cockpit_view_model_generation", "frontend_ready_artifact", "non_trading_runtime_event"])
    if record.record_type == "view_model_quality_gate_review":
        tags.extend(["view_model_quality_gates", "semantic_validation", "non_trading_runtime_event"])
    if record.record_type == "cockpit_consumer_readiness_review":
        tags.extend(["cockpit_consumer_readiness", "consumer_contract_boundary", "non_trading_runtime_event"])
    if "near_trigger" in text and record.record_type != "cockpit_view_model_contract":
        tags.append("near_trigger")
    if "latest_active_checkpoint" in text:
        tags.append("latest_active_checkpoint")
    if "closed_profit_locked" in text or "close_bot" in text:
        tags.append("closed_profit_locked")
    if record.record_type == "strategy_state" and zec_closure_exists:
        if "zec" in text and "closed_profit_locked" not in text:
            tags.extend(["historical", "superseded", "superseded_by_zec_closure"])
    if record.record_type == "pending_command":
        tags.append("source_status")
        if "phase2_v3" in text:
            tags.append("historical_command_sample")
    if record.timestamp_source == "path_date":
        tags.append("timestamp_inferred_from_path")
    if record.timestamp_source == "unknown":
        tags.append("unknown_timestamp")
    return sorted(set(tags))


def build_event_id(record: LoadedRecord) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", record.relpath).strip("-").lower()
    return f"timeline-{base}"


def build_events(records: list[LoadedRecord]) -> list[dict[str, Any]]:
    zec_closure_exists = has_zec_closure(records)
    events: list[dict[str, Any]] = []

    for record in records:
        title, summary = title_and_summary(record)
        state_before, state_after = state_before_after(record)
        tags = tags_for(record, zec_closure_exists)
        if "superseded_by_zec_closure" in tags:
            summary = f"Historical ZEC state retained for traceability; superseded by the 2026-06-03 ZEC closure event. Original summary: {summary}"
            state_after = f"{state_after}; superseded_by=records/ldd/2026-06-03/zec_bot_closure_execution_20260603_0838.json"
        if record.record_type == "pending_command" and "historical_command_sample" in tags:
            summary = f"{summary} Source status is retained as a Command Intelligence example; later runtime work may have resolved the draft."

        events.append(
            {
                "timeline_event_id": build_event_id(record),
                "event_time": record.event_time,
                "event_type": event_type(record.record_type),
                "source_file": record.relpath,
                "source_record_type": record.record_type,
                "asset_or_module": asset_or_module(record.record_type, record.data),
                "title": title,
                "summary": summary,
                "state_before": state_before,
                "state_after": state_after,
                "supersedes_or_updates": list_of_strings(record.data.get("updates_or_supersedes")),
                "execution_evidence_level": evidence_level(record.data, record.record_type),
                "cockpit_priority": priority(record.record_type, record.data, tags),
                "tags": tags,
            }
        )

    return sorted(
        events,
        key=lambda event: (
            parse_time(event["event_time"]) is None,
            parse_time(event["event_time"]) or datetime.max,
            event["source_file"],
        ),
    )


def generated_at(events: list[dict[str, Any]]) -> str:
    known_times = [parse_time(event["event_time"]) for event in events]
    known_times = [item for item in known_times if item is not None]
    if not known_times:
        return "unknown"
    latest = max(known_times)
    return latest.isoformat()


def date_range(events: list[dict[str, Any]]) -> dict[str, str]:
    known_times = [parse_time(event["event_time"]) for event in events]
    known_times = [item for item in known_times if item is not None]
    if not known_times:
        return {"start": "unknown", "end": "unknown"}
    return {"start": min(known_times).isoformat(), "end": max(known_times).isoformat()}


def event_date(event: dict[str, Any]) -> str:
    time_value = event["event_time"]
    parsed = parse_time(time_value)
    if parsed is None:
        return "unknown"
    return parsed.date().isoformat()


def markdown_lines(events: list[dict[str, Any]], warnings: list[str]) -> list[str]:
    generated = generated_at(events)
    date_info = date_range(events)
    critical_high_count = sum(1 for event in events if event["cockpit_priority"] in {"critical", "high"})
    lines = [
        "# LDD Runtime Timeline",
        "",
        f"Generated timestamp: `{generated}`",
        "",
        "Generated by `scripts/generate_runtime_timeline.py` from local runtime records.",
        "",
        "## Summary",
        "",
        f"- Total events: `{len(events)}`",
        f"- Date range: `{date_info['start']}` -> `{date_info['end']}`",
        f"- Critical / high priority events: `{critical_high_count}`",
        f"- Warning count: `{len(warnings)}`",
        "- External APIs: not used",
        "- Execution source of truth: user-provided broker/Binance screenshots remain authoritative",
        "",
        "## Timeline",
        "",
    ]

    current_date = ""
    for event in events:
        group = event_date(event)
        if group != current_date:
            current_date = group
            lines.extend([f"### {group}", ""])
        lines.extend(
            [
                f"#### {event['event_time']} - {event['title']}",
                "",
                f"- event_type: `{event['event_type']}`",
                f"- asset_or_module: `{event['asset_or_module']}`",
                f"- cockpit_priority: `{event['cockpit_priority']}`",
                f"- source_file: `{event['source_file']}`",
                f"- summary: {event['summary']}",
            ]
        )
        if event["state_before"] or event["state_after"]:
            lines.append(f"- state_before: {event['state_before'] or 'n/a'}")
            lines.append(f"- state_after: {event['state_after'] or 'n/a'}")
        if event["supersedes_or_updates"]:
            lines.append("- supersedes_or_updates:")
            lines.extend([f"  - `{item}`" for item in event["supersedes_or_updates"]])
        lines.append(f"- tags: `{', '.join(event['tags'])}`")
        lines.append("")

    lines.extend(["## Warnings", ""])
    if warnings:
        lines.extend([f"- {warning}" for warning in warnings])
    else:
        lines.append("- No warnings.")
    lines.append("")
    return lines


def write_outputs(events: list[dict[str, Any]], warnings: list[str]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    COCKPIT_PATH.parent.mkdir(parents=True, exist_ok=True)

    REPORT_PATH.write_text("\n".join(markdown_lines(events, warnings)).rstrip() + "\n", encoding="utf-8")

    payload = {
        "generated_at": generated_at(events),
        "project": "LLM Daredevil Desk",
        "runtime_layer": "runtime_timeline",
        "version": "0.1",
        "source_root": "records/ldd",
        "event_count": len(events),
        "date_range": date_range(events),
        "events": events,
        "warnings": warnings,
    }
    COCKPIT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    records, warnings = collect_records()
    events = build_events(records)

    unknown_count = sum(1 for event in events if event["event_time"] == "unknown")
    if unknown_count:
        warnings.append(f"{unknown_count} timeline events have unknown timestamps and were placed last")

    write_outputs(events, warnings)

    print("Runtime timeline generated.")
    print(f"Events: {len(events)}")
    print(f"Warnings: {len(warnings)}")
    print("- reports/ldd/runtime_timeline.md")
    print("- cockpit/ldd/runtime_timeline.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
