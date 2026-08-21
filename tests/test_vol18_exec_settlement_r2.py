from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from twos_runtime.codex_exec_bridge import (
    ExecutionHandle,
    ExecutionIdentity,
    load_jsonl_final_message_candidate,
    prepare_execution,
    run_execution,
)


def _identity() -> ExecutionIdentity:
    return ExecutionIdentity(
        owner_id=1,
        run_id=2,
        task_id=3,
        task_version=1,
        pack_id=4,
        pack_version=1,
        coding_assignment_id=5,
        coding_assignment_version=1,
        verification_assignment_id=6,
        verification_assignment_version=1,
        routing_snapshot_identity="routing-r2",
        source_snapshot_identity="source-r2",
        connectivity_evidence_identity="connectivity-r2",
        requested_model_identifier="fixture-model",
        executable_fingerprint="executable-r2",
        execution_location_identity="execution-r2",
        source_remote_fingerprint=hashlib.sha256(b"remote").hexdigest(),
        git_boundary_fingerprint=hashlib.sha256(b"git").hexdigest(),
        workspace_snapshot_digest=hashlib.sha256(b"workspace").hexdigest(),
    )


def _prepare(
    tmp_path: Path,
    source: str,
    *,
    timeout_seconds: float = 3.0,
) -> ExecutionHandle:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    working = tmp_path / "working"
    working.mkdir(mode=0o700)
    script = tmp_path / "fixture.py"
    script.write_text(source, encoding="utf-8")
    script.chmod(0o700)
    final_message = tmp_path / "spool" / "coding-r2" / "final-message.txt"
    return prepare_execution(
        tmp_path / "spool",
        phase_key="coding-r2",
        phase="coding",
        identity=_identity(),
        argv=(
            str(Path(sys.executable).resolve(strict=True)),
            str(script),
            str(final_message),
        ),
        stdin_payload=b"approved input\n",
        working_directory=working,
        timeout_seconds=timeout_seconds,
        heartbeat_interval_seconds=0.02,
    )


def _success_events(message: str = "settled result") -> str:
    return f'''
events = [
    {{"type": "thread.started", "thread_id": "thread-r2"}},
    {{"type": "turn.started", "turn_id": "turn-r2"}},
    {{"type": "item.completed", "turn_id": "turn-r2", "item": {{"id": "message-r2", "type": "agent_message", "text": {message!r}}}}},
    {{"type": "turn.completed", "turn_id": "turn-r2"}},
]
for event in events:
    print(json.dumps(event), flush=True)
'''


