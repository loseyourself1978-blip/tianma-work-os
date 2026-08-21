from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from tests.test_self_hosting import init_and_login, make_client, run_command
from tests.test_vol18_stage_local_commit import (
    _api_commit,
    _api_review_plan,
    _api_stage,
    verified_apply_fixture,
)
import tests.test_vol18_delivery_candidate as candidate_fixture_service
from twos_runtime.models import (
    PushExecution,
    SchemaVersion,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.security import hash_password, hash_token
import twos_runtime.push_delivery as push_delivery_service


PUSH_CONFIRMATION = "PUSH_TO_ORIGIN_MAIN"


@pytest.fixture(autouse=True)
def _clear_inherited_git_process_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


@dataclass(frozen=True)
class PushReadyFixture:
    verified: object
    plan: dict[str, object]
    stage: dict[str, object]
    commit: dict[str, object]
    origin: Path
    push_origin: Path | None
    initial_remote_sha: str

    @property
    def client(self):
        return self.verified.client

    @property
    def source_repo(self) -> Path:
        return self.verified.source_repo

    @property
    def factory(self):
        return self.verified.factory

    @property
    def owner_id(self) -> int:
        return self.verified.owner_id

    @property
    def database_path(self) -> Path:
        return self.verified.fixture.candidate.database_path


def _bare_ref(origin: Path, ref: str = "refs/heads/main") -> str:
    return run_command(
        origin.parent,
        "git",
        "--git-dir",
        str(origin),
        "rev-parse",
        ref,
    ).stdout.strip()


def _bare_refs(origin: Path) -> list[str]:
    output = run_command(
        origin.parent,
        "git",
        "--git-dir",
        str(origin),
        "for-each-ref",
        "--format=%(refname) %(objectname)",
    ).stdout
    return sorted(line for line in output.splitlines() if line)


def _local_ref(source_repo: Path, ref: str) -> str:
    return run_command(
        source_repo,
        "git",
        "rev-parse",
        ref,
    ).stdout.strip()


def _local_symref(source_repo: Path, ref: str) -> str:
    return run_command(
        source_repo,
        "git",
        "symbolic-ref",
        ref,
    ).stdout.strip()


def _copy_objects(source_repo: Path, origin: Path) -> None:
    source = source_repo / ".git" / "objects"
    destination = origin / "objects"
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


def _commit_object(
    source_repo: Path,
    *,
    parent: str,
    subject: str,
) -> str:
    tree = run_command(
        source_repo,
        "git",
        "rev-parse",
        f"{parent}^{{tree}}",
    ).stdout.strip()
    return run_command(
        source_repo,
        "git",
        "commit-tree",
        tree,
        "-p",
        parent,
        "-m",
        subject,
    ).stdout.strip()


def _set_bare_main(origin: Path, new_oid: str, old_oid: str) -> None:
    run_command(
        origin.parent,
        "git",
        "--git-dir",
        str(origin),
        "update-ref",
        "refs/heads/main",
        new_oid,
        old_oid,
    )


@contextmanager
def push_ready_fixture(
    tmp_path: Path,
    *,
    distinct_push_origin: bool = False,
):
    origin = tmp_path / "origin.git"
    push_origin = (
        tmp_path / "push-origin.git" if distinct_push_origin else None
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_command(
        tmp_path,
        "git",
        "init",
        "--bare",
        "--initial-branch=main",
        str(origin),
    )
    if push_origin is not None:
        run_command(
            tmp_path,
            "git",
            "init",
            "--bare",
            "--initial-branch=main",
            str(push_origin),
        )
    source_holder: dict[str, Path] = {}
    seeded = False
    original_make_source_repo = candidate_fixture_service.make_source_repo
    original_capture_source_snapshot = (
        candidate_fixture_service.capture_source_snapshot
    )

    def make_source_repo_with_origin(path: Path) -> Path:
        source_repo = original_make_source_repo(path)
        run_command(
            source_repo,
            "git",
            "remote",
            "add",
            "origin",
            str(origin),
        )
        if push_origin is not None:
            run_command(
                source_repo,
                "git",
                "config",
                "remote.origin.pushurl",
                str(push_origin),
            )
        source_holder["root"] = source_repo
        return source_repo

    def capture_after_direct_origin_seed(repo: Path, *args, **kwargs):
        nonlocal seeded
        source_repo = source_holder.get("root")
        if (
            source_repo is not None
            and repo.resolve() == source_repo.resolve()
            and not seeded
        ):
            remote_repositories = [origin]
            if push_origin is not None:
                remote_repositories.append(push_origin)
            head = run_command(
                source_repo, "git", "rev-parse", "HEAD"
            ).stdout.strip()
            for remote_repository in remote_repositories:
                _copy_objects(source_repo, remote_repository)
                run_command(
                    tmp_path,
                    "git",
                    "--git-dir",
                    str(remote_repository),
                    "update-ref",
                    "refs/heads/main",
                    head,
                )
            run_command(
                source_repo,
                "git",
                "update-ref",
                "refs/remotes/origin/main",
                head,
            )
            run_command(
                source_repo,
                "git",
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            )
            seeded = True
        return original_capture_source_snapshot(repo, *args, **kwargs)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            candidate_fixture_service,
            "make_source_repo",
            make_source_repo_with_origin,
        )
        monkeypatch.setattr(
            candidate_fixture_service,
            "capture_source_snapshot",
            capture_after_direct_origin_seed,
        )
        with verified_apply_fixture(tmp_path / "fixture") as verified:
            assert seeded is True
            initial_remote_sha = _bare_ref(origin)
            reviewed = _api_review_plan(verified)
            assert reviewed.status_code == 200, reviewed.text
            plan = reviewed.json()["plan"]
            staged = _api_stage(verified, plan)
            assert staged.status_code == 200, staged.text
            stage = staged.json()["stage"]
            committed = _api_commit(verified, plan, stage)
            assert committed.status_code == 200, committed.text
            commit = committed.json()["commit"]
            assert commit["state"] == "COMMITTED"
            assert commit["parent_sha"] == initial_remote_sha
            assert commit["commit_sha"] != initial_remote_sha
            assert _bare_ref(origin) == initial_remote_sha
            if push_origin is not None:
                assert _bare_ref(push_origin) == initial_remote_sha
            yield PushReadyFixture(
                verified=verified,
                plan=plan,
                stage=stage,
                commit=commit,
                origin=origin,
                push_origin=push_origin,
                initial_remote_sha=initial_remote_sha,
            )


def _review_url(fixture: PushReadyFixture) -> str:
    return f"/api/local-commits/{fixture.commit['id']}/push-delivery"


def _preflight_url(fixture: PushReadyFixture) -> str:
    return f"/api/local-commits/{fixture.commit['id']}/push-preflights"


def _confirm_url(push_execution_id: str) -> str:
    return f"/api/push-preflights/{push_execution_id}/push-attempts"


def _confirm_payload(push_execution: dict[str, object]) -> dict[str, str]:
    return {
        "confirmation": PUSH_CONFIRMATION,
        "expected_confirmation_digest": str(
            push_execution["confirmation_digest"]
        ),
    }


def test_explicit_preflight_and_confirmation_push_exact_commit_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        original_push = push_delivery_service._run_standard_push
        observed_refspecs: list[str] = []

        def counted_push(root: Path, refspec: str):
            observed_refspecs.append(refspec)
            return original_push(root, refspec)

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            counted_push,
        )
        initial_refs = _bare_refs(fixture.origin)
        initial = fixture.client.get(_review_url(fixture))
        assert initial.status_code == 200, initial.text
        initial_payload = initial.json()
        assert initial_payload["action_state"] == "READY_TO_PUSH"
        assert initial_payload["actions"] == {
            "can_push_to_origin_main": True,
            "can_confirm_push": False,
            "can_view_delivery_result": False,
        }
        assert initial_payload["readiness"]["status"] == "READY_TO_PUSH"
        assert initial_payload["readiness"]["ahead"] == 1
        assert initial_payload["readiness"]["behind"] == 0
        assert initial_payload["readiness"]["worktree_clean"] is True
        assert initial_payload["readiness"]["index_clean"] is True
        assert initial_payload["readiness"]["staged_path_count"] == 0
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0

        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        preflight_payload = preflight.json()
        push_execution = preflight_payload["push_execution"]
        assert push_execution["state"] == "READY_TO_PUSH"
        assert preflight_payload["actions"]["can_confirm_push"] is True
        assert observed_refspecs == []
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha

        confirmed = fixture.client.post(
            _confirm_url(push_execution["id"]),
            json=_confirm_payload(push_execution),
        )
        assert confirmed.status_code == 200, confirmed.text
        result = confirmed.json()
        approved = str(fixture.commit["commit_sha"])
        assert observed_refspecs == [f"{approved}:refs/heads/main"]
        assert result["action_state"] == "PUSHED"
        assert result["push_execution"]["state"] == "PUSHED"
        assert result["push_execution"]["command_attempt_count"] == 1
        assert result["delivery_result"]["complete"] is True
        assert result["delivery_result"]["status"] == "DELIVERED"
        reconciliation = result["delivery_result"]["reconciliation"]
        assert reconciliation["local_head"] == approved
        assert reconciliation["origin_main_sha"] == approved
        assert reconciliation["approved_commit_sha"] == approved
        assert reconciliation["ahead"] == 0
        assert reconciliation["behind"] == 0
        assert reconciliation["worktree_clean"] is True
        assert reconciliation["index_clean"] is True
        assert reconciliation["staged_path_count"] == 0
        assert _bare_ref(fixture.origin) == approved
        final_refs = _bare_refs(fixture.origin)
        assert [row.split(" ", 1)[0] for row in initial_refs] == [
            "refs/heads/main"
        ]
        assert [row.split(" ", 1)[0] for row in final_refs] == [
            "refs/heads/main"
        ]

        repeated = fixture.client.post(
            _confirm_url(push_execution["id"]),
            json=_confirm_payload(push_execution),
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["push_execution"]["state"] == "PUSHED"
        assert observed_refspecs == [f"{approved}:refs/heads/main"]
        assert _bare_ref(fixture.origin) == approved
        refreshed = fixture.client.get(_review_url(fixture))
        assert refreshed.status_code == 200
        assert refreshed.json()["delivery_result"]["complete"] is True
        with fixture.factory() as session:
            rows = list(session.scalars(select(PushExecution)).all())
            assert len(rows) == 1
            assert rows[0].state == "PUSHED"
            assert rows[0].command_attempt_count == 1


def test_remote_move_after_preflight_aborts_without_push_and_persists_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        push_execution = preflight.json()["push_execution"]
        approved = str(fixture.commit["commit_sha"])
        _copy_objects(fixture.source_repo, fixture.origin)
        run_command(
            fixture.origin.parent,
            "git",
            "--git-dir",
            str(fixture.origin),
            "update-ref",
            "refs/heads/main",
            approved,
            fixture.initial_remote_sha,
        )

        def forbidden_push(_root: Path, _refspec: str):
            raise AssertionError("Push must not run after live origin/main moves")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        reviewed_after_move = fixture.client.get(_review_url(fixture))
        assert reviewed_after_move.status_code == 200, reviewed_after_move.text
        reviewed_payload = reviewed_after_move.json()
        assert reviewed_payload["action_state"] == "REMOTE_MOVED"
        assert reviewed_payload["actions"]["can_confirm_push"] is False
        assert reviewed_payload["readiness"]["status"] == "PUSH_BLOCKED"
        response = fixture.client.post(
            _confirm_url(push_execution["id"]),
            json=_confirm_payload(push_execution),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["command_attempt_count"] == 0
        assert payload["actions"]["can_confirm_push"] is False
        assert payload["actions"]["can_view_delivery_result"] is True
        assert payload["delivery_result"]["complete"] is False
        assert any(
            item["code"] == "REMOTE_MOVED"
            for item in payload["push_execution"]["blockers"]
        )
        repeated = fixture.client.post(
            _confirm_url(push_execution["id"]),
            json=_confirm_payload(push_execution),
        )
        assert repeated.status_code == 200
        assert repeated.json()["push_execution"]["state"] == "REMOTE_MOVED"
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.state == "REMOTE_MOVED"
            assert row.command_attempt_count == 0


def test_push_endpoints_require_auth_and_cross_owner_is_nondisclosing(
    tmp_path: Path,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200
        push_execution = preflight.json()["push_execution"]
        fixture.client.cookies.clear()
        assert fixture.client.get(_review_url(fixture)).status_code == 401
        assert fixture.client.post(_preflight_url(fixture)).status_code == 401
        assert fixture.client.post(
            _confirm_url(push_execution["id"]),
            json=_confirm_payload(push_execution),
        ).status_code == 401

        raw_token = "phase18-4b-second-owner-token"
        password_hash, password_salt = hash_password("second-owner-password")
        with fixture.factory() as session:
            second_owner = User(
                username="phase18-4b-second-owner",
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
        headers = {"Authorization": f"Bearer {raw_token}"}
        missing_commit = "commit_" + "0" * 40
        missing_push = "push_" + "0" * 40
        pairs = (
            (
                fixture.client.get(_review_url(fixture), headers=headers),
                fixture.client.get(
                    f"/api/local-commits/{missing_commit}/push-delivery",
                    headers=headers,
                ),
            ),
            (
                fixture.client.post(_preflight_url(fixture), headers=headers),
                fixture.client.post(
                    f"/api/local-commits/{missing_commit}/push-preflights",
                    headers=headers,
                ),
            ),
            (
                fixture.client.post(
                    _confirm_url(push_execution["id"]),
                    json=_confirm_payload(push_execution),
                    headers=headers,
                ),
                fixture.client.post(
                    _confirm_url(missing_push),
                    json=_confirm_payload(push_execution),
                    headers=headers,
                ),
            ),
        )
        for wrong_owner, absent in pairs:
            assert wrong_owner.status_code == absent.status_code == 404
            wrong = wrong_owner.json()
            missing = absent.json()
            wrong.pop("request_id", None)
            missing.pop("request_id", None)
            if isinstance(wrong.get("error"), dict):
                wrong["error"].pop("request_id", None)
            if isinstance(missing.get("error"), dict):
                missing["error"].pop("request_id", None)
            assert wrong == missing


def test_exact_push_command_has_no_forbidden_delivery_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = "a" * 40
    command = push_delivery_service._command_evidence(approved)
    assert command["safe_argv"] == [
        "push",
        "--porcelain",
        "--no-follow-tags",
        "--recurse-submodules=no",
        "--",
        "origin",
        f"{approved}:refs/heads/main",
    ]
    assert command["refspec_count"] == 1
    assert command["full_argv"] == push_delivery_service._transport_command(
        *command["safe_argv"]
    )
    for hardened_pair in (
        ["-c", "remote.origin.mirror=false"],
        ["-c", "push.pushOption="],
        ["-c", "push.negotiate=false"],
        ["-c", "push.useForceIfIncludes=false"],
    ):
        offset = next(
            index
            for index in range(len(command["full_argv"]) - 1)
            if command["full_argv"][index : index + 2] == hardened_pair
        )
        assert offset > 0
    for key in (
        "force",
        "force_with_lease",
        "mirror",
        "all",
        "tags",
        "follow_tags",
        "set_upstream",
        "recurse_submodules",
        "automatic_retry",
        "fetch",
        "pull",
        "merge",
        "rebase",
        "remote_mutation",
    ):
        assert command[key] is False
    argv = json.dumps(command["safe_argv"])
    for forbidden in (
        "--force",
        "--force-with-lease",
        "--mirror",
        "--all",
        "--tags",
        "--follow-tags",
        "--set-upstream",
    ):
        assert forbidden not in argv

    calls: list[list[str]] = []

    def capture_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(push_delivery_service.subprocess, "run", capture_run)
    result = push_delivery_service._run_standard_push(
        Path("/private/tmp/unused-disposable-repository"),
        str(command["refspec"]),
    )
    assert result.returncode == 0
    assert calls == [command["full_argv"]]


def test_vol18_009_schema_and_terminal_push_record_are_immutable(
    tmp_path: Path,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        result = fixture.client.post(
            _confirm_url(preflight["id"]),
            json=_confirm_payload(preflight),
        )
        assert result.status_code == 200, result.text
        engine = fixture.client.app.state.engine
        with fixture.factory() as session:
            assert "vol18.009" in set(
                session.scalars(select(SchemaVersion.version)).all()
            )
            row = session.scalar(select(PushExecution))
            assert row is not None and row.state == "PUSHED"
            row.failure_category = "tampered"
            with pytest.raises(RuntimeError, match="immutable"):
                session.commit()
            session.rollback()
        with engine.begin() as connection:
            with pytest.raises(Exception, match="immutable"):
                connection.execute(
                    text(
                        "UPDATE push_executions SET failure_category='tampered' "
                        "WHERE push_execution_id=:push_id"
                    ),
                    {"push_id": preflight["id"]},
                )


def test_client_supplied_push_truth_is_rejected_before_state_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        transport_calls: list[str] = []

        def forbidden_push(_root: Path, refspec: str):
            transport_calls.append(refspec)
            raise AssertionError("Invalid request material must not reach Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        injected = fixture.client.post(
            _preflight_url(fixture),
            json={
                "commit_sha": "f" * 40,
                "remote_url": "https://token@example.test/private.git",
                "branch": "another",
                "refspec": "refs/heads/another",
            },
        )
        assert injected.status_code == 422, injected.text
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 0

        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        push_execution = preflight.json()["push_execution"]
        confirmation = _confirm_payload(push_execution)
        confirmation.update(
            {
                "commit_sha": "e" * 40,
                "remote_url": "file:///private/secret.git",
                "branch": "another",
                "refspec": "refs/heads/another",
            }
        )
        rejected = fixture.client.post(
            _confirm_url(str(push_execution["id"])),
            json=confirmation,
        )
        assert rejected.status_code == 422, rejected.text
        assert transport_calls == []
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.state == "READY_TO_PUSH"
            assert row.command_attempt_count == 0


@pytest.mark.parametrize("remote_reconciled", [True, False])
def test_pushing_restart_recovery_only_reconciles_and_never_retries_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_reconciled: bool,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        push_execution = preflight.json()["push_execution"]
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            row.state = "PUSHING"
            row.command_attempt_count = 1
            row.command_started_at = utc_now()
            row.execution_remote_base_oid = fixture.initial_remote_sha
            session.commit()
        if remote_reconciled:
            _copy_objects(fixture.source_repo, fixture.origin)
            _set_bare_main(
                fixture.origin,
                str(fixture.commit["commit_sha"]),
                fixture.initial_remote_sha,
            )

        transport_calls: list[str] = []

        def forbidden_retry(_root: Path, refspec: str):
            transport_calls.append(refspec)
            raise AssertionError("PUSHING recovery must never retry Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_retry,
        )
        settings = fixture.client.app.state.settings
        with make_client(
            tmp_path / "restarted-app",
            fixture.source_repo,
            Path(settings.codex_executable),
            database_path=fixture.database_path,
            codex_model_identifier=settings.codex_model_identifier,
            codex_model_capabilities=settings.codex_model_capabilities,
        ) as restarted:
            init_and_login(restarted)
            before = restarted.get(_review_url(fixture))
            assert before.status_code == 200, before.text
            assert before.json()["action_state"] == "PUSHING"
            recovered = restarted.post(
                _confirm_url(str(push_execution["id"])),
                json=_confirm_payload(push_execution),
            )
            assert recovered.status_code == 200, recovered.text
            expected = "PUSHED" if remote_reconciled else "PUSHING"
            payload = recovered.json()
            assert payload["action_state"] == expected
            assert payload["push_execution"]["state"] == expected
            assert payload["push_execution"]["command_attempt_count"] == 1
            assert payload["delivery_result"]["complete"] is remote_reconciled
            assert payload["actions"]["can_confirm_push"] is (not remote_reconciled)
            if not remote_reconciled:
                assert payload["delivery_result"]["reconciliation"]["ahead"] == 1
                assert payload["delivery_result"]["reconciliation"]["behind"] == 0
            repeated = restarted.post(
                _confirm_url(str(push_execution["id"])),
                json=_confirm_payload(push_execution),
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["push_execution"]["state"] == expected
        assert transport_calls == []
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.state == expected
            assert row.command_attempt_count == 1


def test_failed_push_is_terminal_redacted_viewable_and_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        calls: list[str] = []

        def failed_push(_root: Path, refspec: str):
            calls.append(refspec)
            return subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"https://owner:secret-token@example.test/private.git",
                stderr=b"Permission denied: secret-token",
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            failed_push,
        )
        failed = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert failed.status_code == 200, failed.text
        payload = failed.json()
        assert payload["action_state"] == "PUSH_FAILED"
        assert payload["actions"]["can_view_delivery_result"] is True
        assert payload["delivery_result"]["complete"] is False
        assert payload["delivery_result"]["status"] == "NOT_DELIVERED"
        serialized = json.dumps(payload)
        assert "secret-token" not in serialized
        assert "owner:" not in serialized
        assert calls == [
            f"{fixture.commit['commit_sha']}:refs/heads/main"
        ]
        repeated = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["action_state"] == "PUSH_FAILED"
        assert len(calls) == 1
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha


def test_timeout_remains_pushing_and_explicit_recovery_never_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        calls: list[str] = []

        def timed_out(_root: Path, refspec: str):
            calls.append(refspec)
            raise push_delivery_service.PushDeliveryError(
                "REMOTE_TIMEOUT",
                "The remote Git operation timed out.",
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            timed_out,
        )
        response = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "PUSHING"
        assert payload["push_execution"]["command_attempt_count"] == 1
        assert payload["actions"]["can_confirm_push"] is True
        assert payload["delivery_result"]["next_action"] == (
            "Review Push reconciliation before any new action."
        )
        recovered = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["action_state"] == "PUSHING"
        assert len(calls) == 1
        same_preflight = fixture.client.post(_preflight_url(fixture))
        assert same_preflight.status_code == 200, same_preflight.text
        assert same_preflight.json()["push_execution"]["id"] == preflight["id"]
        assert len(calls) == 1
        with fixture.factory() as session:
            rows = list(session.scalars(select(PushExecution)).all())
            assert len(rows) == 1
            assert rows[0].state == "PUSHING"
            assert rows[0].command_attempt_count == 1


def test_remote_move_during_transport_is_truthful_and_no_second_attempt_occurs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        competing = _commit_object(
            fixture.source_repo,
            parent=fixture.initial_remote_sha,
            subject="Competing remote commit",
        )
        _copy_objects(fixture.source_repo, fixture.origin)
        calls: list[str] = []

        def remotely_rejected(_root: Path, refspec: str):
            calls.append(refspec)
            _set_bare_main(
                fixture.origin,
                competing,
                fixture.initial_remote_sha,
            )
            return subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"",
                stderr=b"rejected (fetch first)",
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            remotely_rejected,
        )
        response = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["command_attempt_count"] == 1
        assert payload["actions"]["can_view_delivery_result"] is True
        assert payload["delivery_result"]["complete"] is False
        assert _bare_ref(fixture.origin) == competing
        repeated = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert repeated.status_code == 200
        assert len(calls) == 1


def test_remote_moved_before_preflight_records_terminal_block_without_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        competing = _commit_object(
            fixture.source_repo,
            parent=fixture.initial_remote_sha,
            subject="Remote moved before preflight",
        )
        _copy_objects(fixture.source_repo, fixture.origin)
        _set_bare_main(fixture.origin, competing, fixture.initial_remote_sha)

        def forbidden_push(_root: Path, _refspec: str):
            raise AssertionError("A REMOTE_MOVED preflight cannot Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        response = fixture.client.post(_preflight_url(fixture))
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["state"] == "REMOTE_MOVED"
        assert payload["push_execution"]["command_attempt_count"] == 0
        assert payload["actions"]["can_confirm_push"] is False
        assert payload["actions"]["can_view_delivery_result"] is True
        assert _bare_ref(fixture.origin) == competing


def test_get_and_delivery_result_review_never_invoke_push_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        def forbidden_push(_root: Path, _refspec: str):
            raise AssertionError("Read-only review must not Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        before = fixture.client.get(_review_url(fixture))
        assert before.status_code == 200, before.text
        assert before.json()["actions"]["can_push_to_origin_main"] is True
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        after = fixture.client.get(_review_url(fixture))
        assert after.status_code == 200, after.text
        assert after.json()["push_execution"]["state"] == "READY_TO_PUSH"
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha


def test_ready_confirmation_is_disabled_when_fresh_local_blocker_appears(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        (fixture.source_repo / "modify.txt").write_text(
            "changed after confirmation review\n",
            encoding="utf-8",
        )

        def forbidden_push(_root: Path, _refspec: str):
            raise AssertionError("Fresh blocker must prevent Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        reviewed = fixture.client.get(_review_url(fixture))
        assert reviewed.status_code == 200, reviewed.text
        payload = reviewed.json()
        assert payload["action_state"] == "PUSH_BLOCKED"
        assert payload["actions"]["can_confirm_push"] is False
        assert payload["readiness"]["status"] == "PUSH_BLOCKED"
        assert payload["delivery_result"]["next_action"] == (
            "The working tree is not clean."
        )
        confirmed = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["push_execution"]["state"] == "PUSH_BLOCKED"
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha


def test_invalid_live_remote_response_is_safe_blocker_not_type_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        def invalid_remote(*_args, **_kwargs):
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"not-an-oid\trefs/heads/main\n",
                stderr=b"secret remote diagnostic",
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_run_transport",
            invalid_remote,
        )
        review = fixture.client.get(_review_url(fixture))
        assert review.status_code == 200, review.text
        payload = review.json()
        assert payload["action_state"] == "PUSH_BLOCKED"
        assert payload["readiness"]["blockers"] == [
            {
                "code": "REMOTE_EVIDENCE_INVALID",
                "message": "The live origin/main response is invalid.",
            }
        ]
        assert "secret remote diagnostic" not in json.dumps(payload)
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 409, preflight.text
        assert "TypeError" not in preflight.text
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 0


def test_remote_display_redacts_credentials_path_and_query() -> None:
    display = push_delivery_service._safe_remote_display(
        b"https://owner:token@example.test/private/token/repository.git?key=secret"
    )
    assert display == "https://example.test/[redacted path]"
    for secret in ("owner", "token", "private", "repository", "key", "secret"):
        assert secret not in display


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("wrong_branch", "WRONG_BRANCH"),
        ("head_changed_extra_commit", "HEAD_CHANGED"),
        ("dirty_worktree", "WORKTREE_DIRTY"),
        ("staged_index", "INDEX_DIRTY"),
        ("remote_url_changed", "REMOTE_URL_CHANGED"),
    ],
)
def test_local_push_blockers_are_detected_before_any_live_remote_contact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        approved = str(fixture.commit["commit_sha"])
        if case == "wrong_branch":
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/heads/not-main",
                approved,
            )
            run_command(
                fixture.source_repo,
                "git",
                "symbolic-ref",
                "HEAD",
                "refs/heads/not-main",
            )
        elif case == "head_changed_extra_commit":
            extra = _commit_object(
                fixture.source_repo,
                parent=approved,
                subject="Unexpected extra local commit",
            )
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/heads/main",
                extra,
                approved,
            )
        elif case == "dirty_worktree":
            (fixture.source_repo / "modify.txt").write_text(
                "unapproved working tree mutation\n",
                encoding="utf-8",
            )
        elif case == "staged_index":
            (fixture.source_repo / "modify.txt").write_text(
                "unapproved staged mutation\n",
                encoding="utf-8",
            )
            run_command(
                fixture.source_repo,
                "git",
                "add",
                "--",
                "modify.txt",
            )
        elif case == "remote_url_changed":
            other_origin = tmp_path / "other-origin.git"
            run_command(
                tmp_path,
                "git",
                "init",
                "--bare",
                "--initial-branch=main",
                str(other_origin),
            )
            _copy_objects(fixture.source_repo, other_origin)
            run_command(
                tmp_path,
                "git",
                "--git-dir",
                str(other_origin),
                "update-ref",
                "refs/heads/main",
                fixture.initial_remote_sha,
            )
            run_command(
                fixture.source_repo,
                "git",
                "remote",
                "set-url",
                "origin",
                str(other_origin),
            )
        else:  # pragma: no cover - the parametrization is closed above
            raise AssertionError(case)

        live_calls: list[Path] = []

        def forbidden_live_remote(root: Path) -> str:
            live_calls.append(root)
            raise AssertionError(
                "Local blockers must be resolved before contacting origin"
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            forbidden_live_remote,
        )
        response = fixture.client.post(_preflight_url(fixture))
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "PUSH_BLOCKED"
        assert payload["push_execution"]["state"] == "PUSH_BLOCKED"
        assert payload["push_execution"]["command_attempt_count"] == 0
        assert payload["actions"]["can_confirm_push"] is False
        codes = {
            blocker["code"]
            for blocker in payload["push_execution"]["blockers"]
        }
        assert expected_code in codes
        assert live_calls == []
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha


@pytest.mark.parametrize("url_kind", ["fetch", "push"])
def test_multiple_origin_urls_block_before_live_remote_and_create_no_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    url_kind: str,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        key = (
            "remote.origin.url"
            if url_kind == "fetch"
            else "remote.origin.pushurl"
        )
        additions = 1 if url_kind == "fetch" else 2
        for ordinal in range(additions):
            run_command(
                fixture.source_repo,
                "git",
                "config",
                "--add",
                key,
                str(tmp_path / f"extra-{url_kind}-{ordinal}.git"),
            )

        def forbidden_live_remote(_root: Path) -> str:
            raise AssertionError("Unsafe remote URL cardinality must not be contacted")

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            forbidden_live_remote,
        )
        response = fixture.client.post(_preflight_url(fixture))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["details"] == {
            "code": "REMOTE_URL_UNSAFE",
            "message": "origin must resolve to one bounded remote URL.",
        }
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 0


def test_preapproved_distinct_fetch_and_push_destinations_block_without_contact_or_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(
        tmp_path,
        distinct_push_origin=True,
    ) as fixture:
        assert fixture.push_origin is not None
        live_calls: list[Path] = []
        push_calls: list[str] = []

        def forbidden_live(root: Path) -> str:
            live_calls.append(root)
            raise AssertionError("Distinct Push destination must not be contacted")

        def forbidden_push(_root: Path, refspec: str):
            push_calls.append(refspec)
            raise AssertionError("Distinct Push destination must never Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            forbidden_live,
        )
        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_push,
        )
        reviewed = fixture.client.get(_review_url(fixture))
        assert reviewed.status_code == 200, reviewed.text
        payload = reviewed.json()
        assert payload["action_state"] == "PUSH_BLOCKED"
        assert payload["actions"]["can_push_to_origin_main"] is False
        assert payload["actions"]["can_confirm_push"] is False
        assert payload["readiness"]["blockers"] == [
            {
                "code": "REMOTE_DESTINATION_MISMATCH",
                "message": "origin fetch and Push destinations do not match exactly.",
            }
        ]
        preflight = fixture.client.post(_preflight_url(fixture))
        assert preflight.status_code == 409, preflight.text
        assert preflight.json()["error"]["details"] == {
            "code": "REMOTE_DESTINATION_MISMATCH",
            "message": "origin fetch and Push destinations do not match exactly.",
        }
        assert live_calls == []
        assert push_calls == []
        assert _bare_ref(fixture.origin) == fixture.initial_remote_sha
        assert _bare_ref(fixture.push_origin) == fixture.initial_remote_sha
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 0


def test_delivery_reconciliation_never_contacts_new_distinct_push_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        pushed = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["push_execution"]["state"] == "PUSHED"
        distinct = tmp_path / "distinct-push-origin.git"
        run_command(
            tmp_path,
            "git",
            "init",
            "--bare",
            "--initial-branch=main",
            str(distinct),
        )
        run_command(
            fixture.source_repo,
            "git",
            "config",
            "remote.origin.pushurl",
            str(distinct),
        )

        def forbidden_live(_root: Path) -> str:
            raise AssertionError("Distinct Push destination must not be contacted")

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            forbidden_live,
        )
        reviewed = fixture.client.get(_review_url(fixture))
        assert reviewed.status_code == 200, reviewed.text
        payload = reviewed.json()
        assert payload["action_state"] == "RECONCILIATION_BLOCKED"
        assert payload["delivery_result"]["complete"] is False
        assert payload["delivery_result"]["reconciliation"]["blockers"] == [
            {
                "code": "REMOTE_DESTINATION_MISMATCH",
                "message": "origin fetch and Push destinations do not match exactly.",
            }
        ]
        assert _bare_refs(distinct) == []


