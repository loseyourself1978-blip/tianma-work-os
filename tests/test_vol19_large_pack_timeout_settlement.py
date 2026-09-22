from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from tests.test_self_hosting import (
    approve_pack,
    create_executable_task,
    generate_pack,
    init_and_login,
    make_client,
    make_nonreading_codex,
    make_source_repo,
    start_codex_run,
    wait_for_run,
    wait_for_spawned_run,
)
from twos_runtime import codex_exec_bridge, run_lifecycle
from twos_runtime import codex_adapter as adapter_module
from twos_runtime.codex_adapter import ResultIntakeError
from twos_runtime.result_intake import reconcile_run_monitors
from twos_runtime.models import (
    AIModelInvocationEvidence,
    AuditEvent,
    CodexExecutionAttempt,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
)
from twos_runtime.run_lifecycle import coding_timeout_receipt_persisted


def start_large_pack(client, headers, size: int) -> int:
    task_id = create_executable_task(client, headers)
    response = client.patch(
        f"/api/tasks/{task_id}", headers=headers,
        json={"required_output": "X" * size},
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/ai/team-compose", headers=headers, json={"task_id": task_id},
    )
    assert response.status_code == 200, response.text
    pack = generate_pack(client, headers, task_id)
    approve_pack(client, headers, task_id, pack["id"])
    response = start_codex_run(client, headers, task_id, pack)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def join_workers(manager) -> None:
    # Condition-based joins wait for real optional evidence settlement; they
    # neither relax the five-second process-truth assertion nor accept SETTLING.
    deadline = time.monotonic() + 10
    while True:
        with manager._lock:
            workers = list(manager._workers.values())
        if not workers:
            return
        for worker in workers:
            worker.join(timeout=max(0, deadline - time.monotonic()))
        assert time.monotonic() < deadline, "Run evidence worker did not terminate"


def wait_for_coding_timeout(client, headers, run_id):
    # The one-second Coding clock starts at child launch, after independent
    # bounded Git/auth/snapshot preflight. Observe that real boundary first;
    # the previous five-second wait from POST included preparation and could
    # shut down the app while a valid timeout receipt was being committed.
    # Keep the five-second terminal budget and the <6000ms receipt assertion.
    wait_for_spawned_run(client, headers, run_id, timeout=10)
    return wait_for_run(client, headers, run_id, {"timed_out"}, timeout=5)


def assert_one_timeout(factory, run_id: int, *, incomplete: bool) -> tuple[int, str]:
    with factory() as session:
        run = session.get(CodexRun, run_id)
        assert run is not None
        assert run.status == "timed_out"
        assert run.timed_out is True and run.cancelled is False
        assert run.exit_code == -15
        assert 0 <= run.duration_ms < 6000
        assert run.process_spawned is True
        assert run.verification_process_spawned is False
        assert run.verification_status == "not_started"
        assert coding_timeout_receipt_persisted(session, run)
        invocations = session.scalars(select(AIModelInvocationEvidence)).all()
        assert len(invocations) == 1
        assert invocations[0].outcome == "timed_out"
        assert invocations[0].timed_out is True
        assert invocations[0].cancelled is False
        attempts = session.scalars(select(CodexExecutionAttempt)).all()
        assert len(attempts) == 1 and attempts[0].phase == "CODING"
        assert attempts[0].attempt_state == "TIMED_OUT"
        assert attempts[0].process_exit_known and not attempts[0].process_live
        assert attempts[0].receipt_digest
        monitor = session.scalar(select(CodexRunMonitor))
        assert monitor is not None
        assert monitor.process_id and monitor.process_start_identity
        assert not codex_exec_bridge.process_identity_matches(
            monitor.process_id, monitor.process_start_identity,
        )
        if incomplete:
            assert json.loads(run.structured_result or "{}") == {}
            assert session.scalar(select(CodexResultEnvelope)) is None
        else:
            assert json.loads(run.structured_result)
        assert len(session.scalars(select(CodexRun)).all()) == 1
        audits = session.scalars(select(AuditEvent).where(
            AuditEvent.action == "codex_timeout_terminal_persisted",
        )).all()
        assert len(audits) == 1
        return monitor.process_id, monitor.process_start_identity


