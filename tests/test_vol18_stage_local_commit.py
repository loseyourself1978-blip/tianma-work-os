from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from tests.test_self_hosting import init_and_login, make_client, run_command
from tests.test_vol18_apply_revert import (
    ApplyRevertFixture,
    _apply,
    _git_boundary,
    _prepare_retained_run_material,
    create_manifest_entry,
    phase18b_fixture,
)
from tests.test_vol18_delivery_candidate import (
    build_candidate_fixture,
    candidate_url,
    close_candidate_fixture,
)
from tests.test_vol18_post_apply_verification import _post_verification
from tests.test_vol18_review_apply_plan import apply_plan_url
from twos_runtime.models import (
    ApplySession,
    CommitPlan,
    LocalCommitExecution,
    PostApplyVerification,
    SchemaVersion,
    SessionToken,
    StageExecution,
    User,
    utc_now,
)
from twos_runtime.post_apply_verifications import (
    get_or_create_post_apply_verification,
)
from twos_runtime.commit_builder import (
    COMMIT_BUILDER_POLICY_VERSION,
    MAX_COMMIT_BODY_BYTES,
    MAX_COMMIT_SUBJECT_BYTES,
    CommitBuilderError,
    _commit_out,
    _other_stage_blocker,
    _safe_message,
    _stage_out,
    commit_builder_review,
    commit_plan_out,
    create_local_commit,
    get_or_create_commit_plan,
    stage_commit_plan,
)
from twos_runtime.security import hash_password, hash_token
import twos_runtime.commit_builder as commit_builder_service


STAGE_CONFIRMATION = "STAGE_APPROVED_FILES"
COMMIT_CONFIRMATION = "CREATE_LOCAL_COMMIT"
COMMIT_SUBJECT = "Apply verified Phase 18 fixture changes"
COMMIT_BODY = "Create one local commit from the exact verified Apply result."


