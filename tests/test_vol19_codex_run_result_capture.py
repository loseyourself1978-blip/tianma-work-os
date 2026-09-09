from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import twos_runtime.codex_adapter as codex_adapter_module
import twos_runtime.self_hosting as self_hosting_module
from tests.test_self_hosting import (
    approve_pack,
    create_executable_task,
    generate_pack,
    init_and_login,
    make_client,
    make_fake_codex,
    make_source_repo,
    run_command,
    start_codex_run,
    wait_for_run,
)
from twos_runtime.codex_exec_bridge import (
    CodexExecBridgeError,
    capture_process_start_identity,
    process_identity_matches,
)
from twos_runtime.config import STATIC_COCKPIT_DIR
from twos_runtime.models import (
    AIModelAssignment,
    ApplyPlan,
    ApplySession,
    CodexInstructionPack,
    CodexLifecycleSnapshot,
    CodexRun,
    CodexRunMonitor,
    CodexResultEnvelope,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    PushExecution,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.security import hash_password, hash_token


TERMINAL_CANONICAL_STATES = {
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
    "needs_setup",
    "blocked",
}


def _wait_for_result_envelope(client, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/codex-runs/{run_id}/result-envelope",
            headers=headers,
        )
        if response.status_code == 200:
            return response.json()["result"]
        assert response.status_code == 404, response.text
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not publish a Result envelope")


def test_owner_confirmation_and_idempotent_start_spawn_one_real_run(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    fake_codex.with_name(fake_codex.name + ".delay-second-detection").write_text(
        "delay\n"
    )

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_VOL19_PROGRESS VOL19_EXPLICIT_START",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        route = f"/api/tasks/{task_id}/codex-runs"
        request_key = "vol19-confirmed-codex-start-0001"

        missing_confirmation = client.post(
            route,
            headers=headers,
            json={
                "idempotency_key": request_key,
                "pack_id": pack["id"],
                "pack_version": pack["version"],
            },
        )
        assert missing_confirmation.status_code == 422
        assert client.get(route, headers=headers).json() == []

        started = start_codex_run(
            client,
            headers,
            task_id,
            pack,
            idempotency_key=request_key,
        )
        assert started.status_code == 200, started.text
        assert started.json()["owner_start_confirmed"] is True
        assert started.json()["start_request_replayed"] is False

        replayed = start_codex_run(
            client,
            headers,
            task_id,
            pack,
            idempotency_key=request_key,
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["id"] == started.json()["id"]
        assert replayed.json()["start_request_replayed"] is True

        observed = {started.json()["canonical_status"]}
        deadline = time.monotonic() + 15
        run = started.json()
        while time.monotonic() < deadline:
            response = client.get(
                f"/api/codex-runs/{started.json()['id']}",
                headers=headers,
            )
            assert response.status_code == 200, response.text
            run = response.json()
            observed.add(run["canonical_status"])
            if run["canonical_status"] in TERMINAL_CANONICAL_STATES:
                break
            if {"starting", "running"}.issubset(observed):
                break
            time.sleep(0.02)

        if "succeeded" not in observed:
            run = wait_for_run(
                client,
                headers,
                started.json()["id"],
                {"completed"},
                timeout=20,
            )
            observed.add(run["canonical_status"])
        assert {"starting", "running", "succeeded"}.issubset(observed), observed
        assert run["canonical_status"] == "succeeded"
        runs = client.get(route, headers=headers).json()
        assert [item["id"] for item in runs] == [started.json()["id"]]
        assert runs[0]["process_spawned"] is True
        events = run["lifecycle"]["events"]
        sequences = [item["sequence"] for item in events]
        assert sequences == list(range(1, len(events) + 1))
        assert len(sequences) == len(set(sequences))
        event_times = [item["occurred_at"] for item in events]
        assert event_times == sorted(event_times)
        log_reference = run["lifecycle"]["advanced"]["protected_log_reference"]
        assert log_reference.startswith("codex-run-log:")
        assert not Path(log_reference).is_absolute()
        assert "/" not in log_reference and "\\" not in log_reference
        assert str(tmp_path) not in log_reference


def test_distinct_concurrent_start_requests_admit_exactly_one_process(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        barrier = threading.Barrier(3)
        responses = []

        def request_run(request_key: str) -> None:
            barrier.wait()
            responses.append(
                start_codex_run(
                    client,
                    headers,
                    task_id,
                    pack,
                    idempotency_key=request_key,
                )
            )

        workers = [
            threading.Thread(
                target=request_run,
                args=(f"vol19-distinct-concurrent-start-{index}",),
            )
            for index in range(2)
        ]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=5)
        assert all(not worker.is_alive() for worker in workers)

        assert sorted(response.status_code for response in responses) == [200, 409]
        admitted = next(response for response in responses if response.status_code == 200)
        runs = client.get(
            f"/api/tasks/{task_id}/codex-runs",
            headers=headers,
        ).json()
        assert [item["id"] for item in runs] == [admitted.json()["id"]]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = client.get(
                f"/api/codex-runs/{admitted.json()['id']}",
                headers=headers,
            ).json()
            if active["process_spawned"]:
                break
            time.sleep(0.02)
        assert active["process_spawned"] is True
        cancelled = client.post(
            f"/api/codex-runs/{admitted.json()['id']}/cancel",
            headers=headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        terminal = wait_for_run(
            client,
            headers,
            admitted.json()["id"],
            {"cancelled"},
            timeout=5,
        )
        assert len(terminal["model_invocations"]) == 1
        assert terminal["model_invocations"][0]["capability"] == "coding"


def test_real_result_captures_modified_and_created_files_tests_stderr_and_reload(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "vol19-codex-result.sqlite3"
    run_id = 0
    expected_result: dict = {}
    candidate_identity = ""
    candidate_digest = ""

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker=(
                "FAKE_MODIFY_TRACKED FAKE_TEST_COMMAND FAKE_SAFE_STDERR "
                "VOL19_AUTOMATIC_RESULT_CAPTURE"
            ),
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed"},
            timeout=15,
        )
        run_id = terminal["id"]
        expected_result = terminal["result"]

        assert terminal["canonical_status"] == "succeeded"
        assert terminal["completion_classification"] == "succeeded_with_changes"
        assert terminal["changed_file_count"] == 2
        assert terminal["result"]["changed_files"] == [
            "README.md",
            "codex-result.txt",
        ]
        evidence = {
            item["path"]: item
            for item in terminal["result"]["changed_file_evidence"]
        }
        assert evidence["README.md"]["before_sha256"]
        assert evidence["README.md"]["after_sha256"]
        assert (
            evidence["README.md"]["before_sha256"]
            != evidence["README.md"]["after_sha256"]
        )
        assert evidence["codex-result.txt"]["before_sha256"] is None
        assert evidence["codex-result.txt"]["after_sha256"]

        workspace = terminal["result"]["workspace_evidence"]
        assert workspace["tracked_modified_files"] == ["README.md"]
        assert workspace["added_files"] == ["codex-result.txt"]
        assert workspace["attribution"]["baseline_preexisting"] == []
        assert workspace["attribution"]["run_produced"] == [
            "README.md",
            "codex-result.txt",
        ]
        assert workspace["attribution"]["origin_unproven"] == []
        assert workspace["staged_files"] == []

        assert terminal["result"]["tests"] == [
            {
                "evidence_type": "test_execution",
                "command_label": "pytest",
                "status": "passed",
                "exit_code": 0,
                "summary": "1 passed in 0.01s",
            }
        ]
        assert terminal["result"]["tests_reported"] == ["1 passed in 0.01s"]
        assert "VOL19 controlled stderr diagnostic" in terminal["stderr"]
        final_message = json.loads(
            terminal["result"]["advanced_diagnostics"][
                "coding_final_agent_message"
            ]
        )
        assert final_message == {
            "schema": "twos.coding_handoff.v1",
            "status": "completed",
            "summary": "1 passed in fake validation",
        }
        envelope = _wait_for_result_envelope(client, headers, run_id)
        assert envelope["structured_handoff_status"] == "captured"
        assert envelope["final_response"] == "1 passed in fake validation"

        assert (source_repo / "README.md").read_text() == "# Test source\n"
        assert (
            run_command(source_repo, "git", "diff", "--cached", "--name-only")
            .stdout.strip()
            == ""
        )
        with client.app.state.session_factory() as session:
            assert session.query(CodexRun).count() == 1
            candidates = list(
                session.scalars(
                    select(DeliveryCandidate).where(
                        DeliveryCandidate.run_id == run_id
                    )
                ).all()
            )
            assert len(candidates) == 1
            candidate = candidates[0]
            assert candidate.derivation_version == (
                "twos.result_delivery_candidate.v1"
            )
            assert candidate.readiness_state == "ready"
            assert candidate.acceptance_status == "owner_review"
            assert candidate.acceptance.status == "owner_review"
            assert candidate.acceptance.decision_digest == ""
            assert candidate.result_envelope_public_id == envelope["id"]
            assert len(candidate.candidate_digest) == 64
            candidate_identity = candidate.candidate_id
            candidate_digest = candidate.candidate_digest
            assert session.query(ApplyPlan).count() == 0
            assert session.query(ApplySession).count() == 0
            assert session.query(CommitPlan).count() == 0
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as restarted:
        headers = init_and_login(restarted)
        reloaded = restarted.get(
            f"/api/codex-runs/{run_id}",
            headers=headers,
        )
        assert reloaded.status_code == 200, reloaded.text
        assert reloaded.json()["canonical_status"] == "succeeded"
        assert reloaded.json()["completion_classification"] == (
            "succeeded_with_changes"
        )
        assert reloaded.json()["result"] == expected_result
        activity = restarted.get("/api/run-activity", headers=headers)
        assert activity.status_code == 200, activity.text
        persisted = next(
            item for item in activity.json()["runs"] if item["run_id"] == run_id
        )
        assert persisted["result_available"] is True
        assert persisted["lifecycle"]["events"]
        with restarted.app.state.session_factory() as session:
            candidate = session.scalar(
                select(DeliveryCandidate).where(
                    DeliveryCandidate.run_id == run_id
                )
            )
            assert candidate is not None
            assert candidate.candidate_id == candidate_identity
            assert candidate.candidate_digest == candidate_digest
            assert candidate.acceptance.status == "owner_review"
            assert session.query(ApplyPlan).count() == 0
            assert session.query(ApplySession).count() == 0
            assert session.query(CommitPlan).count() == 0
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0


def test_missing_structured_handoff_keeps_automatic_terminal_evidence(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_MISSING_HANDOFF VOL19_RESULT_INCOMPLETE",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"blocked", "failed"},
            timeout=15,
        )

        assert terminal["canonical_status"] not in {
            "pending",
            "starting",
            "running",
        }
        assert terminal["completion_classification"] == "result_incomplete"
        assert terminal["exit_code"] == 0
        assert terminal["result"]["changed_files"] == ["codex-result.txt"]
        assert terminal["result"]["process"]["exit_code"] == 0
        assert terminal["result"]["coding_process"]["process_started"] is True
        assert terminal["result"]["advanced_diagnostics"][
            "coding_final_agent_message"
        ] == "Completed without a structured handoff."
        assert terminal["verification_target"]["process_spawned"] is False
        assert terminal["result"]["structured_handoff"] == {}
        envelope = _wait_for_result_envelope(client, headers, terminal["id"])
        assert envelope["structured_handoff_status"] == "unavailable"
        assert envelope["completion_classification"] == "result_incomplete"
        assert not envelope["completion_classification"].startswith("succeeded")
        ingested = [
            item
            for item in client.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_result_ingested"
            and f"run={terminal['id']};" in item["details"]
        ]
        assert ingested
        assert all("integrity=VERIFIED" in item["details"] for item in ingested)


@pytest.mark.parametrize(
    ("marker", "expected_response"),
    [
        (
            "FAKE_INVALID_JSON_HANDOFF VOL19_RESULT_INCOMPLETE",
            '{"schema":"twos.coding_handoff.v1"',
        ),
        (
            "FAKE_INVALID_STATUS_HANDOFF VOL19_RESULT_INCOMPLETE",
            (
                '{"schema":"twos.coding_handoff.v1","status":"partial",'
                '"summary":"The transport finished but the handoff status is invalid."}'
            ),
        ),
    ],
)
def test_jsonl_only_invalid_handoff_keeps_transport_truth_and_blocks_verification(
    tmp_path: Path,
    marker: str,
    expected_response: str,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker=marker)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"failed"},
            timeout=15,
        )

        assert terminal["exit_code"] == 0
        assert terminal["completion_classification"] == "result_incomplete"
        assert terminal["result"]["final_response"] == expected_response
        assert terminal["result"]["structured_handoff"] == {}
        assert terminal["result"]["exec_bridge"]["integrity_state"] == "verified"
        assert terminal["verification_target"]["process_spawned"] is False
        envelope = _wait_for_result_envelope(client, headers, terminal["id"])
        assert envelope["integrity_state"] == "VERIFIED"
        assert envelope["structured_handoff_status"] == "unavailable"
        assert envelope["completion_classification"] == "result_incomplete"
        refreshed = client.get(
            f"/api/codex-runs/{terminal['id']}", headers=headers
        ).json()
        assert refreshed["lifecycle"]["state"] == "result_available"
        assert refreshed["lifecycle"]["result_integrity"] == "verified"


def test_terminal_evidence_without_envelope_stops_polling_after_settlement_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        monkeypatch.setattr(
            client.app.state.codex_manager,
            "start",
            lambda _run_id: True,
        )
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        watcher = client.app.state.result_intake_monitor
        watcher.shutdown()
        expired_at = utc_now() - timedelta(seconds=6)

        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, started.json()["id"])
            assert run is not None
            run.status = "blocked"
            run.finished_at = expired_at
            run.structured_result = json.dumps(
                {
                    "process": {"exit_code": 0},
                    "workspace_evidence": {"changed_files": []},
                }
            )
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run.id)
            )
            assert monitor is not None
            monitor.monitor_state = "RESULT_INTEGRITY_BLOCKED"
            monitor.recovery_state = "INTEGRITY_BLOCKED"
            monitor.terminal_at = expired_at
            session.commit()

        assert watcher._has_pending_monitors() is False


