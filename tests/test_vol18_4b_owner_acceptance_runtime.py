from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from scripts.vol18_4b_owner_acceptance_app import (
    TASK_TITLE,
    _history_database_path,
    _origin_path,
    _repository_boundary,
    _run_bare,
    create_app,
)
from tests.test_self_hosting import OWNER_PASSWORD
from twos_runtime.config import Settings
from twos_runtime.models import (
    ApplyPlan,
    ApplySession,
    CodexResultEnvelope,
    CodexRunMonitor,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    PostApplyVerification,
    PushExecution,
    SessionToken,
    StageExecution,
    Task,
    User,
)


def _settings(tmp_path: Path) -> Settings:
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700, exist_ok=True)
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'acceptance.sqlite3'}",
        source_repo=tmp_path / "fixture-repo",
        worktree_root=tmp_path / "worktrees",
        codex_spool_root=spool,
        codex_executable=str(tmp_path / "codex-must-not-run"),
    )


def _push_count(session) -> int:
    if not inspect(session.get_bind()).has_table("push_executions"):
        return 0
    return int(session.execute(text("SELECT COUNT(*) FROM push_executions")).scalar() or 0)


def _history_counts(session) -> dict[str, int]:
    return {
        "monitors": int(
            session.scalar(select(func.count()).select_from(CodexRunMonitor)) or 0
        ),
        "envelopes": int(
            session.scalar(select(func.count()).select_from(CodexResultEnvelope)) or 0
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
        "stages": int(
            session.scalar(select(func.count()).select_from(StageExecution)) or 0
        ),
        "commits": int(
            session.scalar(select(func.count()).select_from(LocalCommitExecution))
            or 0
        ),
    }


def test_fresh_fixture_has_exact_task_and_push_ready_repository_before_signup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GIT_PAGER", "cat")
    settings = _settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    factory = app.state.session_factory
    origin = _origin_path(settings.source_repo)
    history_database = _history_database_path(tmp_path / "acceptance.sqlite3")

    assert history_database.is_file()
    assert origin.is_dir()
    assert _run_bare(origin, "rev-parse", "--is-bare-repository") == "true"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(SessionToken)) == 0
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(Task.title)) == TASK_TITLE
        assert _history_counts(session) == {
            "monitors": 0,
            "envelopes": 0,
            "candidates": 0,
            "apply_plans": 0,
            "apply_sessions": 0,
            "verifications": 0,
            "commit_plans": 0,
            "stages": 0,
            "commits": 0,
        }
        assert _push_count(session) == 0

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/twos").status_code == 200
        response = client.get("/fixture-health")
        assert response.status_code == 200, response.text
        health = response.json()
        assert health["ready"] is True
        assert health["task"] == {"title": TASK_TITLE}
        assert health["process_environment"] == {
            "inherited_git_overrides_removed": ["GIT_PAGER"],
            "git_overrides_present": [],
        }
        assert health["counts"] == {
            "owners": 0,
            "result_monitors": 0,
            "result_envelopes": 0,
            "candidates": 0,
            "apply_plans": 0,
            "apply_sessions": 0,
            "verifications": 0,
            "commit_plans": 0,
            "stage_records": 0,
            "commit_records": 0,
            "push_records": 0,
        }
        assert health["repository"] == {
            "branch": "main",
            "head_matches_approved_commit": True,
            "origin_main_matches_expected_parent": True,
            "origin_main_matches_approved_commit": False,
            "ahead": 1,
            "behind": 0,
            "worktree_clean": True,
            "index_clean": True,
            "staged_path_count": 0,
            "remote_name": "origin",
            "remote_kind": "local_disposable_bare",
            "remote_count": 1,
        }
        assert health["scheduler"] == "disabled"
        assert health["automatic_actions"] == {
            "push": False,
            "next_run": False,
        }


