#!/usr/bin/env python3
"""Validate the static Vol.6 read-only UI boundary contract."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "mock_consumers" / "ldd"
VIEW_MODEL_PATH = REPO_ROOT / "cockpit" / "ldd" / "view_model.json"
CONTRACT_PATH = MOCK_DIR / "ui_boundary_contract.json"
SURFACE_MAP_PATH = MOCK_DIR / "ui_surface_map.json"
VISIBILITY_PATH = MOCK_DIR / "ui_field_visibility_matrix.json"
TAXONOMY_PATH = MOCK_DIR / "ui_state_taxonomy.json"

EXPECTED_CHECKPOINT = "2026-06-10T08:49:00+08:00"
EXPECTED_SOURCE = "cockpit/ldd/view_model.json"

BOUNDARY_PATHS = [
    VIEW_MODEL_PATH,
    CONTRACT_PATH,
    SURFACE_MAP_PATH,
    VISIBILITY_PATH,
    TAXONOMY_PATH,
]

REQUIRED_SECTIONS = {
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
}

REQUIRED_VISIBILITY_CLASSES = {
    "public_safe",
    "internal_only",
    "sensitive_account",
    "execution_sensitive",
    "never_expose",
}

REQUIRED_TAXONOMIES = {
    "data_states",
    "position_states",
    "rule_states",
    "strategy_states",
    "interaction_states",
}

REQUIRED_PROHIBITIONS = {
    "customer_facing_rendering",
    "runtime_record_mutation",
    "order_submission",
    "trade_execution",
    "credential_entry",
    "live_api_connection",
    "broker_api_connection",
    "binance_api_connection",
    "raw_record_state_reconstruction",
}

FORBIDDEN_ALLOWED_INTERACTION = re.compile(
    r"(execute|order|trade|buy|sell|cancel|connect|credential|mutat|write)",
    re.IGNORECASE,
)

SENSITIVE_ASSIGNMENT = re.compile(
    r"(api[_ -]?key|access[_ -]?token|auth[_ -]?token|password|secret)"
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


def main() -> int:
    results = Results()
    before_hashes = {
        path: digest(path)
        for path in BOUNDARY_PATHS
        if path.exists()
    }

    documents: dict[Path, dict[str, Any]] = {}
    load_failures: list[str] = []
    for path in BOUNDARY_PATHS:
        try:
            documents[path] = load_json(path)
        except ValueError as exc:
            load_failures.append(str(exc))

    results.check(
        "artifact_presence",
        not load_failures and len(documents) == len(BOUNDARY_PATHS),
        f"{len(documents)}/{len(BOUNDARY_PATHS)} boundary artifacts loaded"
        if not load_failures
        else "; ".join(load_failures),
    )

    if not load_failures:
        view_model = documents[VIEW_MODEL_PATH]
        contract = documents[CONTRACT_PATH]
        surface_map = documents[SURFACE_MAP_PATH]
        visibility = documents[VISIBILITY_PATH]
        taxonomy = documents[TAXONOMY_PATH]

        checkpoint = (
            view_model.get("checkpoint", {}).get("latest_active_checkpoint")
            if isinstance(view_model.get("checkpoint"), dict)
            else None
        )
        results.check(
            "checkpoint_integrity",
            checkpoint == EXPECTED_CHECKPOINT
            and contract.get("baseline_checkpoint") == EXPECTED_CHECKPOINT,
            f"view model and boundary contract use {EXPECTED_CHECKPOINT}",
        )

        results.check(
            "source_contract",
            contract.get("source_view_model") == EXPECTED_SOURCE
            and surface_map.get("source_view_model") == EXPECTED_SOURCE
            and visibility.get("source_view_model") == EXPECTED_SOURCE
            and taxonomy.get("source_view_model") == EXPECTED_SOURCE,
            "all boundary artifacts reference cockpit/ldd/view_model.json",
        )

        allowed_sections = set(contract.get("allowed_view_model_sections", []))
        results.check(
            "view_model_sections",
            allowed_sections == REQUIRED_SECTIONS
            and REQUIRED_SECTIONS.issubset(view_model.keys()),
            "the complete approved view-model section set is declared",
        )

        surface_reads = {
            str(item)
            for surface in surface_map.get("surfaces", [])
            if isinstance(surface, dict)
            for item in surface.get("reads", [])
        }
        invalid_reads = surface_reads - REQUIRED_SECTIONS - {"source_files"}
        raw_record_reads = [
            item
            for item in surface_reads
            if item.startswith("records/") or "records/ldd" in item
        ]
        results.check(
            "surface_map_boundary",
            not invalid_reads and not raw_record_reads,
            f"{len(surface_map.get('surfaces', []))} surfaces read approved sections only"
            if not invalid_reads and not raw_record_reads
            else f"invalid reads={sorted(invalid_reads)}; raw record reads={raw_record_reads}",
        )

        classes = {
            item.get("visibility_class")
            for item in visibility.get("classes", [])
            if isinstance(item, dict)
        }
        results.check(
            "visibility_classes",
            classes == REQUIRED_VISIBILITY_CLASSES,
            "all five visibility classes are defined",
        )

        never_expose = next(
            (
                item
                for item in visibility.get("classes", [])
                if isinstance(item, dict)
                and item.get("visibility_class") == "never_expose"
            ),
            {},
        )
        execution_sensitive = next(
            (
                item
                for item in visibility.get("classes", [])
                if isinstance(item, dict)
                and item.get("visibility_class") == "execution_sensitive"
            ),
            {},
        )
        results.check(
            "privacy_defaults",
            never_expose.get("customer_facing_default") == "prohibited"
            and never_expose.get("reject_before_render") is True
            and execution_sensitive.get("must_not_be_interactive") is True,
            "never-expose and execution-sensitive fields use deny-by-default behavior",
        )

        taxonomies = taxonomy.get("taxonomies", {})
        taxonomy_names = set(taxonomies) if isinstance(taxonomies, dict) else set()
        forbidden_states = set(taxonomy.get("forbidden_interaction_states", []))
        results.check(
            "state_taxonomy",
            REQUIRED_TAXONOMIES.issubset(taxonomy_names)
            and {"closed_position", "prohibited_reentry"}.issubset(
                set(taxonomies.get("position_states", []))
            )
            and {"stale", "superseded", "unknown"}.issubset(
                set(taxonomies.get("data_states", []))
            )
            and {"execute", "submit_order", "buy", "sell"}.issubset(
                forbidden_states
            ),
            "data, position, rule, strategy, and read-only interaction states are explicit",
        )

        allowed_interactions = contract.get("allowed_interactions", [])
        bad_allowed = [
            item
            for item in allowed_interactions
            if FORBIDDEN_ALLOWED_INTERACTION.search(str(item))
        ]
        results.check(
            "read_only_interactions",
            not bad_allowed,
            "allowed interactions are local, navigational, and read-only"
            if not bad_allowed
            else f"forbidden allowed interactions: {bad_allowed}",
        )

        prohibitions = set(contract.get("prohibited_capabilities", []))
        results.check(
            "prohibited_capabilities",
            REQUIRED_PROHIBITIONS.issubset(prohibitions),
            "live services, mutation, credentials, and execution are explicitly prohibited",
        )

        status = contract.get("status", {})
        status = status if isinstance(status, dict) else {}
        false_flags = [
            "customer_facing_ready",
            "frontend_implemented",
            "api_server_present",
            "external_api_connected",
            "broker_api_connected",
            "binance_api_connected",
            "trading_automation_enabled",
        ]
        results.check(
            "implementation_boundary",
            all(status.get(flag) is False for flag in false_flags)
            and status.get("internal_read_only_ready") is True,
            "customer-facing, frontend, server, connection, and automation flags remain false",
        )

        combined_text = "\n".join(
            json.dumps(document, ensure_ascii=False, sort_keys=True)
            for document in documents.values()
        )
        results.check(
            "credential_safety",
            SENSITIVE_ASSIGNMENT.search(combined_text) is None,
            "no credential-like values are present",
        )

    after_hashes = {
        path: digest(path)
        for path in BOUNDARY_PATHS
        if path.exists()
    }
    changed = [
        relative(path)
        for path, before in before_hashes.items()
        if after_hashes.get(path) != before
    ]
    results.check(
        "read_only_hash_integrity",
        not changed and len(before_hashes) == len(BOUNDARY_PATHS),
        "all boundary source hashes are unchanged"
        if not changed and len(before_hashes) == len(BOUNDARY_PATHS)
        else f"changed or missing files: {changed}",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.failures:
        print(f"FAIL {item}")
    for item in results.warnings:
        print(f"WARN {item}")

    print()
    print(
        "UI boundary contract validation failed."
        if results.failures
        else "UI boundary contract validation passed."
    )
    print(f"Checks: {results.checked}")
    print(f"Boundary files checked: {len(documents)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print("Customer-facing ready: false")
    print("Frontend implemented: false")
    print("API server present: false")
    print("Trading automation enabled: false")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
