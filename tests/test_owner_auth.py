from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import twos_runtime.cli as owner_cli
from twos_runtime.app import SESSION_COOKIE, create_app
from twos_runtime.config import ROOT_DIR, STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings, get_settings
from twos_runtime.db import initialize_database, make_engine, make_session_factory
from twos_runtime.models import (
    AuditEvent,
    CodexInstructionPack,
    CodexRun,
    OwnerAcceptanceSession,
    Project,
    SessionToken,
    Task,
    User,
    utc_now,
)
from twos_runtime.security import HASH_ROUNDS, hash_password, hash_token


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin1234"
PADDED_USERNAME = "  admin  "
WHITESPACE_PASSWORD = "  admin1234  "
RECOVERY_PASSWORD = "replacement owner password"
STALE_SESSION_TOKEN = "test-only-stale-session-token"

ANONYMOUS_SESSION = {"authenticated": False, "user": None}
AUTHENTICATED_SESSION = {
    "authenticated": True,
    "user": {"username": ADMIN_USERNAME},
}
INVALID_CREDENTIALS = {
    "code": "INVALID_CREDENTIALS",
    "message": "Incorrect username or password.",
}
ACCOUNT_EXISTS = {
    "code": "ACCOUNT_EXISTS",
    "message": "An account already exists. Log in instead.",
}
AUTH_SERVICE_ERROR = {
    "code": "AUTH_SERVICE_ERROR",
    "message": "Something went wrong. Try again.",
}


def database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def make_app(database_path: Path) -> FastAPI:
    settings = Settings(
        database_url=database_url(database_path),
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        worktree_root=database_path.parent / "worktrees",
    )
    return create_app(settings=settings, start_scheduler=False)


def signup(client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD):
    return client.post(
        "/api/auth/signup",
        json={"username": username, "password": password},
    )


