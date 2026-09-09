from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import test_self_hosting as fixtures
from twos_runtime.app import codex_run_out, run_result_projection
from twos_runtime.models import CodexExecutionAttempt, CodexRun
from twos_runtime import run_lifecycle
from twos_runtime import codex_adapter as adapter_module
from twos_runtime import codex_exec_bridge as bridge


def sqlite_handles(root: Path) -> list[str]:
    """Observe real handles before process exit, without GC or closing them."""
    root = root.resolve()
    proc = Path("/proc/self/fd")
    if proc.is_dir():
        targets = []
        for fd in proc.iterdir():
            try:
                targets.append(os.readlink(fd))
            except FileNotFoundError:
                pass
    else:
        result = subprocess.run(
            ["lsof", "-a", "-p", str(os.getpid()), "-F", "n"],
            check=True, capture_output=True, text=True,
        )
        targets = [line[1:] for line in result.stdout.splitlines() if line.startswith("n")]
    return sorted(
        str(Path(target).resolve()) for target in targets
        if ".sqlite" in target and Path(target).resolve().is_relative_to(root)
    )


@pytest.mark.parametrize("state", [
    "queued", "starting", "running", "verifying", "completed", "failed",
    "cancelled", "timed_out", "interrupted",
])
@pytest.mark.parametrize("partial", [None, [], "malformed"])
def test_public_result_shape_is_stable_without_persisting_evidence(state, partial):
    payload = {key: partial for key in (
        "verification", "verification_process", "process", "coding_process",
        "verification_verdict", "changed_files", "changed_file_evidence",
    )}
    run = CodexRun(
        id=1, status=state, task_id=1, pack_id=1,
        process_spawned=state not in {"queued", "starting"},
        timed_out=state == "timed_out", cancelled=state == "cancelled",
        exit_code=-15 if state == "timed_out" else None,
        verification_status="not_started", verification_process_spawned=False,
        structured_result=json.dumps(payload),
    )
    original = run.structured_result
    first = codex_run_out(run)
    again = codex_run_out(run)
    assert first == again
    result = first["result"]
    for key in ("verification", "verification_process", "process", "coding_process", "verification_verdict"):
        assert isinstance(result[key], dict)
    assert result["verification"]["status"] == "not_started"
    assert result["verification"]["process_spawned"] is False
    assert result["verification_verdict"]["status"] == "not_reached"
    assert result["changed_files"] == []
    assert result["changed_file_evidence"] == []
    assert result["process"]["timed_out"] is (state == "timed_out")
    assert result["coding_invocation"]["actual_model_identity_verified"] is False
    assert "workspace_evidence" not in result
    assert "working_tree_status" not in result
    assert "run_produced_changes" not in result
    assert run.structured_result == original


def test_projection_preserves_settled_evidence_and_does_not_mutate_input():
    run = CodexRun(status="completed", exit_code=0, process_spawned=True)
    result = {
        "process": {"exit_code": 0, "runtime_interrupted": False},
        "coding_process": {"status": "completed", "process_started": True},
        "verification": {"status": "completed", "process_spawned": True},
        "verification_process": {"status": "completed", "exit_code": 0},
        "verification_verdict": {"status": "passed", "passed_checks": ["exact content"]},
        "verification_invocation": {"mode": "local_command", "model_provider_invoked": False},
        "changed_files": ["target.txt"],
        "changed_file_evidence": [{"path": "target.txt"}],
        "workspace_evidence": {"status": "captured"},
    }
    before = copy.deepcopy(result)
    projected = run_result_projection(run, result)
    for key, value in result.items():
        if isinstance(value, dict):
            assert projected[key].items() >= value.items()
        else:
            assert projected[key] == value
    assert result == before