def test_cross_owner_run_access_and_recovery_workspace_escapes_are_denied(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed"},
            timeout=15,
        )
        run_id = terminal["id"]

        other_password = "other-owner-password-123"
        password_hash, password_salt = hash_password(other_password)
        other_token = "vol19-other-owner-session-token-0001"
        with client.app.state.session_factory() as session:
            other = User(
                username="other-owner",
                password_hash=password_hash,
                password_salt=password_salt,
                is_active=True,
            )
            session.add(other)
            session.flush()
            session.add(
                SessionToken(
                    user_id=other.id,
                    token_hash=hash_token(other_token),
                    expires_at=utc_now() + timedelta(hours=1),
                )
            )
            session.commit()
        assert client.post("/api/auth/logout").status_code == 200
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert client.get(
            f"/api/codex-runs/{run_id}", headers=other_headers
        ).status_code == 404
        assert client.get(
            f"/api/codex-runs/{run_id}/result-envelope",
            headers=other_headers,
        ).status_code == 404
        assert client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=other_headers
        ).status_code == 404
        assert client.get(
            f"/api/tasks/{task_id}/codex-runs", headers=other_headers
        ).json() == []
        denied_start = start_codex_run(
            client, other_headers, task_id, pack
        )
        assert denied_start.status_code in {404, 409}
        with client.app.state.session_factory() as session:
            assert session.query(CodexRun).count() == 1

        manager = client.app.state.codex_manager
        authorized_root = manager.settings.worktree_root
        authorized_root.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside-authorized-worktree-root"
        outside.mkdir()
        traversal = authorized_root / ".." / outside.name
        escaped_link = authorized_root / "escaped-worktree"
        escaped_link.symlink_to(outside, target_is_directory=True)

        for unsafe_path in (traversal, escaped_link):
            with pytest.raises(CodexExecBridgeError) as exc_info:
                manager._recovery_worktree(
                    SimpleNamespace(worktree_path=str(unsafe_path))
                )
            assert exc_info.value.code == "RECOVERY_WORKTREE_OUTSIDE_ROOT"


