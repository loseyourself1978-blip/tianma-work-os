#!/usr/bin/env python3
"""Validate the static Vol.6 read-only API contract and examples."""

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

CONTRACT_PATH = MOCK_DIR / "read_only_api_contract.json"
ENDPOINT_PATH = MOCK_DIR / "read_only_api_endpoint_catalog.json"
RESPONSE_PATH = MOCK_DIR / "read_only_api_response_examples.json"
FORBIDDEN_PATH = MOCK_DIR / "read_only_api_forbidden_capabilities.json"

REQUIRED_FILES = [
    CONTRACT_PATH,
    ENDPOINT_PATH,
    RESPONSE_PATH,
    FORBIDDEN_PATH,
]

REQUIRED_SCHEMAS = [
    SCHEMA_DIR / "read_only_api_contract.schema.json",
    SCHEMA_DIR / "read_only_api_response_envelope.schema.json",
    SCHEMA_DIR / "read_only_api_contract_review.schema.json",
]

EXPECTED_CHECKPOINT = "2026-06-10T08:49:00+08:00"
EXPECTED_EVIDENCE_TIMESTAMP = "2026-06-10T17:06:00+08:00"

REQUIRED_ENDPOINTS = {
    "cockpit_snapshot_read",
    "cockpit_positions_read",
    "cockpit_rules_read",
    "governance_evidence_read",
    "cockpit_warnings_read",
    "permission_masking_policy_read",
    "customer_facing_view_status_read",
}

REQUIRED_EXAMPLES = {
    "internal_operator_cockpit_snapshot",
    "ai_board_reviewer_rules_read",
    "audit_reviewer_governance_evidence_read",
    "customer_facing_viewer_blocked_status",
}

REQUIRED_FORBIDDEN = {
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
    "mutate_runtime_record",
    "promote_checkpoint",
    "suppress_warning",
    "hide_data_quality_flag",
    "reveal_never_expose_field",
    "collect_credential",
    "store_credential",
    "export_sensitive_account_value_to_customer_view",
    "enable_customer_facing_ui",
}

PHASE_ARTIFACTS = [
    "docs/runtime/VOL6_PHASE6_3_READ_ONLY_API_CONTRACT_v0.1.md",
    "schemas/read_only_api_contract.schema.json",
    "schemas/read_only_api_response_envelope.schema.json",
    "schemas/read_only_api_contract_review.schema.json",
    "mock_consumers/ldd/read_only_api_contract.json",
    "mock_consumers/ldd/read_only_api_endpoint_catalog.json",
    "mock_consumers/ldd/read_only_api_response_examples.json",
    "mock_consumers/ldd/read_only_api_forbidden_capabilities.json",
    "scripts/validate_read_only_api_contract.py",
    "scripts/validate_read_only_api_contract.sh",
    "records/ldd/2026-06-10/vol6_phase6_3_read_only_api_contract_review_0849_sgt.json",
    "reports/ldd/vol6_phase6_3_read_only_api_contract.md",
]

