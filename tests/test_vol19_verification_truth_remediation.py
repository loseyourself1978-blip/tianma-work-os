from __future__ import annotations

import json
import subprocess
import sys
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
    make_fake_codex,
    make_source_repo,
    start_codex_run,
    wait_for_run,
)
from twos_runtime.models import (
    AIModelInvocationEvidence,
    ApplySession,
    CodexExecutionAttempt,
    CodexRun,
    LocalCommitExecution,
    PushExecution,
)


def make_local_verifier(
    tmp_path: Path,
    *,
    forced_failure: bool = False,
    name: str = "deterministic-local-verifier.py",
) -> tuple[str, ...]:
    script = tmp_path / name
    script.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "def emit(value):",
                "    print(json.dumps(value, separators=(',', ':')), flush=True)",
                "target = Path('codex-result.txt')",
                "content_ok = target.is_file() and target.read_text() == 'isolated result\\n'",
                "secret_free = all(key not in os.environ for key in (",
                "    'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'CODEX_HOME',",
                "    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',",
                "    'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',",
                "))",
                f"passed = content_ok and secret_free and {not forced_failure!r}",
                "result = {",
                "    'schema': 'twos.verification.v1',",
                "    'verdict': 'pass' if passed else 'fail',",
                "    'changed_files_checked': ['codex-result.txt'],",
                "    'unexpected_files': [],",
                "    'exact_content': 'pass' if passed else 'fail',",
                "    'tests': 'pass' if passed else 'fail',",
                "    'git_boundary': 'pass',",
                "    'remote_boundary': 'pass',",
                "}",
                "turn_id = 'fixture-local-verification-turn-001'",
                "emit({'type': 'thread.started', 'thread_id': 'fixture-local-verification-thread-001'})",
                "emit({'type': 'turn.started', 'turn_id': turn_id})",
                "emit({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(result, separators=(',', ':'))}})",
                "emit({'type': 'turn.completed', 'turn_id': turn_id, 'usage': {'input_tokens': 0, 'output_tokens': 0}})",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return (str(Path(sys.executable).resolve()), str(script.resolve()))


def _result_envelope(client, headers: dict[str, str], run_id: int) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/codex-runs/{run_id}/result-envelope", headers=headers
        )
        if response.status_code == 200:
            return response.json()
        assert response.status_code == 404, response.text
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not publish a Result envelope")


def test_real_coding_then_deterministic_verification_persists_one_terminal_truth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-must-not-reach-verifier")
    monkeypatch.setenv("HTTPS_PROXY", "https://fixture-proxy.invalid")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "forbidden-codex-home"))
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "terminal-truth.sqlite3"
    command = make_local_verifier(tmp_path)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
        local_verification_command=command,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(
            client,
            headers,
            marker="FAKE_TEST_COMMAND FAKE_READ_ONLY_GIT_INSPECTION",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client, headers, started.json()["id"], {"completed"}, timeout=20
        )
        run_id = terminal["id"]

        assert terminal["exit_code"] == 0
        assert terminal["result"]["coding_process"]["status"] == "completed"
        assert terminal["verification_target"]["process_spawned"] is True
        assert terminal["verification_target"]["exit_code"] == 0
        assert terminal["result"]["verification"]["mode"] == "local_command"
        assert terminal["result"]["verification_process"]["status"] == "completed"
        assert terminal["result"]["verification_invocation"] == {
            **terminal["result"]["verification_invocation"],
            "mode": "local_command",
            "process_execution_verified": True,
            "codex_turn_verified": False,
            "model_provider_invoked": False,
            "requested_model": "",
            "actual_resolved_model": None,
            "actual_model_identity_verified": False,
            "failure": "",
        }
        assert terminal["result"]["verification_verdict"]["status"] == "passed"
        assert terminal["result"]["verification"]["tests"] == [
            {
                "name": "deterministic verification contract",
                "status": "passed",
                "summary": "Structured local Verification checks passed.",
            }
        ]
        assert terminal["lifecycle"]["verification_started"] is True
        assert terminal["result"]["verification_process"]["sidecar_state"] == "missing"
        assert terminal["result"]["verification_process"]["result_transport"] == (
            "codex_exec_bridge_jsonl"
        )
        assert terminal["result"]["verification_process"][
            "terminal_receipt_verified"
        ] is True

        envelope_response = _result_envelope(client, headers, run_id)
        envelope = envelope_response["result"]
        assert envelope["completion_classification"] == "succeeded_with_changes"
        assert envelope["result_integrity"] == "VERIFIED"
        assert envelope["verification_result"]["verdict"] == "PASS"
        assert envelope["execution_successful"] is True
        activity = next(
            item
            for item in client.get("/api/run-activity", headers=headers).json()[
                "runs"
            ]
            if item["run_id"] == run_id
        )
        refreshed = client.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        assert refreshed["terminal_truth"] == activity["terminal_truth"]
        assert refreshed["terminal_truth"] == envelope_response["terminal_truth"]
        truth = refreshed["terminal_truth"]
        assert truth["coding"]["status"] == "succeeded"
        assert truth["verification"]["status"] == "passed"
        assert truth["result"]["state"] == "available"
        assert truth["workspace"]["state"] == "captured"
        assert truth["primary_status"] == "result_available"

        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == run_id,
                    CodexExecutionAttempt.phase == "VERIFICATION",
                )
            )
            assert attempt is not None
            assert attempt.attempt_state == "COMPLETED"
            assert attempt.process_id is not None
            assert len(attempt.process_start_identity) == 64
            assert len(attempt.ticket_digest) == 64
            assert len(attempt.receipt_digest) == 64
            assert attempt.sidecar_state == "MISSING"
            assert attempt.jsonl_recovery_candidate is True
            assert attempt.result_resolution_source == "JSONL_FINAL_MESSAGE_RECOVERY"
            evidence = list(
                session.scalars(
                    select(AIModelInvocationEvidence).where(
                        AIModelInvocationEvidence.codex_run_id == run_id,
                        AIModelInvocationEvidence.capability == "verification",
                    )
                ).all()
            )
            assert evidence == []
            assert session.query(ApplySession).count() == 0
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0
            protected_spool = Path(attempt.protected_spool_locator)
            receipt_mtime = (protected_spool / "terminal.json").stat().st_mtime_ns

        run_worktree = Path(refreshed["worktree_path"])
        assert (run_worktree / "codex-result.txt").read_text() == "isolated result\n"
        assert subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=run_worktree,
            text=True,
            capture_output=True,
            check=True,
        ).stdout == "?? codex-result.txt\n"
        assert subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=run_worktree,
            text=True,
            capture_output=True,
            check=True,
        ).stdout == ""
        assert subprocess.run(
            ["git", "remote"],
            cwd=run_worktree,
            text=True,
            capture_output=True,
            check=True,
        ).stdout == ""

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
        local_verification_command=command,
    ) as restarted:
        headers = init_and_login(restarted)
        persisted = restarted.get(
            f"/api/codex-runs/{run_id}", headers=headers
        ).json()
        assert persisted["terminal_truth"] == truth
        with restarted.app.state.session_factory() as session:
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == run_id,
                    CodexExecutionAttempt.phase == "VERIFICATION",
                )
            )
            assert attempt is not None
            assert (Path(attempt.protected_spool_locator) / "terminal.json").stat().st_mtime_ns == receipt_mtime
        assert restarted.app.state.codex_manager._local_verification_backend_selected(
            run_id,
            Path(persisted["worktree_path"]),
        ) is True

    changed_command = make_local_verifier(
        tmp_path,
        name="changed-deterministic-local-verifier.py",
    )
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
        local_verification_command=changed_command,
    ) as drifted:
        with pytest.raises(RuntimeError) as error:
            drifted.app.state.codex_manager._local_verification_backend_selected(
                run_id,
                Path(persisted["worktree_path"]),
            )
        assert getattr(error.value, "code", "") == (
            "VERIFICATION_BACKEND_CONFIGURATION_DRIFT"
        )


