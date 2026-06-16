#!/usr/bin/env python3
"""Generate the Vol.8 future implementation readiness ladder Markdown.

The generator reads local fixture files only, uses the Python standard library,
and never accesses network, credentials, live data, or runtime mutation paths.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ITEMS_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_future_implementation_readiness_items.json"
LADDER_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_future_implementation_readiness_ladder.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "runtime" / "VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER_v0.1.md"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def count_by(items: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(item.get(key, "unknown")) for item in items)


def render_counts(title: str, counts: Counter[str]) -> list[str]:
    lines = [f"## {title}", ""]
    for key in sorted(counts):
        lines.append(f"- `{key}`: `{counts[key]}`")
    lines.append("")
    return lines


def main() -> int:
    raw_items = load_json(ITEMS_PATH)
    ladder = load_json(LADDER_PATH)
    if not isinstance(raw_items, list):
        raise ValueError(f"{ITEMS_PATH.relative_to(REPO_ROOT)} must contain a readiness item array")
    if not isinstance(ladder, dict):
        raise ValueError(f"{LADDER_PATH.relative_to(REPO_ROOT)} must contain a readiness ladder object")

    items = [item for item in raw_items if isinstance(item, dict)]
    level_counts = count_by(items, "readiness_level")
    gate_counts = count_by(items, "required_gate_type")
    static_ready_count = sum(1 for item in items if item.get("readiness_level") in {"L1_static_doc_refinement_ready", "L2_static_fixture_refinement_ready"})
    roadmap_only_count = sum(1 for item in items if item.get("roadmap_only") is True)
    future_gate_count = sum(1 for item in items if item.get("requires_future_gate") is True)
    rejected_count = sum(1 for item in items if item.get("readiness_level") == "L0_forbidden_rejected")
    deferred_out_of_scope_count = sum(1 for item in items if item.get("readiness_level") == "L10_out_of_scope_deferred")
    execution_gate_count = sum(1 for item in items if item.get("required_gate_type") == "execution_governance_gate")
    network_gate_count = sum(1 for item in items if item.get("required_gate_type") == "network_api_integration_gate")
    customer_gate_count = sum(1 for item in items if item.get("required_gate_type") == "customer_facing_readiness_gate")
    security_gate_count = sum(1 for item in items if item.get("required_gate_type") == "security_credential_gate")

    lines: list[str] = [
        "# Vol.8 Future Implementation Readiness Ladder v0.1",
        "",
        f"Phase: `{scalar(ladder.get('phase'))}`",
        "",
        f"Baseline commit: `{scalar(ladder.get('baseline_commit'))}`",
        "",
        f"Runtime records baseline: `{scalar(ladder.get('runtime_records'))}`",
        "",
        f"Static shell path: `{scalar(ladder.get('static_shell_path'))}`",
        "",
        f"Source boundary map: `{scalar(ladder.get('source_boundary_map'))}`",
        "",
        "Customer-facing readiness: `false`",
        "",
        "This readiness ladder is generated from local fixtures only. Readiness level is not implementation approval and does not imply live data, API access, execution capability, broker/Binance connectivity, credentials, auth, mutation, or customer-facing readiness.",
        "",
        "## Summary",
        "",
        f"- Total ladder items: `{len(items)}`",
        f"- Static-ready count: `{static_ready_count}`",
        f"- Roadmap-only count: `{roadmap_only_count}`",
        f"- Future-gate-required count: `{future_gate_count}`",
        f"- Rejected forbidden-scope count: `{rejected_count}`",
        f"- Deferred/out-of-scope count: `{deferred_out_of_scope_count}`",
        f"- Execution-governance-required count: `{execution_gate_count}`",
        f"- Network/API-gate-required count: `{network_gate_count}`",
        f"- Customer-facing-gate-required count: `{customer_gate_count}`",
        f"- Security/credential-gate-required count: `{security_gate_count}`",
        "",
    ]

    lines.extend(render_counts("Count By Readiness Level", level_counts))
    lines.extend(render_counts("Count By Required Gate Type", gate_counts))

    lines.extend(["## Boundary Risk Notes", ""])
    summary = ladder.get("summary") if isinstance(ladder.get("summary"), dict) else {}
    notes = as_list(summary.get("boundary_risk_notes"))
    if notes:
        for note in notes:
            lines.append(f"- {scalar(note)}")
    else:
        lines.append("- None.")
    lines.append("")

    lines.extend(["## Recommended Next Action", "", scalar(summary.get("recommended_next_action")), ""])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("Vol.8 future implementation readiness ladder generated.")
    print(f"- source_items: {ITEMS_PATH.relative_to(REPO_ROOT)}")
    print(f"- source_ladder: {LADDER_PATH.relative_to(REPO_ROOT)}")
    print(f"- output: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"- readiness_items: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
