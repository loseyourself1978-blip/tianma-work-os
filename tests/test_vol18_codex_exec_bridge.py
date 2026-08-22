from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from twos_runtime.codex_exec_bridge import (
    BRIDGE_POLICY,
    CodexExecBridgeError,
    ExecutionHandle,
    ExecutionIdentity,
    handle_from_ticket_path,
    launch_sidecar,
    load_execution_state,
    load_final_message,
    load_launch_info,
    load_stream_bytes,
    load_terminal_receipt,
    load_ticket,
    prepare_execution,
    prepare_spool_root,
    process_identity_matches,
    replay_stdout_to_collector,
    request_cancel,
    run_execution,
)


def _real_collector():
    from twos_runtime import codex_adapter as codex_adapter_module

    return codex_adapter_module._CodexJsonlEvidenceCollector(
        "fixture-approved-model"
    )


def _identity(**overrides: object) -> ExecutionIdentity:
    values: dict[str, object] = {
        "owner_id": 101,
        "run_id": 202,
        "task_id": 303,
        "task_version": 4,
        "pack_id": 505,
        "pack_version": 6,
        "coding_assignment_id": 707,
        "coding_assignment_version": 8,
        "verification_assignment_id": 909,
        "verification_assignment_version": 10,
        "routing_snapshot_identity": "routing-fixture-001",
        "source_snapshot_identity": "source-fixture-001",
        "connectivity_evidence_identity": "connectivity-fixture-001",
        "requested_model_identifier": "fixture-approved-model",
        "executable_fingerprint": "fixture-executable-fingerprint",
        "execution_location_identity": "fixture-execution-location",
        "source_remote_fingerprint": hashlib.sha256(b"fixture-remote").hexdigest(),
        "git_boundary_fingerprint": hashlib.sha256(b"fixture-git-boundary").hexdigest(),
        "workspace_snapshot_digest": hashlib.sha256(b"fixture-workspace").hexdigest(),
        "pre_verification_workspace_digest": None,
    }
    values.update(overrides)
    return ExecutionIdentity(**values)  # type: ignore[arg-type]


def _write_script(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)
    return path


def _prepare(
    tmp_path: Path,
    script_source: str,
    *,
    phase_key: str = "coding-202",
    script_arguments: tuple[str, ...] = (),
    stdin_payload: bytes = b"approved pack\n",
    output_limit_bytes: int = 64 * 1024,
    timeout_seconds: float = 5.0,
    heartbeat_interval_seconds: float = 0.05,
    phase: str = "coding",
    identity: ExecutionIdentity | None = None,
    environment_keys: tuple[str, ...] | None = None,
) -> tuple[ExecutionHandle, Path, Path]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    working = tmp_path / "working"
    working.mkdir(mode=0o700)
    script = _write_script(tmp_path / f"{phase_key}.py", script_source)
    spool = tmp_path / "spool"
    final_message = spool / phase_key / "final-message.txt"
    argv = (
        str(Path(sys.executable).resolve(strict=True)),
        str(script),
        str(final_message),
        *script_arguments,
    )
    handle = prepare_execution(
        spool,
        phase_key=phase_key,
        phase=phase,
        identity=identity
        or _identity(
            pre_verification_workspace_digest=(
                hashlib.sha256(b"fixture-pre-verification-workspace").hexdigest()
                if phase == "verification"
                else None
            )
        ),
        argv=argv,
        stdin_payload=stdin_payload,
        working_directory=working,
        output_limit_bytes=output_limit_bytes,
        timeout_seconds=timeout_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        **({"environment_keys": environment_keys} if environment_keys is not None else {}),
    )
    return handle, working, final_message