def login(client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def assert_sensitive_absent(materials: list[str | None], *surfaces: object) -> None:
    corpus = "\n".join(str(surface) for surface in surfaces)
    if any(material and material in corpus for material in materials):
        pytest.fail("sensitive authentication material leaked")


def validation_error(field: str, message: str) -> dict[str, object]:
    return {
        "code": "VALIDATION_ERROR",
        "message": "Check the highlighted fields.",
        "fields": {field: message},
    }


def test_canonical_signup_session_logout_login_refresh_and_restart(tmp_path: Path) -> None:
    """API requirements 1-8: one canonical lifecycle, including commit and restart."""
    database_path = tmp_path / "canonical-lifecycle.sqlite3"
    app = make_app(database_path)

    with TestClient(app) as client:
        fresh = client.get("/api/auth/session")
        assert fresh.status_code == 200
        assert fresh.json() == ANONYMOUS_SESSION

        created = signup(client)
        assert created.status_code == 201
        assert created.json() == AUTHENTICATED_SESSION
        assert "token" not in json.dumps(created.json()).lower()
        raw_token = client.cookies.get(SESSION_COOKIE)
        assert raw_token
        set_cookie = created.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie

        # An independent transaction can observe every record before the 201 is returned.
        with app.state.session_factory() as independent_session:
            stored_user = independent_session.scalar(select(User))
            stored_session = independent_session.scalar(select(SessionToken))
            auth_audits = independent_session.scalars(
                select(AuditEvent).where(AuditEvent.actor_user_id == stored_user.id)
            ).all() if stored_user is not None else []
            assert stored_user is not None
            assert stored_user.username == ADMIN_USERNAME
            assert stored_session is not None
            assert stored_session.revoked_at is None
            assert auth_audits

        after_signup = client.get("/api/auth/session")
        assert after_signup.status_code == 200
        assert after_signup.json() == AUTHENTICATED_SESSION
        assert client.get("/twos").status_code == 200
        assert client.get("/api/auth/session").json() == AUTHENTICATED_SESSION

        logged_out = client.post("/api/auth/logout")
        assert logged_out.status_code == 200
        assert logged_out.json() == {"success": True}
        assert client.cookies.get(SESSION_COOKIE) is None
        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION

        # A copied cookie cannot resurrect a server-revoked session.
        client.cookies.set(SESSION_COOKIE, raw_token, path="/")
        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION
        client.cookies.clear()

        logged_in = login(client)
        assert logged_in.status_code == 200
        assert logged_in.json() == AUTHENTICATED_SESSION
        restarted_token = client.cookies.get(SESSION_COOKIE)
        assert restarted_token

    app.state.engine.dispose()

    restarted_app = make_app(database_path)
    with TestClient(restarted_app) as restarted:
        restarted.cookies.set(SESSION_COOKIE, restarted_token, path="/")
        persisted_session = restarted.get("/api/auth/session")
        assert persisted_session.status_code == 200
        assert persisted_session.json() == AUTHENTICATED_SESSION
        assert restarted.post("/api/auth/logout").json() == {"success": True}
        restarted_login = login(restarted)
        assert restarted_login.status_code == 200
        assert restarted_login.json() == AUTHENTICATED_SESSION
    restarted_app.state.engine.dispose()


def test_username_normalization_matches_and_password_is_never_trimmed(tmp_path: Path) -> None:
    """API requirements 9-10: normalize only the username boundary."""
    app = make_app(tmp_path / "credential-normalization.sqlite3")
    with TestClient(app) as client:
        created = signup(client, PADDED_USERNAME, WHITESPACE_PASSWORD)
        assert created.status_code == 201
        assert created.json() == AUTHENTICATED_SESSION
        assert client.post("/api/auth/logout").status_code == 200

        transformed_password = login(client, ADMIN_USERNAME, WHITESPACE_PASSWORD.strip())
        assert transformed_password.status_code == 401
        assert transformed_password.json() == INVALID_CREDENTIALS

        exact_password = login(client, PADDED_USERNAME, WHITESPACE_PASSWORD)
        assert exact_password.status_code == 200
        assert exact_password.json() == AUTHENTICATED_SESSION
    app.state.engine.dispose()


@pytest.mark.parametrize(
    ("payload", "field", "message", "secret"),
    [
        (
            {"username": "", "password": ADMIN_PASSWORD},
            "username",
            "Enter a username.",
            ADMIN_PASSWORD,
        ),
        (
            {"username": "   ", "password": ADMIN_PASSWORD},
            "username",
            "Enter a username.",
            ADMIN_PASSWORD,
        ),
        ({"username": ADMIN_USERNAME, "password": ""}, "password", "Enter a password.", None),
        (
            {"username": ADMIN_USERNAME, "password": "seven77"},
            "password",
            "Use at least 8 characters.",
            "seven77",
        ),
    ],
)
def test_signup_validation_is_product_safe_and_field_specific(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    payload: dict[str, str],
    field: str,
    message: str,
    secret: str | None,
) -> None:
    """API requirements 11-13 and 17: no framework payload or submitted password echo."""
    app = make_app(tmp_path / f"validation-{field}-{len(payload['username'])}.sqlite3")
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        response = client.post("/api/auth/signup", json=payload)
        assert response.status_code == 400
        assert response.json() == validation_error(field, message)
        response_text = response.text
        assert "Request validation failed" not in response_text
        assert "pydantic" not in response_text.lower()
        assert "stack" not in response_text.lower()
        assert_sensitive_absent([secret], response_text, caplog.text)
        if message == "Use at least 8 characters.":
            boundary = signup(client, ADMIN_USERNAME, "12345678")
            assert boundary.status_code == 201
            assert boundary.json() == AUTHENTICATED_SESSION
    app.state.engine.dispose()


@pytest.mark.parametrize(
    ("payload", "field", "message", "secret"),
    [
        (
            {"username": "", "password": ADMIN_PASSWORD},
            "username",
            "Enter a username.",
            ADMIN_PASSWORD,
        ),
        ({"username": ADMIN_USERNAME, "password": ""}, "password", "Enter a password.", None),
    ],
)
def test_login_empty_fields_use_the_same_product_validation_contract(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    payload: dict[str, str],
    field: str,
    message: str,
    secret: str | None,
) -> None:
    app = make_app(tmp_path / f"login-validation-{field}.sqlite3")
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 400
        assert response.json() == validation_error(field, message)
        assert_sensitive_absent([secret], response.text, caplog.text)
    app.state.engine.dispose()


def test_duplicate_signup_and_credential_failures_use_exact_public_contract(tmp_path: Path) -> None:
    """API requirements 14-16: exact conflict and indistinguishable credential errors."""
    app = make_app(tmp_path / "public-errors.sqlite3")
    with TestClient(app) as client:
        assert signup(client).status_code == 201
        assert client.post("/api/auth/logout").status_code == 200

        duplicate = signup(client, "different-user", "different-password")
        assert duplicate.status_code == 409
        assert duplicate.json() == ACCOUNT_EXISTS

        wrong_password = login(client, ADMIN_USERNAME, "definitely-wrong")
        unknown_username = login(client, "unknown-user", ADMIN_PASSWORD)
        assert wrong_password.status_code == 401
        assert unknown_username.status_code == 401
        assert wrong_password.json() == INVALID_CREDENTIALS
        assert unknown_username.json() == INVALID_CREDENTIALS
        assert wrong_password.content == unknown_username.content
    app.state.engine.dispose()


def test_concurrent_signup_serializes_to_one_success_and_one_account_exists(tmp_path: Path) -> None:
    app = make_app(tmp_path / "concurrent-signup.sqlite3")
    payloads = [
        {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        {"username": "second-admin", "password": "second-admin-password"},
    ]

    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda payload: client.post("/api/auth/signup", json=payload),
                    payloads,
                )
            )

        assert sorted(response.status_code for response in responses) == [201, 409]
        conflict = next(response for response in responses if response.status_code == 409)
        assert conflict.json() == ACCOUNT_EXISTS

        with app.state.session_factory() as session:
            assert len(session.scalars(select(User)).all()) == 1
            assert len(session.scalars(select(SessionToken)).all()) == 1

    app.state.engine.dispose()