@pytest.mark.parametrize("size", [1_000_000, 2_000_000])
def test_real_timeout_truth_precedes_optional_evidence_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, size: int,
) -> None:
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    with make_client(tmp_path, source, executable, timeout=1) as client:
        manager = client.app.state.codex_manager
        factory = client.app.state.session_factory
        real_derive = manager._derive_result
        real_persist = manager._persist_coding_timeout_before_settlement
        captured = {}

        def capture_persist(*args, **kwargs):
            captured.update(kwargs)
            return real_persist(*args, **kwargs)

        monkeypatch.setattr(manager, "_persist_coding_timeout_before_settlement", capture_persist)

        def gated_derive(*args, **kwargs):
            entered.set()
            assert release.wait(15), "test did not release optional settlement"
            return real_derive(*args, **kwargs)

        monkeypatch.setattr(manager, "_derive_result", gated_derive)
        headers = init_and_login(client)
        run_id = start_large_pack(client, headers, size)
        try:
            run = wait_for_coding_timeout(client, headers, run_id)
            assert entered.wait(1)
            identity = assert_one_timeout(factory, run_id, incomplete=True)
            assert len(run["model_invocations"]) == 1
            assert run["model_invocations"][0]["verified_real_invocation"] is False
            assert run["model_invocations"][0]["actual_invoked_model_identifier"] is None
            assert run["terminal_truth"]["coding"]["status"] == "timed_out"
            assert run["terminal_truth"]["verification"]["started"] is False
            assert run["terminal_truth"]["result"]["available"] is False
            assert run["terminal_truth"]["result"]["integrity"] != "verified"
            assert run["terminal_truth"]["workspace"]["state"] == "incomplete"
            assert run["result"]["verification"]["status"] == "not_started"
            assert run["result"]["verification"]["process_spawned"] is False
            assert run["result"]["verification"]["summary"] == (
                "Independent Verification did not start because Coding timed out."
            )
            assert run["result"]["process"]["timed_out"] is True
            assert run["result"]["process"]["cancelled"] is False
            assert run["result"]["process"]["exit_code"] == -15
            assert run["result"]["coding_process"]["status"] == "timed_out"
            assert run["result"]["changed_files"] == []
            assert run["result"]["changed_file_evidence"] == []
            assert run["result"]["verification_verdict"]["status"] == "not_reached"
            assert client.get(
                f"/api/codex-runs/{run_id}/result-envelope", headers=headers,
            ).status_code == 404
            refreshed = client.post(
                f"/api/codex-runs/{run_id}/refresh-status", headers=headers,
            )
            assert refreshed.status_code == 200, refreshed.text
            activity = refreshed.json()["run"]
            assert activity["run_status"] == "timed_out"
            assert activity["terminal_truth"] == run["terminal_truth"]
            again = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
            assert again["status"] == "timed_out"
            assert again["terminal_truth"] == run["terminal_truth"]
            assert assert_one_timeout(factory, run_id, incomplete=True) == identity
            # A repeated sealed receipt does not create another invocation,
            # change the exit fact, or publish a fictional result envelope.
            assert real_persist(run_id, **captured) is True
            assert assert_one_timeout(factory, run_id, incomplete=True) == identity
            for key, invalid in (
                ("receipt", None), ("process_id", identity[0] + 1),
                ("process_start_identity", "0" * 64), ("exit_code", 0),
            ):
                wrong = dict(captured)
                wrong["bridge"] = {**captured["bridge"], key: invalid}
                with pytest.raises(ResultIntakeError):
                    real_persist(run_id, **wrong)
                assert_one_timeout(factory, run_id, incomplete=True)
        finally:
            release.set()
            join_workers(manager)
        assert_one_timeout(factory, run_id, incomplete=False)
        final = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        assert final["result"].keys() >= run["result"].keys()
        assert final["result"]["process"]["timed_out"] is True
        assert final["result"]["verification"]["status"] == "not_started"
    assert manager._workers == {}
    assert manager._processes == {}
    assert not codex_exec_bridge.process_identity_matches(*identity)
    assert client.app.state.result_intake_monitor._thread is None
    assert client.app.state.engine.pool.checkedout() == 0
    assert client.app.state.engine.pool.checkedin() == 0
    assert run_lifecycle._reconciliation_lock_registry_size() == 0


