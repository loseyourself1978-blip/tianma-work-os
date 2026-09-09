from __future__ import annotations

import json
import hashlib
import os
import secrets
import sqlite3
import stat
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import twos_runtime.app as app_module
import twos_runtime.first_run as first_run_module
from twos_runtime.app import create_app
from twos_runtime.config import ROOT_DIR, STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.db import initialize_database, make_engine
from twos_runtime.models import (
    AIModelInvocationEvidence,
    ApplySession,
    AuditEvent,
    AuthorizedWorkspace,
    CodexInstructionPack,
    CodexRun,
    Installation,
    LocalCommitExecution,
    Project,
    PushExecution,
    SessionToken,
    Task,
    TaskRun,
    User,
    utc_now,
)


USERNAME = "owner-first-run"
PASSWORD = secrets.token_urlsafe(24)


def fresh_settings(root: Path, *, installation_id: str | None = None, port: int = 18765) -> Settings:
    data = root / "data"
    logs = root / "logs"
    runtime = root / "runtime"
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    logs.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    identity = installation_id or f"install_{uuid.uuid4().hex}"
    return Settings(
        database_url=f"sqlite:///{data / 'twos.sqlite3'}",
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=ROOT_DIR,
        worktree_root=runtime / "worktrees",
        codex_spool_root=runtime / "codex-spool",
        fresh_install=True,
        installation_id=identity,
        data_root=data,
        runtime_environment=Path(sys.prefix),
        log_directory=logs,
        installation_config_path=data / "installation.json",
        setup_authorization_path=data / "setup-authorization.txt",
        bind_host="127.0.0.1",
        bind_port=port,
        session_cookie_name=f"twos_session_{identity}",
    )


def start_owner_step(client: TestClient) -> None:
    assert client.post(
        "/api/setup/start", json={"confirmation": "START_FIRST_RUN"}
    ).json()["state"] == "installation_confirmation_pending"
    assert client.post(
        "/api/setup/start", json={"confirmation": "CONFIRM_INSTALLATION"}
    ).json()["state"] == "owner_creation_pending"


def owner_payload(settings: Settings, *, request_id: str = "setup-request-0001") -> dict[str, str]:
    assert settings.setup_authorization_path is not None
    return {
        "username": USERNAME,
        "password": PASSWORD,
        "password_confirmation": PASSWORD,
        "setup_authorization": settings.setup_authorization_path.read_text(encoding="utf-8").strip(),
        "request_id": request_id,
    }


def create_owner_and_workspace(
    client: TestClient,
    settings: Settings,
    workspace: Path,
    *,
    request_id: str = "setup-request-0001",
) -> None:
    start_owner_step(client)
    response = client.post("/api/setup/owner", json=owner_payload(settings, request_id=request_id))
    assert response.status_code == 201, response.text
    assert response.json()["owner_created"] is True
    assert response.json()["state"] == "workspace_pending"
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    authorized = client.post(
        "/api/setup/workspace",
        json={"path": str(workspace), "create_if_missing": False},
    )
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["state"] == "optional_tools_pending"


def finish_setup(client: TestClient) -> None:
    skipped = client.post("/api/setup/optional-tools", json={"decision": "skip"})
    assert skipped.status_code == 200
    assert skipped.json()["state"] == "completion_pending"
    finished = client.post(
        "/api/setup/finish", json={"confirmation": "FINISH_FIRST_RUN"}
    )
    assert finished.status_code == 200
    assert finished.json()["state"] == "ready"


def test_fresh_install_starts_empty_and_requires_setup_authorization(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(User.id))) == 0
            assert session.scalar(select(func.count(Project.id))) == 0
            assert session.scalar(select(func.count(Task.id))) == 0
            installation = session.scalar(select(Installation))
            assert installation is not None
            assert installation.first_run_state == "setup_authorization_pending"
            assert installation.setup_token_hash
        assert settings.setup_authorization_path is not None
        assert settings.setup_authorization_path.is_file()
        assert settings.setup_authorization_path.stat().st_mode & 0o077 == 0
        with TestClient(app) as client:
            status = client.get("/api/setup/status")
            assert status.status_code == 200
            assert status.json()["owner_exists"] is False
            assert status.json()["installation"]["localhost_only"] is True
            assert client.get("/api/projects").status_code == 428
            start_owner_step(client)
            invalid = owner_payload(settings)
            invalid["setup_authorization"] = "invalid-setup-authorization"
            rejected = client.post("/api/setup/owner", json=invalid)
            assert rejected.status_code == 403
            assert rejected.json()["error"]["code"] == "SETUP_AUTHORIZATION_INVALID"
    finally:
        app.state.engine.dispose()


