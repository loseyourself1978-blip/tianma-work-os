from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from tests.test_self_hosting import init_and_login, make_client, run_command
from tests.test_vol18_delivery_candidate import (
    CandidateFixture,
    build_candidate_fixture,
    candidate_url,
    close_candidate_fixture,
    git_index_artifact,
    source_boundary,
)
from twos_runtime.apply_plans import (
    APPLY_PLAN_READ_ONLY_GIT_ALLOWLIST,
    construct_path_decisions,
    effective_apply_plan_state,
    get_or_create_apply_plan,
    validate_apply_plan_integrity,
)
from twos_runtime.delivery_candidates import validate_delivery_candidate
from twos_runtime.models import (
    ApplyPlan,
    ApplyPlanEntry,
    CodexRun,
    DeliveryCandidate,
    SchemaVersion,
    SessionToken,
    SourceDriftEvaluation,
    User,
    utc_now,
)
from twos_runtime.security import hash_password, hash_token


def apply_plan_url(fixture: CandidateFixture) -> str:
    return f"/api/codex-runs/{fixture.run_id}/apply-plans"


def historical_plan_url(plan_id: str) -> str:
    return f"/api/apply-plans/{plan_id}"


@contextmanager
def phase18_fixture(tmp_path: Path, **options):
    fixture = build_candidate_fixture(tmp_path, **options)
    try:
        yield fixture
    finally:
        close_candidate_fixture(fixture)


def create_candidate(fixture: CandidateFixture) -> dict[str, object]:
    response = fixture.client.post(candidate_url(fixture))
    assert response.status_code == 200, response.text
    candidate = response.json()["candidate"]
    assert candidate is not None
    return candidate


def review_apply_plan(fixture: CandidateFixture) -> dict[str, object]:
    response = fixture.client.post(apply_plan_url(fixture))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == fixture.run_id
    assert isinstance(body["history"], list)
    plan = body["plan"]
    assert isinstance(plan, dict)
    return plan


def manifest_entry(path: object, operation: str) -> dict[str, object]:
    before = b"before\n"
    after = b"after\n"
    before_required = operation in {"MODIFY", "DELETE"}
    after_required = operation in {"CREATE", "MODIFY"}
    return {
        "path": path,
        "operation": operation,
        "unexpected": False,
        "before_hash": hashlib.sha256(before).hexdigest() if before_required else None,
        "after_hash": hashlib.sha256(after).hexdigest() if after_required else None,
        "before_size": len(before) if before_required else None,
        "after_size": len(after) if after_required else None,
        "before_mode": 0o644 if before_required else None,
        "after_mode": 0o644 if after_required else None,
        "content_kind": "text",
        "evidence_identity": "e" * 64,
    }


def plan_rows(factory) -> list[ApplyPlan]:
    with factory() as session:
        return list(
            session.scalars(
                select(ApplyPlan).order_by(ApplyPlan.plan_version, ApplyPlan.id)
            ).all()
        )


