from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from scripts.vol18_4a_owner_acceptance_app import (
    BASELINE_FILES,
    POSTIMAGES,
    AcceptanceFixtureError,
    bind_fixture_to_owner,
    sanitize_acceptance_process_environment,
    seed_unbound_acceptance_fixture,
)
from twos_runtime.app import create_app as create_product_app
from twos_runtime.config import Settings, get_settings
from twos_runtime.models import (
    ApplyPlan,
    ApplyPlanEntry,
    ApplySession,
    ApplySessionAudit,
    ApplySessionEntry,
    CodexInstructionPack,
    CodexResultArtifact,
    CodexResultEnvelope,
    CodexRunMonitor,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    OwnerAcceptanceSession,
    PostApplyVerification,
    SourceDriftEvaluation,
    StageExecution,
    Task,
    User,
)


TASK_TITLE = "[18.4B] Local commit ready for Push to origin/main"
SHADOW_OWNER_USERNAME = "phase18-4b-history-owner"
SHADOW_OWNER_PASSWORD = "phase18-4b-history-owner-password"
COMMIT_SUBJECT = "Apply verified Phase 18 fixture changes"
COMMIT_BODY = "Create one local commit from the exact verified Apply result."
STAGE_CONFIRMATION = "STAGE_APPROVED_FILES"
COMMIT_CONFIRMATION = "CREATE_LOCAL_COMMIT"


_HISTORY_MODELS = (
    CodexRunMonitor,
    CodexResultEnvelope,
    CodexResultArtifact,
    DeliveryCandidate,
    SourceDriftEvaluation,
    ApplyPlan,
    ApplyPlanEntry,
    ApplySession,
    ApplySessionEntry,
    ApplySessionAudit,
    PostApplyVerification,
    CommitPlan,
    StageExecution,
    LocalCommitExecution,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "PAGER": "cat",
            "LC_ALL": "C",
        }
    )
    return environment


def _run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgSign=false",
            *arguments,
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=_git_environment(),
        timeout=60,
    )
    if result.returncode != 0:
        raise AcceptanceFixtureError(
            result.stderr.strip() or "Fixture Git command failed."
        )
    return result.stdout.strip()


def _run_bare(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "--git-dir",
            str(repository),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        cwd=repository.parent,
        capture_output=True,
        text=True,
        check=False,
        env=_git_environment(),
        timeout=60,
    )
    if result.returncode != 0:
        raise AcceptanceFixtureError(
            result.stderr.strip() or "Fixture bare Git command failed."
        )
    return result.stdout.strip()


