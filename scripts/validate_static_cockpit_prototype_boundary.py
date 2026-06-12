#!/usr/bin/env python3
"""Validate the static Vol.6 cockpit prototype boundary contracts."""

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

SURFACE_LAYOUT_PATH = MOCK_DIR / "static_cockpit_surface_layout.json"
CARD_CATALOG_PATH = MOCK_DIR / "static_cockpit_card_catalog.json"
INTERACTION_POLICY_PATH = MOCK_DIR / "static_cockpit_interaction_policy.json"
BLOCKED_CONTROLS_PATH = MOCK_DIR / "static_cockpit_blocked_controls.json"
DATA_QUALITY_POLICY_PATH = MOCK_DIR / "static_cockpit_data_quality_display_policy.json"

REQUIRED_FILES = [
    SURFACE_LAYOUT_PATH,
    CARD_CATALOG_PATH,
    INTERACTION_POLICY_PATH,
    BLOCKED_CONTROLS_PATH,
    DATA_QUALITY_POLICY_PATH,
]

REQUIRED_SCHEMAS = [
    SCHEMA_DIR / "static_cockpit_prototype_boundary.schema.json",
    SCHEMA_DIR / "static_cockpit_prototype_review.schema.json",
]

EXPECTED_CHECKPOINT = "2026-06-12T09:18:00+08:00"

REQUIRED_SURFACES = {
    "internal_operator_cockpit_static",
    "ai_board_review_static",
    "audit_debug_static",
    "public_demo_static_blocked",
    "customer_facing_static_blocked",
}

REQUIRED_CARDS = {
    "account_snapshot_card",
    "cash_defense_ratio_card",
    "active_positions_card",
    "closed_positions_card",
    "active_rules_card",
    "execution_ledger_card",
    "strategy_state_card",
    "warning_data_quality_card",
    "source_traceability_card",
    "checkpoint_status_card",
    "non_promoted_evidence_card",
    "customer_facing_blocked_status_card",
}

REQUIRED_INTERACTIONS = {
    "read_static_snapshot",
    "expand_card_details",
    "collapse_card_details",
    "filter_static_table",
    "sort_static_table",
    "switch_read_only_surface",
    "inspect_source_traceability",
    "inspect_data_quality_warning",
    "inspect_checkpoint_status",
    "inspect_non_promoted_evidence_banner",
}

REQUIRED_BLOCKED_CONTROLS = {
    "buy_button",
    "sell_button",
    "cancel_order_button",
    "modify_order_button",
    "execute_trade_button",
    "start_bot_button",
    "stop_bot_button",
    "reopen_grid_button",
    "connect_broker_button",
    "connect_binance_button",
    "connect_external_market_data_button",
    "refresh_live_price_button",
    "promote_checkpoint_button",
    "edit_runtime_record_button",
    "suppress_warning_button",
    "hide_data_quality_button",
    "reveal_sensitive_value_button",
    "reveal_never_expose_field_button",
    "export_customer_facing_sensitive_data_button",
    "enable_customer_facing_view_button",
}