def test_unavailable_bound_repository_blocks_without_push_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        def unavailable_repository(*_args, **_kwargs):
            raise OSError("sensitive host path is unavailable")

        monkeypatch.setattr(
            push_delivery_service,
            "_source_repository_identity",
            unavailable_repository,
        )
        response = fixture.client.post(_preflight_url(fixture))
        assert response.status_code == 409, response.text
        assert response.json()["error"]["details"] == {
            "code": "REPOSITORY_UNAVAILABLE",
            "message": "The bound repository is unavailable.",
        }
        assert "sensitive host path" not in response.text
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 0


def test_origin_tracking_main_transition_and_origin_head_symref_are_authorized(
    tmp_path: Path,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        assert _local_ref(
            fixture.source_repo, "refs/remotes/origin/main"
        ) == fixture.initial_remote_sha
        assert _local_symref(
            fixture.source_repo, "refs/remotes/origin/HEAD"
        ) == "refs/remotes/origin/main"
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        approved = str(fixture.commit["commit_sha"])
        response = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "PUSHED"
        assert payload["delivery_result"]["complete"] is True
        assert _local_ref(
            fixture.source_repo, "refs/remotes/origin/main"
        ) == approved
        assert _local_symref(
            fixture.source_repo, "refs/remotes/origin/HEAD"
        ) == "refs/remotes/origin/main"


def test_reconciliation_blocked_record_recovers_with_set_once_evidence_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        blocked_evidence = {
            "status": "RECONCILIATION_BLOCKED",
            "complete": False,
            "local_head": fixture.commit["commit_sha"],
            "origin_main_sha": fixture.initial_remote_sha,
            "approved_commit_sha": fixture.commit["commit_sha"],
            "ahead": 1,
            "behind": 0,
            "worktree_clean": True,
            "index_clean": True,
            "staged_path_count": 0,
            "blockers": [
                {
                    "code": "RECONCILIATION_BLOCKED",
                    "message": "Initial reconciliation was unavailable.",
                }
            ],
        }
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            row.state = "PUSHING"
            row.command_attempt_count = 1
            row.command_started_at = utc_now()
            row.execution_remote_base_oid = fixture.initial_remote_sha
            session.commit()
            row.state = "RECONCILIATION_BLOCKED"
            row.command_finished_at = utc_now()
            row.command_exit_code = 0
            row.failure_category = "RECONCILIATION_BLOCKED"
            row.failure_evidence_json = json.dumps(
                blocked_evidence["blockers"],
                sort_keys=True,
                separators=(",", ":"),
            )
            row.post_push_evidence_json = json.dumps(
                blocked_evidence,
                sort_keys=True,
                separators=(",", ":"),
            )
            row.finished_at = utc_now()
            session.commit()
        same_intent = fixture.client.post(_preflight_url(fixture))
        assert same_intent.status_code == 200, same_intent.text
        assert same_intent.json()["push_execution"]["id"] == preflight["id"]
        assert same_intent.json()["push_execution"]["state"] == (
            "RECONCILIATION_BLOCKED"
        )
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PushExecution)
            ) == 1
        _copy_objects(fixture.source_repo, fixture.origin)
        _set_bare_main(
            fixture.origin,
            str(fixture.commit["commit_sha"]),
            fixture.initial_remote_sha,
        )

        def forbidden_retry(_root: Path, _refspec: str):
            raise AssertionError("Reconciliation recovery cannot invoke Push")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_retry,
        )
        response = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action_state"] == "PUSHED"
        assert payload["delivery_result"]["complete"] is True
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.state == "PUSHED"
            assert json.loads(row.post_push_evidence_json) == blocked_evidence
            recovery = json.loads(row.recovery_reconciliation_json)
            assert recovery["complete"] is True
            assert row.recovery_reconciliation_digest
            assert row.recovered_at is not None
            assert row.receipt_digest


