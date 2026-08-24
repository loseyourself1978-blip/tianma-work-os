from __future__ import annotations

import hashlib
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import inspect, select, text

from tests.test_self_hosting import run_command
from tests.test_vol18_delivery_candidate import (
    CandidateFixture,
    build_candidate_fixture,
    candidate_url,
    close_candidate_fixture,
    git_index_artifact,
)
from tests.test_vol18_review_apply_plan import apply_plan_url
from twos_runtime.apply_sessions import (
    APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST,
    ApplySessionError,
    apply_accepted_changes,
    apply_session_entries,
    apply_session_out,
    reconcile_apply_session,
    revert_applied_changes,
)
import twos_runtime.apply_sessions as apply_session_service
from twos_runtime.models import (
    ApplyPlan,
    ApplySession,
    ApplySessionAudit,
    ApplySessionEntry,
    CodexRun,
    SchemaVersion,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.security import hash_password, hash_token
from twos_runtime.self_hosting import capture_source_snapshot


APPLY_CONFIRMATION = "APPLY_ACCEPTED_CHANGES"
REVERT_CONFIRMATION = "REVERT_APPLIED_CHANGES"
DEFAULT_POSTIMAGES = {
    "created.txt": b"created by run\n",
    "modify.txt": b"after modify\n",
    "asset.bin": b"\x00\x10\x02\x03\x04",
}
def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def create_manifest_entry(path: str, payload: bytes, mode: int = 0o644) -> dict[str, object]:
    return {
        "path": path,
        "change_type": "created",
        "before_sha256": None,
        "after_sha256": sha256_bytes(payload),
        "before_size": None,
        "after_size": len(payload),
        "before_mode": None,
        "after_mode": mode,
        "content_kind": "text",
        "added_lines": payload.count(b"\n"),
        "removed_lines": 0,
        "changed_hunks": 1,
        "content_included": False,
    }


@dataclass(frozen=True)
class ApplyRevertFixture:
    candidate: CandidateFixture
    run_worktree: Path
    plan: dict[str, object]

    @property
    def client(self):
        return self.candidate.client

    @property
    def source_repo(self) -> Path:
        return self.candidate.source_repo

    @property
    def owner_id(self) -> int:
        return self.candidate.owner_id

    @property
    def run_id(self) -> int:
        return self.candidate.run_id

    @property
    def factory(self):
        return self.client.app.state.session_factory


def _create_retained_run_worktree(source_repo: Path, destination: Path) -> None:
    run_command(
        source_repo,
        "git",
        "worktree",
        "add",
        "--detach",
        str(destination),
        "HEAD",
    )


def _prepare_retained_run_material(
    fixture: CandidateFixture,
    *,
    postimages: dict[str, bytes] | None = None,
    after_modes: dict[str, int] | None = None,
    deleted_paths: set[str] | None = None,
) -> Path:
    run_worktree = fixture.database_path.parent / "retained-run-worktree"
    _create_retained_run_worktree(fixture.source_repo, run_worktree)
    material = dict(DEFAULT_POSTIMAGES if postimages is None else postimages)
    modes = dict(after_modes or {})

    for relative in (
        {"delete.txt"} if deleted_paths is None else deleted_paths
    ):
        delete_path = run_worktree / relative
        if delete_path.exists():
            delete_path.unlink()
    for relative, payload in material.items():
        target = run_worktree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        target.chmod(modes.get(relative, 0o644))

    post_run_snapshot = capture_source_snapshot(run_worktree)
    with fixture.client.app.state.session_factory() as session:
        run = session.get(CodexRun, fixture.run_id)
        assert run is not None
        result = json.loads(run.structured_result)
        result["post_run_snapshot_digest"] = post_run_snapshot["digest"]
        run.structured_result = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        )
        run.worktree_path = str(run_worktree)
        run.worktree_branch = "twos/run-phase18-2b-fixture"
        session.commit()

    with fixture.client.app.state.session_factory() as session:
        run = session.get(CodexRun, fixture.run_id)
        assert run is not None
        result = json.loads(run.structured_result)
        assert result["post_run_snapshot_digest"] == capture_source_snapshot(
            run_worktree
        )["digest"]
    return run_worktree


@contextmanager
def phase18b_fixture(
    tmp_path: Path,
    *,
    postimages: dict[str, bytes] | None = None,
    after_modes: dict[str, int] | None = None,
    **candidate_options,
):
    fixture = build_candidate_fixture(tmp_path, **candidate_options)
    try:
        records = candidate_options.get("manifest_records")
        deleted_paths = (
            None
            if records is None
            else {
                str(item["path"])
                for item in records
                if isinstance(item, dict)
                and str(item.get("change_type") or "").casefold()
                == "deleted"
            }
        )
        run_worktree = _prepare_retained_run_material(
            fixture,
            postimages=postimages,
            after_modes=after_modes,
            deleted_paths=deleted_paths,
        )
        candidate_response = fixture.client.post(candidate_url(fixture))
        assert candidate_response.status_code == 200, candidate_response.text
        assert candidate_response.json()["candidate"] is not None
        plan_response = fixture.client.post(apply_plan_url(fixture))
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        assert plan["effective_state"] in {
            "ready_for_owner_review",
            "review_with_source_changes",
        }
        yield ApplyRevertFixture(
            candidate=fixture,
            run_worktree=run_worktree,
            plan=plan,
        )
    finally:
        close_candidate_fixture(fixture)


def _plan_row(session, fixture: ApplyRevertFixture) -> ApplyPlan:
    plan = session.scalar(
        select(ApplyPlan).where(ApplyPlan.plan_id == fixture.plan["id"])
    )
    assert plan is not None
    return plan


def _apply(
    fixture: ApplyRevertFixture,
    *,
    confirmed: bool = True,
    fault_injector=None,
) -> tuple[dict[str, object], bool]:
    with fixture.factory() as session:
        row, created = apply_accepted_changes(
            session,
            owner_id=fixture.owner_id,
            plan=_plan_row(session, fixture),
            source_repo=fixture.source_repo,
            confirmed=confirmed,
            fault_injector=fault_injector,
        )
        return apply_session_out(session, row), created


def _revert(
    fixture: ApplyRevertFixture,
    session_id: str,
    *,
    confirmed: bool = True,
    fault_injector=None,
) -> tuple[dict[str, object], bool]:
    with fixture.factory() as session:
        row = session.scalar(
            select(ApplySession).where(ApplySession.session_id == session_id)
        )
        assert row is not None
        row, changed = revert_applied_changes(
            session,
            owner_id=fixture.owner_id,
            apply_session=row,
            source_repo=fixture.source_repo,
            confirmed=confirmed,
            fault_injector=fault_injector,
        )
        return apply_session_out(session, row), changed