def test_verification_timeout_never_becomes_coding_timeout():
    run = CodexRun(
        status="timed_out", exit_code=0, timed_out=False, cancelled=False,
        process_spawned=True, verification_status="timed_out",
        verification_process_spawned=True, verification_exit_code=-15,
        verification_timed_out=True, verification_cancelled=False, structured_result="{}",
    )
    public = codex_run_out(run)
    assert public["timed_out"] is True
    assert public["result"]["process"]["timed_out"] is False
    assert public["result"]["coding_process"]["status"] == "completed"
    assert public["result"]["verification_process"]["timed_out"] is True
    assert public["result"]["verification_process"]["exit_code"] == -15
    assert run.structured_result == "{}"


@pytest.mark.parametrize("exceptional", [False, True])
def test_repeated_app_disposal_returns_sqlite_and_workers_to_baseline(tmp_path, exceptional):
    before_handles = sqlite_handles(tmp_path)
    before_threads = {thread.ident for thread in threading.enumerate()}
    for index in range(4):
        fixture = tmp_path / str(index)
        fixture.mkdir()
        source = fixtures.make_source_repo(fixture)
        executable = fixtures.make_nonreading_codex(fixture)
        client = fixtures.make_client(fixture, source, executable)
        try:
            with client:
                assert client.get("/api/health").status_code == 200
                if exceptional:
                    raise RuntimeError("controlled lifespan exit")
        except RuntimeError as exc:
            assert exceptional and str(exc) == "controlled lifespan exit"
        assert client.app.state.engine.pool.checkedout() == 0
        assert client.app.state.engine.pool.checkedin() == 0
        assert client.app.state.codex_manager._workers == {}
        assert client.app.state.codex_manager._processes == {}
        assert client.app.state.result_intake_monitor._thread is None
        assert run_lifecycle._reconciliation_lock_registry_size() == 0
        assert sqlite_handles(tmp_path) == before_handles
        assert {thread.ident for thread in threading.enumerate()} == before_threads


@pytest.mark.parametrize("scenario", ["migration", "restart"])
def test_existing_test_observations_close_their_own_database_resources(tmp_path, scenario):
    before = sqlite_handles(tmp_path)
    if scenario == "migration":
        fixtures.test_existing_database_migration_preserves_old_task(tmp_path)
    else:
        fixtures.test_runtime_shutdown_hands_off_detached_run_for_restart_recovery(tmp_path)
    assert sqlite_handles(tmp_path) == before
    assert run_lifecycle._reconciliation_lock_registry_size() == 0


def test_worker_ownership_includes_final_database_reconciliation(tmp_path, monkeypatch):
    source = fixtures.make_source_repo(tmp_path)
    executable = fixtures.make_nonreading_codex(tmp_path)
    entered, release = threading.Event(), threading.Event()
    captured = []
    with fixtures.make_client(tmp_path, source, executable) as client:
        manager = client.app.state.codex_manager
        real_reconcile = adapter_module.reconcile_run_monitors

        def gated_reconcile(*args, **kwargs):
            if threading.current_thread().name == "twos-codex-999":
                captured.append(threading.current_thread())
                entered.set()
                assert release.wait(5), "final database pass was not released"
            return real_reconcile(*args, **kwargs)

        # Isolate thread ownership of the final DB pass. The timeout tests in
        # the companion module retain their real Coding/bridge subprocesses.
        monkeypatch.setattr(manager, "_execute", lambda run_id: None)
        monkeypatch.setattr(adapter_module, "reconcile_run_monitors", gated_reconcile)
        assert manager.start(999)
        try:
            assert entered.wait(3)
            with manager._lock:
                assert manager._workers.get(999) is captured[0]
            release.set()
            manager.shutdown()
            assert not captured[0].is_alive()
            assert manager._workers == {}
        finally:
            release.set()
            for worker in captured:
                worker.join(5)
                assert not worker.is_alive()
    assert sqlite_handles(tmp_path) == []


