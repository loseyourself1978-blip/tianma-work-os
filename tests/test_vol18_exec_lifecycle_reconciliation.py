from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, inspect, select

from tests.test_vol18_result_intake import _run, result_intake_fixture
from twos_runtime.models import (
    CodexActivityAggregate,
    CodexActivityEvent,
    CodexExecutionAttempt,
    CodexLifecycleNotification,
    CodexLifecycleSnapshot,
    CodexResultEnvelope,
    CodexRunMonitor,
    SchemaVersion,
    Task,
    utc_now,
)
from twos_runtime.result_intake import ensure_run_monitor, reconcile_run_monitors
from twos_runtime.run_lifecycle import (
    LifecycleReconciliationError,
    _event_descriptor,
    _next_action,
    _read_activity_events,
    lifecycle_snapshot_out,
    reconcile_execution_attempt,
    settle_reconciliation_error,
)


def test_live_activity_distinguishes_progress_and_final_result_messages() -> None:
    progress = {
        "type": "item.completed",
        "item": {
            "id": "progress-1",
            "type": "agent_message",
            "text": "I will continue with validation.",
        },
    }
    final = {
        "type": "item.completed",
        "item": {
            "id": "final-1",
            "type": "agent_message",
            "text": json.dumps(
                {
                    "schema": "twos.coding_handoff.v1",
                    "status": "completed",
                    "summary": "Validation passed.",
                }
            ),
        },
    }

    assert _event_descriptor(progress, phase="CODING")[:3] == (
        "PROGRESS",
        "COMPLETED",
        "Codex progress message",
    )
    assert _event_descriptor(final, phase="CODING")[:3] == (
        "RESULT",
        "COMPLETED",
        "Codex final result message",
    )
    assert _next_action("RESULT_INTEGRITY_BLOCKED") == "Review blocker evidence"


def _terminal_evidence(
    tmp_path: Path,
    *,
    terminal_state: str = "RESULT_INTEGRITY_BLOCKED",
    terminal_reason: str = "final_message_jsonl_mismatch",
    terminal_blocker_code: str = "",
    jsonl_recovery_candidate: bool = False,
) -> tuple[dict[str, object], SimpleNamespace]:
    now = utc_now()
    phase_directory = tmp_path / "sealed-phase"
    phase_directory.mkdir(exist_ok=True)
    (phase_directory / "stdout.bin").write_bytes(b"")
    evidence: dict[str, object] = {
        "ticket_digest": "a" * 64,
        "receipt_digest": "b" * 64,
        "observation_digest": "c" * 64,
        "receipt_present": True,
        "process_id": 12345,
        "process_start_identity": "d" * 64,
        "process_live": False,
        "process_exit_known": True,
        "process_exit_code": 0,
        "process_exit_signal": None,
        "terminal_state": terminal_state,
        "terminal_reason": terminal_reason,
        "terminal_blocker_code": terminal_blocker_code,
        "started_at": now,
        "terminal_at": now,
        "stdout_offset": 4096,
        "stderr_offset": 128,
        "stdout_spool_bytes": 4096,
        "stderr_spool_bytes": 128,
        "stdout_eof": True,
        "stderr_eof": True,
        "trailing_partial_line_present": False,
        "trailing_partial_line_resolved": True,
        "terminal_event_observed": True,
        "terminal_event_type": "turn.completed",
        "terminal_event_identity": "e" * 64,
        "terminal_event_at": now,
        "turn_identity": "turn-fixture",
        "event_count": 4,
        "event_histogram": {
            "thread.started": 1,
            "turn.started": 1,
            "item.completed": 1,
            "turn.completed": 1,
        },
        "last_event_type": "turn.completed",
        "last_event_at": now,
        "sidecar_state": "MISSING" if jsonl_recovery_candidate else "MISMATCH",
        "sidecar_digest": "",
        "sidecar_size": None,
        "same_turn_final_message": True,
        "terminal_success": True,
        "terminal_failure": False,
        "terminal_contradiction": False,
        "timed_out": False,
        "cancelled": False,
        "phase": "CODING",
        "protected_spool_locator": str(phase_directory),
        "spool_locator_identity": "f" * 64,
        "jsonl_recovery_candidate": jsonl_recovery_candidate,
    }
    return evidence, SimpleNamespace(phase_directory=phase_directory)


