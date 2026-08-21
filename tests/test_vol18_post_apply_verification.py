from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from tests.test_self_hosting import init_and_login, run_command
from tests.test_vol18_apply_revert import (
    ApplyRevertFixture,
    _apply,
    _git_boundary,
    _prepare_retained_run_material,
    _response_error_code,
    _revert,
    phase18b_fixture,
)
from tests.test_vol18_delivery_candidate import (
    build_candidate_fixture,
    candidate_url,
    close_candidate_fixture,
)
from tests.test_vol18_review_apply_plan import apply_plan_url
from twos_runtime.apply_sessions import APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST
from twos_runtime.models import (
    ApplySession,
    PostApplyVerification,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.post_apply_verifications import (
    get_or_create_post_apply_verification,
)
import twos_runtime.post_apply_verifications as post_apply_service
from twos_runtime.security import hash_password, hash_token


SECRET_CANARY = "phase18-post-apply-secret-must-not-render"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _verification_url(session_id: str) -> str:
    return f"/api/apply-sessions/{session_id}/post-apply-verifications"


def _filesystem_boundary(root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for directory, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        directory_names[:] = sorted(
            name for name in directory_names if name != ".git"
        )
        for name in sorted(file_names):
            path = directory_path / name
            relative = path.relative_to(root).as_posix()
            item_stat = path.lstat()
            if stat.S_ISREG(item_stat.st_mode):
                material = path.read_bytes()
                result[relative] = {
                    "kind": "regular",
                    "sha256": hashlib.sha256(material).hexdigest(),
                    "size": len(material),
                    "mode": item_stat.st_mode & 0o777,
                }
            elif stat.S_ISLNK(item_stat.st_mode):
                result[relative] = {
                    "kind": "symlink",
                    "target": os.readlink(path),
                    "mode": item_stat.st_mode & 0o777,
                }
            else:
                result[relative] = {
                    "kind": "unsupported",
                    "mode": item_stat.st_mode & 0o777,
                }
    return result


def _post_verification(
    fixture: ApplyRevertFixture,
    applied: dict[str, object],
):
    return fixture.client.post(
        _verification_url(str(applied["id"])),
        json={"expected_journal_digest": applied["journal_digest"]},
    )


def _blocker_codes(review: dict[str, object]) -> set[str]:
    verification = review.get("verification")
    assert isinstance(verification, dict)
    return {
        str(item.get("code") or "")
        for item in verification.get("blockers", [])
        if isinstance(item, dict)
    }


def _verification_rows(fixture: ApplyRevertFixture) -> list[PostApplyVerification]:
    with fixture.factory() as session:
        return list(
            session.scalars(
                select(PostApplyVerification).order_by(PostApplyVerification.id)
            ).all()
        )


def _git_artifact_path(repo: Path, name: str) -> Path:
    raw = run_command(repo, "git", "rev-parse", "--git-path", name).stdout.strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo / candidate
    return candidate.resolve(strict=True)


def _advance_mtime(path: Path) -> tuple[int, int]:
    before = path.stat()
    after_ns = before.st_mtime_ns + 1_000_000_000
    os.utime(
        path,
        ns=(before.st_atime_ns, after_ns),
        follow_symlinks=False,
    )
    observed_ns = path.stat().st_mtime_ns
    assert observed_ns != before.st_mtime_ns
    return before.st_mtime_ns, observed_ns


def _test_status(review: dict[str, object], code: str) -> str:
    verification = review.get("verification")
    assert isinstance(verification, dict)
    tests = verification.get("tests")
    assert isinstance(tests, list)
    result = next(
        item
        for item in tests
        if isinstance(item, dict) and item.get("code") == code
    )
    return str(result.get("status") or "")


def test_post_apply_verification_passes_exact_create_modify_delete_binary_without_mutation(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        source_before = _filesystem_boundary(fixture.source_repo)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert verification["status"] == "PASSED"
        assert verification["status_label"] == "PASSED"
        assert verification["blockers"] == []
        assert review["actions"] == {"can_verify": True}
        files = {
            item["path"]: item
            for item in verification["changed_files"]
        }
        assert {
            path: files[path]["operation"]
            for path in ("created.txt", "modify.txt", "delete.txt")
        } == {
            "created.txt": "CREATE",
            "modify.txt": "MODIFY",
            "delete.txt": "DELETE",
        }
        assert files["asset.bin"] == {
            "path": "asset.bin",
            "operation": "MODIFY",
            "result": "PASSED",
        }
        assert all(item["result"] == "PASSED" for item in files.values())
        assert {item["status"] for item in verification["tests"]} == {"PASS"}
        assert verification["unexpected_files"] == []
        assert verification["advanced"]["policy_version"] == (
            "twos.post_apply_verification.v2"
        )
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_boundary(fixture.source_repo) == git_before

        serialized = json.dumps(review, sort_keys=True)
        assert str(tmp_path) not in serialized
        assert SECRET_CANARY not in serialized
        assert "\x00\x10\x02\x03\x04" not in serialized
        boundary_evidence = verification["advanced"]["boundary_evidence"]
        assert {
            key: value
            for key, value in boundary_evidence.items()
            if key not in {"git_fingerprints", "git_metadata_semantics"}
        } == {
            "head_ref_config_remote_mutation": False,
            "index_mutation": False,
            "inspection": "read_only",
            "git_policy": "explicit_read_only_allowlist",
            "git_commands": list(APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST),
            "source_mutation": False,
            "stage_commit_push": False,
        }
        assert boundary_evidence["git_metadata_semantics"] == {
            "refresh_observed": False,
            "categories": [],
            "blocking": False,
            "index_comparison": "content_digest_and_staged_state",
        }
        fingerprints = boundary_evidence["git_fingerprints"]
        assert fingerprints["expected"] == fingerprints["observed"]
        assert fingerprints["staged_path_count"] == 0
        assert all(
            SHA256_PATTERN.fullmatch(digest)
            for digest in fingerprints["expected"].values()
        )
        assert "can_stage" not in review["actions"]
        assert "can_commit" not in review["actions"]
        assert "can_push" not in review["actions"]


def test_git_status_and_git_directory_metadata_refresh_are_non_blocking(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        git_dir = _git_artifact_path(fixture.source_repo, ".")
        source_before = _filesystem_boundary(fixture.source_repo)
        index_before = _git_artifact_path(
            fixture.source_repo,
            "index",
        ).read_bytes()

        status = run_command(
            fixture.source_repo,
            "git",
            "status",
            "--short",
            "--untracked-files=all",
        )
        assert "created.txt" in status.stdout
        _advance_mtime(git_dir)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert verification["status"] == "PASSED"
        assert verification["unexpected_files"] == []
        assert _test_status(review, "UNEXPECTED_FILES") == "PASS"
        assert _test_status(review, "UNRELATED_CHANGES") == "PASS"
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_artifact_path(fixture.source_repo, "index").read_bytes() == index_before

        diagnostics = verification["advanced"]["diagnostics"]
        assert diagnostics["git_metadata_refresh_observed"] is True
        assert "git_internal_directory_metadata_refresh" in diagnostics[
            "git_metadata_refresh_categories"
        ]
        assert diagnostics["git_metadata_refresh_summary"]
        boundary = verification["advanced"]["boundary_evidence"]
        assert boundary["git_metadata_semantics"] == {
            "refresh_observed": True,
            "categories": diagnostics["git_metadata_refresh_categories"],
            "blocking": False,
            "index_comparison": "content_digest_and_staged_state",
        }
        serialized_default = json.dumps(
            verification["unexpected_files"],
            sort_keys=True,
        )
        assert ".git" not in serialized_default
        assert "excluded path withheld" not in serialized_default


def test_index_mtime_only_change_preserves_semantic_clean_index(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        index = _git_artifact_path(fixture.source_repo, "index")
        content_before = index.read_bytes()
        _advance_mtime(index)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert verification["status"] == "PASSED"
        assert verification["blockers"] == []
        assert verification["unexpected_files"] == []
        assert _test_status(review, "CLEAN_INDEX") == "PASS"
        assert index.read_bytes() == content_before
        fingerprints = verification["advanced"]["boundary_evidence"][
            "git_fingerprints"
        ]
        assert fingerprints["expected"]["index"] == fingerprints["observed"]["index"]
        assert fingerprints["staged_path_count"] == 0
        diagnostics = verification["advanced"]["diagnostics"]
        assert diagnostics["git_metadata_refresh_observed"] is True
        assert "index_metadata_refresh" in diagnostics[
            "git_metadata_refresh_categories"
        ]


def test_optional_git_lock_lifecycle_between_samples_is_non_blocking_and_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        original = post_apply_service._repository_observation
        calls = 0

        def observation_with_lock_lifecycle(**kwargs):
            nonlocal calls
            calls += 1
            observed = original(**kwargs)
            if calls == 1:
                git_dir = _git_artifact_path(fixture.source_repo, ".")
                lock = git_dir / "index.lock"
                assert not lock.exists()
                lock.write_bytes(b"")
                lock.unlink()
                _advance_mtime(git_dir)
            return observed

        monkeypatch.setattr(
            post_apply_service,
            "_repository_observation",
            observation_with_lock_lifecycle,
        )

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert calls == 2
        assert verification["status"] == "PASSED"
        assert verification["blockers"] == []
        assert verification["unexpected_files"] == []
        assert _test_status(review, "STABLE_OBSERVATION") == "PASS"
        assert verification["advanced"]["diagnostics"][
            "git_metadata_refresh_observed"
        ] is True


def test_semantic_index_digest_change_blocks_even_with_zero_staged_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        original = post_apply_service._repository_observation

        def observation_with_changed_index_digest(**kwargs):
            observed = json.loads(json.dumps(original(**kwargs)))
            observed["global"]["index"]["fingerprint"] = "f" * 64
            return observed

        monkeypatch.setattr(
            post_apply_service,
            "_repository_observation",
            observation_with_changed_index_digest,
        )

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert verification["status"] == "BLOCKED"
        assert "INDEX_CHANGED" in _blocker_codes(review)
        assert _test_status(review, "CLEAN_INDEX") == "BLOCKED"
        assert verification["advanced"]["diagnostics"]["staged_path_count"] == 0
        assert verification["advanced"]["diagnostics"][
            "git_metadata_refresh_observed"
        ] is False


def test_git_directory_security_metadata_change_remains_blocking(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        git_dir = _git_artifact_path(fixture.source_repo, ".")
        original_mode = stat.S_IMODE(git_dir.stat().st_mode)
        changed_mode = 0o700 if original_mode != 0o700 else 0o755
        git_dir.chmod(changed_mode)
        try:
            response = _post_verification(fixture, applied)
        finally:
            git_dir.chmod(original_mode)

        assert response.status_code == 200, response.text
        review = response.json()
        assert review["verification"]["status"] == "BLOCKED"
        assert "UNSAFE_OR_EXCLUDED_PATH_CHANGED" in _blocker_codes(review)
        assert _test_status(review, "UNEXPECTED_FILES") == "BLOCKED"


@pytest.mark.parametrize(
    ("file_type", "reason"),
    [
        ("symlink", "runtime_or_cache"),
        ("unsupported", "runtime_or_cache"),
        ("directory", "credential_or_secret"),
    ],
)
def test_git_path_identity_without_exact_safe_shape_is_never_metadata_normalized(
    file_type: str,
    reason: str,
) -> None:
    before = {
        "excluded_entries": [
            {
                "path_identity": post_apply_service._GIT_DIRECTORY_PATH_IDENTITY,
                "reason": reason,
                "file_type": file_type,
                "mode": 0o755,
                "size": 128,
                "mtime_ns": 1_000,
            }
        ]
    }
    after = json.loads(json.dumps(before))
    after["excluded_entries"][0]["size"] = 256
    after["excluded_entries"][0]["mtime_ns"] = 2_000

    assert post_apply_service._semantic_excluded_fingerprint(before) != (
        post_apply_service._semantic_excluded_fingerprint(after)
    )


@pytest.mark.parametrize(
    ("operation", "mutate"),
    [
        ("CREATE", lambda repo: (repo / "created.txt").write_bytes(b"changed create\n")),
        ("MODIFY", lambda repo: (repo / "modify.txt").write_bytes(b"changed modify\n")),
        ("DELETE", lambda repo: (repo / "delete.txt").write_bytes(b"recreated delete\n")),
    ],
)
def test_post_apply_verification_blocks_each_changed_applied_operation(
    tmp_path: Path,
    operation: str,
    mutate,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        mutate(fixture.source_repo)
        source_before = _filesystem_boundary(fixture.source_repo)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        assert review["verification"]["status"] == "BLOCKED"
        assert "APPLIED_PATH_CHANGED" in _blocker_codes(review)
        assert any(
            item["operation"] == operation and item["result"] == "BLOCKED"
            for item in review["verification"]["changed_files"]
        )
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_boundary(fixture.source_repo) == git_before


@pytest.mark.parametrize(
    ("operation", "mutate", "code"),
    [
        (
            "CREATE",
            lambda repo: (repo / "after-apply-unexpected.txt").write_text(
                "unexpected\n"
            ),
            "UNEXPECTED_FILE_CREATED",
        ),
        (
            "MODIFY",
            lambda repo: (repo / "README.md").write_text("# changed after apply\n"),
            "UNEXPECTED_FILE_MODIFIED",
        ),
        (
            "DELETE",
            lambda repo: (repo / "README.md").unlink(),
            "UNEXPECTED_FILE_DELETED",
        ),
    ],
)
def test_post_apply_verification_blocks_unexpected_create_modify_delete(
    tmp_path: Path,
    operation: str,
    mutate,
    code: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        mutate(fixture.source_repo)
        source_before = _filesystem_boundary(fixture.source_repo)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        assert review["verification"]["status"] == "BLOCKED"
        assert code in _blocker_codes(review)
        assert any(
            item["operation"] == operation
            for item in review["verification"]["unexpected_files"]
        )
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_boundary(fixture.source_repo) == git_before


@pytest.mark.parametrize("unsafe_kind", ["non_git_excluded", "symlink"])
def test_non_git_excluded_and_symlink_changes_remain_blocking(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        if unsafe_kind == "non_git_excluded":
            excluded = fixture.source_repo / "__pycache__"
            excluded.mkdir()
            (excluded / "owner-output.pyc").write_bytes(b"not executable bytecode")
        else:
            (fixture.source_repo / "owner-output-link").symlink_to("README.md")

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        verification = review["verification"]
        assert verification["status"] == "BLOCKED"
        assert "UNSAFE_OR_EXCLUDED_PATH_CHANGED" in _blocker_codes(review)
        assert _test_status(review, "UNEXPECTED_FILES") == "BLOCKED"
        assert verification["unexpected_files"] == [
            {
                "path": "[excluded path withheld]",
                "operation": "MODIFY",
            }
        ]


def test_apply_revert_index_mtime_boundary_behavior_is_not_changed_by_phase18_3_fix(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        _advance_mtime(_git_artifact_path(fixture.source_repo, "index"))

        reverted, changed = _revert(fixture, str(applied["id"]))

        assert changed is True
        assert reverted["state"] == "REVERT_BLOCKED"
        assert "INDEX_CHANGED" in {
            str(item.get("code") or "")
            for item in reverted.get("blockers", [])
            if isinstance(item, dict)
        }


@pytest.mark.parametrize(
    ("boundary", "expected_code"),
    [
        ("staged", "STAGED_PATHS_PRESENT"),
        ("head", "HEAD_CHANGED"),
        ("branch", "BRANCH_CHANGED"),
        ("refs", "REFS_CHANGED"),
        ("config", "CONFIG_CHANGED"),
        ("remote", "REMOTE_CHANGED"),
    ],
)
def test_post_apply_verification_blocks_git_boundary_changes_without_mutating_them(
    tmp_path: Path,
    boundary: str,
    expected_code: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        if boundary == "staged":
            run_command(fixture.source_repo, "git", "add", "created.txt")
        elif boundary == "head":
            run_command(
                fixture.source_repo,
                "git",
                "commit",
                "--allow-empty",
                "-m",
                "post-apply verification boundary fixture",
            )
        elif boundary == "branch":
            run_command(fixture.source_repo, "git", "branch", "-m", "not-main")
        elif boundary == "refs":
            run_command(
                fixture.source_repo,
                "git",
                "update-ref",
                "refs/tags/post-apply-verification-fixture",
                "HEAD",
            )
        elif boundary == "config":
            run_command(
                fixture.source_repo,
                "git",
                "config",
                "verification.fixture",
                "true",
            )
        else:
            run_command(
                fixture.source_repo,
                "git",
                "remote",
                "add",
                "verification-fixture",
                "https://example.invalid/owner/repository.git",
            )
        source_before = _filesystem_boundary(fixture.source_repo)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        assert review["verification"]["status"] == "BLOCKED"
        assert expected_code in _blocker_codes(review)
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_boundary(fixture.source_repo) == git_before
        assert "example.invalid" not in json.dumps(review, sort_keys=True)


def test_post_apply_verification_preserves_preexisting_modified_and_untracked_files(
    tmp_path: Path,
) -> None:
    candidate = build_candidate_fixture(tmp_path)
    try:
        run_root = _prepare_retained_run_material(candidate)
        modified = candidate.source_repo / "README.md"
        untracked = candidate.source_repo / "owner-notes.txt"
        modified.write_text("# preserved owner change\n")
        untracked.write_text("preserved private note\n")
        assert candidate.client.post(candidate_url(candidate)).status_code == 200
        plan_response = candidate.client.post(apply_plan_url(candidate))
        assert plan_response.status_code == 200, plan_response.text
        fixture = ApplyRevertFixture(
            candidate=candidate,
            run_worktree=run_root,
            plan=plan_response.json()["plan"],
        )
        assert fixture.plan["effective_state"] == "review_with_source_changes"
        modified_before = modified.read_bytes()
        untracked_before = untracked.read_bytes()
        applied, _ = _apply(fixture)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        verification = response.json()["verification"]
        assert verification["status"] == "PASSED"
        assert modified.read_bytes() == modified_before
        assert untracked.read_bytes() == untracked_before
        assert _git_boundary(fixture.source_repo) == git_before
        preserved = {
            item["path"]
            for item in verification["advanced"]["preserved_paths"]
        }
        assert {"README.md", "owner-notes.txt"} <= preserved
    finally:
        close_candidate_fixture(candidate)


def test_repeated_identical_verification_is_idempotent_and_changed_observation_appends_history(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)

        first = _post_verification(fixture, applied)
        second = _post_verification(fixture, applied)

        assert first.status_code == second.status_code == 200
        first_review = first.json()
        second_review = second.json()
        assert first_review["verification"]["status"] == "PASSED"
        assert second_review["verification"]["id"] == first_review["verification"]["id"]
        assert (
            second_review["verification"]["advanced"]["verification_digest"]
            == first_review["verification"]["advanced"]["verification_digest"]
        )
        assert len(second_review["history"]) == 1
        assert len(_verification_rows(fixture)) == 1

        _advance_mtime(_git_artifact_path(fixture.source_repo, "index"))
        _advance_mtime(_git_artifact_path(fixture.source_repo, "."))
        metadata_only = _post_verification(fixture, applied)
        assert metadata_only.status_code == 200, metadata_only.text
        metadata_review = metadata_only.json()
        assert metadata_review["verification"]["status"] == "PASSED"
        assert metadata_review["verification"]["id"] == first_review["verification"]["id"]
        assert metadata_review["verification"]["advanced"]["policy_version"] == (
            "twos.post_apply_verification.v2"
        )
        assert len(metadata_review["history"]) == 1
        assert len(_verification_rows(fixture)) == 1

        (fixture.source_repo / "modify.txt").write_bytes(b"changed after pass\n")
        changed = _post_verification(fixture, applied)

        assert changed.status_code == 200, changed.text
        changed_review = changed.json()
        assert changed_review["verification"]["status"] == "BLOCKED"
        assert changed_review["verification"]["id"] != first_review["verification"]["id"]
        assert len(changed_review["history"]) == 2
        rows = _verification_rows(fixture)
        assert len(rows) == 2
        assert rows[0].status == "PASSED"
        assert rows[0].verification_id == first_review["verification"]["id"]
        assert rows[1].status == "BLOCKED"


def test_v2_policy_creates_a_distinct_current_record_without_rewriting_v1_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        monkeypatch.setattr(
            post_apply_service,
            "POST_APPLY_VERIFICATION_POLICY_VERSION",
            "twos.post_apply_verification.v1",
        )
        legacy = _post_verification(fixture, applied)
        assert legacy.status_code == 200, legacy.text
        legacy_review = legacy.json()
        legacy_id = legacy_review["verification"]["id"]
        legacy_digest = legacy_review["verification"]["advanced"][
            "verification_digest"
        ]
        assert legacy_review["verification"]["advanced"]["policy_version"] == (
            "twos.post_apply_verification.v1"
        )

        monkeypatch.setattr(
            post_apply_service,
            "POST_APPLY_VERIFICATION_POLICY_VERSION",
            "twos.post_apply_verification.v2",
        )
        current = _post_verification(fixture, applied)

        assert current.status_code == 200, current.text
        review = current.json()
        assert review["verification"]["status"] == "PASSED"
        assert review["verification"]["id"] != legacy_id
        assert review["verification"]["advanced"]["policy_version"] == (
            "twos.post_apply_verification.v2"
        )
        assert len(review["history"]) == 2
        rows = _verification_rows(fixture)
        assert len(rows) == 2
        assert rows[0].verification_id == legacy_id
        assert rows[0].policy_version == "twos.post_apply_verification.v1"
        assert rows[0].verification_digest == legacy_digest
        assert rows[1].verification_id == review["verification"]["id"]
        assert rows[1].policy_version == "twos.post_apply_verification.v2"


def test_get_is_read_only_and_non_applied_reverted_and_missing_sessions_cannot_verify(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path / "get") as fixture:
        applied, _ = _apply(fixture)
        url = _verification_url(str(applied["id"]))
        before = _filesystem_boundary(fixture.source_repo)
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PostApplyVerification)
            ) == 0

        review = fixture.client.get(url)

        assert review.status_code == 200, review.text
        assert review.json()["verification"] is None
        assert review.json()["history"] == []
        assert review.json()["eligibility"]["status"] == "READY"
        with fixture.factory() as session:
            assert session.scalar(
                select(func.count()).select_from(PostApplyVerification)
            ) == 0
        assert _filesystem_boundary(fixture.source_repo) == before

        missing = fixture.client.post(
            _verification_url("aps_" + "0" * 40),
            json={"expected_journal_digest": "0" * 64},
        )
        assert missing.status_code == 404

    with phase18b_fixture(tmp_path / "blocked") as fixture:
        (fixture.source_repo / "modify.txt").write_bytes(b"conflict before apply\n")
        blocked, _ = _apply(fixture)
        assert blocked["state"] == "PREFLIGHT_BLOCKED"
        response = _post_verification(fixture, blocked)
        assert response.status_code == 409
        assert _response_error_code(response) == "APPLY_SESSION_NOT_APPLIED"
        assert _verification_rows(fixture) == []

    with phase18b_fixture(tmp_path / "reverted") as fixture:
        applied, _ = _apply(fixture)
        reverted, _ = _revert(fixture, str(applied["id"]))
        assert reverted["state"] == "REVERTED"
        response = _post_verification(fixture, reverted)
        assert response.status_code == 409
        assert _response_error_code(response) == "APPLY_SESSION_NOT_APPLIED"
        assert _verification_rows(fixture) == []


def test_post_apply_verification_api_owner_isolation_and_unauthenticated_access(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        url = _verification_url(str(applied["id"]))
        request = {"expected_journal_digest": applied["journal_digest"]}
        fixture.client.cookies.clear()
        assert fixture.client.get(url).status_code == 401
        assert fixture.client.post(url, json=request).status_code == 401
        init_and_login(fixture.client)

        raw_token = "phase18-3-second-owner-token"
        password_hash, password_salt = hash_password("second-owner-password")
        with fixture.factory() as session:
            second_owner = User(
                username="phase18-3-second-owner",
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
        missing_url = _verification_url("aps_" + "0" * 40)
        wrong_get = fixture.client.get(url, headers=headers)
        wrong_post = fixture.client.post(url, json=request, headers=headers)
        missing_get = fixture.client.get(missing_url, headers=headers)
        missing_post = fixture.client.post(
            missing_url,
            json={"expected_journal_digest": "0" * 64},
            headers=headers,
        )
        assert {
            wrong_get.status_code,
            wrong_post.status_code,
            missing_get.status_code,
            missing_post.status_code,
        } == {404}
        for wrong, absent in (
            (wrong_get, missing_get),
            (wrong_post, missing_post),
        ):
            assert {
                key: value
                for key, value in wrong.json()["error"].items()
                if key != "request_id"
            } == {
                key: value
                for key, value in absent.json()["error"].items()
                if key != "request_id"
            }
        assert _verification_rows(fixture) == []


def test_post_apply_verification_records_are_immutable_in_orm_and_sqlite(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        response = _post_verification(fixture, applied)
        assert response.status_code == 200, response.text
        verification_id = response.json()["verification"]["id"]

        with fixture.factory() as session:
            row = session.scalar(
                select(PostApplyVerification).where(
                    PostApplyVerification.verification_id == verification_id
                )
            )
            assert row is not None
            row.status = "FAILED"
            with pytest.raises(RuntimeError, match="append-only and immutable"):
                session.commit()
            session.rollback()

        with fixture.factory() as session:
            row = session.scalar(
                select(PostApplyVerification).where(
                    PostApplyVerification.verification_id == verification_id
                )
            )
            assert row is not None
            session.delete(row)
            with pytest.raises(RuntimeError, match="append-only and immutable"):
                session.commit()
            session.rollback()

        engine = fixture.client.app.state.engine
        with engine.connect() as connection:
            trigger_names = {
                name
                for name in connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND tbl_name = 'post_apply_verifications'"
                    )
                ).scalars()
            }
            assert {
                "trg_post_apply_verifications_no_update",
                "trg_post_apply_verifications_no_delete",
            } <= trigger_names
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "UPDATE post_apply_verifications SET status = 'FAILED' "
                        "WHERE verification_id = :verification_id"
                    ),
                    {"verification_id": verification_id},
                )
            connection.rollback()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "DELETE FROM post_apply_verifications "
                        "WHERE verification_id = :verification_id"
                    ),
                    {"verification_id": verification_id},
                )
            connection.rollback()

        with fixture.factory() as session:
            persisted = session.scalar(
                select(PostApplyVerification).where(
                    PostApplyVerification.verification_id == verification_id
                )
            )
            assert persisted is not None
            assert persisted.status == "PASSED"


def test_service_owner_boundary_and_forbidden_git_commands(
    tmp_path: Path,
) -> None:
    forbidden = {
        "add",
        "commit",
        "merge",
        "push",
        "rebase",
        "stage",
        "tag",
    }
    assert APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST
    for command in APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST:
        assert forbidden.isdisjoint(command.split())

    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        with fixture.factory() as session:
            apply_session = session.scalar(
                select(ApplySession).where(
                    ApplySession.session_id == applied["id"]
                )
            )
            assert apply_session is not None
            with pytest.raises(ValueError, match="Apply session not found"):
                get_or_create_post_apply_verification(
                    session,
                    owner_id=fixture.owner_id + 100_000,
                    apply_session=apply_session,
                    source_repo=fixture.source_repo,
                    expected_journal_digest=str(applied["journal_digest"]),
                )
            assert session.scalar(
                select(func.count()).select_from(PostApplyVerification)
            ) == 0


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_non_regular_applied_target_is_a_truthful_path_blocker_not_generic_failure(
    tmp_path: Path,
    replacement: str,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        target = fixture.source_repo / "modify.txt"
        target.unlink()
        if replacement == "symlink":
            target.symlink_to("README.md")
        else:
            target.mkdir()
        source_before = _filesystem_boundary(fixture.source_repo)
        git_before = _git_boundary(fixture.source_repo)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        assert review["verification"]["status"] == "BLOCKED"
        assert _blocker_codes(review) == {"APPLIED_PATH_CHANGED"}
        assert any(
            item == {
                "path": "modify.txt",
                "operation": "MODIFY",
                "result": "BLOCKED",
            }
            for item in review["verification"]["changed_files"]
        )
        assert _filesystem_boundary(fixture.source_repo) == source_before
        assert _git_boundary(fixture.source_repo) == git_before


def test_advanced_pairs_expected_and_observed_hashes_and_modes_for_changed_target(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        changed = fixture.source_repo / "modify.txt"
        changed.write_bytes(b"owner changed content after Apply\n")
        changed.chmod(0o600)

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        verification = response.json()["verification"]
        assert verification["status"] == "BLOCKED"
        paired = {
            item["path"]: item
            for item in verification["advanced"]["expected_paths"]
        }["modify.txt"]
        assert SHA256_PATTERN.fullmatch(paired["expected_hash"])
        assert SHA256_PATTERN.fullmatch(paired["observed_hash"])
        assert paired["expected_hash"] != paired["observed_hash"]
        assert paired["expected_mode"] == 0o644
        assert paired["observed_mode"] == 0o600
        assert paired["result"] == "BLOCKED"
        default_file = next(
            item
            for item in verification["changed_files"]
            if item["path"] == "modify.txt"
        )
        assert "hash" not in default_file
        assert "mode" not in default_file


def test_advanced_boundary_diagnostics_persist_only_hashed_git_fingerprints(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        raw_remote = "https://example.invalid/private-owner/private-repository.git"
        run_command(
            fixture.source_repo,
            "git",
            "remote",
            "add",
            "private-fixture-remote",
            raw_remote,
        )

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        verification = response.json()["verification"]
        assert verification["status"] == "BLOCKED"
        boundary = verification["advanced"]["boundary_evidence"]
        fingerprints = boundary["git_fingerprints"]
        assert set(fingerprints) == {"expected", "observed", "staged_path_count"}
        for sample in ("expected", "observed"):
            assert set(fingerprints[sample]) == {
                "index",
                "refs",
                "local_config",
                "remote",
            }
            for name, digest in fingerprints[sample].items():
                assert SHA256_PATTERN.fullmatch(digest), (sample, name)
        assert (
            fingerprints["expected"]["remote"]
            != fingerprints["observed"]["remote"]
        )
        assert (
            fingerprints["expected"]["local_config"]
            != fingerprints["observed"]["local_config"]
        )
        serialized = json.dumps(
            {
                "boundary": boundary,
                "diagnostics": verification["advanced"]["diagnostics"],
            },
            sort_keys=True,
        )
        assert raw_remote not in serialized
        assert "example.invalid" not in serialized
        assert str(fixture.source_repo) not in serialized
        assert "file://" not in serialized


def test_repository_change_between_two_read_only_samples_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        original = post_apply_service._repository_observation
        calls = 0

        def inconsistent_observation(**kwargs):
            nonlocal calls
            calls += 1
            observed = original(**kwargs)
            if calls == 2:
                observed = json.loads(json.dumps(observed))
                observed["global"]["repository_fingerprint"] = "f" * 64
            return observed

        monkeypatch.setattr(
            post_apply_service,
            "_repository_observation",
            inconsistent_observation,
        )

        response = _post_verification(fixture, applied)

        assert response.status_code == 200, response.text
        review = response.json()
        assert calls == 2
        assert review["verification"]["status"] == "BLOCKED"
        assert "REPOSITORY_CHANGED_DURING_VERIFICATION" in _blocker_codes(review)
        stable_check = next(
            item
            for item in review["verification"]["tests"]
            if item["code"] == "STABLE_OBSERVATION"
        )
        assert stable_check["status"] == "BLOCKED"


def test_unreadable_unrelated_directory_cannot_hide_an_unexpected_file(
    tmp_path: Path,
) -> None:
    with phase18b_fixture(tmp_path) as fixture:
        applied, _ = _apply(fixture)
        hidden_directory = fixture.source_repo / "unreadable-owner-output"
        hidden_directory.mkdir()
        (hidden_directory / "unexpected.txt").write_text(
            "unexpected after Apply\n",
            encoding="utf-8",
        )
        hidden_directory.chmod(0)
        try:
            response = _post_verification(fixture, applied)
        finally:
            hidden_directory.chmod(0o700)

        assert response.status_code == 200, response.text
        verification = response.json()["verification"]
        assert verification["status"] == "FAILED"
        assert {
            item["code"] for item in verification["blockers"]
        } == {"VERIFICATION_EVIDENCE_UNAVAILABLE"}
        serialized = json.dumps(verification, sort_keys=True)
        assert str(fixture.source_repo) not in serialized
        assert "unexpected after Apply" not in serialized