def test_ready_candidate_creates_complete_read_only_apply_plan(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        candidate = create_candidate(fixture)
        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "ready_for_owner_review"
        assert plan["status_at_creation"] == "ready_for_owner_review"
        assert plan["status_label"] == "READY FOR OWNER REVIEW"
        assert plan["candidate_status_label"] == "Available"
        assert plan["drift_status"] == "ready_to_apply"
        assert plan["drift_status_label"] == "Ready to apply"
        assert plan["candidate_entry_count"] == plan["classified_entry_count"] == 4
        assert len(plan["entries"]) == 4
        assert {item["disposition"] for item in plan["entries"]} == {"INCLUDED"}
        assert {item["operation"] for item in plan["entries"]} == {
            "CREATE",
            "MODIFY",
            "DELETE",
        }
        assert plan["blockers"] == []
        assert (
            plan["next_action"]
            == "Explicitly choose Apply Accepted Changes to run a fresh preflight and "
            "open the final source-mutation confirmation."
        )
        assert plan["advanced"]["candidate_id"] == candidate["id"]
        assert plan["advanced"]["candidate_digest"] == candidate["candidate_digest"]
        assert plan["advanced"]["branch"] == "main"
        assert plan["advanced"]["staged_path_count"] == 0
        for key in (
            "plan_digest",
            "binding_digest",
            "drift_semantic_fingerprint",
            "repository_locator_fingerprint",
            "repository_fingerprint",
            "index_fingerprint",
            "worktree_fingerprint",
        ):
            assert len(plan["advanced"][key]) == 64
        serialized = json.dumps(plan, sort_keys=True)
        assert str(fixture.source_repo) not in serialized
        assert "Apply Accepted Changes requires a separate explicit Owner confirmation." in serialized
        assert "Revert Applied Changes requires a separate explicit Owner confirmation" in serialized
        assert all(
            item["status"] == "PLANNED CHECK"
            for item in plan["future_preconditions"]
        )
        for checks in plan["planned_validation"].values():
            assert checks
            assert all(item["status"] == "PLANNED CHECK" for item in checks)


def test_unrelated_source_drift_is_reviewable_and_outside_operation_scope(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        (fixture.source_repo / "README.md").write_text("# unrelated owner edit\n")

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "review_with_source_changes"
        assert plan["drift_status"] == "source_changed_since_run"
        assert plan["status_label"] == "REVIEW WITH SOURCE CHANGES"
        assert {item["disposition"] for item in plan["entries"]} == {"INCLUDED"}
        assert any(
            item["path"] == "README.md"
            and item["disposition"] == "EXCLUDED"
            and item["reason_code"] == "UNRELATED_CURRENT_SOURCE"
            for item in plan["scope_exclusions"]
        )
        assert "Apply Accepted Changes" in plan["next_action"]


def test_candidate_path_conflict_is_blocked_with_exact_path_decision(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        (fixture.source_repo / "modify.txt").write_text("owner conflict\n")

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "blocked_by_conflict"
        assert plan["drift_status"] == "conflict_detected"
        modified = next(
            item for item in plan["entries"] if item["path"] == "modify.txt"
        )
        assert modified["operation"] == "MODIFY"
        assert modified["disposition"] == "BLOCKED"
        assert "CANDIDATE_PREIMAGE_CONFLICT" in modified["conflicts"]
        assert any(
            item["code"] == "CANDIDATE_PREIMAGE_CONFLICT"
            for item in plan["blockers"]
        )
        assert "before Apply" in plan["next_action"]


def test_candidate_unavailable_creates_a_reviewable_blocked_explanation(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path, run_status="failed") as fixture:
        candidate_review = fixture.client.post(candidate_url(fixture))
        assert candidate_review.status_code == 200
        assert candidate_review.json()["candidate"] is None

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "blocked_by_candidate"
        assert plan["candidate_status_label"] == "Candidate unavailable"
        assert plan["candidate_entry_count"] == plan["classified_entry_count"] == 0
        assert any(item["code"] == "RUN_FAILED" for item in plan["blockers"])


def test_repository_unavailable_is_sanitized_and_blocked(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    moved = tmp_path / "source-repo-unavailable"
    try:
        create_candidate(fixture)
        fixture.source_repo.rename(moved)

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "blocked_by_repository"
        assert plan["drift_status"] == "repository_unavailable"
        assert any(
            item["code"] == "REPOSITORY_UNAVAILABLE" for item in plan["blockers"]
        )
        serialized = json.dumps(plan, sort_keys=True)
        assert str(fixture.source_repo) not in serialized
        assert str(moved) not in serialized
    finally:
        close_candidate_fixture(fixture)


def test_unsupported_branch_is_blocked_by_repository_policy(tmp_path: Path) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        run_command(fixture.source_repo, "git", "branch", "-m", "review-only")

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "blocked_by_repository"
        assert plan["advanced"]["branch"] == "review-only"
        assert any(item["code"] == "UNSUPPORTED_BRANCH" for item in plan["blockers"])


def test_staged_paths_are_blocked_and_index_evidence_is_truthful(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        (fixture.source_repo / "README.md").write_text("# staged unrelated edit\n")
        run_command(fixture.source_repo, "git", "add", "README.md")

        plan = review_apply_plan(fixture)

        assert plan["effective_state"] == "blocked_by_repository"
        assert plan["advanced"]["staged_path_count"] == 1
        assert any(
            item["code"] == "STAGED_FILES_PRESENT" for item in plan["blockers"]
        )


def test_unexpected_candidate_path_is_explicitly_excluded(
    tmp_path: Path,
) -> None:
    with phase18_fixture(
        tmp_path,
        unexpected_paths=["created.txt"],
    ) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)

        created = next(
            item for item in plan["entries"] if item["path"] == "created.txt"
        )
        assert created["operation"] == "CREATE"
        assert created["disposition"] == "EXCLUDED"
        assert created["unexpected"] is True
        assert any(item["path"] == "created.txt" for item in plan["unexpected_files"])
        assert plan["candidate_entry_count"] == plan["classified_entry_count"]


def test_binary_candidate_entry_remains_metadata_only(tmp_path: Path) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)

        binary = next(item for item in plan["entries"] if item["path"] == "asset.bin")
        assert binary["content_kind"] == "binary"
        assert binary["operation"] == "MODIFY"
        serialized = json.dumps(binary, sort_keys=True)
        assert "binary_content" not in serialized
        assert "\\u0000" not in serialized
        advanced = next(
            item
            for item in plan["advanced"]["entries"]
            if item["path"] == "asset.bin"
        )
        assert len(advanced["before_hash"]) == len(advanced["after_hash"]) == 64


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/absolute.txt",
        "../traversal.txt",
        "nested/../../escape.txt",
        r"C:\windows.txt",
        ".git/config",
        "runtime.sqlite3",
    ],
)
def test_unsafe_paths_are_blocked_without_persisting_raw_host_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    entries, order, conflicts = construct_path_decisions(
        [manifest_entry(unsafe_path, "CREATE")],
        repository_root=tmp_path,
    )
    assert order == []
    assert len(entries) == 1
    assert entries[0]["disposition"] == "BLOCKED"
    assert entries[0]["operation_ordinal"] is None
    assert conflicts[0]["code"] in {
        "UNSAFE_PATH",
        "POLICY_PATH_BLOCKED",
        "SECRET_PATH_BLOCKED",
    }
    if unsafe_path.startswith(("/", "C:")):
        assert entries[0]["display_path"] == "[unsafe path withheld]"


def test_duplicate_and_case_colliding_paths_are_blocked(tmp_path: Path) -> None:
    entries, order, _ = construct_path_decisions(
        [
            manifest_entry("same.txt", "CREATE"),
            manifest_entry("same.txt", "CREATE"),
            manifest_entry("Readme.md", "CREATE"),
            manifest_entry("README.md", "CREATE"),
        ],
        repository_root=tmp_path,
    )
    assert order == []
    by_path: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        by_path.setdefault(str(entry["display_path"]), []).append(entry)
    assert {item["reason_code"] for item in by_path["same.txt"]} == {
        "DUPLICATE_PATH"
    }
    assert {
        by_path["Readme.md"][0]["reason_code"],
        by_path["README.md"][0]["reason_code"],
    } == {"CASE_PATH_COLLISION"}
    assert all(item["disposition"] == "BLOCKED" for item in entries)


def test_file_to_directory_replacement_has_dependency_order(
    tmp_path: Path,
) -> None:
    before = b"before\n"
    (tmp_path / "tree").write_bytes(before)
    entries, order, conflicts = construct_path_decisions(
        [
            manifest_entry("tree/leaf.txt", "CREATE"),
            manifest_entry("tree", "DELETE"),
        ],
        repository_root=tmp_path,
    )

    assert conflicts == []
    assert {item["disposition"] for item in entries} == {"INCLUDED"}
    assert [(item["operation"], item["path"]) for item in order] == [
        ("DELETE", "tree"),
        ("CREATE", "tree/leaf.txt"),
    ]
    assert order[1]["dependencies"] == [2]


def test_directory_to_file_replacement_is_blocked(tmp_path: Path) -> None:
    directory = tmp_path / "tree"
    directory.mkdir()
    (directory / "leaf.txt").write_bytes(b"before\n")
    entries, order, _ = construct_path_decisions(
        [
            manifest_entry("tree/leaf.txt", "DELETE"),
            manifest_entry("tree", "CREATE"),
        ],
        repository_root=tmp_path,
    )
    assert order == []
    assert all(item["disposition"] == "BLOCKED" for item in entries)
    assert {
        str(item["reason_code"])
        for item in entries
    } & {"CREATE_TARGET_EXISTS", "PATH_SHAPE_CONFLICT"}


def test_default_manifest_operation_order_is_deterministic(tmp_path: Path) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)
        operations = plan["advanced"]["operation_order"]["operations"]
        assert [(item["operation"], item["path"]) for item in operations] == [
            ("DELETE", "delete.txt"),
            ("MODIFY", "asset.bin"),
            ("MODIFY", "modify.txt"),
            ("CREATE", "created.txt"),
        ]
        assert [item["ordinal"] for item in operations] == [1, 2, 3, 4]