@pytest.mark.parametrize(
    "blocker_code",
    (
        "FINAL_AGENT_MESSAGE_UNAVAILABLE",
        "SIDECAR_ATTEMPT_IDENTITY_MISMATCH",
        "FINAL_RESULT_SEMANTIC_MISMATCH",
        "FINAL_RESULT_SCHEMA_INVALID",
    ),
)
def test_bridge_terminal_blocker_code_is_authoritative_in_every_projection(
    tmp_path: Path,
    monkeypatch,
    blocker_code: str,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(
            tmp_path,
            terminal_blocker_code=blocker_code,
        )
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with fixture.client.app.state.session_factory() as session:
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == fixture.run_id
                )
            )
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            snapshot = session.scalar(
                select(CodexLifecycleSnapshot).where(
                    CodexLifecycleSnapshot.run_id == fixture.run_id
                )
            )
            assert attempt is not None and attempt.blocker_code == blocker_code
            assert monitor is not None and monitor.failure_code == blocker_code
            assert snapshot is not None and snapshot.blocker_code == blocker_code


def _prepare_running_monitor(fixture, tmp_path: Path):
    with fixture.client.app.state.session_factory() as session:
        run = _run(session, fixture)
        run.status = "running"
        run.structured_result = "{}"
        run.started_at = run.started_at or utc_now()
        task = session.get(Task, run.task_id)
        assert task is not None
        task.status = "running"
        monitor = ensure_run_monitor(session, fixture.owner_id, run)
        monitor.monitor_state = "RUNNING"
        monitor.result_source = "codex_exec_jsonl_spool"
        monitor.protected_result_locator = str(tmp_path / "spool")
        monitor.result_locator_identity = "1" * 64
        session.commit()


def test_vol18_006_lifecycle_migration_and_durable_entities(tmp_path: Path) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            assert "vol18.006" in set(
                session.scalars(select(SchemaVersion.version)).all()
            )
        assert {
            "codex_execution_attempts",
            "codex_lifecycle_snapshots",
            "codex_activity_events",
            "codex_activity_aggregates",
            "codex_lifecycle_notifications",
        } <= set(inspect(fixture.client.app.state.engine).get_table_names())


def test_terminal_integrity_blocker_settles_every_projection_atomically_and_idempotently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(tmp_path)
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        factory = fixture.client.app.state.session_factory
        for _ in range(2):
            with factory() as session:
                run = _run(session, fixture)
                monitor = session.scalar(
                    select(CodexRunMonitor).where(
                        CodexRunMonitor.run_id == fixture.run_id
                    )
                )
                assert monitor is not None
                result = reconcile_execution_attempt(
                    session, fixture.owner_id, run, monitor
                )
                assert result["state"] == "RESULT_INTEGRITY_BLOCKED"
                session.commit()

        with factory() as session:
            run = _run(session, fixture)
            task = session.get(Task, run.task_id)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == fixture.run_id
                )
            )
            snapshot = session.scalar(
                select(CodexLifecycleSnapshot).where(
                    CodexLifecycleSnapshot.run_id == fixture.run_id
                )
            )
            assert task is not None and task.status == "needs_review"
            assert task.acceptance_state == "needs_review"
            assert run.status == "blocked"
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_INTEGRITY_BLOCKED"
            assert attempt is not None
            assert attempt.attempt_state == "RESULT_INTEGRITY_BLOCKED"
            assert attempt.owner_id == fixture.owner_id
            assert attempt.task_id == run.task_id
            assert attempt.task_version == run.task_version
            assert attempt.pack_id == run.pack_id
            assert attempt.pack_version == run.pack.version
            assert attempt.coding_assignment_id == run.execution_assignment_id
            assert attempt.coding_assignment_version == run.execution_assignment.assignment_version
            assert attempt.verification_assignment_id == run.verification_assignment_id
            assert (
                attempt.verification_assignment_version
                == run.verification_assignment.assignment_version
            )
            assert attempt.routing_snapshot_identity == run.routing_snapshot_hash
            assert attempt.source_snapshot_identity == run.source_snapshot_digest
            assert snapshot is not None
            assert snapshot.lifecycle_state == "RESULT_INTEGRITY_BLOCKED"
            assert snapshot.process_live is False
            assert session.scalar(select(func.count(CodexResultEnvelope.id))) == 0
            assert session.scalar(select(func.count(CodexExecutionAttempt.id))) == 1
            assert session.scalar(select(func.count(CodexLifecycleSnapshot.id))) == 1
            assert session.scalar(select(func.count(CodexLifecycleNotification.id))) == 1
            # Launch plus one terminal blocker, not one row per reconciliation.
            assert session.scalar(select(func.count(CodexActivityEvent.id))) == 2