def _wait_for_state(
    handle: ExecutionHandle,
    states: set[str],
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = load_execution_state(handle)
        if last is not None and last.get("state") in states:
            return last
        time.sleep(0.02)
    raise AssertionError(f"state did not reach {states}; last={last}")


def _wait_for_terminal(
    handle: ExecutionHandle,
    *,
    timeout: float = 8.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        receipt = load_terminal_receipt(handle)
        if receipt is not None:
            return receipt
        time.sleep(0.02)
    raise AssertionError("terminal receipt did not appear")


def test_ticket_is_identity_bound_owner_only_atomic_and_idempotent(tmp_path: Path) -> None:
    source = "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('ok', encoding='utf-8')\n"
    handle, working, final_message = _prepare(tmp_path, source)
    ticket = load_ticket(handle)

    assert ticket["policy"] == BRIDGE_POLICY
    assert ticket["identity"] == _identity().as_dict()
    assert ticket["argv"] == [
        str(Path(sys.executable).resolve(strict=True)),
        str(tmp_path / "coding-202.py"),
        str(final_message),
    ]
    assert ticket["working_directory"] == str(working)
    assert ticket["ticket_digest"] == handle.ticket_digest
    assert ticket["phase_preflight"] == {
        "source_remote_fingerprint": _identity().source_remote_fingerprint,
        "git_boundary_fingerprint": _identity().git_boundary_fingerprint,
        "workspace_snapshot_digest": _identity().workspace_snapshot_digest,
        "pre_verification_workspace_digest": None,
    }
    assert stat.S_IMODE(handle.spool_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(handle.phase_directory.stat().st_mode) == 0o700
    for name in ("stdin.bin", "ticket.json", "ticket.seal.json"):
        assert stat.S_IMODE((handle.phase_directory / name).stat().st_mode) == 0o600
        assert (handle.phase_directory / name).stat().st_nlink == 1

    repeated = prepare_execution(
        handle.spool_root,
        phase_key=handle.phase_key,
        phase="coding",
        identity=_identity(),
        argv=tuple(ticket["argv"]),
        stdin_payload=b"approved pack\n",
        working_directory=working,
        output_limit_bytes=64 * 1024,
        timeout_seconds=5,
        heartbeat_interval_seconds=0.05,
    )
    assert repeated == handle

    with pytest.raises(CodexExecBridgeError):
        prepare_execution(
            handle.spool_root,
            phase_key=handle.phase_key,
            phase="coding",
            identity=_identity(run_id=999),
            argv=tuple(ticket["argv"]),
            stdin_payload=b"approved pack\n",
            working_directory=working,
            output_limit_bytes=64 * 1024,
            timeout_seconds=5,
            heartbeat_interval_seconds=0.05,
        )


def test_exact_argv_is_shell_free_and_replay_uses_existing_collector(tmp_path: Path) -> None:
    sentinel = tmp_path / "must-not-exist"
    injection = f";touch {sentinel}"
    source = r'''
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text("Codex final response", encoding="utf-8")
events = [
    {"type": "thread.started", "thread_id": "thread-1", "actual_model_identifier": "fixture-approved-model"},
    {"type": "turn.started", "turn_id": "turn-1"},
    {"type": "error", "message": "transient connectivity observation", "fatal": False},
    {"type": "item.completed", "item": {"id": "message-1", "type": "agent_message", "text": "Codex final response"}},
    {"type": "turn.completed", "turn_id": "turn-1", "usage": {"input_tokens": 1, "output_tokens": 2}},
]
for event in events:
    print(json.dumps(event), flush=True)
sys.stderr.write("bounded stderr evidence")
assert sys.argv[2].startswith(";touch ")
'''
    handle, _, _ = _prepare(tmp_path, source, script_arguments=(injection,))
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["process_exit_code"] == 0
    assert not sentinel.exists()
    assert load_final_message(handle) == "Codex final response"
    assert b"bounded stderr evidence" == load_stream_bytes(handle, stream="stderr")
    assert load_stream_bytes(handle, stream="stdout").startswith(b'{"type": "thread.started"')

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector, chunk_size=7)
    assert replay.stdout_truncated is False
    assert replay.terminal_event_replayed is False
    assert collector.structured_success is True
    assert collector.actual_model_identifier == "fixture-approved-model"
    assert collector.final_agent_message == "Codex final response"
    assert receipt["stdout_jsonl"]["terminal_event_count"] == 1
    assert receipt["stdout_jsonl"]["type_histogram"]["error"] == 1
    assert receipt["stdout_jsonl"]["last_terminal_event_type"] == "turn.completed"


def test_failed_turn_without_agent_message_preserves_verified_terminal_evidence(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text("model rejected", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "failed-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "failed-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "failed-error", "type": "error", "message": "model rejected"}}))
print(json.dumps({"type": "turn.failed", "turn_id": "failed-turn", "error": {"message": "model rejected"}}))
raise SystemExit(2)
'''
    handle, _, _ = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "FAILED"
    assert receipt["process_exit_code"] == 2
    assert receipt["stdout_jsonl"]["agent_message_count"] == 0
    assert receipt["stdout_jsonl"]["terminal_event_count"] == 1
    assert receipt["stdout_jsonl"]["last_terminal_event_type"] == "turn.failed"

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector)
    assert replay.collection_incomplete is False
    assert collector.collection_incomplete is False
    assert collector.lifecycle_conflict is False
    assert collector.thread_started is True
    assert collector.turn_started is True
    assert collector.turn_failed is True
    assert collector.terminal_turn_status == "failed"


def test_combined_output_is_bounded_while_both_streams_are_fully_drained(tmp_path: Path) -> None:
    source = r'''