def test_operation_preconditions_and_reversibility_are_exact(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)
        entries = {item["operation"]: item for item in plan["entries"]}

        create_codes = {
            item["code"] for item in entries["CREATE"]["preconditions"]
        }
        modify_codes = {
            item["code"] for item in entries["MODIFY"]["preconditions"]
        }
        delete_codes = {
            item["code"] for item in entries["DELETE"]["preconditions"]
        }
        assert {"SAFE_PARENT_CHAIN", "TARGET_ABSENT", "AFTER_IDENTITY_AVAILABLE"} <= create_codes
        assert {"SAFE_PARENT_CHAIN", "EXPECTED_REGULAR_PREIMAGE", "AFTER_IDENTITY_AVAILABLE"} <= modify_codes
        assert {
            "SAFE_PARENT_CHAIN",
            "EXPECTED_REGULAR_PREIMAGE",
            "EXACT_PATH_ONLY",
            "RESTORATION_MATERIAL",
        } <= delete_codes
        assert (
            entries["CREATE"]["reversibility"]["future_reverse_operation"]
            == "DELETE_EXACT"
        )
        assert (
            entries["MODIFY"]["reversibility"]["future_reverse_operation"]
            == "RESTORE_EXACT"
        )
        assert (
            entries["DELETE"]["reversibility"]["future_reverse_operation"]
            == "RECREATE_EXACT"
        )
        assert (
            plan["reversibility_requirements"]["state"]
            == "CAPTURED_ONLY_BY_EXPLICIT_APPLY"
        )