def test_first_owner_uses_canonical_auth_and_exact_request_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            start_owner_step(client)
            payload = owner_payload(settings)
            created = client.post("/api/setup/owner", json=payload)
            assert created.status_code == 201
            assert created.json()["owner_created"] is True
            assert settings.setup_authorization_path is not None
            assert not settings.setup_authorization_path.exists()

            replay = client.post("/api/setup/owner", json=payload)
            assert replay.status_code == 201
            assert replay.json()["owner_created"] is False
            assert replay.json()["authenticated"] is True
            with app.state.session_factory() as session:
                assert session.scalar(select(func.count(SessionToken.id))) == 1
                assert session.scalar(select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "first_owner_created"
                )) == 1

            distinct = dict(payload, request_id="setup-request-0002")
            rejected = client.post("/api/setup/owner", json=distinct)
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == "FIRST_OWNER_EXISTS"

            client.post("/api/auth/logout")
            replay_signed_out = client.post("/api/setup/owner", json=payload)
            assert replay_signed_out.status_code == 201
            assert replay_signed_out.json()["owner_created"] is False
            assert replay_signed_out.json()["authenticated"] is False
            assert replay_signed_out.json()["user"] is None
            assert client.get("/api/auth/session").json()["authenticated"] is False
            with app.state.session_factory() as session:
                assert session.scalar(select(func.count(SessionToken.id))) == 1
            wrong = client.post(
                "/api/auth/login", json={"username": USERNAME, "password": "wrong-password"}
            )
            assert wrong.status_code == 401
            login = client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            )
            assert login.status_code == 200
            assert login.json()["user"]["username"] == USERNAME
            assert client.post(
                "/api/auth/signup", json={"username": "second", "password": "another-password"}
            ).json()["code"] == "FIRST_RUN_REQUIRED"

        with app.state.session_factory() as session:
            owners = session.scalars(select(User)).all()
            installation = session.scalar(select(Installation))
            assert len(owners) == 1
            assert installation is not None
            assert installation.setup_token_hash is None
            assert installation.setup_token_used_at is not None
            assert installation.owner_setup_request_id == payload["request_id"]
            expected_nonsecret_digest = hashlib.sha256(
                f"first-owner-v1\0{payload['request_id']}\0{USERNAME}".encode("utf-8")
            ).hexdigest()
            old_password_derived_digest = hashlib.sha256(
                f"{payload['request_id']}\0{USERNAME}\0{PASSWORD}".encode("utf-8")
            ).hexdigest()
            assert installation.owner_setup_request_digest == expected_nonsecret_digest
            assert installation.owner_setup_request_digest != old_password_derived_digest
            audit_text = json.dumps(
                [row.details for row in session.scalars(select(AuditEvent)).all()]
            )
            assert PASSWORD not in audit_text
            assert payload["setup_authorization"] not in audit_text
        with closing(sqlite3.connect(settings.data_root / "twos.sqlite3")) as connection, connection:
            persisted_text = "\n".join(connection.iterdump())
        assert PASSWORD not in persisted_text
        assert old_password_derived_digest not in persisted_text
    finally:
        app.state.engine.dispose()


def test_setup_and_auth_response_bodies_never_expose_secret_material(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with app.state.session_factory() as session:
            setup_hash = session.scalar(select(Installation)).setup_token_hash
        with TestClient(app) as client:
            responses = [client.get("/api/setup/status"), client.get("/api/auth/session")]
            start_owner_step(client)
            payload = owner_payload(settings)
            responses.append(client.post("/api/setup/owner", json=payload))
            assert responses[-1].status_code == 201
            raw_sessions = [client.cookies.get(settings.session_cookie_name)]
            responses.extend([client.get("/api/setup/status"), client.get("/api/auth/session")])
            responses.append(client.post("/api/setup/owner", json=payload))
            responses.append(client.post("/api/auth/logout"))
            responses.append(client.post(
                "/api/auth/login", json={"username": USERNAME, "password": "invalid-secret-value"}
            ))
            assert responses[-1].status_code == 401
            responses.append(client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            ))
            assert responses[-1].status_code == 200
            raw_sessions.append(client.cookies.get(settings.session_cookie_name))
            responses.extend([client.get("/api/setup/status"), client.get("/api/auth/session")])
            with app.state.session_factory() as session:
                owner = session.scalar(select(User))
                secrets_to_exclude = [
                    PASSWORD, payload["setup_authorization"], setup_hash,
                    owner.password_hash, owner.password_salt, "invalid-secret-value",
                    *raw_sessions,
                    *session.scalars(select(SessionToken.token_hash)).all(),
                ]
            # HttpOnly Set-Cookie is the intentional session transport, never JSON evidence.
            response_bodies = "\n".join(response.text for response in responses)
            for secret in secrets_to_exclude:
                assert secret
                assert secret not in response_bodies, "A setup/auth response exposed secret material"
            for field in ("password_hash", "password_salt", "setup_token_hash", "token_hash"):
                assert field not in response_bodies
    finally:
        app.state.engine.dispose()