def _git_boundary(repo: Path) -> dict[str, object]:
    return {
        "head": run_command(repo, "git", "rev-parse", "HEAD").stdout,
        "branch": run_command(repo, "git", "branch", "--show-current").stdout,
        "index": git_index_artifact(repo),
        "staged": run_command(
            repo, "git", "diff", "--cached", "--name-only"
        ).stdout,
        "refs": run_command(
            repo, "git", "for-each-ref", "--format=%(refname)%00%(objectname)%00"
        ).stdout,
        "remotes": run_command(repo, "git", "remote", "-v").stdout,
        "config": run_command(
            repo, "git", "config", "--local", "--null", "--list"
        ).stdout,
    }


def _failure_codes(payload: dict[str, object]) -> set[str]:
    return {
        str(item.get("code"))
        for item in payload.get("blockers", [])
        if isinstance(item, dict)
    }


def _response_error_code(response) -> str:
    body = response.json()
    if isinstance(body.get("detail"), dict):
        return str(body["detail"].get("code") or "")
    error = body.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        if isinstance(details, dict):
            return str(details.get("code") or "")
        return str(error.get("code") or "")
    return ""


def test_ready_plan_applies_exact_create_modify_delete_binary_and_git_boundary(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        before_git = _git_boundary(fixture.source_repo)
        result, created = _apply(fixture)

        assert created is True
        assert result["state"] == "APPLIED"
        assert result["integrity_check_result"] == "PASSED"
        assert (fixture.source_repo / "created.txt").read_bytes() == b"created by run\n"
        assert (fixture.source_repo / "modify.txt").read_bytes() == b"after modify\n"
        assert not (fixture.source_repo / "delete.txt").exists()
        assert (fixture.source_repo / "asset.bin").read_bytes() == b"\x00\x10\x02\x03\x04"
        assert {item["operation"] for item in result["files"]} == {
            "CREATE",
            "MODIFY",
            "DELETE",
        }
        assert _git_boundary(fixture.source_repo) == before_git
        assert result["index_boundary"]["staged_path_count"] == 0
        assert result["advanced"]["diagnostics"] == {
            "path_mutation": "explicit_path_scoped",
            "git_mutation": False,
            "index_mutation": False,
            "head_ref_config_remote_mutation": False,
            "post_apply_verification": False,
            "git_metadata_refresh": [],
        }
        assert not (tmp_path / "codex-must-not-be-invoked").exists()


def test_apply_preflight_ignores_git_directory_metadata_only_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        original = apply_session_service._global_evidence
        calls = 0

        def refreshed_metadata(*args, **kwargs):
            nonlocal calls
            calls += 1
            observed = original(*args, **kwargs)
            if calls in {2, 3}:
                git_row = next(
                    row
                    for row in observed["direct_filesystem"]["excluded_entries"]
                    if row.get("path_identity")
                    == apply_session_service._path_identity(".git")
                )
                git_row["mtime_ns"] = int(git_row.get("mtime_ns") or 0) + calls
                git_row["size"] = int(git_row.get("size") or 0) + calls
                observed["direct_filesystem"]["excluded_fingerprint"] = "f" * 64
            return observed

        monkeypatch.setattr(
            apply_session_service,
            "_global_evidence",
            refreshed_metadata,
        )

        result, created = _apply(fixture)

        assert created is True
        assert result["state"] == "APPLIED"
        assert calls >= 3
        assert (fixture.source_repo / "created.txt").exists()


def test_apply_preflight_component_diff_blocks_actual_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        original = apply_session_service._global_evidence
        calls = 0

        def mutate_between_samples(*args, **kwargs):
            nonlocal calls
            calls += 1
            observed = original(*args, **kwargs)
            if calls == 1:
                (fixture.source_repo / "unexpected-during-preflight.txt").write_text(
                    "changed during protected preflight\n",
                    encoding="utf-8",
                )
            return observed

        monkeypatch.setattr(
            apply_session_service,
            "_global_evidence",
            mutate_between_samples,
        )

        result, created = _apply(fixture)

        assert created is True
        assert result["state"] == "PREFLIGHT_BLOCKED"
        blocker = next(
            item
            for item in result["blockers"]
            if item.get("code") == "REPOSITORY_CHANGED_DURING_PREFLIGHT"
        )
        difference = blocker["details"]["semantic_difference"]
        assert "UNRELATED_SOURCE_CHANGED" in difference["codes"]
        assert difference["path_changes"] == [
            {
                "path": "unexpected-during-preflight.txt",
                "operation": "CREATE",
                "candidate_target": False,
            }
        ]
        assert not (fixture.source_repo / "created.txt").exists()


def test_review_with_unrelated_source_changes_preserves_modified_and_untracked(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        run_root = _prepare_retained_run_material(fixture)
        modified = fixture.source_repo / "README.md"
        untracked = fixture.source_repo / "owner-notes.txt"
        modified.write_text("# owner work remains\n")
        untracked.write_text("private local note\n")
        candidate_response = fixture.client.post(candidate_url(fixture))
        assert candidate_response.status_code == 200
        plan_response = fixture.client.post(apply_plan_url(fixture))
        assert plan_response.status_code == 200
        review = ApplyRevertFixture(
            candidate=fixture,
            run_worktree=run_root,
            plan=plan_response.json()["plan"],
        )
        assert review.plan["effective_state"] == "review_with_source_changes"
        modified_before = modified.read_bytes()
        untracked_before = untracked.read_bytes()

        result, _ = _apply(review)

        assert result["state"] == "APPLIED"
        assert modified.read_bytes() == modified_before
        assert untracked.read_bytes() == untracked_before
        unrelated_paths = {
            item["path"] for item in result["unrelated_source_changes"]
        }
        assert {"README.md", "owner-notes.txt"} <= unrelated_paths
    finally:
        close_candidate_fixture(fixture)


def test_apply_and_revert_each_require_separate_explicit_confirmation(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        with fixture.factory() as session:
            with pytest.raises(ApplySessionError) as error:
                apply_accepted_changes(
                    session,
                    owner_id=fixture.owner_id,
                    plan=_plan_row(session, fixture),
                    source_repo=fixture.source_repo,
                    confirmed=False,
                )
            assert error.value.code == "APPLY_CONFIRMATION_REQUIRED"
        assert not (fixture.source_repo / "created.txt").exists()

        applied, _ = _apply(fixture)
        with fixture.factory() as session:
            row = session.scalar(
                select(ApplySession).where(
                    ApplySession.session_id == applied["id"]
                )
            )
            assert row is not None
            with pytest.raises(ApplySessionError) as error:
                revert_applied_changes(
                    session,
                    owner_id=fixture.owner_id,
                    apply_session=row,
                    source_repo=fixture.source_repo,
                    confirmed=False,
                )
            assert error.value.code == "REVERT_CONFIRMATION_REQUIRED"
        assert (fixture.source_repo / "created.txt").exists()


def test_nested_create_records_parents_and_mode_then_revert_removes_only_created_parents(
    tmp_path: Path,
) -> None:
    payload = b"#!/bin/sh\nexit 0\n"
    record = {
        "path": "generated/deep/tool.sh",
        "change_type": "created",
        "before_sha256": None,
        "after_sha256": sha256_bytes(payload),
        "before_size": None,
        "after_size": len(payload),
        "before_mode": None,
        "after_mode": 0o755,
        "content_kind": "text",
        "added_lines": 2,
        "removed_lines": 0,
        "changed_hunks": 1,
        "content_included": False,
    }
    with phase18b_fixture(
        tmp_path,
        manifest_records=[record],
        postimages={"generated/deep/tool.sh": payload},
        after_modes={"generated/deep/tool.sh": 0o755},
    ) as fixture:
        applied, _ = _apply(fixture)
        target = fixture.source_repo / "generated/deep/tool.sh"
        assert target.read_bytes() == payload
        assert stat.S_IMODE(target.stat().st_mode) == 0o755
        entry = applied["advanced"]["entries"][0]
        assert [item["path"] for item in entry["created_parent_dirs"]] == [
            "generated",
            "generated/deep",
        ]

        reverted, changed = _revert(fixture, applied["id"])

        assert changed is True
        assert reverted["state"] == "REVERTED"
        assert not target.exists()
        assert not (fixture.source_repo / "generated").exists()


def test_multiple_create_entries_share_one_new_parent_and_revert_exactly(
    tmp_path: Path,
) -> None:
    first_payload = b"first shared child\n"
    second_payload = b"second shared child\n"
    records = [
        create_manifest_entry("shared-output/first.txt", first_payload),
        create_manifest_entry("shared-output/second.txt", second_payload),
    ]
    with phase18b_fixture(
        tmp_path,
        manifest_records=records,
        postimages={
            "shared-output/first.txt": first_payload,
            "shared-output/second.txt": second_payload,
        },
    ) as fixture:
        applied, _ = _apply(fixture)

        assert applied["state"] == "APPLIED"
        assert (fixture.source_repo / "shared-output/first.txt").read_bytes() == (
            first_payload
        )
        assert (fixture.source_repo / "shared-output/second.txt").read_bytes() == (
            second_payload
        )
        parent_owners = [
            parent["path"]
            for entry in applied["advanced"]["entries"]
            for parent in entry["created_parent_dirs"]
        ]
        assert parent_owners == ["shared-output"]

        reverted, _ = _revert(fixture, applied["id"])

        assert reverted["state"] == "REVERTED"
        assert not (fixture.source_repo / "shared-output").exists()


def test_nonempty_session_created_parent_blocks_revert_before_target_mutation(
    tmp_path: Path,
) -> None:
    payload = b"session-created child\n"
    with phase18b_fixture(
        tmp_path,
        manifest_records=[
            create_manifest_entry("session-parent/created.txt", payload)
        ],
        postimages={"session-parent/created.txt": payload},
    ) as fixture:
        applied, _ = _apply(fixture)
        target = fixture.source_repo / "session-parent/created.txt"
        owner_file = fixture.source_repo / "session-parent/owner-newer.txt"
        owner_file.write_bytes(b"newer owner content\n")

        blocked, changed = _revert(fixture, applied["id"])

        assert changed is True
        assert blocked["state"] == "REVERT_BLOCKED"
        assert "CREATED_PARENT_NOT_EMPTY" in _failure_codes(blocked)
        assert target.read_bytes() == payload
        assert owner_file.read_bytes() == b"newer owner content\n"


def test_revert_preserves_preexisting_parent_and_restores_all_operations(
    tmp_path: Path,
) -> None:
    payload = b"nested owner-approved output\n"
    record = {
        "path": "existing-parent/new.txt",
        "change_type": "created",
        "before_sha256": None,
        "after_sha256": sha256_bytes(payload),
        "before_size": None,
        "after_size": len(payload),
        "before_mode": None,
        "after_mode": 0o644,
        "content_kind": "text",
        "added_lines": 1,
        "removed_lines": 0,
        "changed_hunks": 1,
        "content_included": False,
    }
    fixture = build_candidate_fixture(tmp_path, manifest_records=[record])
    try:
        (fixture.source_repo / "existing-parent").mkdir()
        run_root = _prepare_retained_run_material(
            fixture,
            postimages={"existing-parent/new.txt": payload},
            deleted_paths=set(),
        )
        assert run_root.is_dir()
        assert fixture.client.post(candidate_url(fixture)).status_code == 200
        plan = fixture.client.post(apply_plan_url(fixture)).json()["plan"]
        review = ApplyRevertFixture(fixture, run_root, plan)

        applied, _ = _apply(review)
        assert (fixture.source_repo / "existing-parent/new.txt").exists()
        reverted, _ = _revert(review, applied["id"])

        assert reverted["state"] == "REVERTED"
        assert (fixture.source_repo / "existing-parent").is_dir()
        assert not (fixture.source_repo / "existing-parent/new.txt").exists()
    finally:
        close_candidate_fixture(fixture)


def test_excluded_candidate_entry_and_unrelated_files_are_never_applied(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path, unexpected_paths=["created.txt"])
    try:
        run_root = _prepare_retained_run_material(fixture)
        owner_file = fixture.source_repo / "owner-untracked.txt"
        owner_file.write_bytes(b"preserve exactly\n")
        assert fixture.client.post(candidate_url(fixture)).status_code == 200
        plan = fixture.client.post(apply_plan_url(fixture)).json()["plan"]
        review = ApplyRevertFixture(fixture, run_root, plan)
        excluded = {
            item["path"]
            for item in plan["entries"]
            if item["disposition"] == "EXCLUDED"
        }
        assert "created.txt" in excluded

        result, _ = _apply(review)

        assert result["state"] == "APPLIED"
        assert result["excluded_path_count"] >= 1
        assert not (fixture.source_repo / "created.txt").exists()
        assert owner_file.read_bytes() == b"preserve exactly\n"
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("mutation", "expected_codes"),
    [
        ("changed_preimage", {"CONFLICT_DETECTED", "CANDIDATE_PREIMAGE_CONFLICT"}),
        ("staged", {"STAGED_PATHS_PRESENT", "PLAN_REPOSITORY_BINDING_CHANGED"}),
        ("dirty_index", {"INDEX_FINGERPRINT_CHANGED", "PLAN_REPOSITORY_BINDING_CHANGED"}),
        ("wrong_branch", {"WRONG_BRANCH", "PLAN_REPOSITORY_BINDING_CHANGED"}),
        ("missing_postimage", {"POSTIMAGE_MATERIAL_INVALID", "POSTIMAGE_MATERIAL_MISSING"}),
        ("target_symlink", {"CONFLICT_DETECTED", "SYMLINK_UNSUPPORTED"}),
    ],
)
def test_apply_preflight_blocks_changed_git_or_unsafe_state_without_mutation(
    tmp_path: Path,
    mutation: str,
    expected_codes: set[str],
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        outside = tmp_path / "outside.txt"
        outside.write_bytes(b"outside must survive\n")
        if mutation == "changed_preimage":
            (fixture.source_repo / "modify.txt").write_bytes(b"owner changed target\n")
        elif mutation == "staged":
            (fixture.source_repo / "README.md").write_text("# staged owner work\n")
            run_command(fixture.source_repo, "git", "add", "README.md")
        elif mutation == "dirty_index":
            run_command(
                fixture.source_repo,
                "git",
                "update-index",
                "--assume-unchanged",
                "README.md",
            )
        elif mutation == "wrong_branch":
            run_command(
                fixture.source_repo, "git", "branch", "-m", "not-main"
            )
        elif mutation == "missing_postimage":
            (fixture.run_worktree / "modify.txt").unlink()
        elif mutation == "target_symlink":
            target = fixture.source_repo / "modify.txt"
            target.unlink()
            target.symlink_to(outside)

        result, created = _apply(fixture)

        assert created is True
        assert result["state"] == "PREFLIGHT_BLOCKED"
        assert _failure_codes(result) & expected_codes
        assert not (fixture.source_repo / "created.txt").exists()
        assert outside.read_bytes() == b"outside must survive\n"


def test_blocked_path_and_expired_plan_cannot_apply(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        run_root = _prepare_retained_run_material(fixture)
        assert fixture.client.post(candidate_url(fixture)).status_code == 200
        (fixture.source_repo / "modify.txt").write_text("conflicting owner edit\n")
        blocked_plan = fixture.client.post(apply_plan_url(fixture)).json()["plan"]
        assert blocked_plan["effective_state"] == "blocked_by_conflict"
        review = ApplyRevertFixture(fixture, run_root, blocked_plan)
        blocked, _ = _apply(review)
        assert blocked["state"] == "PREFLIGHT_BLOCKED"
        assert "BLOCKED_PATH_PRESENT" in _failure_codes(blocked)
    finally:
        close_candidate_fixture(fixture)

    second = build_candidate_fixture(tmp_path / "expired")
    try:
        run_root = _prepare_retained_run_material(second)
        assert second.client.post(candidate_url(second)).status_code == 200
        old_plan = second.client.post(apply_plan_url(second)).json()["plan"]
        (second.source_repo / "README.md").write_text("# newer owner state\n")
        new_plan = second.client.post(apply_plan_url(second)).json()["plan"]
        assert new_plan["id"] != old_plan["id"]
        review = ApplyRevertFixture(second, run_root, old_plan)
        blocked, _ = _apply(review)
        assert blocked["state"] == "PREFLIGHT_BLOCKED"
        assert _failure_codes(blocked) & {
            "PLAN_SUPERSEDED",
            "PLAN_EXPIRED",
        }
    finally:
        close_candidate_fixture(second)


def test_candidate_and_repository_unavailable_are_truthful_preflight_blockers(
    tmp_path: Path,
) -> None:
    unavailable_candidate = build_candidate_fixture(
        tmp_path / "candidate-unavailable",
        run_status="failed",
    )
    try:
        _prepare_retained_run_material(unavailable_candidate)
        candidate_review = unavailable_candidate.client.post(
            candidate_url(unavailable_candidate)
        )
        assert candidate_review.status_code == 200
        assert candidate_review.json()["candidate"] is None
        plan_payload = unavailable_candidate.client.post(
            apply_plan_url(unavailable_candidate)
        ).json()["plan"]
        with unavailable_candidate.client.app.state.session_factory() as session:
            plan = session.scalar(
                select(ApplyPlan).where(
                    ApplyPlan.plan_id == plan_payload["id"]
                )
            )
            assert plan is not None
            with pytest.raises(ApplySessionError) as error:
                apply_accepted_changes(
                    session,
                    owner_id=unavailable_candidate.owner_id,
                    plan=plan,
                    source_repo=unavailable_candidate.source_repo,
                    confirmed=True,
                )
            assert error.value.code == "CANDIDATE_UNAVAILABLE"
    finally:
        close_candidate_fixture(unavailable_candidate)

    with phase18b_fixture(tmp_path / "repository-unavailable") as fixture:
        moved = tmp_path / "moved-source-repository"
        fixture.source_repo.rename(moved)
        result, created = _apply(fixture)
        assert created is True
        assert result["state"] == "PREFLIGHT_BLOCKED"
        assert "REPOSITORY_UNAVAILABLE" in _failure_codes(result)
        assert not (moved / "created.txt").exists()


def test_apply_is_idempotent_and_cross_owner_service_access_is_hidden(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        first, first_created = _apply(fixture)
        second, second_created = _apply(fixture)

        assert first_created is True
        assert second_created is False
        assert second["id"] == first["id"]
        assert second["state"] == "APPLIED"
        with fixture.factory() as session:
            assert (
                session.scalar(select(ApplySession).where(ApplySession.run_id == fixture.run_id))
                is not None
            )
            assert len(
                list(
                    session.scalars(
                        select(ApplySession).where(
                            ApplySession.run_id == fixture.run_id
                        )
                    )
                )
            ) == 1
            with pytest.raises(ApplySessionError) as error:
                apply_accepted_changes(
                    session,
                    owner_id=fixture.owner_id + 100_000,
                    plan=_plan_row(session, fixture),
                    source_repo=fixture.source_repo,
                    confirmed=True,
                )
            assert error.value.code == "APPLY_PLAN_NOT_FOUND"


def test_concurrent_apply_requests_create_one_session_and_mutate_once(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        plan_id = fixture.plan["id"]
        review_url = f"/api/apply-plans/{plan_id}/apply-sessions"
        request = {
            "confirmation": APPLY_CONFIRMATION,
            "expected_plan_digest": fixture.plan["advanced"]["plan_digest"],
            "expected_candidate_digest": fixture.plan["advanced"][
                "candidate_digest"
            ],
        }

        def submit_apply(_ordinal: int):
            return fixture.client.post(review_url, json=request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit_apply, range(2)))

        assert {response.status_code for response in responses} == {200}
        session_ids = {
            response.json()["session"]["id"] for response in responses
        }
        assert len(session_ids) == 1
        observed_states = {
            response.json()["session"]["state"] for response in responses
        }
        assert observed_states <= {"APPLYING", "APPLIED"}
        assert "APPLIED" in observed_states
        final = fixture.client.get(
            f"/api/apply-sessions/{next(iter(session_ids))}"
        )
        assert final.status_code == 200
        assert final.json()["session"]["state"] == "APPLIED"
        assert (fixture.source_repo / "created.txt").read_bytes() == (
            b"created by run\n"
        )
        with fixture.factory() as session:
            rows = list(
                session.scalars(
                    select(ApplySession).where(
                        ApplySession.apply_plan_public_id == plan_id
                    )
                )
            )
            assert len(rows) == 1


def test_partial_repository_state_blocks_a_different_plan_with_sanitized_code(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        operation_failed = False

        def partial_fault(phase: str, _entry: ApplySessionEntry) -> None:
            nonlocal operation_failed
            if phase == "after_apply_operation" and not operation_failed:
                operation_failed = True
                raise RuntimeError("controlled Apply failure")
            if phase == "before_apply_compensation":
                raise RuntimeError("controlled compensation failure")

        partial, _ = _apply(fixture, fault_injector=partial_fault)
        assert partial["state"] == "APPLY_FAILED_PARTIAL"
        (fixture.source_repo / "README.md").write_text(
            "# force a distinct immutable Plan binding\n"
        )
        plan_response = fixture.client.post(apply_plan_url(fixture.candidate))
        assert plan_response.status_code == 200
        next_plan = plan_response.json()["plan"]
        assert next_plan["id"] != fixture.plan["id"]

        response = fixture.client.post(
            f"/api/apply-plans/{next_plan['id']}/apply-sessions",
            json={
                "confirmation": APPLY_CONFIRMATION,
                "expected_plan_digest": next_plan["advanced"]["plan_digest"],
                "expected_candidate_digest": next_plan["advanced"][
                    "candidate_digest"
                ],
            },
        )

        assert response.status_code == 409
        assert _response_error_code(response) == "CONCURRENT_APPLY"
        serialized = json.dumps(response.json(), sort_keys=True)
        assert str(fixture.source_repo) not in serialized
        assert str(fixture.run_worktree) not in serialized


def test_cross_plan_active_apply_returns_sanitized_concurrent_apply_not_500(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        entered = Event()
        release = Event()
        paused = False

        def pause_before_mutation(
            phase: str,
            _entry: ApplySessionEntry,
        ) -> None:
            nonlocal paused
            if phase == "before_apply_operation" and not paused:
                paused = True
                entered.set()
                assert release.wait(timeout=20)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _apply,
                fixture,
                fault_injector=pause_before_mutation,
            )
            try:
                assert entered.wait(timeout=20)
                (fixture.source_repo / "README.md").write_text(
                    "# unrelated change creates Plan version two\n"
                )
                plan_response = fixture.client.post(
                    apply_plan_url(fixture.candidate)
                )
                assert plan_response.status_code == 200
                next_plan = plan_response.json()["plan"]
                assert next_plan["id"] != fixture.plan["id"]
                response = fixture.client.post(
                    f"/api/apply-plans/{next_plan['id']}/apply-sessions",
                    json={
                        "confirmation": APPLY_CONFIRMATION,
                        "expected_plan_digest": next_plan["advanced"][
                            "plan_digest"
                        ],
                        "expected_candidate_digest": next_plan["advanced"][
                            "candidate_digest"
                        ],
                    },
                )
                assert response.status_code == 409
                assert _response_error_code(response) == "CONCURRENT_APPLY"
                serialized = json.dumps(response.json(), sort_keys=True)
                assert str(fixture.source_repo) not in serialized
                assert str(fixture.run_worktree) not in serialized
            finally:
                release.set()
            original_result, _ = future.result(timeout=30)

        assert original_result["state"] in {
            "APPLIED",
            "APPLY_FAILED_RECOVERED",
        }
        assert (fixture.source_repo / "README.md").read_text() == (
            "# unrelated change creates Plan version two\n"
        )


def test_concurrent_revert_requests_are_idempotent_and_cas_safe(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        entered = Event()
        release = Event()
        paused = False

        def pause_before_reverse(
            phase: str,
            _entry: ApplySessionEntry,
        ) -> None:
            nonlocal paused
            if phase == "before_revert_operation" and not paused:
                paused = True
                entered.set()
                assert release.wait(timeout=20)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _revert,
                fixture,
                applied["id"],
                fault_injector=pause_before_reverse,
            )
            try:
                assert entered.wait(timeout=20)
                concurrent = fixture.client.post(
                    f"/api/apply-sessions/{applied['id']}/reverts",
                    json={
                        "confirmation": REVERT_CONFIRMATION,
                        "expected_journal_digest": applied["journal_digest"],
                    },
                )
                assert concurrent.status_code == 200
                assert concurrent.json()["session"]["id"] == applied["id"]
                assert concurrent.json()["session"]["state"] == "REVERTING"
            finally:
                release.set()
            first, changed = future.result(timeout=30)

        assert changed is True
        assert first["state"] == "REVERTED"
        final = fixture.client.get(f"/api/apply-sessions/{applied['id']}")
        assert final.status_code == 200
        assert final.json()["session"]["state"] == "REVERTED"
        assert not (fixture.source_repo / "created.txt").exists()
        assert (fixture.source_repo / "modify.txt").read_bytes() == (
            b"before modify\n"
        )
        assert (fixture.source_repo / "delete.txt").read_bytes() == (
            b"delete baseline\n"
        )


def test_apply_failure_after_one_operation_is_fully_compensated(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        before_git = _git_boundary(fixture.source_repo)
        before = {
            "modify": (fixture.source_repo / "modify.txt").read_bytes(),
            "delete": (fixture.source_repo / "delete.txt").read_bytes(),
            "asset": (fixture.source_repo / "asset.bin").read_bytes(),
        }
        calls = 0

        def fault(phase: str, _entry: ApplySessionEntry) -> None:
            nonlocal calls
            if phase == "after_apply_operation":
                calls += 1
                if calls == 1:
                    raise RuntimeError("controlled test fault")

        result, _ = _apply(fixture, fault_injector=fault)

        with fixture.factory() as session:
            persisted = session.scalar(
                select(ApplySession).where(
                    ApplySession.session_id == result["id"]
                )
            )
            assert persisted is not None
            diagnostic = {
                "before": json.loads(persisted.before_evidence_json),
                "after": json.loads(persisted.after_evidence_json),
                "compensation": json.loads(
                    persisted.compensation_evidence_json
                ),
            }
        assert result["state"] == "APPLY_FAILED_RECOVERED", json.dumps(
            diagnostic, sort_keys=True
        )
        assert result["integrity_check_result"] == "COMPENSATED"
        assert (fixture.source_repo / "modify.txt").read_bytes() == before["modify"]
        assert (fixture.source_repo / "delete.txt").read_bytes() == before["delete"]
        assert (fixture.source_repo / "asset.bin").read_bytes() == before["asset"]
        assert not (fixture.source_repo / "created.txt").exists()
        assert result["advanced"]["compensation"]
        assert _git_boundary(fixture.source_repo) == before_git


def test_failed_apply_compensation_reports_partial_state(tmp_path: Path) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        operation_failed = False

        def fault(phase: str, _entry: ApplySessionEntry) -> None:
            nonlocal operation_failed
            if phase == "after_apply_operation" and not operation_failed:
                operation_failed = True
                raise RuntimeError("controlled apply failure")
            if phase == "before_apply_compensation":
                raise RuntimeError("controlled compensation failure")

        result, _ = _apply(fixture, fault_injector=fault)

        assert result["state"] == "APPLY_FAILED_PARTIAL"
        assert result["integrity_check_result"] == "PARTIAL"
        assert any(
            item["result"] == "FAILED"
            for item in result["advanced"]["compensation"]
        )
        assert result["revert_available"] is False


def test_database_commit_failure_after_filesystem_mutation_compensates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        before_git = _git_boundary(fixture.source_repo)
        before_files = {
            "modify.txt": (fixture.source_repo / "modify.txt").read_bytes(),
            "delete.txt": (fixture.source_repo / "delete.txt").read_bytes(),
            "asset.bin": (fixture.source_repo / "asset.bin").read_bytes(),
        }
        with fixture.factory() as session:
            original_commit = session.commit
            armed = False
            failed_once = False

            def arm_after_filesystem_mutation(
                phase: str,
                _entry: ApplySessionEntry,
            ) -> None:
                nonlocal armed
                if phase == "after_apply_operation":
                    armed = True

            def fail_commit_after_durable_write() -> None:
                nonlocal failed_once
                if armed and not failed_once:
                    failed_once = True
                    original_commit()
                    raise RuntimeError(
                        "controlled commit acknowledgement failure"
                    )
                original_commit()

            monkeypatch.setattr(session, "commit", fail_commit_after_durable_write)
            row, created = apply_accepted_changes(
                session,
                owner_id=fixture.owner_id,
                plan=_plan_row(session, fixture),
                source_repo=fixture.source_repo,
                confirmed=True,
                fault_injector=arm_after_filesystem_mutation,
            )
            result = apply_session_out(session, row)

        assert created is True
        assert failed_once is True
        assert result["state"] == "APPLY_FAILED_RECOVERED"
        assert result["integrity_check_result"] == "COMPENSATED"
        assert not (fixture.source_repo / "created.txt").exists()
        for path, payload in before_files.items():
            assert (fixture.source_repo / path).read_bytes() == payload
        assert _git_boundary(fixture.source_repo) == before_git


@pytest.mark.parametrize("race_kind", ["rename", "symlink"])
def test_path_race_never_overwrites_newer_content_or_follows_symlink(
    tmp_path: Path,
    race_kind: str,
) -> None:
    after = b"approved postimage\n"
    record = {
        "path": "modify.txt",
        "change_type": "modified",
        "before_sha256": sha256_bytes(b"before modify\n"),
        "after_sha256": sha256_bytes(after),
        "before_size": len(b"before modify\n"),
        "after_size": len(after),
        "before_mode": 0o644,
        "after_mode": 0o644,
        "content_kind": "text",
        "added_lines": 1,
        "removed_lines": 1,
        "changed_hunks": 1,
        "content_included": False,
    }
    with phase18b_fixture(
        tmp_path,
        manifest_records=[record],
        postimages={"modify.txt": after},
    ) as fixture:
        target = fixture.source_repo / "modify.txt"
        preserved = fixture.source_repo / "modify-owner-preserved.txt"
        outside = tmp_path / "outside-race-target.txt"
        outside.write_bytes(b"outside newer content\n")
        injected = False

        def race_before_mutation(
            phase: str,
            entry: ApplySessionEntry,
        ) -> None:
            nonlocal injected
            if (
                phase == "before_apply_operation"
                and entry.repository_path == "modify.txt"
                and not injected
            ):
                injected = True
                target.rename(preserved)
                if race_kind == "rename":
                    target.write_bytes(b"newer replacement content\n")
                else:
                    target.symlink_to(outside)

        result, _ = _apply(fixture, fault_injector=race_before_mutation)

        assert injected is True
        assert result["state"] == "APPLY_FAILED_PARTIAL"
        assert preserved.read_bytes() == b"before modify\n"
        if race_kind == "rename":
            assert target.read_bytes() == b"newer replacement content\n"
        else:
            assert target.is_symlink()
            assert target.resolve() == outside.resolve()
            assert outside.read_bytes() == b"outside newer content\n"
        assert after not in {
            preserved.read_bytes(),
            outside.read_bytes(),
        }


def test_successful_revert_is_exact_idempotent_and_preserves_unrelated_changes(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        before_git = _git_boundary(fixture.source_repo)
        original = {
            "modify": (fixture.source_repo / "modify.txt").read_bytes(),
            "delete": (fixture.source_repo / "delete.txt").read_bytes(),
            "asset": (fixture.source_repo / "asset.bin").read_bytes(),
        }
        unrelated = fixture.source_repo / "after-apply-owner-note.txt"
        applied, _ = _apply(fixture)
        unrelated.write_bytes(b"written after apply\n")

        reverted, first_changed = _revert(fixture, applied["id"])
        repeated, second_changed = _revert(fixture, applied["id"])

        assert first_changed is True
        assert second_changed is False
        assert repeated["id"] == reverted["id"]
        assert reverted["state"] == "REVERTED"
        assert not (fixture.source_repo / "created.txt").exists()
        assert (fixture.source_repo / "modify.txt").read_bytes() == original["modify"]
        assert (fixture.source_repo / "delete.txt").read_bytes() == original["delete"]
        assert (fixture.source_repo / "asset.bin").read_bytes() == original["asset"]
        assert unrelated.read_bytes() == b"written after apply\n"
        assert _git_boundary(fixture.source_repo) == before_git


@pytest.mark.parametrize("boundary", ["staged", "wrong_branch", "commit"])
def test_revert_blocks_git_boundary_changes_before_any_reverse_mutation(
    tmp_path: Path,
    boundary: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        after_apply = {
            path: (fixture.source_repo / path).read_bytes()
            for path in ("created.txt", "modify.txt", "asset.bin")
        }
        if boundary == "staged":
            (fixture.source_repo / "README.md").write_text(
                "# staged after apply\n"
            )
            run_command(fixture.source_repo, "git", "add", "README.md")
        elif boundary == "wrong_branch":
            run_command(
                fixture.source_repo,
                "git",
                "branch",
                "-m",
                "not-main",
            )
        else:
            run_command(fixture.source_repo, "git", "add", "-A")
            run_command(
                fixture.source_repo,
                "git",
                "commit",
                "-m",
                "fixture commit boundary",
            )

        blocked, changed = _revert(fixture, applied["id"])

        assert changed is True
        assert blocked["state"] == "REVERT_BLOCKED"
        assert _failure_codes(blocked) & {
            "STAGED_PATHS_PRESENT",
            "WRONG_BRANCH",
            "BRANCH_CHANGED",
            "HEAD_CHANGED",
            "INDEX_CHANGED",
            "REFS_CHANGED",
        }
        assert {
            path: (fixture.source_repo / path).read_bytes()
            for path in ("created.txt", "modify.txt", "asset.bin")
        } == after_apply
        assert not (fixture.source_repo / "delete.txt").exists()


def test_post_apply_path_change_blocks_all_path_revert_without_overwrite(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        created = fixture.source_repo / "created.txt"
        created.write_bytes(b"newer owner change\n")
        other_after = (fixture.source_repo / "modify.txt").read_bytes()

        result, changed = _revert(fixture, applied["id"])

        assert changed is True
        assert result["state"] == "REVERT_BLOCKED"
        assert "REVERT_PRECONDITION_CONFLICT" in _failure_codes(result)
        assert created.read_bytes() == b"newer owner change\n"
        assert (fixture.source_repo / "modify.txt").read_bytes() == other_after


def test_revert_failure_compensates_to_applied_state(tmp_path: Path) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        applied_bytes = {
            "created": (fixture.source_repo / "created.txt").read_bytes(),
            "modify": (fixture.source_repo / "modify.txt").read_bytes(),
            "asset": (fixture.source_repo / "asset.bin").read_bytes(),
        }
        calls = 0

        def fault(phase: str, _entry: ApplySessionEntry) -> None:
            nonlocal calls
            if phase == "after_revert_operation":
                calls += 1
                if calls == 1:
                    raise RuntimeError("controlled reverse failure")

        result, _ = _revert(
            fixture,
            applied["id"],
            fault_injector=fault,
        )

        assert result["state"] == "REVERT_BLOCKED"
        assert result["integrity_check_result"] == "REVERT_COMPENSATED"
        assert (fixture.source_repo / "created.txt").read_bytes() == applied_bytes["created"]
        assert (fixture.source_repo / "modify.txt").read_bytes() == applied_bytes["modify"]
        assert (fixture.source_repo / "asset.bin").read_bytes() == applied_bytes["asset"]
        assert not (fixture.source_repo / "delete.txt").exists()


def test_revert_failed_compensation_reports_truthful_partial_state(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        operation_failed = False

        def fault(phase: str, _entry: ApplySessionEntry) -> None:
            nonlocal operation_failed
            if phase == "after_revert_operation" and not operation_failed:
                operation_failed = True
                raise RuntimeError("controlled reverse failure")
            if phase == "before_revert_compensation":
                raise RuntimeError("controlled reverse compensation failure")

        result, _ = _revert(
            fixture,
            applied["id"],
            fault_injector=fault,
        )

        assert result["state"] == "REVERT_FAILED_PARTIAL"
        assert result["integrity_check_result"] == "REVERT_PARTIAL"
        assert result["revert_available"] is False


@pytest.mark.parametrize(
    ("durable_state", "material_state", "expected"),
    [
        ("APPLYING", "after", "APPLIED"),
        ("APPLYING", "before", "APPLY_FAILED_RECOVERED"),
        ("REVERTING", "before", "REVERTED"),
        ("REVERTING", "after", "REVERT_BLOCKED"),
    ],
)
def test_restart_reconciliation_never_replays_mutation(
    tmp_path: Path,
    durable_state: str,
    material_state: str,
    expected: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        if material_state == "before":
            reverted, _ = _revert(fixture, applied["id"])
            assert reverted["state"] == "REVERTED"
        elif durable_state == "REVERTING":
            raised = False

            def before_reverse_fault(
                phase: str,
                _entry: ApplySessionEntry,
            ) -> None:
                nonlocal raised
                if phase == "before_revert_operation" and not raised:
                    raised = True
                    raise RuntimeError("controlled crash-before-reverse fixture")

            recovered, _ = _revert(
                fixture,
                applied["id"],
                fault_injector=before_reverse_fault,
            )
            assert recovered["state"] == "REVERT_BLOCKED"
        with fixture.factory() as session:
            row = session.scalar(
                select(ApplySession).where(
                    ApplySession.session_id == applied["id"]
                )
            )
            assert row is not None
            # Simulate a crash after durable state transition. The reconciler
            # inspects actual evidence and never executes an Apply/Revert.
            row.state = durable_state
            session.commit()
            reconciled = reconcile_apply_session(
                session,
                apply_session=row,
                source_repo=fixture.source_repo,
            )
            assert reconciled.state == expected


def test_vol18_003_schema_journal_and_append_only_audit_are_present(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        engine = fixture.client.app.state.engine
        assert {
            "apply_sessions",
            "apply_session_entries",
            "apply_session_audits",
        } <= set(inspect(engine).get_table_names())
        with fixture.factory() as session:
            assert (
                session.scalar(
                    select(SchemaVersion).where(
                        SchemaVersion.version == "vol18.003"
                    )
                )
                is not None
            )
            row = session.scalar(
                select(ApplySession).where(
                    ApplySession.session_id == applied["id"]
                )
            )
            assert row is not None
            entries = apply_session_entries(session, row)
            assert len(entries) == row.included_path_count == 4
            assert all(
                item.before_material is not None
                for item in entries
                if item.before_present
            )
            assert all(
                item.after_material is not None
                for item in entries
                if item.after_present
            )
            assert list(
                session.scalars(
                    select(ApplySessionAudit).where(
                        ApplySessionAudit.apply_session_id == row.id
                    )
                )
            )
        with engine.connect() as connection:
            trigger_names = {
                item[0]
                for item in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='trigger' ORDER BY name"
                    )
                )
            }
        assert {
            "trg_apply_session_audits_no_update",
            "trg_apply_session_audits_no_delete",
        } <= trigger_names


def test_apply_revert_git_allowlist_excludes_every_mutating_command() -> None:
    forbidden = {
        "add",
        "checkout",
        "clean",
        "commit",
        "fetch",
        "merge",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "stage",
        "stash",
        "switch",
        "tag",
    }
    assert APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST
    for command in APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST:
        assert forbidden.isdisjoint(command.split())


def test_apply_revert_api_requires_literal_confirmation_and_is_idempotent(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        plan_id = fixture.plan["id"]
        review_url = f"/api/apply-plans/{plan_id}/apply-sessions"
        review = fixture.client.get(review_url)
        assert review.status_code == 200, review.text
        envelope = review.json()
        assert envelope["session"] is None
        assert envelope["actions"]["can_apply"] is True
        assert envelope["apply_confirmation"]["explicit_confirmation_required"] is True
        assert not (fixture.source_repo / "created.txt").exists()

        missing = fixture.client.post(review_url, json={})
        wrong = fixture.client.post(
            review_url,
            json={
                "confirmation": "REVIEW_ONLY",
                "expected_plan_digest": fixture.plan["advanced"]["plan_digest"],
                "expected_candidate_digest": fixture.plan["advanced"]["candidate_digest"],
            },
        )
        assert missing.status_code == wrong.status_code == 422
        assert not (fixture.source_repo / "created.txt").exists()

        request = {
            "confirmation": APPLY_CONFIRMATION,
            "expected_plan_digest": fixture.plan["advanced"]["plan_digest"],
            "expected_candidate_digest": fixture.plan["advanced"]["candidate_digest"],
        }
        stale_binding = fixture.client.post(
            review_url,
            json={**request, "expected_plan_digest": "0" * 64},
        )
        assert stale_binding.status_code == 409
        assert not (fixture.source_repo / "created.txt").exists()
        first = fixture.client.post(review_url, json=request)
        second = fixture.client.post(review_url, json=request)
        assert first.status_code == second.status_code == 200
        assert first.json()["session"]["state"] == "APPLIED"
        assert second.json()["session"]["id"] == first.json()["session"]["id"]
        assert (fixture.source_repo / "created.txt").exists()

        session_id = first.json()["session"]["id"]
        retrieved = fixture.client.get(f"/api/apply-sessions/{session_id}")
        refreshed = fixture.client.get(review_url)
        assert retrieved.status_code == refreshed.status_code == 200
        assert retrieved.json()["session"]["state"] == "APPLIED"
        assert refreshed.json()["session"]["state"] == "APPLIED"
        assert (fixture.source_repo / "created.txt").exists()
        revert_url = f"/api/apply-sessions/{session_id}/reverts"
        journal_digest = first.json()["session"]["journal_digest"]
        missing_revert = fixture.client.post(revert_url, json={})
        assert missing_revert.status_code == 422
        stale_revert = fixture.client.post(
            revert_url,
            json={
                "confirmation": REVERT_CONFIRMATION,
                "expected_journal_digest": "0" * 64,
            },
        )
        assert stale_revert.status_code == 409
        assert (fixture.source_repo / "created.txt").exists()
        reverted = fixture.client.post(
            revert_url,
            json={
                "confirmation": REVERT_CONFIRMATION,
                "expected_journal_digest": journal_digest,
            },
        )
        repeated = fixture.client.post(
            revert_url,
            json={
                "confirmation": REVERT_CONFIRMATION,
                "expected_journal_digest": journal_digest,
            },
        )
        assert reverted.status_code == repeated.status_code == 200
        assert reverted.json()["session"]["state"] == "REVERTED"
        assert repeated.json()["session"]["id"] == session_id


def test_apply_revert_api_auth_non_disclosure_and_legacy_routes_remain_absent(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        plan_id = fixture.plan["id"]
        review_url = f"/api/apply-plans/{plan_id}/apply-sessions"
        fixture.client.cookies.clear()
        assert fixture.client.get(review_url).status_code == 401
        assert fixture.client.post(review_url, json={}).status_code == 401

        missing = f"/api/apply-plans/ap_{'0' * 40}/apply-sessions"
        # Authentication is restored through the fixture's real login helper
        # cookie by rebuilding the client cookie from its persisted test token.
        from tests.test_self_hosting import init_and_login

        init_and_login(fixture.client)
        assert fixture.client.get(missing).status_code == 404
        syntactically_valid_request = {
            "confirmation": APPLY_CONFIRMATION,
            "expected_plan_digest": "0" * 64,
            "expected_candidate_digest": "0" * 64,
        }
        assert (
            fixture.client.post(
                missing,
                json=syntactically_valid_request,
            ).status_code
            == 404
        )

        raw_token = "phase18-2b-second-owner"
        password_hash, password_salt = hash_password("second-owner-password")
        with fixture.factory() as session:
            second_owner = User(
                username="phase18-2b-second-owner",
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
        wrong_owner_get = fixture.client.get(review_url, headers=headers)
        wrong_owner_post = fixture.client.post(
            review_url,
            json=syntactically_valid_request,
            headers=headers,
        )
        missing_get = fixture.client.get(missing, headers=headers)
        missing_post = fixture.client.post(
            missing,
            json=syntactically_valid_request,
            headers=headers,
        )
        assert (
            wrong_owner_get.status_code
            == wrong_owner_post.status_code
            == missing_get.status_code
            == missing_post.status_code
            == 404
        )
        for wrong_owner, absent in (
            (wrong_owner_get, missing_get),
            (wrong_owner_post, missing_post),
        ):
            assert {
                key: value
                for key, value in wrong_owner.json()["error"].items()
                if key != "request_id"
            } == {
                key: value
                for key, value in absent.json()["error"].items()
                if key != "request_id"
            }
        assert fixture.client.post(f"/api/apply-plans/{plan_id}/apply").status_code == 404
        assert fixture.client.post(f"/api/apply-plans/{plan_id}/revert").status_code == 404


def test_ui_copy_confirmation_surfaces_and_phase18_4_boundary(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        page = fixture.client.get("/twos")
        script = fixture.client.get(
            "/static_cockpit/vol12_static_mvp/twos_command_center.js"
        )
        styles = fixture.client.get(
            "/static_cockpit/vol12_static_mvp/styles.css"
        )
        assert page.status_code == script.status_code == styles.status_code == 200
        assert (
            "The locked file set reflects this captured Run Result. Candidate "
            "readiness, Owner review, and independent Verification are shown "
            "separately below. Reviewing it does not change your source "
            "repository."
        ) in page.text
        assert "produced by this accepted and independently verified Run" not in page.text
        assert (
            "Read-only instructions for how TWOS would apply the locked "
            "Candidate to the current repository. Reviewing it does not apply "
            "anything."
        ) in page.text
        assert (
            "Apply Accepted Changes is the first action in this workflow that "
            "modifies the real source repository."
        ) in page.text
        assert "Apply Accepted Changes" in page.text
        assert "Revert Applied Changes" in page.text
        assert "Verify Applied Changes" in page.text
        assert 'id="apply-confirmation-dialog"' in page.text
        assert 'id="revert-confirmation-dialog"' in page.text
        assert '<details id="advanced-panel"' in page.text
        assert "@media (max-width: 420px)" in styles.text
        assert 'id="push-to-origin-main"' in page.text
        assert 'id="push-to-origin-main" class="button button-danger" type="button" hidden disabled' in page.text
        apply_action = script.text.split(
            "async function confirmApplyAcceptedChanges()",
            1,
        )[1].split("async function confirmRevertAppliedChanges", 1)[0]
        revert_action = script.text.split(
            "async function confirmRevertAppliedChanges()",
            1,
        )[1].split("async function cancelCodex", 1)[0]
        for earlier_phase_action in (apply_action, revert_action):
            assert '"/push-preflights"' not in earlier_phase_action
            assert '"/push-attempts"' not in earlier_phase_action
            assert "confirmPushToOriginMain" not in earlier_phase_action


def test_default_and_advanced_payloads_hide_material_secrets_and_absolute_paths(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        result, _ = _apply(fixture)
        serialized = json.dumps(result, sort_keys=True)
        assert str(fixture.source_repo) not in serialized
        assert str(fixture.run_worktree) not in serialized
        assert "created by run" not in serialized
        assert "\\u0000\\u0010" not in serialized
        assert "before_material" not in serialized
        assert "after_material" not in serialized
        assert "credential" not in serialized.casefold()
        assert "token" not in serialized.casefold()