def test_exit_zero_push_persists_receipt_while_live_reconciliation_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        original_live = push_delivery_service._live_origin_main
        live_calls = 0

        def live_then_unavailable(root: Path) -> str:
            nonlocal live_calls
            live_calls += 1
            if live_calls == 1:
                return original_live(root)
            raise push_delivery_service.PushDeliveryError(
                "REMOTE_UNAVAILABLE",
                "Live origin/main is temporarily unavailable.",
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            live_then_unavailable,
        )
        response = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["push_execution"]["state"] == "PUSHED"
        assert payload["action_state"] == "RECONCILIATION_BLOCKED"
        assert payload["delivery_result"]["complete"] is False
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.state == "PUSHED"
            assert row.command_exit_code == 0
            assert row.receipt_digest

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            original_live,
        )
        reconciled = fixture.client.get(_review_url(fixture))
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["action_state"] == "PUSHED"
        assert reconciled.json()["delivery_result"]["complete"] is True


def test_delivery_review_does_not_contact_changed_remote_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        pushed = fixture.client.post(
            _confirm_url(str(preflight["id"])),
            json=_confirm_payload(preflight),
        )
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["push_execution"]["state"] == "PUSHED"
        changed_origin = tmp_path / "changed-origin.git"
        run_command(
            tmp_path,
            "git",
            "init",
            "--bare",
            "--initial-branch=main",
            str(changed_origin),
        )
        run_command(
            fixture.source_repo,
            "git",
            "remote",
            "set-url",
            "origin",
            str(changed_origin),
        )

        def forbidden_live(_root: Path) -> str:
            raise AssertionError("Changed remote config must not be contacted")

        monkeypatch.setattr(
            push_delivery_service,
            "_live_origin_main",
            forbidden_live,
        )
        review = fixture.client.get(_review_url(fixture))
        assert review.status_code == 200, review.text
        payload = review.json()
        assert payload["action_state"] == "RECONCILIATION_BLOCKED"
        assert payload["delivery_result"]["complete"] is False
        codes = {
            item["code"]
            for item in payload["delivery_result"]["reconciliation"]["blockers"]
        }
        assert "REMOTE_URL_CHANGED" in codes