def test_missing_first_owner_request_identity_cannot_create_an_owner_or_session(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            start_owner_step(client)
            payload = owner_payload(settings)
            del payload["request_id"]
            rejected = client.post("/api/setup/owner", json=payload)
            assert rejected.status_code == 400
            assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
            assert PASSWORD not in rejected.text
            assert payload["setup_authorization"] not in rejected.text
            status = client.get("/api/setup/status").json()
            assert status["state"] == "owner_creation_pending"
            assert status["owner_exists"] is False
            assert status["setup_authorization"]["available"] is True
            assert client.get("/api/auth/session").json()["authenticated"] is False
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(User.id))) == 0
            assert session.scalar(select(func.count(SessionToken.id))) == 0
            installation = session.scalar(select(Installation))
            assert installation.owner_setup_request_id is None
            assert installation.setup_token_used_at is None
    finally:
        app.state.engine.dispose()


def test_concurrent_first_owner_attempts_create_exactly_one_owner(tmp_path: Path) -> None:
    from tests.test_vol19_timeout_result_projection_cleanup import sqlite_handles

    before = sqlite_handles(tmp_path)
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as control:
            start_owner_step(control)
            token = settings.setup_authorization_path.read_text(encoding="utf-8").strip()

            def submit(index: int) -> int:
                response = control.post(
                    "/api/setup/owner",
                    json={
                        "username": USERNAME,
                        "password": PASSWORD,
                        "password_confirmation": PASSWORD,
                        "setup_authorization": token,
                        "request_id": f"concurrent-request-{index:04d}",
                    },
                )
                return response.status_code

            # Concurrent requests share one real server lifespan. Concurrently
            # entering/exiting two lifespans on one app can dispose another
            # request's pool while its SQLite connection is still checked out.
            with ThreadPoolExecutor(max_workers=2) as executor:
                statuses = sorted(executor.map(submit, (1, 2)))
            assert statuses == [201, 409]
            with app.state.session_factory() as session:
                assert session.scalar(select(func.count(User.id))) == 1
    finally:
        app.state.engine.dispose()
    assert sqlite_handles(tmp_path) == before