import json
import os
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text("done", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "bounded-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "bounded-turn"}))
for _ in range(64):
    os.write(1, (json.dumps({"type": "item.updated", "payload": "x" * 8000}) + "\n").encode())
    os.write(2, b"y" * 8192)
print(json.dumps({"type": "item.completed", "item": {"id": "bounded-message", "type": "agent_message", "text": "done"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "bounded-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source, output_limit_bytes=4096)
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "COMPLETED"
    combined = receipt["combined_output"]
    assert combined["observed_bytes"] > 64 * 8000 * 2
    assert combined["retained_bytes"] == 4096
    assert len(load_stream_bytes(handle, stream="stdout")) + len(
        load_stream_bytes(handle, stream="stderr")
    ) == 4096
    assert receipt["stdout"]["truncated"] or receipt["stderr"]["truncated"]
    histogram_count = sum(receipt["chunk_histogram"]["stdout"].values()) + sum(
        receipt["chunk_histogram"]["stderr"].values()
    )
    assert histogram_count > 2
    assert receipt["stream_offsets"]["stdout_observed"] > 64 * 8000
    assert receipt["stream_offsets"]["stderr_observed"] == 64 * 8192


def test_ten_thousand_additive_events_preserve_authenticated_terminal_replay(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text("terminal result", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "thread-many", "actual_model_identifier": "fixture-approved-model"}))
print(json.dumps({"type": "turn.started", "turn_id": "turn-many"}))
print(json.dumps({"type": "error", "message": "nonterminal observation", "fatal": False}))
for index in range(10_000):
    print(json.dumps({"type": "item.updated", "item": {"id": f"item-{index}"}}))
print(json.dumps({"type": "item.completed", "item": {"id": "message-many", "type": "agent_message", "text": "terminal result"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "turn-many"}))
'''
    handle, _, _ = _prepare(tmp_path, source, output_limit_bytes=2048)
    receipt = run_execution(handle)
    jsonl = receipt["stdout_jsonl"]

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["stdout"]["truncated"] is True
    assert jsonl["event_count"] == 10_005
    assert jsonl["type_histogram"]["item.updated"] == 10_000
    assert jsonl["type_histogram"]["error"] == 1
    assert jsonl["terminal_event_count"] == 1
    assert jsonl["last_terminal_event_type"] == "turn.completed"
    assert jsonl["terminal_event_within_retained_prefix"] is False
    assert jsonl["terminal_event"]["relative_path"] == "stdout-terminal-event.jsonl"

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector, chunk_size=31)
    assert replay.stdout_truncated is True
    assert replay.agent_message_event_replayed is True
    assert replay.terminal_event_replayed is True
    assert replay.omitted_stdout_bytes > 0
    assert collector.structured_success is True
    assert collector.turn_completed is True
    assert collector.turn_failed is False
    assert collector.final_agent_message == "terminal result"


def test_heartbeat_records_exact_process_identity_and_terminal_receipt_is_last(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
import time

pathlib.Path(sys.argv[1]).write_text("slow result", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "slow-thread", "actual_model_identifier": "fixture-approved-model"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "slow-turn"}), flush=True)
time.sleep(0.35)
print(json.dumps({"type": "item.completed", "item": {"id": "slow-message", "type": "agent_message", "text": "slow result"}}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": "slow-turn"}), flush=True)
'''
    handle, _, _ = _prepare(tmp_path, source, heartbeat_interval_seconds=0.04)
    result: dict[str, object] = {}

    def execute() -> None:
        result.update(run_execution(handle))

    worker = threading.Thread(target=execute)
    worker.start()
    running = _wait_for_state(handle, {"RUNNING"})
    assert running["heartbeat_sequence"] >= 1
    assert running["sidecar_process_id"] == os.getpid()
    assert process_identity_matches(
        int(running["child_process_id"]),
        str(running["child_process_start_identity"]),
    )
    worker.join(5)
    assert not worker.is_alive()
    receipt = load_terminal_receipt(handle)
    assert receipt == result
    assert receipt is not None
    assert receipt["heartbeat_sequence"] >= 2
    assert receipt["terminal_state"] == "COMPLETED"
    assert (handle.phase_directory / "terminal.json").stat().st_mtime_ns >= (
        handle.phase_directory / "stdout-terminal-event.jsonl"
    ).stat().st_mtime_ns


@pytest.mark.parametrize(
    ("mode", "expected_state"),
    [("timeout", "TIMED_OUT"), ("cancel", "CANCELLED")],
)
def test_timeout_and_durable_cancel_stop_only_the_exact_process_tree(
    tmp_path: Path,
    mode: str,
    expected_state: str,
) -> None:
    source = r'''
import json
import pathlib
import sys
import time

pathlib.Path(sys.argv[1]).write_text("partial", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "wait-thread", "actual_model_identifier": "fixture-approved-model"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "wait-turn"}), flush=True)
time.sleep(10)
'''
    handle, _, _ = _prepare(
        tmp_path,
        source,
        phase_key=f"coding-{mode}",
        timeout_seconds=0.2 if mode == "timeout" else 5,
    )
    result: dict[str, object] = {}
    worker = threading.Thread(target=lambda: result.update(run_execution(handle)))
    worker.start()
    running = _wait_for_state(handle, {"RUNNING"})
    child_pid = int(running["child_process_id"])
    child_identity = str(running["child_process_start_identity"])
    if mode == "cancel":
        assert request_cancel(handle) == "requested"
        assert request_cancel(handle) == "replayed"
    worker.join(6)
    assert not worker.is_alive()
    assert result["terminal_state"] == expected_state
    assert request_cancel(handle) == "terminal"
    assert not process_identity_matches(child_pid, child_identity)


def test_cancel_read_settles_only_the_exact_internal_publication_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from twos_runtime import codex_exec_bridge as bridge_module

    source = "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('unused')\n"
    handle, _, _ = _prepare(tmp_path, source, phase_key="coding-cancel-publication")
    cancel_path = handle.phase_directory / "cancel.request.json"
    publish_name = bridge_module.re.compile(
        rf"^\.{bridge_module.re.escape(cancel_path.name)}\.[0-9a-f]{{32}}\.publish$"
    )
    publisher_linked = threading.Event()
    reader_observed_publication = threading.Event()
    release_publisher = threading.Event()
    original_unlink = bridge_module.os.unlink
    original_alias_matcher = bridge_module._internal_publication_alias_matches

    def unlink_with_publication_barrier(
        target: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        candidate = Path(os.fspath(target))
        if (
            candidate.parent == handle.phase_directory
            and publish_name.fullmatch(candidate.name)
        ):
            publisher_linked.set()
            assert release_publisher.wait(2)
        original_unlink(target, *args, **kwargs)  # type: ignore[arg-type]

    def observed_alias_matcher(path: Path, observed: os.stat_result) -> bool:
        matched = original_alias_matcher(path, observed)
        if matched:
            reader_observed_publication.set()
        return matched

    monkeypatch.setattr(bridge_module.os, "unlink", unlink_with_publication_barrier)
    monkeypatch.setattr(
        bridge_module,
        "_internal_publication_alias_matches",
        observed_alias_matcher,
    )
    writer_result: list[str] = []
    writer_errors: list[BaseException] = []
    reader_result: list[bool] = []
    reader_errors: list[BaseException] = []

    def publish_cancel() -> None:
        try:
            writer_result.append(request_cancel(handle))
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    def read_cancel() -> None:
        try:
            reader_result.append(bridge_module._cancel_requested(handle))
        except BaseException as exc:  # pragma: no cover - asserted below
            reader_errors.append(exc)

    publisher = threading.Thread(target=publish_cancel)
    publisher.start()
    assert publisher_linked.wait(2)
    assert cancel_path.stat().st_nlink == 2
    unrelated_publish = handle.phase_directory / (
        f".{cancel_path.name}.{'b' * 32}.publish"
    )
    unrelated_publish.write_text("losing publisher", encoding="utf-8")
    unrelated_publish.chmod(0o600)

    reader = threading.Thread(target=read_cancel)
    reader.start()
    assert reader_observed_publication.wait(2)
    release_publisher.set()
    publisher.join(2)
    reader.join(2)
    assert not publisher.is_alive()
    assert not reader.is_alive()
    assert writer_errors == []
    assert reader_errors == []
    assert writer_result == ["requested"]
    assert reader_result == [True]
    assert cancel_path.stat().st_nlink == 1

    monkeypatch.setattr(bridge_module.os, "unlink", original_unlink)
    monkeypatch.setattr(
        bridge_module,
        "_internal_publication_alias_matches",
        original_alias_matcher,
    )
    unrelated_publish.unlink()

    persistent_publish_alias = handle.phase_directory / (
        f".{cancel_path.name}.{'a' * 32}.publish"
    )
    os.link(cancel_path, persistent_publish_alias)
    with pytest.raises(CodexExecBridgeError) as persistent:
        bridge_module._cancel_requested(handle)
    assert persistent.value.code == "HARDLINK_REJECTED"
    persistent_publish_alias.unlink()

    arbitrary_alias = handle.phase_directory / "cancel-request-alias.json"
    os.link(cancel_path, arbitrary_alias)
    with pytest.raises(CodexExecBridgeError) as arbitrary:
        bridge_module._cancel_requested(handle)
    assert arbitrary.value.code == "HARDLINK_REJECTED"


def test_single_writer_lease_and_terminal_idempotency(tmp_path: Path) -> None:
    source = r'''
import json
import pathlib
import sys
import time
pathlib.Path(sys.argv[1]).write_text("ok", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "lease-thread"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "lease-turn"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"id": "lease-message", "type": "agent_message", "text": "ok"}}), flush=True)
time.sleep(0.4)
print(json.dumps({"type": "turn.completed", "turn_id": "lease-turn"}), flush=True)
'''
    handle, _, _ = _prepare(tmp_path, source)
    first: dict[str, object] = {}
    worker = threading.Thread(target=lambda: first.update(run_execution(handle)))
    worker.start()
    _wait_for_state(handle, {"RUNNING"})

    with pytest.raises(CodexExecBridgeError) as caught:
        run_execution(handle)
    assert caught.value.code == "PHASE_ALREADY_RUNNING"

    worker.join(5)
    assert first["terminal_state"] == "COMPLETED"
    assert run_execution(handle) == first


def test_traversal_symlink_hardlink_and_replacement_are_rejected(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir(mode=0o700)
    script = _write_script(tmp_path / "safe.py", "pass\n")
    argv = (str(Path(sys.executable).resolve(strict=True)), str(script))
    with pytest.raises(CodexExecBridgeError) as traversal:
        prepare_execution(
            tmp_path / "traversal-spool",
            phase_key="../escape",
            phase="coding",
            identity=_identity(),
            argv=argv,
            stdin_payload=b"",
            working_directory=working,
        )
    assert traversal.value.code == "PHASE_KEY_INVALID"

    real_root = tmp_path / "real-spool"
    real_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked-spool"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(CodexExecBridgeError) as symlink:
        prepare_spool_root(linked_root)
    assert symlink.value.code == "SYMLINK_REJECTED"

    source = "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('ok')\n"
    handle, _, _ = _prepare(tmp_path / "hardlink-case", source)
    os.link(handle.ticket_path, handle.phase_directory / "ticket-alias.json")
    with pytest.raises(CodexExecBridgeError) as hardlink:
        load_ticket(handle)
    assert hardlink.value.code == "HARDLINK_REJECTED"

    replacement_root = tmp_path / "replacement-case"
    replacement_root.mkdir()
    replacement_handle, _, _ = _prepare(replacement_root, source)
    run_execution(replacement_handle)
    stdout_path = replacement_handle.phase_directory / "stdout.bin"
    payload = stdout_path.read_bytes()
    replacement = replacement_handle.phase_directory / "replacement.bin"
    replacement.write_bytes(payload)
    replacement.chmod(0o600)
    os.replace(replacement, stdout_path)
    with pytest.raises(CodexExecBridgeError) as replaced:
        load_stream_bytes(replacement_handle, stream="stdout")
    assert replaced.value.code == "STREAM_REPLACED"


def test_final_message_is_owner_only_bounded_and_replacement_protected(tmp_path: Path) -> None:
    source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("owner result", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "owner-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "owner-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "owner-message", "type": "agent_message", "text": "owner result"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "owner-turn"}))
'''
    handle, _, final_message = _prepare(tmp_path, source)
    receipt = run_execution(handle)
    assert receipt["final_message"]["present"] is True
    assert stat.S_IMODE(final_message.stat().st_mode) == 0o600
    assert final_message.stat().st_nlink == 1
    assert load_final_message(handle) == "owner result"

    replacement = handle.phase_directory / "replacement-message.txt"
    replacement.write_text("owner result", encoding="utf-8")
    replacement.chmod(0o600)
    os.replace(replacement, final_message)
    with pytest.raises(CodexExecBridgeError) as caught:
        load_final_message(handle)
    assert caught.value.code == "FINAL_MESSAGE_REPLACED"


def test_detached_sidecar_survives_launcher_and_publishes_protected_receipt(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
import time

pathlib.Path(sys.argv[1]).write_text("detached result", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "detached-thread", "actual_model_identifier": "fixture-approved-model"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "detached-turn"}), flush=True)
time.sleep(0.2)
print(json.dumps({"type": "item.completed", "item": {"id": "detached-message", "type": "agent_message", "text": "detached result"}}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": "detached-turn"}), flush=True)
'''
    handle, _, _ = _prepare(tmp_path, source)
    launch = launch_sidecar(handle)
    assert launch.ticket_digest == handle.ticket_digest
    assert process_identity_matches(launch.process_id, launch.process_start_identity)
    assert load_launch_info(handle) == launch
    assert launch_sidecar(handle) == launch

    receipt = _wait_for_terminal(handle)
    assert receipt["terminal_state"] == "COMPLETED"
    assert load_final_message(handle) == "detached result"
    assert handle_from_ticket_path(handle.ticket_path) == handle
    assert stat.S_IMODE((handle.phase_directory / "terminal.json").stat().st_mode) == 0o600


def _launch_cleanup_fixture(
    tmp_path: Path,
    *,
    phase_key: str,
) -> tuple[ExecutionHandle, Path]:
    counter = tmp_path / f"{phase_key}-child-count.txt"
    source = r'''
import json
import pathlib
import sys

counter = pathlib.Path(sys.argv[2])
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1")
message = "launch cleanup completed"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "launch-cleanup-thread"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "launch-cleanup-turn"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"id": "launch-cleanup-message", "type": "agent_message", "text": message}}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": "launch-cleanup-turn"}), flush=True)
'''
    handle, _, _ = _prepare(
        tmp_path,
        source,
        phase_key=phase_key,
        script_arguments=(str(counter),),
    )
    return handle, counter


def test_sidecar_identity_capture_failure_reaps_unpublished_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    handle, counter = _launch_cleanup_fixture(
        tmp_path,
        phase_key="coding-launch-identity-cleanup",
    )
    spawned: list[object] = []
    original_popen = bridge_module.subprocess.Popen
    original_capture = bridge_module.capture_process_start_identity

    with monkeypatch.context() as scoped:
        def recording_popen(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            spawned.append(process)
            return process

        def missing_launch_identity(process_id: int) -> str:
            if spawned and process_id == spawned[-1].pid:  # type: ignore[attr-defined]
                return ""
            return original_capture(process_id)

        scoped.setattr(bridge_module.subprocess, "Popen", recording_popen)
        scoped.setattr(
            bridge_module,
            "capture_process_start_identity",
            missing_launch_identity,
        )
        with pytest.raises(CodexExecBridgeError) as blocked:
            launch_sidecar(handle)

    assert blocked.value.code == "SIDECAR_IDENTITY_UNAVAILABLE"
    assert len(spawned) == 1
    assert spawned[0].poll() is not None  # type: ignore[attr-defined]
    assert load_launch_info(handle) is None
    assert load_execution_state(handle) is None
    assert load_terminal_receipt(handle) is None
    assert not counter.exists()


def test_launch_record_publication_failure_reaps_sidecar_and_allows_fresh_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    handle, counter = _launch_cleanup_fixture(
        tmp_path,
        phase_key="coding-launch-publication-cleanup",
    )
    spawned: list[object] = []
    original_popen = bridge_module.subprocess.Popen
    original_create = bridge_module._create_immutable_json

    with monkeypatch.context() as scoped:
        def recording_popen(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            spawned.append(process)
            return process

        def fail_launch_publication(path: Path, value: object):
            if Path(path).name == "launch.json":
                raise OSError("injected launch publication failure")
            return original_create(path, value)

        scoped.setattr(bridge_module.subprocess, "Popen", recording_popen)
        scoped.setattr(
            bridge_module,
            "_create_immutable_json",
            fail_launch_publication,
        )
        with pytest.raises(CodexExecBridgeError) as blocked:
            launch_sidecar(handle)

    assert blocked.value.code == "LAUNCH_RECORD_PUBLISH_FAILED"
    assert len(spawned) == 1
    assert spawned[0].poll() is not None  # type: ignore[attr-defined]
    assert load_launch_info(handle) is None
    assert load_execution_state(handle) is None
    assert load_terminal_receipt(handle) is None
    assert not counter.exists()

    launch = launch_sidecar(handle)
    assert load_launch_info(handle) == launch
    receipt = _wait_for_terminal(handle)
    assert receipt["terminal_state"] == "COMPLETED"
    assert counter.read_text() == "1"


@pytest.mark.parametrize(
    ("mode", "expected_reason"),
    [
        ("missing", "final_message_missing"),
        ("mismatch", "final_message_jsonl_mismatch"),
    ],
)
def test_success_requires_final_sidecar_matching_last_jsonl_agent_message(
    tmp_path: Path,
    mode: str,
    expected_reason: str,
) -> None:
    source = r'''
import json
import pathlib
import sys

if sys.argv[2] == "mismatch":
    pathlib.Path(sys.argv[1]).write_text("different sidecar", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "binding-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "binding-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "binding-message", "type": "agent_message", "text": "authoritative JSONL result"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "binding-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source, script_arguments=(mode,))
    receipt = run_execution(handle)

    assert receipt["process_exit_code"] == 0
    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == expected_reason
    assert receipt["final_message"]["matches_last_agent_message"] is False


def test_large_agent_message_outside_retained_prefix_is_restored_for_replay(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys

message = "M" * 4096
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "large-thread", "actual_model_identifier": "fixture-approved-model"}))
print(json.dumps({"type": "turn.started", "turn_id": "large-turn"}))
for index in range(100):
    print(json.dumps({"type": "item.updated", "item": {"id": f"padding-{index}", "text": "p" * 100}}))
print(json.dumps({"type": "item.completed", "item": {"id": "large-message", "type": "agent_message", "text": message}}))
print(json.dumps({"type": "turn.completed", "turn_id": "large-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source, output_limit_bytes=2048)
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["final_message"]["normalized_size"] == 4096
    assert receipt["final_message"]["matches_last_agent_message"] is True
    assert receipt["stdout"]["truncated"] is True
    assert receipt["stdout_jsonl"]["agent_message_event_within_retained_prefix"] is False
    assert receipt["stdout_jsonl"]["agent_message_event"]["size"] > 2048

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector, chunk_size=37)
    assert replay.agent_message_event_replayed is True
    assert replay.terminal_event_replayed is True
    assert replay.collection_incomplete is False
    # Transport evidence remains complete while Owner-facing presentation is
    # intentionally bounded by the existing collector.
    assert collector.final_agent_message == "M" * 2000
    assert collector.structured_success is True


def test_presentation_collector_failure_does_not_replace_transport_receipt(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("transport result", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "transport-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "transport-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "transport-message", "type": "agent_message", "text": "transport result"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "transport-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    class BrokenPresentationCollector:
        incomplete = False

        def feed(self, _chunk: bytes) -> None:
            raise RuntimeError("presentation parser failed")

        def finish(self) -> None:
            return None

        def mark_incomplete(self) -> None:
            self.incomplete = True

    collector = BrokenPresentationCollector()
    replay = replay_stdout_to_collector(handle, collector)

    assert replay.collection_incomplete is True
    assert collector.incomplete is True
    assert replay.terminal_state == "COMPLETED"
    assert receipt["process_exit_code"] == 0
    assert load_terminal_receipt(handle)["process_exit_code"] == 0


def test_unknown_additive_jsonl_event_is_audited_and_does_not_displace_success(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
message = "future event accepted"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "future-thread", "actual_model_identifier": "fixture-approved-model"}))
print(json.dumps({"type": "turn.started", "turn_id": "future-turn"}))
print(json.dumps({"type": "future.progress.v2", "detail": {"percent": 50, "presentation": "optional"}}))
print(json.dumps({"type": "item.completed", "item": {"id": "future-message", "type": "agent_message", "text": message}}))
print(json.dumps({"type": "turn.completed", "turn_id": "future-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source)
    receipt = run_execution(handle)
    summary = receipt["stdout_jsonl"]

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["process_exit_code"] == 0
    assert summary["type_histogram"]["future.progress.v2"] == 1
    assert len(summary["unknown_samples"]) == 1
    sample = summary["unknown_samples"][0]
    assert sample["event_type"] == "future.progress.v2"
    assert set(sample) == {"event_type", "line_bytes", "line_sha256"}
    assert sample["line_bytes"] > 0
    assert len(sample["line_sha256"]) == 64
    assert "optional" not in json.dumps(sample)

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector)
    assert replay.collection_incomplete is False
    assert collector.structured_success is True
    assert collector.final_agent_message == "future event accepted"


def test_malformed_jsonl_blocks_integrity_without_erasing_process_exit_truth(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
message = "process exited successfully"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "malformed-thread", "actual_model_identifier": "fixture-approved-model"}))
print(json.dumps({"type": "turn.started", "turn_id": "malformed-turn"}))
print("{this is not JSON")
print(json.dumps({"type": "item.completed", "item": {"id": "malformed-message", "type": "agent_message", "text": message}}))
print(json.dumps({"type": "turn.completed", "turn_id": "malformed-turn"}))
'''
    handle, _, _ = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["process_exit_code"] == 0
    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "stdout_jsonl_malformed"
    assert receipt["stdout_jsonl"]["malformed_count"] == 1
    assert receipt["stdout_jsonl"]["terminal_event_count"] == 1
    assert receipt["final_message"]["matches_last_agent_message"] is True

    collector = _real_collector()
    replay = replay_stdout_to_collector(handle, collector)
    assert replay.terminal_state == "RESULT_INTEGRITY_BLOCKED"
    assert replay.collection_incomplete is True
    assert collector.collection_incomplete is True
    assert collector.structured_success is False
    assert load_terminal_receipt(handle)["process_exit_code"] == 0


def test_launch_pid_start_identity_mismatch_blocks_without_relaunch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    counter = tmp_path / "launch-count.txt"
    source = r'''
import json
import pathlib
import sys
import time
counter = pathlib.Path(sys.argv[2])
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1")
message = "one detached launch"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "launch-reuse-thread"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "launch-reuse-turn"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"id": "launch-reuse-message", "type": "agent_message", "text": message}}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": "launch-reuse-turn"}), flush=True)
time.sleep(0.5)
'''
    handle, _, _ = _prepare(
        tmp_path,
        source,
        phase_key="coding-launch-reuse",
        script_arguments=(str(counter),),
    )
    launch = launch_sidecar(handle)
    _wait_for_state(handle, {"RUNNING"})

    original_matches = bridge_module.process_identity_matches
    with monkeypatch.context() as scoped:
        scoped.setattr(
            bridge_module,
            "process_identity_matches",
            lambda pid, identity: (
                False
                if pid == launch.process_id
                else original_matches(pid, identity)
            ),
        )

        def unexpected_relaunch(*_args, **_kwargs):
            raise AssertionError("PID identity mismatch must never relaunch")

        scoped.setattr(bridge_module.subprocess, "Popen", unexpected_relaunch)
        with pytest.raises(CodexExecBridgeError) as blocked:
            launch_sidecar(handle)
    assert blocked.value.code == "SIDECAR_PROCESS_LOST"

    receipt = _wait_for_terminal(handle)
    assert receipt["process_exit_code"] == 0
    assert counter.read_text() == "1"
    assert load_ticket(handle)["ticket_digest"] == launch.ticket_digest


def test_child_state_pid_start_identity_mismatch_blocks_and_terminal_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    counter = tmp_path / "child-count.txt"
    source = r'''
import json
import pathlib
import sys
import time
counter = pathlib.Path(sys.argv[2])
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1")
message = "single child launch"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "child-reuse-thread"}), flush=True)
print(json.dumps({"type": "turn.started", "turn_id": "child-reuse-turn"}), flush=True)
print(json.dumps({"type": "item.completed", "item": {"id": "child-reuse-message", "type": "agent_message", "text": message}}), flush=True)
print(json.dumps({"type": "turn.completed", "turn_id": "child-reuse-turn"}), flush=True)
time.sleep(0.5)
'''
    handle, _, _ = _prepare(
        tmp_path,
        source,
        phase_key="coding-child-reuse",
        script_arguments=(str(counter),),
    )
    result: dict[str, object] = {}
    worker = threading.Thread(target=lambda: result.update(run_execution(handle)))
    worker.start()
    state = _wait_for_state(handle, {"RUNNING"})
    child_pid = int(state["child_process_id"])
    original_matches = bridge_module.process_identity_matches
    monkeypatch.setattr(
        bridge_module,
        "process_identity_matches",
        lambda pid, identity: (
            False if pid == child_pid else original_matches(pid, identity)
        ),
    )
    worker.join(5)
    assert not worker.is_alive()

    assert result["process_exit_code"] == 0
    assert result["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert result["terminal_reason"] == "process_identity_changed"
    assert counter.read_text() == "1"
    assert run_execution(handle) == result
    assert counter.read_text() == "1"


def test_phase_preflight_is_hash_only_and_verification_requires_its_workspace_digest(
    tmp_path: Path,
) -> None:
    success_source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("verified", encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "verification-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "verification-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "verification-message", "type": "agent_message", "text": "verified"}}))
print(json.dumps({"type": "turn.completed", "turn_id": "verification-turn"}))
'''
    verification_digest = hashlib.sha256(b"coded-workspace").hexdigest()
    identity = _identity(pre_verification_workspace_digest=verification_digest)
    handle, _, _ = _prepare(
        tmp_path / "valid-verification",
        success_source,
        phase="verification",
        phase_key="verification-202",
        identity=identity,
    )
    ticket = load_ticket(handle)
    assert ticket["phase_preflight"]["pre_verification_workspace_digest"] == verification_digest
    assert all(
        value is None or (isinstance(value, str) and len(value) == 64)
        for value in ticket["phase_preflight"].values()
    )

    with pytest.raises(CodexExecBridgeError) as missing:
        _prepare(
            tmp_path / "missing-verification",
            success_source,
            phase="verification",
            phase_key="verification-missing",
            identity=_identity(),
        )
    assert missing.value.code == "PREFLIGHT_EVIDENCE_MISSING"

    with pytest.raises(CodexExecBridgeError) as invalid:
        _identity(source_remote_fingerprint="https://credential@example.invalid/repo").as_dict()
    assert invalid.value.code == "PREFLIGHT_EVIDENCE_INVALID"

    with pytest.raises(CodexExecBridgeError) as wrong_phase:
        _prepare(
            tmp_path / "wrong-phase",
            success_source,
            identity=identity,
        )
    assert wrong_phase.value.code == "PREFLIGHT_EVIDENCE_PHASE_MISMATCH"


def test_detached_sidecar_inherits_approved_codex_environment_without_persisting_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-secret-never-persist"
    token = "test-token-never-persist"
    proxy = "http://acceptance-proxy.invalid:8080"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", token)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    source = r'''
import json
import os
import pathlib
import sys

assert os.environ["OPENAI_API_KEY"].startswith("test-secret-")
assert os.environ["CODEX_ACCESS_TOKEN"].startswith("test-token-")
assert os.environ["HTTPS_PROXY"].startswith("http://acceptance-proxy.invalid")
assert os.environ["NO_COLOR"] == "1"
assert os.environ["GIT_TERMINAL_PROMPT"] == "0"
assert os.environ["GIT_ALLOW_PROTOCOL"] == ""
message = "approved environment inherited"
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "environment-thread"}))
print(json.dumps({"type": "turn.started", "turn_id": "environment-turn"}))
print(json.dumps({"type": "item.completed", "item": {"id": "environment-message", "type": "agent_message", "text": message}}))
print(json.dumps({"type": "turn.completed", "turn_id": "environment-turn"}))
'''
    environment_keys = (
        "PATH",
        "HOME",
        "OPENAI_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "HTTPS_PROXY",
        "NO_COLOR",
        "GIT_TERMINAL_PROMPT",
        "GIT_ALLOW_PROTOCOL",
    )
    handle, _, _ = _prepare(
        tmp_path,
        source,
        phase_key="coding-environment",
        environment_keys=environment_keys,
    )
    ticket_text = handle.ticket_path.read_text(encoding="utf-8")
    assert all(key in ticket_text for key in environment_keys)
    assert secret not in ticket_text
    assert token not in ticket_text
    assert proxy not in ticket_text

    launch_sidecar(
        handle,
        child_environment={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "OPENAI_API_KEY": secret,
            "CODEX_ACCESS_TOKEN": token,
            "HTTPS_PROXY": proxy,
            "NO_COLOR": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "",
        },
    )
    receipt = _wait_for_terminal(handle)
    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["process_exit_code"] == 0
    for artifact in handle.phase_directory.iterdir():
        if artifact.is_file():
            payload = artifact.read_bytes()
            assert secret.encode() not in payload
            assert token.encode() not in payload
            assert proxy.encode() not in payload


def test_short_sensitive_environment_value_is_rejected_before_process_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_secret = "abc1234"
    source = (
        "import pathlib\n"
        "pathlib.Path('spawned.txt').write_text('unexpected', encoding='utf-8')\n"
    )
    handle, working, _ = _prepare(
        tmp_path,
        source,
        phase_key="coding-short-secret",
        environment_keys=("PATH", "HOME", "OPENAI_API_KEY"),
    )

    with pytest.raises(CodexExecBridgeError) as detached_error:
        launch_sidecar(
            handle,
            child_environment={
                "PATH": os.environ["PATH"],
                "HOME": os.environ["HOME"],
                "OPENAI_API_KEY": short_secret,
            },
        )
    assert detached_error.value.code == "ENVIRONMENT_VALUE_INVALID"
    assert load_launch_info(handle) is None
    assert not (working / "spawned.txt").exists()

    monkeypatch.setenv("OPENAI_API_KEY", short_secret)
    with pytest.raises(CodexExecBridgeError) as child_error:
        run_execution(handle)
    assert child_error.value.code == "ENVIRONMENT_VALUE_INVALID"
    assert not (working / "spawned.txt").exists()
    for artifact in handle.phase_directory.iterdir():
        if artifact.is_file():
            assert short_secret.encode() not in artifact.read_bytes()


def test_module_has_no_database_dependency_or_write_surface() -> None:
    source = (
        Path(__file__).parents[1] / "twos_runtime" / "codex_exec_bridge.py"
    ).read_text(encoding="utf-8")
    assert "sqlalchemy" not in source
    assert "Session(" not in source
    assert "git add" not in source
    assert "shell=True" not in source