def test_restart_recovers_optional_timeout_evidence_without_relaunch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    entered, release = threading.Event(), threading.Event()
    with make_client(tmp_path, source, executable, timeout=1) as client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        real_derive = manager._derive_result

        def gated_derive(*args, **kwargs):
            entered.set()
            assert release.wait(15)
            return real_derive(*args, **kwargs)

        monkeypatch.setattr(manager, "_derive_result", gated_derive)
        run_id = start_large_pack(client, headers, 1_000_000)
        try:
            wait_for_coding_timeout(client, headers, run_id)
            assert entered.wait(1)
            identity = assert_one_timeout(client.app.state.session_factory, run_id, incomplete=True)
            handle = manager._existing_bridge_handle(run_id, "coding")
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            before = copy.deepcopy(receipt)
            manager.shutdown()
        finally:
            release.set()
            join_workers(manager)
        assert_one_timeout(client.app.state.session_factory, run_id, incomplete=True)
    assert client.app.state.result_intake_monitor._thread is None
    assert client.app.state.engine.pool.checkedout() == 0
    assert client.app.state.engine.pool.checkedin() == 0
    assert run_lifecycle._reconciliation_lock_registry_size() == 0

    launches = []
    real_popen = codex_exec_bridge.subprocess.Popen

    def forbid_relaunch(argv, *args, **kwargs):
        if "twos_runtime.codex_exec_bridge" in [str(value) for value in argv]:
            launches.append(argv)
            raise AssertionError("restart tried to launch another Coding process")
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(codex_exec_bridge.subprocess, "Popen", forbid_relaunch)
    with make_client(tmp_path, source, executable, timeout=1) as reopened:
        headers = init_and_login(reopened)
        factory = reopened.app.state.session_factory
        manager2 = reopened.app.state.codex_manager
        assert manager2 is not manager
        deadline = time.monotonic() + 10
        while True:
            response = reopened.get(f"/api/codex-runs/{run_id}", headers=headers)
            assert response.status_code == 200
            assert response.json()["status"] == "timed_out"
            assert response.json()["result"]["verification"]["status"] == "not_started"
            assert response.json()["result"]["process"]["timed_out"] is True
            with factory() as session:
                complete = bool(json.loads(session.get(CodexRun, run_id).structured_result or "{}"))
            if complete:
                break
            assert time.monotonic() < deadline, "sealed timeout result was not recovered"
            reopened.app.state.result_intake_monitor.notify()
            with manager2._lock:
                workers = list(manager2._workers.values())
            if workers:
                workers[0].join(timeout=0.1)
            else:
                reopened.app.state.result_intake_monitor.reconcile_now([run_id])
        join_workers(manager2)
        assert assert_one_timeout(factory, run_id, incomplete=False) == identity
        after = codex_exec_bridge.load_terminal_receipt(
            manager2._existing_bridge_handle(run_id, "coding"),
        )
        assert after == before
        assert launches == []
    assert manager2._workers == {} and manager2._processes == {}
    assert reopened.app.state.result_intake_monitor._thread is None
    assert reopened.app.state.engine.pool.checkedout() == 0
    assert reopened.app.state.engine.pool.checkedin() == 0
    assert run_lifecycle._reconciliation_lock_registry_size() == 0


def test_prelaunch_failure_settles_an_already_observed_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    with make_client(tmp_path, source, executable) as client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        factory = client.app.state.session_factory
        monkeypatch.setattr(manager, "start", lambda _run_id: True)
        run_id = start_large_pack(client, headers, 65536)
        client.app.state.result_intake_monitor.shutdown()
        assert client.app.state.result_intake_monitor._thread is None
        real_popen = codex_exec_bridge.subprocess.Popen
        launch_attempts = []

        def failed_launch(argv, *args, **kwargs):
            if "twos_runtime.codex_exec_bridge" in [str(value) for value in argv]:
                launch_attempts.append(argv)
                reconcile_run_monitors(factory, run_ids=[run_id])
                with factory() as session:
                    attempt = session.scalar(select(CodexExecutionAttempt))
                    assert attempt.attempt_state == "STARTING"
                    assert attempt.process_id is None
                raise OSError("fixture bridge launch unavailable")
            return real_popen(argv, *args, **kwargs)

        monkeypatch.setattr(codex_exec_bridge.subprocess, "Popen", failed_launch)
        manager._execute(run_id)
        assert len(launch_attempts) == 1
        # A synchronous prelaunch rejection cannot depend on a later watcher
        # pass to publish its terminal snapshot, or on worker-finally intake.
        immediate = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        expected_summary = "Blocked before process start: approved execution conditions are no longer satisfied."
        assert immediate["status"] == "blocked"
        assert immediate["owner_summary"] == expected_summary
        for _ in range(3):
            reconcile_run_monitors(factory, run_ids=[run_id])
            run = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
            assert run["status"] == "blocked"
            assert run["owner_summary"] == expected_summary
            assert run["process_spawned"] is False
            assert run["exit_code"] is None
            assert run["model_invocations"] == []
            with factory() as session:
                persisted = session.get(CodexRun, run_id)
                assert persisted.task.status == "blocked"
                assert persisted.started_at is None
                attempt = session.scalar(select(CodexExecutionAttempt))
                assert attempt.attempt_state == "RESULT_UNAVAILABLE"
                assert attempt.blocker_code == "CODEX_EXECUTION_BLOCKED_PRELAUNCH"
                assert not attempt.process_live and not attempt.process_exit_known
                assert attempt.receipt_digest == ""
                assert session.scalar(select(AIModelInvocationEvidence)) is None
    assert run_lifecycle._reconciliation_lock_registry_size() == 0
    assert client.app.state.engine.pool.checkedout() == 0
    assert client.app.state.engine.pool.checkedin() == 0