FORBIDDEN_IMPLEMENTATION_SUFFIXES = {
    ".html",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".go",
    ".rb",
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
        if path.suffix in FORBIDDEN_IMPLEMENTATION_SUFFIXES:
            problems.append(f"implementation-like file type: {artifact}")

    validator_path = REPO_ROOT / "scripts" / "validate_read_only_api_contract.py"
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

    for path in [CONTRACT_PATH, ENDPOINT_PATH, RESPONSE_PATH]:
        text = path.read_text(encoding="utf-8").lower()
        if "http://" in text or "https://" in text:
            problems.append(f"runnable URL-like value found in {relative(path)}")
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
        "all contract JSON files are valid"
        if not json_failures
        else "; ".join(json_failures),
    )

    results.check(
        "required_schemas",
        all(path.exists() for path in REQUIRED_SCHEMAS),
        f"{sum(path.exists() for path in REQUIRED_SCHEMAS)}/{len(REQUIRED_SCHEMAS)} required schemas exist",
    )

    if not json_failures and len(documents) == len(REQUIRED_FILES):
        contract = documents[CONTRACT_PATH]
        endpoint_doc = documents[ENDPOINT_PATH]
        response_doc = documents[RESPONSE_PATH]
        forbidden_doc = documents[FORBIDDEN_PATH]

        safety_expected = {
            "customer_facing_ready": False,
            "read_only_only": True,
            "runtime_mutation_allowed": False,
            "execution_trigger_allowed": False,
            "external_api_connection_allowed": False,
            "broker_api_connection_allowed": False,
            "binance_api_connection_allowed": False,
            "live_market_data_allowed": False,
            "credential_handling_allowed": False,
        }
        bad_safety = {
            key: contract.get(key)
            for key, expected in safety_expected.items()
            if contract.get(key) is not expected
        }
        results.check(
            "contract_safety_booleans",
            not bad_safety,
            "all read-only safety booleans have required values"
            if not bad_safety
            else f"invalid values: {bad_safety}",
        )

        endpoints = {
            item.get("endpoint_id"): item
            for item in endpoint_doc.get("endpoints", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_endpoint_ids",
            set(endpoints) == REQUIRED_ENDPOINTS,
            "all seven required endpoint IDs exist",
        )

        results.check(
            "endpoints_contract_only",
            all(item.get("contract_only") is True for item in endpoints.values()),
            "every endpoint is contract-only",
        )
        results.check(
            "endpoints_no_mutation",
            all(item.get("mutation_allowed") is False for item in endpoints.values()),
            "every endpoint denies mutation",
        )
        results.check(
            "endpoints_no_execution",
            all(item.get("execution_allowed") is False for item in endpoints.values()),
            "every endpoint denies execution",
        )
        results.check(
            "endpoints_no_external_connection",
            all(
                item.get("external_connection_allowed") is False
                for item in endpoints.values()
            ),
            "every endpoint denies external connections",
        )
        results.check(
            "endpoints_no_credentials",
            all(item.get("credential_required") is False for item in endpoints.values()),
            "every endpoint denies credential requirements",
        )

        customer_endpoint = endpoints.get("customer_facing_view_status_read", {})
        results.check(
            "customer_facing_blocked",
            contract.get("customer_facing_ready") is False
            and customer_endpoint.get("customer_facing_ready") is False
            and customer_endpoint.get("unblock_requires_governance_approval") is True,
            "customer-facing readiness remains false",
        )

        layers = {
            item.get("layer_id"): item
            for item in contract.get("source_layers", [])
            if isinstance(item, dict)
        }
        governance_layer = layers.get("non_promoted_governance_evidence", {})
        results.check(
            "non_promoted_evidence",
            governance_layer.get("timestamp") == EXPECTED_EVIDENCE_TIMESTAMP
            and governance_layer.get("promoted") is False
            and governance_layer.get("execution_event") is False
            and endpoints.get("governance_evidence_read", {}).get(
                "promoted_to_checkpoint"
            )
            is False,
            "Phase 6.2a evidence is represented as non-promoted and non-executing",
        )

        examples = {
            item.get("example_id"): item
            for item in response_doc.get("examples", [])
            if isinstance(item, dict)
        }
        override_items = [
            override
            for example in examples.values()
            for override in example.get("stale_checkpoint_overrides", [])
            if isinstance(override, dict)
        ]
        override_text = json.dumps(override_items, ensure_ascii=False)
        results.check(
            "stale_checkpoint_overrides",
            "GLD" in override_text
            and "NVDA" in override_text
            and all(
                item.get("promoted_to_checkpoint") is False
                and item.get("reconciliation_required") is True
                for item in override_items
            ),
            "GLD and NVDA overrides exist and remain non-promoted",
        )

        results.check(
            "response_source_and_quote",
            set(examples) == REQUIRED_EXAMPLES
            and all(
                bool(item.get("source_of_truth")) and bool(item.get("quote_type"))
                for item in examples.values()
            ),
            "all four response examples include Source-of-Truth and quote-type metadata",
        )
        results.check(
            "response_warnings_and_quality",
            all(
                isinstance(item.get("warnings"), list)
                and isinstance(item.get("data_quality"), dict)
                for item in examples.values()
            ),
            "all response examples include warnings and data quality",
        )
        results.check(
            "response_forbidden_actions",
            all(bool(item.get("forbidden_actions")) for item in examples.values()),
            "all response examples include forbidden actions",
        )

        capabilities = {
            item.get("capability_id"): item
            for item in forbidden_doc.get("capabilities", [])
            if isinstance(item, dict)
        }
        results.check(
            "required_forbidden_capabilities",
            set(capabilities) == REQUIRED_FORBIDDEN,
            "all twenty forbidden capabilities exist",
        )
        results.check(
            "forbidden_capabilities_blocked",
            all(item.get("blocked") is True for item in capabilities.values()),
            "every forbidden capability is blocked",
        )
        results.check(
            "forbidden_capabilities_no_roles",
            all(item.get("allowed_roles") == [] for item in capabilities.values()),
            "every forbidden capability has an empty allowed-role list",
        )

        problems = implementation_problems()
        results.check(
            "no_implementation_files",
            not problems,
            "no server, route, listener, connector, executor, credential store, or frontend implementation detected"
            if not problems
            else "; ".join(problems),
        )

    after_hashes = {
        path: digest(path)
        for path in REQUIRED_FILES
        if path.exists()
    }
    changed = [
        relative(path)
        for path, before in before_hashes.items()
        if after_hashes.get(path) != before
    ]
    results.check(
        "read_only_hash_integrity",
        not changed and len(before_hashes) == len(REQUIRED_FILES),
        "all contract fixture hashes are unchanged"
        if not changed and len(before_hashes) == len(REQUIRED_FILES)
        else f"changed or missing fixtures: {changed}",
    )

    for item in results.passes:
        print(f"PASS {item}")
    for item in results.failures:
        print(f"FAIL {item}")
    for item in results.warnings:
        print(f"WARN {item}")

    print()
    if results.failures:
        print("Read-only API contract validation failed.")
    else:
        print("Read-only API contract validation passed.")
    print(f"Checks: {results.checked}")
    print(f"Contract files checked: {len(REQUIRED_FILES)}")
    print(f"Blocking failures: {len(results.failures)}")
    print(f"Warnings: {len(results.warnings)}")
    print("Actual API server created: false")
    print("Live endpoint created: false")
    print("Customer-facing ready: false")
    print("Runtime mutation enabled: false")
    print("Execution trigger enabled: false")

    return 1 if results.failures else 0


if __name__ == "__main__":
    sys.exit(main())