def test_safe_workspace_authorization_is_non_mutating_and_blocks_unsafe_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = fresh_settings(tmp_path / "installation")
    app = create_app(settings=settings, start_scheduler=False)
    try:
        workspace = tmp_path / "workspace"
        workspace.mkdir(mode=0o700)
        existing = workspace / "owner-note.txt"
        existing.write_text("preserve exactly\n", encoding="utf-8")
        before = {item.name: item.read_bytes() for item in workspace.iterdir()}
        with TestClient(app) as client:
            start_owner_step(client)
            assert client.post("/api/setup/owner", json=owner_payload(settings)).status_code == 201
            accepted = client.post(
                "/api/setup/workspace",
                json={"path": str(workspace), "create_if_missing": False},
            )
            assert accepted.status_code == 200
            rejected_later = tmp_path / "must-not-be-created-after-authorization"
            blocked = client.post(
                "/api/setup/workspace",
                json={"path": str(rejected_later), "create_if_missing": True},
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "WORKSPACE_ALREADY_AUTHORIZED"
            assert not rejected_later.exists()
        after = {item.name: item.read_bytes() for item in workspace.iterdir()}
        assert after == before
        assert settings.source_repo == workspace.resolve()

        fake_source = tmp_path / "fake-source"
        fake_source.mkdir()
        monkeypatch.setattr(first_run_module, "ROOT_DIR", fake_source)
        forbidden = fake_source / "must-not-be-created"
        with pytest.raises(first_run_module.FirstRunError) as raised:
            first_run_module.validate_authorized_workspace(
                str(forbidden), settings=settings, create_if_missing=True
            )
        assert raised.value.code == "WORKSPACE_IS_TWOS_SOURCE"
        assert not forbidden.exists()
    finally:
        app.state.engine.dispose()


def test_dangling_symlink_is_rejected_before_data_or_workspace_resolution(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path / "installation")
    absent_target = tmp_path / "absent-target"
    dangling = tmp_path / "dangling"
    dangling.symlink_to(absent_target, target_is_directory=True)
    for path in (dangling, dangling / "nested"):
        with pytest.raises(first_run_module.FirstRunError) as data_error:
            first_run_module.validate_data_root(path)
        assert data_error.value.code == "PATH_SYMLINK_UNSAFE"
        with pytest.raises(first_run_module.FirstRunError) as workspace_error:
            first_run_module.validate_authorized_workspace(
                str(path), settings=settings, create_if_missing=True
            )
        assert workspace_error.value.code == "PATH_SYMLINK_UNSAFE"
        assert not absent_target.exists()
        assert dangling.is_symlink()


def test_workspace_traversal_symlink_home_and_nested_git_root_are_blocked(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path / "installation")
    with pytest.raises(first_run_module.FirstRunError) as traversal:
        first_run_module.validate_authorized_workspace(
            str(tmp_path / "missing" / ".." / "workspace"),
            settings=settings,
            create_if_missing=False,
        )
    assert traversal.value.code == "WORKSPACE_TRAVERSAL"

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-workspace"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(first_run_module.FirstRunError) as symlink:
        first_run_module.validate_authorized_workspace(
            str(link), settings=settings, create_if_missing=False
        )
    assert symlink.value.code == "PATH_SYMLINK_UNSAFE"

    with pytest.raises(first_run_module.FirstRunError) as home:
        first_run_module.validate_authorized_workspace(
            str(Path.home()), settings=settings, create_if_missing=False
        )
    assert home.value.code == "WORKSPACE_SCOPE_TOO_BROAD"

    repository = tmp_path / "repository"
    nested = repository / "nested"
    (repository / ".git").mkdir(parents=True)
    nested.mkdir()
    with pytest.raises(first_run_module.FirstRunError) as git_scope:
        first_run_module.validate_authorized_workspace(
            str(nested), settings=settings, create_if_missing=False
        )
    assert git_scope.value.code == "WORKSPACE_NOT_REPOSITORY_ROOT"


def test_setup_step_restart_cookie_clear_task_persistence_and_no_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = f"install_{uuid.uuid4().hex}"
    root = tmp_path / "installation"
    settings = fresh_settings(root, installation_id=identity)
    workspace = tmp_path / "workspace"
    app = create_app(settings=settings, start_scheduler=False)
    with TestClient(app) as client:
        create_owner_and_workspace(client, settings, workspace)
        assert client.get("/api/setup/status").json()["state"] == "optional_tools_pending"
    app.state.engine.dispose()

    restarted_settings = fresh_settings(root, installation_id=identity)
    restarted = create_app(settings=restarted_settings, start_scheduler=False)
    try:
        with TestClient(restarted) as client:
            status = client.get("/api/setup/status").json()
            assert status["state"] == "optional_tools_pending"
            assert status["owner_exists"] is True
            assert status["authenticated"] is False
            assert client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            ).status_code == 200
            finish_setup(client)

            def unexpected_detect(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("automatic Codex CLI detection is forbidden")

            monkeypatch.setattr(restarted.state.codex_manager.adapter, "detect", unexpected_detect)
            passive = client.get("/api/codex/status")
            assert passive.status_code == 200
            assert passive.json()["passive"] is True
            assert passive.json()["readiness_state"] == "Skipped"

            projects = client.get("/api/projects").json()
            assert len(projects) == 1
            task = client.post(
                "/api/tasks",
                json={
                    "project_id": projects[0]["id"],
                    "title": "VOL19 19.2A — First Fresh Install Task",
                    "development_task": "Confirm the fresh First Run boundary.",
                    "objective": "Save and reopen without execution.",
                    "action": "Analyze",
                    "workflow_type": "general",
                },
            )
            assert task.status_code == 200
            assert task.json()["status"] == "draft"
            task_id = task.json()["id"]
            assert [item["id"] for item in client.get("/api/tasks").json()] == [task_id]
            passive_eligibility = client.get(f"/api/tasks/{task_id}/run-eligibility")
            assert passive_eligibility.status_code == 200
            assert passive_eligibility.json()["eligible"] is False

        with restarted.state.session_factory() as session:
            assert session.scalar(select(func.count(Task.id))) == 1
            for model in (
                TaskRun,
                CodexInstructionPack,
                CodexRun,
                AIModelInvocationEvidence,
                ApplySession,
                LocalCommitExecution,
                PushExecution,
            ):
                assert session.scalar(select(func.count(model.id))) == 0
    finally:
        restarted.state.engine.dispose()

    final_settings = fresh_settings(root, installation_id=identity)
    final_app = create_app(settings=final_settings, start_scheduler=False)
    try:
        with TestClient(final_app) as client:
            assert client.get("/api/setup/status").json()["state"] == "ready"
            assert client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            ).status_code == 200
            tasks = client.get("/api/tasks").json()
            assert len(tasks) == 1
            assert tasks[0]["title"] == "VOL19 19.2A — First Fresh Install Task"
    finally:
        final_app.state.engine.dispose()