def test_password_hash_salt_and_session_values_never_leak_to_json_logs_or_audit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """API requirements 4 and 17-19: secrets stay out of product and evidence surfaces."""
    app = make_app(tmp_path / "secret-surfaces.sqlite3")
    caplog.set_level(logging.DEBUG)

    with TestClient(app) as client:
        created = signup(client)
        assert created.status_code == 201
        raw_token = client.cookies.get(SESSION_COOKIE)
        assert raw_token
        session_response = client.get("/api/auth/session")
        failed = login(client, ADMIN_USERNAME, "wrong-password-value")

        with app.state.session_factory() as session:
            owner = session.scalar(select(User))
            persisted_token = session.scalar(select(SessionToken))
            audits = session.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
            assert owner is not None
            assert persisted_token is not None
            assert owner.password_hash != ADMIN_PASSWORD
            assert owner.password_salt != ADMIN_PASSWORD
            assert persisted_token.token_hash != raw_token
            password_hash = owner.password_hash
            password_salt = owner.password_salt
            token_hash = persisted_token.token_hash
            audit_corpus = "\n".join(
                f"{event.action}|{event.entity_type}|{event.details}|{event.request_id or ''}"
                for event in audits
            )

        json_corpus = json.dumps(
            [created.json(), session_response.json(), failed.json()],
            sort_keys=True,
        )
        assert "password_hash" not in json_corpus
        assert "password_salt" not in json_corpus
        assert "token" not in json_corpus.lower()
        assert_sensitive_absent(
            [
                ADMIN_PASSWORD,
                "wrong-password-value",
                password_hash,
                password_salt,
                raw_token,
                token_hash,
            ],
            json_corpus,
            caplog.text,
            audit_corpus,
        )
    app.state.engine.dispose()


