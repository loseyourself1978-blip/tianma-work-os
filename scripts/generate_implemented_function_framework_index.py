#!/usr/bin/env python3
"""Generate the implemented function framework index Markdown.

The generator reads a local fixture and writes a deterministic Markdown output.
It uses only the Python standard library and never accesses the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = REPO_ROOT / "mock_consumers" / "ldd" / "implemented_function_framework_index.json"
OUTPUT_PATH = REPO_ROOT / "docs" / "runtime" / "IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX_v0.1.md"


def load_index() -> dict[str, Any]:
    value = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{SOURCE_PATH.relative_to(REPO_ROOT)} must contain a JSON object")
    return value


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def compact_paths(paths: list[Any], limit: int = 3) -> str:
    clean = [f"`{scalar(path)}`" for path in paths if scalar(path)]
    if not clean:
        return "n/a"
    if len(clean) > limit:
        visible = clean[:limit]
        visible.append(f"+{len(clean) - limit} more")
        return "<br>".join(visible)
    return "<br>".join(clean)


def status_label(value: str) -> str:
    return value.replace("_", " ")


def render(data: dict[str, Any]) -> str:
    frameworks = as_list(data.get("frameworks"))
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}

    lines: list[str] = [
        "# Implemented Function Framework Index v0.1",
        "",
        f"Generated for: `{scalar(data.get('generated_for_phase'))}`",
        "",
        f"Baseline commit: `{scalar(data.get('baseline_commit'))}`",
        "",
        f"Runtime records baseline: `{scalar(data.get('runtime_records'))}`",
        "",
        "Customer-facing readiness: `false`",
        "",
        "This index lists repo-backed implemented frameworks only. It does not claim customer-facing readiness, live integration, runtime mutation, or execution readiness.",
        "",
        "| # | Functional Framework | Category | Implemented Since | Latest Verified | Current Status | Key Artifacts | Next Improvement |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for index, item in enumerate(frameworks, start=1):
        if not isinstance(item, dict):
            continue
        implemented = f"{scalar(item.get('implemented_since_phase'))}<br>{scalar(item.get('implemented_since_version'))}"
        verified = f"{scalar(item.get('latest_verified_phase'))}<br>`{scalar(item.get('latest_verified_commit'))}`"
        artifacts = compact_paths(as_list(item.get("artifact_paths")))
        row = [
            str(index),
            scalar(item.get("framework_name")),
            scalar(item.get("category")),
            implemented,
            verified,
            status_label(scalar(item.get("status"))),
            artifacts,
            scalar(item.get("next_improvement")),
        ]
        lines.append("| " + " | ".join(table_cell(cell) for cell in row) + " |")

    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Total implemented frameworks: `{scalar(summary.get('total_implemented_frameworks'))}`",
            f"- Customer-facing frameworks: `{scalar(summary.get('customer_facing_frameworks'))}`",
            f"- Live/runtime/execution frameworks: `{scalar(summary.get('live_runtime_execution_frameworks'))}`",
            f"- Fixture/static/read-only frameworks count: `{scalar(summary.get('fixture_static_read_only_frameworks'))}`",
            f"- Validation-backed frameworks count: `{scalar(summary.get('validation_backed_frameworks'))}`",
            "",
            "## Notes",
            "",
        ]
    )

    for note in as_list(data.get("notes")):
        lines.append(f"- {scalar(note)}")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    data = load_index()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(data), encoding="utf-8")
    print("Implemented function framework index generated.")
    print(f"- source: {SOURCE_PATH.relative_to(REPO_ROOT)}")
    print(f"- output: {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    print(f"- frameworks: {len(as_list(data.get('frameworks')))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