def test_failed_workspace_step_persists_and_requires_explicit_retry_after_restart(
    tmp_path: Path,
) -> None:
    identity = f"install_{uuid.uuid4().hex}"
    root = tmp_path / "installation"
    settings = fresh_settings(root, installation_id=identity)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            start_owner_step(client)
            assert client.post("/api/setup/owner", json=owner_payload(settings)).status_code == 201
            failed = client.post(
                "/api/setup/workspace",
                json={"path": str(tmp_path / "absent"), "create_if_missing": False},
            )
            assert failed.status_code == 400
            status = client.get("/api/setup/status").json()
            assert status["state"] == "failed"
            assert status["current_step"] == "workspace"
            assert status["blocking_reason"]
            assert client.get("/api/projects").status_code == 428
        with app.state.session_factory() as session:
            installation = session.scalar(select(Installation))
            assert installation.first_run_state == "failed"
            assert installation.resume_state == "workspace_pending"
            assert installation.failure_code == failed.json()["error"]["code"]
            assert session.scalar(select(func.count(User.id))) == 1
            assert session.scalar(select(func.count(AuthorizedWorkspace.id))) == 0
    finally:
        app.state.engine.dispose()

    restarted_settings = fresh_settings(root, installation_id=identity)
    restarted = create_app(settings=restarted_settings, start_scheduler=False)
    try:
        with TestClient(restarted) as client:
            assert client.get("/api/setup/status").json()["state"] == "failed"
            assert client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            ).status_code == 200
            assert client.get("/api/setup/status").json()["current_step"] == "workspace"
            workspace = tmp_path / "explicitly-created-workspace"
            assert not workspace.exists()
            resumed = client.post(
                "/api/setup/workspace", json={"path": str(workspace), "create_if_missing": True}
            )
            assert resumed.status_code == 200, resumed.text
            assert resumed.json()["state"] == "optional_tools_pending"
            assert resumed.json()["blocking_reason"] is None
            assert workspace.is_dir() and list(workspace.iterdir()) == []
            finish_setup(client)
        with restarted.state.session_factory() as session:
            installation = session.scalar(select(Installation))
            assert installation.first_run_state == "ready"
            assert installation.resume_state is None
            assert installation.failure_code is None
            assert session.scalar(select(func.count(User.id))) == 1
            assert session.scalar(select(func.count(AuthorizedWorkspace.id))) == 1
            assert session.scalar(select(func.count(Task.id))) == 0
    finally:
        restarted.state.engine.dispose()


def test_expired_setup_authorization_rotates_and_preserves_current_step(tmp_path: Path) -> None:
    identity = f"install_{uuid.uuid4().hex}"
    root = tmp_path / "installation"
    settings = fresh_settings(root, installation_id=identity)
    app = create_app(settings=settings, start_scheduler=False)
    with TestClient(app) as client:
        start_owner_step(client)
        old_token = settings.setup_authorization_path.read_text(encoding="utf-8")
    with app.state.session_factory() as session:
        installation = session.scalar(select(Installation))
        assert installation is not None
        installation.setup_token_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    app.state.engine.dispose()

    restarted_settings = fresh_settings(root, installation_id=identity)
    restarted = create_app(settings=restarted_settings, start_scheduler=False)
    try:
        assert restarted_settings.setup_authorization_path.read_text(encoding="utf-8") != old_token
        with TestClient(restarted) as client:
            status = client.get("/api/setup/status").json()
            assert status["state"] == "owner_creation_pending"
            assert status["setup_authorization"]["available"] is True
    finally:
        restarted.state.engine.dispose()


def test_existing_foreign_or_legacy_database_is_never_adopted(tmp_path: Path) -> None:
    root = tmp_path / "foreign"
    settings = fresh_settings(root)
    database = settings.data_root / "twos.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE schema_versions (version TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_versions(version) VALUES ('vol19.004')")
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    before = database.read_bytes()
    with pytest.raises(first_run_module.FirstRunError) as raised:
        create_app(settings=settings, start_scheduler=False)
    assert raised.value.code == "DATABASE_INCOMPATIBLE"
    assert database.read_bytes() == before