def test_codex_created_symlink_escape_is_captured_and_blocked(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client, headers, marker="FAKE_SYMLINK_ESCAPE"
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"failed", "blocked"},
            timeout=15,
        )

    assert run["verification_target"]["process_spawned"] is False
    assert (
        "WORKSPACE_SYMLINK_UNSAFE"
        in run["result"]["boundary_confirmation"]["boundary_violations"]
    )
    assert {
        "path": "codex-escape-link",
        "reason": "unsafe_symlink",
    } in run["result"]["unexpected_excluded_artifacts"]
    assert (
        "codex-escape-link"
        in run["result"]["run_produced_changes"]["unexpected_files"]
    )
    link = Path(run["worktree_path"]) / "codex-escape-link"
    assert link.is_symlink()
    assert not link.resolve().is_relative_to(
        Path(run["worktree_path"]).resolve()
    )


def test_verification_is_not_running_until_exact_child_identity_is_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        monkeypatch.setattr(client.app.state.codex_manager, "start", lambda _run_id: True)
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        factory = client.app.state.session_factory

        with factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            run.status = "verifying"
            run.verification_process_spawned = True
            run.verification_status = "running"
            session.commit()
        unbound = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        assert unbound["canonical_status"] == "starting"

        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run_id)
            )
            assert monitor is not None
            monitor.verification_process_id = os.getpid()
            monitor.verification_process_start_identity = (
                capture_process_start_identity(os.getpid())
            )
            monitor.monitor_state = "VERIFYING"
            session.commit()
        bound = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        assert bound["canonical_status"] == "running"


def test_settling_child_identity_is_never_exposed_as_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        monkeypatch.setattr(
            client.app.state.codex_manager,
            "start",
            lambda _run_id: True,
        )
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]

        current_pid = os.getpid()
        current_identity = capture_process_start_identity(current_pid)
        assert process_identity_matches(current_pid, current_identity)
        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run_id)
            )
            snapshot = session.scalar(
                select(CodexLifecycleSnapshot).where(
                    CodexLifecycleSnapshot.run_id == run_id
                )
            )
            assert run is not None
            assert monitor is not None
            if snapshot is None:
                snapshot = CodexLifecycleSnapshot(
                    owner_id=monitor.owner_id,
                    task_id=run.task_id,
                    run_id=run.id,
                    monitor_id=monitor.id,
                    lifecycle_state="SETTLING",
                    phase="CODING",
                    current_activity="Settling terminal Run evidence",
                    next_owner_action=(
                        "Wait for TWOS to settle the durable Run evidence."
                    ),
                    process_live=False,
                    monitor_attached=True,
                    terminal_evidence_observed=True,
                )
                session.add(snapshot)
            # Reproduce the narrow post-process/pre-settlement window: the
            # coding Run is terminal, while the receipt-bound lifecycle is
            # still authoritatively settling.
            run.status = "completed"
            run.process_spawned = True
            run.exit_code = 0
            run.finished_at = utc_now()
            monitor.monitor_state = "RESULT_PENDING"
            monitor.process_id = current_pid
            monitor.process_start_identity = current_identity
            snapshot.lifecycle_state = "SETTLING"
            snapshot.current_activity = "Settling terminal Run evidence"
            snapshot.process_live = False
            snapshot.process_exited = True
            snapshot.terminal_evidence_observed = True
            session.commit()
        settling = client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        assert settling["canonical_status"] == "starting"
        assert settling["lifecycle"]["state"] == "settling"
        assert settling["terminal_truth"]["primary_status"] == "settling"
        assert settling["terminal_truth"]["primary_status"] != "needs_review"
        activity = next(
            item
            for item in client.get(
                "/api/run-activity", headers=headers
            ).json()["runs"]
            if item["run_id"] == run_id
        )
        assert activity["run_status"] == "settling"
        assert activity["terminal_truth"]["primary_status"] == "settling"
        assert activity["terminal_truth"]["primary_status"] != "needs_review"