def test_concurrent_double_confirmation_runs_one_transport_and_returns_safe_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_preflight_url(fixture)).json()[
            "push_execution"
        ]
        original_push = push_delivery_service._run_standard_push
        started = threading.Event()
        release = threading.Event()
        calls: list[str] = []

        def held_push(root: Path, refspec: str):
            calls.append(refspec)
            started.set()
            assert release.wait(timeout=10), "concurrent test release timed out"
            return original_push(root, refspec)

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            held_push,
        )
        second = TestClient(fixture.client.app)
        second.cookies.update(fixture.client.cookies)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                first_future = executor.submit(
                    fixture.client.post,
                    _confirm_url(str(preflight["id"])),
                    json=_confirm_payload(preflight),
                )
                assert started.wait(timeout=10), "Push transport did not start"
                concurrent = second.post(
                    _confirm_url(str(preflight["id"])),
                    json=_confirm_payload(preflight),
                )
                release.set()
                first = first_future.result(timeout=20)
        finally:
            release.set()
            second.close()
        assert first.status_code == 200, first.text
        assert first.json()["action_state"] == "PUSHED"
        assert concurrent.status_code == 409, concurrent.text
        details = concurrent.json()["error"]["details"]
        assert details["code"] in {
            "REPOSITORY_MUTATION_ACTIVE",
            "REPOSITORY_LOCK_UNAVAILABLE",
        }
        assert len(calls) == 1
        with fixture.factory() as session:
            rows = list(session.scalars(select(PushExecution)).all())
            assert len(rows) == 1
            assert rows[0].state == "PUSHED"
            assert rows[0].command_attempt_count == 1
