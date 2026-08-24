from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, inspect, select, text

from tests.test_self_hosting import (
    approve_pack,
    configure_test_model_registry,
    create_development_task,
    generate_pack,
    init_and_login,
    make_client,
    make_fake_codex,
    make_source_repo,
    start_codex_run,
    wait_for_run,
)
from tests.test_vol18_delivery_candidate import (
    CandidateFixture,
    build_candidate_fixture,
    close_candidate_fixture,
)
from twos_runtime.models import (
    AIModelInvocationEvidence,
    AuditEvent,
    CodexExecutionAttempt,
    CodexLifecycleSnapshot,
    CodexResultArtifact,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
    DeliveryCandidate,
    HandoffInstructionDraft,
    HandoffReview,
    SchemaVersion,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime import codex_exec_bridge
from twos_runtime import result_intake as result_intake_module
from twos_runtime.codex_adapter import CodexExecutionManager
from twos_runtime.codex_exec_bridge import (
    handle_from_ticket_path,
    load_execution_state,
    load_terminal_receipt,
    process_identity_matches as bridge_process_identity_matches,
)
from twos_runtime.result_intake import (
    MAX_RESULT_BYTES,
    MONITOR_STATES,
    RECOVERY_STATES,
    RESULT_INTAKE_POLICY,
    ResultIntakeError,
    ResultIntakeMonitor,
    approve_instruction_draft,
    canonical_sha256,
    ensure_run_monitor,
    get_or_create_handoff_review,
    get_or_create_instruction_draft,
    handoff_review_out,
    import_codex_result,
    ingest_result_file,
    ingest_result_payload,
    instruction_draft_out,
    monitor_out,
    observe_monitor,
    reconcile_run_monitors,
    reconnect_run_monitor,
    result_envelope_out,
)
from twos_runtime.security import hash_password, hash_token


FORBIDDEN_AUTOMATIC_ACTIONS = (
    "automatic Result acceptance",
    "automatic Candidate",
    "automatic Apply",
    "automatic Revert",
    "automatic next Codex Run",
)
SECRET_SENTINEL = "phase18-result-intake-secret-must-not-leak"
ABSOLUTE_PATH_SENTINEL = "/private/tmp/phase18-result-intake-private/result.json"
SECRET_SHAPED_SENTINELS = (
    "sk-proj-" + "A" * 32,
    "ghp_" + "0123456789ABCDEFGHIJKLMN",
    "github_pat_" + "0123456789_ABCDEFGHIJKLMN",
    "xoxb-" + "123456789012-abcdefghijkl",
    "AKIA" + "ABCDEFGHIJKLMNOP",
)


def _make_restart_recovery_codex(
    tmp_path: Path,
    *,
    coding_delay: float = 4.0,
    coding_final_message_mismatch: bool = False,
    coding_contract_invalid: bool = False,
) -> Path:
    executable = tmp_path / "restart-recovery-codex"
    executable.write_text(
        f'''#!/usr/bin/env python3
import json
import pathlib
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print("codex-cli restart-recovery-fixture")
    raise SystemExit(0)
if args == ["exec", "--help"]:
    print("Usage: codex exec --model MODEL --json --output-last-message PATH [PROMPT]")
    raise SystemExit(0)
if args == ["login", "--help"]:
    print("Usage: codex login [status]")
    raise SystemExit(0)
if args == ["login", "status"]:
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if not args or args[0] != "exec":
    raise SystemExit(64)

model = args[args.index("--model") + 1]
sandbox = args[args.index("--sandbox") + 1]
last_message = (
    pathlib.Path(args[args.index("--output-last-message") + 1])
    if "--output-last-message" in args
    else None
)
prompt = sys.stdin.read()
phase = "coding" if sandbox == "workspace-write" else "verification"
counter = pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + f".{{phase}}-count")
counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1")
pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + f".{{phase}}-started").write_text("started\\n")

def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)

turn_id = f"restart-recovery-{{phase}}-turn"
emit({{"type":"thread.started","thread_id":f"restart-recovery-{{phase}}-thread","actual_model_identifier":model}})
emit({{"type":"turn.started","turn_id":turn_id}})
if phase == "coding":
    time.sleep({coding_delay!r})
    pathlib.Path("codex-result.txt").write_text("restart recovery result\\n")
    if {coding_contract_invalid!r}:
        message = "plain transport output without a Coding handoff contract"
    else:
        message = json.dumps({{
            "schema":"twos.coding_handoff.v1",
            "status":"completed",
            "summary":"1 passed in restart recovery validation",
        }}, separators=(",", ":"))
else:
    result = {{
        "schema":"twos.verification.v1",
        "verdict":"pass",
        "changed_files_checked":["codex-result.txt"],
        "unexpected_files":[],
        "exact_content":"pass",
        "tests":"pass",
        "git_boundary":"pass",
        "remote_boundary":"pass",
    }}
    message = json.dumps(result, separators=(",", ":"))
durable_message = message
if phase == "coding" and {coding_final_message_mismatch!r}:
    durable_message = message + " tampered durable final message"
if last_message is not None:
    last_message.write_text(durable_message)
emitted_message = (
    durable_message
    if last_message is None and phase == "coding" and {coding_final_message_mismatch!r}
    else message
)
emit({{"type":"item.completed","item":{{"id":f"restart-recovery-{{phase}}-message","type":"agent_message","text":emitted_message}}}})
emit({{"type":"turn.completed","turn_id":turn_id,"usage":{{"input_tokens":5,"output_tokens":3}}}})
''',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _wait_for_bridge_handle(
    spool_root: Path,
    run_id: int,
    phase: str,
    *,
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seals = list(spool_root.glob(f"*/run-{run_id}-{phase}/ticket.seal.json"))
        if len(seals) == 1:
            return handle_from_ticket_path(seals[0].with_name("ticket.json"))
        time.sleep(0.02)
    raise AssertionError(f"Durable {phase} bridge ticket was not published.")


def _bridge_ticket_for_run(run: CodexRun, *, phase: str) -> dict[str, object]:
    connectivity = (
        run.verification_connectivity_evidence
        if phase == "verification"
        else run.execution_connectivity_evidence
    )
    requested_model = (
        run.verification_model_identifier
        if phase == "verification"
        else run.requested_model_identifier
    )
    return {
        "phase": phase,
        "phase_key": f"run-{run.id}-{phase}",
        "working_directory": run.worktree_path,
        "identity": {
            "owner_id": int(run.pack.approved_by_user_id),
            "run_id": int(run.id),
            "task_id": int(run.task_id),
            "task_version": int(run.task_version),
            "pack_id": int(run.pack_id),
            "pack_version": int(run.pack.version),
            "coding_assignment_id": int(run.execution_assignment.id),
            "coding_assignment_version": int(
                run.execution_assignment.assignment_version
            ),
            "verification_assignment_id": int(run.verification_assignment.id),
            "verification_assignment_version": int(
                run.verification_assignment.assignment_version
            ),
            "routing_snapshot_identity": run.routing_snapshot_hash,
            "source_snapshot_identity": run.source_snapshot_digest,
            "connectivity_evidence_identity": str(
                connectivity.evidence_digest if connectivity is not None else ""
            ),
            "requested_model_identifier": requested_model,
            "executable_fingerprint": "a" * 64,
            "source_remote_fingerprint": "b" * 64,
            "git_boundary_fingerprint": "c" * 64,
            "workspace_snapshot_digest": run.source_snapshot_digest,
            "pre_verification_workspace_digest": run.source_snapshot_digest,
        },
    }


@contextmanager
def result_intake_fixture(
    tmp_path: Path,
    *,
    run_status: str = "completed",
    verification_verdict: str = "passed",
):
    fixture = build_candidate_fixture(
        tmp_path,
        run_status=run_status,
        verification_verdict=verification_verdict,
    )
    try:
        with fixture.client.app.state.session_factory() as session:
            run = session.get(CodexRun, fixture.run_id)
            assert run is not None
            model_by_capability = {
                "coding": run.requested_model_identifier,
                "verification": run.verification_model_identifier,
            }
            for evidence in session.scalars(
                select(AIModelInvocationEvidence).where(
                    AIModelInvocationEvidence.codex_run_id == run.id
                )
            ).all():
                model_identifier = model_by_capability[evidence.capability]
                process = json.loads(evidence.process_evidence)
                process.update(
                    {
                        "actual_model_identity_verified": True,
                        "model_identity_observed": True,
                        "model_identity_source": "explicit_actual_model_metadata",
                    }
                )
                evidence.actual_invoked_model_identifier = model_identifier
                evidence.process_evidence = json.dumps(
                    process,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            session.commit()
        yield fixture
    finally:
        close_candidate_fixture(fixture)


def _run(session, fixture: CandidateFixture) -> CodexRun:
    run = session.get(CodexRun, fixture.run_id)
    assert run is not None
    return run


def valid_result_payload(
    session,
    fixture: CandidateFixture,
    *,
    explicit_identity: bool = True,
) -> dict[str, object]:
    run = _run(session, fixture)
    payload = json.loads(run.structured_result)
    payload.update(
        {
            "final_response": (
                "Coding completed the bounded task and independent Verification passed."
            ),
            "tests": [
                {
                    "command": "pytest -q",
                    "status": "passed",
                    "summary": "All focused validation passed.",
                }
            ],
            "warnings": ["One non-blocking compatibility warning."],
            "limitations": ["Owner approval remains required for later actions."],
        }
    )
    if explicit_identity:
        coding_version = (
            run.execution_assignment.assignment_version
            if run.execution_assignment is not None
            else run.assignment_version
        )
        verification_version = (
            run.verification_assignment.assignment_version
            if run.verification_assignment is not None
            else run.assignment_version
        )
        payload["identity"] = {
            "run_id": run.id,
            "task_id": run.task_id,
            "task_version": run.task_version,
            "pack_id": run.pack_id,
            "pack_version": run.pack.version,
            "coding_assignment_id": run.execution_assignment_id,
            "coding_assignment_version": coding_version,
            "verification_assignment_id": run.verification_assignment_id,
            "verification_assignment_version": verification_version,
            "routing_snapshot_identity": run.routing_snapshot_hash,
            "source_snapshot_identity": run.source_snapshot_digest,
        }
    return payload


def _second_owner_headers(fixture: CandidateFixture) -> dict[str, str]:
    raw_token = "phase18-result-intake-second-owner-session"
    password_hash, password_salt = hash_password("second-owner-password")
    with fixture.client.app.state.session_factory() as session:
        second_owner = User(
            username="second-owner",
            password_hash=password_hash,
            password_salt=password_salt,
            is_active=True,
        )
        session.add(second_owner)
        session.flush()
        session.add(
            SessionToken(
                user_id=second_owner.id,
                token_hash=hash_token(raw_token),
                created_at=utc_now(),
                expires_at=utc_now() + timedelta(hours=1),
            )
        )
        session.commit()
    return {"Authorization": f"Bearer {raw_token}"}


def _wait_for_envelope(factory, run_id: int, timeout: float = 4.0) -> CodexResultEnvelope:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with factory() as session:
            envelope = session.scalar(
                select(CodexResultEnvelope).where(
                    CodexResultEnvelope.run_id == run_id
                )
            )
            if envelope is not None:
                session.expunge(envelope)
                return envelope
        time.sleep(0.05)
    raise AssertionError("The bounded Result Intake watcher did not persist an envelope.")


def test_vol18_004_migration_and_durable_entities_are_present(tmp_path: Path) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        engine = fixture.client.app.state.engine
        with fixture.client.app.state.session_factory() as session:
            versions = set(session.scalars(select(SchemaVersion.version)).all())
        table_names = set(inspect(engine).get_table_names())
        assert "vol18.004" in versions
        assert {
            "codex_run_monitors",
            "codex_result_envelopes",
            "codex_result_artifacts",
            "handoff_reviews",
            "handoff_instruction_drafts",
        } <= table_names
        with engine.connect() as connection:
            triggers = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='trigger' ORDER BY name"
                    )
                )
            }
        assert {
            "trg_codex_result_envelopes_no_update",
            "trg_codex_result_envelopes_no_delete",
            "trg_codex_result_artifacts_no_update",
            "trg_codex_result_artifacts_no_delete",
            "trg_handoff_reviews_no_update",
            "trg_handoff_reviews_no_delete",
            "trg_codex_run_monitors_no_delete",
            "trg_handoff_instruction_drafts_no_delete",
        } <= triggers


def test_monitor_state_contract_is_complete_and_recovery_is_bounded() -> None:
    assert MONITOR_STATES == {
        "QUEUED",
        "STARTING",
        "RUNNING",
        "VERIFYING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "PROCESS_LOST",
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    }
    assert RECOVERY_STATES == {
        "NONE",
        "MONITORING_RESUMED",
        "RESULT_RECOVERED",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
        "INTEGRITY_BLOCKED",
    }
    assert RESULT_INTAKE_POLICY == "twos.result_intake.vol18.004"


def test_sealed_verification_receipt_can_bind_before_manager_without_state_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fast terminal receipt may win the watcher/manager process-bind race."""

    process_id = 74123
    process_identity = "7" * 64
    ticket_digest = "8" * 64
    terminal_receipt: dict[str, object] = {
        "child_process_id": process_id,
        "child_process_start_identity": process_identity,
        "terminal_state": "COMPLETED",
        "process_exit_code": 0,
    }
    receipt_digest = canonical_sha256(terminal_receipt)
    with result_intake_fixture(tmp_path, run_status="completed") as fixture:
        factory = fixture.client.app.state.session_factory
        worktree = tmp_path / "fast-verification-worktree"
        worktree.mkdir()
        with factory() as session:
            run = _run(session, fixture)
            run.status = "verifying"
            run.verification_process_spawned = False
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            monitor.monitor_state = "RESULT_PENDING"
            monitor.recovery_state = "RESULT_RECOVERED"
            monitor.failure_code = "RESULT_SETTLEMENT_PENDING"
            monitor.safe_summary = "The terminal Codex result is still being settled."
            monitor.verification_process_id = None
            monitor.verification_process_start_identity = ""
            attempt = CodexExecutionAttempt(
                attempt_id="attempt-fast-verification-receipt",
                owner_id=fixture.owner_id,
                task_id=run.task_id,
                task_version=run.task_version,
                run_id=run.id,
                pack_id=run.pack_id,
                pack_version=run.pack.version,
                coding_assignment_id=run.execution_assignment_id,
                coding_assignment_version=(
                    run.execution_assignment.assignment_version
                ),
                verification_assignment_id=run.verification_assignment_id,
                verification_assignment_version=(
                    run.verification_assignment.assignment_version
                ),
                routing_snapshot_identity=run.routing_snapshot_hash,
                source_snapshot_identity=run.source_snapshot_digest,
                monitor_id=monitor.id,
                phase="VERIFICATION",
                attempt_number=1,
                attempt_state="SETTLING",
                process_id=process_id,
                process_start_identity=process_identity,
                process_live=False,
                process_exit_known=True,
                process_exit_code=0,
                ticket_digest=ticket_digest,
                receipt_digest=receipt_digest,
                terminal_event_observed=True,
                terminal_event_type="turn.completed",
                terminal_event_identity="9" * 64,
                blocker_code="VERIFICATION_RESULT_VALIDATION_PENDING",
                safe_summary="Verifying final result evidence",
            )
            session.add(attempt)
            session.commit()

        manager = fixture.client.app.state.codex_manager
        fake_handle = SimpleNamespace(ticket_digest=ticket_digest)
        monkeypatch.setattr(
            manager,
            "_validated_bridge_ticket",
            lambda _run_row, *, phase, worktree: (fake_handle, {}),
        )
        monkeypatch.setattr(
            manager,
            "_existing_bridge_handle",
            lambda _run_id, _phase: fake_handle,
        )
        monkeypatch.setattr(
            codex_exec_bridge,
            "load_terminal_receipt",
            lambda _handle: dict(terminal_receipt),
        )
        mismatched_receipt = dict(terminal_receipt)
        mismatched_receipt["terminal_state"] = "FAILED"
        with pytest.raises(
            ResultIntakeError,
            match="does not match this phase binding",
        ):
            manager._bind_bridge_child(
                fixture.run_id,
                phase="verification",
                process_id=process_id,
                process_start_identity=process_identity,
                executable=str(tmp_path / "already-exited-codex"),
                worktree=worktree,
                terminal_receipt=mismatched_receipt,
            )
        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_PENDING"
            assert monitor.verification_process_id is None
            assert monitor.verification_process_start_identity == ""

        manager._bind_bridge_child(
            fixture.run_id,
            phase="verification",
            process_id=process_id,
            process_start_identity=process_identity,
            executable=str(tmp_path / "already-exited-codex"),
            worktree=worktree,
            # Simulate the manager reading live state just before the watcher
            # committed RESULT_PENDING from the newly sealed receipt. The
            # bind path must re-read that receipt rather than regress state.
            terminal_receipt=None,
        )

        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            run = _run(session, fixture)
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_PENDING"
            assert monitor.recovery_state == "RESULT_RECOVERED"
            assert monitor.failure_code == "RESULT_SETTLEMENT_PENDING"
            assert monitor.safe_summary == (
                "The terminal Codex result is still being settled."
            )
            assert monitor.verification_process_id == process_id
            assert (
                monitor.verification_process_start_identity == process_identity
            )
            assert run.verification_process_spawned is True
            assert session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action
                    == "codex_run_monitor_terminal_process_bound"
                )
            ) == 1

        # A fresh manager instance replays the same exact identity as a no-op.
        restarted = CodexExecutionManager(factory, manager.settings)
        monkeypatch.setattr(
            restarted,
            "_validated_bridge_ticket",
            lambda _run_row, *, phase, worktree: (fake_handle, {}),
        )
        restarted._bind_bridge_child(
            fixture.run_id,
            phase="verification",
            process_id=process_id,
            process_start_identity=process_identity,
            executable=str(tmp_path / "already-exited-codex"),
            worktree=worktree,
            terminal_receipt=dict(terminal_receipt),
        )
        with factory() as session:
            assert session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action
                    == "codex_run_monitor_terminal_process_bound"
                )
            ) == 1

        with pytest.raises(
            codex_exec_bridge.CodexExecBridgeError,
            match="identity conflicts with this Run",
        ):
            restarted._bind_bridge_child(
                fixture.run_id,
                phase="verification",
                process_id=process_id + 1,
                process_start_identity="a" * 64,
                executable=str(tmp_path / "already-exited-codex"),
                worktree=worktree,
                terminal_receipt=dict(terminal_receipt),
            )


def test_normal_process_start_running_heartbeat_and_successful_exit(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path, run_status="queued") as fixture:
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            assert monitor.monitor_state == "QUEUED"
            assert monitor.heartbeat_sequence == 0
            started = observe_monitor(
                session,
                monitor,
                state="STARTING",
                process_id=os.getpid(),
                codex_session_identity="fixture-thread-001",
            )
            start_identity = started.process_start_identity
            assert start_identity
            assert started.started_at is not None
            running = observe_monitor(session, monitor, state="RUNNING")
            assert running.heartbeat_sequence == 2
            assert running.last_heartbeat_at is not None
            verifying = observe_monitor(session, monitor, state="VERIFYING")
            completed = observe_monitor(
                session,
                verifying,
                state="COMPLETED",
                exit_code=0,
            )
            assert completed.process_id == os.getpid()
            assert completed.process_start_identity == start_identity
            assert completed.codex_session_identity == "fixture-thread-001"
            assert completed.process_exit_code == 0
            assert completed.terminal_at is not None
            session.commit()


@pytest.mark.parametrize(
    ("run_status", "expected_state"),
    [
        ("completed", "COMPLETED"),
        ("failed", "FAILED"),
        ("blocked", "FAILED"),
        ("cancelled", "CANCELLED"),
        ("timed_out", "TIMED_OUT"),
    ],
)
def test_terminal_run_state_is_not_conflated_with_result_availability(
    tmp_path: Path,
    run_status: str,
    expected_state: str,
) -> None:
    with result_intake_fixture(tmp_path, run_status=run_status) as fixture:
        with fixture.client.app.state.session_factory() as session:
            monitor = ensure_run_monitor(
                session,
                fixture.owner_id,
                _run(session, fixture),
            )
            assert monitor.monitor_state == expected_state
            assert monitor.monitor_state != "RESULT_AVAILABLE"
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 0


def test_pid_reuse_or_process_loss_is_reported_without_duplicate_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.result_intake as result_intake_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            monitor = ensure_run_monitor(
                session,
                fixture.owner_id,
                _run(session, fixture),
                process_id=os.getpid(),
                process_start_identity="a" * 64,
            )
            monitor_id = monitor.id
            session.commit()
        monkeypatch.setattr(
            result_intake_module,
            "process_identity_matches",
            lambda _pid, _identity: False,
        )
        reconciled = reconcile_run_monitors(factory, run_ids=[fixture.run_id])
        assert reconciled == [
            {
                "run_id": fixture.run_id,
                "state": "PROCESS_LOST",
                "blocker": "PID_REUSED_OR_PROCESS_LOST",
            }
        ]
        with factory() as session:
            monitor = session.get(CodexRunMonitor, monitor_id)
            assert monitor is not None
            assert monitor.monitor_state == "PROCESS_LOST"
            assert monitor.recovery_state == "PROCESS_LOST"
            assert monitor.failure_code == "PID_REUSED_OR_PROCESS_LOST"
            assert session.scalar(select(func.count(CodexRun.id))) == 1


@pytest.mark.parametrize(
    ("bridge_evidence", "expected_recovery"),
    [
        (
            {
                "phase": "coding",
                "terminal": False,
                "terminal_state": "",
                "sidecar_alive": True,
                "child_alive": True,
                "child_bound": True,
            },
            "MONITORING_RESUMED",
        ),
        (
            {
                "phase": "coding",
                "terminal": True,
                "terminal_state": "COMPLETED",
                "sidecar_alive": False,
                "child_alive": False,
            },
            "RESULT_RECOVERED",
        ),
    ],
)
def test_sealed_bridge_waiter_or_terminal_receipt_prevents_false_process_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bridge_evidence: dict[str, object],
    expected_recovery: str,
) -> None:
    import twos_runtime.result_intake as result_intake_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = _run(session, fixture)
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            monitor.result_source = "codex_exec_jsonl_spool"
            monitor.protected_result_locator = str(tmp_path / "sealed-spool")
            session.commit()
        monkeypatch.setattr(
            result_intake_module,
            "_validated_bridge_monitor_evidence",
            lambda _monitor, _run: dict(bridge_evidence),
        )

        reconciled = reconcile_run_monitors(factory, run_ids=[fixture.run_id])

        assert reconciled == [{"run_id": fixture.run_id, "state": "RUNNING"}]
        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "RUNNING"
            assert monitor.recovery_state == expected_recovery
            assert monitor.failure_code == ""
            assert session.scalar(select(func.count(CodexRun.id))) == 1
            assert session.scalar(select(func.count(CodexResultEnvelope.id))) == 0


def test_sealed_launch_without_state_is_starting_and_clears_stale_terminal_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module
    import twos_runtime.result_intake as result_intake_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        factory = fixture.client.app.state.session_factory
        fake_handle = object()
        with factory() as session:
            run = _run(session, fixture)
            ticket = _bridge_ticket_for_run(run, phase="coding")
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            monitor.result_source = "codex_exec_jsonl_spool"
            monitor.protected_result_locator = str(tmp_path / "sealed-spool")
            monitor.failure_code = "STALE_PROCESS_LOST"
            monitor.process_exit_code = -1
            monitor.terminal_at = utc_now()
            session.commit()

        monkeypatch.setattr(
            result_intake_module,
            "_bridge_publication_status",
            lambda _root, _run_id, phase: (
                ("ready", fake_handle) if phase == "coding" else ("absent", None)
            ),
        )
        monkeypatch.setattr(bridge_module, "load_ticket", lambda _handle: ticket)
        monkeypatch.setattr(
            bridge_module,
            "load_terminal_receipt",
            lambda _handle: None,
        )
        monkeypatch.setattr(
            bridge_module,
            "load_execution_state",
            lambda _handle: None,
        )
        launch = bridge_module.LaunchInfo(
            process_id=os.getpid(),
            process_start_identity="d" * 64,
            ticket_digest="e" * 64,
            launched_at=utc_now().isoformat(),
        )
        monkeypatch.setattr(
            bridge_module,
            "load_launch_info",
            lambda _handle: launch,
        )
        monkeypatch.setattr(
            bridge_module,
            "process_identity_matches",
            lambda pid, identity: pid == os.getpid() and identity == "d" * 64,
        )

        reconciled = reconcile_run_monitors(factory, run_ids=[fixture.run_id])

        assert reconciled == [{"run_id": fixture.run_id, "state": "STARTING"}]
        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "STARTING"
            assert monitor.recovery_state == "MONITORING_RESUMED"
            assert monitor.failure_code == ""
            assert monitor.process_exit_code is None
            assert monitor.terminal_at is None
            assert session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action
                    == "codex_run_monitor_stale_terminal_cleared",
                    AuditEvent.entity_id == fixture.run_id,
                )
            ) == 1


def test_terminal_receipt_is_re_read_after_state_observation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module
    import twos_runtime.result_intake as result_intake_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        factory = fixture.client.app.state.session_factory
        fake_handle = object()
        with factory() as session:
            run = _run(session, fixture)
            ticket = _bridge_ticket_for_run(run, phase="coding")
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            monitor.result_source = "codex_exec_jsonl_spool"
            monitor.protected_result_locator = str(tmp_path / "sealed-spool")
            session.commit()
        monkeypatch.setattr(
            result_intake_module,
            "_bridge_publication_status",
            lambda _root, _run_id, phase: (
                ("ready", fake_handle) if phase == "coding" else ("absent", None)
            ),
        )
        monkeypatch.setattr(bridge_module, "load_ticket", lambda _handle: ticket)
        receipt_reads = iter(
            [
                None,
                {
                    "terminal_state": "COMPLETED",
                    "process_exit_code": 0,
                },
            ]
        )
        monkeypatch.setattr(
            bridge_module,
            "load_terminal_receipt",
            lambda _handle: next(receipt_reads),
        )

        def fail_state_read(_handle):
            raise bridge_module.CodexExecBridgeError(
                "STATE_OBSERVATION_RACE",
                "The state changed during observation.",
            )

        monkeypatch.setattr(bridge_module, "load_execution_state", fail_state_read)

        reconciled = reconcile_run_monitors(factory, run_ids=[fixture.run_id])

        assert reconciled == [{"run_id": fixture.run_id, "state": "RUNNING"}]
        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "RUNNING"
            assert monitor.recovery_state == "RESULT_RECOVERED"
            assert monitor.failure_code == ""


def test_execution_manager_re_reads_terminal_receipt_after_state_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        manager = fixture.client.app.state.codex_manager
        fake_handle = object()
        monkeypatch.setattr(
            manager,
            "_bridge_preparation_status",
            lambda _run_id, phase: "ready" if phase == "coding" else "absent",
        )
        monkeypatch.setattr(
            manager,
            "_validated_bridge_ticket",
            lambda _run, *, phase, worktree: (fake_handle, {"phase": phase}),
        )
        receipt = {
            "terminal_state": "COMPLETED",
            "process_exit_code": 0,
        }
        receipt_reads = iter([None, receipt])
        monkeypatch.setattr(
            bridge_module,
            "load_terminal_receipt",
            lambda _handle: next(receipt_reads),
        )

        def fail_state_read(_handle):
            raise bridge_module.CodexExecBridgeError(
                "STATE_OBSERVATION_RACE",
                "The state changed during observation.",
            )

        monkeypatch.setattr(bridge_module, "load_execution_state", fail_state_read)
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            run.verification_process_spawned = False
            session.flush()
            observation = manager._bridge_recovery_observation(
                run,
                tmp_path,
            )

        assert observation["status"] == "terminal"
        assert observation["phase"] == "coding"
        assert observation["receipt"] == receipt


def test_execution_manager_treats_exact_launch_without_state_as_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        manager = fixture.client.app.state.codex_manager
        fake_handle = object()
        monkeypatch.setattr(
            manager,
            "_bridge_preparation_status",
            lambda _run_id, phase: "ready" if phase == "coding" else "absent",
        )
        monkeypatch.setattr(
            manager,
            "_validated_bridge_ticket",
            lambda _run, *, phase, worktree: (fake_handle, {"phase": phase}),
        )
        monkeypatch.setattr(
            bridge_module,
            "load_terminal_receipt",
            lambda _handle: None,
        )
        monkeypatch.setattr(
            bridge_module,
            "load_execution_state",
            lambda _handle: None,
        )
        launch = bridge_module.LaunchInfo(
            process_id=os.getpid(),
            process_start_identity="f" * 64,
            ticket_digest="e" * 64,
            launched_at=utc_now().isoformat(),
        )
        monkeypatch.setattr(
            bridge_module,
            "load_launch_info",
            lambda _handle: launch,
        )
        monkeypatch.setattr(
            bridge_module,
            "process_identity_matches",
            lambda pid, identity: pid == os.getpid() and identity == "f" * 64,
        )
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            run.verification_process_spawned = False
            session.flush()
            observation = manager._bridge_recovery_observation(run, tmp_path)

        assert observation["status"] == "starting"
        assert observation["phase"] == "coding"
        assert observation["launch"] == launch


def test_unsealed_verification_ticket_is_bounded_preparation_not_selected_phase(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path, run_status="verifying") as fixture:
        factory = fixture.client.app.state.session_factory
        spool_root = tmp_path / "sealed-spool"
        verification_directory = spool_root / f"run-{fixture.run_id}-verification"
        verification_directory.mkdir(parents=True)
        (verification_directory / "ticket.json").write_text(
            '{"publication":"incomplete"}',
            encoding="utf-8",
        )
        with factory() as session:
            run = _run(session, fixture)
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            monitor.result_source = "codex_exec_jsonl_spool"
            monitor.protected_result_locator = str(spool_root)
            session.commit()

        reconciled = reconcile_run_monitors(factory, run_ids=[fixture.run_id])

        assert reconciled == [{"run_id": fixture.run_id, "state": "VERIFYING"}]
        with factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "VERIFYING"
            assert monitor.recovery_state == "NONE"
            assert monitor.failure_code == ""


@pytest.mark.parametrize("bridge_status", ["starting", "active", "terminal"])
def test_execution_manager_recovery_uses_recovery_waiter_and_never_normal_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bridge_status: str,
) -> None:
    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        manager = fixture.client.app.state.codex_manager
        factory = fixture.client.app.state.session_factory
        recovered: list[tuple[int, bool]] = []
        monkeypatch.setattr(
            manager,
            "_recovery_worktree",
            lambda _run: tmp_path,
        )
        monkeypatch.setattr(
            manager,
            "_bridge_preparation_status",
            lambda _run_id, _phase: "ready",
        )
        monkeypatch.setattr(
            manager,
            "_bridge_recovery_observation",
            lambda _run, _worktree: {
                "status": bridge_status,
                "phase": "coding",
            },
        )
        monkeypatch.setattr(
            manager,
            "_start_worker",
            lambda run_id, *, recover_bridge: (
                recovered.append((run_id, recover_bridge)) or True
            ),
        )

        manager.recover_interrupted_runs()

        assert recovered == [(fixture.run_id, True)]
        with factory() as session:
            run = _run(session, fixture)
            assert run.status == "running"
            assert session.scalar(select(func.count(CodexRun.id))) == 1
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.recovery_state == (
                "MONITORING_RESUMED"
                if bridge_status in {"starting", "active"}
                else "RESULT_RECOVERED"
            )
            # A recovered terminal receipt is settlement evidence, never a
            # reason to re-project the stale persisted Run as RUNNING.
            assert monitor.monitor_state == (
                "RESULT_PENDING" if bridge_status == "terminal" else "RUNNING"
            )


@pytest.mark.parametrize("terminal_before_restart", [False, True])
def test_real_detached_bridge_restart_recovers_without_duplicate_coding(
    tmp_path: Path,
    terminal_before_restart: bool,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = _make_restart_recovery_codex(tmp_path)
    database = tmp_path / "restart-recovery.sqlite3"
    spool_root = tmp_path / "codex-spool"

    first = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=15,
    )
    with first:
        headers = init_and_login(first)
        configure_test_model_registry(first)
        task_id = create_development_task(
            first,
            headers,
            marker="DETACHED_BRIDGE_RESTART_RECOVERY",
        )
        pack = generate_pack(first, headers, task_id)
        approve_pack(first, headers, task_id, pack["id"])
        started = start_codex_run(first, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        coding_handle = _wait_for_bridge_handle(spool_root, run_id, "coding")
        deadline = time.monotonic() + 5
        live_state: dict[str, object] | None = None
        while time.monotonic() < deadline:
            live_state = load_execution_state(coding_handle)
            if (
                isinstance(live_state, dict)
                and live_state.get("state") == "RUNNING"
                and type(live_state.get("child_process_id")) is int
                and live_state.get("child_process_id", 0) > 0
            ):
                break
            time.sleep(0.02)
        assert isinstance(live_state, dict)
        assert live_state["state"] == "RUNNING"
        assert bridge_process_identity_matches(
            int(live_state["sidecar_process_id"]),
            str(live_state["sidecar_process_start_identity"]),
        )
        assert bridge_process_identity_matches(
            int(live_state["child_process_id"]),
            str(live_state["child_process_start_identity"]),
        )

    # TestClient shutdown stops only its daemon waiter.  The exact detached
    # sidecar/child remains authoritative for the replacement runtime.
    if terminal_before_restart:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if load_terminal_receipt(coding_handle) is not None:
                break
            time.sleep(0.02)
        receipt = load_terminal_receipt(coding_handle)
        assert receipt is not None
        assert receipt["terminal_state"] == "COMPLETED"
    else:
        state_after_shutdown = load_execution_state(coding_handle)
        assert isinstance(state_after_shutdown, dict)
        assert load_terminal_receipt(coding_handle) is None
        assert bridge_process_identity_matches(
            int(state_after_shutdown["sidecar_process_id"]),
            str(state_after_shutdown["sidecar_process_start_identity"]),
        )

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=15,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(
            restarted,
            headers,
            run_id,
            {"completed"},
            timeout=15,
        )
        envelope = _wait_for_envelope(
            restarted.app.state.session_factory,
            run_id,
            timeout=5,
        )
        with restarted.app.state.session_factory() as session:
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id)).where(
                    CodexResultEnvelope.run_id == run_id
                )
            ) == 1
            assert session.scalar(
                select(func.count(AIModelInvocationEvidence.id)).where(
                    AIModelInvocationEvidence.codex_run_id == run_id
                )
            ) == 2

    assert terminal["status"] == "completed"
    assert terminal["result"]["verification_verdict"]["status"] == "passed"
    assert envelope.integrity_state == "VERIFIED"
    assert fake_codex.with_name(fake_codex.name + ".coding-count").read_text() == "1"
    assert fake_codex.with_name(fake_codex.name + ".verification-count").read_text() == "1"


def test_post_launch_adapter_error_recovers_terminal_receipt_without_fake_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.codex_exec_bridge as bridge_module

    source_repo = make_source_repo(tmp_path)
    fake_codex = _make_restart_recovery_codex(tmp_path, coding_delay=0.1)
    real_replay = bridge_module.replay_stdout_to_collector
    failed_once = False

    def fail_once_after_terminal(handle, collector):
        nonlocal failed_once
        if not failed_once and handle.phase_key.endswith("-coding"):
            failed_once = True
            raise bridge_module.CodexExecBridgeError(
                "POST_LAUNCH_REPLAY_RACE",
                "A controlled post-launch read failed once.",
            )
        return real_replay(handle, collector)

    monkeypatch.setattr(
        bridge_module,
        "replay_stdout_to_collector",
        fail_once_after_terminal,
    )
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "post-launch-recovery.sqlite3",
        timeout=15,
    ) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(
            client,
            headers,
            marker="POST_LAUNCH_RECOVERY_NO_FAKE_EXIT",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        terminal = wait_for_run(client, headers, run_id, {"completed"}, timeout=15)
        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            assert run.exit_code == 0
            assert run.stdout
            assert session.scalar(
                select(func.count(AIModelInvocationEvidence.id)).where(
                    AIModelInvocationEvidence.codex_run_id == run_id
                )
            ) == 2

    assert failed_once is True
    assert terminal["status"] == "completed"
    assert fake_codex.with_name(fake_codex.name + ".coding-count").read_text() == "1"
    assert fake_codex.with_name(fake_codex.name + ".verification-count").read_text() == "1"


def test_recovered_invalid_handoff_persists_real_exit_output_and_evidence(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = _make_restart_recovery_codex(
        tmp_path,
        coding_delay=0.5,
        coding_final_message_mismatch=True,
    )
    database = tmp_path / "integrity-recovery.sqlite3"
    spool_root = tmp_path / "codex-spool"

    first = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=15,
    )
    with first:
        headers = init_and_login(first)
        configure_test_model_registry(first)
        task_id = create_development_task(
            first,
            headers,
            marker="RECOVERED_INTEGRITY_BLOCKED_EVIDENCE",
        )
        pack = generate_pack(first, headers, task_id)
        approve_pack(first, headers, task_id, pack["id"])
        started = start_codex_run(first, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        coding_handle = _wait_for_bridge_handle(spool_root, run_id, "coding")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = load_execution_state(coding_handle)
            if isinstance(state, dict) and state.get("state") == "RUNNING":
                break
            time.sleep(0.02)
        assert isinstance(state, dict)
        assert state["state"] == "RUNNING"

    deadline = time.monotonic() + 8
    receipt = None
    while time.monotonic() < deadline:
        receipt = load_terminal_receipt(coding_handle)
        if receipt is not None:
            break
        time.sleep(0.02)
    assert receipt is not None
    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["process_exit_code"] == 0
    assert receipt["outcome_facts"]["integrity_blocked"] is False

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=15,
    ) as restarted:
        headers = init_and_login(restarted)
        terminal = wait_for_run(restarted, headers, run_id, {"failed"}, timeout=15)
        _wait_for_envelope(restarted.app.state.session_factory, run_id)
        with restarted.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            assert run.status == "failed"
            assert run.exit_code == 0
            assert "thread.started" in run.stdout
            assert run.verification_process_spawned is False
            assert run.verification_status == "not_started"
            assert session.scalar(
                select(func.count(AIModelInvocationEvidence.id)).where(
                    AIModelInvocationEvidence.codex_run_id == run_id
                )
            ) == 1
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run_id)
            )
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_AVAILABLE"
            assert monitor.recovery_state == "RESULT_RECOVERED"
            assert monitor.process_exit_code == 0
        result_response = restarted.get(
            f"/api/codex-runs/{run_id}/result-envelope",
            headers=headers,
        )
        assert result_response.status_code == 200, result_response.text
        envelope = result_response.json()["result"]
        assert envelope["integrity_state"] == "VERIFIED"
        assert envelope["structured_handoff_status"] == "unavailable"
        assert envelope["completion_classification"] == "result_incomplete"

    assert terminal["status"] == "failed"
    assert fake_codex.with_name(fake_codex.name + ".coding-count").read_text() == "1"
    assert not fake_codex.with_name(
        fake_codex.name + ".verification-count"
    ).exists()


def test_valid_transport_with_invalid_coding_handoff_never_starts_verification(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = _make_restart_recovery_codex(
        tmp_path,
        coding_delay=0.05,
        coding_contract_invalid=True,
    )

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "invalid-coding-contract.sqlite3",
        timeout=15,
    ) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(
            client,
            headers,
            marker="INVALID_CODING_HANDOFF_CONTRACT",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        terminal = wait_for_run(client, headers, run_id, {"failed"}, timeout=15)
        # Run finalization commits before taking the per-Run lifecycle lock so
        # it cannot deadlock the independent monitor's SQLite writer.  Bound
        # the intentionally tiny projection window and prove convergence.
        projection_deadline = time.monotonic() + 5
        while time.monotonic() < projection_deadline:
            with client.app.state.session_factory() as projection_session:
                projected_attempt = projection_session.scalar(
                    select(CodexExecutionAttempt).where(
                        CodexExecutionAttempt.run_id == run_id,
                        CodexExecutionAttempt.phase == "CODING",
                    )
                )
                if (
                    projected_attempt is not None
                    and projected_attempt.attempt_state == "COMPLETED"
                ):
                    break
            time.sleep(0.02)
        with client.app.state.session_factory() as session:
            run = session.get(CodexRun, run_id)
            assert run is not None
            assert run.status == "failed"
            assert run.exit_code == 0
            assert run.verification_process_spawned is False
            assert run.verification_status == "not_started"
            attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == run_id,
                    CodexExecutionAttempt.phase == "CODING",
                )
            )
            assert attempt is not None
            assert attempt.attempt_state == "COMPLETED"
            assert (
                attempt.blocker_code
                == "STRUCTURED_CODING_HANDOFF_UNAVAILABLE"
            )
            assert attempt.verification_eligible is False
            snapshot = session.scalar(
                select(CodexLifecycleSnapshot).where(
                    CodexLifecycleSnapshot.run_id == run_id
                )
            )
            assert snapshot is not None
            assert snapshot.lifecycle_state == "RESULT_AVAILABLE"
            assert snapshot.result_integrity_state == "VERIFIED"
            assert session.scalar(
                select(func.count(AIModelInvocationEvidence.id)).where(
                    AIModelInvocationEvidence.codex_run_id == run_id
                )
            ) == 1

        result_response = client.get(
            f"/api/codex-runs/{run_id}/result-envelope",
            headers=headers,
        )
        assert result_response.status_code == 200, result_response.text
        envelope = result_response.json()["result"]
        assert envelope["integrity_state"] == "VERIFIED"
        assert envelope["structured_handoff_status"] == "unavailable"
        assert envelope["completion_classification"] == "result_incomplete"

    assert terminal["status"] == "failed"
    assert fake_codex.with_name(fake_codex.name + ".coding-count").read_text() == "1"
    assert not fake_codex.with_name(
        fake_codex.name + ".verification-count"
    ).exists()


def test_browser_session_is_not_the_monitor_and_terminal_result_is_automatic(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            ensure_run_monitor(session, fixture.owner_id, _run(session, fixture))
            session.commit()
        fixture.client.cookies.clear()
        watcher = ResultIntakeMonitor(factory, poll_seconds=0.25)
        watcher.start()
        try:
            envelope = _wait_for_envelope(factory, fixture.run_id)
        finally:
            watcher.shutdown()
        assert envelope.integrity_state == "VERIFIED"
        assert envelope.run_id == fixture.run_id
        assert fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/result-envelope"
        ).status_code == 401
        init_and_login(fixture.client)
        reopened = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/result-envelope"
        )
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["result"]["id"] == envelope.envelope_id
        with factory() as session:
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 1


def test_fake_local_cli_run_is_automatically_monitored_and_ingested(
    tmp_path: Path,
) -> None:
    """Exercise the real adapter boundary with a local fake executable only."""
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(
            client,
            headers,
            marker="FAKE_SUCCESS Phase 18.5A automatic intake",
        )
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        terminal = wait_for_run(client, headers, run_id, {"completed"}, timeout=10)
        assert terminal["verification_target"]["status"] == "completed"
        envelope = _wait_for_envelope(
            client.app.state.session_factory,
            run_id,
            timeout=5,
        )
        assert envelope.integrity_state == "VERIFIED"
        assert envelope.verification_verdict == "PASS"
        with client.app.state.session_factory() as session:
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run_id)
            )
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_AVAILABLE"
            assert monitor.heartbeat_sequence > 0
            assert monitor.process_id is not None
            assert monitor.process_start_identity
            assert monitor.verification_process_id is not None
            assert monitor.verification_process_start_identity
            assert monitor.codex_session_identity
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id)).where(
                    CodexResultEnvelope.run_id == run_id
                )
            ) == 1
            assert session.scalar(
                select(func.count(DeliveryCandidate.id)).where(
                    DeliveryCandidate.run_id == run_id
                )
            ) == 0
            assert session.scalar(
                select(func.count(HandoffInstructionDraft.id)).where(
                    HandoffInstructionDraft.run_id == run_id
                )
            ) == 0


def test_valid_result_intake_persists_manifest_evidence_and_is_idempotent(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = _run(session, fixture)
            payload = valid_result_payload(session, fixture)
            first = ingest_result_payload(
                session,
                fixture.owner_id,
                run,
                payload,
                result_source="controlled_test",
                require_explicit_identity=True,
            )
            first_digest = first.result_digest
            first_id = first.id
            session.commit()
        with factory() as session:
            second = ingest_result_payload(
                session,
                fixture.owner_id,
                _run(session, fixture),
                payload,
                result_source="controlled_test",
                require_explicit_identity=True,
            )
            assert second.id == first_id
            assert second.result_digest == first_digest
            session.commit()
        with factory() as session:
            envelope = session.get(CodexResultEnvelope, first_id)
            assert envelope is not None
            public = result_envelope_out(envelope, advanced=True)
            assert public["terminal_status"] == "completed"
            assert public["verification_result"]["verdict"] == "PASS"
            assert public["result_integrity"] == "VERIFIED"
            assert public["tests"][0]["status"] == "passed"
            assert public["owner_action"] == "Review Handoff"
            assert len(public["advanced"]["result_digest"]) == 64
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 1
            artifacts = list(
                session.scalars(
                    select(CodexResultArtifact).order_by(
                        CodexResultArtifact.ordinal
                    )
                ).all()
            )
            assert {item.operation for item in artifacts} == {
                "CREATE",
                "MODIFY",
                "DELETE",
            }
            assert all(item.repository_path and item.evidence_identity for item in artifacts)
            binary = next(item for item in artifacts if item.repository_path == "asset.bin")
            assert binary.content_kind in {"binary", "binary_or_oversized"}
            assert binary.before_hash and binary.after_hash
            serialized = json.dumps(public, sort_keys=True)
            assert "\\u0000" not in serialized


def test_imported_model_claim_cannot_mint_authoritative_execution_identity(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = _run(session, fixture)
            for evidence in session.scalars(
                select(AIModelInvocationEvidence).where(
                    AIModelInvocationEvidence.codex_run_id == run.id
                )
            ).all():
                process = json.loads(evidence.process_evidence)
                process["actual_model_identity_verified"] = False
                process["model_identity_observed"] = False
                process.pop("model_identity_source", None)
                evidence.actual_invoked_model_identifier = ""
                evidence.process_evidence = json.dumps(
                    process,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            payload = valid_result_payload(session, fixture)
            payload["coding_invocation"] = {
                "actual_model_identity_verified": True,
                "model_identity_observed": True,
                "model_identity_source": "explicit_actual_model_metadata",
                "actual_resolved_model_identifier": "client-forged-model",
            }
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                run.id,
                payload,
            )
            session.commit()
            public = result_envelope_out(envelope)
            monitor = session.scalar(
                select(CodexRunMonitor).where(CodexRunMonitor.run_id == run.id)
            )
            assert envelope.actual_model_identifier == ""
            assert public["actual_model"] is None
            assert public["actual_model_verified"] is False
            assert public["effective_model"] is None
            assert public["effective_model_available"] is False
            assert public["effective_model_display"] == (
                "Not exposed by the current Codex CLI protocol."
            )
            assert public["requested_model_accepted"] is True
            assert public["execution_successful"] is True
            assert public["verification_result"]["verdict"] == "PASS"
            assert monitor is not None
            assert monitor_out(monitor, envelope=envelope)["actual_model"] is None


def test_legacy_envelope_and_stale_monitor_model_claims_are_suppressed() -> None:
    envelope = CodexResultEnvelope(
        envelope_id="legacy-model-envelope",
        owner_id=1,
        monitor_id=1,
        run_id=1,
        task_id=1,
        task_version=1,
        pack_id=1,
        pack_version=1,
        coding_assignment_id=1,
        coding_assignment_version=1,
        verification_assignment_id=2,
        verification_assignment_version=1,
        routing_snapshot_identity="a" * 64,
        source_snapshot_identity="b" * 64,
        requested_model_identifier="requested-model",
        actual_model_identifier="legacy-unproven-model",
        terminal_status="completed",
        process_exit_code=0,
        final_response="legacy",
        structured_handoff_json="{}",
        tests_summary_json="[]",
        changed_file_manifest_json="[]",
        diff_identity="c" * 64,
        coding_evidence_json='{"outcome":"succeeded","actual_model":"legacy-unproven-model"}',
        verification_evidence_json='{"outcome":"succeeded"}',
        verification_verdict="PASS",
        warnings_json="[]",
        limitations_json="[]",
        boundary_statements_json="{}",
        result_source="legacy",
        result_source_identity="d" * 64,
        process_evidence_identity="e" * 64,
        result_digest="f" * 64,
        integrity_state="VERIFIED",
        integrity_findings_json="[]",
    )
    monitor = CodexRunMonitor(
        monitor_id="legacy-monitor",
        owner_id=1,
        task_id=1,
        task_version=1,
        pack_id=1,
        pack_version=1,
        coding_assignment_version=1,
        verification_assignment_version=1,
        routing_snapshot_identity="a" * 64,
        source_snapshot_identity="b" * 64,
        run_id=1,
        requested_model_identifier="requested-model",
        actual_model_identifier="legacy-unproven-model",
        executable_fingerprint="1" * 64,
        isolated_worktree_identity="2" * 64,
        execution_location_identity="3" * 64,
        monitor_digest="4" * 64,
        monitor_state="RESULT_AVAILABLE",
    )
    public = result_envelope_out(envelope)
    assert public["actual_model"] is None
    assert public["actual_model_verified"] is False
    assert public["execution_successful"] is False
    assert public["handoff_reconciliation"] == "BLOCKED"
    assert monitor_out(monitor)["actual_model"] is None
    assert monitor_out(monitor, envelope=envelope)["actual_model"] is None


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("not-json", "RESULT_MALFORMED"),
        (b"\xff\xfe", "RESULT_MALFORMED"),
        ({}, "RESULT_INCOMPLETE"),
    ],
)
def test_malformed_and_empty_results_are_integrity_blocked(
    tmp_path: Path,
    payload,
    expected_code: str,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            with pytest.raises(ResultIntakeError) as error:
                ingest_result_payload(
                    session,
                    fixture.owner_id,
                    _run(session, fixture),
                    payload,
                    require_explicit_identity=True,
                )
            assert error.value.code == expected_code
            monitor = session.scalar(
                select(CodexRunMonitor).where(
                    CodexRunMonitor.run_id == fixture.run_id
                )
            )
            assert monitor is not None
            assert monitor.monitor_state == "RESULT_INTEGRITY_BLOCKED"
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 0


def test_identity_only_result_is_rejected_as_incomplete(tmp_path: Path) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            complete = valid_result_payload(session, fixture)
            identity_only = {"identity": complete["identity"]}
            with pytest.raises(ResultIntakeError) as error:
                import_codex_result(
                    session,
                    fixture.owner_id,
                    fixture.run_id,
                    identity_only,
                )
            assert error.value.code == "RESULT_INCOMPLETE"
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 0


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "task_version",
        "pack_version",
        "coding_assignment_version",
        "verification_assignment_version",
    ],
)
def test_mismatched_result_identity_is_never_attached(
    tmp_path: Path,
    field: str,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            payload = valid_result_payload(session, fixture)
            identity = dict(payload["identity"])
            identity[field] = int(identity[field]) + 1000
            payload["identity"] = identity
            with pytest.raises(ResultIntakeError) as error:
                import_codex_result(
                    session,
                    fixture.owner_id,
                    fixture.run_id,
                    payload,
                )
            assert error.value.code == "RESULT_IDENTITY_MISMATCH"
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 0


def test_changed_file_paths_reject_traversal_and_absolute_locations(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        for unsafe_path in ("../outside.txt", "/private/tmp/outside.txt"):
            with factory() as session:
                payload = valid_result_payload(session, fixture)
                changed = list(payload["changed_file_evidence"])
                changed[0] = {**changed[0], "path": unsafe_path}
                payload["changed_file_evidence"] = changed
                with pytest.raises(ResultIntakeError) as error:
                    import_codex_result(
                        session,
                        fixture.owner_id,
                        fixture.run_id,
                        payload,
                    )
                assert error.value.code in {
                    "RESULT_PATH_INVALID",
                    "RESULT_PATH_UNSAFE",
                }
                session.rollback()
        with factory() as session:
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 0


def test_stale_result_cannot_replace_immutable_envelope_and_duplicate_reads_are_safe(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            payload = valid_result_payload(session, fixture)
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                payload,
            )
            digest = envelope.result_digest
            session.commit()
        reconcile_run_monitors(factory, run_ids=[fixture.run_id])
        reconcile_run_monitors(factory, run_ids=[fixture.run_id])
        stale = json.loads(json.dumps(payload))
        stale["final_response"] = "A conflicting stale final response."
        with factory() as session:
            with pytest.raises(ResultIntakeError) as error:
                import_codex_result(
                    session,
                    fixture.owner_id,
                    fixture.run_id,
                    stale,
                )
            assert error.value.code == "RESULT_IMMUTABILITY_CONFLICT"
            persisted = session.scalar(select(CodexResultEnvelope))
            assert persisted is not None
            assert persisted.result_digest == digest
            assert session.scalar(
                select(func.count(CodexResultEnvelope.id))
            ) == 1


def test_prior_verification_coupled_result_digest_replays_without_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with result_intake_fixture(
        tmp_path,
        run_status="completed",
        verification_verdict="failed",
    ) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            payload = valid_result_payload(session, fixture)
            payload["structured_handoff"] = {
                "schema": "twos.coding_handoff.v1",
                "status": "completed",
                "summary": "Coding completed before independent Verification failed.",
            }
            payload["workspace_evidence"] = {
                "schema": "twos.codex_workspace_evidence.v1",
                "status": "captured",
                "boundary_violations": [],
            }
            run = _run(session, fixture)
            monitor = ensure_run_monitor(session, fixture.owner_id, run)
            material = result_intake_module._result_material(
                session,
                run,
                monitor,
                payload,
            )
            assert material["completion_classification"].startswith("succeeded")
            assert material["prior_policy_result_digest"] != material["result_digest"]
            real_result_material = result_intake_module._result_material

            def prior_policy_material(*args, **kwargs):
                prior = real_result_material(*args, **kwargs)
                prior["result_digest"] = prior["prior_policy_result_digest"]
                prior["completion_classification"] = "failed"
                return prior

            with monkeypatch.context() as context:
                context.setattr(
                    result_intake_module,
                    "_result_material",
                    prior_policy_material,
                )
                envelope = import_codex_result(
                    session,
                    fixture.owner_id,
                    fixture.run_id,
                    payload,
                )
            session.commit()

        with factory() as session:
            replayed = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                payload,
            )
            assert replayed.result_digest == material["prior_policy_result_digest"]
            assert replayed.completion_classification == "failed"


def test_result_material_rejects_conflicting_persisted_and_structured_exit_codes(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path, run_status="failed") as fixture:
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            run.exit_code = 9
            payload = valid_result_payload(session, fixture)
            payload["coding_process"] = {
                "status": "completed",
                "exit_code": 0,
            }
            monitor = ensure_run_monitor(session, fixture.owner_id, run)

            material = result_intake_module._result_material(
                session,
                run,
                monitor,
                payload,
            )

            assert material["completion_classification"] == "failed"


def test_oversized_output_is_rejected_and_secrets_and_absolute_paths_are_redacted(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            oversized = valid_result_payload(session, fixture)
            oversized["final_response"] = "x" * (MAX_RESULT_BYTES + 1)
            with pytest.raises(ResultIntakeError) as error:
                import_codex_result(
                    session,
                    fixture.owner_id,
                    fixture.run_id,
                    oversized,
                )
            assert error.value.code == "RESULT_TOO_LARGE"
            session.rollback()
        with factory() as session:
            payload = valid_result_payload(session, fixture)
            payload["final_response"] = (
                f"Completed at {ABSOLUTE_PATH_SENTINEL}; "
                f"Bearer {SECRET_SENTINEL}; "
                + "; ".join(SECRET_SHAPED_SENTINELS)
            )
            payload["warnings"] = [
                {
                    "api_token": SECRET_SENTINEL,
                    "diagnostic": (
                        ABSOLUTE_PATH_SENTINEL
                        + " "
                        + " ".join(SECRET_SHAPED_SENTINELS)
                    ),
                }
            ]
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                payload,
            )
            serialized = json.dumps(
                result_envelope_out(envelope, advanced=True),
                sort_keys=True,
            )
            assert SECRET_SENTINEL not in serialized
            assert ABSOLUTE_PATH_SENTINEL not in serialized
            assert all(secret not in serialized for secret in SECRET_SHAPED_SENTINELS)
            assert "credential withheld" in serialized
            assert "absolute path withheld" in serialized


def test_result_file_intake_rejects_symlink_escape_and_accepts_bounded_json(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path / "fixture") as fixture:
        result_root = tmp_path / "result-root"
        result_root.mkdir()
        outside = tmp_path / "outside-result.json"
        with fixture.client.app.state.session_factory() as session:
            payload = valid_result_payload(session, fixture)
        outside.write_text(json.dumps(payload))
        symlink = result_root / "result.json"
        symlink.symlink_to(outside)
        with fixture.client.app.state.session_factory() as session:
            with pytest.raises(ResultIntakeError) as error:
                ingest_result_file(
                    session,
                    fixture.owner_id,
                    _run(session, fixture),
                    symlink,
                    expected_root=result_root,
                )
            assert error.value.code == "RESULT_FILE_UNSAFE"
            session.rollback()
        symlink.unlink()
        safe = result_root / "result.json"
        safe.write_text(json.dumps(payload))
        with fixture.client.app.state.session_factory() as session:
            envelope = ingest_result_file(
                session,
                fixture.owner_id,
                _run(session, fixture),
                safe,
                expected_root=result_root,
            )
            assert envelope.integrity_state == "VERIFIED"
            assert envelope.result_source == "durable_result_file"


def test_restart_recovery_preserves_one_result_and_creates_no_candidate_or_draft(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path / "fixture") as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                valid_result_payload(session, fixture),
            )
            envelope_id = envelope.envelope_id
            session.commit()
        restarted = make_client(
            tmp_path / "restart",
            fixture.source_repo,
            tmp_path / "codex-must-not-be-invoked",
            database_path=fixture.database_path,
        )
        restarted.__enter__()
        try:
            init_and_login(restarted)
            response = restarted.get(
                f"/api/codex-runs/{fixture.run_id}/result-envelope"
            )
            assert response.status_code == 200, response.text
            assert response.json()["result"]["id"] == envelope_id
            with restarted.app.state.session_factory() as session:
                assert session.scalar(
                    select(func.count(CodexResultEnvelope.id))
                ) == 1
                assert session.scalar(
                    select(func.count(DeliveryCandidate.id))
                ) == 0
                assert session.scalar(
                    select(func.count(HandoffInstructionDraft.id))
                ) == 0
        finally:
            restarted.__exit__(None, None, None)


def test_review_handoff_pass_and_exactly_one_nonexecuting_draft(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                valid_result_payload(session, fixture),
            )
            run_count = session.scalar(select(func.count(CodexRun.id)))
            review = get_or_create_handoff_review(
                session,
                fixture.owner_id,
                fixture.run_id,
            )
            assert handoff_review_out(review)["recommended_reconciliation"] == "PASS"
            first = get_or_create_instruction_draft(
                session,
                fixture.owner_id,
                review,
            )
            second = get_or_create_instruction_draft(
                session,
                fixture.owner_id,
                review.id,
            )
            assert second.id == first.id
            public = instruction_draft_out(first)
            assert public["label"] == "Draft — Owner approval required"
            assert public["approval_state"] == "OWNER_APPROVAL_REQUIRED"
            assert public["execution_authorized"] is False
            assert len(public["completion_gate"]) == 4
            assert len(public["required_handoff"]) == 4
            assert public["instruction_id"].endswith("-R1")
            assert "EXECUTION: NOT AUTHORIZED BY THIS DRAFT" in public["instruction_text"]
            approved = approve_instruction_draft(
                session,
                fixture.owner_id,
                first.id,
            )
            assert approved.approval_state == "APPROVED"
            assert instruction_draft_out(approved)["execution_authorized"] is False
            assert session.scalar(
                select(func.count(HandoffInstructionDraft.id))
            ) == 1
            assert session.scalar(select(func.count(CodexRun.id))) == run_count
            assert session.scalar(
                select(func.count(DeliveryCandidate.id))
            ) == 0


def test_review_handoff_truthfully_recommends_blocked_with_warnings_and_limitations(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(
        tmp_path,
        run_status="failed",
        verification_verdict="failed",
    ) as fixture:
        with fixture.client.app.state.session_factory() as session:
            payload = valid_result_payload(session, fixture)
            payload["task_acceptance"] = {
                "status": "failed",
                "reason": "Independent Verification failed.",
            }
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                payload,
            )
            assert envelope.verification_verdict == "FAIL"
            review = get_or_create_handoff_review(
                session,
                fixture.owner_id,
                fixture.run_id,
            )
            public = handoff_review_out(review)
            assert public["recommended_reconciliation"] == "BLOCKED"
            assert public["warnings"] == payload["warnings"]
            assert public["limitations"] == payload["limitations"]
            assert len(public["unresolved_blockers"]) >= 2
            assert any("failed" in item.lower() for item in public["unresolved_blockers"])


def test_verification_launch_failure_surfaces_exact_safe_blocker(
    tmp_path: Path,
) -> None:
    exact_blocker = (
        "The queued Verification target no longer matches the approved routing snapshot."
    )
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            session.execute(
                delete(AIModelInvocationEvidence).where(
                    AIModelInvocationEvidence.codex_run_id == run.id,
                    AIModelInvocationEvidence.capability == "verification",
                )
            )
            run.status = "failed"
            run.verification_status = "failed"
            run.verification_process_spawned = False
            run.verification_summary = exact_blocker
            session.flush()
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                valid_result_payload(session, fixture),
            )
            public_result = result_envelope_out(envelope)
            assert envelope.verification_verdict == "UNAVAILABLE"
            assert envelope.completion_classification == "result_incomplete"
            assert public_result["verification_result"]["evidence"][
                "safe_summary"
            ] == exact_blocker
            review = get_or_create_handoff_review(
                session,
                fixture.owner_id,
                fixture.run_id,
            )
            public_review = handoff_review_out(review)
            assert public_review["recommended_reconciliation"] == "BLOCKED"
            assert any(
                exact_blocker in item
                for item in public_review["unresolved_blockers"]
            )


def test_optional_verification_does_not_block_verified_coding_result_truth(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            envelope = import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                valid_result_payload(session, fixture),
            )
            session.expunge(envelope)
            envelope.verification_assignment_id = None
            envelope.verification_verdict = "UNAVAILABLE"
            envelope.verification_evidence_json = json.dumps(
                {
                    "outcome": "unavailable",
                    "safe_summary": "Independent Verification was not required.",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            public_result = result_envelope_out(envelope)
            assert public_result["verification_result"]["required"] is False
            assert public_result["execution_successful"] is True
            assert public_result["source_result_eligible_for_owner_review"] is True


def test_local_verification_summary_requires_sealed_attempt_evidence(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            run = _run(session, fixture)
            session.query(AIModelInvocationEvidence).filter(
                AIModelInvocationEvidence.codex_run_id == run.id,
                AIModelInvocationEvidence.capability == "verification",
            ).delete(synchronize_session=False)
            run.structured_result = json.dumps(
                {
                    "verification": {
                        "status": "completed",
                        "summary": "Unsealed local Verification claim.",
                    },
                    "verification_invocation": {
                        "mode": "local_command",
                        "model_provider_invoked": False,
                        "process_execution_verified": True,
                        "ticket_digest": "a" * 64,
                        "command_digest": "b" * 64,
                        "executable_fingerprint": "c" * 64,
                    },
                    "verification_verdict": {"status": "passed"},
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            session.flush()

            summary = result_intake_module._evidence_summary(
                session,
                run,
                "verification",
            )

            assert summary["available"] is False
            assert summary["verified_local_process"] is False
            assert summary["identity"] == ""
            assert summary["ticket_digest"] == ""
            assert summary["digest"] == ""


def test_reconnect_resumes_exact_process_or_reports_loss_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import twos_runtime.result_intake as result_intake_module

    with result_intake_fixture(tmp_path, run_status="running") as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = _run(session, fixture)
            ensure_run_monitor(
                session,
                fixture.owner_id,
                run,
                process_id=os.getpid(),
                process_start_identity="a" * 64,
            )
            run_count = session.scalar(select(func.count(CodexRun.id)))
            session.commit()
        monkeypatch.setattr(
            result_intake_module,
            "process_identity_matches",
            lambda _pid, _identity: True,
        )
        with factory() as session:
            resumed = reconnect_run_monitor(
                session,
                fixture.owner_id,
                fixture.run_id,
            )
            assert resumed.monitor_state == "RUNNING"
            assert resumed.recovery_state == "MONITORING_RESUMED"
            session.commit()
        monkeypatch.setattr(
            result_intake_module,
            "process_identity_matches",
            lambda _pid, _identity: False,
        )
        with factory() as session:
            lost = reconnect_run_monitor(
                session,
                fixture.owner_id,
                fixture.run_id,
            )
            assert lost.monitor_state == "PROCESS_LOST"
            assert lost.recovery_state == "PROCESS_LOST"
            assert session.scalar(select(func.count(CodexRun.id))) == run_count


def test_manual_fallback_api_is_structured_idempotent_and_owner_scoped(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            payload = valid_result_payload(session, fixture)
        url = f"/api/codex-runs/{fixture.run_id}/import-result"
        arbitrary = fixture.client.post(url, json={"result": "pasted prose"})
        assert arbitrary.status_code == 409
        imported = fixture.client.post(url, json={"result": payload})
        repeated = fixture.client.post(url, json={"result": payload})
        assert imported.status_code == repeated.status_code == 200
        assert (
            imported.json()["result"]["id"]
            == repeated.json()["result"]["id"]
        )
        wrong_owner_headers = _second_owner_headers(fixture)
        wrong_owner = fixture.client.post(
            url,
            json={"result": payload},
            headers=wrong_owner_headers,
        )
        missing = fixture.client.post(
            f"/api/codex-runs/{fixture.run_id + 100_000}/import-result",
            json={"result": payload},
            headers=wrong_owner_headers,
        )
        assert wrong_owner.status_code == missing.status_code == 404
        assert (
            wrong_owner.json()["error"]["message"]
            == missing.json()["error"]["message"]
        )


def test_run_activity_result_handoff_and_draft_routes_are_owner_scoped(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        with fixture.client.app.state.session_factory() as session:
            import_codex_result(
                session,
                fixture.owner_id,
                fixture.run_id,
                valid_result_payload(session, fixture),
            )
            session.commit()
        activity = fixture.client.get("/api/run-activity")
        result = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/result-envelope"
        )
        reviewed = fixture.client.post(
            f"/api/codex-runs/{fixture.run_id}/handoff-review"
        )
        draft = fixture.client.post(
            f"/api/codex-runs/{fixture.run_id}/instruction-draft"
        )
        assert activity.status_code == result.status_code == 200
        assert reviewed.status_code == draft.status_code == 200
        item = next(
            row for row in activity.json()["runs"] if row["run_id"] == fixture.run_id
        )
        assert item["task_name"]
        assert item["run_status"]
        assert item["requested_model"]
        assert item["result_integrity"] == "VERIFIED"
        assert item["owner_action"] == "Review Handoff"
        assert result.json()["result"]["owner_action"] == "Review Handoff"
        assert reviewed.json()["review"]["analysis_only"] is True
        assert draft.json()["draft"]["execution_authorized"] is False
        draft_payload = draft.json()["draft"]
        with fixture.client.app.state.session_factory() as session:
            run_count = session.scalar(select(func.count(CodexRun.id)))
        approved = fixture.client.post(
            f"/api/instruction-drafts/{draft_payload['id']}/approve",
            json={
                "action": "approve",
                "expected_digest": draft_payload["draft_digest"],
            },
        )
        repeated_approval = fixture.client.post(
            f"/api/instruction-drafts/{draft_payload['id']}/approve",
            json={
                "action": "approve",
                "expected_digest": draft_payload["draft_digest"],
            },
        )
        assert approved.status_code == repeated_approval.status_code == 200
        assert approved.json()["draft"]["approval_state"] == "APPROVED"
        assert approved.json()["draft"]["execution_authorized"] is False
        with fixture.client.app.state.session_factory() as session:
            assert session.scalar(select(func.count(CodexRun.id))) == run_count

        fixture.client.cookies.clear()
        for method, path in (
            ("get", "/api/run-activity"),
            (
                "get",
                f"/api/codex-runs/{fixture.run_id}/result-envelope",
            ),
            (
                "post",
                f"/api/codex-runs/{fixture.run_id}/handoff-review",
            ),
            (
                "post",
                f"/api/codex-runs/{fixture.run_id}/instruction-draft",
            ),
            (
                "post",
                f"/api/instruction-drafts/{draft_payload['id']}/approve",
            ),
        ):
            kwargs = (
                {
                    "json": {
                        "action": "approve",
                        "expected_digest": draft_payload["draft_digest"],
                    }
                }
                if "approve" in path
                else {}
            )
            response = getattr(fixture.client, method)(path, **kwargs)
            assert response.status_code == 401


def test_ui_contract_fixes_long_titles_selection_loading_and_progressive_disclosure() -> None:
    ui_root = (
        Path(__file__).parents[1]
        / "static_cockpit"
        / "vol12_static_mvp"
    )
    html = (ui_root / "twos_command_center.html").read_text(encoding="utf-8")
    javascript = (ui_root / "twos_command_center.js").read_text(encoding="utf-8")
    css = (ui_root / "styles.css").read_text(encoding="utf-8")

    for label in (
        "Run Activity",
        "Run Result",
        "Requested model",
        "Requested model accepted",
        "Run-local effective model",
        "Review Handoff",
        "Review Instruction Draft",
        "Approve Instruction",
        "Refresh Run Status",
        "Reconnect to Codex Run",
        "Import Codex Result",
        "Draft — Owner approval required",
        "Advanced",
    ):
        assert label in html or label in javascript
    assert 'id="selected-task-name"' in html
    assert 'id="selected-task-context"' in html
    assert 'data-state="loading"' in html
    assert 'id="run-activity' in html
    assert 'id="result-envelope-requested-model-accepted"' in html
    assert (
        "Not exposed by the current Codex CLI protocol."
        in html
    )
    assert "<details" in html
    assert "Advanced" in html
    assert "Loading the selected Task." in javascript
    assert "Selected Task loaded." in javascript
    assert "The selected Task could not be loaded." in javascript
    assert 'elements.feedback.textContent === "Loading task…"' in javascript
    assert 'setFeedback("Selected Task loaded.", "success")' in javascript
    assert 'elements.feedback.textContent === "Loading the selected Run Result…"' in javascript
    assert 'setFeedback("Run Result loaded.", "success")' in javascript
    assert "taskSelectionEpoch" in javascript
    assert "requestedTaskId" in javascript
    assert (
        "requestSelectionEpoch !== state.taskSelectionEpoch"
        in javascript
    )
    assert "String(state.selectedTaskId) !== String(requestedTaskId)" in javascript
    assert 'button.className = "task-list-button"' in javascript
    assert "button.title = taskDisplayName(task)" in javascript
    assert "elements.selectedTaskName.title = task ? name : \"\"" in javascript
    assert "title.title = view.taskName" in javascript
    assert (
        'appendRunActivityFact(facts, "Requested model accepted", '
        "view.requestedModelAccepted)"
        in javascript
    )
    assert (
        'appendRunActivityFact(facts, "Run-local effective model", '
        "view.runLocalEffectiveModel)"
        in javascript
    )
    assert "record.requested_model_accepted === true" in javascript
    assert "record.actual_model_verified === true" in javascript
    assert "RUN_LOCAL_MODEL_NOT_EXPOSED" in javascript
    assert "&& connectivity.actual_model" not in javascript
    assert "requested-model execution are ready" in javascript
    assert "Run-local effective model:" in javascript
    assert (
        "The installed Codex CLI is not compatible with this TWOS runtime. "
        "Open Advanced for technical details."
        in javascript
    )
    assert "safeProtocolDetails || diagnostics.output_summary" in javascript
    assert '"aria-current",' in javascript
    assert "overflow-wrap: anywhere" in css
    assert '.selected-task-context[data-state="success"]' in css
    assert '.selected-task-context[data-state="loading"]' in css
    assert '.selected-task-context[data-state="failure"]' in css
    assert "@media (max-width: 420px)" in css
    assert ".run-activity-item-grid" in css


def test_result_intake_source_has_no_automatic_delivery_or_provider_actions() -> None:
    root = Path(__file__).parents[1]
    result_source = (root / "twos_runtime" / "result_intake.py").read_text(
        encoding="utf-8"
    )
    app_source = (root / "twos_runtime" / "app.py").read_text(encoding="utf-8")
    ui_source = (
        root
        / "static_cockpit"
        / "vol12_static_mvp"
        / "twos_command_center.js"
    ).read_text(encoding="utf-8")

    assert "ProviderGateway" not in result_source
    assert "subprocess.Popen" not in result_source
    assert "CodexExecutionManager(" not in result_source
    assert "RuntimeScheduler(" not in result_source
    assert "get_or_create_delivery_candidate(" not in result_source
    assert "apply_accepted_changes(" not in result_source
    assert "revert_applied_changes(" not in result_source
    assert "Verify Applied Changes" in ui_source
    # Later phases may expose their controls in the shared shell.  Result
    # intake remains a pure evidence/recovery boundary and must never import or
    # invoke the Push service.
    assert "push_delivery" not in result_source
    assert "create_push_preflight" not in result_source
    assert "confirm_push_to_origin_main" not in result_source
    for boundary in FORBIDDEN_AUTOMATIC_ACTIONS:
        assert boundary in app_source or boundary in result_source or boundary in ui_source
