#!/usr/bin/env python3
"""Generate a single LDD cockpit view model from existing cockpit summaries.

The generator is deterministic, file-based, and uses only local cockpit JSON
files. It does not call external APIs, infer live prices, or execute trades.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COCKPIT_DIR = REPO_ROOT / "cockpit" / "ldd"
MANIFEST_PATH = COCKPIT_DIR / "manifest.json"
OUTPUT_PATH = COCKPIT_DIR / "view_model.json"

PROJECT = "LLM Daredevil Desk"
VIEW_MODEL_VERSION = "0.1"
GENERATOR = "scripts/generate_cockpit_view_model.py"


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def scalar(value: Any, default: str = "unknown") -> str:
    if value is None or value == "":
        return default
    return str(value)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_sources() -> tuple[dict[str, dict[str, Any]], list[str]]:
    warnings: list[str] = []
    manifest, warning = read_json(MANIFEST_PATH)
    if warning:
        return {}, [warning]
    assert manifest is not None

    payloads: dict[str, dict[str, Any]] = {"manifest": manifest}
    files = as_dict(manifest.get("files"))

    for key, file_name in sorted(files.items()):
        if key == "view_model":
            continue
        if not isinstance(file_name, str):
            warnings.append(f"manifest files.{key} is not a string path")
            continue
        path = REPO_ROOT / file_name
        data, file_warning = read_json(path)
        if file_warning:
            warnings.append(file_warning)
            continue
        assert data is not None
        payloads[key] = data

    return payloads, warnings


def source_files(payloads: dict[str, dict[str, Any]]) -> list[str]:
    manifest = payloads.get("manifest", {})
    files = as_dict(manifest.get("files"))
    values = [
        file_name
        for key, file_name in files.items()
        if isinstance(file_name, str) and key != "view_model"
    ]
    values.append("cockpit/ldd/manifest.json")
    return sorted(set(values))


def build_positions(latest_state: dict[str, Any], strategy_states: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state_summary = as_dict(latest_state.get("state_summary"))
    us_equities = as_dict(state_summary.get("us_equities"))
    runtime = as_dict(state_summary.get("runtime"))

    closed_state = as_dict(runtime.get("position_states"))
    closed_positions: list[dict[str, Any]] = []
    for asset, state in sorted(closed_state.items()):
        if state == "closed_position":
            closed_positions.append(
                {
                    "asset": asset,
                    "position_state": "closed_position",
                    "quantity": "0",
                    "current_action": "no_readd",
                    "source_files": ["cockpit/ldd/latest_state.json"],
                    "tags": ["closed_position", "historical_cleanup", "prohibited_reentry"],
                }
            )

    for label in as_list(us_equities.get("closed_positions")):
        text = str(label).strip()
        if not text:
            continue
        parts = text.split(maxsplit=1)
        asset = parts[0]
        quantity = parts[1] if len(parts) > 1 else "0_or_not_applicable"
        if any(entry.get("asset") == asset for entry in closed_positions):
            continue
        closed_positions.append(
            {
                "asset": asset,
                "position_state": "closed_position",
                "quantity": quantity,
                "current_action": "no_readd / no reopening / no re-entry without a new approved rule",
                "source_files": ["cockpit/ldd/latest_state.json"],
                "tags": ["closed_position", "historical_cleanup", "prohibited_reentry"],
            }
        )

    active_positions: list[dict[str, Any]] = []
    for label in as_list(us_equities.get("key_positions")):
        text = str(label)
        asset = text.split()[0] if text else "unknown"
        if asset in closed_state and closed_state.get(asset) == "closed_position":
            continue
        active_positions.append(
            {
                "asset_or_position": text,
                "position_state": "active_position",
                "source_files": ["cockpit/ldd/latest_state.json"],
                "tags": ["current_position"],
            }
        )

    for item in as_list(strategy_states.get("strategy_states")):
        if not isinstance(item, dict):
            continue
        if item.get("status") == "closed":
            asset = scalar(item.get("asset_or_module"))
            if not any(entry.get("asset") == asset for entry in closed_positions):
                closed_positions.append(
                    {
                        "asset": asset,
                        "position_state": "closed_position",
                        "quantity": "0_or_not_applicable",
                        "current_action": scalar(item.get("next_required_action"), "No reopening."),
                        "source_files": as_list(item.get("source_files")),
                        "tags": sorted(set(["closed_position"] + [str(tag) for tag in as_list(item.get("tags"))])),
                    }
                )

    return active_positions, closed_positions


def build_risk_summary(latest_state: dict[str, Any], account_structure: dict[str, Any], active_rules: dict[str, Any]) -> dict[str, Any]:
    state_summary = as_dict(latest_state.get("state_summary"))
    us_equities = as_dict(state_summary.get("us_equities"))
    crypto = as_dict(state_summary.get("crypto"))
    sections = as_dict(account_structure.get("sections"))
    us_section = as_dict(sections.get("us_equities"))
    quality = as_dict(account_structure.get("quality_assessment"))

    rules = as_list(active_rules.get("rules"))
    return {
        "overall_status": scalar(quality.get("overall_status"), "core_position_defense_mode"),
        "open_risks": as_list(us_equities.get("open_risks")) + as_list(crypto.get("open_risks")),
        "risk_factors": as_list(quality.get("risk_factors")),
        "near_trigger_count": as_dict(active_rules.get("summary")).get("near_trigger_count", 0),
        "triggered_rules": [
            rule
            for rule in rules
            if isinstance(rule, dict) and rule.get("status") in {"triggered", "near_trigger", "awaiting_execution_confirmation"}
        ],
        "main_remaining_leveraged_etf_risk_valve": scalar(us_section.get("main_remaining_leveraged_risk_valve"), "GGLL"),
        "main_core_risk_watch": scalar(us_section.get("main_core_risk_watch"), "NVDA"),
        "gld_status": scalar(us_section.get("gld_status")),
        "btc_buyback_status": scalar(crypto.get("btc_buyback_status")),
        "zec_grid_status": scalar(crypto.get("zec_bot_status")),
    }


def collect_warnings(payloads: dict[str, dict[str, Any]], extra_warnings: list[str]) -> list[str]:
    warnings = list(extra_warnings)
    for name, payload in payloads.items():
        for warning in as_list(payload.get("warnings")):
            warnings.append(f"{name}: {warning}")
    return warnings


def build_view_model(payloads: dict[str, dict[str, Any]], load_warnings: list[str]) -> dict[str, Any]:
    manifest = payloads.get("manifest", {})
    latest_state = payloads.get("latest_state", {})
    account_structure = payloads.get("account_structure", {})
    active_rules = payloads.get("active_rules", {})
    strategy_states = payloads.get("strategy_states", {})
    timeline = payloads.get("runtime_timeline", {})
    pending_commands = payloads.get("pending_commands", {})
    memory_checkpoint = payloads.get("memory_checkpoint", {})

    latest_checkpoint = scalar(
        manifest.get("latest_active_checkpoint")
        or latest_state.get("latest_active_checkpoint")
        or timeline.get("generated_at")
    )
    state_summary = as_dict(latest_state.get("state_summary"))
    runtime = as_dict(state_summary.get("runtime"))
    sections = as_dict(account_structure.get("sections"))
    active_positions, closed_positions = build_positions(latest_state, strategy_states)
    warnings = collect_warnings(payloads, load_warnings)
    portfolio_mode = scalar(runtime.get("portfolio_mode"), "core_position_defense_mode")
    operating_mode = scalar(runtime.get("operating_mode"), portfolio_mode)

    return {
        "meta": {
            "project": scalar(manifest.get("project"), PROJECT),
            "view_model_version": VIEW_MODEL_VERSION,
            "generated_at": latest_checkpoint,
            "generator": GENERATOR,
            "source_manifest": "cockpit/ldd/manifest.json",
            "source_files": source_files(payloads),
            "contract_source": "records/ldd/2026-06-08/cockpit_view_model_contract_0844_sgt.json",
        },
        "checkpoint": {
            "latest_active_checkpoint": latest_checkpoint,
            "status": "latest_active_checkpoint_confirmed" if as_dict(manifest.get("status")).get("latest_checkpoint_confirmed") else "checkpoint_from_cockpit_summary",
            "source_files": ["cockpit/ldd/manifest.json", "cockpit/ldd/latest_state.json"],
        },
        "portfolio_mode": {
            "current": portfolio_mode,
            "operating_mode": operating_mode,
            "status": "active",
            "summary": f"Portfolio is in {portfolio_mode}.",
            "source_files": ["cockpit/ldd/latest_state.json", "cockpit/ldd/strategy_states.json"],
        },
        "account_overview": {
            "total_account": as_dict(state_summary.get("total_account")),
            "us_equities": as_dict(state_summary.get("us_equities")),
            "crypto": as_dict(state_summary.get("crypto")),
            "hong_kong_equities": as_dict(state_summary.get("hong_kong_equities")),
            "source_files": ["cockpit/ldd/latest_state.json"],
        },
        "account_sections": {
            "sections": sections,
            "quality_assessment": as_dict(account_structure.get("quality_assessment")),
            "source_files": ["cockpit/ldd/account_structure.json"],
        },
        "positions": active_positions,
        "closed_positions": closed_positions,
        "risk_summary": build_risk_summary(latest_state, account_structure, active_rules),
        "active_rules": as_list(active_rules.get("rules")),
        "strategy_states": as_list(strategy_states.get("strategy_states")),
        "timeline": {
            "generated_at": scalar(timeline.get("generated_at")),
            "event_count": timeline.get("event_count", 0),
            "warning_count": len(as_list(timeline.get("warnings"))),
            "date_range": as_dict(timeline.get("date_range")),
            "events": as_list(timeline.get("events")),
            "source_files": ["cockpit/ldd/runtime_timeline.json"],
        },
        "pending_commands": {
            "summary": as_dict(pending_commands.get("summary")),
            "commands": as_list(pending_commands.get("commands")),
            "execution_recognition_rule": scalar(pending_commands.get("execution_recognition_rule")),
            "source_files": ["cockpit/ldd/pending_commands.json"],
        },
        "memory_checkpoint": {
            "active_memory_status": scalar(memory_checkpoint.get("active_memory_status")),
            "current_checkpoint": scalar(memory_checkpoint.get("current_checkpoint")),
            "durable_rules": as_list(memory_checkpoint.get("durable_rules")),
            "superseded_snapshot_candidates": as_list(memory_checkpoint.get("superseded_snapshot_candidates")),
            "requires_user_approval": bool(memory_checkpoint.get("requires_user_approval", True)),
            "source_files": ["cockpit/ldd/memory_checkpoint.json"],
        },
        "warnings": warnings,
        "data_quality": {
            "external_api_connected": bool(as_dict(manifest.get("status")).get("external_api_connected", False)),
            "trading_automation_enabled": bool(as_dict(manifest.get("status")).get("trading_automation_enabled", False)),
            "ui_created": False,
            "frontend_app_created": False,
            "execution_source_of_truth": "User-provided broker/Binance screenshots remain authoritative.",
            "latest_checkpoint_confirmed": bool(as_dict(manifest.get("status")).get("latest_checkpoint_confirmed")),
            "timeline_warning_count": len(as_list(timeline.get("warnings"))),
            "active_rule_count": as_dict(active_rules.get("summary")).get("rule_count", len(as_list(active_rules.get("rules")))),
            "strategy_state_count": as_dict(strategy_states.get("summary")).get("strategy_state_count", len(as_list(strategy_states.get("strategy_states")))),
            "quote_type_tagging_required": True,
            "no_new_execution_reported_at_checkpoint": bool(runtime.get("no_new_execution_confirmed", False)),
            "confirmed_execution_reconciled": bool(runtime.get("confirmed_execution_reconciled", False)),
            "rule_compliance_price_outcome_separated": bool(runtime.get("rule_compliance_vs_price_outcome")),
            "runtime_status_conflict_resolved": as_dict(runtime.get("runtime_status_arbitration")).get("severity") == "non_blocking",
            "no_historical_checkpoint_reingested": True,
        },
    }


def main() -> int:
    payloads, warnings = load_sources()
    if "manifest" not in payloads:
        print("Cockpit view model generation failed.")
        for warning in warnings:
            print(f"- {warning}")
        return 1

    view_model = build_view_model(payloads, warnings)
    write_json(OUTPUT_PATH, view_model)

    data_quality = as_dict(view_model.get("data_quality"))
    print("Cockpit view model generated.")
    print(f"Latest active checkpoint: {as_dict(view_model.get('checkpoint')).get('latest_active_checkpoint')}")
    print(f"Warnings: {len(as_list(view_model.get('warnings')))}")
    print(f"Active rules: {data_quality.get('active_rule_count')}")
    print(f"Strategy states: {data_quality.get('strategy_state_count')}")
    print(f"Timeline events: {as_dict(view_model.get('timeline')).get('event_count')}")
    print(f"- {relpath(OUTPUT_PATH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