def test_empty_timeout_output_cannot_regress_terminal_run_to_settling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(
            tmp_path,
            terminal_state="TIMED_OUT",
            terminal_reason="timeout",
        )
        evidence.update(
            {
                "process_exit_code": -15,
                "terminal_event_observed": False,
                "terminal_event_type": "",
                "terminal_event_identity": "",
                "terminal_success": False,
                "timed_out": True,
            }
        )
        # A sealed timeout can legitimately contain no stdout or stderr.
        # Presence of the receipt asks the monitor to hold an unfinished Run
        # in settling until the execution manager persists its final state.
        (handle.phase_directory / "terminal.json").write_text(
            json.dumps({"terminal_state": "TIMED_OUT"})
        )
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            assert run.status == "settling"
            session.commit()

        # Simulate the execution manager's authoritative terminal projection.
        # A later watcher pass must retain it even though empty output is valid.
        with factory() as session:
            run = _run(session, fixture)
            run.status = "timed_out"
            run.timed_out = True
            run.stdout = ""
            run.stderr = ""
            session.commit()
        with factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with factory() as session:
            run = _run(session, fixture)
            assert run.status == "timed_out"
            assert run.timed_out is True


def test_jsonl_recovery_candidate_remains_settling_until_post_commit_manager_callback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(
            tmp_path,
            jsonl_recovery_candidate=True,
        )
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        observed_after_commit: list[tuple[int, str, str]] = []
        factory = fixture.client.app.state.session_factory

        def callback(run_id: int) -> None:
            with factory() as callback_session:
                run = callback_session.get(type(_run(callback_session, fixture)), run_id)
                monitor = callback_session.scalar(
                    select(CodexRunMonitor).where(CodexRunMonitor.run_id == run_id)
                )
                assert run is not None and monitor is not None
                observed_after_commit.append((run_id, run.status, monitor.monitor_state))

        reconciled = reconcile_run_monitors(
            factory,
            run_ids=[fixture.run_id],
            on_recovery_needed=callback,
        )
        assert reconciled == [
            {
                "run_id": fixture.run_id,
                "state": "RESULT_PENDING",
                "blocker": "JSONL_FINAL_MESSAGE_RECOVERY_PENDING",
                "recovery_needed": True,
            }
        ]
        assert observed_after_commit == [
            (fixture.run_id, "running", "RESULT_PENDING")
        ]
        with factory() as session:
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == fixture.run_id
                )
            )
            snapshot = session.scalar(
                select(CodexLifecycleSnapshot).where(
                    CodexLifecycleSnapshot.run_id == fixture.run_id
                )
            )
            assert attempt is not None and attempt.attempt_state == "SETTLING"
            assert attempt.jsonl_recovery_candidate is True
            assert snapshot is not None and snapshot.lifecycle_state == "SETTLING"
            assert session.scalar(select(func.count(CodexResultEnvelope.id))) == 0