@pytest.fixture(autouse=True)
def _clear_inherited_git_process_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal product calls run without caller-controlled Git redirection."""
    for name in tuple(__import__("os").environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


@dataclass(frozen=True)
class VerifiedApplyFixture:
    fixture: ApplyRevertFixture
    applied: dict[str, object]
    verification: dict[str, object]

    @property
    def client(self):
        return self.fixture.client

    @property
    def source_repo(self) -> Path:
        return self.fixture.source_repo

    @property
    def factory(self):
        return self.fixture.factory

    @property
    def owner_id(self) -> int:
        return self.fixture.owner_id


@contextmanager
def verified_apply_fixture(tmp_path: Path, **options):
    with phase18b_fixture(tmp_path, **options) as fixture:
        applied, created = _apply(fixture)
        assert created is True
        assert applied["state"] == "APPLIED"
        response = _post_verification(fixture, applied)
        assert response.status_code == 200, response.text
        verification = response.json()["verification"]
        assert verification["status"] == "PASSED"
        assert verification["advanced"]["policy_version"] == (
            "twos.post_apply_verification.v2"
        )
        yield VerifiedApplyFixture(
            fixture=fixture,
            applied=applied,
            verification=verification,
        )


def _commit_plan_url(verification_id: str) -> str:
    return f"/api/post-apply-verifications/{verification_id}/commit-plans"


def _stage_url(plan_id: str) -> str:
    return f"/api/commit-plans/{plan_id}/stage-sessions"


def _commit_url(stage_id: str) -> str:
    return f"/api/stage-sessions/{stage_id}/local-commits"


def _api_review_plan(fixture: VerifiedApplyFixture):
    return fixture.client.post(
        _commit_plan_url(str(fixture.verification["id"])),
        json={
            "expected_verification_digest": fixture.verification["advanced"][
                "verification_digest"
            ],
            "subject": COMMIT_SUBJECT,
            "body": COMMIT_BODY,
        },
    )


def _api_stage(fixture: VerifiedApplyFixture, plan: dict[str, object]):
    return fixture.client.post(
        _stage_url(str(plan["id"])),
        json={
            "confirmation": STAGE_CONFIRMATION,
            "expected_plan_digest": plan["advanced"]["plan_digest"],
        },
    )


def _api_commit(
    fixture: VerifiedApplyFixture,
    plan: dict[str, object],
    stage: dict[str, object],
):
    return fixture.client.post(
        _commit_url(str(stage["id"])),
        json={
            "confirmation": COMMIT_CONFIRMATION,
            "expected_plan_digest": plan["advanced"]["plan_digest"],
            "expected_stage_digest": stage["stage_digest"],
        },
    )


def _head(repo: Path) -> str:
    return run_command(repo, "git", "rev-parse", "HEAD").stdout.strip()


def _branch(repo: Path) -> str:
    return run_command(repo, "git", "branch", "--show-current").stdout.strip()


def _staged_paths(repo: Path) -> list[str]:
    output = run_command(
        repo,
        "git",
        "diff",
        "--cached",
        "--name-only",
        "-z",
    ).stdout
    return [path for path in output.split("\0") if path]


def _commit_changed_paths(repo: Path, commit_oid: str) -> list[str]:
    output = run_command(
        repo,
        "git",
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "-r",
        "-z",
        commit_oid,
    ).stdout
    return [path for path in output.split("\0") if path]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _verification_row(session, fixture: VerifiedApplyFixture) -> PostApplyVerification:
    row = session.scalar(
        select(PostApplyVerification).where(
            PostApplyVerification.verification_id == fixture.verification["id"]
        )
    )
    assert row is not None
    return row


def _review_plan(
    fixture: VerifiedApplyFixture,
    *,
    subject: str = COMMIT_SUBJECT,
    body: str = COMMIT_BODY,
) -> tuple[dict[str, object], bool]:
    with fixture.factory() as session:
        row, created = get_or_create_commit_plan(
            session,
            owner_id=fixture.owner_id,
            post_apply_verification=_verification_row(session, fixture),
            source_repo=fixture.source_repo,
            subject=subject,
            body=body,
        )
        session.commit()
        return commit_plan_out(row), created


def _stage_plan(
    fixture: VerifiedApplyFixture,
    plan: dict[str, object],
) -> tuple[dict[str, object], bool]:
    with fixture.factory() as session:
        row = session.scalar(
            select(CommitPlan).where(CommitPlan.commit_plan_id == plan["id"])
        )
        assert row is not None
        execution, created = stage_commit_plan(
            session,
            owner_id=fixture.owner_id,
            plan=row,
            source_repo=fixture.source_repo,
            expected_plan_digest=str(plan["advanced"]["plan_digest"]),
        )
        return {
            "id": execution.stage_execution_id,
            "state": execution.state,
            "stage_digest": execution.stage_digest,
            "staged_entries": json.loads(execution.staged_entries_json),
        }, created


def _create_commit(
    fixture: VerifiedApplyFixture,
    plan: dict[str, object],
    stage: dict[str, object],
) -> tuple[dict[str, object], bool]:
    with fixture.factory() as session:
        plan_row = session.scalar(
            select(CommitPlan).where(CommitPlan.commit_plan_id == plan["id"])
        )
        stage_row = session.scalar(
            select(StageExecution).where(
                StageExecution.stage_execution_id == stage["id"]
            )
        )
        assert plan_row is not None
        assert stage_row is not None
        execution, created = create_local_commit(
            session,
            owner_id=fixture.owner_id,
            plan=plan_row,
            stage_execution=stage_row,
            source_repo=fixture.source_repo,
            expected_plan_digest=str(plan["advanced"]["plan_digest"]),
            expected_stage_digest=str(stage["stage_digest"]),
        )
        return {
            "id": execution.commit_execution_id,
            "state": execution.state,
            "commit_oid": execution.commit_oid,
            "parent_oid": execution.parent_oid,
            "tree_oid": execution.tree_oid,
            "receipt_digest": execution.receipt_digest,
        }, created


def _error_code(call) -> str:
    with pytest.raises(CommitBuilderError) as caught:
        call()
    return caught.value.code


def _api_error_code(response) -> str:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("code") or "")
    error = payload.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        if isinstance(details, dict):
            return str(details.get("code") or "")
        return str(error.get("code") or "")
    return ""


def _without_request_id(response) -> dict[str, object]:
    payload = response.json()
    error = payload.get("error")
    if isinstance(error, dict):
        payload = dict(payload)
        payload["error"] = {
            key: value for key, value in error.items() if key != "request_id"
        }
    return payload


def _persist_newer_blocked_verification(
    session,
    *,
    fixture: VerifiedApplyFixture,
    owner_id: int,
    verification: PostApplyVerification,
) -> str:
    apply_session = session.get(ApplySession, verification.apply_session_id)
    assert apply_session is not None
    newer, created = get_or_create_post_apply_verification(
        session,
        owner_id=owner_id,
        apply_session=apply_session,
        source_repo=fixture.source_repo,
        expected_journal_digest=apply_session.journal_digest,
    )
    assert created is True
    assert newer.status == "BLOCKED"
    assert newer.id != verification.id
    session.commit()
    return newer.verification_id


def _inject_newer_blocked_verification_on_third_binding(
    fixture: VerifiedApplyFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[int], list[str]]:
    original = commit_builder_service._bound_verification
    binding_calls: list[int] = []
    injected_verifications: list[str] = []

    def inject(session, *, owner_id, verification):
        binding_calls.append(int(verification.id))
        if len(binding_calls) == 3:
            injected_verifications.append(
                _persist_newer_blocked_verification(
                    session,
                    fixture=fixture,
                    owner_id=owner_id,
                    verification=verification,
                )
            )
        return original(
            session,
            owner_id=owner_id,
            verification=verification,
        )

    monkeypatch.setattr(commit_builder_service, "_bound_verification", inject)
    return binding_calls, injected_verifications


def _inject_newer_blocked_verification_on_first_refresh(
    fixture: VerifiedApplyFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[int], list[str]]:
    original = commit_builder_service._refresh_latest_plan_verification
    refresh_calls: list[int] = []
    injected_verifications: list[str] = []

    def inject(session, *, owner_id, plan):
        refresh_calls.append(int(plan.id))
        if len(refresh_calls) == 1:
            verification = session.get(
                PostApplyVerification,
                plan.post_apply_verification_id,
            )
            assert verification is not None
            injected_verifications.append(
                _persist_newer_blocked_verification(
                    session,
                    fixture=fixture,
                    owner_id=owner_id,
                    verification=verification,
                )
            )
        return original(session, owner_id=owner_id, plan=plan)

    monkeypatch.setattr(
        commit_builder_service,
        "_refresh_latest_plan_verification",
        inject,
    )
    return refresh_calls, injected_verifications


def test_review_stage_and_local_commit_are_explicit_exact_and_idempotent(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        initial_head = _head(fixture.source_repo)
        initial_branch = _branch(fixture.source_repo)
        initial_boundary = _git_boundary(fixture.source_repo)

        with fixture.factory() as session:
            review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
        assert review["eligibility"] == {
            "status": "READY",
            "can_review": True,
            "next_action": "Review Commit Plan.",
            "blockers": [],
        }
        assert review["plan"] is None
        assert _git_boundary(fixture.source_repo) == initial_boundary

        plan, created = _review_plan(fixture)
        assert created is True
        assert plan["status"] == "READY"
        assert plan["status_at_creation"] == "READY"
        assert plan["subject"] == COMMIT_SUBJECT
        assert plan["body"] == COMMIT_BODY
        assert plan["actions"] == {"can_stage": True, "can_commit": False}
        assert plan["advanced"]["policy_version"] == COMMIT_BUILDER_POLICY_VERSION
        assert {
            (item["path"], item["operation"]) for item in plan["verified_paths"]
        } == {
            ("created.txt", "CREATE"),
            ("modify.txt", "MODIFY"),
            ("delete.txt", "DELETE"),
            ("asset.bin", "MODIFY"),
        }
        assert _git_boundary(fixture.source_repo) == initial_boundary

        repeated, repeated_created = _review_plan(fixture)
        assert repeated_created is False
        assert repeated == plan
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 0
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0

        stage, stage_created = _stage_plan(fixture, plan)
        assert stage_created is True
        assert stage["state"] == "STAGED"
        assert stage["stage_digest"]
        assert _head(fixture.source_repo) == initial_head
        assert _branch(fixture.source_repo) == initial_branch
        assert _staged_paths(fixture.source_repo) == [
            "asset.bin",
            "created.txt",
            "delete.txt",
            "modify.txt",
        ]
        assert {
            (item["path"], item["operation"], item["present"])
            for item in stage["staged_entries"]
        } == {
            ("created.txt", "CREATE", True),
            ("modify.txt", "MODIFY", True),
            ("delete.txt", "DELETE", False),
            ("asset.bin", "MODIFY", True),
        }
        repeated_stage, repeated_stage_created = _stage_plan(fixture, plan)
        assert repeated_stage_created is False
        assert repeated_stage == stage
        assert _head(fixture.source_repo) == initial_head

        commit, commit_created = _create_commit(fixture, plan, stage)
        assert commit_created is True
        assert commit["state"] == "COMMITTED"
        assert commit["parent_oid"] == initial_head
        assert commit["commit_oid"] == _head(fixture.source_repo)
        assert commit["tree_oid"]
        assert commit["receipt_digest"]
        assert _branch(fixture.source_repo) == initial_branch
        assert _staged_paths(fixture.source_repo) == []
        assert _commit_changed_paths(
            fixture.source_repo,
            str(commit["commit_oid"]),
        ) == ["asset.bin", "created.txt", "delete.txt", "modify.txt"]
        assert run_command(
            fixture.source_repo,
            "git",
            "show",
            "-s",
            "--format=%B",
            str(commit["commit_oid"]),
        ).stdout == COMMIT_SUBJECT + "\n\n" + COMMIT_BODY + "\n\n"
        assert run_command(
            fixture.source_repo,
            "git",
            "show",
            f"{commit['commit_oid']}:created.txt",
        ).stdout == "created by run\n"
        assert run_command(
            fixture.source_repo,
            "git",
            "show",
            f"{commit['commit_oid']}:asset.bin",
        ).stdout.encode("latin-1") == b"\x00\x10\x02\x03\x04"
        committed_tree_paths = run_command(
            fixture.source_repo,
            "git",
            "ls-tree",
            "-r",
            "--name-only",
            str(commit["commit_oid"]),
        ).stdout.splitlines()
        assert "delete.txt" not in committed_tree_paths

        repeated_commit, repeated_commit_created = _create_commit(
            fixture,
            plan,
            stage,
        )
        assert repeated_commit_created is False
        assert repeated_commit == commit
        assert _head(fixture.source_repo) == commit["commit_oid"]
        final_boundary = _git_boundary(fixture.source_repo)
        assert final_boundary["branch"] == initial_boundary["branch"]
        assert final_boundary["remotes"] == initial_boundary["remotes"]
        assert final_boundary["config"] == initial_boundary["config"]
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 1
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 1


def test_mutation_response_projection_uses_exact_durable_result_without_relocking(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        review_response = _api_review_plan(fixture)
        assert review_response.status_code == 200, review_response.text
        reviewed = review_response.json()
        plan = reviewed["plan"]
        assert reviewed["action_state"] == "READY_TO_STAGE"

        original_lock = commit_builder_service._repository_mutation_lock

        @contextmanager
        def unavailable_after_mutation(_repository_identity):
            raise commit_builder_service.ApplySessionError(
                "CONCURRENT_APPLY",
                "a concurrent read owns the repository lock",
            )
            yield  # pragma: no cover

        stage, created = _stage_plan(fixture, plan)
        assert created is True
        with fixture.factory() as session:
            projected = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
                effective_status_override="STAGED",
            )
        assert projected["eligibility"]["status"] == "STAGED"
        assert projected["actions"]["can_create_local_commit"] is True

        monkeypatch_context = pytest.MonkeyPatch()
        monkeypatch_context.setattr(
            commit_builder_service,
            "_repository_mutation_lock",
            unavailable_after_mutation,
        )
        try:
            with fixture.factory() as session:
                projected_under_contention = commit_builder_review(
                    session,
                    owner_id=fixture.owner_id,
                    post_apply_verification=_verification_row(session, fixture),
                    source_repo=fixture.source_repo,
                    effective_status_override="STAGED",
                )
                with pytest.raises(CommitBuilderError) as caught:
                    commit_builder_review(
                        session,
                        owner_id=fixture.owner_id,
                        post_apply_verification=_verification_row(session, fixture),
                        source_repo=fixture.source_repo,
                    )
            assert caught.value.code == "REPOSITORY_MUTATION_ACTIVE"
        finally:
            monkeypatch_context.undo()
        assert projected_under_contention["eligibility"]["status"] == "STAGED"

        commit, commit_created = _create_commit(fixture, plan, stage)
        assert commit_created is True
        with fixture.factory() as session:
            committed_projection = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
                effective_status_override="COMMITTED",
            )
        assert committed_projection["eligibility"]["status"] == "COMMITTED"
        assert committed_projection["commit"]["commit_oid"] == commit["commit_oid"]
        assert original_lock is commit_builder_service._repository_mutation_lock


def test_stage_and_commit_api_responses_do_not_reobserve_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful mutation response is projected from its durable receipt.

    The effective-status observer takes the repository lock.  Making that
    observer fail after Review proves both POST routes use the exact successful
    Stage/Commit result instead of racing a polling GET for a second lock.
    """
    with verified_apply_fixture(tmp_path) as fixture:
        reviewed_response = _api_review_plan(fixture)
        assert reviewed_response.status_code == 200, reviewed_response.text
        reviewed = reviewed_response.json()
        plan = reviewed["plan"]
        assert reviewed["action_state"] == "READY_TO_STAGE"

        observer_calls = 0

        def reject_post_mutation_reobservation(*_args, **_kwargs):
            nonlocal observer_calls
            observer_calls += 1
            raise AssertionError(
                "mutation POST response reacquired the repository observer"
            )

        monkeypatch.setattr(
            commit_builder_service,
            "commit_plan_effective_status",
            reject_post_mutation_reobservation,
        )

        stage_response = _api_stage(fixture, plan)
        assert stage_response.status_code == 200, stage_response.text
        staged = stage_response.json()
        assert staged["action_state"] == "READY_TO_COMMIT"
        assert staged["eligibility"]["status"] == "STAGED"
        assert staged["stage"]["state"] == "STAGED"
        assert staged["actions"] == {
            "can_review_commit_plan": True,
            "can_stage_approved_files": False,
            "can_create_local_commit": True,
        }

        commit_response = _api_commit(
            fixture,
            plan,
            staged["stage"],
        )
        assert commit_response.status_code == 200, commit_response.text
        committed = commit_response.json()
        assert committed["action_state"] == "COMMITTED"
        assert committed["eligibility"]["status"] == "COMMITTED"
        assert committed["commit"]["state"] == "COMMITTED"
        assert committed["actions"] == {
            "can_review_commit_plan": False,
            "can_stage_approved_files": False,
            "can_create_local_commit": False,
        }
        assert observer_calls == 0