@pytest.mark.parametrize("permanent", [False, True], ids=["recovers", "bounded-failure"])
def test_optional_evidence_failure_does_not_reverse_timeout_or_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, permanent: bool,
) -> None:
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    with make_client(tmp_path, source, executable, timeout=1) as client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        factory = client.app.state.session_factory
        real_derive = manager._derive_result
        calls = []

        def failing_derive(*args, **kwargs):
            calls.append(args[1])
            if permanent or len(calls) == 1:
                raise OSError("DO_NOT_STORE_OPTIONAL_EVIDENCE_EXCEPTION_SECRET")
            return real_derive(*args, **kwargs)

        monkeypatch.setattr(manager, "_derive_result", failing_derive)
        run_id = start_large_pack(client, headers, 1_000_000)
        wait_for_coding_timeout(client, headers, run_id)
        deadline = time.monotonic() + 10
        while True:
            client.app.state.result_intake_monitor.reconcile_now([run_id])
            join_workers(manager)
            with factory() as session:
                run = session.get(CodexRun, run_id)
                assert run.status == "timed_out"
                failed = session.scalar(select(AuditEvent.id).where(
                    AuditEvent.action == "codex_timeout_evidence_settlement_failed",
                ))
                settled = bool(json.loads(run.structured_result or "{}"))
            if (permanent and failed) or (not permanent and settled):
                break
            assert time.monotonic() < deadline
        assert calls == [run_id, run_id]
        assert_one_timeout(factory, run_id, incomplete=permanent)
        for _ in range(3):
            client.app.state.result_intake_monitor.reconcile_now([run_id])
        assert calls == [run_id, run_id]
        with factory() as session:
            audits = session.scalars(select(AuditEvent)).all()
            assert "DO_NOT_STORE_OPTIONAL_EVIDENCE_EXCEPTION_SECRET" not in repr(
                [audit.details for audit in audits],
            )
            run = session.get(CodexRun, run_id)
            if permanent:
                assert "could not be settled" in run.owner_summary
                assert session.scalar(select(CodexResultEnvelope)) is None
                monitor = session.scalar(select(CodexRunMonitor))
                assert monitor.monitor_state == "RESULT_UNAVAILABLE"
                assert monitor.failure_code == "CODEX_TIMEOUT_RESULT_UNAVAILABLE"
        if permanent:
            assert client.app.state.result_intake_monitor._has_pending_monitors() is False
            public = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
            assert public["result"]["verification"]["status"] == "not_started"
            assert public["result"]["process"]["timed_out"] is True
            assert public["terminal_truth"]["result"]["available"] is False
    assert manager._workers == {} and manager._processes == {}
    assert client.app.state.result_intake_monitor._thread is None
    assert client.app.state.engine.pool.checkedout() == 0
    assert client.app.state.engine.pool.checkedin() == 0
    assert run_lifecycle._reconciliation_lock_registry_size() == 0


