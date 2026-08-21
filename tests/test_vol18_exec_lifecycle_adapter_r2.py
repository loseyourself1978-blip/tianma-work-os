from __future__ import annotations

import json
from pathlib import Path

from twos_runtime.codex_adapter import (
    CodexExecutionManager,
    _valid_coding_handoff_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_exact_pack_stdin_contains_phase_contract_without_wrapper() -> None:
    adapter_source = (ROOT / "twos_runtime" / "codex_adapter.py").read_text(
        encoding="utf-8"
    )
    pack_source = (ROOT / "twos_runtime" / "self_hosting.py").read_text(
        encoding="utf-8"
    )

    assert adapter_source.count("prompt=pack_content") >= 2
    assert "_coding_phase_prompt(pack_content)" not in adapter_source
    assert "pack_content = launch_run.pack.content" in adapter_source
    assert "## Execution Phase Contract" in pack_source
    assert "Do not launch, delegate, spawn, or wait for the independent Verification process." in pack_source
    assert "TWOS alone starts the separately bound, read-only Verification process" in pack_source
    assert "twos.coding_handoff.v1" in pack_source


def test_persisted_jsonl_neutralizes_private_reasoning_content() -> None:
    private_text = "private scratchpad that must never be persisted"
    source = "\n".join(
        [
            json.dumps(
                {
                    "type": "reasoning.delta",
                    "thread_id": "thread-secret",
                    "turn_id": "turn-1",
                    "item": {
                        "id": "reasoning-1",
                        "type": "reasoning",
                        "text": private_text,
                    },
                    "delta": private_text,
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "Public final response",
                    },
                }
            ),
        ]
    )

    persisted = CodexExecutionManager._sanitize_process_output(source)
    events = [json.loads(line) for line in persisted.splitlines()]

    assert private_text not in persisted
    assert events[0]["summary"] == "Codex is reasoning"
    assert events[0]["item"] == {"id": "reasoning-1", "type": "reasoning"}
    assert events[0]["thread_id"].startswith("sha256:")
    assert events[1]["item"]["text"] == "Public final response"


def test_jsonl_coding_recovery_requires_exact_bounded_handoff_schema() -> None:
    assert _valid_coding_handoff_contract(
        json.dumps(
            {
                "schema": "twos.coding_handoff.v1",
                "status": "completed",
                "summary": "Coding completed and validation passed.",
            }
        )
    )
    assert not _valid_coding_handoff_contract("Coding completed")
    assert not _valid_coding_handoff_contract(
        json.dumps(
            {
                "schema": "twos.coding_handoff.v1",
                "status": "completed",
                "summary": "ambiguous",
                "unexpected": True,
            }
        )
    )