def test_fast_terminal_receipt_never_regresses_through_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    real_load_state = codex_adapter_module.codex_exec_bridge.load_execution_state

    def hide_live_state(handle):
        observed = real_load_state(handle)
        if isinstance(observed, dict) and observed.get("state") == "RUNNING":
            return None
        return observed

    monkeypatch.setattr(
        codex_adapter_module.codex_exec_bridge,
        "load_execution_state",
        hide_live_state,
    )
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        observed_statuses = {started.json()["canonical_status"]}
        deadline = time.monotonic() + 20
        terminal = started.json()
        while time.monotonic() < deadline:
            terminal = client.get(
                f"/api/codex-runs/{started.json()['id']}", headers=headers
            ).json()
            observed_statuses.add(terminal["canonical_status"])
            if terminal["canonical_status"] in TERMINAL_CANONICAL_STATES:
                break
            time.sleep(0.02)

        assert terminal["canonical_status"] == "succeeded"
        assert "running" not in observed_statuses
        assert terminal["process_spawned"] is True
        audits = client.get("/api/audit", headers=headers).json()
        run_audits = [
            item for item in audits if item["entity_id"] == terminal["id"]
        ]
        assert not any(item["action"] == "codex_run_started" for item in run_audits)
        assert any(
            item["action"] == "codex_run_monitor_terminal_process_bound"
            for item in run_audits
        )
        _wait_for_result_envelope(client, headers, terminal["id"])
        candidate_response = client.get(
            f"/api/codex-runs/{terminal['id']}/delivery-candidate",
            headers=headers,
        )
        assert candidate_response.status_code == 200, candidate_response.text
        candidate = candidate_response.json()["candidate"]
        assert candidate is not None
        assert candidate["readiness_state"] == "ready", candidate
        with client.app.state.session_factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == terminal["id"]
                )
            )
            assert monitor is not None
            assert re.fullmatch(
                r"[0-9a-f]{64}", monitor.isolated_worktree_identity or ""
            )
            assert re.fullmatch(
                r"[0-9a-f]{64}", monitor.execution_location_identity or ""
            )


def test_live_bound_terminal_receipt_is_non_running_on_detail_and_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    live_bound = threading.Event()
    release_manager = threading.Event()

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        watcher = client.app.state.result_intake_monitor
        watcher.shutdown()
        manager = client.app.state.codex_manager
        real_bind = manager._bind_bridge_child
        held_once = False

        def bind_then_hold(*args, **kwargs):
            nonlocal held_once
            result = real_bind(*args, **kwargs)
            if (
                kwargs.get("phase") == "coding"
                and kwargs.get("terminal_receipt") is None
                and not held_once
            ):
                held_once = True
                live_bound.set()
                assert release_manager.wait(10)
            return result

        monkeypatch.setattr(manager, "_bind_bridge_child", bind_then_hold)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]

        try:
            assert live_bound.wait(5)
            running = client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            assert running["canonical_status"] == "running"
            running_activity = next(
                item
                for item in client.get(
                    "/api/run-activity", headers=headers
                ).json()["runs"]
                if item["run_id"] == run_id
            )
            assert running_activity["lifecycle"]["state"] == "running"
            assert running_activity["lifecycle"]["process_live"] is True

            handle = manager._existing_bridge_handle(run_id, "coding")
            assert handle is not None
            assert (
                codex_adapter_module.codex_exec_bridge.request_cancel(handle)
                == "requested"
            )
            deadline = time.monotonic() + 5
            receipt = None
            while time.monotonic() < deadline:
                receipt = (
                    codex_adapter_module.codex_exec_bridge.load_terminal_receipt(
                        handle
                    )
                )
                if receipt is not None:
                    break
                time.sleep(0.02)
            assert receipt is not None
            assert receipt["terminal_state"] == "CANCELLED"
            assert not process_identity_matches(
                int(receipt["child_process_id"]),
                str(receipt["child_process_start_identity"]),
            )

            settling = client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            assert settling["canonical_status"] != "running"
            assert settling["lifecycle"]["state"] == "settling"
            activity = next(
                item
                for item in client.get(
                    "/api/run-activity", headers=headers
                ).json()["runs"]
                if item["run_id"] == run_id
            )
            assert activity["run_status"] == "settling"
            assert activity["lifecycle"]["state"] == "settling"
            assert activity["lifecycle"]["process_live"] is False
        finally:
            release_manager.set()

        terminal = wait_for_run(
            client,
            headers,
            run_id,
            {"cancelled"},
            timeout=10,
        )
        assert terminal["started_at"] is not None
        assert terminal["finished_at"] is not None
        assert terminal["started_at"] <= terminal["finished_at"]


def test_owner_start_bindings_are_set_once_through_orm_and_raw_sqlite(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "owner-start-set-once.sqlite3"
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]

        replacements = {
            "approved_instruction_digest": "a" * 64,
            "start_idempotency_digest": "b" * 64,
            "start_request_digest": "c" * 64,
            "owner_start_confirmed_at": utc_now() + timedelta(days=1),
        }
        for field, replacement in replacements.items():
            with client.app.state.session_factory() as session:
                run = session.get(CodexRun, run_id)
                assert run is not None and getattr(run, field) not in {None, ""}
                setattr(run, field, replacement)
                with pytest.raises(RuntimeError, match="set only once"):
                    session.flush()
                session.rollback()

        raw_replacements = {
            "approved_instruction_digest": "d" * 64,
            "start_idempotency_digest": "e" * 64,
            "start_request_digest": "f" * 64,
            "owner_start_confirmed_at": "2099-01-01 00:00:00",
        }
        with closing(sqlite3.connect(database_path)) as connection, connection:
            for field, replacement in raw_replacements.items():
                with pytest.raises(sqlite3.IntegrityError, match="set only once"):
                    connection.execute(
                        f"UPDATE codex_runs SET {field} = ? WHERE id = ?",
                        (replacement, run_id),
                    )
                connection.rollback()

        client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)


def test_staged_baseline_is_not_run_attributed_and_special_staged_path_blocks(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    (source_repo / "README.md").write_text("# Owner-approved staged baseline\n")
    run_command(source_repo, "git", "add", "--", "README.md")
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_STAGE_SPECIAL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client, headers, started.json()["id"], {"failed"}, timeout=15
        )

    result = terminal["result"]
    special_path = "codex staged [special] #1.txt"
    assert "README.md" in result["workspace_evidence"]["attribution"]["baseline_preexisting"]
    assert "README.md" not in result["changed_files"]
    assert special_path in result["changed_files"]
    assert special_path in result["workspace_evidence"]["staged_files"]
    assert "CODEX_STAGED_CHANGES" in result["boundary_confirmation"]["boundary_violations"]
    assert result["boundary_confirmation"]["prohibited_git_mutation_observed"] is True