def test_shared_snapshot_fallback_prefers_terminal_monitor_over_stale_running_run(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            monitor.monitor_state = "RESULT_INTEGRITY_BLOCKED"
            monitor.failure_code = "HISTORICAL_INTEGRITY_BLOCKER"
            session.commit()
        with fixture.client.app.state.session_factory() as session:
            output = lifecycle_snapshot_out(
                session, fixture.owner_id, _run(session, fixture)
            )
            assert output["snapshot_version"] == 0
            assert output["state"] == "result_integrity_blocked"
            assert output["result_integrity"] == "blocked"
            assert output["sidecar_state"] == "not_observed"
            assert output["process_live"] is False
            assert output["next_action"]


def test_reasoning_deltas_are_aggregated_without_reasoning_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(tmp_path)
        evidence.update(
            {
                "receipt_present": False,
                "terminal_state": "",
                "process_live": True,
                "process_exit_known": False,
                "terminal_event_observed": False,
                "terminal_event_type": "",
                "terminal_event_identity": "",
                "sidecar_state": "PENDING",
                "observation_digest": "9" * 64,
            }
        )
        secret_reasoning = "private scratchpad text must never persist"
        with (handle.phase_directory / "stdout.bin").open("wb") as stream:
            for _ in range(10_000):
                stream.write(
                    json.dumps(
                        {
                            "type": "reasoning.delta",
                            "turn_id": "turn-1",
                            "item": {"id": "reasoning-1", "type": "reasoning"},
                            "text": secret_reasoning,
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with fixture.client.app.state.session_factory() as session:
            aggregates = list(session.scalars(select(CodexActivityAggregate)).all())
            assert len(aggregates) == 1
            assert aggregates[0].event_count == 10_000
            assert aggregates[0].safe_last_sample == "Codex is reasoning"
            persisted = " ".join(
                [
                    aggregates[0].safe_first_sample,
                    aggregates[0].safe_last_sample,
                    aggregates[0].sample_digest,
                ]
            )
            assert secret_reasoning not in persisted
            assert session.scalar(select(func.count(CodexActivityEvent.id))) == 1


def test_terminal_elapsed_time_freezes_and_advanced_is_allowlisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(tmp_path)
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with fixture.client.app.state.session_factory() as session:
            first = lifecycle_snapshot_out(
                session, fixture.owner_id, _run(session, fixture), advanced=True
            )
        with fixture.client.app.state.session_factory() as session:
            second = lifecycle_snapshot_out(
                session, fixture.owner_id, _run(session, fixture), advanced=True
            )
        assert first["elapsed_ms"] == second["elapsed_ms"]
        assert first["snapshot_version"] >= 1
        assert first["last_activity_at"]
        assert first["inactivity_ms"] >= 0
        assert set(first["advanced"]) == {
            "execution_attempt_id",
            "monitor_id",
            "execution_id",
            "stream_offsets",
            "event_histogram",
            "sidecar_state",
            "exit_code",
            "reconciliation_version",
            "snapshot_version",
            "process_start_identity",
            "terminal_event_identity",
            "receipt_digest",
        }
        assert "protected_spool_locator" not in first["advanced"]


def test_concurrent_watchers_converge_on_one_attempt_and_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(tmp_path)
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        factory = fixture.client.app.state.session_factory
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda _index: reconcile_run_monitors(
                        factory, run_ids=[fixture.run_id]
                    ),
                    range(2),
                )
            )
        assert all(outcome and outcome[0]["run_id"] == fixture.run_id for outcome in outcomes)
        with factory() as session:
            assert session.scalar(select(func.count(CodexExecutionAttempt.id))) == 1
            assert session.scalar(select(func.count(CodexLifecycleSnapshot.id))) == 1
            assert session.scalar(select(func.count(CodexLifecycleNotification.id))) == 1


def test_reconciliation_error_requests_stop_only_through_exact_sealed_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        requested: list[object] = []
        fake_handle = SimpleNamespace(ticket_digest="a" * 64)
        monkeypatch.setattr(lifecycle_module, "_bridge_handle", lambda *_args: fake_handle)
        monkeypatch.setattr(lifecycle_module, "_validate_ticket_binding", lambda *_args: None)
        monkeypatch.setattr(lifecycle_module.codex_exec_bridge, "load_ticket", lambda _handle: {})
        monkeypatch.setattr(
            lifecycle_module.codex_exec_bridge,
            "load_terminal_receipt",
            lambda _handle: None,
        )
        monkeypatch.setattr(
            lifecycle_module.codex_exec_bridge,
            "load_execution_state",
            lambda _handle: {
                "child_process_id": 43210,
                "child_process_start_identity": "b" * 64,
            },
        )
        monkeypatch.setattr(
            lifecycle_module.codex_exec_bridge,
            "load_launch_info",
            lambda _handle: None,
        )
        monkeypatch.setattr(
            lifecycle_module.codex_exec_bridge,
            "process_identity_matches",
            lambda pid, identity: pid == 43210 and identity == "b" * 64,
        )
        monkeypatch.setattr(
            lifecycle_module.codex_exec_bridge,
            "request_cancel",
            lambda handle: requested.append(handle) or True,
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == fixture.run_id)
            )
            assert monitor is not None
            result = settle_reconciliation_error(
                session,
                fixture.owner_id,
                run,
                monitor,
                LifecycleReconciliationError(
                    "EXECUTION_ATTEMPT_IDENTITY_MISMATCH",
                    "The exact attempt binding changed.",
                ),
            )
            session.commit()
            assert result["state"] == "RESULT_INTEGRITY_BLOCKED"
        assert requested == [fake_handle]
        with fixture.client.app.state.session_factory() as session:
            summaries = list(
                session.scalars(
                    select(CodexActivityEvent.safe_summary).where(
                        CodexActivityEvent.run_id == fixture.run_id
                    )
                ).all()
            )
            assert "Stopping the exact blocked Codex process" in summaries


def test_command_updates_are_bounded_and_completed_and_all_file_changes_are_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.run_lifecycle as lifecycle_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        _prepare_running_monitor(fixture, tmp_path)
        evidence, handle = _terminal_evidence(tmp_path)
        evidence.update(
            {
                "receipt_present": False,
                "terminal_state": "",
                "process_live": True,
                "process_exit_known": False,
                "terminal_event_observed": False,
                "terminal_event_type": "",
                "terminal_event_identity": "",
                "sidecar_state": "PENDING",
                "observation_digest": "8" * 64,
            }
        )
        events = [
            {
                "type": "item.updated",
                "turn_id": "turn-1",
                "item": {"id": "command-1", "type": "command_execution"},
            }
            for _ in range(10_000)
        ]
        events.extend(
            [
                {
                    "type": "item.completed",
                    "turn_id": "turn-1",
                    "item": {"id": "command-1", "type": "command_execution"},
                },
                {
                    "type": "item.completed",
                    "turn_id": "turn-1",
                    "item": {
                        "id": "files-1",
                        "type": "file_change",
                        "changes": [
                            {"kind": "add", "path": "one.txt"},
                            {"kind": "update", "path": "nested/two.txt"},
                            {"kind": "delete", "path": "old.txt"},
                        ],
                    },
                },
            ]
        )
        stdout_path = handle.phase_directory / "stdout.bin"
        with stdout_path.open("wb") as stream:
            for event in events[:5000]:
                stream.write(json.dumps(event).encode("utf-8") + b"\n")
        monkeypatch.setattr(
            lifecycle_module,
            "_bridge_evidence",
            lambda _monitor, _run_row, _owner, phase: (
                (dict(evidence), handle) if phase == "CODING" else None
            ),
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == fixture.run_id)
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with stdout_path.open("ab") as stream:
            for event in events[5000:]:
                stream.write(json.dumps(event).encode("utf-8") + b"\n")
        evidence["observation_digest"] = "7" * 64
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == fixture.run_id)
            )
            assert monitor is not None
            reconcile_execution_attempt(session, fixture.owner_id, run, monitor)
            session.commit()
        with fixture.client.app.state.session_factory() as session:
            aggregate = session.scalar(select(CodexActivityAggregate))
            assert aggregate is not None
            assert aggregate.event_count == 10_000
            assert aggregate.final_observable_outcome == "COMPLETED"
            file_rows = list(
                session.scalars(
                    select(CodexActivityEvent).where(
                        CodexActivityEvent.event_category == "FILE"
                    )
                ).all()
            )
            assert {(row.repository_path, row.safe_summary) for row in file_rows} == {
                ("one.txt", "Creating one.txt"),
                ("nested/two.txt", "Modifying nested/two.txt"),
                ("old.txt", "Deleting old.txt"),
            }