def test_identical_requests_are_idempotent_despite_fresh_drift_evidence(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        first = review_apply_plan(fixture)
        second = review_apply_plan(fixture)
        assert second["id"] == first["id"]
        assert second["version"] == first["version"] == 1
        assert (
            second["advanced"]["plan_digest"]
            == first["advanced"]["plan_digest"]
        )
        factory = fixture.client.app.state.session_factory
        assert len(plan_rows(factory)) == 1
        with factory() as session:
            evaluations = list(
                session.scalars(
                    select(SourceDriftEvaluation).where(
                        SourceDriftEvaluation.run_id == fixture.run_id
                    )
                ).all()
            )
        assert len(evaluations) >= 3


def test_worktree_change_versions_plan_and_expires_history(tmp_path: Path) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        first = review_apply_plan(fixture)
        (fixture.source_repo / "README.md").write_text("# new unrelated state\n")
        second = review_apply_plan(fixture)

        assert second["version"] == 2
        assert second["id"] != first["id"]
        assert second["effective_state"] == "review_with_source_changes"
        history = fixture.client.get(historical_plan_url(first["id"]))
        assert history.status_code == 200, history.text
        historical = history.json()["plan"]
        assert historical["effective_state"] == "expired"
        assert any(
            item["code"] in {"PLAN_SUPERSEDED", "REPOSITORY_BINDING_CHANGED"}
            for item in historical["blockers"]
        )


def test_index_fingerprint_change_versions_plan_with_zero_staged_paths(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        first = review_apply_plan(fixture)
        run_command(
            fixture.source_repo,
            "git",
            "update-index",
            "--assume-unchanged",
            "README.md",
        )
        assert (
            run_command(
                fixture.source_repo,
                "git",
                "diff",
                "--cached",
                "--name-only",
            ).stdout
            == ""
        )
        second = review_apply_plan(fixture)
        assert second["version"] == 2
        assert second["advanced"]["staged_path_count"] == 0
        assert (
            second["advanced"]["index_fingerprint"]
            != first["advanced"]["index_fingerprint"]
        )


def test_head_change_versions_plan_without_mutating_head_during_review(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        first = review_apply_plan(fixture)
        (fixture.source_repo / "unrelated-head.txt").write_text("new commit\n")
        run_command(fixture.source_repo, "git", "add", "unrelated-head.txt")
        run_command(fixture.source_repo, "git", "commit", "-m", "unrelated test commit")
        changed_head = run_command(
            fixture.source_repo, "git", "rev-parse", "HEAD"
        ).stdout.strip()

        second = review_apply_plan(fixture)

        assert second["version"] == 2
        assert second["advanced"]["head"] == changed_head
        assert second["advanced"]["head"] != first["advanced"]["head"]
        assert (
            run_command(fixture.source_repo, "git", "rev-parse", "HEAD").stdout.strip()
            == changed_head
        )


def test_policy_version_change_creates_new_immutable_version(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        first = review_apply_plan(fixture)
        factory = fixture.client.app.state.session_factory
        fixture.client.get(candidate_url(fixture))
        with factory() as session:
            run = session.get(CodexRun, fixture.run_id)
            candidate = session.scalar(
                select(DeliveryCandidate).where(
                    DeliveryCandidate.run_id == fixture.run_id
                )
            )
            drift = session.scalar(
                select(SourceDriftEvaluation)
                .where(SourceDriftEvaluation.run_id == fixture.run_id)
                .order_by(SourceDriftEvaluation.id.desc())
            )
            assert run is not None and candidate is not None and drift is not None
            eligibility = validate_delivery_candidate(
                session, fixture.owner_id, run, candidate
            )
            second, created = get_or_create_apply_plan(
                session,
                owner_id=fixture.owner_id,
                run=run,
                candidate=candidate,
                candidate_eligibility=eligibility,
                drift=drift,
                source_repo=fixture.source_repo,
                policy_version="twos.review_apply_plan.v2-test",
            )
            assert created is True
            session.commit()
            assert second.plan_version == 2
            assert second.plan_id != first["id"]
            state, reasons = effective_apply_plan_state(
                session,
                session.scalar(
                    select(ApplyPlan).where(ApplyPlan.plan_version == 1)
                ),
                source_repo=fixture.source_repo,
                policy_version="twos.review_apply_plan.v2-test",
            )
            assert state == "expired"
            assert any(
                item["code"] in {"PLAN_SUPERSEDED", "POLICY_VERSION_CHANGED"}
                for item in reasons
            )


def test_process_restart_preserves_apply_plan_identity(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    create_candidate(fixture)
    original = review_apply_plan(fixture)
    database_path = fixture.database_path
    source_repo = fixture.source_repo
    close_candidate_fixture(fixture)

    restarted = make_client(
        tmp_path / "restart",
        source_repo,
        tmp_path / "codex-must-not-be-invoked",
        database_path=database_path,
    )
    restarted.__enter__()
    try:
        init_and_login(restarted)
        response = restarted.get(
            f"/api/codex-runs/{fixture.run_id}/apply-plans"
        )
        assert response.status_code == 200, response.text
        persisted = response.json()["plan"]
        assert persisted["id"] == original["id"]
        assert persisted["version"] == original["version"]
        assert (
            persisted["advanced"]["plan_digest"]
            == original["advanced"]["plan_digest"]
        )
    finally:
        restarted.__exit__(None, None, None)


def test_apply_plan_and_entries_are_immutable_at_orm_and_database_layers(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)
        factory = fixture.client.app.state.session_factory
        engine = fixture.client.app.state.engine
        with factory() as session:
            persisted = session.scalar(
                select(ApplyPlan).where(ApplyPlan.plan_id == plan["id"])
            )
            entry = session.scalar(
                select(ApplyPlanEntry).where(
                    ApplyPlanEntry.apply_plan_id == persisted.id
                )
            )
            assert persisted is not None and entry is not None
            assert validate_apply_plan_integrity(session, persisted)
            persisted.status_at_creation = "blocked_by_repository"
            with pytest.raises(RuntimeError, match="append-only|immutable"):
                session.commit()
            session.rollback()

            entry = session.get(ApplyPlanEntry, entry.id)
            entry.reason = "mutated"
            with pytest.raises(RuntimeError, match="append-only|immutable"):
                session.commit()
            session.rollback()

        for statement in (
            "UPDATE apply_plans SET policy_version='mutated' WHERE plan_id=:plan_id",
            "DELETE FROM apply_plans WHERE plan_id=:plan_id",
            "UPDATE apply_plan_entries SET reason='mutated' WHERE apply_plan_id=(SELECT id FROM apply_plans WHERE plan_id=:plan_id)",
            "DELETE FROM apply_plan_entries WHERE apply_plan_id=(SELECT id FROM apply_plans WHERE plan_id=:plan_id)",
        ):
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(statement), {"plan_id": plan["id"]})


def test_apply_plan_has_no_update_delete_or_later_phase_routes(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)
        for method in ("put", "patch", "delete"):
            assert (
                getattr(fixture.client, method)(apply_plan_url(fixture)).status_code
                == 405
            )
            assert (
                getattr(fixture.client, method)(
                    historical_plan_url(plan["id"])
                ).status_code
                == 405
            )
        forbidden_posts = (
            f"/api/apply-plans/{plan['id']}/approve",
            f"/api/apply-plans/{plan['id']}/apply",
            f"/api/apply-plans/{plan['id']}/revert",
            f"/api/apply-plans/{plan['id']}/verify",
            f"/api/apply-plans/{plan['id']}/stage",
            f"/api/apply-plans/{plan['id']}/commit",
            f"/api/apply-plans/{plan['id']}/push",
        )
        for path in forbidden_posts:
            assert fixture.client.post(path).status_code == 404


def test_unauthenticated_and_cross_owner_access_do_not_leak_plan_existence(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        plan = review_apply_plan(fixture)
        fixture.client.cookies.clear()
        assert fixture.client.get(apply_plan_url(fixture)).status_code == 401
        assert fixture.client.post(apply_plan_url(fixture)).status_code == 401
        assert (
            fixture.client.get(historical_plan_url(plan["id"])).status_code == 401
        )

        raw_token = "phase18-apply-plan-second-owner"
        password_hash, password_salt = hash_password("second-owner-password")
        factory = fixture.client.app.state.session_factory
        with factory() as session:
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
        headers = {"Authorization": f"Bearer {raw_token}"}
        wrong_run = fixture.client.post(apply_plan_url(fixture), headers=headers)
        missing_run = fixture.client.post(
            f"/api/codex-runs/{fixture.run_id + 100_000}/apply-plans",
            headers=headers,
        )
        assert wrong_run.status_code == missing_run.status_code == 404
        assert (
            wrong_run.json()["error"]["message"]
            == missing_run.json()["error"]["message"]
        )
        wrong_plan = fixture.client.get(
            historical_plan_url(plan["id"]),
            headers=headers,
        )
        missing_plan = fixture.client.get(
            historical_plan_url("ap_" + "0" * 40),
            headers=headers,
        )
        assert wrong_plan.status_code == missing_plan.status_code == 404
        assert (
            wrong_plan.json()["error"]["message"]
            == missing_plan.json()["error"]["message"]
        )


def test_review_apply_plan_does_not_mutate_source_git_or_invoke_provider(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        create_candidate(fixture)
        before = source_boundary(fixture.source_repo)
        index_before = git_index_artifact(fixture.source_repo)
        tracked = {
            path: (
                (fixture.source_repo / path).read_bytes(),
                (fixture.source_repo / path).stat().st_mode,
                (fixture.source_repo / path).stat().st_mtime_ns,
            )
            for path in ("README.md", "modify.txt", "delete.txt", "asset.bin")
        }
        sentinel = tmp_path / "codex-must-not-be-invoked"

        plan = review_apply_plan(fixture)
        retrieved = fixture.client.get(historical_plan_url(plan["id"]))
        assert retrieved.status_code == 200

        assert git_index_artifact(fixture.source_repo) == index_before
        assert source_boundary(fixture.source_repo) == before
        for path, expected in tracked.items():
            candidate = fixture.source_repo / path
            assert (
                candidate.read_bytes(),
                candidate.stat().st_mode,
                candidate.stat().st_mtime_ns,
            ) == expected
        assert not sentinel.exists()


def test_apply_plan_git_allowlist_contains_no_mutating_operation() -> None:
    forbidden = {
        "add",
        "checkout",
        "clean",
        "commit",
        "config",
        "fetch",
        "merge",
        "pull",
        "push",
        "rebase",
        "remote",
        "reset",
        "restore",
        "stage",
        "stash",
        "switch",
        "tag",
    }
    assert APPLY_PLAN_READ_ONLY_GIT_ALLOWLIST
    for command in APPLY_PLAN_READ_ONLY_GIT_ALLOWLIST:
        assert forbidden.isdisjoint(command.split())


def test_vol18_002_migration_and_immutable_triggers_are_present(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        engine = fixture.client.app.state.engine
        factory = fixture.client.app.state.session_factory
        assert {"apply_plans", "apply_plan_entries"} <= set(
            inspect(engine).get_table_names()
        )
        with factory() as session:
            assert (
                session.scalar(
                    select(SchemaVersion).where(
                        SchemaVersion.version == "vol18.002"
                    )
                )
                is not None
            )
        with engine.connect() as connection:
            trigger_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='trigger' ORDER BY name"
                    )
                )
            }
        assert {
            "trg_apply_plans_no_update",
            "trg_apply_plans_no_delete",
            "trg_apply_plan_entries_no_update",
            "trg_apply_plan_entries_no_delete",
        } <= trigger_names


def test_review_apply_plan_ui_never_invokes_later_delivery_actions(
    tmp_path: Path,
) -> None:
    with phase18_fixture(tmp_path) as fixture:
        page = fixture.client.get("/twos")
        script = fixture.client.get(
            "/static_cockpit/vol12_static_mvp/twos_command_center.js"
        )
        assert page.status_code == script.status_code == 200
        assert "Review Change Candidate" in page.text
        assert "Review Apply Plan" in page.text
        assert "Apply Accepted Changes" in page.text
        assert "Revert Applied Changes" in page.text
        assert "Verify Applied Changes" in page.text
        assert 'id="review-apply-plan"' in page.text
        assert 'id="push-to-origin-main" class="button button-danger" type="button" hidden disabled' in page.text
        review_action = script.text.split(
            "async function reviewApplyPlan()",
            1,
        )[1].split("async function reviewCommitPlan", 1)[0]
        assert '"/push-preflights"' not in review_action
        assert '"/push-attempts"' not in review_action
        assert "confirmPushToOriginMain" not in review_action