def test_stage_receipt_survives_ordinary_status_stat_cache_refresh(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, created = _stage_plan(fixture, plan)
        assert created is True

        with fixture.factory() as session:
            stored = session.scalar(select(StageExecution))
            assert stored is not None
            post_stage = json.loads(stored.post_stage_evidence_json)
            stored_index_fingerprint = post_stage["index"]["fingerprint"]
            staged_entries = json.loads(stored.staged_entries_json)

        index_path = Path(
            run_command(
                fixture.source_repo,
                "git",
                "rev-parse",
                "--git-path",
                "index",
            ).stdout.strip()
        )
        if not index_path.is_absolute():
            index_path = fixture.source_repo / index_path
        before_status = hashlib.sha256(index_path.read_bytes()).hexdigest()
        assert before_status == stored_index_fingerprint

        status_environment = os.environ.copy()
        status_environment["GIT_OPTIONAL_LOCKS"] = "1"
        refreshed = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "status", "--porcelain"],
            cwd=fixture.source_repo,
            capture_output=True,
            text=True,
            check=False,
            env=status_environment,
        )
        assert refreshed.returncode == 0, refreshed.stderr
        assert hashlib.sha256(index_path.read_bytes()).hexdigest() == before_status
        assert _staged_paths(fixture.source_repo) == sorted(
            (str(item["path"]) for item in staged_entries),
            key=lambda value: value.encode("utf-8"),
        )
        for item in staged_entries:
            indexed = subprocess.run(
                ["git", "ls-files", "--stage", "--", str(item["path"])],
                cwd=fixture.source_repo,
                capture_output=True,
                text=True,
                check=False,
                env=status_environment,
            )
            assert indexed.returncode == 0, indexed.stderr
            if item["present"] is False:
                assert indexed.stdout == ""
            else:
                metadata, observed_path = indexed.stdout.rstrip("\n").split("\t", 1)
                observed_mode, observed_oid, observed_stage = metadata.split(" ")
                assert observed_path == item["path"]
                assert observed_mode == item["mode"]
                assert observed_oid == item["blob_oid"]
                assert observed_stage == "0"

        with fixture.factory() as session:
            reviewed = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
        assert reviewed["eligibility"]["status"] == "STAGED"
        assert reviewed["actions"]["can_create_local_commit"] is True

        commit, commit_created = _create_commit(fixture, plan, stage)
        assert commit_created is True
        assert commit["commit_oid"] == _head(fixture.source_repo)
        assert _staged_paths(fixture.source_repo) == []


