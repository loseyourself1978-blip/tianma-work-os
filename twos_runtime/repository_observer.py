from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping


_INDEX_VOLATILE_KEYS = frozenset(
    {
        "inode",
        "st_ino",
        "device",
        "st_dev",
        "atime",
        "atime_ns",
        "st_atime_ns",
        "mtime",
        "mtime_ns",
        "st_mtime_ns",
        "ctime",
        "ctime_ns",
        "st_ctime_ns",
        "birthtime",
        "birthtime_ns",
        "birth_time",
        "birth_time_ns",
    }
)
_SOURCE_FILE_VOLATILE_KEYS = _INDEX_VOLATILE_KEYS
_GIT_DIRECTORY_VOLATILE_KEYS = _INDEX_VOLATILE_KEYS | {"size", "st_size"}
_TOP_LEVEL_DIAGNOSTIC_KEYS = frozenset(
    {
        "metadata_diagnostics",
        "observation_timing",
    }
)
_INDEX_CONTENT_KEYS = frozenset(
    {
        "fingerprint",
        "content_sha256",
        "sha256",
        "size",
        "mode",
    }
)
_STAGED_SET_KEYS = frozenset(
    {
        "staged_path_count",
        "staged_path_identities",
        "staged_paths",
        "ordered_staged_paths",
    }
)
_STAGED_ENTRY_KEYS = frozenset(
    {
        "staged_entries",
        "staged_entry_identities",
    }
)
_IDENTITY_KEYS = (
    "repository_locator_fingerprint",
    "repository_root_identity",
    "git_common_dir_identity",
    "source_repository_identity",
    "sanitized_repository_identity",
)
_HEAD_KEYS = ("head", "observed_head")
_SOURCE_AGGREGATE_KEYS = (
    "source_digest",
    "current_source_digest",
    "worktree_fingerprint",
)
_GIT_DIRECTORY_PATH_IDENTITY = hashlib.sha256(b".git").hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): copy.deepcopy(item) for key, item in value.items()}


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _without_keys(value: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    excluded = set(keys)
    return {
        str(key): copy.deepcopy(item)
        for key, item in value.items()
        if str(key) not in excluded
    }


def _is_regular_source_row(row: Mapping[str, Any]) -> bool:
    return str(row.get("file_type") or row.get("type") or "") == "regular"


def _is_exact_git_directory_row(row: Mapping[str, Any]) -> bool:
    path = str(row.get("path") or "")
    path_identity = str(row.get("path_identity") or "")
    return bool(
        str(row.get("file_type") or row.get("type") or "") == "directory"
        and str(row.get("reason") or "") == "runtime_or_cache"
        and (
            (path == ".git" and path_identity in {"", _GIT_DIRECTORY_PATH_IDENTITY})
            or (not path and path_identity == _GIT_DIRECTORY_PATH_IDENTITY)
        )
    )


def _semantic_source_row(row: Mapping[str, Any]) -> dict[str, Any]:
    # Only ordinary regular-file stat cache fields are diagnostic. Content,
    # presence, size, mode and file type remain delivery-bearing. Non-regular
    # rows retain every field so a symlink or unsafe file-type transition fails
    # closed.
    if _is_regular_source_row(row):
        return _without_keys(row, _SOURCE_FILE_VOLATILE_KEYS)
    return _mapping(row)


def _semantic_excluded_row(row: Mapping[str, Any]) -> dict[str, Any]:
    # The exact .git directory is the sole excluded entry whose internal size
    # and stat lifecycle are known to be volatile. A lookalike row is not
    # normalized.
    if _is_exact_git_directory_row(row):
        return _without_keys(row, _GIT_DIRECTORY_VOLATILE_KEYS)
    return _mapping(row)


def _sort_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projected = [_mapping(row) for row in rows]
    projected.sort(key=_canonical_json)
    return projected


def _semantic_index(value: object) -> dict[str, Any]:
    return _without_keys(_mapping(value), _INDEX_VOLATILE_KEYS)


def _semantic_direct_filesystem(value: object) -> dict[str, Any]:
    direct = _mapping(value)
    if "entries" in direct:
        entries = _sort_rows(
            _semantic_source_row(row) for row in _rows(direct.get("entries"))
        )
        direct["entries"] = entries
        # The stored aggregate may include timestamps. Recompute it from the
        # normalized rows whenever the detailed evidence required to do so is
        # present. Missing detailed evidence retains the original fingerprint
        # and therefore fails closed.
        direct["state_fingerprint"] = _canonical_sha256(entries)
    if "excluded_entries" in direct:
        excluded = _sort_rows(
            _semantic_excluded_row(row)
            for row in _rows(direct.get("excluded_entries"))
        )
        direct["excluded_entries"] = excluded
        direct["excluded_fingerprint"] = _canonical_sha256(excluded)
    return direct


def semantic_projection(global_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return delivery-relevant repository evidence.

    Known filesystem stat-cache fields are removed only for the Git index,
    ordinary source regular files and the exact excluded .git directory row.
    Unknown fields remain in the projection so incomplete or newly introduced
    evidence cannot silently become non-blocking.
    """

    if not isinstance(global_evidence, Mapping):
        raise TypeError("global_evidence must be a mapping")
    projected = _without_keys(global_evidence, _TOP_LEVEL_DIAGNOSTIC_KEYS)
    if "index" in projected:
        projected["index"] = _semantic_index(projected.get("index"))
    if "direct_filesystem" in projected:
        projected["direct_filesystem"] = _semantic_direct_filesystem(
            projected.get("direct_filesystem")
        )
    return projected


def _diagnostic_fields(
    value: Mapping[str, Any],
    allowed: Iterable[str],
) -> dict[str, Any]:
    keys = set(allowed)
    return {
        str(key): copy.deepcopy(item)
        for key, item in value.items()
        if str(key) in keys
    }


def _safe_path(path: object, identity: object = "") -> str:
    raw = str(path or "")
    try:
        pure = PurePosixPath(raw)
        if (
            raw
            and not pure.is_absolute()
            and raw == pure.as_posix()
            and "\\" not in raw
            and all(part not in {"", ".", ".."} for part in pure.parts)
        ):
            return raw
    except (TypeError, ValueError):
        pass
    digest = str(identity or "")
    if not digest:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    return f"[path withheld:{digest[:12]}]"


def metadata_diagnostics(global_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return safe, non-delivery-bearing stat diagnostics separately."""

    if not isinstance(global_evidence, Mapping):
        raise TypeError("global_evidence must be a mapping")
    index = _mapping(global_evidence.get("index"))
    direct = _mapping(global_evidence.get("direct_filesystem"))
    source_rows: list[dict[str, Any]] = []
    for row in _rows(direct.get("entries")):
        if not _is_regular_source_row(row):
            continue
        diagnostics = _diagnostic_fields(row, _SOURCE_FILE_VOLATILE_KEYS)
        if diagnostics:
            source_rows.append(
                {
                    "path": _safe_path(row.get("path"), row.get("path_identity")),
                    "path_identity": row.get("path_identity"),
                    "metadata": diagnostics,
                }
            )
    source_rows.sort(key=_canonical_json)
    git_rows = [
        _diagnostic_fields(row, _GIT_DIRECTORY_VOLATILE_KEYS)
        for row in _rows(direct.get("excluded_entries"))
        if _is_exact_git_directory_row(row)
    ]
    git_rows.sort(key=_canonical_json)
    return {
        "schema": "twos.repository_metadata_diagnostics.v1",
        "index": _diagnostic_fields(index, _INDEX_VOLATILE_KEYS),
        "git_directory": git_rows[0] if len(git_rows) == 1 else {},
        "source_files": source_rows,
    }


@dataclass(frozen=True)
class PathSemanticChange:
    path: str
    operation: str
    candidate_target: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "candidate_target": self.candidate_target,
        }


@dataclass(frozen=True)
class RepositorySemanticDiff:
    equal: bool
    codes: tuple[str, ...]
    components: tuple[str, ...]
    path_changes: tuple[PathSemanticChange, ...]
    metadata_refresh_categories: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return not self.equal

    def safe_message(self, fallback: str) -> str:
        if not self.codes:
            return fallback
        labels = {
            "CANDIDATE_PATH_CHANGED": "A Candidate path changed.",
            "STAGED_SET_CHANGED": "The staged path set changed.",
            "STAGED_ENTRY_IDENTITY_CHANGED": "A staged entry identity changed.",
            "INDEX_CONTENT_CHANGED": "Git index content changed.",
            "HEAD_CHANGED": "HEAD changed.",
            "BRANCH_CHANGED": "The branch changed.",
            "REFS_CHANGED": "Git refs changed.",
            "CONFIG_CHANGED": "Local Git configuration changed.",
            "REMOTE_CHANGED": "Git remote configuration changed.",
            "REPOSITORY_IDENTITY_CHANGED": "The repository identity changed.",
            "UNRELATED_SOURCE_CHANGED": "An unrelated source path changed.",
            "UNSAFE_OR_EXCLUDED_PATH_CHANGED": "An unsafe or excluded path changed.",
        }
        explanations = [labels[code] for code in self.codes if code in labels]
        if self.path_changes:
            paths = ", ".join(item.path for item in self.path_changes[:3])
            explanations.append(f"Affected path(s): {paths}.")
        return " ".join(explanations) or fallback

    def as_dict(self) -> dict[str, Any]:
        return {
            "equal": self.equal,
            "codes": list(self.codes),
            "components": list(self.components),
            "path_changes": [item.as_dict() for item in self.path_changes],
            "metadata_refresh_categories": list(
                self.metadata_refresh_categories
            ),
        }


def _different_keys(before: Mapping[str, Any], after: Mapping[str, Any]) -> set[str]:
    return {
        key
        for key in set(before) | set(after)
        if before.get(key) != after.get(key)
    }


def _row_identity(row: Mapping[str, Any]) -> str:
    path = str(row.get("path") or "")
    identity = str(row.get("path_identity") or "")
    if path:
        return "path:" + path
    if identity:
        return "identity:" + identity
    return "row:" + _canonical_sha256(row)


def _row_map(value: object) -> dict[str, dict[str, Any]]:
    return {_row_identity(row): row for row in _rows(value)}


def _path_changes(
    before_direct: Mapping[str, Any],
    after_direct: Mapping[str, Any],
    candidate_paths: set[str],
) -> list[PathSemanticChange]:
    before_rows = _row_map(before_direct.get("entries"))
    after_rows = _row_map(after_direct.get("entries"))
    changes: list[PathSemanticChange] = []
    for identity in sorted(set(before_rows) | set(after_rows)):
        before = before_rows.get(identity)
        after = after_rows.get(identity)
        if before == after:
            continue
        observed = after or before or {}
        path = _safe_path(observed.get("path"), observed.get("path_identity"))
        operation = "MODIFY"
        if before is None:
            operation = "CREATE"
        elif after is None:
            operation = "DELETE"
        changes.append(
            PathSemanticChange(
                path=path,
                operation=operation,
                candidate_target=path in candidate_paths,
            )
        )
    return changes


def _metadata_refresh_categories(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[str, ...]:
    before_diagnostics = metadata_diagnostics(before)
    after_diagnostics = metadata_diagnostics(after)
    categories: list[str] = []
    if before_diagnostics["index"] != after_diagnostics["index"]:
        categories.append("index_metadata_refresh")
    if before_diagnostics["git_directory"] != after_diagnostics["git_directory"]:
        categories.append("git_internal_directory_metadata_refresh")
    if before_diagnostics["source_files"] != after_diagnostics["source_files"]:
        categories.append("source_file_metadata_refresh")
    return tuple(categories)


def semantic_diff(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    candidate_paths: Iterable[str] = (),
) -> RepositorySemanticDiff:
    """Return a component-level semantic repository difference.

    The result is blocking whenever the semantic projections differ. Metadata
    refresh categories are reported independently and never make ``equal``
    false on their own.
    """

    first = semantic_projection(before)
    second = semantic_projection(after)
    metadata_categories = _metadata_refresh_categories(before, after)
    if first == second:
        return RepositorySemanticDiff(
            equal=True,
            codes=(),
            components=(),
            path_changes=(),
            metadata_refresh_categories=metadata_categories,
        )

    codes: set[str] = set()
    components: set[str] = set()
    handled: set[str] = set()

    for key in _IDENTITY_KEYS:
        handled.add(key)
        if first.get(key) != second.get(key):
            codes.add("REPOSITORY_IDENTITY_CHANGED")
            components.add(key)
    if first.get("branch") != second.get("branch"):
        codes.add("BRANCH_CHANGED")
        components.add("branch")
    handled.add("branch")
    for key in _HEAD_KEYS:
        handled.add(key)
        if first.get(key) != second.get(key):
            codes.add("HEAD_CHANGED")
            components.add(key)
    for key, code in (
        ("refs_fingerprint", "REFS_CHANGED"),
        ("local_config_fingerprint", "CONFIG_CHANGED"),
        ("remote_fingerprint", "REMOTE_CHANGED"),
    ):
        handled.add(key)
        if first.get(key) != second.get(key):
            codes.add(code)
            components.add(key)

    before_index = _mapping(first.get("index"))
    after_index = _mapping(second.get("index"))
    index_keys = _different_keys(before_index, after_index)
    if index_keys & _INDEX_CONTENT_KEYS:
        codes.add("INDEX_CONTENT_CHANGED")
        components.update("index." + key for key in index_keys & _INDEX_CONTENT_KEYS)
    if index_keys & _STAGED_SET_KEYS:
        codes.add("STAGED_SET_CHANGED")
        components.update("index." + key for key in index_keys & _STAGED_SET_KEYS)
    if index_keys & _STAGED_ENTRY_KEYS:
        codes.add("STAGED_ENTRY_IDENTITY_CHANGED")
        components.update("index." + key for key in index_keys & _STAGED_ENTRY_KEYS)
    remaining_index = index_keys - _INDEX_CONTENT_KEYS - _STAGED_SET_KEYS - _STAGED_ENTRY_KEYS
    if remaining_index:
        codes.add("INDEX_SEMANTICS_CHANGED")
        components.update("index." + key for key in remaining_index)
    handled.add("index")

    before_direct = _mapping(first.get("direct_filesystem"))
    after_direct = _mapping(second.get("direct_filesystem"))
    candidate_set = {str(path) for path in candidate_paths}
    paths = _path_changes(before_direct, after_direct, candidate_set)
    if paths:
        if any(item.candidate_target for item in paths):
            codes.add("CANDIDATE_PATH_CHANGED")
        if any(not item.candidate_target for item in paths):
            codes.add("UNRELATED_SOURCE_CHANGED")
        components.add("direct_filesystem.entries")
    if before_direct.get("excluded_entries") != after_direct.get("excluded_entries"):
        codes.add("UNSAFE_OR_EXCLUDED_PATH_CHANGED")
        components.add("direct_filesystem.excluded_entries")
    if before_direct != after_direct and not paths and (
        before_direct.get("excluded_entries") == after_direct.get("excluded_entries")
    ):
        codes.add("SOURCE_SEMANTICS_CHANGED")
        components.add("direct_filesystem")
    handled.add("direct_filesystem")

    for key in _SOURCE_AGGREGATE_KEYS:
        handled.add(key)
        if first.get(key) != second.get(key):
            codes.add("SOURCE_SEMANTICS_CHANGED")
            components.add(key)
    handled.add("unrelated")
    if first.get("unrelated") != second.get("unrelated"):
        codes.add("UNRELATED_SOURCE_CHANGED")
        components.add("unrelated")
    handled.add("repository_fingerprint")
    if first.get("repository_fingerprint") != second.get("repository_fingerprint"):
        codes.add("REPOSITORY_STATE_CHANGED")
        components.add("repository_fingerprint")

    remaining_first = {key: value for key, value in first.items() if key not in handled}
    remaining_second = {key: value for key, value in second.items() if key not in handled}
    remaining_keys = _different_keys(remaining_first, remaining_second)
    if remaining_keys:
        codes.add("DELIVERY_BOUNDARY_CHANGED")
        components.update(remaining_keys)

    # Projection inequality must never accidentally yield a non-blocking
    # result merely because a future field is outside the current taxonomy.
    if not codes:
        codes.add("DELIVERY_BOUNDARY_CHANGED")
        components.add("unclassified_semantic_evidence")
    return RepositorySemanticDiff(
        equal=False,
        codes=tuple(sorted(codes)),
        components=tuple(sorted(components)),
        path_changes=tuple(paths),
        metadata_refresh_categories=metadata_categories,
    )