def test_untracked_filename_is_preserved_exactly_through_result_capture(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    exact_path = "codex exact\n\t\"name.txt"

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_UNTRACKED_EXACT_PATH",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed", "failed", "blocked"},
            timeout=15,
        )
        envelope = _wait_for_result_envelope(client, headers, terminal["id"])

    assert terminal["canonical_status"] == "succeeded"
    assert exact_path in terminal["result"]["changed_files"]
    assert exact_path in terminal["result"]["workspace_evidence"]["added_files"]
    assert exact_path in terminal["result"]["workspace_evidence"][
        "untracked_files"
    ]
    exact_evidence = next(
        item
        for item in terminal["result"]["changed_file_evidence"]
        if item["path"] == exact_path
    )
    assert exact_evidence["before_sha256"] is None
    assert exact_evidence["after_sha256"]
    assert exact_path in [item["path"] for item in envelope["changed_files"]]
    assert exact_path in envelope["advanced"]["workspace_evidence"][
        "untracked_files"
    ]


def test_untouched_owner_staged_baseline_is_preserved_without_boundary_violation(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    (source_repo / "README.md").write_text("# Owner-approved staged baseline\n")
    run_command(source_repo, "git", "add", "--", "README.md")

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed", "failed"},
            timeout=15,
        )

    result = terminal["result"]
    assert terminal["canonical_status"] == "succeeded"
    assert "README.md" in result["workspace_evidence"]["baseline_staged_files"]
    assert "README.md" in result["workspace_evidence"]["staged_files"]
    assert "README.md" in result["workspace_evidence"]["attribution"][
        "baseline_preexisting"
    ]
    assert "README.md" not in result["changed_files"]
    assert result["workspace_evidence"]["run_index_changed"] is False
    assert "CODEX_STAGED_CHANGES" not in result["boundary_confirmation"][
        "boundary_violations"
    ]


def test_unknown_model_reroute_blocks_before_verification_process_spawn(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_UNKNOWN_REROUTE",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"failed", "blocked"},
            timeout=15,
        )

    assert terminal["canonical_status"] == "failed"
    assert terminal["verification_target"]["process_spawned"] is False
    assert terminal["result"]["verification"]["status"] == "not_started"
    assert {item["capability"] for item in terminal["model_invocations"]} == {
        "coding"
    }
    evidence = terminal["model_invocations"][0]
    assert evidence["verified_real_invocation"] is False
    assert evidence["diagnostic_code"] == "unsupported_model_routing_event"


def test_coding_tag_mutation_blocks_as_git_boundary_change(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_TAG_MUTATION",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"failed", "blocked"},
            timeout=15,
        )

    boundary = terminal["result"]["boundary_confirmation"]
    assert terminal["canonical_status"] in {"failed", "blocked"}
    assert boundary["git_boundary_observed"] is True
    assert boundary["git_boundary_unchanged"] is False
    assert "GIT_BOUNDARY_CHANGED" in boundary["boundary_violations"]
    assert terminal["verification_target"]["process_spawned"] is False


def test_malformed_nonempty_handoff_remains_unavailable_and_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        watcher = client.app.state.result_intake_monitor
        watcher.shutdown()
        monkeypatch.setattr(
            codex_adapter_module,
            "reconcile_run_monitors",
            lambda *_args, **_kwargs: [],
        )
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with client.app.state.session_factory() as session:
                run = session.get(CodexRun, run_id)
                assert run is not None
                if run.status in {"completed", "failed", "blocked"}:
                    break
            time.sleep(0.02)
        assert run.status == "completed"

        malformed = {
            "schema": "twos.coding_handoff.v0",
            "status": "completed",
            "summary": "This malformed handoff must not be trusted.",
            "unexpected": True,
        }
        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            payload = json.loads(run.structured_result)
            payload["structured_handoff"] = malformed
            payload.setdefault("advanced_diagnostics", {})[
                "coding_final_agent_message"
            ] = json.dumps(malformed, separators=(",", ":"))
            run.structured_result = json.dumps(payload, separators=(",", ":"))
            session.commit()
        watcher.reconcile_now([run_id])
        envelope = _wait_for_result_envelope(client, headers, run_id)
        with client.app.state.session_factory() as session:
            persisted_envelope = session.scalar(
                select(CodexResultEnvelope).where(CodexResultEnvelope.run_id == run_id)
            )
            assert persisted_envelope is not None
            assert json.loads(persisted_envelope.structured_handoff_json) == {}

    assert envelope["structured_handoff_status"] == "unavailable"
    assert envelope["completion_classification"] == "result_incomplete"


def test_process_success_without_changes_keeps_process_classification(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_NO_CHANGE VOL19_NO_CHANGE_CLASSIFICATION",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed", "failed"},
            timeout=15,
        )
        envelope = _wait_for_result_envelope(client, headers, terminal["id"])

    assert terminal["result"]["coding_process"]["exit_code"] == 0
    assert terminal["result"]["changed_files"] == []
    assert envelope["completion_classification"] == (
        "succeeded_without_workspace_changes"
    )


def test_mobile_owner_run_controls_and_advanced_logs_have_safe_source_contract() -> None:
    root = STATIC_COCKPIT_DIR / "vol12_static_mvp"
    html = (root / "twos_command_center.html").read_text()
    css = (root / "styles.css").read_text()
    javascript = (root / "twos_command_center.js").read_text()

    assert 'id="start-codex-confirmation-dialog"' in html
    assert 'id="confirm-start-codex-run"' in html
    assert ">Review Run Result<" in html
    assert "<summary><span>Advanced</span>" in html
    assert "<details" in html and " open" not in html.split(
        "<summary><span>Advanced</span>", 1
    )[0].rsplit("<details", 1)[-1]
    assert "@media (max-width: 420px)" in css
    assert ".button-row > .button" in css
    assert "width: 100%;" in css
    assert "overflow-x: hidden;" in css
    assert "overflow-wrap: anywhere;" in css
    assert "startCodexConfirmationDialog.showModal()" in javascript
    assert "(automatic fallback blocked)" in javascript
    assert "approved same-provider fallback" not in javascript


