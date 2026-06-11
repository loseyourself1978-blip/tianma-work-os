#!/usr/bin/env python3
"""Validate LDD mock consumer fixtures without mutating source artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
COCKPIT_DIR = REPO_ROOT / "cockpit" / "ldd"
MOCK_DIR = REPO_ROOT / "mock_consumers" / "ldd"
MANIFEST_PATH = COCKPIT_DIR / "manifest.json"
VIEW_MODEL_PATH = COCKPIT_DIR / "view_model.json"

EXPECTED_CHECKPOINT = "2026-06-11T08:10:00+08:00"
EXPECTED_PORTFOLIO_MODE = "core_position_defense_mode"
EXPECTED_SOURCE_VIEW_MODEL = "cockpit/ldd/view_model.json"

FIXTURE_PATHS = [
    MOCK_DIR / "view_model_snapshot.json",
    MOCK_DIR / "ui_boundary_sample.json",
    MOCK_DIR / "report_consumer_sample.json",
    MOCK_DIR / "api_consumer_sample.json",
    MOCK_DIR / "mobile_consumer_sample.json",
    MOCK_DIR / "ai_board_consumer_sample.json",
    MOCK_DIR / "consumer_contract_test_matrix.json",
    MOCK_DIR / "privacy_boundary_sample.json",
]

SENSITIVE_VALUE_KEYS = {
    "api_key",
    "api_keys",
    "access_token",
    "auth_token",
    "password",
    "login_credential",
    "login_credentials",
    "broker_account_number",
    "binance_account_number",
    "customer_identifier",
    "personal_identifier",
    "secret",
}

EXECUTION_CALL_KEYS = {
    "auto_buy",
    "auto_sell",
    "execute_order",
    "place_order",
    "submit_order",
    "broker_trade",
    "binance_trade",
}

EXECUTION_CALL_PATTERN = re.compile(
    r"\b(auto_buy|auto_sell|execute_order|place_order|submit_order|"
    r"broker_trade|binance_trade)\s*\(",
    re.IGNORECASE,
)

CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|secret)\b"
    r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{12,}",
    re.IGNORECASE,
)


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{relative(path)} cannot be loaded: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{relative(path)} must contain a JSON object")
    return value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalized_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk_values(value: Any, path: str = "$") -> list[tuple[str, str, Any]]:
    values: list[tuple[str, str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            values.append((child_path, str(key), child))
            values.extend(walk_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            values.extend(walk_values(child, f"{path}[{index}]"))
    return values


class Results:
    def __init__(self) -> None:
        self.checked = 0
        self.passes: list[str] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, condition: bool, detail: str) -> None:
        self.checked += 1
        if condition:
            self.passes.append(f"{name}: {detail}")
        else:
            self.failures.append(f"{name}: {detail}")


def check_fixture_presence(
    documents: dict[Path, dict[str, Any]],
    load_failures: list[str],
    results: Results,
) -> None:
    results.check(
        "fixture_presence",
        len(documents) == len(FIXTURE_PATHS) and not load_failures,
        f"{len(documents)}/{len(FIXTURE_PATHS)} required fixtures loaded"
        if not load_failures
        else "; ".join(load_failures),
    )


def check_checkpoint_and_mode(
    view_model: dict[str, Any],
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    checkpoint_values = {
        "view_model": as_dict(view_model.get("checkpoint")).get("latest_active_checkpoint"),
        "snapshot": documents.get(MOCK_DIR / "view_model_snapshot.json", {}).get("latest_checkpoint"),
        "api_sample": as_dict(
            documents.get(MOCK_DIR / "api_consumer_sample.json", {}).get("sample_response")
        ).get("source_checkpoint"),
        "matrix": documents.get(MOCK_DIR / "consumer_contract_test_matrix.json", {}).get(
            "baseline_checkpoint"
        ),
    }
    mode_values = {
        "view_model": as_dict(view_model.get("portfolio_mode")).get("current"),
        "snapshot": documents.get(MOCK_DIR / "view_model_snapshot.json", {}).get("portfolio_mode"),
        "api_sample": as_dict(
            documents.get(MOCK_DIR / "api_consumer_sample.json", {}).get("sample_response")
        ).get("portfolio_mode"),
        "matrix": documents.get(MOCK_DIR / "consumer_contract_test_matrix.json", {}).get(
            "portfolio_mode"
        ),
    }
    source_problems = [
        relative(path)
        for path, document in documents.items()
        if document.get("source_view_model") != EXPECTED_SOURCE_VIEW_MODEL
    ]
    valid = (
        all(value == EXPECTED_CHECKPOINT for value in checkpoint_values.values())
        and all(value == EXPECTED_PORTFOLIO_MODE for value in mode_values.values())
        and not source_problems
    )
    detail = (
        f"checkpoint={EXPECTED_CHECKPOINT}; mode={EXPECTED_PORTFOLIO_MODE}; all fixtures reference the view model"
        if valid
        else f"checkpoints={checkpoint_values}; modes={mode_values}; bad_sources={source_problems}"
    )
    results.check("checkpoint_and_mode_integrity", valid, detail)


def check_manifest(
    manifest: dict[str, Any],
    view_model: dict[str, Any],
    results: Results,
) -> None:
    files = as_dict(manifest.get("files"))
    valid = (
        files.get("view_model") == EXPECTED_SOURCE_VIEW_MODEL
        and VIEW_MODEL_PATH.exists()
        and as_dict(view_model.get("checkpoint")).get("latest_active_checkpoint")
        == manifest.get("latest_active_checkpoint")
    )
    results.check(
        "manifest_integrity",
        valid,
        "manifest references the existing view model at the current checkpoint"
        if valid
        else f"manifest view_model={files.get('view_model')!r}; exists={VIEW_MODEL_PATH.exists()}",
    )


def check_no_live_data(
    view_model: dict[str, Any],
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    problems: list[str] = []
    all_documents = {VIEW_MODEL_PATH: view_model, **documents}
    false_boundary_keys = {
        "external_api_connected",
        "broker_api_connected",
        "binance_api_connected",
        "trading_automation_enabled",
        "automated_execution",
        "trade_submission",
        "live_market_data",
        "live_execution_quote",
        "mock_samples_are_live_data",
    }
    for path, document in all_documents.items():
        for json_path, key, value in walk_values(document):
            if key in false_boundary_keys and value is not False:
                problems.append(f"{relative(path)} {json_path} must be false")

    api_sample = documents.get(MOCK_DIR / "api_consumer_sample.json", {})
    if api_sample.get("implementation_status") != "not_implemented":
        problems.append("api_consumer_sample implementation_status must be not_implemented")
    if api_sample.get("method_boundary") != "read_only_get_concept":
        problems.append("api_consumer_sample must remain a read-only concept")

    results.check(
        "no_live_data_boundary",
        not problems,
        "fixtures declare no live API, broker, Binance, market-data, or execution connection"
        if not problems
        else "; ".join(problems),
    )


def check_no_automation(
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    problems: list[str] = []
    for path, document in documents.items():
        for json_path, key, value in walk_values(document):
            if key.lower() in EXECUTION_CALL_KEYS:
                problems.append(f"{relative(path)} contains executable field {json_path}")
            if isinstance(value, str) and EXECUTION_CALL_PATTERN.search(value):
                problems.append(f"{relative(path)} contains execution-call syntax at {json_path}")

    ai_policy = as_dict(
        documents.get(MOCK_DIR / "ai_board_consumer_sample.json", {}).get("execution_policy")
    )
    if ai_policy.get("automated_execution") is not False or ai_policy.get("trade_submission") is not False:
        problems.append("AI Board execution policy is not explicitly read-only")

    results.check(
        "no_automation_boundary",
        not problems,
        "no executable trading calls or automated execution paths are present"
        if not problems
        else "; ".join(problems),
    )


def check_privacy(
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    problems: list[str] = []
    for path, document in documents.items():
        for json_path, key, value in walk_values(document):
            if key.lower() in SENSITIVE_VALUE_KEYS and value not in (None, "", [], {}):
                problems.append(f"{relative(path)} exposes sensitive value at {json_path}")
            if isinstance(value, str) and CREDENTIAL_ASSIGNMENT_PATTERN.search(value):
                problems.append(f"{relative(path)} resembles a credential assignment at {json_path}")

    privacy = documents.get(MOCK_DIR / "privacy_boundary_sample.json", {})
    categories = as_dict(privacy.get("categories"))
    required = {
        "public_safe_fields",
        "internal_only_fields",
        "sensitive_account_fields",
        "execution_sensitive_fields",
        "never_expose_fields",
    }
    missing = sorted(required - set(categories))
    if missing:
        problems.append(f"privacy boundary categories missing: {', '.join(missing)}")

    results.check(
        "privacy_boundary",
        not problems,
        "no credential values or raw private identifiers are present; privacy categories are complete"
        if not problems
        else "; ".join(problems),
    )


def check_rule_interpretation(
    view_model: dict[str, Any],
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    snapshot = documents.get(MOCK_DIR / "view_model_snapshot.json", {})
    closed = {
        str(item.get("asset", "")).upper(): item
        for item in as_list(snapshot.get("closed_positions"))
        if isinstance(item, dict)
    }
    required_closed = {"GLD", "SOXL", "UGL", "INTC", "SOXS", "TSLQ", "GDXU"}
    closed_valid = required_closed.issubset(closed) and all(
        closed[symbol].get("state") == "closed_position"
        and closed[symbol].get("reentry") == "prohibited"
        for symbol in required_closed
    )
    risk = as_dict(snapshot.get("risk_summary"))
    gld = as_dict(risk.get("GLD"))
    nvda = as_dict(risk.get("NVDA"))
    goog = as_dict(risk.get("GOOG_GGLL"))
    view_risk = as_dict(view_model.get("risk_summary"))
    valid = (
        closed_valid
        and gld.get("rule_compliance_result") == "confirmed_execution_closed_position"
        and gld.get("position_after") == 0
        and nvda.get("position_after") == 10
        and nvda.get("next_protection_level") == 198
        and goog.get("goog_defense_level") == 355
        and goog.get("ggll_role") == "main_remaining_leveraged_etf_risk_valve"
        and goog.get("ggll_position_after") == 5
        and view_risk.get("main_core_risk_watch") == "NVDA"
    )
    results.check(
        "rule_interpretation_boundary",
        valid,
        "closed/no-reentry, GLD/NVDA/GGLL execution reconciliation, and GOOG/GGLL risk roles are preserved"
        if valid
        else "one or more rule-interpretation boundaries are inconsistent",
    )


def check_pl_and_opportunity_cost(
    view_model: dict[str, Any],
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    sections = as_dict(as_dict(view_model.get("account_sections")).get("sections"))
    required_sections = {
        "total_account",
        "us_equities",
        "hong_kong_equities",
        "crypto_spot",
        "historical_cleanup",
        "active_risk_non_execution",
        "closed_position_opportunity_cost",
    }
    matrix = documents.get(MOCK_DIR / "consumer_contract_test_matrix.json", {})
    dimensions = set(str(item) for item in as_list(matrix.get("test_dimensions")))
    required_dimensions = {
        "active_vs_historical_pl_separation",
        "rule_compliance_vs_opportunity_cost",
        "hk_high_profit_protection_separation",
    }
    valid = required_sections.issubset(sections) and required_dimensions.issubset(dimensions)
    results.check(
        "pl_and_opportunity_cost_separation",
        valid,
        "section P/L, HK protection, historical cleanup, opportunity cost, and compliance remain separate"
        if valid
        else "required account sections or contract dimensions are missing",
    )


def check_quote_types(view_model: dict[str, Any], results: Results) -> None:
    sections = as_dict(as_dict(view_model.get("account_sections")).get("sections"))
    quote_quality = as_dict(sections.get("quote_quality"))
    quote_types = set(str(item) for item in as_list(quote_quality.get("required_quote_types")))
    required = {
        "regular_close",
        "after_hours_price",
        "broker_holding_valuation",
        "executable_quote",
        "active_position_valuation",
    }
    valid = required.issubset(quote_types) and as_dict(view_model.get("data_quality")).get(
        "quote_type_tagging_required"
    ) is True
    results.check(
        "quote_type_boundary",
        valid,
        "close, after-hours, broker valuation, executable, and active-position quote types remain distinct"
        if valid
        else f"missing quote types: {sorted(required - quote_types)}",
    )


def check_contract_matrix(
    documents: dict[Path, dict[str, Any]],
    results: Results,
) -> None:
    matrix = documents.get(MOCK_DIR / "consumer_contract_test_matrix.json", {})
    summary = as_dict(matrix.get("pass_fail_summary"))
    cases = as_list(matrix.get("test_cases"))
    valid = (
        summary.get("total_tests") == 16
        and summary.get("passed") == 16
        and summary.get("failed") == 0
        and summary.get("warnings") == 0
        and summary.get("overall_status") == "passed"
        and summary.get("consumer_readiness") == "ready_with_limits"
        and len(cases) == 16
        and all(isinstance(item, dict) and item.get("status") == "passed" for item in cases)
    )
    results.check(
        "consumer_contract_matrix",
        valid,
        "contract matrix remains 16/16 passed with ready_with_limits readiness"
        if valid
        else f"matrix summary is {summary}; case_count={len(cases)}",
    )


def main() -> int:
    results = Results()
    source_paths = [MANIFEST_PATH, VIEW_MODEL_PATH, *FIXTURE_PATHS]
    load_failures: list[str] = []
    documents: dict[Path, dict[str, Any]] = {}

    before_hashes: dict[Path, str] = {}
    for path in source_paths:
        if path.exists():
            before_hashes[path] = digest(path)

    try:
        manifest = load_json(MANIFEST_PATH)
        view_model = load_json(VIEW_MODEL_PATH)
    except ValueError as exc:
        print(f"FAIL source_loading: {exc}")
        return 1

    for path in FIXTURE_PATHS:
        try:
            documents[path] = load_json(path)
        except ValueError as exc:
            load_failures.append(str(exc))

    check_fixture_presence(documents, load_failures, results)
    if not load_failures:
        check_checkpoint_and_mode(view_model, documents, results)
        check_manifest(manifest, view_model, results)
        check_no_live_data(view_model, documents, results)
        check_no_automation(documents, results)
        check_privacy(documents, results)
        check_rule_interpretation(view_model, documents, results)
        check_pl_and_opportunity_cost(view_model, documents, results)
        check_quote_types(view_model, results)
        check_contract_matrix(documents, results)

    after_hashes = {
        path: digest(path)
        for path in source_paths
        if path.exists()
    }
    changed = [
        relative(path)
        for path, before in before_hashes.items()
        if after_hashes.get(path) != before
    ]
    results.check(
        "read_only_hash_integrity",
        not changed and len(before_hashes) == len(source_paths),
        "all source hashes are unchanged"
        if not changed and len(before_hashes) == len(source_paths)
        else f"changed or missing source files: {changed}",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.failures:
        print(f"FAIL {item}")
    for item in results.warnings:
        print(f"WARN {item}")

    print()
    if results.failures:
        print("Read-only consumer fixture validation failed.")
    else:
        print("Read-only consumer fixture validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Mock consumer files checked: {len(documents)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print(f"Contract matrix: {'16/16 passed' if not results.failures else 'validation blocked'}")
    print("Consumer readiness: ready_with_limits")
    print(f"Read-only confirmed: {str(not changed).lower()}")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
