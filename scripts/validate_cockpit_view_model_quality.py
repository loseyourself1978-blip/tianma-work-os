#!/usr/bin/env python3
"""Run semantic quality gates against the generated LDD cockpit view model.

The checks are deterministic, local-only, and intentionally separate from
JSON-schema validation. Blocking contradictions return a non-zero exit code.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COCKPIT_DIR = REPO_ROOT / "cockpit" / "ldd"
VIEW_MODEL_PATH = COCKPIT_DIR / "view_model.json"
MANIFEST_PATH = COCKPIT_DIR / "manifest.json"
LATEST_STATE_PATH = COCKPIT_DIR / "latest_state.json"
TIMELINE_PATH = COCKPIT_DIR / "runtime_timeline.json"

EXPECTED_CHECKPOINT = "2026-06-09T08:28:00+08:00"
EXPECTED_PORTFOLIO_MODE = "core_position_defense_mode"
REQUIRED_TOP_LEVEL = [
    "meta",
    "checkpoint",
    "portfolio_mode",
    "account_overview",
    "account_sections",
    "positions",
    "closed_positions",
    "risk_summary",
    "active_rules",
    "strategy_states",
    "timeline",
    "pending_commands",
    "memory_checkpoint",
    "warnings",
    "data_quality",
]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.relative_to(REPO_ROOT)} cannot be loaded: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(REPO_ROOT)} is not a JSON object")
    return value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalized_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


class GateResults:
    def __init__(self) -> None:
        self.checked = 0
        self.passes: list[str] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def gate(self, name: str, condition: bool, detail: str) -> None:
        self.checked += 1
        if condition:
            self.passes.append(f"{name}: {detail}")
        else:
            self.failures.append(f"{name}: {detail}")

    def warn(self, name: str, detail: str) -> None:
        self.warnings.append(f"{name}: {detail}")


def represented_prohibition(view_model: dict[str, Any], symbol: str) -> tuple[bool, bool]:
    symbol_upper = symbol.upper()
    evidence: list[str] = []

    for item in as_list(view_model.get("closed_positions")):
        if not isinstance(item, dict) or str(item.get("asset", "")).upper() != symbol_upper:
            continue
        evidence.append(normalized_text(item))

    for item in as_list(view_model.get("active_rules")):
        if not isinstance(item, dict) or symbol_upper not in normalized_text(item).upper():
            continue
        evidence.append(normalized_text(item))

    if not evidence:
        return False, False

    prohibition_terms = (
        "no_readd",
        "no reopening",
        "no re-entry",
        "no-reentry",
        "do not chase",
        "prohibited_reentry",
        "new approved rule before any re-entry",
    )
    return True, any(any(term in item for term in prohibition_terms) for item in evidence)


def check_required_sections(view_model: dict[str, Any], results: GateResults) -> None:
    missing = [key for key in REQUIRED_TOP_LEVEL if key not in view_model]
    results.gate(
        "required_sections",
        not missing,
        "all required view-model sections are present"
        if not missing
        else f"missing required sections: {', '.join(missing)}",
    )


def check_checkpoint(
    view_model: dict[str, Any],
    manifest: dict[str, Any],
    latest_state: dict[str, Any],
    results: GateResults,
) -> None:
    values = {
        "view_model": as_dict(view_model.get("checkpoint")).get("latest_active_checkpoint"),
        "manifest": manifest.get("latest_active_checkpoint"),
        "latest_state": latest_state.get("latest_active_checkpoint"),
    }
    results.gate(
        "checkpoint_consistency",
        all(value == EXPECTED_CHECKPOINT for value in values.values()),
        f"all cockpit checkpoints equal {EXPECTED_CHECKPOINT}"
        if all(value == EXPECTED_CHECKPOINT for value in values.values())
        else f"inconsistent checkpoint values: {values}",
    )


def check_portfolio_mode(view_model: dict[str, Any], results: GateResults) -> None:
    current = as_dict(view_model.get("portfolio_mode")).get("current")
    results.gate(
        "portfolio_mode",
        current == EXPECTED_PORTFOLIO_MODE,
        f"portfolio mode is {current!r}; expected {EXPECTED_PORTFOLIO_MODE!r}",
    )


def check_timeline(
    view_model: dict[str, Any],
    latest_state: dict[str, Any],
    timeline: dict[str, Any],
    results: GateResults,
) -> None:
    view_timeline = as_dict(view_model.get("timeline"))
    latest_runtime = as_dict(as_dict(latest_state.get("state_summary")).get("runtime"))
    counts = {
        "view_model": view_timeline.get("event_count"),
        "latest_state": latest_runtime.get("timeline_event_count"),
        "runtime_timeline": timeline.get("event_count"),
    }
    warning_counts = {
        "view_model": view_timeline.get("warning_count"),
        "data_quality": as_dict(view_model.get("data_quality")).get("timeline_warning_count"),
        "runtime_timeline": len(as_list(timeline.get("warnings"))),
    }
    results.gate(
        "timeline_count",
        len(set(counts.values())) == 1 and None not in counts.values(),
        f"timeline event counts match: {counts}"
        if len(set(counts.values())) == 1 and None not in counts.values()
        else f"timeline event counts differ: {counts}",
    )
    results.gate(
        "timeline_warnings",
        all(value == 0 for value in warning_counts.values()),
        f"timeline warning counts are zero: {warning_counts}"
        if all(value == 0 for value in warning_counts.values())
        else f"timeline warnings detected: {warning_counts}",
    )


def check_closed_positions(view_model: dict[str, Any], results: GateResults) -> None:
    closed = {
        str(item.get("asset", "")).upper(): item
        for item in as_list(view_model.get("closed_positions"))
        if isinstance(item, dict)
    }
    active_text = " ".join(
        str(item.get("asset_or_position", "")).upper()
        for item in as_list(view_model.get("positions"))
        if isinstance(item, dict)
    )
    problems: list[str] = []
    for symbol in ["SOXL", "UGL", "INTC"]:
        item = closed.get(symbol)
        if not item:
            problems.append(f"{symbol} missing from closed_positions")
            continue
        if item.get("position_state") != "closed_position":
            problems.append(f"{symbol} state is {item.get('position_state')!r}")
        if not str(item.get("quantity", "")).startswith("0"):
            problems.append(f"{symbol} quantity is {item.get('quantity')!r}")
        if re.search(rf"\b{re.escape(symbol)}\b", active_text):
            problems.append(f"{symbol} appears in active positions")
    results.gate(
        "closed_positions",
        not problems,
        "SOXL, UGL, and INTC remain closed at zero and absent from active positions"
        if not problems
        else "; ".join(problems),
    )


def check_prohibitions(view_model: dict[str, Any], results: GateResults) -> None:
    failures: list[str] = []
    for symbol in ["SOXL", "SOXS", "NVDD", "NVDS", "GDXU", "TSLQ"]:
        represented, prohibited = represented_prohibition(view_model, symbol)
        if represented and not prohibited:
            failures.append(f"{symbol} is represented without no-reentry/no-chase evidence")
        elif not represented:
            results.warn("prohibition_coverage", f"{symbol} is not represented in the current view model")
    results.gate(
        "no_reentry_prohibitions",
        not failures,
        "represented leveraged cleanup/inverse products are not buy candidates"
        if not failures
        else "; ".join(failures),
    )


def check_risk_roles(view_model: dict[str, Any], results: GateResults) -> None:
    risk = as_dict(view_model.get("risk_summary"))
    results.gate(
        "leveraged_risk",
        risk.get("main_remaining_leveraged_etf_risk_valve") == "GGLL",
        f"main remaining leveraged ETF risk valve is {risk.get('main_remaining_leveraged_etf_risk_valve')!r}",
    )
    results.gate(
        "core_risk",
        risk.get("main_core_risk_watch") == "NVDA",
        f"main core-risk watch is {risk.get('main_core_risk_watch')!r}",
    )


def check_gld(view_model: dict[str, Any], results: GateResults) -> None:
    value = str(as_dict(view_model.get("risk_summary")).get("gld_status", ""))
    lower = value.lower()
    required = all(term in lower for term in ["ordinary", "concentration", "risk-line"])
    stale = "ugl-linked protection" in lower and "not" not in lower and "no longer" not in lower
    results.gate(
        "gld_rule",
        required and not stale,
        f"GLD status is {value!r}",
    )


def check_crypto(view_model: dict[str, Any], results: GateResults) -> None:
    crypto = as_dict(as_dict(view_model.get("account_overview")).get("crypto"))
    risk = as_dict(view_model.get("risk_summary"))
    posture = str(crypto.get("cash_posture", "")).lower()
    btc = str(risk.get("btc_buyback_status", "")).lower()
    zec = str(risk.get("zec_grid_status", "")).lower()
    problems: list[str] = []
    if "usdt" not in posture or "dominant" not in posture:
        problems.append("crypto posture is not USDT-dominant")
    if "not triggered" not in btc or "75,500" not in btc or "76,000" not in btc:
        problems.append("BTC inactive 75,500-76,000 trigger is not preserved")
    if "closed" not in zec or "profit" not in zec or ("no" not in zec and "do not" not in zec):
        problems.append("ZEC closed/profit-locked/no-reopen state is not preserved")
    results.gate(
        "crypto_defense",
        not problems,
        "USDT defense, inactive BTC buyback, and closed ZEC grid are preserved"
        if not problems
        else "; ".join(problems),
    )


def check_data_quality(view_model: dict[str, Any], results: GateResults) -> None:
    quality = as_dict(view_model.get("data_quality"))
    problems: list[str] = []
    if not isinstance(view_model.get("warnings"), list):
        problems.append("warnings is not an array")
    if not quality:
        problems.append("data_quality is missing or empty")
    if quality.get("latest_checkpoint_confirmed") is not True:
        problems.append("latest checkpoint is not confirmed")
    if quality.get("no_historical_checkpoint_reingested") is not True:
        problems.append("historical checkpoint re-ingestion guard is not confirmed")
    results.gate(
        "data_quality",
        not problems,
        "warning and data-quality sections are present with checkpoint guards"
        if not problems
        else "; ".join(problems),
    )


def check_ui_safety(view_model: dict[str, Any], results: GateResults) -> None:
    quality = as_dict(view_model.get("data_quality"))
    text = normalized_text(view_model)
    credential_patterns = [
        r"\bapi[_ -]?key\s*[:=]\s*[\"']?[a-z0-9_\-]{12,}",
        r"\bpassword\s*[:=]\s*[\"']?\S{8,}",
        r"\bbearer\s+[a-z0-9._\-]{12,}",
        r"-----begin (?:rsa |ec |openssh )?private key-----",
    ]
    automation_phrases = [
        "automated trade execution enabled",
        "trading automation enabled",
        "live order placement enabled",
        "auto-execute trades",
        "automatically place orders",
    ]
    problems: list[str] = []
    if quality.get("external_api_connected") is not False:
        problems.append("external_api_connected must be false")
    if quality.get("trading_automation_enabled") is not False:
        problems.append("trading_automation_enabled must be false")
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in credential_patterns):
        problems.append("credential-like material detected")
    if any(phrase in text for phrase in automation_phrases):
        problems.append("automated execution implication detected")
    results.gate(
        "ui_safety",
        not problems,
        "no credentials, live API connection, or automated execution implication detected"
        if not problems
        else "; ".join(problems),
    )


def main() -> int:
    results = GateResults()
    try:
        view_model = load_json(VIEW_MODEL_PATH)
        manifest = load_json(MANIFEST_PATH)
        latest_state = load_json(LATEST_STATE_PATH)
        timeline = load_json(TIMELINE_PATH)
    except ValueError as exc:
        print("View model quality gates failed.")
        print(f"FAIL input_files: {exc}")
        print("Blocking failures: 1")
        print("Warnings: 0")
        return 1

    check_required_sections(view_model, results)
    check_checkpoint(view_model, manifest, latest_state, results)
    check_portfolio_mode(view_model, results)
    check_timeline(view_model, latest_state, timeline, results)
    check_closed_positions(view_model, results)
    check_prohibitions(view_model, results)
    check_risk_roles(view_model, results)
    check_gld(view_model, results)
    check_crypto(view_model, results)
    check_data_quality(view_model, results)
    check_ui_safety(view_model, results)

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.warnings:
        print(f"WARN {item}")
    for item in results.failures:
        print(f"FAIL {item}")

    print()
    if results.failures:
        print("View model quality gates failed.")
    elif results.warnings:
        print("View model quality gates passed with warnings.")
    else:
        print("View model quality gates passed.")
    print(f"Gates checked: {results.checked}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