def test_only_exact_interrupted_schema_and_registry_shape_can_resume(tmp_path: Path) -> None:
    mutations = {
        "extra-table": "CREATE TABLE unexpected_empty_table (value TEXT)",
        "schema-set": (
            "DELETE FROM schema_versions WHERE version = 'mvp14.001'; "
            "INSERT INTO schema_versions(version, applied_at) "
            "VALUES ('foreign.001', CURRENT_TIMESTAMP)"
        ),
        "registry-row": (
            "UPDATE tools SET status = 'configured' WHERE name = 'Calendar'"
        ),
    }
    for offset, (name, mutation) in enumerate(mutations.items()):
        settings = fresh_settings(tmp_path / name, port=18800 + offset)
        engine = make_engine(settings.database_url)
        initialize_database(engine, seed_default_projects=False)
        engine.dispose()
        database = settings.data_root / "twos.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript(mutation)
        before = database.read_bytes()

        with pytest.raises(first_run_module.FirstRunError) as raised:
            create_app(settings=settings, start_scheduler=False)

        assert raised.value.code == "DATABASE_INCOMPATIBLE"
        assert database.read_bytes() == before


def test_setup_private_files_reject_fifo_and_hardlink_without_side_effect(
    tmp_path: Path,
) -> None:
    linked_settings = fresh_settings(tmp_path / "linked-token", port=18810)
    outside_token = tmp_path / "outside-token.txt"
    outside_token.write_text("OWNER DATA MUST REMAIN UNCHANGED\n", encoding="utf-8")
    os.link(outside_token, linked_settings.setup_authorization_path)
    with pytest.raises(first_run_module.FirstRunError) as linked_error:
        create_app(settings=linked_settings, start_scheduler=False)
    assert linked_error.value.code == "PRIVATE_FILE_UNSAFE"
    assert outside_token.read_text(encoding="utf-8") == "OWNER DATA MUST REMAIN UNCHANGED\n"

    fifo_settings = fresh_settings(tmp_path / "fifo-token", port=18811)
    os.mkfifo(fifo_settings.setup_authorization_path)
    with pytest.raises(first_run_module.FirstRunError) as fifo_error:
        create_app(settings=fifo_settings, start_scheduler=False)
    assert fifo_error.value.code == "PRIVATE_FILE_UNSAFE"
    assert stat.S_ISFIFO(fifo_settings.setup_authorization_path.lstat().st_mode)

    consume_settings = fresh_settings(tmp_path / "consume-token", port=18812)
    consume_app = create_app(settings=consume_settings, start_scheduler=False)
    consume_app.state.engine.dispose()
    consume_settings.setup_authorization_path.unlink()
    os.mkfifo(consume_settings.setup_authorization_path)
    with pytest.raises(first_run_module.FirstRunError) as consume_error:
        first_run_module.consume_setup_authorization_file(consume_settings)
    assert consume_error.value.code == "SETUP_AUTHORIZATION_PATH_UNSAFE"
    assert stat.S_ISFIFO(consume_settings.setup_authorization_path.lstat().st_mode)


def test_installation_configuration_rejects_hardlink_without_read_or_rewrite(
    tmp_path: Path,
) -> None:
    settings = fresh_settings(tmp_path / "linked-configuration", port=18813)
    outside_configuration = tmp_path / "outside-configuration.json"
    outside_configuration.write_text('{"private_owner_value":"preserve"}\n', encoding="utf-8")
    os.link(outside_configuration, settings.installation_config_path)
    with pytest.raises(first_run_module.FirstRunError) as raised:
        create_app(settings=settings, start_scheduler=False)
    assert raised.value.code == "INSTALLATION_CONFIG_UNSAFE"
    assert outside_configuration.read_text(encoding="utf-8") == (
        '{"private_owner_value":"preserve"}\n'
    )