def test_jsonl_contradiction_does_not_hide_a_real_process_timeout(tmp_path: Path) -> None:
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    events = [
        {"type": "thread.started", "thread_id": "thread-one"},
        {"type": "turn.started", "turn_id": "turn-one"},
        {"type": "turn.completed", "turn_id": "turn-one"},
        {"type": "turn.failed", "turn_id": "turn-one"},
    ]
    executable.write_text(executable.read_text().replace(
        "time.sleep(10)",
        "\n".join(f"print({json.dumps(event)!r}, flush=True)" for event in events)
        + "\ntime.sleep(10)",
    ))
    with make_client(tmp_path, source, executable, timeout=1) as client:
        headers = init_and_login(client)
        run_id = start_large_pack(client, headers, 1_000_000)
        run = wait_for_coding_timeout(client, headers, run_id)
        manager = client.app.state.codex_manager
        join_workers(manager)
        receipt = codex_exec_bridge.load_terminal_receipt(
            manager._existing_bridge_handle(run_id, "coding"),
        )
        assert receipt["outcome_facts"]["terminal_contradiction"] is True
        assert receipt["outcome_facts"]["timed_out"] is True
        assert receipt["terminal_state"] == "TIMED_OUT"
        assert_one_timeout(client.app.state.session_factory, run_id, incomplete=False)
        assert run["terminal_truth"]["coding"]["status"] == "timed_out"
        assert run["model_invocations"][0]["verified_real_invocation"] is False
        final = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        assert final["status"] == "timed_out"
        assert final["terminal_truth"]["verification"]["started"] is False
        # Verified transport/receipt integrity is not a claim that contradictory
        # Codex output or the objective passed. Assert the actual invocation
        # integrity fields rather than conflating these accepted dimensions.
        assert final["result"]["coding_invocation"]["codex_turn_verified"] is False
        assert final["result"]["coding_invocation"]["process_execution_verified"] is False
        assert final["result"]["exec_bridge"]["transport_consumption_completed"] is False
        assert final["model_invocations"][0]["process_evidence"]["codex_lifecycle_conflict"] is True
    assert manager._workers == {} and manager._processes == {}
    assert run_lifecycle._reconciliation_lock_registry_size() == 0


@pytest.mark.parametrize('failed_read', [None, 'remote', 'git', 'workspace'])
def test_timeout_preflight_joins_all_independent_boundary_reads_before_launch(tmp_path, monkeypatch, failed_read):
    source = make_source_repo(tmp_path)
    executable = make_nonreading_codex(tmp_path)
    barrier = threading.Barrier(3)
    observations = []
    completed = []
    with make_client(tmp_path, source, executable, timeout=1) as client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager

        def observe(name, original):
            def read(*args, **kwargs):
                parallel = threading.current_thread().name.startswith('twos-boundary-read')
                if parallel:
                    observations.append(name)
                    barrier.wait(timeout=3)
                value = original(*args, **kwargs)
                if parallel:
                    completed.append(name)
                    if name == failed_read:
                        if name == 'workspace':
                            raise RuntimeError('Controlled preflight snapshot failure')
                        return ('', value[1], False) if name == 'remote' else ('', False)
                return value
            return read

        monkeypatch.setattr(manager, '_remote_state_fingerprint', observe('remote', manager._remote_state_fingerprint))
        monkeypatch.setattr(manager, '_git_boundary_fingerprint', observe('git', manager._git_boundary_fingerprint))
        monkeypatch.setattr(adapter_module, '_capture_approved_source_snapshot', observe('workspace', adapter_module._capture_approved_source_snapshot))
        real_launch = codex_exec_bridge.launch_sidecar
        launches = []

        def launch(*args, **kwargs):
            assert sorted(completed) == ['git', 'remote', 'workspace']
            assert not any(t.name.startswith('twos-boundary-read') for t in threading.enumerate())
            launches.append(1)
            return real_launch(*args, **kwargs)

        monkeypatch.setattr(codex_exec_bridge, 'launch_sidecar', launch)
        run_id = start_large_pack(client, headers, 1_000_000)
        expected = 'blocked' if failed_read else 'timed_out'
        run = (
            wait_for_run(client, headers, run_id, {expected}, timeout=5)
            if failed_read else wait_for_coding_timeout(client, headers, run_id)
        )
        join_workers(manager)
        assert sorted(observations) == ['git', 'remote', 'workspace']
        assert sorted(completed) == ['git', 'remote', 'workspace']
        if failed_read:
            assert run['status'] == 'blocked'
            assert run['process_spawned'] is False and run['exit_code'] is None
            assert run['model_invocations'] == []
            assert launches == []
        else:
            assert run['timed_out'] is True and run['exit_code'] == -15
            assert launches == [1]
            assert_one_timeout(client.app.state.session_factory, run_id, incomplete=False)
    assert not any(t.name.startswith('twos-boundary-read') for t in threading.enumerate())
    assert run_lifecycle._reconciliation_lock_registry_size() == 0
