#!/usr/bin/env python3
"""Validate the Vol.6 internal operator cockpit static spec contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "mock_consumers" / "ldd"
SCHEMA_DIR = REPO_ROOT / "schemas"

SPEC_PATH = MOCK_DIR / "internal_operator_cockpit_static_spec.json"
SECTION_ORDER_PATH = MOCK_DIR / "internal_operator_cockpit_section_order.json"
CARD_FIELD_MAP_PATH = MOCK_DIR / "internal_operator_cockpit_card_field_map.json"
WARNING_POLICY_PATH = MOCK_DIR / "internal_operator_cockpit_warning_policy.json"
SOURCE_TRACEABILITY_PATH = MOCK_DIR / "internal_operator_cockpit_source_traceability_policy.json"
BLOCKED_ACTION_PATH = MOCK_DIR / "internal_operator_cockpit_blocked_action_policy.json"
ACTIVE_RULES_PATH = REPO_ROOT / "cockpit" / "ldd" / "active_rules.json"

REQUIRED_FILES = [
    SPEC_PATH,
    SECTION_ORDER_PATH,
    CARD_FIELD_MAP_PATH,
    WARNING_POLICY_PATH,
    SOURCE_TRACEABILITY_PATH,
    BLOCKED_ACTION_PATH,
]

REQUIRED_SCHEMAS = [
    SCHEMA_DIR / "internal_operator_cockpit_static_spec.schema.json",
    SCHEMA_DIR / "internal_operator_cockpit_static_spec_review.schema.json",
]

EXPECTED_CHECKPOINT = "2026-06-12T09:18:00+08:00"

REQUIRED_SECTIONS = [
    "system_status_header",
    "active_checkpoint_banner",
    "account_snapshot_section",
    "cash_defense_section",
    "active_positions_section",
    "execution_ledger_section",
    "active_rules_section",
    "strategy_states_section",
    "warning_data_quality_section",
    "source_traceability_section",
    "non_promoted_evidence_section",
    "customer_facing_blocked_status_section",
]

REQUIRED_CARDS = {
    "system_status_header_card",
    "active_checkpoint_card",
    "account_snapshot_card",
    "us_cash_defense_card",
    "binance_usdt_defense_card",
    "active_us_positions_card",
    "closed_positions_card",
    "confirmed_execution_ledger_card",
    "active_rules_card",
    "strategy_states_card",
    "warning_data_quality_card",
    "source_traceability_card",
    "non_promoted_evidence_card",
    "customer_facing_blocked_status_card",
}

REQUIRED_ACCOUNT_FIELDS = {
    "total_assets_usd",
    "us_section_usd",
    "us_holding_value_usd",
    "implied_us_cash_usd",
    "us_cash_ratio",
    "us_day_pnl_usd",
    "us_holding_pnl_usd",
}

REQUIRED_US_CASH_FIELDS = {
    "implied_us_cash_usd",
    "us_cash_ratio",
}

REQUIRED_BINANCE_FIELDS = {
    "total_assets_usdt",
    "usdt_balance",
    "usdt_defense_ratio",
}

REQUIRED_ACTIVE_POSITION_FIELDS = {
    "GOOG",
    "NVDA",
    "GGLL",
    "TSLA",
    "GLD",
}

REQUIRED_EXECUTION_LEDGER_FIELDS = {
    "sell GGLL 5 @ 111.6250",
    "sell GOOG 5 @ 347.77",
}

REQUIRED_WARNING_ITEMS = {
    "customer_facing_blocked",
    "no_live_api_connection",
    "no_broker_connection",
    "no_binance_connection",
    "no_trading_automation",
    "checkpoint_timestamp_visible",
    "source_priority_visible",
    "quote_type_visible",
    "non_promoted_evidence_labeled",
    "execution_ledger_read_only",
    "sensitive_fields_masked",
    "never_expose_fields_rejected",
}

REQUIRED_SOURCE_ITEMS = {
    "user_broker_screenshots",
    "user_binance_screenshots",
    "actual_order_screenshots",
    "external_market_data_for_validation_only",
    "active_checkpoint_record",
    "cockpit_view_model",
    "read_only_api_contract",
    "permission_privacy_masking_contract",
    "static_cockpit_prototype_boundary",
    "non_promoted_governance_evidence",
}

REQUIRED_BLOCKED_ACTIONS = {
    "place_order",
    "cancel_order",
    "modify_order",
    "execute_trade",
    "start_bot",
    "stop_bot",
    "reopen_grid",
    "connect_broker_api",
    "connect_binance_api",
    "connect_external_market_api",
    "fetch_live_market_data",
    "refresh_live_price",
    "mutate_runtime_record",
    "promote_checkpoint",
    "suppress_warning",
    "hide_data_quality_flag",
    "reveal_sensitive_value",
    "reveal_never_expose_field",
    "enable_customer_facing_view",
    "export_sensitive_customer_data",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_5_INTERNAL_OPERATOR_COCKPIT_STATIC_SPEC_v0.1.md",
    "schemas/internal_operator_cockpit_static_spec.schema.json",
    "schemas/internal_operator_cockpit_static_spec_review.schema.json",
    "mock_consumers/ldd/internal_operator_cockpit_static_spec.json",
    "mock_consumers/ldd/internal_operator_cockpit_section_order.json",
    "mock_consumers/ldd/internal_operator_cockpit_card_field_map.json",
    "mock_consumers/ldd/internal_operator_cockpit_warning_policy.json",
    "mock_consumers/ldd/internal_operator_cockpit_source_traceability_policy.json",
    "mock_consumers/ldd/internal_operator_cockpit_blocked_action_policy.json",
    "scripts/validate_internal_operator_cockpit_static_spec.py",
    "scripts/validate_internal_operator_cockpit_static_spec.sh",
    "records/ldd/2026-06-11/vol6_phase6_5_internal_operator_cockpit_static_spec_review_0810_sgt.json",
    "reports/ldd/vol6_phase6_5_internal_operator_cockpit_static_spec.md",
]

FORBIDDEN_IMPLEMENTATION_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
}

FORBIDDEN_IMPLEMENTATION_PATH_PARTS = {
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

FORBIDDEN_FILENAMES = {
    "package.json",
    "vite.config.js",
    "vite.config.ts",
    "next.config.js",
    "next.config.ts",
    "svelte.config.js",
}

FORBIDDEN_PYTHON_IMPORTS = {
    "aiohttp",
    "bottle",
    "django",
    "fastapi",
    "flask",
    "http.server",
    "requests",
    "socket",
    "starlette",
    "tornado",
    "uvicorn",
}


def relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative(path)} must contain a JSON object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Results:
    def __init__(self) -> None:
        self.checked = 0
        self.passes: list[str] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, name: str, condition: bool, detail: str) -> None:
        self.checked += 1
        target = self.passes if condition else self.failures
        target.append(f"{name}: {detail}")


def implementation_problems() -> list[str]:
    problems: list[str] = []
    for artifact in PHASE_ARTIFACTS:
        path = REPO_ROOT / artifact
        if not path.exists():
            problems.append(f"missing phase artifact: {artifact}")
            continue
        parts = set(path.relative_to(REPO_ROOT).parts)
        if path.suffix in FORBIDDEN_IMPLEMENTATION_SUFFIXES:
            problems.append(f"implementation-like file type: {artifact}")
        if parts & FORBIDDEN_IMPLEMENTATION_PATH_PARTS:
            problems.append(f"implementation-like path segment: {artifact}")
        if path.name in FORBIDDEN_FILENAMES:
            problems.append(f"frontend/server package file: {artifact}")

    validator_path = REPO_ROOT / "scripts" / "validate_internal_operator_cockpit_static_spec.py"
    try:
        tree = ast.parse(validator_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        problems.append(f"cannot inspect validator imports: {exc}")
        return problems

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    bad_imports = sorted(
        module
        for module in imports
        if module in FORBIDDEN_PYTHON_IMPORTS
        or any(module.startswith(f"{item}.") for item in FORBIDDEN_PYTHON_IMPORTS)
    )
    if bad_imports:
        problems.append(f"server/connector imports found: {bad_imports}")
    return problems


def main() -> int:
    results = Results()
    before_hashes = {
        path: digest(path)
        for path in REQUIRED_FILES
        if path.exists()
    }

    results.check(
        "required_files",
        all(path.exists() for path in REQUIRED_FILES),
        f"{sum(path.exists() for path in REQUIRED_FILES)}/{len(REQUIRED_FILES)} required contract files exist",
    )

    documents: dict[Path, dict[str, Any]] = {}
    json_failures: list[str] = []
    for path in REQUIRED_FILES:
        try:
            documents[path] = load_json(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            json_failures.append(f"{relative(path)}: {exc}")
    results.check(
        "json_syntax",
        not json_failures,
        "all internal operator static spec JSON contracts are valid"
        if not json_failures
        else "; ".join(json_failures),
    )

    results.check(
        "required_schemas",
        all(path.exists() for path in REQUIRED_SCHEMAS),
        f"{sum(path.exists() for path in REQUIRED_SCHEMAS)}/{len(REQUIRED_SCHEMAS)} required schemas exist",
    )

    if not json_failures and len(documents) == len(REQUIRED_FILES):
        spec = documents[SPEC_PATH]
        sections_doc = documents[SECTION_ORDER_PATH]
        cards_doc = documents[CARD_FIELD_MAP_PATH]
        warnings_doc = documents[WARNING_POLICY_PATH]
        sources_doc = documents[SOURCE_TRACEABILITY_PATH]
        blocked_doc = documents[BLOCKED_ACTION_PATH]

        results.check(
            "spec_actual_ui_false",
            spec.get("actual_ui_created") is False,
            "internal_operator_cockpit_static_spec actual_ui_created is false",
        )
        results.check(
            "spec_customer_facing_false",
            spec.get("customer_facing_ready") is False,
            "internal_operator_cockpit_static_spec customer_facing_ready is false",
        )
        results.check(
            "spec_roles",
            "internal_operator" in spec.get("allowed_roles", [])
            and "customer_facing_viewer_blocked" in spec.get("blocked_roles", []),
            "internal_operator is allowed and customer_facing_viewer_blocked is blocked",
        )
        results.check(
            "spec_checkpoint",
            spec.get("source_checkpoint") == EXPECTED_CHECKPOINT,
            f"spec source checkpoint is {EXPECTED_CHECKPOINT}",
        )

        sections = {
            item.get("section_id"): item
            for item in sections_doc.get("sections", [])
            if isinstance(item, dict)
        }
        section_ids = [item.get("section_id") for item in sections_doc.get("sections", []) if isinstance(item, dict)]
        orders = [item.get("order") for item in sections_doc.get("sections", []) if isinstance(item, dict)]
        results.check(
            "required_sections",
            set(section_ids) == set(REQUIRED_SECTIONS),
            f"required sections present: {len(set(section_ids) & set(REQUIRED_SECTIONS))}/{len(REQUIRED_SECTIONS)}",
        )
        results.check(
            "section_order_unique_sequential",
            sorted(orders) == list(range(1, len(REQUIRED_SECTIONS) + 1)) and len(set(orders)) == len(REQUIRED_SECTIONS),
            "section order is unique and sequential",
        )
        results.check(
            "section_static_spec_only",
            all(item.get("implementation_status") == "static_spec_only" for item in sections.values()),
            "all sections are static_spec_only",
        )
        results.check(
            "section_no_mutation",
            all(item.get("mutation_allowed") is False for item in sections.values()),
            "all sections have mutation_allowed false",
        )
        results.check(
            "section_no_execution",
            all(item.get("execution_allowed") is False for item in sections.values()),
            "all sections have execution_allowed false",
        )
        results.check(
            "section_no_customer_facing",
            all(item.get("customer_facing_allowed") is False for item in sections.values()),
            "all sections have customer_facing_allowed false",
        )
        policy_sections = [
            "warning_data_quality_section",
            "source_traceability_section",
            "non_promoted_evidence_section",
            "customer_facing_blocked_status_section",
        ]
        results.check(
            "policy_sections_required",
            all(sections.get(section_id, {}).get("required") is True for section_id in policy_sections),
            "warning, source, non-promoted evidence, and blocked-status sections are required",
        )

        cards = {
            item.get("card_id"): item
            for item in cards_doc.get("cards", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_cards",
            set(cards) == REQUIRED_CARDS,
            f"required cards present: {len(set(cards) & REQUIRED_CARDS)}/{len(REQUIRED_CARDS)}",
        )
        results.check(
            "card_static_spec_only",
            all(item.get("implementation_status") == "static_spec_only" for item in cards.values()),
            "all cards are static_spec_only",
        )
        results.check(
            "card_no_mutation",
            all(item.get("mutation_allowed") is False for item in cards.values()),
            "all cards have mutation_allowed false",
        )
        results.check(
            "card_no_execution",
            all(item.get("execution_allowed") is False for item in cards.values()),
            "all cards have execution_allowed false",
        )
        results.check(
            "card_no_customer_facing",
            all(item.get("customer_facing_allowed") is False for item in cards.values()),
            "all cards have customer_facing_allowed false",
        )
        never_expose_cards = [
            card_id
            for card_id, item in cards.items()
            if "never_expose" in item.get("field_classes_used", [])
        ]
        results.check(
            "card_no_never_expose",
            not never_expose_cards,
            "never_expose field class is absent from all cards"
            if not never_expose_cards
            else f"never_expose found in cards: {never_expose_cards}",
        )
        execution_sensitive_interactive = [
            card_id
            for card_id, item in cards.items()
            if "execution_sensitive" in item.get("field_classes_used", [])
            and item.get("interactive_controls_allowed") is not False
        ]
        results.check(
            "execution_sensitive_cards_non_interactive",
            not execution_sensitive_interactive,
            "execution-sensitive cards are non-interactive"
            if not execution_sensitive_interactive
            else f"interactive execution-sensitive cards: {execution_sensitive_interactive}",
        )
        results.check(
            "account_snapshot_fields",
            REQUIRED_ACCOUNT_FIELDS <= set(cards.get("account_snapshot_card", {}).get("fields", [])),
            "account_snapshot_card includes required account fields",
        )
        results.check(
            "cash_defense_fields",
            REQUIRED_US_CASH_FIELDS <= set(cards.get("us_cash_defense_card", {}).get("fields", []))
            and REQUIRED_BINANCE_FIELDS <= set(cards.get("binance_usdt_defense_card", {}).get("fields", [])),
            "cash defense cards include required U.S. and Binance fields",
        )
        results.check(
            "active_position_fields",
            REQUIRED_ACTIVE_POSITION_FIELDS <= set(cards.get("active_us_positions_card", {}).get("fields", [])),
            "active_us_positions_card includes GOOG, NVDA, GGLL, TSLA, and GLD",
        )
        ledger = cards.get("confirmed_execution_ledger_card", {})
        results.check(
            "execution_ledger_fields",
            REQUIRED_EXECUTION_LEDGER_FIELDS <= set(ledger.get("fields", [])),
            "confirmed_execution_ledger_card includes latest GGLL and GOOG order-detail sells",
        )
        results.check(
            "execution_ledger_read_only",
            ledger.get("action_controls_present") is False
            and ledger.get("interactive_controls_allowed") is False
            and ledger.get("mutation_allowed") is False
            and ledger.get("execution_allowed") is False,
            "confirmed_execution_ledger_card is read-only and has no action controls",
        )

        active_rules_doc = load_json(ACTIVE_RULES_PATH)
        expected_rule_ids = {
            item.get("rule_id")
            for item in active_rules_doc.get("rules", [])
            if isinstance(item, dict)
        }
        active_rules_card = cards.get("active_rules_card", {})
        actual_rule_ids = set(active_rules_card.get("fields", []))
        results.check(
            "active_rules_card_rule_count",
            actual_rule_ids == expected_rule_ids,
            f"active_rules_card includes all {len(expected_rule_ids)} active rules",
        )
        non_promoted = cards.get("non_promoted_evidence_card", {})
        results.check(
            "non_promoted_evidence_label",
            non_promoted.get("evidence_label") == "non_promoted"
            and non_promoted.get("execution_event") is False,
            "non_promoted_evidence_card labels Phase 6.2a evidence as non-promoted and non-executing",
        )
        customer_blocked_card = cards.get("customer_facing_blocked_status_card", {})
        results.check(
            "customer_blocked_card",
            customer_blocked_card.get("customer_facing_ready") is False,
            "customer_facing_blocked_status_card shows customer_facing_ready false",
        )

        warning_items = {
            item.get("warning_id"): item
            for item in warnings_doc.get("warning_items", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_warning_items",
            set(warning_items) == REQUIRED_WARNING_ITEMS,
            f"required warning items present: {len(set(warning_items) & REQUIRED_WARNING_ITEMS)}/{len(REQUIRED_WARNING_ITEMS)}",
        )
        results.check(
            "warning_items_visible",
            all(item.get("display_required") is True and item.get("may_hide") is False for item in warning_items.values()),
            "every warning item is required and cannot be hidden",
        )
        results.check(
            "high_severity_required_warnings",
            warning_items.get("customer_facing_blocked", {}).get("severity") == "high"
            and warning_items.get("never_expose_fields_rejected", {}).get("severity") == "high",
            "customer_facing_blocked and never_expose_fields_rejected are high severity",
        )

        source_items = {
            item.get("source_id"): item
            for item in sources_doc.get("source_items", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_source_items",
            set(source_items) == REQUIRED_SOURCE_ITEMS,
            f"required source traceability items present: {len(set(source_items) & REQUIRED_SOURCE_ITEMS)}/{len(REQUIRED_SOURCE_ITEMS)}",
        )
        external_priority = source_items.get("external_market_data_for_validation_only", {}).get("priority", 999)
        user_source_priorities = [
            source_items.get("user_broker_screenshots", {}).get("priority", 999),
            source_items.get("user_binance_screenshots", {}).get("priority", 999),
            source_items.get("actual_order_screenshots", {}).get("priority", 999),
        ]
        results.check(
            "source_priority",
            all(priority < external_priority for priority in user_source_priorities),
            "user broker/order/Binance sources rank above external market validation data",
        )
        results.check(
            "external_validation_only",
            source_items.get("external_market_data_for_validation_only", {}).get("source_type") == "validation_only",
            "external market data is labeled validation_only",
        )
        results.check(
            "active_checkpoint_source",
            source_items.get("active_checkpoint_record", {}).get("checkpoint") == EXPECTED_CHECKPOINT,
            f"active checkpoint source references {EXPECTED_CHECKPOINT}",
        )
        results.check(
            "non_promoted_source",
            source_items.get("non_promoted_governance_evidence", {}).get("source_type") == "non_promoted",
            "non-promoted governance evidence source is labeled non_promoted",
        )

        blocked_actions = {
            item.get("action_id"): item
            for item in blocked_doc.get("blocked_actions", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_blocked_actions",
            set(blocked_actions) == REQUIRED_BLOCKED_ACTIONS,
            f"required blocked actions present: {len(set(blocked_actions) & REQUIRED_BLOCKED_ACTIONS)}/{len(REQUIRED_BLOCKED_ACTIONS)}",
        )
        results.check(
            "blocked_actions_true",
            all(item.get("blocked") is True for item in blocked_actions.values()),
            "every blocked action has blocked true",
        )
        results.check(
            "blocked_actions_no_roles",
            all(item.get("allowed_roles") == [] for item in blocked_actions.values()),
            "every blocked action has empty allowed_roles",
        )
        results.check(
            "promote_checkpoint_blocked",
            blocked_actions.get("promote_checkpoint", {}).get("blocked") is True
            and blocked_actions.get("promote_checkpoint", {}).get("allowed_roles") == [],
            "promote_checkpoint remains blocked from UI",
        )

    problems = implementation_problems()
    results.check(
        "no_implementation_files",
        not problems,
        "no frontend app, web page, API server, live endpoint, route handler, connector, trading executor, credential store, runtime mutation UI, or automation trigger artifacts found"
        if not problems
        else "; ".join(problems),
    )

    after_hashes = {
        path: digest(path)
        for path in REQUIRED_FILES
        if path.exists()
    }
    results.check(
        "read_only_integrity",
        before_hashes == after_hashes,
        "validator did not modify internal operator static spec files",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.warnings:
        print(f"WARN {item}")
    for item in results.failures:
        print(f"FAIL {item}")

    print()
    if results.failures:
        print("Internal operator cockpit static spec validation failed.")
    else:
        print("Internal operator cockpit static spec validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Contract files checked: {len(REQUIRED_FILES)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print(f"Active checkpoint: {EXPECTED_CHECKPOINT}")
    print("Actual UI created: false")
    print("Frontend app created: false")
    print("HTML/CSS/JS UI created: false")
    print("API server created: false")
    print("Live endpoint created: false")
    print("Customer-facing ready: false")
    print("Trading automation enabled: false")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
