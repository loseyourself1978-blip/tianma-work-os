from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from scripts.vol18_4a_owner_acceptance_app import TASK_TITLE, create_app
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
    SessionToken,
    StageExecution,
    Task,
    User,
)


def test_fresh_signup_receives_exact_executable_phase18_4a_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GIT_PAGER", "cat")
    spool = tmp_path / "spool"
    spool.mkdir(mode=0o700)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'acceptance.sqlite3'}",
        source_repo=tmp_path / "fixture-repo",
        worktree_root=tmp_path / "worktrees",
        codex_spool_root=spool,
        codex_executable=str(tmp_path / "codex-must-not-run"),
    )
    app = create_app(settings=settings, start_scheduler=False)
    factory = app.state.session_factory
    source_repo = settings.source_repo

    def repository_boundary() -> dict[str, object]:
        index = source_repo / ".git" / "index"
        return {
            "head": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=source_repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "files": {
                item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                for item in source_repo.iterdir()
                if item.is_file()
            },
        }

    boundary_before = repository_boundary()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(SessionToken)) == 0
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(Task.title)) == TASK_TITLE
        for model in (
            DeliveryCandidate,
            ApplyPlan,
            ApplySession,
            PostApplyVerification,
            CommitPlan,
            StageExecution,
            LocalCommitExecution,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0

    with TestClient(app) as client:
        fixture_health = client.get("/fixture-health")
        assert fixture_health.status_code == 200
        assert fixture_health.json()["ready"] is True
        assert fixture_health.json()["process_environment"] == {
            "inherited_git_overrides_removed": ["GIT_PAGER"],
            "git_overrides_present": [],
        }
        assert fixture_health.json()["counts"] == {
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
        }
        signup = client.post(
            "/api/auth/signup",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert signup.status_code == 201, signup.text
        tasks = client.get("/api/tasks")
        assert tasks.status_code == 200, tasks.text
        assert [item["title"] for item in tasks.json()] == [TASK_TITLE]
        task_id = tasks.json()[0]["id"]
        runs = client.get(f"/api/tasks/{task_id}/codex-runs")
        assert runs.status_code == 200, runs.text
        assert len(runs.json()) == 1
        run_id = runs.json()[0]["id"]
        result_response = client.get(f"/api/codex-runs/{run_id}/result-envelope")
        assert result_response.status_code == 200, result_response.text
        result = result_response.json()["result"]
        assert result["result_available"] is True
        assert result["integrity_state"] == "VERIFIED"
        assert result["changed_files"] and {
            item["operation"] for item in result["changed_files"]
        } == {"CREATE", "MODIFY", "DELETE"}
        activity_response = client.get("/api/run-activity")
        assert activity_response.status_code == 200, activity_response.text
        activity = activity_response.json()["runs"]
        assert len(activity) == 1
        assert activity[0]["monitor_state"] == "RESULT_AVAILABLE"
        assert activity[0]["result_available"] is True
        assert activity[0]["envelope"]["integrity_state"] == "VERIFIED"
        # This is the exact data predicate that makes the browser's active-Run
        # observer stop polling: the lifecycle is terminal and the immutable
        # envelope is valid.
        assert activity[0]["lifecycle"]["state"] == "result_available"
        assert activity[0]["lifecycle"]["result_integrity"] == "verified"
        initial_candidate = client.get(f"/api/codex-runs/{run_id}/delivery-candidate")
        assert initial_candidate.status_code == 200, initial_candidate.text
        assert initial_candidate.json()["candidate"] is None
        assert repository_boundary() == boundary_before

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(SessionToken)) == 1
        assert session.scalar(select(func.count()).select_from(CodexRunMonitor)) == 1
        assert session.scalar(select(func.count()).select_from(CodexResultEnvelope)) == 1
        for model in (
            DeliveryCandidate,
            ApplyPlan,
            ApplySession,
            PostApplyVerification,
            CommitPlan,
            StageExecution,
            LocalCommitExecution,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_acceptance_harness_has_no_push_execution_path() -> None:
    source = Path(__file__).parents[1].joinpath(
        "scripts", "vol18_4a_owner_acceptance_app.py"
    ).read_text(encoding="utf-8")
    assert '"push"' not in source.casefold()
    assert "push -u" not in source.casefold()
    assert "--set-upstream" not in source.casefold()


def test_acceptance_fixture_completes_full_phase18_4a_journey(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tests.test_vol18_stage_local_commit import (
        COMMIT_BODY,
        COMMIT_CONFIRMATION,
        COMMIT_SUBJECT,
        STAGE_CONFIRMATION,
    )

    spool = tmp_path / "spool"
    monkeypatch.setenv("GIT_PAGER", "cat")
    spool.mkdir(mode=0o700)
    source_repo = tmp_path / "fixture-repo"
    app = create_app(
        settings=Settings(
            database_url=f"sqlite:///{tmp_path / 'acceptance.sqlite3'}",
            source_repo=source_repo,
            worktree_root=tmp_path / "worktrees",
            codex_spool_root=spool,
            codex_executable=str(tmp_path / "codex-must-not-run"),
        ),
        start_scheduler=False,
    )
    with TestClient(app) as client:
        process_environment = client.get("/fixture-health").json()[
            "process_environment"
        ]
        assert "GIT_PAGER" in process_environment[
            "inherited_git_overrides_removed"
        ]
        assert process_environment["git_overrides_present"] == []
        assert client.post(
            "/api/auth/signup",
            json={"username": "owner", "password": OWNER_PASSWORD},
        ).status_code == 201
        task = client.get("/api/tasks").json()[0]
        run = client.get(f"/api/tasks/{task['id']}/codex-runs").json()[0]

        candidate_review = client.post(
            f"/api/codex-runs/{run['id']}/delivery-candidate"
        )
        assert candidate_review.status_code == 200, candidate_review.text
        candidate = candidate_review.json()["candidate"]
        assert candidate is not None
        assert {item["operation"] for item in candidate["changed_files"]} == {
            "CREATE",
            "MODIFY",
            "DELETE",
        }

        plan_review = client.post(f"/api/codex-runs/{run['id']}/apply-plans")
        assert plan_review.status_code == 200, plan_review.text
        plan = plan_review.json()["plan"]
        apply_review_url = f"/api/apply-plans/{plan['id']}/apply-sessions"
        confirmation = client.get(apply_review_url).json()["apply_confirmation"]
        assert confirmation["eligible"] is True
        applied_response = client.post(
            apply_review_url,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": confirmation[
                    "expected_candidate_digest"
                ],
            },
        )
        assert applied_response.status_code == 200, applied_response.text
        applied = applied_response.json()["session"]
        assert applied["state"] == "APPLIED"

        verification_response = client.post(
            f"/api/apply-sessions/{applied['id']}/post-apply-verifications",
            json={"expected_journal_digest": applied["journal_digest"]},
        )
        assert verification_response.status_code == 200, verification_response.text
        verification = verification_response.json()["verification"]
        assert verification["status"] == "PASSED"

        commit_plan_response = client.post(
            f"/api/post-apply-verifications/{verification['id']}/commit-plans",
            json={
                "expected_verification_digest": verification["advanced"][
                    "verification_digest"
                ],
                "subject": COMMIT_SUBJECT,
                "body": COMMIT_BODY,
            },
        )
        assert commit_plan_response.status_code == 200, commit_plan_response.text
        commit_plan = commit_plan_response.json()["plan"]
        stage_response = client.post(
            f"/api/commit-plans/{commit_plan['id']}/stage-sessions",
            json={
                "confirmation": STAGE_CONFIRMATION,
                "expected_plan_digest": commit_plan["advanced"]["plan_digest"],
            },
        )
        assert stage_response.status_code == 200, stage_response.text
        stage = stage_response.json()["stage"]
        assert stage["state"] == "STAGED"
        commit_response = client.post(
            f"/api/stage-sessions/{stage['id']}/local-commits",
            json={
                "confirmation": COMMIT_CONFIRMATION,
                "expected_plan_digest": commit_plan["advanced"]["plan_digest"],
                "expected_stage_digest": stage["stage_digest"],
            },
        )
        assert commit_response.status_code == 200, commit_response.text
        commit = commit_response.json()["commit"]
        assert commit["state"] == "COMMITTED"

        assert subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=source_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""
        assert subprocess.run(
            ["git", "remote"],
            cwd=source_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout == ""
        changed = subprocess.run(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "--no-renames",
                "-r",
                commit["commit_oid"],
            ],
            cwd=source_repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        assert set(changed) == {"created.txt", "modify.txt", "delete.txt"}
        refreshed = client.get(
            f"/api/post-apply-verifications/{verification['id']}/commit-plans"
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["plan"]["id"] == commit_plan["id"]
