#!/usr/bin/env python3
"""Generate local Markdown reports from Tianma Work OS runtime records.

The script uses only the Python standard library and reads local JSON files
under records/ldd. It does not call external services.
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
REPORT_DIR = REPO_ROOT / "reports" / "ldd"


@dataclass(frozen=True)
class RuntimeRecord:
    path: Path
    relpath: str
    kind: str
    data: dict[str, Any]
    timestamp_text: str
    timestamp: datetime | None


TIMESTAMP_FIELDS = [
    "snapshot_time",
    "last_review_time",
    "review_time",
    "sync_time",
    "event_time",
    "created_at",
    "check_time",
    "execution_time",
]


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


def classify_record(path: Path, data: dict[str, Any]) -> str | None:
    name = path.name
    if "portfolio_state" in name:
        return "portfolio_state"
    if "pending_" in name or "pending_command" in name:
        return "pending_command"
    if "rule_based_execution_review" in name:
        return "execution_review"
    if "volatility_execution_split" in name:
        return "volatility_split"
    if "sync_block_delta" in name or "sync_delta" in name or "delta_protocol" in name:
        return "delta_sync"
    if "rule_ledger_snapshot" in name:
        return "rule_ledger_snapshot"
    if "closure_execution" in name:
        return "execution_event"
    if "strategy_state" in name:
        return "strategy_state"
    if "trigger_rule" in name or "trigger_execution" in name:
        return "trigger_rule"
    if "account_structure_review" in name or "account_structure_score" in name or "account_structure_update" in name:
        return "account_structure_review"

    if "rule_id" in data and "trigger_condition" in data:
        return "trigger_rule"
    if "strategy_id" in data and "health_state" in data:
        return "strategy_state"
    if "review_id" in data and "structure_score" in data:
        return "account_structure_review"
    if "delta_id" in data:
        return "delta_sync"
    return None


def collect_records() -> tuple[list[RuntimeRecord], list[str]]:
    warnings: list[str] = []
    records: list[RuntimeRecord] = []

    if not RECORD_ROOT.exists():
        return records, [f"{RECORD_ROOT.relative_to(REPO_ROOT)} does not exist"]

    for path in sorted(RECORD_ROOT.rglob("*.json")):
        data, warning = load_json(path)
        if warning:
            warnings.append(warning)
            continue
        assert data is not None
        kind = classify_record(path, data)
        if kind is None:
            warnings.append(f"{path.relative_to(REPO_ROOT)} has no report mapping")
            continue
        timestamp_text, timestamp = first_timestamp(data)
        records.append(
            RuntimeRecord(
                path=path,
                relpath=str(path.relative_to(REPO_ROOT)),
                kind=kind,
                data=data,
                timestamp_text=timestamp_text,
                timestamp=timestamp,
            )
        )

    return records, warnings


def by_kind(records: list[RuntimeRecord], kind: str) -> list[RuntimeRecord]:
    return sorted(
        [record for record in records if record.kind == kind],
        key=lambda item: (item.timestamp or datetime.min, item.relpath),
    )


def latest(records: list[RuntimeRecord]) -> RuntimeRecord | None:
    if not records:
        return None
    return sorted(records, key=lambda item: (item.timestamp or datetime.min, item.relpath))[-1]


def latest_timestamp(records: list[RuntimeRecord]) -> str:
    item = latest([record for record in records if record.timestamp_text])
    return item.timestamp_text if item else "unknown"


def date_folders(records: list[RuntimeRecord]) -> list[str]:
    dates: set[str] = set()
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}")
    for record in records:
        for part in Path(record.relpath).parts:
            if pattern.fullmatch(part):
                dates.add(part)
    return sorted(dates)


def md_list(items: list[str], empty: str = "No records found.") -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- {item}" for item in items]


def source(record: RuntimeRecord | None) -> str:
    return f"`{record.relpath}`" if record else "`unknown`"


def scalar(value: Any, default: str = "unknown") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, float):
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return str(value)


def common_header(title: str, records: list[RuntimeRecord]) -> list[str]:
    return [
        f"# {title}",
        "",
        "Generated by `scripts/generate_runtime_report.py` from local runtime records.",
        "",
        f"- Source root: `records/ldd/`",
        f"- Latest record timestamp: `{latest_timestamp(records)}`",
        "- External APIs: not used",
        "- Execution source of truth: user-provided broker/Binance screenshots remain authoritative",
        "",
    ]


def trigger_entries(records: list[RuntimeRecord]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    top_level_assets: set[str] = set()
    for record in by_kind(records, "trigger_rule"):
        data = record.data
        asset_key = scalar(data.get("asset")).lower().replace("/usdt", "")
        top_level_assets.add(asset_key)
        entries.append(
            {
                "asset": scalar(data.get("asset")),
                "condition": scalar(data.get("trigger_condition")),
                "status": scalar(data.get("trigger_status") or data.get("execution_status")),
                "intended_action": scalar(data.get("intended_action") or data.get("next_action")),
                "latest_state": scalar(data.get("execution_result") or data.get("next_trigger_line")),
                "source": record.relpath,
                "sort": (record.timestamp or datetime.min, scalar(data.get("asset"))),
            }
        )

    for record in by_kind(records, "rule_ledger_snapshot"):
        for rule in record.data.get("rules", []):
            if not isinstance(rule, dict):
                continue
            asset_key = scalar(rule.get("asset")).lower().replace("/usdt", "")
            if asset_key in top_level_assets:
                continue
            entries.append(
                {
                    "asset": scalar(rule.get("asset")),
                    "condition": scalar(rule.get("trigger_condition")),
                    "status": scalar(rule.get("trigger_status") or rule.get("execution_status")),
                    "intended_action": scalar(rule.get("intended_action")),
                    "latest_state": scalar(rule.get("current_observed_value")),
                    "source": f"{record.relpath}#{scalar(rule.get('rule_id'))}",
                    "sort": (record.timestamp or datetime.min, scalar(rule.get("asset"))),
                }
            )

    return sorted(entries, key=lambda item: item["sort"])


def latest_account_review(records: list[RuntimeRecord], contains: str | None = None) -> RuntimeRecord | None:
    candidates = by_kind(records, "account_structure_review")
    if contains:
        needle = contains.lower()
        candidates = [item for item in candidates if needle in scalar(item.data.get("account")).lower()]
    return latest(candidates)


def write_report(filename: str, lines: list[str]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / filename
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_latest_runtime_report(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Latest LDD Runtime Report", records)
    portfolio = latest(by_kind(records, "portfolio_state"))
    zec_state = latest(
        [
            record
            for record in by_kind(records, "strategy_state")
            if "zec" in scalar(record.data.get("linked_asset")).lower()
        ]
    )
    execution = latest(by_kind(records, "execution_event"))
    account = latest_account_review(records)
    crypto_account = latest_account_review(records, "binance")
    pending = by_kind(records, "pending_command")

    lines.extend(["## Latest Record Dates", ""])
    lines.extend(md_list([f"`{item}`" for item in date_folders(records)]))
    lines.append("")

    lines.extend(["## Latest U.S. Account State", ""])
    if portfolio:
        assets = portfolio.data.get("total_visible_assets", {})
        notes = portfolio.data.get("notes", [])
        lines.extend(
            [
                f"- Snapshot time: `{scalar(portfolio.data.get('snapshot_time'))}`",
                f"- U.S. broker total assets: `{scalar(assets.get('us_broker_total_assets_usd'))} USD`",
                f"- U.S. stock section: `{scalar(assets.get('us_stock_section_usd'))} USD`",
                f"- U.S. holdings market value: `{scalar(assets.get('us_holdings_market_value_usd'))} USD`",
                f"- U.S. holding P/L: `{scalar(assets.get('us_holding_pl_usd'))} USD`",
                f"- U.S. day P/L: `{scalar(assets.get('us_day_pl_usd'))} USD`",
                f"- Source: `{portfolio.relpath}`",
            ]
        )
        if notes:
            lines.append("- Notes:")
            lines.extend([f"  - {item}" for item in notes])
    else:
        lines.append("- No portfolio state record found.")
    lines.append("")

    lines.extend(["## Latest Crypto Account State", ""])
    if portfolio:
        cash = portfolio.data.get("cash_balance", {})
        lines.extend(
            [
                f"- Portfolio snapshot crypto posture: {scalar(cash.get('crypto_account_posture'))}",
                f"- Binance USDT in portfolio snapshot: `{scalar(cash.get('binance_usdt'))}`",
            ]
        )
    if crypto_account:
        lines.extend(
            [
                f"- Latest crypto account review: {scalar(crypto_account.data.get('account'))}",
                f"- Cash pressure: {scalar(crypto_account.data.get('cash_pressure'))}",
                f"- Bot strategy risk: {scalar(crypto_account.data.get('bot_strategy_risk'))}",
                f"- Redeployment readiness: {scalar(crypto_account.data.get('redeployment_readiness'))}",
                f"- Source: `{crypto_account.relpath}`",
            ]
        )
    lines.append("")

    lines.extend(["## Latest ZEC Bot State", ""])
    if zec_state:
        residual = zec_state.data.get("residual_position", {})
        lines.extend(
            [
                f"- Health state: `{scalar(zec_state.data.get('health_state'))}`",
                f"- Current return: `{scalar(zec_state.data.get('current_return_pct'))}%`",
                f"- Recommended action: {scalar(zec_state.data.get('recommended_action'))}",
                f"- Residual ZEC: `{scalar(residual.get('quantity'))}`",
                f"- Source: `{zec_state.relpath}`",
            ]
        )
    else:
        lines.append("- No ZEC strategy-state record found.")
    lines.append("")

    lines.extend(["## Latest Major Execution Event", ""])
    if execution:
        trade = execution.data.get("trade", {})
        lines.extend(
            [
                f"- Event: {scalar(execution.data.get('execution_type'))}",
                f"- Asset: {scalar(execution.data.get('asset'))}",
                f"- Action: {scalar(execution.data.get('action'))}",
                f"- Time: `{scalar(execution.data.get('event_time'))}`",
                f"- Trade: {scalar(trade.get('side'))} `{scalar(trade.get('quantity'))}` {scalar(trade.get('symbol'))} at `{scalar(trade.get('price'))}`",
                f"- Source: `{execution.relpath}`",
            ]
        )
    else:
        lines.append("- No execution event record found.")
    lines.append("")

    lines.extend(["## Latest Account Structure Conclusion", ""])
    if account:
        lines.extend(
            [
                f"- Account: {scalar(account.data.get('account'))}",
                f"- Structure score: `{scalar(account.data.get('structure_score'))}`",
                f"- Rule compliance: {scalar(account.data.get('rule_compliance'))}",
                f"- Redeployment readiness: {scalar(account.data.get('redeployment_readiness'))}",
                f"- Source: `{account.relpath}`",
            ]
        )
    else:
        lines.append("- No account structure review found.")
    lines.append("")

    lines.extend(["## Pending Commands", ""])
    if pending:
        for record in pending:
            lines.extend(
                [
                    f"- `{scalar(record.data.get('command_id'))}`",
                    f"  - Status: `{scalar(record.data.get('status'))}` / `{scalar(record.data.get('final_status'))}`",
                    f"  - Summary: {scalar(record.data.get('command_summary'))}",
                    f"  - Source: `{record.relpath}`",
                ]
            )
    else:
        lines.append("- No pending command records found.")
    return lines


def generate_active_trigger_rules(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Active Trigger Rules", records)
    lines.extend(
        [
            "This report includes active and recently relevant trigger rules. Executed rules remain listed when they define the latest known state.",
            "",
        ]
    )
    for entry in trigger_entries(records):
        lines.extend(
            [
                f"## {entry['asset']}",
                "",
                f"- Trigger condition: {entry['condition']}",
                f"- Rule status: `{entry['status']}`",
                f"- Intended action: {entry['intended_action']}",
                f"- Latest known state: {entry['latest_state']}",
                f"- Source record: `{entry['source']}`",
                "",
            ]
        )
    if len(lines) <= len(common_header("Active Trigger Rules", records)) + 2:
        lines.append("- No trigger rules found.")
    return lines


def generate_strategy_state_summary(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Strategy State Summary", records)
    strategy_states = by_kind(records, "strategy_state")
    zec_state = latest([record for record in strategy_states if "zec" in scalar(record.data.get("linked_asset")).lower()])
    account = latest_account_review(records, "binance")
    portfolio = latest(by_kind(records, "portfolio_state"))

    lines.extend(["## Current Highlights", ""])
    if zec_state:
        lines.extend(
            [
                f"- ZEC bot: `{scalar(zec_state.data.get('health_state'))}` after the 2026-06-03 closure.",
                f"- ZEC action after execution: {scalar(zec_state.data.get('recommended_action_after_execution') or zec_state.data.get('recommended_action'))}",
            ]
        )
    lines.append("- BTC: waiting for the 75,500-76,000 stabilization/confirmation trigger; no buyback record exists.")
    lines.append("- Crypto account: USDT defensive / cash dominant according to account structure records.")
    lines.append("- U.S. historical positions: cleanup and risk-control phase remains active.")
    lines.append("- LDD new U.S. model strategy: no new position opened in current records.")
    lines.append("")

    lines.extend(["## Strategy Records", ""])
    if strategy_states:
        for record in strategy_states:
            lines.extend(
                [
                    f"### {scalar(record.data.get('strategy_id'))}",
                    "",
                    f"- Asset: {scalar(record.data.get('linked_asset'))}",
                    f"- Health state: `{scalar(record.data.get('health_state'))}`",
                    f"- Current return: `{scalar(record.data.get('current_return_pct'))}%`",
                    f"- Recommended action: {scalar(record.data.get('recommended_action'))}",
                    f"- Source: `{record.relpath}`",
                    "",
                ]
            )
    else:
        lines.append("- No strategy-state records found.")

    if account or portfolio:
        lines.extend(["## Supporting Account Context", ""])
        if account:
            lines.append(f"- Latest crypto structure review: `{account.relpath}`")
        if portfolio:
            lines.append(f"- Latest portfolio state: `{portfolio.relpath}`")
    return lines


def generate_pending_commands_summary(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Pending Commands Summary", records)
    pending = by_kind(records, "pending_command")

    lines.extend(
        [
            "## Command Intelligence Sample",
            "",
            "Phase 2 v1 -> v2 -> v3 demonstrates that pending command was not final command.",
            "",
            "- Newer LDD sync data superseded older drafted instructions.",
            "- Tianma Work OS should execute the latest valid command, not stale command drafts.",
            "",
        ]
    )

    lines.extend(["## Command Records", ""])
    if pending:
        for record in pending:
            feedback = record.data.get("execution_feedback", {})
            superseded = feedback.get("superseded_versions", []) if isinstance(feedback, dict) else []
            lines.extend(
                [
                    f"### {scalar(record.data.get('command_id'))}",
                    "",
                    f"- Status: `{scalar(record.data.get('status'))}`",
                    f"- Final status: `{scalar(record.data.get('final_status'))}`",
                    f"- Latest valid version: `{scalar(record.data.get('latest_valid_version'))}`",
                    f"- Waiting for: {scalar(record.data.get('waiting_for'))}",
                    f"- Revision reason: {scalar(record.data.get('revision_reason'))}",
                    f"- Source: `{record.relpath}`",
                ]
            )
            if superseded:
                lines.append("- Superseded versions:")
                for item in superseded:
                    if isinstance(item, dict):
                        lines.append(f"  - `{scalar(item.get('version'))}`: {scalar(item.get('status'))}; {scalar(item.get('reason'))}")
            lines.append("")
    else:
        lines.append("- No pending command records found.")
    return lines


def generate_account_structure_summary(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Account Structure Summary", records)
    reviews = by_kind(records, "account_structure_review")

    lines.extend(
        [
            "The account structure score evaluates cash pressure, leverage exposure, weak-position drag, historical-position cleanup, new-strategy separation, bot exposure, cash dominance, and redeployment readiness.",
            "",
        ]
    )

    if reviews:
        for record in reversed(reviews):
            data = record.data
            lines.extend(
                [
                    f"## {scalar(data.get('review_id'))}",
                    "",
                    f"- Snapshot time: `{scalar(data.get('snapshot_time'))}`",
                    f"- Account: {scalar(data.get('account'))}",
                    f"- Structure score: `{scalar(data.get('structure_score'))}`",
                    f"- Cash pressure: {scalar(data.get('cash_pressure'))}",
                    f"- Leverage exposure: {scalar(data.get('leverage_risk'))}",
                    f"- Weak-position drag: {scalar(data.get('weak_position_drag'))}",
                    f"- Historical cleanup / legacy risk: {scalar(data.get('legacy_position_risk'))}",
                    f"- Bot exposure: {scalar(data.get('bot_strategy_risk'))}",
                    f"- Redeployment readiness: {scalar(data.get('redeployment_readiness'))}",
                    f"- Source: `{record.relpath}`",
                    "",
                ]
            )
            findings = data.get("key_findings", [])
            if findings:
                lines.append("Key findings:")
                lines.extend([f"- {item}" for item in findings])
                lines.append("")
    else:
        lines.append("- No account structure review records found.")

    lines.extend(
        [
            "## ZEC Closure Impact",
            "",
            "The 2026-06-03 ZEC bot closure is account-structure positive because it reduced active bot exposure, strengthened USDT cash dominance, and converted floating profit risk into a more defensive cash-like state.",
        ]
    )
    return lines


def generate_execution_review_summary(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Execution Review Summary", records)
    reviews = by_kind(records, "execution_review")

    lines.extend(
        [
            "Execution correctness should be judged by rule compliance and account-risk improvement, not only short-term price movement.",
            "",
        ]
    )

    if reviews:
        for record in reviews:
            data = record.data
            lines.extend(
                [
                    f"## {scalar(data.get('review_id'))}",
                    "",
                    f"- Asset: {scalar(data.get('asset'))}",
                    f"- Position tag: {scalar(data.get('position_tag'))}",
                    f"- Review time: `{scalar(data.get('review_time'))}`",
                    f"- Intended rule: {scalar(data.get('intended_rule'))}",
                    f"- Actual execution: {scalar(data.get('actual_execution'))}",
                    f"- Rule compliance score: `{scalar(data.get('rule_compliance_score'))}`",
                    f"- Account risk improvement: {scalar(data.get('account_risk_improvement'))}",
                    f"- Short-term price outcome: {scalar(data.get('short_term_price_outcome'))}",
                    f"- Review conclusion: {scalar(data.get('review_conclusion'))}",
                    f"- Source: `{record.relpath}`",
                    "",
                ]
            )
    else:
        lines.append("- No rule-based execution review records found.")
    return lines


def generate_delta_sync_summary(records: list[RuntimeRecord]) -> list[str]:
    lines = common_header("Delta Sync Summary", records)
    deltas = by_kind(records, "delta_sync")

    lines.extend(
        [
            "Delta sync records capture updates that arrive after a prior sync block or strategy-state assumption.",
            "",
            "Priority order:",
            "",
            "```text",
            "actual execution",
            "-> account screenshot",
            "-> bot state",
            "-> market interpretation",
            "-> strategy forecast",
            "```",
            "",
        ]
    )

    if deltas:
        for record in deltas:
            data = record.data
            lines.extend(
                [
                    f"## {scalar(data.get('delta_id'))}",
                    "",
                    f"- Sync time: `{scalar(data.get('sync_time'))}`",
                    f"- Source cutoff time: `{scalar(data.get('source_cutoff_time'))}`",
                    f"- Sync status: `{scalar(data.get('sync_status'))}`",
                    f"- Delta reason: {scalar(data.get('delta_reason'))}",
                    f"- Source: `{record.relpath}`",
                    "",
                    "Updates or supersedes:",
                ]
            )
            lines.extend(md_list([f"`{item}`" for item in data.get("updates_or_supersedes", [])]))
            lines.append("")
            lines.append("Included events:")
            lines.extend(md_list([str(item) for item in data.get("included_events", [])]))
            lines.append("")
            lines.append("Pending events:")
            lines.extend(md_list([str(item) for item in data.get("pending_events", [])]))
            lines.append("")
    else:
        lines.append("- No delta sync records found.")
    return lines


def main() -> int:
    records, warnings = collect_records()

    reports = {
        "latest_runtime_report.md": generate_latest_runtime_report(records),
        "active_trigger_rules.md": generate_active_trigger_rules(records),
        "strategy_state_summary.md": generate_strategy_state_summary(records),
        "pending_commands_summary.md": generate_pending_commands_summary(records),
        "account_structure_summary.md": generate_account_structure_summary(records),
        "execution_review_summary.md": generate_execution_review_summary(records),
        "delta_sync_summary.md": generate_delta_sync_summary(records),
    }

    for filename, lines in reports.items():
        write_report(filename, lines)

    print("Runtime reports generated.")
    print(f"Records loaded: {len(records)}")
    print(f"Reports written: {len(reports)}")
    for filename in sorted(reports):
        print(f"- reports/ldd/{filename}")

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