REQUIRED_DISPLAY_ITEMS = {
    "active_checkpoint_timestamp",
    "source_priority",
    "quote_type",
    "source_of_truth",
    "warnings",
    "timeline_warning_count",
    "stale_checkpoint_evidence",
    "non_promoted_governance_evidence",
    "execution_reconciliation_status",
    "customer_facing_blocked_status",
    "permission_masking_profile",
    "data_freshness_label",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_4_STATIC_COCKPIT_PROTOTYPE_BOUNDARY_REVIEW_v0.1.md",
    "schemas/static_cockpit_prototype_boundary.schema.json",
    "schemas/static_cockpit_prototype_review.schema.json",
    "mock_consumers/ldd/static_cockpit_surface_layout.json",
    "mock_consumers/ldd/static_cockpit_card_catalog.json",
    "mock_consumers/ldd/static_cockpit_interaction_policy.json",
    "mock_consumers/ldd/static_cockpit_blocked_controls.json",
    "mock_consumers/ldd/static_cockpit_data_quality_display_policy.json",
    "scripts/validate_static_cockpit_prototype_boundary.py",
    "scripts/validate_static_cockpit_prototype_boundary.sh",
    "records/ldd/2026-06-11/vol6_phase6_4_static_cockpit_prototype_boundary_review_0810_sgt.json",
    "reports/ldd/vol6_phase6_4_static_cockpit_prototype_boundary_review.md",
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

    validator_path = REPO_ROOT / "scripts" / "validate_static_cockpit_prototype_boundary.py"
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
        "all static cockpit JSON contracts are valid"
        if not json_failures
        else "; ".join(json_failures),
    )

    results.check(
        "required_schemas",
        all(path.exists() for path in REQUIRED_SCHEMAS),
        f"{sum(path.exists() for path in REQUIRED_SCHEMAS)}/{len(REQUIRED_SCHEMAS)} required schemas exist",
    )

    if not json_failures and len(documents) == len(REQUIRED_FILES):
        layout = documents[SURFACE_LAYOUT_PATH]
        cards_doc = documents[CARD_CATALOG_PATH]
        interaction_doc = documents[INTERACTION_POLICY_PATH]
        blocked_doc = documents[BLOCKED_CONTROLS_PATH]
        display_doc = documents[DATA_QUALITY_POLICY_PATH]

        surfaces = {
            item.get("surface_id"): item
            for item in layout.get("surfaces", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_surfaces",
            set(surfaces) == REQUIRED_SURFACES,
            f"required surfaces present: {len(set(surfaces) & REQUIRED_SURFACES)}/{len(REQUIRED_SURFACES)}",
        )
        results.check(
            "surface_implementation_status",
            all(item.get("implementation_status") == "contract_only_not_implemented" for item in surfaces.values()),
            "all surfaces are contract_only_not_implemented",
        )
        results.check(
            "surface_customer_facing_denied",
            all(item.get("customer_facing_allowed") is False for item in surfaces.values()),
            "all surfaces have customer_facing_allowed false",
        )
        results.check(
            "public_demo_blocked",
            surfaces.get("public_demo_static_blocked", {}).get("surface_status") == "blocked",
            "public_demo_static_blocked is marked blocked",
        )
        results.check(
            "customer_facing_blocked",
            surfaces.get("customer_facing_static_blocked", {}).get("surface_status") == "blocked",
            "customer_facing_static_blocked is marked blocked",
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
        sensitive_interactive_cards = [
            card_id
            for card_id, item in cards.items()
            if item.get("execution_sensitive") is True
            and item.get("interactive_controls_allowed") is not False
        ]
        results.check(
            "execution_sensitive_cards_non_interactive",
            not sensitive_interactive_cards,
            "execution-sensitive cards are non-interactive"
            if not sensitive_interactive_cards
            else f"interactive execution-sensitive cards: {sensitive_interactive_cards}",
        )
        warning_card = cards.get("warning_data_quality_card", {})
        results.check(
            "warning_data_quality_card_visible",
            warning_card.get("warnings_visible") is True
            and warning_card.get("data_quality_visible") is True,
            "warning_data_quality_card shows warnings and data quality",
        )
        trace_card = cards.get("source_traceability_card", {})
        results.check(
            "source_traceability_card_visible",
            trace_card.get("source_traceability_visible") is True,
            "source_traceability_card shows source traceability",
        )
        customer_blocked_card = cards.get("customer_facing_blocked_status_card", {})
        results.check(
            "customer_blocked_card_status",
            customer_blocked_card.get("customer_facing_ready") is False,
            "customer_facing_blocked_status_card states customer_facing_ready false",
        )

        interactions = {
            item.get("interaction_id"): item
            for item in interaction_doc.get("interactions", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_interactions",
            set(interactions) == REQUIRED_INTERACTIONS,
            f"required interactions present: {len(set(interactions) & REQUIRED_INTERACTIONS)}/{len(REQUIRED_INTERACTIONS)}",
        )
        results.check(
            "interactions_read_only",
            all(item.get("read_only") is True for item in interactions.values()),
            "all interactions are read_only true",
        )
        results.check(
            "interactions_no_mutation",
            all(item.get("mutation_allowed") is False for item in interactions.values()),
            "all interactions have mutation_allowed false",
        )
        results.check(
            "interactions_no_execution",
            all(item.get("execution_allowed") is False for item in interactions.values()),
            "all interactions have execution_allowed false",
        )
        results.check(
            "interactions_no_external_connection_or_credentials",
            all(
                item.get("external_connection_allowed") is False
                and item.get("credential_required") is False
                for item in interactions.values()
            ),
            "all interactions deny external connection and credentials",
        )

        controls = {
            item.get("control_id"): item
            for item in blocked_doc.get("blocked_controls", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_blocked_controls",
            set(controls) == REQUIRED_BLOCKED_CONTROLS,
            f"required blocked controls present: {len(set(controls) & REQUIRED_BLOCKED_CONTROLS)}/{len(REQUIRED_BLOCKED_CONTROLS)}",
        )
        results.check(
            "blocked_controls_true",
            all(item.get("blocked") is True for item in controls.values()),
            "all blocked controls have blocked true",
        )
        results.check(
            "blocked_controls_no_roles",
            all(item.get("allowed_roles") == [] for item in controls.values()),
            "all blocked controls have empty allowed_roles",
        )

        display_items = {
            item.get("item_id"): item
            for item in display_doc.get("display_items", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_display_items",
            set(display_items) == REQUIRED_DISPLAY_ITEMS,
            f"required display policy items present: {len(set(display_items) & REQUIRED_DISPLAY_ITEMS)}/{len(REQUIRED_DISPLAY_ITEMS)}",
        )
        required_visible = {
            "warnings",
            "source_of_truth",
            "quote_type",
            "active_checkpoint_timestamp",
            "customer_facing_blocked_status",
        }
        hidden_required = [
            item_id
            for item_id in required_visible
            if display_items.get(item_id, {}).get("display_required") is not True
            or display_items.get(item_id, {}).get("may_hide") is not False
        ]
        results.check(
            "data_quality_required_display",
            not hidden_required,
            "warnings, source of truth, quote type, active checkpoint, and customer-facing blocked status are required and not hideable"
            if not hidden_required
            else f"display items may be hidden or are not required: {hidden_required}",
        )
        results.check(
            "non_promoted_label",
            display_items.get("non_promoted_governance_evidence", {}).get("label_required") == "non_promoted",
            "non-promoted evidence requires non_promoted label",
        )
        results.check(
            "checkpoint_display",
            display_items.get("active_checkpoint_timestamp", {}).get("expected_value") == EXPECTED_CHECKPOINT
            and layout.get("source_checkpoint") == EXPECTED_CHECKPOINT,
            f"active checkpoint is represented as {EXPECTED_CHECKPOINT}",
        )

    problems = implementation_problems()
    results.check(
        "no_implementation_files",
        not problems,
        "no frontend app, web page, API server, live endpoint, connector, trading executor, credential store, or automation trigger artifacts found"
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
        "validator did not modify static contract files",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.warnings:
        print(f"WARN {item}")
    for item in results.failures:
        print(f"FAIL {item}")

    print()
    if results.failures:
        print("Static cockpit prototype boundary validation failed.")
    else:
        print("Static cockpit prototype boundary validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Contract files checked: {len(REQUIRED_FILES)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print("Actual UI created: false")
    print("Frontend app created: false")
    print("API server created: false")
    print("Live endpoint created: false")
    print("Customer-facing ready: false")
    print("Trading automation enabled: false")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
