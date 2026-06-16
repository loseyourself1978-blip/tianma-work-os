#!/usr/bin/env python3
"""Generate the Vol.8 feedback-to-roadmap boundary map Markdown.

The generator reads local fixture files only, uses the Python standard library,
and never accesses network, credentials, live data, or runtime mutation paths.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ITEMS_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_feedback_to_roadmap_mapping_sample.json"
MAP_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_feedback_to_roadmap_boundary_map.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "runtime" / "VOL8_FEEDBACK_TO_ROADMAP_BOUNDARY_MAP_v0.1.md"

DEFERRED_CATEGORIES = {
    "live_runtime_request_deferred",
    "execution_request_deferred",
    "credential_or_auth_request_deferred",
    "customer_facing_request_deferred",
}


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
    boundary_map = load_json(MAP_PATH)
    if not isinstance(raw_items, list):
        raise ValueError(f"{ITEMS_PATH.relative_to(REPO_ROOT)} must contain a mapping item array")
    if not isinstance(boundary_map, dict):
        raise ValueError(f"{MAP_PATH.relative_to(REPO_ROOT)} must contain a boundary map object")

    items = [item for item in raw_items if isinstance(item, dict)]
    category_counts = count_by(items, "mapping_category")
    decision_counts = count_by(items, "boundary_decision")
    safe_static_count = sum(1 for item in items if item.get("boundary_decision") == "safe_to_refine_now_static_only")
    roadmap_only_count = sum(1 for item in items if item.get("roadmap_only") is True)
    future_gate_count = sum(1 for item in items if item.get("requires_future_gate") is True)
    rejected_count = sum(1 for item in items if item.get("mapping_category") == "forbidden_scope_rejected")
    deferred_live_execution_count = sum(1 for item in items if item.get("mapping_category") in DEFERRED_CATEGORIES)

    lines: list[str] = [
        "# Vol.8 Feedback-to-Roadmap Boundary Map v0.1",
        "",
        f"Phase: `{scalar(boundary_map.get('phase'))}`",
        "",
        f"Baseline commit: `{scalar(boundary_map.get('baseline_commit'))}`",
        "",
        f"Runtime records baseline: `{scalar(boundary_map.get('runtime_records'))}`",
        "",
        f"Static shell path: `{scalar(boundary_map.get('static_shell_path'))}`",
        "",
        f"Source feedback rollup: `{scalar(boundary_map.get('source_feedback_rollup'))}`",
        "",
        "Customer-facing readiness: `false`",
        "",
        "This boundary map is generated from local fixtures only. Roadmap mapping is not implementation approval and does not imply live data, API access, execution capability, broker/Binance connectivity, credentials, auth, mutation, or customer-facing readiness.",
        "",
        "## Summary",
        "",
        f"- Total mapped items: `{len(items)}`",
        f"- Safe static-only refinements count: `{safe_static_count}`",
        f"- Roadmap-only candidates count: `{roadmap_only_count}`",
        f"- Future readiness gate required count: `{future_gate_count}`",
        f"- Rejected forbidden-scope count: `{rejected_count}`",
        f"- Deferred live/runtime/execution count: `{deferred_live_execution_count}`",
        "",
    ]

    lines.extend(render_counts("Count By Mapping Category", category_counts))
    lines.extend(render_counts("Count By Boundary Decision Type", decision_counts))

    lines.extend(["## Boundary Risk Notes", ""])
    notes = as_list(boundary_map.get("summary", {}).get("boundary_risk_notes") if isinstance(boundary_map.get("summary"), dict) else [])
    if notes:
        for note in notes:
            lines.append(f"- {scalar(note)}")
    else:
        lines.append("- None.")
    lines.append("")

    lines.extend(["## Recommended Next Action", "", scalar(boundary_map.get("summary", {}).get("recommended_next_action")), ""])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("Vol.8 feedback-to-roadmap boundary map generated.")
    print(f"- source_items: {ITEMS_PATH.relative_to(REPO_ROOT)}")
    print(f"- source_boundary_map: {MAP_PATH.relative_to(REPO_ROOT)}")
    print(f"- output: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"- mapped_items: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