def test_real_signup_only_imports_completed_history_and_never_changes_repository(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    factory = app.state.session_factory
    origin = _origin_path(settings.source_repo)
    before = _repository_boundary(settings.source_repo, origin)

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert signup.status_code == 201, signup.text
        assert _repository_boundary(settings.source_repo, origin) == before

        tasks = client.get("/api/tasks")
        assert tasks.status_code == 200, tasks.text
        assert [item["title"] for item in tasks.json()] == [TASK_TITLE]
        task_id = tasks.json()[0]["id"]
        runs = client.get(f"/api/tasks/{task_id}/codex-runs")
        assert runs.status_code == 200, runs.text
        assert len(runs.json()) == 1
        run_id = runs.json()[0]["id"]
        result = client.get(f"/api/codex-runs/{run_id}/result-envelope")
        assert result.status_code == 200, result.text
        assert result.json()["result"]["integrity_state"] == "VERIFIED"

        health = client.get("/fixture-health").json()
        assert health["ready"] is True
        assert health["counts"]["owners"] == 1
        assert health["counts"]["commit_records"] == 1
        assert health["counts"]["push_records"] == 0
        assert health["repository"]["ahead"] == 1
        assert health["repository"]["behind"] == 0

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(SessionToken)) == 1
        assert _history_counts(session) == {
            "monitors": 1,
            "envelopes": 1,
            "candidates": 1,
            "apply_plans": 1,
            "apply_sessions": 1,
            "verifications": 1,
            "commit_plans": 1,
            "stages": 1,
            "commits": 1,
        }
        commit = session.scalar(select(LocalCommitExecution))
        stage = session.scalar(select(StageExecution))
        assert commit is not None and commit.state == "COMMITTED"
        assert stage is not None and stage.state == "STAGED"
        assert commit.parent_oid == before["origin_main"]
        assert commit.commit_oid == before["head"]
        assert _push_count(session) == 0


def test_restart_preserves_imported_history_without_repository_repreparation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    first = create_app(settings=settings, start_scheduler=False)
    origin = _origin_path(settings.source_repo)
    with TestClient(first) as client:
        assert client.post(
            "/api/auth/signup",
            json={"username": "owner", "password": OWNER_PASSWORD},
        ).status_code == 201
    before = _repository_boundary(settings.source_repo, origin)

    restarted = create_app(settings=settings, start_scheduler=False)
    assert _repository_boundary(settings.source_repo, origin) == before
    with TestClient(restarted) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert login.status_code == 200, login.text
        health = client.get("/fixture-health").json()
        assert health["ready"] is True
        assert health["counts"]["owners"] == 1
        assert health["counts"]["commit_records"] == 1
        assert health["counts"]["push_records"] == 0
        assert health["repository"]["ahead"] == 1
        assert health["repository"]["behind"] == 0


