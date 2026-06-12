#!/usr/bin/env python3
"""Validate the static Vol.6 permission, privacy, and masking contracts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "mock_consumers" / "ldd"
VIEW_MODEL_PATH = REPO_ROOT / "cockpit" / "ldd" / "view_model.json"
ROLE_PATH = MOCK_DIR / "permission_role_taxonomy.json"
MASKING_PATH = MOCK_DIR / "privacy_masking_policy.json"
FIELD_MATRIX_PATH = MOCK_DIR / "field_permission_matrix.json"
UNBLOCK_PATH = MOCK_DIR / "customer_facing_unblock_criteria.json"

EXPECTED_CHECKPOINT = "2026-06-12T09:18:00+08:00"
EXPECTED_SOURCE = "cockpit/ldd/view_model.json"

CONTRACT_PATHS = [
    VIEW_MODEL_PATH,
    ROLE_PATH,
    MASKING_PATH,
    FIELD_MATRIX_PATH,
    UNBLOCK_PATH,
]

REQUIRED_ROLES = {
    "system_admin",
    "internal_operator",
    "ai_board_reviewer",
    "audit_reviewer",
    "demo_viewer",
    "customer_facing_viewer_blocked",
}

REQUIRED_ROLE_FIELDS = {
    "role_id",
    "display_name",
    "purpose",
    "allowed_surfaces",
    "blocked_surfaces",
    "can_view_public_safe",
    "can_view_internal_read_only",
    "can_view_sensitive_account_value",
    "can_view_execution_sensitive",
    "can_view_audit_only",
    "can_view_never_expose",
    "can_export",
    "can_mutate_runtime",
    "can_trigger_execution",
    "notes",
}

REQUIRED_MASKING_ACTIONS = {
    "visible",
    "masked_partial",
    "masked_full",
    "omitted",
    "blocked",
    "reject_before_render",
}

REQUIRED_ACTION_FIELDS = {
    "action_id",
    "description",
    "allowed_for_customer_facing",
    "allowed_for_internal_read_only",
    "example_before",
    "example_after",
    "validation_rule",
}

REQUIRED_FIELD_CLASSES = {
    "public_safe",
    "internal_read_only",
    "sensitive_account_value",
    "execution_sensitive",
    "audit_only",
    "never_expose",
}

REQUIRED_FIELD_DECISIONS = {
    "field_class",
    "default_access",
    "masking_action",
    "allowed_roles",
    "blocked_roles",
    "customer_facing_policy",
    "export_policy",
    "mutation_policy",
    "validator_expectation",
}


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
        for path in CONTRACT_PATHS
        if path.exists()
    }

    documents: dict[Path, dict[str, Any]] = {}
    load_failures: list[str] = []
    for path in CONTRACT_PATHS:
        try:
            documents[path] = load_json(path)
        except ValueError as exc:
            load_failures.append(str(exc))

    results.check(
        "required_files_and_json",
        not load_failures and len(documents) == len(CONTRACT_PATHS),
        f"{len(documents)}/{len(CONTRACT_PATHS)} required JSON artifacts loaded"
        if not load_failures
        else "; ".join(load_failures),
    )

    if not load_failures:
        view_model = documents[VIEW_MODEL_PATH]
        role_doc = documents[ROLE_PATH]
        masking_doc = documents[MASKING_PATH]
        field_doc = documents[FIELD_MATRIX_PATH]
        unblock_doc = documents[UNBLOCK_PATH]

        checkpoint = (
            view_model.get("checkpoint", {}).get("latest_active_checkpoint")
            if isinstance(view_model.get("checkpoint"), dict)
            else None
        )
        source_documents = [role_doc, masking_doc, field_doc, unblock_doc]
        results.check(
            "checkpoint_and_source",
            checkpoint == EXPECTED_CHECKPOINT
            and all(
                document.get("baseline_checkpoint") == EXPECTED_CHECKPOINT
                and document.get("source_view_model") == EXPECTED_SOURCE
                for document in source_documents
            ),
            f"all contracts use {EXPECTED_CHECKPOINT} and {EXPECTED_SOURCE}",
        )

        roles = {
            role.get("role_id"): role
            for role in role_doc.get("roles", [])
            if isinstance(role, dict)
        }
        results.check(
            "required_roles",
            set(roles) == REQUIRED_ROLES,
            "all six required roles exist",
        )

        incomplete_roles = {
            role_id: sorted(REQUIRED_ROLE_FIELDS - set(role))
            for role_id, role in roles.items()
            if REQUIRED_ROLE_FIELDS - set(role)
        }
        results.check(
            "explicit_role_permissions",
            not incomplete_roles,
            "every role has explicit access, export, mutation, and execution decisions"
            if not incomplete_roles
            else f"incomplete roles: {incomplete_roles}",
        )

        never_expose_roles = [
            role_id
            for role_id, role in roles.items()
            if role.get("can_view_never_expose") is not False
        ]
        results.check(
            "never_expose_role_denial",
            not never_expose_roles,
            "never_expose is denied to every role"
            if not never_expose_roles
            else f"invalid roles: {never_expose_roles}",
        )

        customer_role = roles.get("customer_facing_viewer_blocked", {})
        results.check(
            "customer_role_blocked",
            customer_role.get("allowed_surfaces") == []
            and set(customer_role.get("blocked_surfaces", []))
            >= {
                "internal_operator_cockpit",
                "ai_board_review",
                "audit_debug_view",
                "public_demo_view",
                "customer_facing_view_blocked",
            },
            "customer-facing viewer has no allowed cockpit surface",
        )

        mutable_roles = [
            role_id
            for role_id, role in roles.items()
            if role.get("can_mutate_runtime") is not False
        ]
        results.check(
            "runtime_mutation_denied",
            not mutable_roles,
            "runtime mutation is denied to every role"
            if not mutable_roles
            else f"invalid roles: {mutable_roles}",
        )

        execution_roles = [
            role_id
            for role_id, role in roles.items()
            if role.get("can_trigger_execution") is not False
        ]
        results.check(
            "execution_trigger_denied",
            not execution_roles,
            "execution triggering is denied to every role"
            if not execution_roles
            else f"invalid roles: {execution_roles}",
        )

        actions = {
            action.get("action_id"): action
            for action in masking_doc.get("actions", [])
            if isinstance(action, dict)
        }
        incomplete_actions = {
            action_id: sorted(REQUIRED_ACTION_FIELDS - set(action))
            for action_id, action in actions.items()
            if REQUIRED_ACTION_FIELDS - set(action)
        }
        results.check(
            "masking_actions",
            set(actions) == REQUIRED_MASKING_ACTIONS and not incomplete_actions,
            "all six masking actions have complete policies"
            if not incomplete_actions
            else f"incomplete actions: {incomplete_actions}",
        )

        field_classes = {
            item.get("field_class"): item
            for item in field_doc.get("field_classes", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_field_classes",
            set(field_classes) == REQUIRED_FIELD_CLASSES,
            "all six Phase 6.1 field classes exist",
        )

        incomplete_classes = {
            field_class: sorted(REQUIRED_FIELD_DECISIONS - set(item))
            for field_class, item in field_classes.items()
            if REQUIRED_FIELD_DECISIONS - set(item)
        }
        unknown_role_references = {
            field_class: sorted(
                (
                    set(item.get("allowed_roles", []))
                    | set(item.get("blocked_roles", []))
                )
                - REQUIRED_ROLES
            )
            for field_class, item in field_classes.items()
            if (
                set(item.get("allowed_roles", []))
                | set(item.get("blocked_roles", []))
            )
            - REQUIRED_ROLES
        }
        results.check(
            "explicit_field_decisions",
            not incomplete_classes and not unknown_role_references,
            "every field class has explicit masking, access, export, and mutation decisions"
            if not incomplete_classes and not unknown_role_references
            else (
                f"incomplete={incomplete_classes}; "
                f"unknown_roles={unknown_role_references}"
            ),
        )

        execution_sensitive = field_classes.get("execution_sensitive", {})
        results.check(
            "execution_sensitive_read_only",
            execution_sensitive.get("mutation_policy")
            == "read_only_non_interactive"
            and execution_sensitive.get("masking_action") == "blocked"
            and "customer_facing_viewer_blocked"
            in execution_sensitive.get("blocked_roles", []),
            "execution-sensitive fields are restricted, non-interactive, and blocked for customers",
        )

        never_expose = field_classes.get("never_expose", {})
        results.check(
            "never_expose_field_policy",
            never_expose.get("masking_action") == "reject_before_render"
            and never_expose.get("allowed_roles") == []
            and set(never_expose.get("blocked_roles", [])) == REQUIRED_ROLES,
            "never_expose uses reject_before_render and blocks every role",
        )

        required_true_criteria = [
            "unblock_requires_governance_approval",
            "permission_model_present",
            "masking_policy_present",
            "field_permission_matrix_present",
            "never_expose_validator_present",
            "execution_sensitive_fields_non_interactive",
            "warnings_visible",
            "data_quality_visible",
            "source_traceability_visible",
            "no_credentials_or_tokens",
            "no_account_identifiers",
            "no_live_api_connection",
            "no_broker_connection",
            "no_binance_connection",
            "no_trading_automation",
            "no_runtime_mutation",
        ]
        results.check(
            "customer_facing_block_state",
            unblock_doc.get("customer_facing_ready") is False
            and all(unblock_doc.get(key) is True for key in required_true_criteria),
            "customer-facing readiness is false and all safety criteria are explicit",
        )

        prohibitions = role_doc.get("global_prohibitions", {})
        results.check(
            "connection_permissions_denied",
            prohibitions.get("live_api_access") is False
            and prohibitions.get("broker_connection") is False
            and prohibitions.get("binance_connection") is False
            and prohibitions.get("live_market_data") is False
            and unblock_doc.get("no_live_api_connection") is True
            and unblock_doc.get("no_broker_connection") is True
            and unblock_doc.get("no_binance_connection") is True,
            "no role or criterion enables live API, broker, Binance, or live market data access",
        )

        results.check(
            "credential_and_automation_denied",
            prohibitions.get("credential_entry") is False
            and prohibitions.get("trading_automation") is False
            and prohibitions.get("runtime_mutation") is False
            and prohibitions.get("execution_trigger") is False
            and unblock_doc.get("no_credentials_or_tokens") is True
            and unblock_doc.get("no_trading_automation") is True
            and unblock_doc.get("no_runtime_mutation") is True,
            "credential entry, trading automation, runtime mutation, and execution are denied",
        )

    after_hashes = {
        path: digest(path)
        for path in CONTRACT_PATHS
        if path.exists()
    }
    changed = [
        relative(path)
        for path, before in before_hashes.items()
        if after_hashes.get(path) != before
    ]
    results.check(
        "read_only_hash_integrity",
        not changed and len(before_hashes) == len(CONTRACT_PATHS),
        "all contract source hashes are unchanged"
        if not changed and len(before_hashes) == len(CONTRACT_PATHS)
        else f"changed or missing artifacts: {changed}",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.failures:
        print(f"FAIL {item}")
    for item in results.warnings:
        print(f"WARN {item}")

    print()
    if results.failures:
        print("Permission/privacy/masking validation failed.")
    else:
        print("Permission/privacy/masking validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Contract files checked: {len(CONTRACT_PATHS)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print("Customer-facing ready: false")
    print("Runtime mutation enabled: false")
    print("Execution trigger enabled: false")
    print("Credential handling enabled: false")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