def test_pre_lifespan_database_failure_disposes_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = fresh_settings(tmp_path / "dispose-engine", port=18814)

    class DisposableEngine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = DisposableEngine()
    monkeypatch.setattr(app_module, "make_engine", lambda _url: engine)

    def fail_initialization(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("deterministic initialization failure")

    monkeypatch.setattr(app_module, "initialize_database", fail_initialization)
    with pytest.raises(RuntimeError, match="deterministic initialization failure"):
        create_app(settings=settings, start_scheduler=False)
    assert engine.disposed is True


def test_database_symlink_and_url_reserved_path_escape_block_before_engine_write(
    tmp_path: Path,
) -> None:
    symlink_root = tmp_path / "symlink-installation"
    symlink_settings = fresh_settings(symlink_root)
    external = tmp_path / "external.sqlite3"
    external.touch()
    (symlink_settings.data_root / "twos.sqlite3").symlink_to(external)
    with pytest.raises(first_run_module.FirstRunError) as symlink_error:
        create_app(settings=symlink_settings, start_scheduler=False)
    assert symlink_error.value.code == "DATABASE_SYMLINK_UNSAFE"
    assert external.stat().st_size == 0

    hardlink_root = tmp_path / "hardlink-installation"
    hardlink_settings = fresh_settings(hardlink_root, port=18764)
    hardlink_external = tmp_path / "hardlink-external.sqlite3"
    hardlink_external.touch()
    os.link(hardlink_external, hardlink_settings.data_root / "twos.sqlite3")
    with pytest.raises(first_run_module.FirstRunError) as hardlink_error:
        create_app(settings=hardlink_settings, start_scheduler=False)
    assert hardlink_error.value.code == "DATABASE_PATH_UNSAFE"
    assert hardlink_external.stat().st_size == 0

    reserved_root = tmp_path / "question?mark"
    reserved_settings = fresh_settings(reserved_root)
    parsed_escape = tmp_path / "question"
    with pytest.raises(first_run_module.FirstRunError) as parsed_error:
        create_app(settings=reserved_settings, start_scheduler=False)
    assert parsed_error.value.code == "DATABASE_PATH_UNSAFE"
    assert not parsed_escape.exists()

    # Read-only restart inspection must encode URI fragment characters rather
    # than accidentally opening a different path before checking its binding.
    fragment_settings = fresh_settings(tmp_path / "literal#fragment")
    fragment_app = create_app(settings=fragment_settings, start_scheduler=False)
    fragment_app.state.engine.dispose()
    fragment_restart = create_app(settings=fragment_settings, start_scheduler=False)
    fragment_restart.state.engine.dispose()


def test_separate_data_roots_have_distinct_installations_and_cookie_names(tmp_path: Path) -> None:
    first = fresh_settings(tmp_path / "one", port=18766)
    second = fresh_settings(tmp_path / "two", port=18767)
    first_app = create_app(settings=first, start_scheduler=False)
    second_app = create_app(settings=second, start_scheduler=False)
    try:
        assert first.installation_id != second.installation_id
        assert first.session_cookie_name != second.session_cookie_name
        with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
            start_owner_step(first_client)
            assert first_client.post("/api/setup/owner", json=owner_payload(first)).status_code == 201
            second_client.cookies.update(first_client.cookies)
            assert second_client.get("/api/auth/session").json()["authenticated"] is False
            start_owner_step(second_client)
            second_payload = dict(owner_payload(second), username="separate-installation-owner")
            assert second_client.post("/api/setup/owner", json=second_payload).status_code == 201
            first_client.cookies.update(second_client.cookies)
            assert first_client.get("/api/auth/session").json()["user"]["username"] == USERNAME
            assert second_client.get("/api/auth/session").json()["user"]["username"] == "separate-installation-owner"
            # Even a session placed under the other installation's cookie name
            # cannot cross the database-owned authentication boundary.
            second_token = second_client.cookies.get(second.session_cookie_name)
            first_client.cookies.clear()
            first_client.cookies.set(first.session_cookie_name, second_token)
            assert first_client.get("/api/auth/session").json()["authenticated"] is False
        with first_app.state.session_factory() as first_session, second_app.state.session_factory() as second_session:
            first_installation = first_session.scalar(select(Installation))
            second_installation = second_session.scalar(select(Installation))
            assert first_installation.public_id == first.installation_id
            assert second_installation.public_id == second.installation_id
            assert first_installation.data_root != second_installation.data_root
    finally:
        first_app.state.engine.dispose()
        second_app.state.engine.dispose()


def test_workspace_identity_replacement_blocks_restart(tmp_path: Path) -> None:
    identity = f"install_{uuid.uuid4().hex}"
    root = tmp_path / "installation"
    settings = fresh_settings(root, installation_id=identity)
    workspace = tmp_path / "workspace"
    app = create_app(settings=settings, start_scheduler=False)
    with TestClient(app) as client:
        create_owner_and_workspace(client, settings, workspace)
    app.state.engine.dispose()
    workspace.rmdir()
    workspace.mkdir()

    restarted_settings = fresh_settings(root, installation_id=identity)
    with pytest.raises(first_run_module.FirstRunError) as raised:
        create_app(settings=restarted_settings, start_scheduler=False)
    assert raised.value.code == "WORKSPACE_IDENTITY_CHANGED"


def test_ready_state_without_required_lineage_never_opens_normal_api(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with app.state.session_factory() as session:
            installation = session.scalar(select(Installation))
            installation.first_run_state = "ready"
            installation.completed_at = utc_now()
            session.commit()
        with TestClient(app) as client:
            assert client.get("/api/projects").status_code == 428
    finally:
        app.state.engine.dispose()


def test_interrupted_empty_schema_provisioning_resumes_without_adopting_data(
    tmp_path: Path,
) -> None:
    settings = fresh_settings(tmp_path)
    engine = make_engine(settings.database_url)
    initialize_database(engine, seed_default_projects=False)
    engine.dispose()

    app = create_app(settings=settings, start_scheduler=False)
    try:
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(Installation.id))) == 1
            assert session.scalar(select(func.count(User.id))) == 0
            assert session.scalar(select(func.count(Project.id))) == 0
            assert session.scalar(select(func.count(Task.id))) == 0
    finally:
        app.state.engine.dispose()