def _sqlite_database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise AcceptanceFixtureError(
            "The Phase 18.4B acceptance fixture requires a SQLite database."
        )
    raw = database_url[len(prefix) :]
    if not raw or raw == ":memory:":
        raise AcceptanceFixtureError(
            "The Phase 18.4B acceptance fixture requires a durable SQLite file."
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _history_database_path(database_path: Path) -> Path:
    return database_path.with_name(database_path.name + ".phase18-4b-history")


def _origin_path(source_repo: Path) -> Path:
    return source_repo.parent / "origin.git"


def _status_lines(repository: Path) -> list[str]:
    output = _run_git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    return [line for line in output.splitlines() if line]


def _staged_paths(repository: Path) -> list[str]:
    output = _run_git(repository, "diff", "--cached", "--name-only", "-z")
    return [item for item in output.split("\0") if item]


def _remote_urls(repository: Path, *, push: bool) -> list[str]:
    arguments = ["remote", "get-url", "--all"]
    if push:
        arguments.append("--push")
    arguments.append("origin")
    output = _run_git(repository, *arguments)
    return [line for line in output.splitlines() if line]


def _assert_exact_local_origin(source_repo: Path, origin: Path) -> None:
    names = [line for line in _run_git(source_repo, "remote").splitlines() if line]
    expected = str(origin.resolve(strict=True))
    if names != ["origin"]:
        raise AcceptanceFixtureError(
            "The acceptance source repository must have exactly one origin remote."
        )
    if _remote_urls(source_repo, push=False) != [expected]:
        raise AcceptanceFixtureError(
            "The acceptance origin fetch URL is not the exact local bare repository."
        )
    if _remote_urls(source_repo, push=True) != [expected]:
        raise AcceptanceFixtureError(
            "The acceptance origin push URL is not the exact local bare repository."
        )
    if _run_bare(origin, "rev-parse", "--is-bare-repository") != "true":
        raise AcceptanceFixtureError("The acceptance origin is not a bare repository.")


def _construct_local_origin_without_transport(
    source_repo: Path,
    origin: Path,
    parent_oid: str,
) -> None:
    if origin.exists():
        raise AcceptanceFixtureError(
            "The local acceptance origin already exists without completed fixture evidence."
        )
    origin.mkdir(parents=True, mode=0o700)
    _run_git(origin, "init", "--bare", "-b", "main")
    # Copy the already-created baseline object database directly.  The bare
    # main ref is then installed with update-ref; fixture preparation performs
    # no Git transport operation.
    shutil.copytree(
        source_repo / ".git" / "objects",
        origin / "objects",
        dirs_exist_ok=True,
        symlinks=False,
    )
    _run_bare(origin, "update-ref", "refs/heads/main", parent_oid)
    _run_git(source_repo, "remote", "add", "origin", str(origin.resolve()))
    _run_git(
        source_repo,
        "update-ref",
        "refs/remotes/origin/main",
        parent_oid,
    )
    _assert_exact_local_origin(source_repo, origin)


def _prepare_repository(
    source_repo: Path,
    worktree_root: Path,
    *,
    history_exists: bool,
) -> tuple[Path, Path, str]:
    source_repo.mkdir(parents=True, exist_ok=True)
    if not (source_repo / ".git").exists():
        if history_exists:
            raise AcceptanceFixtureError(
                "The completed acceptance history exists without its repository."
            )
        _run_git(source_repo, "init", "-b", "main")
        _run_git(
            source_repo,
            "config",
            "user.email",
            "twos-acceptance@example.invalid",
        )
        _run_git(source_repo, "config", "user.name", "TWOS Acceptance")
        for relative, payload in BASELINE_FILES.items():
            (source_repo / relative).write_bytes(payload)
        (source_repo / "README.md").write_text(
            "# TWOS Phase 18.4B acceptance fixture\n",
            encoding="utf-8",
        )
        _run_git(source_repo, "add", "README.md", *sorted(BASELINE_FILES))
        _run_git(source_repo, "commit", "-m", "phase 18.4B acceptance baseline")

    if _run_git(source_repo, "branch", "--show-current") != "main":
        raise AcceptanceFixtureError("The acceptance source branch must remain main.")
    if _status_lines(source_repo):
        raise AcceptanceFixtureError("The acceptance source repository must be clean.")
    if _staged_paths(source_repo):
        raise AcceptanceFixtureError("The acceptance source index must be clean.")

    origin = _origin_path(source_repo)
    remote_names = [
        line for line in _run_git(source_repo, "remote").splitlines() if line
    ]
    if not remote_names:
        if history_exists:
            raise AcceptanceFixtureError(
                "The completed acceptance history exists without its origin."
            )
        parent_oid = _run_git(source_repo, "rev-parse", "HEAD")
        _construct_local_origin_without_transport(source_repo, origin, parent_oid)
    else:
        _assert_exact_local_origin(source_repo, origin)
        parent_oid = _run_bare(origin, "rev-parse", "refs/heads/main")

    worktree_root.mkdir(parents=True, exist_ok=True)
    retained = worktree_root / "retained-run-worktree"
    if not retained.exists():
        if history_exists:
            raise AcceptanceFixtureError(
                "The completed acceptance history exists without retained Run evidence."
            )
        _run_git(
            source_repo,
            "worktree",
            "add",
            "--detach",
            str(retained),
            parent_oid,
        )
        (retained / "delete.txt").unlink()
        for relative, payload in POSTIMAGES.items():
            (retained / relative).write_bytes(payload)
    retained_status = {line.lstrip() for line in _status_lines(retained)}
    if retained_status != {"D delete.txt", "M modify.txt", "?? created.txt"}:
        raise AcceptanceFixtureError(
            "The retained Run material is not the exact three-path fixture."
        )
    return retained, origin, parent_oid


def _backup_sqlite(source: Path, destination: Path) -> None:
    if destination.exists():
        raise AcceptanceFixtureError(
            "The immutable acceptance history template already exists."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
            integrity = destination_connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()
    if not integrity or integrity[0] != "ok":
        raise AcceptanceFixtureError(
            "The acceptance history database backup failed its integrity check."
        )


def _shadow_request(response, expected_status: int = 200) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise AcceptanceFixtureError(
            "The completed local Commit history could not be prepared: "
            + str(response.status_code)
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise AcceptanceFixtureError(
            "The completed local Commit history returned invalid evidence."
        )
    return payload


def _complete_shadow_history(
    settings: Settings,
    history_database: Path,
) -> tuple[str, str]:
    shadow_settings = replace(
        settings,
        database_url=f"sqlite:///{history_database}",
    )
    shadow_app = create_product_app(settings=shadow_settings, start_scheduler=False)
    with TestClient(shadow_app) as client:
        _shadow_request(
            client.post(
                "/api/auth/signup",
                json={
                    "username": SHADOW_OWNER_USERNAME,
                    "password": SHADOW_OWNER_PASSWORD,
                },
            ),
            expected_status=201,
        )
        bind_fixture_to_owner(
            shadow_app.state.session_factory,
            task_title=TASK_TITLE,
        )
        tasks = client.get("/api/tasks")
        raw_tasks = tasks.json() if tasks.status_code == 200 else []
        task_rows = raw_tasks if isinstance(raw_tasks, list) else []
        if len(task_rows) != 1:
            raise AcceptanceFixtureError(
                "The shadow history must contain exactly one Task."
            )
        task_id = int(task_rows[0]["id"])
        runs_response = client.get(f"/api/tasks/{task_id}/codex-runs")
        runs = runs_response.json() if runs_response.status_code == 200 else []
        if not isinstance(runs, list) or len(runs) != 1:
            raise AcceptanceFixtureError(
                "The shadow history must contain exactly one completed Run."
            )
        run_id = int(runs[0]["id"])

        candidate_payload = _shadow_request(
            client.post(f"/api/codex-runs/{run_id}/delivery-candidate")
        )
        candidate = candidate_payload.get("candidate")
        if not isinstance(candidate, dict):
            raise AcceptanceFixtureError("The shadow Candidate was not created.")

        plan_payload = _shadow_request(
            client.post(f"/api/codex-runs/{run_id}/apply-plans")
        )
        apply_plan = plan_payload.get("plan")
        if not isinstance(apply_plan, dict):
            raise AcceptanceFixtureError("The shadow Apply Plan was not created.")
        apply_url = f"/api/apply-plans/{apply_plan['id']}/apply-sessions"
        confirmation_payload = _shadow_request(client.get(apply_url))
        confirmation = confirmation_payload.get("apply_confirmation")
        if not isinstance(confirmation, dict) or confirmation.get("eligible") is not True:
            raise AcceptanceFixtureError("The shadow Apply preflight is not ready.")
        apply_payload = _shadow_request(
            client.post(
                apply_url,
                json={
                    "confirmation": "APPLY_ACCEPTED_CHANGES",
                    "expected_plan_digest": confirmation["expected_plan_digest"],
                    "expected_candidate_digest": confirmation[
                        "expected_candidate_digest"
                    ],
                },
            )
        )
        apply_session = apply_payload.get("session")
        if not isinstance(apply_session, dict) or apply_session.get("state") != "APPLIED":
            raise AcceptanceFixtureError("The shadow Apply did not complete.")

        verification_payload = _shadow_request(
            client.post(
                f"/api/apply-sessions/{apply_session['id']}/post-apply-verifications",
                json={"expected_journal_digest": apply_session["journal_digest"]},
            )
        )
        verification = verification_payload.get("verification")
        if not isinstance(verification, dict) or verification.get("status") != "PASSED":
            raise AcceptanceFixtureError(
                "The shadow Post-Apply Verification did not pass."
            )

        commit_plan_payload = _shadow_request(
            client.post(
                f"/api/post-apply-verifications/{verification['id']}/commit-plans",
                json={
                    "expected_verification_digest": verification["advanced"][
                        "verification_digest"
                    ],
                    "subject": COMMIT_SUBJECT,
                    "body": COMMIT_BODY,
                },
            )
        )
        commit_plan = commit_plan_payload.get("plan")
        if not isinstance(commit_plan, dict):
            raise AcceptanceFixtureError("The shadow Commit Plan was not created.")
        stage_payload = _shadow_request(
            client.post(
                f"/api/commit-plans/{commit_plan['id']}/stage-sessions",
                json={
                    "confirmation": STAGE_CONFIRMATION,
                    "expected_plan_digest": commit_plan["advanced"]["plan_digest"],
                },
            )
        )
        stage = stage_payload.get("stage")
        if not isinstance(stage, dict) or stage.get("state") != "STAGED":
            raise AcceptanceFixtureError("The shadow Stage did not complete.")
        commit_payload = _shadow_request(
            client.post(
                f"/api/stage-sessions/{stage['id']}/local-commits",
                json={
                    "confirmation": COMMIT_CONFIRMATION,
                    "expected_plan_digest": commit_plan["advanced"]["plan_digest"],
                    "expected_stage_digest": stage["stage_digest"],
                },
            )
        )
        commit = commit_payload.get("commit")
        if not isinstance(commit, dict) or commit.get("state") != "COMMITTED":
            raise AcceptanceFixtureError("The shadow local Commit did not complete.")
        commit_oid = str(commit.get("commit_oid") or "")
        parent_oid = str(commit.get("parent_sha") or "")
        if not commit_oid or not parent_oid:
            raise AcceptanceFixtureError("The shadow local Commit identity is absent.")
        return commit_oid, parent_oid


def _history_counts(session: Session) -> dict[str, int]:
    return {
        "result_monitors": int(
            session.scalar(select(func.count()).select_from(CodexRunMonitor)) or 0
        ),
        "result_envelopes": int(
            session.scalar(select(func.count()).select_from(CodexResultEnvelope))
            or 0
        ),
        "candidates": int(
            session.scalar(select(func.count()).select_from(DeliveryCandidate)) or 0
        ),
        "apply_plans": int(
            session.scalar(select(func.count()).select_from(ApplyPlan)) or 0
        ),
        "apply_sessions": int(
            session.scalar(select(func.count()).select_from(ApplySession)) or 0
        ),
        "verifications": int(
            session.scalar(select(func.count()).select_from(PostApplyVerification))
            or 0
        ),
        "commit_plans": int(
            session.scalar(select(func.count()).select_from(CommitPlan)) or 0
        ),
        "stage_records": int(
            session.scalar(select(func.count()).select_from(StageExecution)) or 0
        ),
        "commit_records": int(
            session.scalar(select(func.count()).select_from(LocalCommitExecution))
            or 0
        ),
    }


def _push_record_count(session: Session) -> int:
    inspector = inspect(session.get_bind())
    if not inspector.has_table("push_executions"):
        return 0
    return int(session.execute(text("SELECT COUNT(*) FROM push_executions")).scalar() or 0)


def _validate_shadow_history(
    history_database: Path,
    source_repo: Path,
    origin: Path,
) -> tuple[int, str, str]:
    engine = create_engine(f"sqlite:///{history_database}", future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    try:
        with factory() as session:
            owner = session.scalar(select(User).order_by(User.id))
            task = session.scalar(select(Task).order_by(Task.id))
            commit = session.scalar(select(LocalCommitExecution))
            stage = session.scalar(select(StageExecution))
            counts = _history_counts(session)
            if owner is None or task is None or commit is None or stage is None:
                raise AcceptanceFixtureError(
                    "The completed acceptance history template is incomplete."
                )
            required = {
                "result_monitors": 1,
                "result_envelopes": 1,
                "candidates": 1,
                "apply_plans": 1,
                "apply_sessions": 1,
                "verifications": 1,
                "commit_plans": 1,
                "stage_records": 1,
                "commit_records": 1,
            }
            if counts != required:
                raise AcceptanceFixtureError(
                    "The completed acceptance history template has unexpected records."
                )
            if stage.state != "STAGED" or commit.state != "COMMITTED":
                raise AcceptanceFixtureError(
                    "The completed acceptance history does not end at Local Commit."
                )
            if _push_record_count(session) != 0:
                raise AcceptanceFixtureError(
                    "The acceptance history template already contains a Push record."
                )
            commit_oid = str(commit.commit_oid or "")
            parent_oid = str(commit.parent_oid or "")
            if not commit_oid or not parent_oid:
                raise AcceptanceFixtureError(
                    "The completed acceptance Commit identity is incomplete."
                )
            template_owner_id = owner.id
            task_id = task.id
    finally:
        engine.dispose()

    if _run_git(source_repo, "rev-parse", "HEAD") != commit_oid:
        raise AcceptanceFixtureError(
            "The source HEAD does not match the completed acceptance Commit."
        )
    live_origin_main = _run_bare(origin, "rev-parse", "refs/heads/main")
    if live_origin_main not in {parent_oid, commit_oid}:
        raise AcceptanceFixtureError(
            "The local acceptance origin is neither the expected parent nor the "
            "approved Commit."
        )
    if _run_git(source_repo, "rev-parse", f"{commit_oid}^") != parent_oid:
        raise AcceptanceFixtureError(
            "The approved local Commit has an unexpected parent."
        )
    return template_owner_id, commit_oid, parent_oid


def _copy_model_rows(
    source: Session,
    destination: Session,
    model,
    *,
    template_owner_id: int,
    owner_id: int,
) -> None:
    rows = source.scalars(select(model).order_by(model.id)).all()
    for row in rows:
        values = {
            column.name: getattr(row, column.name) for column in model.__table__.columns
        }
        if "owner_id" in values:
            if values["owner_id"] != template_owner_id:
                raise AcceptanceFixtureError(
                    "The completed history contains a cross-Owner record."
                )
            values["owner_id"] = owner_id
        destination.add(model(**values))
    destination.flush()


def bind_completed_history_to_owner(
    factory,
    history_database: Path,
    *,
    expected_task_id: int,
    template_owner_id: int,
) -> None:
    history_engine = create_engine(f"sqlite:///{history_database}", future=True)
    history_factory = sessionmaker(
        bind=history_engine,
        expire_on_commit=False,
        future=True,
    )
    try:
        with history_factory() as history_session:
            with factory() as live_session:
                owners = live_session.scalars(select(User).order_by(User.id)).all()
                if len(owners) != 1:
                    raise AcceptanceFixtureError(
                        "The acceptance history can bind only to one fresh Owner."
                    )
                owner = owners[0]
                if owner.id != template_owner_id:
                    raise AcceptanceFixtureError(
                        "The fresh Owner identity does not match the immutable history."
                    )
                task = live_session.scalar(
                    select(Task).where(Task.id == expected_task_id)
                )
                if task is None or task.title != TASK_TITLE:
                    raise AcceptanceFixtureError(
                        "The exact Phase 18.4B Task is unavailable."
                    )
                if any(_history_counts(live_session).values()):
                    raise AcceptanceFixtureError(
                        "The live database already contains delivery history."
                    )
                if _push_record_count(live_session) != 0:
                    raise AcceptanceFixtureError(
                        "The live database already contains a Push record."
                    )
                pack = live_session.scalar(
                    select(CodexInstructionPack).where(
                        CodexInstructionPack.task_id == task.id
                    )
                )
                acceptance = live_session.scalar(
                    select(OwnerAcceptanceSession).where(
                        OwnerAcceptanceSession.task_id == task.id
                    )
                )
                if pack is None or acceptance is None:
                    raise AcceptanceFixtureError(
                        "The Phase 18.4B prerequisite bindings are unavailable."
                    )
                if pack.approved_by_user_id not in {None, owner.id}:
                    raise AcceptanceFixtureError(
                        "The acceptance Pack is bound to another Owner."
                    )
                if acceptance.decided_by_user_id not in {None, owner.id}:
                    raise AcceptanceFixtureError(
                        "The acceptance evidence is bound to another Owner."
                    )
                pack.approved_by_user_id = owner.id
                acceptance.decided_by_user_id = owner.id
                for model in _HISTORY_MODELS:
                    _copy_model_rows(
                        history_session,
                        live_session,
                        model,
                        template_owner_id=template_owner_id,
                        owner_id=owner.id,
                    )
                live_session.commit()
    finally:
        history_engine.dispose()


def _rename_live_task(factory) -> int:
    with factory() as session:
        existing = session.scalar(select(Task).where(Task.title == TASK_TITLE))
        if existing is not None:
            return existing.id
        task = session.scalar(select(Task).order_by(Task.id))
        if task is None:
            raise AcceptanceFixtureError("The acceptance Task seed is unavailable.")
        if session.scalar(select(func.count()).select_from(Task)) != 1:
            raise AcceptanceFixtureError(
                "The acceptance database contains an unexpected Task inventory."
            )
        task.title = TASK_TITLE
        task.objective = "Push the exact approved local Commit to origin/main."
        task.implementation_scope = (
            "One explicit standard fast-forward Push and Delivery Result."
        )
        task.forbidden_scope = (
            "No force, tags, other branches, remote configuration change, merge, "
            "rebase, trading, or betting."
        )
        task.required_output = (
            "One immutable Push result and truthful local/remote reconciliation."
        )
        task.acceptance_target = (
            "Explicit confirmation, one origin/main Push, and Delivery Result."
        )
        session.commit()
        return task.id


def _repository_boundary(source_repo: Path, origin: Path) -> dict[str, Any]:
    index_path = Path(_run_git(source_repo, "rev-parse", "--git-path", "index"))
    if not index_path.is_absolute():
        index_path = source_repo / index_path
    files = {
        item.name: _sha256(item.read_bytes())
        for item in source_repo.iterdir()
        if item.is_file()
    }
    return {
        "head": _run_git(source_repo, "rev-parse", "HEAD"),
        "branch": _run_git(source_repo, "branch", "--show-current"),
        "index_sha256": _sha256(index_path.read_bytes()),
        "status": _status_lines(source_repo),
        "staged_paths": _staged_paths(source_repo),
        "config_sha256": _sha256(
            _run_git(source_repo, "config", "--local", "--null", "--list").encode()
        ),
        "refs_sha256": _sha256(
            _run_git(
                source_repo,
                "for-each-ref",
                "--format=%(refname)%00%(objectname)%00",
            ).encode()
        ),
        "origin_main": _run_bare(origin, "rev-parse", "refs/heads/main"),
        "files": files,
    }


def fixture_health(
    factory,
    source_repo: Path,
    origin: Path,
    *,
    expected_task_id: int,
    expected_commit_oid: str,
    expected_parent_oid: str,
) -> dict[str, Any]:
    with factory() as session:
        task = session.scalar(select(Task).where(Task.id == expected_task_id))
        owners = int(session.scalar(select(func.count()).select_from(User)) or 0)
        counts = _history_counts(session)
        push_records = _push_record_count(session)
    head = _run_git(source_repo, "rev-parse", "HEAD")
    remote_head = _run_bare(origin, "rev-parse", "refs/heads/main")
    left_right = _run_git(
        source_repo,
        "rev-list",
        "--left-right",
        "--count",
        f"{remote_head}...{head}",
    ).split()
    if len(left_right) != 2:
        raise AcceptanceFixtureError("The acceptance ahead/behind result is invalid.")
    behind, ahead = (int(left_right[0]), int(left_right[1]))
    _assert_exact_local_origin(source_repo, origin)
    remote_state_valid = bool(
        (push_records == 0 and remote_head == expected_parent_oid)
        or (push_records == 1 and remote_head == expected_commit_oid)
    )
    ready = bool(
        task is not None
        and task.title == TASK_TITLE
        and head == expected_commit_oid
        and remote_state_valid
        and not _status_lines(source_repo)
        and not _staged_paths(source_repo)
    )
    return {
        "status": "healthy" if ready else "blocked",
        "ready": ready,
        "task": {"title": task.title if task is not None else None},
        "counts": {
            "owners": owners,
            **counts,
            "push_records": push_records,
        },
        "repository": {
            "branch": _run_git(source_repo, "branch", "--show-current"),
            "head_matches_approved_commit": head == expected_commit_oid,
            "origin_main_matches_expected_parent": remote_head == expected_parent_oid,
            "origin_main_matches_approved_commit": remote_head == expected_commit_oid,
            "ahead": ahead,
            "behind": behind,
            "worktree_clean": not _status_lines(source_repo),
            "index_clean": not _staged_paths(source_repo),
            "staged_path_count": len(_staged_paths(source_repo)),
            "remote_name": "origin",
            "remote_kind": "local_disposable_bare",
            "remote_count": 1,
        },
        "scheduler": "disabled",
        "automatic_actions": {
            "push": False,
            "next_run": False,
        },
    }


def create_app(settings: Settings | None = None, start_scheduler: bool = False):
    removed_git_environment = sanitize_acceptance_process_environment()
    settings = settings or get_settings()
    database_path = _sqlite_database_path(settings.database_url)
    history_database = _history_database_path(database_path)
    retained, origin, initial_parent = _prepare_repository(
        settings.source_repo,
        settings.worktree_root,
        history_exists=history_database.exists(),
    )
    app = create_product_app(settings=settings, start_scheduler=start_scheduler)
    factory = app.state.session_factory

    with factory() as session:
        task_count = int(session.scalar(select(func.count()).select_from(Task)) or 0)
        exact_task = session.scalar(select(Task).where(Task.title == TASK_TITLE))
        owner_count = int(session.scalar(select(func.count()).select_from(User)) or 0)
    if exact_task is None:
        if task_count not in {0, 1} or owner_count != 0 or history_database.exists():
            raise AcceptanceFixtureError(
                "The Phase 18.4B acceptance database is not a fresh fixture."
            )
        seed_unbound_acceptance_fixture(
            factory,
            settings.source_repo,
            retained,
            task_title=TASK_TITLE,
        )
        expected_task_id = _rename_live_task(factory)
        _backup_sqlite(database_path, history_database)
        commit_oid, parent_oid = _complete_shadow_history(
            settings,
            history_database,
        )
        if parent_oid != initial_parent:
            raise AcceptanceFixtureError(
                "The completed local Commit does not bind the prepared origin base."
            )
    else:
        expected_task_id = exact_task.id
        commit_oid = ""
        parent_oid = ""

    template_owner_id, template_commit_oid, template_parent_oid = (
        _validate_shadow_history(history_database, settings.source_repo, origin)
    )
    if commit_oid and commit_oid != template_commit_oid:
        raise AcceptanceFixtureError(
            "The prepared local Commit differs from the immutable history template."
        )
    if parent_oid and parent_oid != template_parent_oid:
        raise AcceptanceFixtureError(
            "The prepared remote base differs from the immutable history template."
        )

    @app.get("/health")
    def acceptance_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/fixture-health")
    def acceptance_fixture_health() -> dict[str, Any]:
        health = fixture_health(
            factory,
            settings.source_repo,
            origin,
            expected_task_id=expected_task_id,
            expected_commit_oid=template_commit_oid,
            expected_parent_oid=template_parent_oid,
        )
        health["process_environment"] = {
            "inherited_git_overrides_removed": list(removed_git_environment),
            "git_overrides_present": sorted(
                name for name in os.environ if name.startswith("GIT_")
            ),
        }
        return health

    @app.middleware("http")
    async def bind_owner_acceptance_fixture(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/api/auth/signup" and response.status_code == 201:
            before = _repository_boundary(settings.source_repo, origin)
            try:
                bind_completed_history_to_owner(
                    factory,
                    history_database,
                    expected_task_id=expected_task_id,
                    template_owner_id=template_owner_id,
                )
                after = _repository_boundary(settings.source_repo, origin)
                if before != after:
                    raise AcceptanceFixtureError(
                        "Owner binding changed the acceptance repository."
                    )
            except AcceptanceFixtureError:
                return JSONResponse(
                    status_code=500,
                    content={
                        "code": "OWNER_ACCEPTANCE_FIXTURE_BIND_FAILED",
                        "message": (
                            "The completed local Commit history could not be bound "
                            "to the Owner."
                        ),
                    },
                )
        return response

    return app
