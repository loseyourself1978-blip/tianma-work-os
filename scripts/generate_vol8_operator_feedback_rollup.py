#!/usr/bin/env python3
"""Generate the Vol.8 local operator feedback rollup Markdown.

The generator reads local fixture files only, uses the Python standard library,
and never accesses network, credentials, live data, or runtime mutation paths.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ITEMS_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_operator_feedback_review_sample.json"
ROLLUP_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_operator_feedback_rollup.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "runtime" / "VOL8_LOCAL_OPERATOR_FEEDBACK_ROLLUP_v0.1.md"


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
    rollup = load_json(ROLLUP_PATH)
    if not isinstance(raw_items, list):
        raise ValueError(f"{ITEMS_PATH.relative_to(REPO_ROOT)} must contain a feedback item array")
    if not isinstance(rollup, dict):
        raise ValueError(f"{ROLLUP_PATH.relative_to(REPO_ROOT)} must contain a rollup object")

    items = [item for item in raw_items if isinstance(item, dict)]
    category_counts = count_by(items, "category")
    severity_counts = count_by(items, "severity")
    routing_counts = count_by(items, "routing")
    forbidden_count = sum(1 for item in items if item.get("category") == "forbidden_scope_request")
    live_runtime_execution_count = sum(
        1
        for item in items
        if item.get("category") in {"live_runtime_request", "execution_related_request"}
        or item.get("network_or_api_claim") is True
        or item.get("execution_or_mutation_claim") is True
    )
    accepted_static_count = sum(
        1
        for item in items
        if item.get("routing") not in {"future_roadmap_backlog", "reject_forbidden_scope", "defer_until_future_readiness_gate"}
    )
    roadmap_only_count = sum(1 for item in items if item.get("roadmap_only") is True)
    boundary_notes = [
        f"{scalar(item.get('feedback_id'))}: {scalar(item.get('feedback_title'))}"
        for item in items
        if item.get("boundary_risk") is True
    ]

    lines: list[str] = [
        "# Vol.8 Local Operator Feedback Rollup v0.1",
        "",
        f"Phase: `{scalar(rollup.get('phase'))}`",
        "",
        f"Baseline commit: `{scalar(rollup.get('baseline_commit'))}`",
        "",
        f"Runtime records baseline: `{scalar(rollup.get('runtime_records'))}`",
        "",
        f"Static shell path: `{scalar(rollup.get('static_shell_path'))}`",
        "",
        "Customer-facing readiness: `false`",
        "",
        "This rollup is generated from local fixtures only. It does not imply live data, API access, execution capability, broker/Binance connectivity, credentials, auth, mutation, or customer-facing readiness.",
        "",
        "## Summary",
        "",
        f"- Total feedback items: `{len(items)}`",
        f"- Forbidden-scope requests count: `{forbidden_count}`",
        f"- Live/runtime/execution requests count: `{live_runtime_execution_count}`",
        f"- Accepted static-shell feedback count: `{accepted_static_count}`",
        f"- Roadmap-only feedback count: `{roadmap_only_count}`",
        "",
    ]

    lines.extend(render_counts("Count By Category", category_counts))
    lines.extend(render_counts("Count By Severity", severity_counts))
    lines.extend(render_counts("Count By Routing", routing_counts))

    lines.extend(["## Boundary Risk Notes", ""])
    for note in boundary_notes:
        lines.append(f"- {note}")
    if not boundary_notes:
        lines.append("- None.")
    lines.append("")

    lines.extend(["## Recommended Next Action", "", scalar(rollup.get("summary", {}).get("recommended_next_action")), ""])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("Vol.8 operator feedback rollup generated.")
    print(f"- source_items: {ITEMS_PATH.relative_to(REPO_ROOT)}")
    print(f"- source_rollup: {ROLLUP_PATH.relative_to(REPO_ROOT)}")
    print(f"- output: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"- feedback_items: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