@pytest.mark.parametrize("same_provider", [False, True])
def test_automatic_provider_fallback_is_always_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    same_provider: bool,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        with client.app.state.session_factory() as session:
            assignment = session.scalar(
                select(AIModelAssignment).where(
                    AIModelAssignment.task_id == task_id,
                    AIModelAssignment.assignment_version
                    == pack["assignment_version"],
                    AIModelAssignment.capability == "coding",
                )
            )
            assert assignment is not None
            assert assignment.assigned_model is not None
            assert assignment.fallback_allowed is True
            assert assignment.fallback_model is not None
            if same_provider:
                assignment.fallback_model.provider_id = (
                    assignment.assigned_model.provider_id
                )
                session.flush()
            assert (
                assignment.fallback_model.provider_id
                == assignment.assigned_model.provider_id
            ) is same_provider
            primary_id = assignment.assigned_model.id

            def eligibility(_session, model, **_kwargs):
                if model is not None and model.id == primary_id:
                    return False, "Primary is unavailable."
                return True, model.provider_model_id if model is not None else ""

            monkeypatch.setattr(
                self_hosting_module,
                "_eligible_codex_model",
                eligibility,
            )
            pack_row = session.get(CodexInstructionPack, pack["id"])
            assert pack_row is not None
            with pytest.raises(ValueError, match="Automatic provider fallback"):
                self_hosting_module.codex_capability_target(
                    session,
                    assignment.task,
                    pack_row,
                    "coding",
                    owner_id=pack_row.approved_by_user_id,
                    codex_executable=str(fake_codex),
                    child_environment={},
                )
            session.rollback()