def test_workspace_identity_change_blocks_finish_before_ready(tmp_path: Path) -> None:
    settings = fresh_settings(tmp_path / "installation")
    workspace = tmp_path / "workspace"
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            create_owner_and_workspace(client, settings, workspace)
            workspace.rmdir()
            workspace.mkdir()
            blocked = client.post("/api/setup/optional-tools", json={"decision": "skip"})
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "WORKSPACE_IDENTITY_CHANGED"
        with app.state.session_factory() as session:
            installation = session.scalar(select(Installation))
            assert installation is not None
            assert installation.first_run_state == "failed"
            assert installation.resume_state == "optional_tools_pending"
            assert installation.completed_at is None
    finally:
        app.state.engine.dispose()


def test_committed_workspace_is_activated_even_if_config_projection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = fresh_settings(tmp_path / "installation")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = create_app(settings=settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            start_owner_step(client)
            assert client.post("/api/setup/owner", json=owner_payload(settings)).status_code == 201

            def fail_projection(*_args: object, **_kwargs: object) -> None:
                raise first_run_module.FirstRunError(
                    "INSTALLATION_CONFIG_WRITE_FAILED",
                    "The installation configuration could not be projected.",
                )

            monkeypatch.setattr("twos_runtime.app.sync_installation_configuration", fail_projection)
            failed = client.post(
                "/api/setup/workspace",
                json={"path": str(workspace), "create_if_missing": False},
            )
            assert failed.status_code == 409
            assert settings.source_repo == workspace.resolve()
            status = client.get("/api/setup/status")
            assert status.status_code == 200
            assert status.json()["state"] == "optional_tools_pending"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count(AuthorizedWorkspace.id))) == 1
    finally:
        app.state.engine.dispose()


def test_fresh_runtime_rejects_unscoped_cookie_and_newer_schema(tmp_path: Path) -> None:
    unsafe_cookie = fresh_settings(tmp_path / "cookie")
    object.__setattr__(unsafe_cookie, "session_cookie_name", "twos_session")
    with pytest.raises(first_run_module.FirstRunError) as cookie_error:
        create_app(settings=unsafe_cookie, start_scheduler=False)
    assert cookie_error.value.code == "SESSION_COOKIE_BINDING_MISMATCH"

    identity = f"install_{uuid.uuid4().hex}"
    root = tmp_path / "schema"
    settings = fresh_settings(root, installation_id=identity)
    app = create_app(settings=settings, start_scheduler=False)
    app.state.engine.dispose()
    with closing(sqlite3.connect(settings.data_root / "twos.sqlite3")) as connection, connection:
        connection.execute(
            "INSERT INTO schema_versions(version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
            ("vol100.001",),
        )
    restarted_settings = fresh_settings(root, installation_id=identity)
    with pytest.raises(first_run_module.FirstRunError) as schema_error:
        create_app(settings=restarted_settings, start_scheduler=False)
    assert schema_error.value.code == "NEWER_SCHEMA_UNSUPPORTED"


def test_first_run_schema_rejection_closes_observation_connection(tmp_path):
    from tests.test_vol19_timeout_result_projection_cleanup import sqlite_handles

    before = sqlite_handles(tmp_path)
    test_fresh_runtime_rejects_unscoped_cookie_and_newer_schema(tmp_path)
    assert sqlite_handles(tmp_path) == before
