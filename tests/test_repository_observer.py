from __future__ import annotations

import copy
import hashlib

import pytest

from twos_runtime.repository_observer import (
    metadata_diagnostics,
    semantic_diff,
    semantic_projection,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _evidence() -> dict:
    git_identity = _sha(".git")
    source_entries = [
        {
            "path": "README.md",
            "path_identity": _sha("README.md"),
            "present": True,
            "sha256": _sha("readme bytes"),
            "size": 12,
            "mode": 0o644,
            "file_type": "regular",
            "inode": 101,
            "atime_ns": 10,
            "mtime_ns": 20,
            "ctime_ns": 30,
            "birthtime_ns": 5,
        }
    ]
    excluded = [
        {
            "path": ".git",
            "path_identity": git_identity,
            "reason": "runtime_or_cache",
            "file_type": "directory",
            "mode": 0o755,
            "inode": 201,
            "size": 512,
            "mtime_ns": 40,
            "birthtime_ns": 4,
        }
    ]
    return {
        "schema": "twos.apply_global_evidence.v1",
        "repository_locator_fingerprint": _sha("root"),
        "git_common_dir_identity": _sha("common"),
        "repository_fingerprint": _sha("repository"),
        "sanitized_repository_identity": "fixture-repo",
        "branch": "main",
        "head": "a" * 40,
        "source_digest": _sha("source"),
        "worktree_fingerprint": _sha("worktree"),
        "index": {
            "fingerprint": _sha("index bytes"),
            "size": 256,
            "mode": 0o644,
            "staged_path_count": 0,
            "staged_path_identities": [],
            "staged_entries": [],
            "inode": 301,
            "mtime_ns": 50,
            "ctime_ns": 51,
            "birthtime_ns": 3,
        },
        "direct_filesystem": {
            "state_fingerprint": _sha("raw state including metadata"),
            "entries": source_entries,
            "excluded_fingerprint": _sha("raw excluded including metadata"),
            "excluded_entries": excluded,
        },
        "unrelated": {
            "state_fingerprint": _sha("unrelated"),
            "entries": [],
        },
        "refs_fingerprint": _sha("refs"),
        "local_config_fingerprint": _sha("config"),
        "remote_fingerprint": _sha("remote"),
    }


def test_metadata_only_refresh_is_semantically_equal_and_diagnosed() -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    after["index"].update(
        inode=999,
        mtime_ns=999,
        ctime_ns=999,
        birthtime_ns=999,
    )
    source = after["direct_filesystem"]["entries"][0]
    source.update(inode=998, atime_ns=998, mtime_ns=998, birthtime_ns=998)
    git_dir = after["direct_filesystem"]["excluded_entries"][0]
    git_dir.update(inode=997, size=4096, mtime_ns=997, birthtime_ns=997)
    after["direct_filesystem"]["state_fingerprint"] = _sha("new raw state")
    after["direct_filesystem"]["excluded_fingerprint"] = _sha("new raw excluded")

    result = semantic_diff(before, after)

    assert result.equal is True
    assert result.codes == ()
    assert result.metadata_refresh_categories == (
        "index_metadata_refresh",
        "git_internal_directory_metadata_refresh",
        "source_file_metadata_refresh",
    )
    assert semantic_projection(before) == semantic_projection(after)
    diagnostics = metadata_diagnostics(after)
    assert diagnostics["index"]["inode"] == 999
    assert diagnostics["source_files"][0]["path"] == "README.md"
    assert diagnostics["git_directory"]["size"] == 4096


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda row: row["index"].update(fingerprint=_sha("changed index")), "INDEX_CONTENT_CHANGED"),
        (
            lambda row: row["index"].update(
                staged_path_count=1,
                staged_path_identities=[_sha("README.md")],
            ),
            "STAGED_SET_CHANGED",
        ),
        (
            lambda row: row["index"].update(
                staged_entries=[{"path_identity": _sha("README.md"), "oid": "b" * 40}]
            ),
            "STAGED_ENTRY_IDENTITY_CHANGED",
        ),
        (lambda row: row.update(head="b" * 40), "HEAD_CHANGED"),
        (lambda row: row.update(branch="other"), "BRANCH_CHANGED"),
        (lambda row: row.update(refs_fingerprint=_sha("other refs")), "REFS_CHANGED"),
        (
            lambda row: row.update(local_config_fingerprint=_sha("other config")),
            "CONFIG_CHANGED",
        ),
        (lambda row: row.update(remote_fingerprint=_sha("other remote")), "REMOTE_CHANGED"),
        (
            lambda row: row.update(repository_locator_fingerprint=_sha("other root")),
            "REPOSITORY_IDENTITY_CHANGED",
        ),
        (
            lambda row: row.update(git_common_dir_identity=_sha("other common")),
            "REPOSITORY_IDENTITY_CHANGED",
        ),
    ],
)
def test_delivery_boundary_changes_block_with_component_code(
    mutation,
    expected_code: str,
) -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    mutation(after)

    result = semantic_diff(before, after)

    assert result.equal is False
    assert expected_code in result.codes