def test_cli_repeated_initialization_and_owner_early_returns_close_database(tmp_path, monkeypatch):
    from twos_runtime import cli
    from twos_runtime.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'cli.sqlite3'}")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    before = sqlite_handles(tmp_path)
    for _ in range(3):
        assert cli.cmd_init_db() == 0
        assert sqlite_handles(tmp_path) == before
    answers = iter(["test-password-123", "different-password-123"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.cmd_init_owner("fixture-owner") == 1
    assert sqlite_handles(tmp_path) == before
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: "test-password-123")
    assert cli.cmd_init_owner("fixture-owner") == 0
    assert sqlite_handles(tmp_path) == before

    def unexpected_prompt(_prompt):
        pytest.fail("an existing Owner must not trigger another password prompt")

    monkeypatch.setattr(cli.getpass, "getpass", unexpected_prompt)
    assert cli.cmd_init_owner("fixture-owner") == 1
    assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize("command", ["init-db", "init-owner", "recover-owner"])
def test_cli_initialization_exception_disposes_opened_pool(tmp_path, monkeypatch, command):
    from twos_runtime import cli
    from twos_runtime.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'initialization.sqlite3'}")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    initialize = cli.initialize_database

    def fail_after_real_database_open(engine):
        initialize(engine)
        assert engine.pool.checkedin() > 0
        raise RuntimeError("controlled initialization failure")

    monkeypatch.setattr(cli, "initialize_database", fail_after_real_database_open)
    before = sqlite_handles(tmp_path)
    with pytest.raises(RuntimeError, match="controlled initialization failure"):
        if command == "init-db":
            cli.cmd_init_db()
        elif command == "init-owner":
            cli.cmd_init_owner("fixture-owner")
        else:
            cli.cmd_recover_owner(True)
    assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize("scenario", ["invalid-owner", "unverifiable-owner"])
def test_real_owner_recovery_cli_returns_sqlite_handles_to_baseline(
    tmp_path, monkeypatch, capsys, scenario,
):
    from tests import test_owner_auth

    before = sqlite_handles(tmp_path)
    if scenario == "invalid-owner":
        test_owner_auth.test_invalid_owner_requires_opt_in_local_recovery_and_preserves_product_data(
            tmp_path, monkeypatch, capsys,
        )
    else:
        test_owner_auth.test_explicit_one_time_recovery_can_replace_an_unverifiable_current_shape(
            tmp_path, monkeypatch,
        )
    assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize("valid", [True, False])
def test_sqlite_fixture_backup_closes_both_connections_on_success_and_failure(tmp_path, valid):
    from scripts.vol18_4b_owner_acceptance_app import _backup_sqlite

    source = tmp_path / "source.sqlite3"
    if valid:
        with closing(sqlite3.connect(source)) as connection, connection:
            connection.execute("CREATE TABLE fixture(value TEXT)")
            connection.execute("INSERT INTO fixture VALUES ('non-sensitive fixture')")
    else:
        source.write_bytes(b"not a SQLite database")
    before = sqlite_handles(tmp_path)
    for index in range(3):
        destination = tmp_path / f"backup-{index}.sqlite3"
        if valid:
            _backup_sqlite(source, destination)
            with closing(sqlite3.connect(destination)) as connection:
                assert connection.execute("SELECT value FROM fixture").fetchall() == [
                    ("non-sensitive fixture",),
                ]
        else:
            with pytest.raises(sqlite3.DatabaseError):
                _backup_sqlite(source, destination)
        assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize("scenario", ["connectivity", "acceptance-4a", "acceptance-4b", "run-binding"])
def test_legacy_observation_queries_release_sqlite_before_test_exit(tmp_path, monkeypatch, scenario):
    from tests import test_vol18_codex_connectivity as connectivity
    from tests import test_vol18_owner_acceptance_runtime as acceptance_4a
    from tests import test_vol18_4b_owner_acceptance_runtime as acceptance_4b
    from tests import test_vol19_codex_run_result_capture as capture

    before = sqlite_handles(tmp_path)
    if scenario == "connectivity":
        connectivity.test_vol18_005_migration_and_append_only_evidence(tmp_path, monkeypatch)
    elif scenario == "acceptance-4a":
        acceptance_4a.test_fresh_signup_receives_exact_executable_phase18_4a_task(tmp_path, monkeypatch)
    elif scenario == "acceptance-4b":
        acceptance_4b.test_real_signup_only_imports_completed_history_and_never_changes_repository(tmp_path)
    else:
        capture.test_owner_start_bindings_are_set_once_through_orm_and_raw_sqlite(tmp_path)
    assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize("exceptional", [False, True])