def test_receipt_waits_for_stream_eof_and_delayed_sidecar_settlement(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import subprocess
import sys

message = "settled result"
writer = "import pathlib,sys,time;time.sleep(0.15);pathlib.Path(sys.argv[1]).write_text(sys.argv[2],encoding='utf-8')"
subprocess.Popen(
    [sys.executable, "-c", writer, sys.argv[1], message],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    start_new_session=True,
)
''' + _success_events()
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["process_exited_at"]
    assert receipt["stream_settlement"]["stdout_eof"] is True
    assert receipt["stream_settlement"]["stderr_eof"] is True
    assert receipt["final_message"]["settlement"]["status"] == "VALID"
    assert receipt["final_message"]["settlement"]["waited_ms"] >= 100
    assert receipt["terminal_at"] >= receipt["process_exited_at"]


def test_missing_sidecar_is_blocked_but_exposes_only_a_higher_layer_recovery_candidate(
    tmp_path: Path,
) -> None:
    recovery_result = json.dumps(
        {
            "schema": "twos.coding_handoff.v1",
            "status": "completed",
            "summary": "recovery result",
        },
        separators=(",", ":"),
    )
    source = "import json\n" + _success_events(recovery_result)
    handle = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_message_missing"
    assert receipt["outcome_facts"]["terminal_success"] is True
    assert receipt["outcome_facts"]["jsonl_recovery_candidate"] is True
    recovery = receipt["final_message"]["jsonl_recovery"]
    assert recovery["schema_validation"] == "PHASE_SCHEMA_VALID"
    assert recovery["identity_validation"] == "REQUIRED_BY_HIGHER_LAYER"
    assert load_jsonl_final_message_candidate(handle) == recovery_result


@pytest.mark.parametrize(
    ("tail", "expected_reason"),
    [
        ('{"type":"turn.completed"', "stdout_trailing_partial_unresolved"),
        ('{"type":"future.partial"', "stdout_trailing_partial_unresolved"),
    ],
)
def test_unresolved_partial_jsonl_never_becomes_success(
    tmp_path: Path, tail: str, expected_reason: str
) -> None:
    source = f'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("partial result", encoding="utf-8")
print(json.dumps({{"type": "thread.started", "thread_id": "partial-thread"}}))
print(json.dumps({{"type": "turn.started", "turn_id": "partial-turn"}}))
print(json.dumps({{"type": "item.completed", "turn_id": "partial-turn", "item": {{"type": "agent_message", "text": "partial result"}}}}))
sys.stdout.write({tail!r})
sys.stdout.flush()
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == expected_reason
    assert receipt["stdout_jsonl"]["trailing_partial_line_present"] is True
    assert receipt["stdout_jsonl"]["trailing_partial_line_resolved"] is False
    assert receipt["outcome_facts"]["terminal_success"] is False


def test_contradictory_terminal_events_cannot_publish_success(tmp_path: Path) -> None:
    source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("contradiction", encoding="utf-8")
events = [
    {"type": "thread.started", "thread_id": "thread-conflict"},
    {"type": "turn.started", "turn_id": "turn-conflict"},
    {"type": "item.completed", "turn_id": "turn-conflict", "item": {"type": "agent_message", "text": "contradiction"}},
    {"type": "turn.completed", "turn_id": "turn-conflict"},
    {"type": "turn.failed", "turn_id": "turn-conflict"},
]
for event in events:
    print(json.dumps(event))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "terminal_event_contradiction"
    assert receipt["outcome_facts"]["terminal_contradiction"] is True
    assert receipt["stdout_jsonl"]["turn_completed_count"] == 1
    assert receipt["stdout_jsonl"]["turn_failed_count"] == 1


def test_valid_terminal_json_object_without_newline_is_resolved_at_eof(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
message = "resolved partial"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "partial-ok-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "partial-ok-turn"}))
print(json.dumps({"type": "item.completed", "turn_id": "partial-ok-turn", "item": {"type": "agent_message", "text": message}}))
sys.stdout.write(json.dumps({"type": "turn.completed", "turn_id": "partial-ok-turn"}))
sys.stdout.flush()
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["stdout_jsonl"]["trailing_partial_line_present"] is True
    assert receipt["stdout_jsonl"]["trailing_partial_line_resolved"] is True
    assert receipt["stdout_jsonl"]["eof_received"] is True


def test_fatal_error_contradicts_turn_completed_but_nonfatal_errors_do_not(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
message = "must not pass"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
events = [
    {"type": "thread.started", "thread_id": "error-thread"},
    {"type": "turn.started", "turn_id": "error-turn"},
    {"type": "error", "fatal": True, "message": "terminal provider error"},
    {"type": "item.completed", "turn_id": "error-turn", "item": {"type": "agent_message", "text": message}},
    {"type": "turn.completed", "turn_id": "error-turn"},
]
for event in events:
    print(json.dumps(event))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "terminal_event_contradiction"
    assert receipt["stdout_jsonl"]["fatal_error_count"] == 1
    assert receipt["outcome_facts"]["terminal_success"] is False


def test_turn_failed_is_terminal_failure_even_when_process_exits_zero(
    tmp_path: Path,
) -> None:
    source = r'''
import json
print(json.dumps({"type": "thread.started", "thread_id": "failed-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "failed-turn"}))
print(json.dumps({"type": "turn.failed", "turn_id": "failed-turn"}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["process_exit_code"] == 0
    assert receipt["terminal_state"] == "FAILED"
    assert receipt["terminal_reason"] == "turn_failed"
    assert receipt["outcome_facts"]["terminal_failure"] is True


def test_timeout_truth_is_preserved_independently_from_integrity(
    tmp_path: Path,
) -> None:
    source = "import time\ntime.sleep(2)\n"
    receipt = run_execution(_prepare(tmp_path, source, timeout_seconds=0.08))

    assert receipt["terminal_state"] == "TIMED_OUT"
    assert receipt["terminal_reason"] == "timeout"
    assert receipt["outcome_facts"]["timed_out"] is True
    assert receipt["outcome_facts"]["integrity_blocked"] is True
    assert "terminal_event_unresolved" in receipt["outcome_facts"]["integrity_reasons"]
    assert receipt["process_exit_code"] is not None
    assert receipt["process_exited_at"]