def test_commit_plan_message_is_immutable_and_review_never_mutates_git(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        before = _git_boundary(fixture.source_repo)
        plan, created = _review_plan(fixture)
        assert created is True
        assert _git_boundary(fixture.source_repo) == before

        code = _error_code(
            lambda: _review_plan(
                fixture,
                subject="Different immutable subject",
                body=COMMIT_BODY,
            )
        )
        assert code == "COMMIT_PLAN_ALREADY_EXISTS"
        assert _git_boundary(fixture.source_repo) == before
        with fixture.factory() as session:
            stored = session.scalar(select(CommitPlan))
            assert stored is not None
            assert stored.commit_plan_id == plan["id"]
            assert stored.subject == COMMIT_SUBJECT
            assert stored.body == COMMIT_BODY
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1


def test_newer_blocked_verification_expires_the_immutable_reviewed_plan(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        original_digest = plan["advanced"]["plan_digest"]
        (fixture.source_repo / "modify.txt").write_bytes(
            b"changed after the passed Post-Apply Verification\n"
        )
        newer_response = _post_verification(fixture.fixture, fixture.applied)
        assert newer_response.status_code == 200, newer_response.text
        newer = newer_response.json()["verification"]
        assert newer["id"] != fixture.verification["id"]
        assert newer["status"] == "BLOCKED"

        review = fixture.client.get(
            _commit_plan_url(str(fixture.verification["id"]))
        )
        assert review.status_code == 200, review.text
        reviewed_plan = review.json()["plan"]
        assert reviewed_plan["id"] == plan["id"]
        assert reviewed_plan["status_at_creation"] == "READY"
        assert reviewed_plan["status"] == "BLOCKED"
        assert reviewed_plan["advanced"]["plan_digest"] == original_digest
        assert review.json()["actions"]["can_stage_approved_files"] is False

        blocked_stage = _api_stage(fixture, plan)
        assert blocked_stage.status_code == 409
        assert _api_error_code(blocked_stage) == "VERIFICATION_SUPERSEDED"
        with fixture.factory() as session:
            stored = session.scalar(select(CommitPlan))
            assert stored is not None
            assert stored.plan_digest == original_digest
            assert stored.status_at_creation == "READY"
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 0


def test_post_apply_verification_digest_must_recompute_before_plan_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        monkeypatch.setattr(
            commit_builder_service,
            "_verification_digest",
            lambda _verification: "0" * 64,
        )

        assert _error_code(lambda: _review_plan(fixture)) == (
            "VERIFICATION_INTEGRITY_BLOCKED"
        )
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 0


def test_api_requires_three_separate_owner_actions_and_gets_are_read_only(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        verification_url = _commit_plan_url(str(fixture.verification["id"]))
        before = _git_boundary(fixture.source_repo)

        initial = fixture.client.get(verification_url)
        assert initial.status_code == 200, initial.text
        assert initial.json()["plan"] is None
        assert initial.json()["actions"] == {
            "can_review_commit_plan": True,
            "can_stage_approved_files": False,
            "can_create_local_commit": False,
        }
        assert _git_boundary(fixture.source_repo) == before

        stale = fixture.client.post(
            verification_url,
            json={
                "expected_verification_digest": "0" * 64,
                "subject": COMMIT_SUBJECT,
                "body": COMMIT_BODY,
            },
        )
        assert stale.status_code == 409
        assert _api_error_code(stale) == "VERIFICATION_CHANGED"
        assert _git_boundary(fixture.source_repo) == before

        planned_response = _api_review_plan(fixture)
        assert planned_response.status_code == 200, planned_response.text
        planned = planned_response.json()
        plan = planned["plan"]
        assert planned["actions"] == {
            "can_review_commit_plan": True,
            "can_stage_approved_files": True,
            "can_create_local_commit": False,
        }
        assert planned["stage"] is None
        assert planned["commit"] is None
        assert _git_boundary(fixture.source_repo) == before

        wrong_stage = fixture.client.post(
            _stage_url(str(plan["id"])),
            json={
                "confirmation": "CREATE_LOCAL_COMMIT",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
            },
        )
        assert wrong_stage.status_code == 422
        assert _git_boundary(fixture.source_repo) == before

        staged_response = _api_stage(fixture, plan)
        assert staged_response.status_code == 200, staged_response.text
        staged = staged_response.json()
        stage = staged["stage"]
        assert staged["actions"] == {
            "can_review_commit_plan": True,
            "can_stage_approved_files": False,
            "can_create_local_commit": True,
        }
        assert staged["commit"] is None
        assert _head(fixture.source_repo) == plan["advanced"]["base_head"]

        stage_get_boundary = _git_boundary(fixture.source_repo)
        loaded = fixture.client.get(_stage_url(str(plan["id"])))
        assert loaded.status_code == 200
        assert loaded.json()["stage"]["id"] == stage["id"]
        assert _git_boundary(fixture.source_repo) == stage_get_boundary

        wrong_commit = fixture.client.post(
            _commit_url(str(stage["id"])),
            json={
                "confirmation": "STAGE_APPROVED_FILES",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_stage_digest": stage["stage_digest"],
            },
        )
        assert wrong_commit.status_code == 422
        assert _head(fixture.source_repo) == plan["advanced"]["base_head"]

        committed_response = _api_commit(fixture, plan, stage)
        assert committed_response.status_code == 200, committed_response.text
        committed = committed_response.json()
        assert committed["commit"]["state"] == "COMMITTED"
        assert committed["commit"]["commit_oid"] == _head(fixture.source_repo)
        commit_oid = committed["commit"]["commit_oid"]

        repeated = _api_commit(fixture, plan, stage)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["commit"]["commit_oid"] == commit_oid
        assert _head(fixture.source_repo) == commit_oid
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 1
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 1


def test_runtime_restart_recovers_stage_and_repeated_commit_without_duplicates(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path / "fixture") as fixture:
        planned_response = _api_review_plan(fixture)
        assert planned_response.status_code == 200, planned_response.text
        plan = planned_response.json()["plan"]
        staged_response = _api_stage(fixture, plan)
        assert staged_response.status_code == 200, staged_response.text
        stage = staged_response.json()["stage"]

        restarted = make_client(
            tmp_path / "restart-one",
            fixture.source_repo,
            tmp_path / "codex-must-not-be-invoked",
            database_path=fixture.fixture.candidate.database_path,
        )
        restarted.__enter__()
        try:
            init_and_login(restarted)
            recovered = restarted.get(_stage_url(str(plan["id"])))
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["stage"]["id"] == stage["id"]
            assert recovered.json()["commit"] is None
            committed = restarted.post(
                _commit_url(str(stage["id"])),
                json={
                    "confirmation": COMMIT_CONFIRMATION,
                    "expected_plan_digest": plan["advanced"]["plan_digest"],
                    "expected_stage_digest": stage["stage_digest"],
                },
            )
            assert committed.status_code == 200, committed.text
            commit_oid = committed.json()["commit"]["commit_oid"]
            assert commit_oid == _head(fixture.source_repo)
            repeated = restarted.post(
                _commit_url(str(stage["id"])),
                json={
                    "confirmation": COMMIT_CONFIRMATION,
                    "expected_plan_digest": plan["advanced"]["plan_digest"],
                    "expected_stage_digest": stage["stage_digest"],
                },
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["commit"]["commit_oid"] == commit_oid
            with restarted.app.state.session_factory() as session:
                assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1
                assert session.scalar(
                    select(func.count()).select_from(StageExecution)
                ) == 1
                assert session.scalar(
                    select(func.count()).select_from(LocalCommitExecution)
                ) == 1
        finally:
            restarted.__exit__(None, None, None)


def test_commit_workflow_api_is_authenticated_and_owner_isolated(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        planned_response = _api_review_plan(fixture)
        assert planned_response.status_code == 200, planned_response.text
        plan = planned_response.json()["plan"]
        staged_response = _api_stage(fixture, plan)
        assert staged_response.status_code == 200, staged_response.text
        stage = staged_response.json()["stage"]
        urls_and_payloads = [
            (
                _commit_plan_url(str(fixture.verification["id"])),
                {
                    "expected_verification_digest": fixture.verification["advanced"][
                        "verification_digest"
                    ],
                    "subject": COMMIT_SUBJECT,
                    "body": COMMIT_BODY,
                },
            ),
            (
                _stage_url(str(plan["id"])),
                {
                    "confirmation": STAGE_CONFIRMATION,
                    "expected_plan_digest": plan["advanced"]["plan_digest"],
                },
            ),
            (
                _commit_url(str(stage["id"])),
                {
                    "confirmation": COMMIT_CONFIRMATION,
                    "expected_plan_digest": plan["advanced"]["plan_digest"],
                    "expected_stage_digest": stage["stage_digest"],
                },
            ),
        ]

        fixture.client.cookies.clear()
        for url, payload in urls_and_payloads:
            assert fixture.client.get(url).status_code == 401
            assert fixture.client.post(url, json=payload).status_code == 401

        raw_token = "phase18-4a-second-owner-token"
        password_hash, password_salt = hash_password("second-owner-password")
        with fixture.factory() as session:
            second_owner = User(
                username="phase18-4a-second-owner",
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
        missing_urls = [
            _commit_plan_url("pav_" + "0" * 40),
            _stage_url("cplan_" + "0" * 40),
            _commit_url("stage_" + "0" * 40),
        ]
        for (url, payload), missing_url in zip(
            urls_and_payloads,
            missing_urls,
            strict=True,
        ):
            wrong_get = fixture.client.get(url, headers=headers)
            absent_get = fixture.client.get(missing_url, headers=headers)
            wrong_post = fixture.client.post(url, json=payload, headers=headers)
            absent_post = fixture.client.post(
                missing_url,
                json=payload,
                headers=headers,
            )
            assert {
                wrong_get.status_code,
                absent_get.status_code,
                wrong_post.status_code,
                absent_post.status_code,
            } == {404}
            assert _without_request_id(wrong_get) == _without_request_id(absent_get)
            assert _without_request_id(wrong_post) == _without_request_id(absent_post)
            assert wrong_get.json()["error"]["message"] == (
                "Commit workflow not found."
            )

        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0


def test_stage_and_commit_preserve_preexisting_unrelated_owner_changes(
    tmp_path: Path,
) -> None:
    candidate = build_candidate_fixture(tmp_path)
    try:
        run_root = _prepare_retained_run_material(candidate)
        modified = candidate.source_repo / "README.md"
        untracked = candidate.source_repo / "owner-notes.txt"
        modified.write_bytes(b"# unrelated owner work remains\n")
        untracked.write_bytes(b"private owner note remains\n")
        modified_before = modified.read_bytes()
        untracked_before = untracked.read_bytes()
        assert candidate.client.post(candidate_url(candidate)).status_code == 200
        plan_response = candidate.client.post(apply_plan_url(candidate))
        assert plan_response.status_code == 200, plan_response.text
        apply_fixture = ApplyRevertFixture(
            candidate=candidate,
            run_worktree=run_root,
            plan=plan_response.json()["plan"],
        )
        assert apply_fixture.plan["effective_state"] == "review_with_source_changes"
        applied, created = _apply(apply_fixture)
        assert created is True
        assert applied["state"] == "APPLIED"
        verification_response = _post_verification(apply_fixture, applied)
        assert verification_response.status_code == 200, verification_response.text
        verification = verification_response.json()["verification"]
        assert verification["status"] == "PASSED"
        fixture = VerifiedApplyFixture(apply_fixture, applied, verification)

        commit_plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, commit_plan)
        commit, _ = _create_commit(fixture, commit_plan, stage)

        assert modified.read_bytes() == modified_before
        assert untracked.read_bytes() == untracked_before
        assert set(_commit_changed_paths(fixture.source_repo, str(commit["commit_oid"]))) == {
            "asset.bin",
            "created.txt",
            "delete.txt",
            "modify.txt",
        }
        status = run_command(
            fixture.source_repo,
            "git",
            "status",
            "--short",
            "--untracked-files=all",
        ).stdout.splitlines()
        assert " M README.md" in status
        assert "?? owner-notes.txt" in status
        assert _staged_paths(fixture.source_repo) == []
    finally:
        close_candidate_fixture(candidate)


def test_git_plumbing_stages_literal_pathspec_magic_and_leading_dash_paths(
    tmp_path: Path,
) -> None:
    magic_path = ":(glob)*.txt"
    dash_path = "--owner-executable"
    magic_payload = b"literal pathspec magic must be exact\n"
    dash_payload = b"leading dash executable must be exact\n"
    records = [
        create_manifest_entry(magic_path, magic_payload),
        create_manifest_entry(dash_path, dash_payload, mode=0o755),
    ]
    with verified_apply_fixture(
        tmp_path,
        manifest_records=records,
        postimages={magic_path: magic_payload, dash_path: dash_payload},
        after_modes={dash_path: 0o755},
    ) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        assert set(_staged_paths(fixture.source_repo)) == {magic_path, dash_path}
        assert {item["path"] for item in stage["staged_entries"]} == {
            magic_path,
            dash_path,
        }

        commit, _ = _create_commit(fixture, plan, stage)

        assert set(
            _commit_changed_paths(fixture.source_repo, str(commit["commit_oid"]))
        ) == {magic_path, dash_path}
        assert (fixture.source_repo / magic_path).read_bytes() == magic_payload
        assert (fixture.source_repo / dash_path).read_bytes() == dash_payload
        tree_rows = run_command(
            fixture.source_repo,
            "git",
            "ls-tree",
            "-r",
            "--format=%(objectmode) %(path)",
            str(commit["commit_oid"]),
        ).stdout.splitlines()
        assert f"100644 {magic_path}" in tree_rows
        assert f"100755 {dash_path}" in tree_rows


def test_commit_message_exact_byte_limits_and_sensitive_content_are_rejected() -> None:
    assert MAX_COMMIT_SUBJECT_BYTES == 200
    assert MAX_COMMIT_BODY_BYTES == 4_000
    assert _safe_message("s" * 200, "b" * 4_000) == (
        "s" * 200,
        "b" * 4_000,
    )
    assert _safe_message("界" * 66, "") == ("界" * 66, "")

    assert _error_code(lambda: _safe_message("s" * 201, "")) == (
        "COMMIT_MESSAGE_INVALID"
    )
    assert _error_code(lambda: _safe_message("界" * 67, "")) == (
        "COMMIT_MESSAGE_INVALID"
    )
    assert _error_code(lambda: _safe_message("subject", "b" * 4_001)) == (
        "COMMIT_MESSAGE_INVALID"
    )
    assert _error_code(
        lambda: _safe_message("subject", "api_key=fixture-secret-value-123456")
    ) == "COMMIT_MESSAGE_SENSITIVE"


def test_review_commit_plan_api_enforces_exact_utf8_message_boundaries(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        url = _commit_plan_url(str(fixture.verification["id"]))
        digest = fixture.verification["advanced"]["verification_digest"]
        for subject, body in (
            ("s" * 201, ""),
            ("界" * 67, ""),
            ("subject", "b" * 4_001),
        ):
            response = fixture.client.post(
                url,
                json={
                    "expected_verification_digest": digest,
                    "subject": subject,
                    "body": body,
                },
            )
            assert response.status_code == 422, response.text
        sensitive = fixture.client.post(
            url,
            json={
                "expected_verification_digest": digest,
                "subject": "subject",
                "body": "password=fixture-sensitive-value-123456",
            },
        )
        assert sensitive.status_code == 409
        assert _api_error_code(sensitive) == "COMMIT_MESSAGE_SENSITIVE"
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 0

        accepted = fixture.client.post(
            url,
            json={
                "expected_verification_digest": digest,
                "subject": "s" * 200,
                "body": "b" * 4_000,
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["plan"]["subject"] == "s" * 200
        assert accepted.json()["plan"]["body"] == "b" * 4_000


def test_inherited_git_redirection_blocks_stage_and_commit_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        before_stage = _git_boundary(fixture.source_repo)
        redirected_index = tmp_path / "attacker-controlled-index"
        redirected_index.write_bytes(b"sentinel remains unchanged\n")
        sentinel = redirected_index.read_bytes()
        monkeypatch.setenv("GIT_INDEX_FILE", str(redirected_index))

        assert _error_code(lambda: _stage_plan(fixture, plan)) == (
            "GIT_ENVIRONMENT_BLOCKED"
        )
        monkeypatch.delenv("GIT_INDEX_FILE")
        assert _git_boundary(fixture.source_repo) == before_stage
        assert redirected_index.read_bytes() == sentinel

        stage, _ = _stage_plan(fixture, plan)
        head_before_commit = _head(fixture.source_repo)
        staged_before_commit = _staged_paths(fixture.source_repo)
        monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path))

        assert _error_code(lambda: _create_commit(fixture, plan, stage)) == (
            "GIT_ENVIRONMENT_BLOCKED"
        )
        monkeypatch.delenv("GIT_WORK_TREE")
        assert _head(fixture.source_repo) == head_before_commit
        assert _staged_paths(fixture.source_repo) == staged_before_commit
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0


def test_repository_lock_acquisition_failure_is_sanitized_for_review_stage_and_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        original_lock = commit_builder_service._repository_mutation_lock

        @contextmanager
        def unavailable_lock(_repository_identity):
            raise commit_builder_service.ApplySessionError(
                "CONCURRENT_APPLY",
                "unsafe lock detail /private/owner/path must not escape",
            )
            yield  # pragma: no cover

        def assert_sanitized(call) -> None:
            with pytest.raises(CommitBuilderError) as caught:
                call()
            assert caught.value.code == "REPOSITORY_MUTATION_ACTIVE"
            assert caught.value.message == "Another repository mutation is active."
            assert "/private/owner/path" not in str(caught.value)

        monkeypatch.setattr(
            commit_builder_service,
            "_repository_mutation_lock",
            unavailable_lock,
        )
        before_stage = _git_boundary(fixture.source_repo)
        with fixture.factory() as session:
            assert_sanitized(
                lambda: commit_builder_review(
                    session,
                    owner_id=fixture.owner_id,
                    post_apply_verification=_verification_row(session, fixture),
                    source_repo=fixture.source_repo,
                )
            )
        assert_sanitized(lambda: _stage_plan(fixture, plan))
        assert _git_boundary(fixture.source_repo) == before_stage

        monkeypatch.setattr(
            commit_builder_service,
            "_repository_mutation_lock",
            original_lock,
        )
        stage, _ = _stage_plan(fixture, plan)
        before_commit = _git_boundary(fixture.source_repo)
        monkeypatch.setattr(
            commit_builder_service,
            "_repository_mutation_lock",
            unavailable_lock,
        )
        assert_sanitized(lambda: _create_commit(fixture, plan, stage))
        assert _git_boundary(fixture.source_repo) == before_commit
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0


def test_newer_blocked_verification_after_stage_intent_blocks_before_index_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        before = _git_boundary(fixture.source_repo)
        binding_calls, injected = _inject_newer_blocked_verification_on_third_binding(
            fixture,
            monkeypatch,
        )

        assert _error_code(lambda: _stage_plan(fixture, plan)) == (
            "VERIFICATION_SUPERSEDED"
        )

        assert len(binding_calls) == 3
        assert len(injected) == 1
        assert _git_boundary(fixture.source_repo) == before
        assert _staged_paths(fixture.source_repo) == []
        with fixture.factory() as session:
            stage = session.scalar(select(StageExecution))
            assert stage is not None
            assert stage.state in {"STAGING", "FAILED"}
            assert stage.state != "STAGED"
            assert stage.stage_digest is None
            verifications = list(
                session.scalars(
                    select(PostApplyVerification).order_by(PostApplyVerification.id)
                ).all()
            )
            assert len(verifications) == 2
            assert verifications[-1].verification_id == injected[0]
            assert verifications[-1].status == "BLOCKED"
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0


def test_newer_blocked_verification_after_commit_intent_blocks_before_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        before_head = _head(fixture.source_repo)
        before_stage = _staged_paths(fixture.source_repo)
        before_boundary = _git_boundary(fixture.source_repo)
        binding_calls, injected = _inject_newer_blocked_verification_on_third_binding(
            fixture,
            monkeypatch,
        )

        assert _error_code(lambda: _create_commit(fixture, plan, stage)) == (
            "VERIFICATION_SUPERSEDED"
        )

        assert len(binding_calls) == 3
        assert len(injected) == 1
        assert _head(fixture.source_repo) == before_head
        assert _staged_paths(fixture.source_repo) == before_stage
        assert _git_boundary(fixture.source_repo) == before_boundary
        with fixture.factory() as session:
            execution = session.scalar(select(LocalCommitExecution))
            assert execution is not None
            assert execution.state in {"COMMITTING", "FAILED"}
            assert execution.state != "COMMITTED"
            assert execution.commit_oid is None
            assert execution.receipt_digest is None
            verifications = list(
                session.scalars(
                    select(PostApplyVerification).order_by(PostApplyVerification.id)
                ).all()
            )
            assert len(verifications) == 2
            assert verifications[-1].verification_id == injected[0]
            assert verifications[-1].status == "BLOCKED"


def test_commit_builder_uses_exact_git_plumbing_and_has_no_broad_add_commit_or_push() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "twos_runtime" / "commit_builder.py"
    ).read_text(encoding="utf-8")
    assert '"hash-object"' in source
    assert '"update-index"' in source
    assert '"write-tree"' in source
    assert '"commit-tree"' in source
    assert '"update-ref"' in source
    assert '"GIT_NO_LAZY_FETCH": "1"' in source
    assert '"GIT_OPTIONAL_LOCKS": "0"' in source
    assert '"GIT_LITERAL_PATHSPECS": "1"' in source
    assert '"core.hooksPath=/dev/null"' in source
    assert '"commit.gpgSign=false"' in source
    assert '"--no-filters"' in source
    assert re.search(r'_run_git\(\s*root,\s*"add"', source) is None
    assert re.search(r'_run_git\(\s*root,\s*"commit"', source) is None
    assert re.search(r'_run_git\(\s*root,\s*"push"', source) is None
    assert "git add ." not in source
    assert "git add -A" not in source
    assert "commit -a" not in source


def test_vol18_008_records_are_durable_unique_and_immutable_in_orm_and_sqlite(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        commit, _ = _create_commit(fixture, plan, stage)
        engine = fixture.client.app.state.engine

        with fixture.factory() as session:
            versions = set(session.scalars(select(SchemaVersion.version)).all())
            assert "vol18.008" in versions
            assert session.scalar(select(func.count()).select_from(CommitPlan)) == 1
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 1
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 1
            plan_row = session.scalar(select(CommitPlan))
            assert plan_row is not None
            plan_row.subject = "mutated subject"
            with pytest.raises(RuntimeError, match="append-only and immutable"):
                session.commit()
            session.rollback()

            stage_row = session.scalar(select(StageExecution))
            assert stage_row is not None
            stage_row.commit_plan_digest = "0" * 64
            with pytest.raises(RuntimeError, match="immutable binding fields"):
                session.commit()
            session.rollback()

            commit_row = session.scalar(select(LocalCommitExecution))
            assert commit_row is not None
            commit_row.stage_digest = "0" * 64
            with pytest.raises(RuntimeError, match="immutable binding fields"):
                session.commit()
            session.rollback()

        assert {
            "commit_plans",
            "stage_executions",
            "local_commit_executions",
        } <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            triggers = {
                name
                for name in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name IN ('commit_plans','stage_executions',"
                        "'local_commit_executions')"
                    )
                ).scalars()
            }
            assert {
                "trg_commit_plans_no_update",
                "trg_commit_plans_no_delete",
                "trg_stage_executions_core_no_update",
                "trg_stage_executions_set_once",
                "trg_stage_executions_no_delete",
                "trg_local_commit_executions_core_no_update",
                "trg_local_commit_executions_set_once",
                "trg_local_commit_executions_no_delete",
            } <= triggers
            for statement, parameters in (
                (
                    "UPDATE commit_plans SET subject = 'changed' "
                    "WHERE commit_plan_id = :public_id",
                    {"public_id": plan["id"]},
                ),
                (
                    "UPDATE stage_executions SET commit_plan_digest = :digest "
                    "WHERE stage_execution_id = :public_id",
                    {"digest": "0" * 64, "public_id": stage["id"]},
                ),
                (
                    "UPDATE local_commit_executions SET stage_digest = :digest "
                    "WHERE commit_execution_id = :public_id",
                    {"digest": "0" * 64, "public_id": commit["id"]},
                ),
            ):
                with pytest.raises(IntegrityError):
                    connection.execute(text(statement), parameters)
                connection.rollback()
            for table_name, public_column, public_id in (
                ("commit_plans", "commit_plan_id", plan["id"]),
                ("stage_executions", "stage_execution_id", stage["id"]),
                (
                    "local_commit_executions",
                    "commit_execution_id",
                    commit["id"],
                ),
            ):
                with pytest.raises(IntegrityError):
                    connection.execute(
                        text(
                            f"DELETE FROM {table_name} "
                            f"WHERE {public_column} = :public_id"
                        ),
                        {"public_id": public_id},
                    )
                connection.rollback()


def test_completed_prior_stage_is_not_a_mutation_blocker_for_a_later_plan(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        _create_commit(fixture, plan, stage)
        with fixture.factory() as session:
            prior = session.scalar(select(CommitPlan))
            assert prior is not None
            synthetic_later_plan = CommitPlan(
                id=prior.id + 100_000,
                repository_locator_fingerprint=prior.repository_locator_fingerprint,
            )

            assert _other_stage_blocker(
                session,
                plan=synthetic_later_plan,
            ) is None


def test_stale_session_is_refreshed_under_lock_before_commit_boundary_decision(
    tmp_path: Path,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        stale_session = fixture.factory()
        try:
            stale_plan = stale_session.scalar(
                select(CommitPlan).where(CommitPlan.commit_plan_id == plan["id"])
            )
            stale_stage = stale_session.scalar(
                select(StageExecution).where(
                    StageExecution.stage_execution_id == stage["id"]
                )
            )
            assert stale_plan is not None
            assert stale_stage is not None
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/tags/concurrent-owner-ref",
                "HEAD",
            )
            head_before = _head(fixture.source_repo)

            with pytest.raises(CommitBuilderError) as caught:
                create_local_commit(
                    stale_session,
                    owner_id=fixture.owner_id,
                    plan=stale_plan,
                    stage_execution=stale_stage,
                    source_repo=fixture.source_repo,
                    expected_plan_digest=str(plan["advanced"]["plan_digest"]),
                    expected_stage_digest=str(stage["stage_digest"]),
                )

            assert caught.value.code == "COMMIT_PLAN_EXPIRED"
            assert _head(fixture.source_repo) == head_before
            assert stale_session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0
        finally:
            stale_session.close()


def test_lost_stage_response_recovers_one_exact_stage_and_clears_active_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        original_verify = commit_builder_service._verify_exact_stage
        crash_count = 0

        def crash_after_index(*args, **kwargs):
            nonlocal crash_count
            crash_count += 1
            if crash_count == 1:
                raise KeyboardInterrupt("simulated lost Stage response")
            return original_verify(*args, **kwargs)

        monkeypatch.setattr(
            commit_builder_service,
            "_verify_exact_stage",
            crash_after_index,
        )
        with pytest.raises(KeyboardInterrupt, match="lost Stage response"):
            _stage_plan(fixture, plan)
        monkeypatch.setattr(
            commit_builder_service,
            "_verify_exact_stage",
            original_verify,
        )

        with fixture.factory() as session:
            pending = session.scalar(select(StageExecution))
            assert pending is not None
            assert pending.state == "STAGING"
            assert _stage_out(pending)["status_label"] == (
                "STAGE RECOVERY REQUIRED"
            )
            pending_id = pending.stage_execution_id
        assert set(_staged_paths(fixture.source_repo)) == {
            "asset.bin",
            "created.txt",
            "delete.txt",
            "modify.txt",
        }
        with fixture.factory() as session:
            pending_review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
        assert pending_review["actions"]["can_stage_approved_files"] is True
        assert {
            item["code"] for item in pending_review["eligibility"]["blockers"]
        } == {"STAGE_RECOVERY_REQUIRED"}

        recovered, created = _stage_plan(fixture, plan)
        assert created is False
        assert recovered["id"] == pending_id
        assert recovered["state"] == "STAGED"
        with fixture.factory() as session:
            row = session.scalar(select(StageExecution))
            assert row is not None
            public = _stage_out(row)
            assert public["blockers"] == []
            assert public["failure_evidence"] == []
            settled_review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
            assert settled_review["eligibility"]["blockers"] == []
            assert settled_review["actions"]["can_create_local_commit"] is True
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 1


def test_failed_stage_retry_preserves_history_but_has_no_active_success_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        original_boundary = commit_builder_service._current_boundary_locked
        boundary_count = 0

        def fail_after_intent(**kwargs):
            nonlocal boundary_count
            boundary_count += 1
            if boundary_count == 2:
                raise CommitBuilderError(
                    "GIT_COMMAND_FAILED",
                    "simulated bounded Stage failure",
                )
            return original_boundary(**kwargs)

        monkeypatch.setattr(
            commit_builder_service,
            "_current_boundary_locked",
            fail_after_intent,
        )
        assert _error_code(lambda: _stage_plan(fixture, plan)) == "GIT_COMMAND_FAILED"
        monkeypatch.setattr(
            commit_builder_service,
            "_current_boundary_locked",
            original_boundary,
        )
        with fixture.factory() as session:
            failed = session.scalar(select(StageExecution))
            assert failed is not None
            assert failed.state == "FAILED"
            assert json.loads(failed.failure_evidence_json) == [
                {"code": "GIT_COMMAND_FAILED"}
            ]

        recovered, created = _stage_plan(fixture, plan)
        assert created is False
        assert recovered["state"] == "STAGED"
        with fixture.factory() as session:
            public = _stage_out(session.scalar(select(StageExecution)))
            assert public["blockers"] == []
            assert public["advanced"]["historical_failure_evidence"] == [
                {"code": "GIT_COMMAND_FAILED"}
            ]


def test_commit_cas_lost_response_recovers_same_sha_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        original_finalize = commit_builder_service._finalize_commit_receipt

        def lose_after_cas(*args, **kwargs):
            raise KeyboardInterrupt("simulated response loss after CAS")

        monkeypatch.setattr(
            commit_builder_service,
            "_finalize_commit_receipt",
            lose_after_cas,
        )
        with pytest.raises(KeyboardInterrupt, match="response loss after CAS"):
            _create_commit(fixture, plan, stage)
        monkeypatch.setattr(
            commit_builder_service,
            "_finalize_commit_receipt",
            original_finalize,
        )

        with fixture.factory() as session:
            pending = session.scalar(select(LocalCommitExecution))
            assert pending is not None
            assert pending.state == "COMMITTING"
            assert pending.commit_oid == _head(fixture.source_repo)
            assert _commit_out(pending)["status_label"] == (
                "COMMIT RECOVERY REQUIRED"
            )
            pending_id = pending.commit_execution_id
            commit_oid = pending.commit_oid
            pending_review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
        assert pending_review["actions"]["can_create_local_commit"] is True
        assert {
            item["code"] for item in pending_review["eligibility"]["blockers"]
        } == {"COMMIT_RECOVERY_REQUIRED"}

        recovered, created = _create_commit(fixture, plan, stage)
        assert created is False
        assert recovered["id"] == pending_id
        assert recovered["commit_oid"] == commit_oid
        assert recovered["state"] == "COMMITTED"
        with fixture.factory() as session:
            row = session.scalar(select(LocalCommitExecution))
            assert row is not None
            public = _commit_out(row)
            assert public["blockers"] == []
            assert public["failure_evidence"] == []
            settled_review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
            assert settled_review["eligibility"]["status"] == "COMMITTED"
            assert settled_review["eligibility"]["blockers"] == []
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 1


def test_newer_blocked_verification_prevents_existing_stage_intent_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        original_verify = commit_builder_service._verify_exact_stage
        crash_count = 0

        def lose_after_exact_index(*args, **kwargs):
            nonlocal crash_count
            crash_count += 1
            if crash_count == 1:
                raise KeyboardInterrupt("simulated existing Stage intent")
            return original_verify(*args, **kwargs)

        monkeypatch.setattr(
            commit_builder_service,
            "_verify_exact_stage",
            lose_after_exact_index,
        )
        with pytest.raises(KeyboardInterrupt, match="existing Stage intent"):
            _stage_plan(fixture, plan)
        monkeypatch.setattr(
            commit_builder_service,
            "_verify_exact_stage",
            original_verify,
        )
        before_head = _head(fixture.source_repo)
        exact_index = _staged_paths(fixture.source_repo)
        refresh_calls, injected = _inject_newer_blocked_verification_on_first_refresh(
            fixture,
            monkeypatch,
        )

        assert _error_code(lambda: _stage_plan(fixture, plan)) == (
            "VERIFICATION_SUPERSEDED"
        )

        assert len(refresh_calls) == 1
        assert len(injected) == 1
        assert _head(fixture.source_repo) == before_head
        assert _staged_paths(fixture.source_repo) == exact_index
        with fixture.factory() as session:
            stage = session.scalar(select(StageExecution))
            assert stage is not None
            assert stage.state != "STAGED"
            assert stage.stage_digest is None
            latest = session.scalar(
                select(PostApplyVerification)
                .order_by(PostApplyVerification.id.desc())
                .limit(1)
            )
            assert latest is not None
            assert latest.verification_id == injected[0]
            assert latest.status == "BLOCKED"


def test_newer_blocked_verification_prevents_head_matched_commit_receipt_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        original_finalize = commit_builder_service._finalize_commit_receipt

        def lose_after_head_cas(*args, **kwargs):
            raise KeyboardInterrupt("simulated existing Commit receipt")

        monkeypatch.setattr(
            commit_builder_service,
            "_finalize_commit_receipt",
            lose_after_head_cas,
        )
        with pytest.raises(KeyboardInterrupt, match="existing Commit receipt"):
            _create_commit(fixture, plan, stage)
        monkeypatch.setattr(
            commit_builder_service,
            "_finalize_commit_receipt",
            original_finalize,
        )
        with fixture.factory() as session:
            pending = session.scalar(select(LocalCommitExecution))
            assert pending is not None
            assert pending.state == "COMMITTING"
            assert pending.commit_oid == _head(fixture.source_repo)
            pending_oid = pending.commit_oid
        refresh_calls, injected = _inject_newer_blocked_verification_on_first_refresh(
            fixture,
            monkeypatch,
        )

        assert _error_code(lambda: _create_commit(fixture, plan, stage)) == (
            "VERIFICATION_SUPERSEDED"
        )

        assert len(refresh_calls) == 1
        assert len(injected) == 1
        assert _head(fixture.source_repo) == pending_oid
        with fixture.factory() as session:
            execution = session.scalar(select(LocalCommitExecution))
            assert execution is not None
            assert execution.state != "COMMITTED"
            assert execution.receipt_digest is None
            latest = session.scalar(
                select(PostApplyVerification)
                .order_by(PostApplyVerification.id.desc())
                .limit(1)
            )
            assert latest is not None
            assert latest.verification_id == injected[0]
            assert latest.status == "BLOCKED"


def test_failed_commit_retry_preserves_history_but_has_no_active_success_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        original_snapshot = commit_builder_service._stable_index_snapshot

        @contextmanager
        def broken_snapshot(_root):
            raise OSError("simulated snapshot failure")
            yield  # pragma: no cover

        monkeypatch.setattr(
            commit_builder_service,
            "_stable_index_snapshot",
            broken_snapshot,
        )
        assert _error_code(lambda: _create_commit(fixture, plan, stage)) == (
            "COMMIT_FAILED"
        )
        monkeypatch.setattr(
            commit_builder_service,
            "_stable_index_snapshot",
            original_snapshot,
        )
        with fixture.factory() as session:
            failed = session.scalar(select(LocalCommitExecution))
            assert failed is not None
            assert failed.state == "FAILED"
            assert json.loads(failed.failure_evidence_json) == [
                {"code": "COMMIT_FAILED"}
            ]

        recovered, created = _create_commit(fixture, plan, stage)
        assert created is False
        assert recovered["state"] == "COMMITTED"
        with fixture.factory() as session:
            public = _commit_out(session.scalar(select(LocalCommitExecution)))
            assert public["blockers"] == []
            assert public["advanced"]["historical_failure_evidence"] == [
                {"code": "COMMIT_FAILED"}
            ]


def test_real_index_race_cannot_enter_the_snapshotted_commit_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        original_run_git = commit_builder_service._run_git
        injected = False

        def mutate_real_index_before_snapshot_write_tree(
            root,
            *args,
            input_bytes=None,
            check=True,
            timeout=60,
            index_file=None,
        ):
            nonlocal injected
            if args and args[0] == "write-tree" and index_file is not None and not injected:
                injected = True
                (root / "owner-index-race.txt").write_bytes(
                    b"must never enter the local Commit tree\n"
                )
                result = subprocess.run(
                    ["git", "add", "--", "owner-index-race.txt"],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                assert result.returncode == 0, result.stderr
            return original_run_git(
                root,
                *args,
                input_bytes=input_bytes,
                check=check,
                timeout=timeout,
                index_file=index_file,
            )

        monkeypatch.setattr(
            commit_builder_service,
            "_run_git",
            mutate_real_index_before_snapshot_write_tree,
        )
        assert _error_code(lambda: _create_commit(fixture, plan, stage)) == (
            "COMMIT_INTEGRITY_BLOCKED"
        )
        monkeypatch.setattr(
            commit_builder_service,
            "_run_git",
            original_run_git,
        )
        assert injected is True
        with fixture.factory() as session:
            execution = session.scalar(select(LocalCommitExecution))
            assert execution is not None
            assert execution.state == "INTEGRITY_BLOCKED"
            assert execution.commit_oid is not None
            blocked_review = commit_builder_review(
                session,
                owner_id=fixture.owner_id,
                post_apply_verification=_verification_row(session, fixture),
                source_repo=fixture.source_repo,
            )
            assert blocked_review["eligibility"]["status"] == "BLOCKED"
            assert {
                item["code"]
                for item in blocked_review["eligibility"]["blockers"]
            } == {"COMMIT_INTEGRITY_BLOCKED"}
            tree_paths = run_command(
                fixture.source_repo,
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                execution.commit_oid,
            ).stdout.splitlines()
        assert "owner-index-race.txt" not in tree_paths
        assert set(_commit_changed_paths(fixture.source_repo, execution.commit_oid)) == {
            "asset.bin",
            "created.txt",
            "delete.txt",
            "modify.txt",
        }
@pytest.mark.parametrize(
    "boundary",
    ["staged", "head", "branch", "refs", "remote", "config", "source", "symlink"],
)
def test_stage_blocks_repository_races_before_mutating_the_index(
    tmp_path: Path,
    boundary: str,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        if boundary == "staged":
            (fixture.source_repo / "README.md").write_bytes(
                b"owner staged a real unrelated change\n"
            )
            run_command(fixture.source_repo, "git", "add", "README.md")
        elif boundary == "head":
            run_command(
                fixture.source_repo,
                "git",
                "commit",
                "--allow-empty",
                "-m",
                "owner race after Commit Plan review",
            )
        elif boundary == "branch":
            run_command(fixture.source_repo, "git", "branch", "-m", "owner-race")
        elif boundary == "refs":
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/tags/owner-race",
                "HEAD",
            )
        elif boundary == "remote":
            run_command(
                fixture.source_repo,
                "git",
                "remote",
                "add",
                "owner-race",
                "https://example.invalid/owner/repository.git",
            )
        elif boundary == "config":
            run_command(
                fixture.source_repo,
                "git",
                "config",
                "owner.race",
                "true",
            )
        elif boundary == "source":
            (fixture.source_repo / "created.txt").write_bytes(b"owner changed applied file\n")
        else:
            outside = tmp_path / "outside-owner-file"
            outside.write_bytes(b"outside remains untouched\n")
            target = fixture.source_repo / "created.txt"
            target.unlink()
            target.symlink_to(outside)
        before_stage = _git_boundary(fixture.source_repo)

        code = _error_code(lambda: _stage_plan(fixture, plan))

        assert code in {"COMMIT_PLAN_EXPIRED", "BRANCH_CHANGED"}
        assert _git_boundary(fixture.source_repo) == before_stage
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(StageExecution)) == 0
            assert session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ) == 0


@pytest.mark.parametrize(
    "boundary",
    [
        "staged_target",
        "staged_extra",
        "unmerged",
        "head",
        "branch",
        "refs",
        "remote",
        "config",
        "source",
        "symlink",
    ],
)
def test_commit_blocks_index_and_repository_races_without_advancing_head(
    tmp_path: Path,
    boundary: str,
) -> None:
    with verified_apply_fixture(tmp_path) as fixture:
        plan, _ = _review_plan(fixture)
        stage, _ = _stage_plan(fixture, plan)
        base_head = _head(fixture.source_repo)
        if boundary == "staged_target":
            (fixture.source_repo / "modify.txt").write_bytes(b"owner staged different content\n")
            run_command(fixture.source_repo, "git", "add", "modify.txt")
        elif boundary == "staged_extra":
            (fixture.source_repo / "owner-extra.txt").write_bytes(b"never commit me\n")
            run_command(fixture.source_repo, "git", "add", "owner-extra.txt")
        elif boundary == "unmerged":
            blob_oid = run_command(
                fixture.source_repo,
                "git",
                "rev-parse",
                "HEAD:README.md",
            ).stdout.strip()
            result = subprocess.run(
                ["git", "update-index", "--index-info"],
                cwd=fixture.source_repo,
                input=(
                    f"100644 {blob_oid} 1\towner-conflict.txt\n"
                    f"100644 {blob_oid} 2\towner-conflict.txt\n"
                ),
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
        elif boundary == "head":
            run_command(
                fixture.source_repo,
                "git",
                "commit",
                "-m",
                "owner commit wins the race",
            )
        elif boundary == "branch":
            run_command(fixture.source_repo, "git", "branch", "-m", "owner-race")
        elif boundary == "refs":
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/tags/owner-race",
                "HEAD",
            )
        elif boundary == "remote":
            run_command(
                fixture.source_repo,
                "git",
                "remote",
                "add",
                "owner-race",
                "https://example.invalid/owner/repository.git",
            )
        elif boundary == "config":
            run_command(
                fixture.source_repo,
                "git",
                "config",
                "owner.race",
                "true",
            )
        elif boundary == "source":
            (fixture.source_repo / "created.txt").write_bytes(b"owner changed after Stage\n")
        else:
            outside = tmp_path / "outside-owner-file"
            outside.write_bytes(b"outside remains untouched\n")
            target = fixture.source_repo / "created.txt"
            target.unlink()
            target.symlink_to(outside)
        head_before_attempt = _head(fixture.source_repo)

        code = _error_code(lambda: _create_commit(fixture, plan, stage))

        assert code in {
            "STAGE_INTEGRITY_BLOCKED",
            "HEAD_CHANGED",
            "BRANCH_CHANGED",
            "COMMIT_PLAN_EXPIRED",
            "APPLIED_PATH_CHANGED",
        }
        assert _head(fixture.source_repo) == head_before_attempt
        if boundary != "head":
            assert _head(fixture.source_repo) == base_head
        with fixture.factory() as session:
            rows = list(session.scalars(select(LocalCommitExecution)).all())
            assert all(row.state != "COMMITTED" for row in rows)