def test_authentication_request_ids_cannot_inject_secret_material_into_logs_or_audit(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = make_app(tmp_path / "request-id-injection.sqlite3")
    injected_secret = "test-only-password-cookie-token-marker"
    caplog.set_level(logging.DEBUG)

    with TestClient(app) as client:
        created = client.post(
            "/api/auth/signup",
            headers={"X-Request-ID": injected_secret},
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert created.status_code == 201

        with app.state.session_factory() as session:
            audit_request_ids = session.scalars(select(AuditEvent.request_id)).all()

        assert audit_request_ids
        assert all(value != injected_secret for value in audit_request_ids)
        assert_sensitive_absent([injected_secret], created.text, caplog.text, audit_request_ids)

    app.state.engine.dispose()


def test_signup_commit_failure_is_safe_and_cannot_persist_partial_auth_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """API requirement 20: a failed commit cannot produce a 201 or a cookie."""
    app = make_app(tmp_path / "commit-failure.sqlite3")
    caplog.set_level(logging.DEBUG)
    internal_marker = "forced authentication commit failure"

    def fail_commit(_session: Session) -> None:
        raise SQLAlchemyError(internal_marker)

    with TestClient(app) as client:
        with monkeypatch.context() as commit_patch:
            commit_patch.setattr(Session, "commit", fail_commit)
            response = signup(client)
        assert response.status_code == 500
        assert response.json() == AUTH_SERVICE_ERROR
        assert SESSION_COOKIE not in response.headers.get("set-cookie", "")

        with app.state.session_factory() as session:
            assert session.scalar(select(User)) is None
            assert session.scalar(select(SessionToken)) is None
            assert session.scalar(select(AuditEvent)) is None

        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION
        assert_sensitive_absent([ADMIN_PASSWORD, internal_marker], response.text, caplog.text)
    app.state.engine.dispose()


def test_invalid_hash_and_database_failure_use_safe_distinct_product_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """API requirement 21: malformed credentials are generic; service errors are safe."""
    database_path = tmp_path / "auth-diagnostics.sqlite3"
    app = make_app(database_path)
    unsupported_hash = "unsupported-stored-password-format"

    with TestClient(app) as client:
        assert signup(client).status_code == 201
        assert client.post("/api/auth/logout").status_code == 200
        with app.state.session_factory() as session:
            owner = session.scalar(select(User))
            assert owner is not None
            owner.password_hash = unsupported_hash
            session.commit()

        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION
        unsupported = login(client)
        assert unsupported.status_code == 401
        assert unsupported.json() == INVALID_CREDENTIALS
        assert_sensitive_absent([unsupported_hash, ADMIN_PASSWORD], unsupported.text, caplog.text)

        app_module = importlib.import_module("twos_runtime.app")
        internal_marker = "database exception detail must remain internal"

        def fail_database_read(*_args, **_kwargs):
            raise SQLAlchemyError(internal_marker)

        caplog.set_level(logging.DEBUG)
        monkeypatch.setattr(app_module, "authenticate", fail_database_read)
        database_failure = login(client)
        assert database_failure.status_code == 500
        assert database_failure.json() == AUTH_SERVICE_ERROR
        assert "database_read_failed" in caplog.text
        assert_sensitive_absent(
            [unsupported_hash, internal_marker, ADMIN_PASSWORD],
            database_failure.text,
            caplog.text,
        )
    app.state.engine.dispose()


def test_valid_legacy_owner_hash_authenticates_without_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-owner.sqlite3"
    engine = make_engine(database_url(database_path))
    initialize_database(engine)
    factory = make_session_factory(engine)

    legacy_username = "o" * 81
    legacy_password = "p" * 201
    legacy_salt = base64.urlsafe_b64encode(bytes(range(24))).decode("ascii")
    legacy_digest = hashlib.pbkdf2_hmac(
        "sha256",
        legacy_password.encode("utf-8"),
        legacy_salt.encode("ascii"),
        HASH_ROUNDS,
    )
    legacy_hash = base64.urlsafe_b64encode(legacy_digest).decode("ascii")
    with factory() as session:
        session.add(
            User(
                username=legacy_username,
                password_hash=legacy_hash,
                password_salt=legacy_salt,
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()

    app = make_app(database_path)
    with TestClient(app) as client:
        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION
        authenticated = login(client, f" {legacy_username} ", legacy_password)
        assert authenticated.status_code == 200
        assert authenticated.json() == {
            "authenticated": True,
            "user": {"username": legacy_username},
        }
        assert client.get("/api/auth/session").json() == authenticated.json()
        with app.state.session_factory() as session:
            owner = session.scalar(select(User))
            assert owner is not None
            assert owner.password_hash == legacy_hash
            assert owner.password_salt == legacy_salt
    app.state.engine.dispose()


def test_invalid_owner_requires_opt_in_local_recovery_and_preserves_product_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """API requirement 22 plus OA-001: recovery remains local, explicit, and data-preserving."""
    database_path = tmp_path / "recover-owner.sqlite3"
    url = database_url(database_path)
    engine = make_engine(url)
    initialize_database(engine)
    factory = make_session_factory(engine)
    marker = "preserve-owner-recovery-data"

    with factory() as session:
        project = session.scalar(select(Project).where(Project.key == "twos"))
        assert project is not None
        invalid_owner = User(
            username=ADMIN_USERNAME,
            password_hash="",
            password_salt="",
            is_active=True,
        )
        session.add(invalid_owner)
        session.flush()
        now = utc_now()
        stale_session = SessionToken(
            user_id=invalid_owner.id,
            token_hash=hash_token(STALE_SESSION_TOKEN),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        session.add(stale_session)
        task = Task(
            project_id=project.id,
            title=marker,
            workflow_type="product_development",
            objective=marker,
            implementation_scope=marker,
            forbidden_scope="No external execution.",
            acceptance_target=marker,
        )
        session.add(task)
        session.flush()
        pack = CodexInstructionPack(
            task_id=task.id,
            version=1,
            status="approved",
            content=marker,
            stage_summary=marker,
            key_boundaries="No merge or push.",
            acceptance_target=marker,
            source_baseline_commit="test-baseline",
        )
        session.add(pack)
        session.flush()
        run = CodexRun(
            task_id=task.id,
            pack_id=pack.id,
            status="owner_review",
            structured_result=json.dumps({"marker": marker}),
            owner_summary=marker,
        )
        session.add(run)
        session.flush()
        acceptance = OwnerAcceptanceSession(
            task_id=task.id,
            codex_run_id=run.id,
            status="owner_review",
            owner_note=marker,
            compact_sync_result=marker,
        )
        original_audit = AuditEvent(
            actor_user_id=None,
            action="preservation_marker",
            entity_type="task",
            entity_id=task.id,
            request_id=None,
            details=marker,
        )
        session.add_all([acceptance, original_audit])
        session.flush()
        session.commit()
        preserved_ids = {
            "owner": invalid_owner.id,
            "task": task.id,
            "pack": pack.id,
            "run": run.id,
            "acceptance": acceptance.id,
            "audit": original_audit.id,
            "session": stale_session.id,
        }
    engine.dispose()

    app = make_app(database_path)
    with TestClient(app) as client:
        status = client.get("/api/auth/session")
        assert status.status_code == 200
        assert status.json() == ANONYMOUS_SESSION
        blocked_signup = signup(client)
        assert blocked_signup.status_code == 409
        assert blocked_signup.json() == ACCOUNT_EXISTS
        blocked_login = login(client)
        assert blocked_login.status_code == 401
        assert blocked_login.json() == INVALID_CREDENTIALS
        unrestricted_reset = client.post(
            "/api/auth/recover",
            json={"username": ADMIN_USERNAME, "password": RECOVERY_PASSWORD},
        )
        assert unrestricted_reset.status_code == 404
    app.state.engine.dispose()

    monkeypatch.setenv("TWOS_DATABASE_URL", url)
    monkeypatch.delenv("TWOS_DATABASE_PATH", raising=False)

    def unexpected_prompt(*_args, **_kwargs):
        pytest.fail("disabled or unavailable recovery unexpectedly prompted for credentials")

    monkeypatch.setattr(owner_cli.getpass, "getpass", unexpected_prompt)
    assert owner_cli.main(["recover-owner"]) == 2

    check_engine = make_engine(url)
    check_factory = make_session_factory(check_engine)
    with check_factory() as session:
        owner_before = session.get(User, preserved_ids["owner"])
        assert owner_before is not None
        assert owner_before.password_hash == ""
        assert session.get(Task, preserved_ids["task"]) is not None
        assert session.get(CodexInstructionPack, preserved_ids["pack"]) is not None
        assert session.get(CodexRun, preserved_ids["run"]) is not None
        assert session.get(OwnerAcceptanceSession, preserved_ids["acceptance"]) is not None
        assert session.get(AuditEvent, preserved_ids["audit"]) is not None
    check_engine.dispose()

    password_answers = iter([RECOVERY_PASSWORD, RECOVERY_PASSWORD])
    monkeypatch.setattr(owner_cli.getpass, "getpass", lambda _prompt: next(password_answers))
    monkeypatch.setattr("builtins.input", unexpected_prompt)
    assert owner_cli.main(["recover-owner", "--confirm-local-recovery"]) == 0

    recovered_app = make_app(database_path)
    with TestClient(recovered_app) as client:
        client.cookies.set(SESSION_COOKIE, STALE_SESSION_TOKEN, path="/")
        assert client.get("/api/auth/session").json() == ANONYMOUS_SESSION
        recovered_login = login(client, ADMIN_USERNAME, RECOVERY_PASSWORD)
        assert recovered_login.status_code == 200
        assert recovered_login.json() == AUTHENTICATED_SESSION
    recovered_app.state.engine.dispose()

    assert owner_cli.main(["recover-owner", "--confirm-local-recovery"]) == 1
    output = capsys.readouterr()

    final_engine = make_engine(url)
    final_factory = make_session_factory(final_engine)
    with final_factory() as session:
        recovered_owner = session.get(User, preserved_ids["owner"])
        preserved_task = session.get(Task, preserved_ids["task"])
        preserved_pack = session.get(CodexInstructionPack, preserved_ids["pack"])
        preserved_run = session.get(CodexRun, preserved_ids["run"])
        preserved_acceptance = session.get(OwnerAcceptanceSession, preserved_ids["acceptance"])
        preserved_audit = session.get(AuditEvent, preserved_ids["audit"])
        recovery_audits = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "owner_recovered")
        ).all()
        stale_session = session.get(SessionToken, preserved_ids["session"])
        assert recovered_owner is not None and recovered_owner.id == preserved_ids["owner"]
        assert preserved_task is not None and preserved_task.title == marker
        assert preserved_pack is not None and preserved_pack.content == marker
        assert preserved_run is not None and preserved_run.owner_summary == marker
        assert preserved_acceptance is not None and preserved_acceptance.owner_note == marker
        assert preserved_audit is not None and preserved_audit.details == marker
        assert len(recovery_audits) == 1
        assert stale_session is not None and stale_session.revoked_at is not None
        assert recovery_audits[0].details == "Explicit local Owner credential recovery completed."
        recovery_hash = recovered_owner.password_hash
        recovery_salt = recovered_owner.password_salt
        audit_corpus = "\n".join(event.details for event in recovery_audits)
    final_engine.dispose()

    assert_sensitive_absent(
        [RECOVERY_PASSWORD, recovery_hash, recovery_salt],
        output.out,
        output.err,
        audit_corpus,
    )


def test_explicit_one_time_recovery_can_replace_an_unverifiable_current_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "unverifiable-owner.sqlite3"
    url = database_url(database_path)
    app = make_app(database_path)
    with TestClient(app) as client:
        assert signup(client).status_code == 201
    app.state.engine.dispose()

    engine = make_engine(url)
    factory = make_session_factory(engine)
    with factory() as session:
        owner = session.scalar(select(User))
        assert owner is not None
        replacement_hash, replacement_salt = hash_password("different valid test password")
        owner.password_hash = replacement_hash
        owner.password_salt = replacement_salt
        session.commit()
    engine.dispose()

    before_recovery = make_app(database_path)
    with TestClient(before_recovery) as client:
        failed = login(client)
        assert failed.status_code == 401
        assert failed.json() == INVALID_CREDENTIALS
    before_recovery.state.engine.dispose()

    monkeypatch.setenv("TWOS_DATABASE_URL", url)
    monkeypatch.delenv("TWOS_DATABASE_PATH", raising=False)
    answers = iter([RECOVERY_PASSWORD, RECOVERY_PASSWORD])
    monkeypatch.setattr(owner_cli.getpass, "getpass", lambda _prompt: next(answers))
    assert owner_cli.main(["recover-owner", "--confirm-local-recovery"]) == 0

    recovered = make_app(database_path)
    with TestClient(recovered) as client:
        authenticated = login(client, ADMIN_USERNAME, RECOVERY_PASSWORD)
        assert authenticated.status_code == 200
        assert authenticated.json() == AUTHENTICATED_SESSION
    recovered.state.engine.dispose()
    assert owner_cli.main(["recover-owner", "--confirm-local-recovery"]) == 1


def test_database_configuration_precedence_and_default_are_cwd_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path_choice = tmp_path / "path-choice.sqlite3"
    url_choice = database_url(tmp_path / "url-choice.sqlite3")
    monkeypatch.setenv("TWOS_DATABASE_PATH", str(path_choice))
    monkeypatch.setenv("TWOS_DATABASE_URL", url_choice)
    assert get_settings().database_url == url_choice

    monkeypatch.delenv("TWOS_DATABASE_URL")
    assert get_settings().database_url == database_url(path_choice)

    monkeypatch.delenv("TWOS_DATABASE_PATH")
    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    expected_default = database_url(ROOT_DIR / "twos_runtime.sqlite3")
    monkeypatch.chdir(first_cwd)
    first_default = get_settings().database_url
    monkeypatch.chdir(second_cwd)
    second_default = get_settings().database_url
    assert first_default == expected_default
    assert second_default == expected_default


class StaticContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.inputs: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, object]] = []
        self.text: list[str] = []
        self._active_script: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "input":
            self.inputs.append(attributes)
        elif tag == "link":
            self.links.append(attributes)
        elif tag == "script":
            script: dict[str, object] = {"src": attributes.get("src", ""), "body": []}
            self.scripts.append(script)
            self._active_script = script

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._active_script = None

    def handle_data(self, data: str) -> None:
        if self._active_script is not None:
            body = self._active_script["body"]
            assert isinstance(body, list)
            body.append(data)
        elif data.strip():
            self.text.append(data.strip())


def test_frontend_uses_canonical_local_assets_and_product_auth_contract() -> None:
    """Static requirements 1-10: rewritten markup, local assets, valid JS, and safe labels."""
    html = TWOS_UI_PATH.read_text(encoding="utf-8")
    css_path = TWOS_UI_PATH.parent / "styles.css"
    js_path = TWOS_UI_PATH.parent / "twos_command_center.js"
    css = css_path.read_text(encoding="utf-8")
    javascript = js_path.read_text(encoding="utf-8")
    corpus = "\n".join([html, css, javascript])

    assert "https://" not in corpus
    assert "http://" not in corpus
    assert "//cdn." not in corpus.lower()

    for obsolete_copy in (
        "Create Owner Account",
        "Owner Login",
        "Owner bootstrap",
        "Setup Owner",
        "Recovery mode",
        "Bootstrap complete",
        "Request validation failed",
        "Invalid username or password",
    ):
        assert obsolete_copy not in corpus

    parser = StaticContractParser()
    parser.feed(html)
    parser.close()
    assert len(parser.ids) == len(set(parser.ids))

    visible_text = " ".join(parser.text)
    assert "Log in" in visible_text
    assert "Sign up" in visible_text
    assert "Create your account" in visible_text
    assert "Welcome back" in visible_text

    username_inputs = [item for item in parser.inputs if item.get("name") == "username"]
    password_inputs = [item for item in parser.inputs if item.get("name") == "password"]
    assert len(username_inputs) >= 2
    assert all(item.get("autocomplete") == "username" for item in username_inputs)
    assert all(item.get("autocapitalize") == "none" for item in username_inputs)
    assert all(item.get("spellcheck") == "false" for item in username_inputs)
    assert {item.get("autocomplete") for item in password_inputs} >= {
        "new-password",
        "current-password",
    }
    assert all(item.get("type") == "password" for item in password_inputs)

    stylesheet_refs = [
        item.get("href", "")
        for item in parser.links
        if "stylesheet" in item.get("rel", "").lower()
    ]
    script_refs = [str(item["src"]) for item in parser.scripts if item["src"]]
    assert any(Path(urlsplit(ref).path).name == "styles.css" for ref in stylesheet_refs)
    assert any(Path(urlsplit(ref).path).name == "twos_command_center.js" for ref in script_refs)

    for asset_ref in stylesheet_refs + script_refs:
        parsed = urlsplit(asset_ref)
        assert not parsed.scheme
        assert not parsed.netloc
        assert not asset_ref.startswith("//")
    assert all(str(item["src"]) for item in parser.scripts)
    assert all(not "".join(item["body"]).strip() for item in parser.scripts)

    checked = subprocess.run(
        ["node", "--check", str(js_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr

    for route in (
        "/api/auth/session",
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/logout",
    ):
        assert route in javascript
    for legacy_route in ("/api/auth/status", "/api/auth/init", "/api/auth/me"):
        assert legacy_route not in javascript
    for state in ("loading", "signed_out", "signing_up", "logging_in", "signed_in", "error"):
        assert state in javascript
    assert "alert(" not in javascript
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert "probeAmbiguousSignupSession" in javascript
    assert "authenticatedUserFromPayload" in javascript
    assert "completeSignedInTransition" in javascript
    assert '[400, 409].indexOf(error.status)' in javascript
    assert '["network", "payload"].indexOf(error.category)' in javascript
    assert 'mode === "login" && error.code === "INVALID_CREDENTIALS"' in javascript
    assert "Multi-Model Orchestration Workbench" in visible_text
    assert "Model assignments" in visible_text
    assert "Model execution evidence" in visible_text
    for column in ("Capability", "Assigned model", "Responsibility", "Readiness", "Real / Simulated"):
        assert column in javascript
    assert "actual_invoked_model_identifier" in javascript
    verified_body = javascript.split("function verifiedRealInvocation(evidence)", 1)[1].split(
        "function actualInvocationDisplayName", 1
    )[0]
    assert "actualIdentifier" in verified_body
    assert "record.verified_real_invocation === true" in verified_body
    assert 'row.verifiedReal ? "Ran with " : "Assigned to "' not in javascript
    assert javascript.count("detection.execution_ready === true") >= 2
    assert 'api("/api/tasks/" + task.id + "/run-eligibility")' in javascript
    assert "const eligibility = effectiveRunEligibility();" in javascript
    assert "elements.runCodex.disabled = !authenticated" in javascript
    assert "eligibility.eligible !== true" in javascript

    recompose_body = javascript.split("async function recomposeTeam()", 1)[1].split(
        "async function generatePack()", 1
    )[0]
    run_body = javascript.split("async function runCodex()", 1)[1].split(
        "async function cancelCodex()", 1
    )[0]
    assert (
        'return "AI Team recomposed. Approval is preserved only when the routing snapshot is unchanged.";'
        in recompose_body
    )
    assert 'return "Codex run queued. TWOS will verify the isolated worktree before process launch.";' in run_body
    assert '"Checking eligibility…"' in run_body
    assert '"Starting…"' not in run_body
    assert "invoked" not in recompose_body.lower()
    assert "ran with" not in recompose_body.lower()
    assert "codex run started" not in run_body.lower()
    assert "codex is running" not in run_body.lower()
    assert 'manageCodex: byId("manage-codex")' in javascript
    assert "const hasPersistedRun = Boolean(run);" in javascript
    assert 'resultUnexpectedFiles: byId("result-unexpected-files")' in javascript
    assert 'resultDiffEvidence: byId("result-diff-evidence")' in javascript
    assert "content withheld" in javascript
    assert "Same model, separate verification invocation" in javascript
    assert "innerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