def test_fixture_owner_journey_starts_at_local_commit_and_pushes_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import twos_runtime.push_delivery as push_delivery_service

    settings = _settings(tmp_path)
    app = create_app(settings=settings, start_scheduler=False)
    factory = app.state.session_factory
    origin = _origin_path(settings.source_repo)
    requested: list[tuple[str, str]] = []

    @app.middleware("http")
    async def record_owner_requests(request, call_next):
        requested.append((request.method, request.url.path))
        return await call_next(request)

    original_transport = push_delivery_service._run_standard_push
    refspecs: list[str] = []

    def counted_transport(root: Path, refspec: str):
        assert root.resolve() == settings.source_repo.resolve()
        refspecs.append(refspec)
        return original_transport(root, refspec)

    monkeypatch.setattr(
        push_delivery_service,
        "_run_standard_push",
        counted_transport,
    )
    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert signup.status_code == 201, signup.text
        with factory() as session:
            commit = session.scalar(select(LocalCommitExecution))
            assert commit is not None and commit.state == "COMMITTED"
            commit_id = commit.commit_execution_id
            approved = str(commit.commit_oid)
            parent = str(commit.parent_oid)
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0
        assert _run_bare(origin, "rev-parse", "refs/heads/main") == parent

        review_url = f"/api/local-commits/{commit_id}/push-delivery"
        initial = client.get(review_url)
        assert initial.status_code == 200, initial.text
        initial_review = initial.json()
        assert initial_review["action_state"] == "READY_TO_PUSH"
        assert initial_review["readiness"]["ahead"] == 1
        assert initial_review["readiness"]["behind"] == 0
        assert initial_review["actions"] == {
            "can_push_to_origin_main": True,
            "can_confirm_push": False,
            "can_view_delivery_result": False,
        }
        assert refspecs == []
        assert _run_bare(origin, "rev-parse", "refs/heads/main") == parent

        preflight = client.post(
            f"/api/local-commits/{commit_id}/push-preflights"
        )
        assert preflight.status_code == 200, preflight.text
        reviewed = preflight.json()
        execution = reviewed["push_execution"]
        assert execution["state"] == "READY_TO_PUSH"
        assert execution["command_attempt_count"] == 0
        assert reviewed["actions"]["can_confirm_push"] is True
        assert execution["refspec"] == f"{approved}:refs/heads/main"
        assert refspecs == []
        assert _run_bare(origin, "rev-parse", "refs/heads/main") == parent

        confirmed = client.post(
            f"/api/push-preflights/{execution['id']}/push-attempts",
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_confirmation_digest": execution[
                    "confirmation_digest"
                ],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        delivered = confirmed.json()
        assert refspecs == [f"{approved}:refs/heads/main"]
        assert delivered["action_state"] == "PUSHED"
        assert delivered["push_execution"]["state"] == "PUSHED"
        assert delivered["push_execution"]["command_attempt_count"] == 1
        result = delivered["delivery_result"]
        assert result["status"] == "DELIVERED"
        assert result["complete"] is True
        assert result["reconciliation"] == {
            "status": "RECONCILED",
            "complete": True,
            "local_head": approved,
            "origin_main_sha": approved,
            "approved_commit_sha": approved,
            "ahead": 0,
            "behind": 0,
            "worktree_clean": True,
            "index_clean": True,
            "staged_path_count": 0,
            "blockers": [],
        }
        assert _run_bare(origin, "rev-parse", "refs/heads/main") == approved

        repeated = client.post(
            f"/api/push-preflights/{execution['id']}/push-attempts",
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_confirmation_digest": execution[
                    "confirmation_digest"
                ],
            },
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["push_execution"]["state"] == "PUSHED"
        assert refspecs == [f"{approved}:refs/heads/main"]

        health = client.get("/fixture-health")
        assert health.status_code == 200, health.text
        health_payload = health.json()
        assert health_payload["ready"] is True
        assert health_payload["counts"]["push_records"] == 1
        assert health_payload["repository"]["ahead"] == 0
        assert health_payload["repository"]["behind"] == 0
        assert health_payload["repository"][
            "origin_main_matches_approved_commit"
        ] is True

    forbidden_prior_phase_posts = (
        "/delivery-candidate",
        "/apply-plans",
        "/apply-sessions",
        "/post-apply-verifications",
        "/commit-plans",
        "/stage-sessions",
    )
    owner_posts = [path for method, path in requested if method == "POST"]
    assert not [
        path
        for path in owner_posts
        if any(marker in path for marker in forbidden_prior_phase_posts)
    ]

    restarted = create_app(settings=settings, start_scheduler=False)
    with TestClient(restarted) as client:
        assert client.post(
            "/api/auth/login",
            json={"username": "owner", "password": OWNER_PASSWORD},
        ).status_code == 200
        persisted = client.get(
            f"/api/local-commits/{commit_id}/push-delivery"
        )
        assert persisted.status_code == 200, persisted.text
        assert persisted.json()["action_state"] == "PUSHED"
        assert persisted.json()["delivery_result"]["complete"] is True
        restarted_repository = client.get("/fixture-health").json()["repository"]
        assert restarted_repository["ahead"] == 0
        assert restarted_repository["behind"] == 0
    assert refspecs == [f"{approved}:refs/heads/main"]


def test_fixture_preparation_has_no_transport_or_history_replay_command() -> None:
    source_path = Path(__file__).parents[1] / "scripts" / "vol18_4b_owner_acceptance_app.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "clone",
        "fetch",
        "pull",
        "push",
        "merge",
        "rebase",
        "tag",
    }
    observed: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"_run_git", "_run_bare"}:
            continue
        for argument in node.args[1:]:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                observed.append((argument.value.casefold(), node.lineno))
    assert not [item for item in observed if item[0] in forbidden]
    assert "shutil.copytree(" in source
    assert '"update-ref", "refs/heads/main"' in source
    assert '"remote", "add", "origin"' in source
    assert 'client.post(f"/api/codex-runs/{run_id}/delivery-candidate")' in source
    assert 'f"/api/stage-sessions/{stage[\'id\']}/local-commits"' in source