def test_repeated_active_cancellation_is_idempotent(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            if active["process_spawned"]:
                break
            time.sleep(0.02)
        assert active["process_spawned"] is True

        first = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        second = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["cancellation_request_replayed"] is False
        assert second.json()["cancellation_request_replayed"] is True
        assert first.json()["cancellation_requested_at"]
        assert (
            second.json()["cancellation_requested_at"]
            == first.json()["cancellation_requested_at"]
        )
        audits = client.get("/api/audit", headers=headers).json()
        requests = [
            item
            for item in audits
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1
        terminal = wait_for_run(
            client,
            headers,
            run_id,
            {"cancelled"},
            timeout=5,
        )
        repeated_terminal = client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert repeated_terminal.status_code == 200
        assert repeated_terminal.json()["cancellation_request_replayed"] is True
        assert (
            repeated_terminal.json()["cancellation_requested_at"]
            == first.json()["cancellation_requested_at"]
        )
        assert terminal["cancelled"] is True


@pytest.mark.parametrize("publication_state", ["partial", "sealed"])
def test_same_runtime_prelaunch_cancel_never_crosses_process_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_state: str,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    prepared = threading.Event()
    release_preparation = threading.Event()

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        real_prepare = manager._prepare_bridge_phase

        def prepare_then_hold(run, **kwargs):
            if publication_state == "sealed":
                handle = real_prepare(run, **kwargs)
            else:
                phase_directory = (
                    manager._bridge_root
                    / manager._bridge_phase_key(int(run.id), "coding")
                )
                phase_directory.mkdir(mode=0o700, parents=True)
                partial_ticket = phase_directory / "ticket.json"
                partial_ticket.write_text("{}", encoding="utf-8")
                partial_ticket.chmod(0o600)
                handle = None
            prepared.set()
            assert release_preparation.wait(10)
            if handle is None:
                raise CodexExecBridgeError(
                    "TEST_PREPARATION_INTERRUPTED",
                    "The controlled partial ticket publication stopped.",
                )
            return handle

        monkeypatch.setattr(manager, "_prepare_bridge_phase", prepare_then_hold)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        try:
            assert prepared.wait(5)
            cancellation = client.post(
                f"/api/codex-runs/{run_id}/cancel", headers=headers
            )
            assert cancellation.status_code == 200, cancellation.text
            assert cancellation.json()["cancellation_request_replayed"] is False
            assert cancellation.json()["cancellation_requested_at"]
        finally:
            release_preparation.set()

        terminal = wait_for_run(
            client, headers, run_id, {"cancelled"}, timeout=10
        )
        assert terminal["process_spawned"] is False
        assert terminal["cancelled"] is True
        assert terminal["owner_summary"] == (
            "Codex execution was cancelled by the Owner."
        )
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()
        requests = [
            item
            for item in client.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1


@pytest.mark.parametrize("preparing_ticket", [False, True])
def test_durable_prelaunch_cancellation_survives_manager_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preparing_ticket: bool,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "durable-cancel-restart.sqlite3"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        monkeypatch.setattr(client.app.state.codex_manager, "start", lambda _run_id: True)
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        monkeypatch.setattr(
            client.app.state.codex_manager,
            "cancel",
            lambda _run_id: "unavailable",
        )
        interrupted = client.post(
            f"/api/codex-runs/{run_id}/cancel",
            headers=headers,
        )
        assert interrupted.status_code == 409
        persisted = client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        requested_at = persisted["cancellation_requested_at"]
        assert requested_at
        assert persisted["process_spawned"] is False
        if preparing_ticket:
            manager = client.app.state.codex_manager
            phase_directory = manager._bridge_root / manager._bridge_phase_key(
                run_id, "coding"
            )
            phase_directory.mkdir(mode=0o700, parents=True)
            partial_ticket = phase_directory / "ticket.json"
            partial_ticket.write_text("{}", encoding="utf-8")
            partial_ticket.chmod(0o600)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = restarted.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        assert terminal["status"] == "cancelled"
        assert terminal["canonical_status"] == "cancelled"
        assert terminal["cancelled"] is True
        assert terminal["process_spawned"] is False
        assert terminal["cancellation_requested_at"] == requested_at
        requests = [
            item
            for item in restarted.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1


def test_cancel_intent_reaches_active_detached_process_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "durable-active-cancel-restart.sqlite3"
    real_request_cancel = codex_adapter_module.codex_exec_bridge.request_cancel
    handle = None
    requested_at = None
    run_id = 0
    process_identity: tuple[int, str] | None = None

    first_client = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    )
    with first_client:
        headers = init_and_login(first_client)
        task_id = create_executable_task(
            first_client, headers, marker="FAKE_CANCEL"
        )
        pack = generate_pack(first_client, headers, task_id)
        approve_pack(first_client, headers, task_id, pack["id"])
        started = start_codex_run(first_client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = first_client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            if active["canonical_status"] == "running":
                break
            time.sleep(0.02)
        assert active["canonical_status"] == "running"
        handle = first_client.app.state.codex_manager._existing_bridge_handle(
            run_id, "coding"
        )
        assert handle is not None
        state = codex_adapter_module.codex_exec_bridge.load_execution_state(handle)
        assert isinstance(state, dict)
        process_identity = (
            int(state["child_process_id"]),
            str(state["child_process_start_identity"]),
        )
        assert process_identity_matches(*process_identity)

        def fail_delivery_once(_handle):
            assert _handle.ticket_digest == handle.ticket_digest
            raise CodexExecBridgeError(
                "TEST_CANCEL_DELIVERY_INTERRUPTED",
                "The cancellation marker was not delivered before restart.",
            )

        monkeypatch.setattr(
            codex_adapter_module.codex_exec_bridge,
            "request_cancel",
            fail_delivery_once,
        )
        interrupted = first_client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert interrupted.status_code == 200
        assert interrupted.json()["cancellation_request_replayed"] is False
        assert interrupted.json()["cancellation_requested_at"]
        persisted = first_client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        requested_at = persisted["cancellation_requested_at"]
        assert requested_at
        assert not (handle.phase_directory / "cancel.request.json").exists()
        requests = [
            item
            for item in first_client.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1

    monkeypatch.setattr(
        codex_adapter_module.codex_exec_bridge,
        "request_cancel",
        real_request_cancel,
    )
    assert handle is not None
    assert process_identity is not None
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(
            restarted,
            headers,
            run_id,
            {"cancelled"},
            timeout=15,
        )
        assert terminal["cancellation_requested_at"] == requested_at
        assert terminal["cancelled"] is True
        receipt = codex_adapter_module.codex_exec_bridge.load_terminal_receipt(
            handle
        )
        assert receipt is not None
        assert receipt["terminal_state"] == "CANCELLED"
        assert receipt["terminal_reason"] == "owner_cancel_requested"
        assert not process_identity_matches(*process_identity)
        requests = [
            item
            for item in restarted.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1
        replay = restarted.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert replay.status_code == 200
        assert replay.json()["cancellation_request_replayed"] is True
        assert replay.json()["cancellation_requested_at"] == requested_at

    time.sleep(1.7)
    assert not (Path(terminal["worktree_path"]) / "child-survived.txt").exists()


def test_recovery_cancels_after_completed_coding_before_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "coding-terminal-cancel-restart.sqlite3"
    coding_completed = threading.Event()
    release_handoff = threading.Event()
    client = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    )
    with client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        real_run_bridge_phase = manager._run_bridge_phase

        def handoff_after_completed_coding(*args, **kwargs):
            result = real_run_bridge_phase(*args, **kwargs)
            if kwargs.get("phase") == "coding":
                receipt = result.get("receipt")
                assert isinstance(receipt, dict)
                assert receipt["terminal_state"] == "COMPLETED"
                coding_completed.set()
                assert release_handoff.wait(timeout=5)
                raise codex_adapter_module._BridgeRuntimeHandoff()
            return result

        monkeypatch.setattr(
            manager,
            "_run_bridge_phase",
            handoff_after_completed_coding,
        )
        task_id = create_executable_task(
            client, headers, marker="FAKE_RUNTIME_HANDOFF"
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        assert coding_completed.wait(timeout=10)
        handle = manager._existing_bridge_handle(
            run_id, "coding"
        )
        assert handle is not None
        receipt = codex_adapter_module.codex_exec_bridge.load_terminal_receipt(
            handle
        )
        assert receipt is not None
        assert receipt["terminal_state"] == "COMPLETED"
        cancelled = client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        requested_at = cancelled.json()["cancellation_requested_at"]
        assert requested_at
        assert cancelled.json()["cancellation_request_replayed"] is False
        assert manager._existing_bridge_handle(run_id, "verification") is None
        with manager._lock:
            manager._stopping = True
        release_handoff.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with manager._lock:
                if run_id not in manager._workers:
                    break
            time.sleep(0.02)
        with manager._lock:
            assert run_id not in manager._workers

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(
            restarted,
            headers,
            run_id,
            {"cancelled"},
            timeout=15,
        )
        assert terminal["cancelled"] is True
        assert terminal["result"]["coding_process"]["status"] == "completed"
        assert terminal["result"]["coding_process"]["cancelled"] is False
        assert terminal["verification_target"]["process_spawned"] is False
        assert "Owner cancelled" in terminal["verification_target"]["summary"]
        assert "Owner cancelled" in terminal["result"]["verification"]["summary"]
        assert "Owner cancellation" in terminal["result"]["verification_process"][
            "failure"
        ]
        assert "Owner cancellation" in terminal["result"][
            "verification_invocation"
        ]["failure"]
        assert "Owner cancellation" in terminal["result"]["task_acceptance"][
            "reason"
        ]
        assert terminal["cancellation_requested_at"] == requested_at
        requests = [
            item
            for item in restarted.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1


def test_recovery_preserves_completed_verification_truth_after_late_cancel_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "verification-terminal-cancel-restart.sqlite3"
    client = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    )
    verification_completed = threading.Event()
    release_handoff = threading.Event()
    with client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        real_execute_verification = manager._execute_verification

        def handoff_after_completed_verification(*args, **kwargs):
            result = real_execute_verification(*args, **kwargs)
            assert result["status"] == "completed"
            verification_completed.set()
            assert release_handoff.wait(timeout=5)
            raise codex_adapter_module._BridgeRuntimeHandoff()

        monkeypatch.setattr(
            manager,
            "_execute_verification",
            handoff_after_completed_verification,
        )
        task_id = create_executable_task(
            client, headers, marker="FAKE_RUNTIME_HANDOFF"
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        assert verification_completed.wait(timeout=15)
        verification_handle = manager._existing_bridge_handle(
            run_id, "verification"
        )
        assert verification_handle is not None
        receipt = codex_adapter_module.codex_exec_bridge.load_terminal_receipt(
            verification_handle
        )
        assert receipt is not None
        assert receipt["terminal_state"] == "COMPLETED"
        late_cancel = client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert late_cancel.status_code == 409
        persisted = client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        requested_at = persisted["cancellation_requested_at"]
        assert requested_at
        with manager._lock:
            manager._stopping = True
        release_handoff.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with manager._lock:
                if run_id not in manager._workers:
                    break
            time.sleep(0.02)
        with manager._lock:
            assert run_id not in manager._workers

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(
            restarted,
            headers,
            run_id,
            {"completed"},
            timeout=15,
        )
        assert terminal["cancelled"] is False
        assert terminal["result"]["coding_process"]["status"] == "completed"
        assert terminal["result"]["verification_process"]["status"] == "completed"
        assert terminal["result"]["verification_verdict"]["status"] == "passed"
        assert terminal["cancellation_requested_at"] == requested_at


def test_recovery_honors_cancel_from_sealed_verification_ticket_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "verification-prelaunch-cancel-restart.sqlite3"
    verification_ticket_sealed = threading.Event()
    client = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    )
    with client:
        headers = init_and_login(client)
        manager = client.app.state.codex_manager
        real_prepare_bridge_phase = manager._prepare_bridge_phase

        def handoff_after_sealed_verification_ticket(*args, **kwargs):
            handle = real_prepare_bridge_phase(*args, **kwargs)
            if kwargs.get("phase") == "verification":
                verification_ticket_sealed.set()
                with manager._lock:
                    manager._stopping = True
                raise codex_adapter_module._BridgeRuntimeHandoff()
            return handle

        monkeypatch.setattr(
            manager,
            "_prepare_bridge_phase",
            handoff_after_sealed_verification_ticket,
        )
        task_id = create_executable_task(
            client, headers, marker="FAKE_RUNTIME_HANDOFF"
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        assert verification_ticket_sealed.wait(timeout=12)
        verification_handle = manager._existing_bridge_handle(
            run_id, "verification"
        )
        assert verification_handle is not None
        assert (
            codex_adapter_module.codex_exec_bridge.load_launch_info(
                verification_handle
            )
            is None
        )
        assert (
            codex_adapter_module.codex_exec_bridge.load_terminal_receipt(
                verification_handle
            )
            is None
        )
        cancelled = client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        requested_at = cancelled.json()["cancellation_requested_at"]
        assert requested_at

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(
            restarted,
            headers,
            run_id,
            {"cancelled"},
            timeout=15,
        )
        assert terminal["cancelled"] is True
        assert terminal["cancellation_requested_at"] == requested_at
        assert terminal["result"]["coding_process"]["status"] == "completed"
        assert terminal["result"]["coding_process"]["cancelled"] is False
        assert terminal["verification_target"]["process_spawned"] is False
        assert terminal["result"]["verification_process"]["status"] == "not_started"
        assert (
            codex_adapter_module.codex_exec_bridge.load_launch_info(
                verification_handle
            )
            is None
        )


def test_verification_cancellation_preserves_completed_coding_truth(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=20) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client, headers, marker="FAKE_RUNTIME_HANDOFF"
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        deadline = time.monotonic() + 12
        verification_handle = None
        while time.monotonic() < deadline:
            active = client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            try:
                verification_handle = (
                    client.app.state.codex_manager._existing_bridge_handle(
                        run_id, "verification"
                    )
                )
            except CodexExecBridgeError:
                verification_handle = None
            state = (
                codex_adapter_module.codex_exec_bridge.load_execution_state(
                    verification_handle
                )
                if verification_handle is not None
                else None
            )
            if (
                active["status"] == "verifying"
                and active["verification_target"]["process_spawned"] is True
                and isinstance(state, dict)
                and state.get("state") == "RUNNING"
            ):
                break
            time.sleep(0.02)
        assert verification_handle is not None
        assert active["verification_target"]["process_spawned"] is True
        cancelled = client.post(
            f"/api/codex-runs/{run_id}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        terminal = wait_for_run(
            client,
            headers,
            run_id,
            {"cancelled"},
            timeout=15,
        )
        time.sleep(0.2)
        terminal = client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        envelope = _wait_for_result_envelope(client, headers, run_id)
        assert terminal["status"] == "cancelled"
        assert terminal["canonical_status"] == "cancelled"
        assert terminal["cancelled"] is True
        assert terminal["exit_code"] == 0
        assert terminal["result"]["coding_process"]["status"] == "completed"
        assert terminal["result"]["coding_process"]["cancelled"] is False
        assert terminal["verification_target"]["cancelled"] is True
        assert terminal["result"]["verification_process"]["status"] == "cancelled"
        assert envelope["completion_classification"] == "succeeded_with_changes"
        process_evidence = envelope["advanced"]["process_evidence"]
        assert process_evidence["cancelled"] is True
        assert process_evidence["coding_cancelled"] is False
        assert process_evidence["verification_cancelled"] is True
        coding_invocation = next(
            item
            for item in terminal["model_invocations"]
            if item["capability"] == "coding"
        )
        verification_invocation = next(
            item
            for item in terminal["model_invocations"]
            if item["capability"] == "verification"
        )
        assert coding_invocation["outcome"] == "succeeded"
        assert coding_invocation["cancelled"] is False
        assert verification_invocation["outcome"] == "cancelled"
        assert verification_invocation["cancelled"] is True
        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            assert run.task.status == "cancelled"
            assert run.exit_code == 0
            assert run.verification_cancelled is True


def test_concurrent_cancellation_creates_one_owner_intent(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=20) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = client.get(
                f"/api/codex-runs/{run_id}", headers=headers
            ).json()
            if active["canonical_status"] == "running":
                break
            time.sleep(0.02)
        assert active["canonical_status"] == "running"

        barrier = threading.Barrier(3)
        responses = []

        def request_cancel() -> None:
            barrier.wait()
            responses.append(
                client.post(
                    f"/api/codex-runs/{run_id}/cancel", headers=headers
                )
            )

        workers = [threading.Thread(target=request_cancel) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive()

        assert [response.status_code for response in responses] == [200, 200]
        payloads = [response.json() for response in responses]
        assert sorted(
            payload["cancellation_request_replayed"] for payload in payloads
        ) == [False, True]
        timestamps = {
            payload["cancellation_requested_at"] for payload in payloads
        }
        assert len(timestamps) == 1
        assert None not in timestamps
        terminal = wait_for_run(
            client, headers, run_id, {"cancelled"}, timeout=10
        )
        assert terminal["cancelled"] is True
        requests = [
            item
            for item in client.get("/api/audit", headers=headers).json()
            if item["action"] == "codex_cancel_requested"
            and item["entity_id"] == run_id
        ]
        assert len(requests) == 1


def test_active_run_blocks_second_task_in_same_authorized_workspace(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        first_task = create_executable_task(client, headers, marker="FAKE_CANCEL")
        first_pack = generate_pack(client, headers, first_task)
        approve_pack(client, headers, first_task, first_pack["id"])
        first = start_codex_run(client, headers, first_task, first_pack)
        assert first.status_code == 200, first.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = client.get(
                f"/api/codex-runs/{first.json()['id']}", headers=headers
            ).json()
            if active["canonical_status"] == "running":
                break
            time.sleep(0.02)
        assert active["canonical_status"] == "running"

        second_task = create_executable_task(client, headers)
        second_pack = generate_pack(client, headers, second_task)
        approve_pack(client, headers, second_task, second_pack["id"])
        blocked = start_codex_run(client, headers, second_task, second_pack)
        assert blocked.status_code == 409, blocked.text
        details = blocked.json()["error"]["details"]
        assert any(
            item["code"] == "ACTIVE_WORKSPACE_RUN_EXISTS"
            for item in details["blockers"]
        )
        assert client.get(
            f"/api/tasks/{second_task}/codex-runs", headers=headers
        ).json() == []
        cancelled = client.post(
            f"/api/codex-runs/{first.json()['id']}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        terminal = wait_for_run(
            client,
            headers,
            first.json()["id"],
            {"cancelled"},
            timeout=10,
        )
        assert terminal["status"] == "cancelled"
        assert terminal["canonical_status"] == "cancelled"
        assert terminal["cancelled"] is True
        assert terminal["cancellation_requested_at"] is not None
        with client.app.state.session_factory() as session:
            persisted = session.get(CodexRun, first.json()["id"])
            assert persisted is not None
            assert persisted.status == "cancelled"
            assert persisted.finished_at is not None
            assert persisted.task.status == "cancelled"