def test_model_registry_fixture_disposes_engines_even_when_test_raises(tmp_path, monkeypatch, exceptional):
    from tests import test_model_orchestration

    before = sqlite_handles(tmp_path)
    with monkeypatch.context() as changes:
        ownership = test_model_orchestration._dispose_test_databases.__wrapped__(changes)
        next(ownership)
        try:
            test_model_orchestration.test_fresh_vol17_schema_starts_empty_and_fixture_sources_are_explicit(tmp_path)
            if exceptional:
                raise RuntimeError("controlled test failure")
        except RuntimeError as exc:
            assert exceptional and str(exc) == "controlled test failure"
        finally:
            ownership.close()
    assert sqlite_handles(tmp_path) == before


@pytest.mark.parametrize('read_failure', [False, True])
def test_activity_stream_does_not_close_concurrent_protected_hash(tmp_path, monkeypatch, read_failure):
    phase = tmp_path / 'phase'
    phase.mkdir()
    stdout = phase / 'stdout.bin'
    stdout.write_bytes(b'{}\n')
    stdout.chmod(0o600)
    protected = phase / 'stdin.bin'
    content = b'deterministic immutable approved input\n'
    protected.write_bytes(content)
    protected.chmod(0o600)
    opened = threading.Event()
    release = threading.Event()
    outcomes = []
    errors = []
    descriptors = {}
    real_open = bridge._open_protected_file
    real_fdopen = os.fdopen

    def observed_open(path):
        descriptor, details = real_open(path)
        if path == protected:
            descriptors['hash'] = descriptor
            opened.set()
            if not release.wait(5):
                os.close(descriptor)
                raise AssertionError('test did not release protected read')
        return descriptor, details

    def hash_input():
        try:
            outcomes.append(bridge._hash_file(protected))
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=hash_input, name='test-protected-hash')

    def observed_fdopen(descriptor, *args, **kwargs):
        descriptors['activity'] = descriptor
        wrapped = real_fdopen(descriptor, *args, **kwargs)

        class ActivityStream:
            def __enter__(self):
                wrapped.__enter__()
                return self

            def seek(self, offset):
                if read_failure:
                    raise RuntimeError('controlled activity read failure')
                return wrapped.seek(offset)

            def __getattr__(self, name):
                return getattr(wrapped, name)

            def __exit__(self, *exception):
                try:
                    return wrapped.__exit__(*exception)
                finally:
                    # Open a real protected file at the exact ownership handoff.
                    # A double close will invalidate this other thread's FD.
                    reader.start()
                    assert opened.wait(5)

        return ActivityStream()

    monkeypatch.setattr(bridge, '_open_protected_file', observed_open)
    monkeypatch.setattr(os, 'fdopen', observed_fdopen)
    attempt = CodexExecutionAttempt(stdout_offset=0, last_event_type='')
    handle = SimpleNamespace(phase_directory=phase)
    try:
        if read_failure:
            with pytest.raises(RuntimeError, match='controlled activity read failure'):
                run_lifecycle._read_activity_events(None, attempt, handle)
        else:
            run_lifecycle._read_activity_events(None, attempt, handle)
            assert attempt.stdout_offset == 3
    finally:
        release.set()
        if reader.ident is not None:
            reader.join(5)
    assert not reader.is_alive()
    assert not errors, [(type(exc).__name__, getattr(exc, 'errno', None), descriptors) for exc in errors]
    assert outcomes[0][0] == hashlib.sha256(content).hexdigest()
    assert outcomes[0][1] == len(content)
    for descriptor in set(descriptors.values()):
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF


def test_activity_wrapper_creation_failure_closes_raw_descriptor(tmp_path, monkeypatch):
    (tmp_path / 'stdout.bin').write_bytes(b'{}\n')
    descriptors = []

    def unavailable_wrapper(descriptor, *args, **kwargs):
        descriptors.append(descriptor)
        raise OSError(errno.ENOMEM, 'controlled stream-wrapper failure')

    monkeypatch.setattr(os, 'fdopen', unavailable_wrapper)
    attempt = CodexExecutionAttempt(stdout_offset=0, last_event_type='')
    with pytest.raises(OSError) as failure:
        run_lifecycle._read_activity_events(None, attempt, SimpleNamespace(phase_directory=tmp_path))
    assert failure.value.errno == errno.ENOMEM
    assert len(descriptors) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(descriptors[0])
    assert closed.value.errno == errno.EBADF


def test_terminal_verification_proof_is_atomic_before_optional_result_intake(tmp_path, monkeypatch):
    """A real terminal API must not depend on the final intake worker winning."""
    from sqlalchemy import select
    from tests.test_vol19_large_pack_timeout_settlement import join_workers
    from tests.test_vol19_verification_truth_remediation import make_local_verifier
    from twos_runtime.models import CodexResultEnvelope

    source = fixtures.make_source_repo(tmp_path)
    executable = fixtures.make_fake_codex(tmp_path)
    final_publication = threading.Event()
    release_intake = threading.Event()
    with fixtures.make_client(
        tmp_path, source, executable, timeout=20,
        local_verification_command=make_local_verifier(tmp_path),
    ) as client:
        headers = fixtures.init_and_login(client)
        manager = client.app.state.codex_manager
        monitor = client.app.state.result_intake_monitor
        factory = client.app.state.session_factory
        real_verification = manager._execute_local_verification
        real_intake = adapter_module.reconcile_run_monitors

        def finish_real_verification(*args, **kwargs):
            result = real_verification(*args, **kwargs)
            assert result['status'] == 'completed'
            assert result['exit_code'] == 0
            monitor.shutdown()
            assert monitor._thread is None
            return result

        def hold_optional_intake(*args, **kwargs):
            # Both real subprocesses have exited. Only optional publication is
            # paused; no Run, receipt, attempt, or API result is fabricated.
            final_publication.set()
            assert release_intake.wait(10)
            return real_intake(*args, **kwargs)

        monkeypatch.setattr(manager, '_execute_local_verification', finish_real_verification)
        monkeypatch.setattr(adapter_module, 'reconcile_run_monitors', hold_optional_intake)
        task_id = fixtures.create_executable_task(
            client, headers, marker='FAKE_TEST_COMMAND FAKE_READ_ONLY_GIT_INSPECTION',
        )
        pack = fixtures.generate_pack(client, headers, task_id)
        fixtures.approve_pack(client, headers, task_id, pack['id'])
        started = fixtures.start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200
        run_id = started.json()['id']
        try:
            assert final_publication.wait(20)
            for _ in range(2):
                response = client.get(f'/api/codex-runs/{run_id}', headers=headers)
                assert response.status_code == 200
                public = response.json()
                assert public['status'] == 'completed'
                assert public['exit_code'] == 0
                assert public['result']['verification']['status'] == 'completed'
                assert public['result']['verification_invocation']['process_execution_verified'] is True
                assert public['result']['verification_invocation']['model_provider_invoked'] is False
                assert public['terminal_truth']['result']['available'] is False
            with factory() as session:
                assert session.scalar(select(CodexResultEnvelope.id)) is None
                attempt = session.scalar(select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == run_id,
                    CodexExecutionAttempt.phase == 'VERIFICATION',
                ))
                assert attempt.attempt_state == 'COMPLETED'
                assert attempt.process_exit_known and attempt.process_exit_code == 0
                assert attempt.receipt_digest and attempt.terminal_event_observed
        finally:
            release_intake.set()
            join_workers(manager)
    assert run_lifecycle._reconciliation_lock_registry_size() == 0
    assert sqlite_handles(tmp_path) == []