def test_local_verification_rejects_relative_worktree_script_argument(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    relative_worktree = tmp_path / "worktrees" / "relative-command"
    relative_worktree.mkdir(parents=True)
    (relative_worktree / "verifier.py").write_text("raise SystemExit(0)\n")
    command = (str(Path(sys.executable).resolve()), "verifier.py")
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        local_verification_command=command,
    ) as client:
        with pytest.raises(RuntimeError, match="absolute canonical paths"):
            client.app.state.codex_manager._local_verification_command(
                relative_worktree
            )


def test_verification_failure_does_not_relabel_successful_coding_as_failed(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    command = make_local_verifier(tmp_path, forced_failure=True)
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=command,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_TEST_COMMAND")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client, headers, started.json()["id"], {"failed"}, timeout=20
        )
        envelope_response = _result_envelope(client, headers, terminal["id"])
        refreshed = client.get(
            f"/api/codex-runs/{terminal['id']}", headers=headers
        ).json()

        assert refreshed["exit_code"] == 0
        assert refreshed["terminal_truth"]["coding"]["status"] == "succeeded"
        assert refreshed["terminal_truth"]["verification"]["status"] == "failed"
        assert refreshed["terminal_truth"]["primary_status"] == "needs_review"
        assert refreshed["terminal_truth"]["primary_label"] == "Needs Review"
        assert refreshed["terminal_truth"] == envelope_response["terminal_truth"]
        assert "Coding and Verification completed" not in json.dumps(refreshed)
        assert refreshed["result"]["verification_verdict"]["status"] == "failed"
        assert (
            envelope_response["result"]["completion_classification"]
            == "succeeded_with_changes"
        )
        assert envelope_response["result"]["requested_model_accepted"] is True
        assert envelope_response["result"]["coding_result"][
            "verified_real_invocation"
        ] is True
        assert envelope_response["result"]["execution_successful"] is False
        assert (
            envelope_response["result"]["source_result_eligible_for_owner_review"]
            is True
        )


def test_local_verification_launch_failure_persists_exact_unavailable_reason(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    missing_verifier = tmp_path / "missing-verifier"
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=(str(missing_verifier.resolve()),),
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_TEST_COMMAND")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        terminal = wait_for_run(
            client, headers, started.json()["id"], {"failed"}, timeout=20
        )

        assert terminal["exit_code"] == 0
        assert terminal["verification_target"]["process_spawned"] is False
        assert terminal["verification_target"]["status"] == "failed"
        assert (
            terminal["result"]["verification_process"]["failure"]
            == "The local Verification executable is unavailable."
        )
        truth = terminal["terminal_truth"]
        assert truth["coding"]["status"] == "succeeded"
        assert truth["verification"]["started"] is False
        assert truth["verification"]["status"] == "unavailable"
        assert (
            truth["verification"]["reason"]
            == "The local Verification executable is unavailable."
        )
        assert truth["primary_status"] == "needs_review"
        with client.app.state.session_factory() as session:
            assert session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == terminal["id"],
                    CodexExecutionAttempt.phase == "VERIFICATION",
                )
            ) is None