def test_source_content_mode_type_presence_and_size_remain_semantic() -> None:
    for field, value in (
        ("sha256", _sha("changed bytes")),
        ("size", 99),
        ("mode", 0o755),
        ("file_type", "symlink"),
        ("present", False),
    ):
        before = _evidence()
        after = copy.deepcopy(before)
        after["direct_filesystem"]["entries"][0][field] = value

        result = semantic_diff(before, after)

        assert result.equal is False, field
        assert "UNRELATED_SOURCE_CHANGED" in result.codes, field
        assert result.path_changes[0].path == "README.md"
        assert result.path_changes[0].operation == "MODIFY"


def test_source_create_delete_and_candidate_attribution_are_component_level() -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    after["direct_filesystem"]["entries"] = [
        {
            "path": "created.txt",
            "path_identity": _sha("created.txt"),
            "present": True,
            "sha256": _sha("created"),
            "size": 7,
            "mode": 0o644,
            "file_type": "regular",
        }
    ]

    result = semantic_diff(before, after, candidate_paths={"created.txt"})

    assert result.equal is False
    assert "CANDIDATE_PATH_CHANGED" in result.codes
    assert "UNRELATED_SOURCE_CHANGED" in result.codes
    assert [item.as_dict() for item in result.path_changes] == [
        {
            "path": "README.md",
            "operation": "DELETE",
            "candidate_target": False,
        },
        {
            "path": "created.txt",
            "operation": "CREATE",
            "candidate_target": True,
        },
    ]


def test_symlink_and_non_git_excluded_metadata_are_not_normalized() -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    after["direct_filesystem"]["excluded_entries"].append(
        {
            "path": "unsafe-link",
            "path_identity": _sha("unsafe-link"),
            "reason": "symlink",
            "file_type": "symlink",
            "mode": 0o777,
            "mtime_ns": 1,
        }
    )

    result = semantic_diff(before, after)

    assert result.equal is False
    assert "UNSAFE_OR_EXCLUDED_PATH_CHANGED" in result.codes


def test_git_directory_lookalike_fails_closed() -> None:
    before = _evidence()
    before["direct_filesystem"]["excluded_entries"][0]["path_identity"] = _sha(
        "not .git"
    )
    after = copy.deepcopy(before)
    after["direct_filesystem"]["excluded_entries"][0]["mtime_ns"] = 999

    result = semantic_diff(before, after)

    assert result.equal is False
    assert "UNSAFE_OR_EXCLUDED_PATH_CHANGED" in result.codes


def test_unknown_semantic_field_fails_closed() -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    after["future_delivery_boundary"] = "changed"

    result = semantic_diff(before, after)

    assert result.equal is False
    assert "DELIVERY_BOUNDARY_CHANGED" in result.codes
    assert "future_delivery_boundary" in result.components


def test_missing_detailed_rows_keeps_aggregate_fingerprint_blocking() -> None:
    before = _evidence()
    before["direct_filesystem"].pop("entries")
    after = copy.deepcopy(before)
    after["direct_filesystem"]["state_fingerprint"] = _sha("changed aggregate")

    result = semantic_diff(before, after)

    assert result.equal is False
    assert "SOURCE_SEMANTICS_CHANGED" in result.codes


def test_absolute_source_path_is_never_returned_in_component_details() -> None:
    before = _evidence()
    after = copy.deepcopy(before)
    after["direct_filesystem"]["entries"][0]["path"] = "/private/secret.txt"

    result = semantic_diff(before, after)

    assert result.equal is False
    assert all(not item.path.startswith("/") for item in result.path_changes)
    assert any(item.path.startswith("[path withheld:") for item in result.path_changes)