def test_api_cannot_pair_stale_verification_proof_with_newer_lifecycle(tmp_path, monkeypatch):
    """Release real phase settlement at the API's lifecycle-read boundary."""
    from tests.test_vol19_large_pack_timeout_settlement import join_workers
    from tests.test_vol19_verification_truth_remediation import make_local_verifier
    import twos_runtime.app as app_module

    source = fixtures.make_source_repo(tmp_path)
    executable = fixtures.make_fake_codex(tmp_path)
    phase_ready = threading.Event()
    release_phase = threading.Event()
    phase_settled = threading.Event()
    release_intake = threading.Event()
    lifecycle_reads = []
    with fixtures.make_client(
        tmp_path, source, executable, timeout=20,
        local_verification_command=make_local_verifier(tmp_path),
    ) as client:
        headers = fixtures.init_and_login(client)
        manager = client.app.state.codex_manager
        monitor = client.app.state.result_intake_monitor
        real_verification = manager._execute_local_verification
        real_phase = manager._settle_terminal_phase
        real_intake = adapter_module.reconcile_run_monitors
        real_lifecycle = app_module.lifecycle_snapshot_out

        def finish_verification(*args, **kwargs):
            result = real_verification(*args, **kwargs)
            assert result['exit_code'] == 0 and result['status'] == 'completed'
            monitor.shutdown()
            assert monitor._thread is None
            return result

        def hold_phase(run_id):
            phase_ready.set()
            assert release_phase.wait(10)
            real_phase(run_id)
            phase_settled.set()

        def hold_intake(*args, **kwargs):
            assert release_intake.wait(10)
            return real_intake(*args, **kwargs)

        def release_at_lifecycle_read(*args, **kwargs):
            if phase_ready.is_set() and not phase_settled.is_set():
                lifecycle_reads.append('terminal-phase-publication')
                release_phase.set()
                assert phase_settled.wait(10)
            return real_lifecycle(*args, **kwargs)

        monkeypatch.setattr(manager, '_execute_local_verification', finish_verification)
        monkeypatch.setattr(manager, '_settle_terminal_phase', hold_phase)
        monkeypatch.setattr(adapter_module, 'reconcile_run_monitors', hold_intake)
        monkeypatch.setattr(app_module, 'lifecycle_snapshot_out', release_at_lifecycle_read)
        task_id = fixtures.create_executable_task(
            client, headers, marker='FAKE_TEST_COMMAND FAKE_READ_ONLY_GIT_INSPECTION',
        )
        pack = fixtures.generate_pack(client, headers, task_id)
        fixtures.approve_pack(client, headers, task_id, pack['id'])
        started = fixtures.start_codex_run(client, headers, task_id, pack)
        assert started.status_code == 200
        run_id = started.json()['id']
        try:
            assert phase_ready.wait(20)
            with client.app.state.session_factory() as session:
                run = session.get(CodexRun, run_id)
                assert run.status == 'completed' and run.exit_code == 0
                assert run.verification_exit_code == 0
            response = client.get(f'/api/codex-runs/{run_id}', headers=headers)
            assert response.status_code == 200
            public = response.json()
            assert lifecycle_reads == ['terminal-phase-publication']
            assert public['status'] == 'completed'
            assert public['result']['verification_invocation']['process_execution_verified'] is True
            assert public['result']['verification']['status'] == 'completed'
            assert public['terminal_truth']['result']['available'] is False
        finally:
            release_phase.set()
            release_intake.set()
            join_workers(manager)
    assert run_lifecycle._reconciliation_lock_registry_size() == 0
    assert sqlite_handles(tmp_path) == []
