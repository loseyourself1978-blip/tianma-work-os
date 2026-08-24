from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from contextlib import contextmanager
import fcntl
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .apply_plans import (
    APPLY_PLAN_POLICY_VERSION,
    _plan_has_result_lineage,
    _stored_entries,
    effective_apply_plan_state,
    get_apply_plan_approval,
    observe_repository,
    validate_apply_plan_approval,
    validate_apply_plan_integrity,
)
from .delivery_candidates import (
    SHA256_PATTERN,
    canonical_json,
    canonical_sha256,
    evaluate_source_drift,
    normalize_repository_path,
    validate_delivery_candidate,
)
from .models import (
    ApplyPlan,
    ApplyPlanApproval,
    ApplyPlanEntry,
    ApplySession,
    ApplySessionAudit,
    ApplySessionEntry,
    CodexRun,
    DeliveryCandidate,
    SourceDriftEvaluation,
    utc_now,
)
from .repository_observer import (
    metadata_diagnostics,
    semantic_diff,
    semantic_projection,
)
from .self_hosting import (
    SOURCE_REPOSITORY_IDENTITY_METHOD,
    SOURCE_REPOSITORY_IDENTITY_METHODS,
    _snapshot_exclusion_reason,
    _source_repository_identity,
    _source_snapshot_digest,
    capture_source_snapshot,
    run_git,
    source_snapshot_has_strong_repository_identity,
)


APPLY_SESSION_SCHEMA = "twos.apply_session.v1"
APPLY_SESSION_POLICY_VERSION = "twos.apply_revert.v1"
APPLY_ELIGIBLE_PLAN_STATES = frozenset(
    {"ready_for_owner_review", "review_with_source_changes"}
)
APPLY_SESSION_TERMINAL_STATES = frozenset(
    {
        "PREFLIGHT_BLOCKED",
        "APPLIED",
        "APPLY_FAILED_RECOVERED",
        "APPLY_FAILED_PARTIAL",
        "REVERTED",
        "REVERT_BLOCKED",
        "REVERT_FAILED_PARTIAL",
    }
)
APPLY_SESSION_STATE_LABELS = {
    "PREFLIGHT_BLOCKED": "Apply blocked by preflight",
    "APPLYING": "Applying accepted changes",
    "APPLIED": "Applied",
    "APPLY_FAILED_RECOVERED": "Apply failed; source restored",
    "APPLY_FAILED_PARTIAL": "Apply failed; partial source change remains",
    "REVERTING": "Reverting applied changes",
    "REVERTED": "Reverted",
    "REVERT_BLOCKED": "Revert blocked",
    "REVERT_FAILED_PARTIAL": "Revert failed; partial reverse change remains",
}
APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST = (
    "rev-parse --show-toplevel",
    "rev-parse --absolute-git-dir",
    "rev-parse --git-common-dir",
    "rev-parse --git-path index",
    "branch --show-current",
    "rev-parse HEAD",
    "status --porcelain --untracked-files=all",
    "ls-files -z",
    "ls-files --others --exclude-standard -z",
    "diff --name-status",
    "diff --name-only",
    "diff --cached --name-only -z",
    "diff --binary",
    "diff --cached --binary",
    "for-each-ref --format=<fixed ref/object format>",
    "config --local --null --list (fingerprint only)",
    "remote -v (fingerprint only)",
)
MAX_APPLY_FILE_BYTES = 24_000_000
_SECRET_MATERIAL_PATTERNS = (
    re.compile(
        rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        re.IGNORECASE,
    ),
    re.compile(rb"[a-z][a-z0-9+.-]*://[^/\s:@]{1,128}:[^/\s@]{1,256}@", re.I),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)"
        rb"\s*[:=]\s*[\"']?[A-Za-z0-9+/=_-]{16,}",
        re.IGNORECASE,
    ),
)

FaultInjector = Callable[[str, ApplySessionEntry], None]


class ApplySessionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@contextmanager
def _repository_mutation_lock(
    repository_locator_fingerprint: str,
) -> Iterator[None]:
    """Serialize source mutation across workers without touching the repository."""
    if not SHA256_PATTERN.fullmatch(repository_locator_fingerprint or ""):
        raise ApplySessionError(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The repository identity is unavailable.",
        )
    lock_directory = Path(tempfile.gettempdir()) / (
        f"twos-apply-locks-{os.getuid()}"
    )
    try:
        lock_directory.mkdir(mode=0o700, exist_ok=True)
        directory_stat = lock_directory.lstat()
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or stat.S_ISLNK(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
        ):
            raise OSError("unsafe lock directory")
        directory_fd = os.open(
            lock_directory,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        lock_fd = os.open(
            f"{repository_locator_fingerprint}.lock",
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        if "directory_fd" in locals():
            os.close(directory_fd)
        raise ApplySessionError(
            "REPOSITORY_LOCK_UNAVAILABLE",
            "The repository mutation lock is unavailable.",
        ) from exc
    os.close(directory_fd)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ApplySessionError(
                "CONCURRENT_APPLY",
                "Another Apply or Revert session is active for this repository.",
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _decoded_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _decoded_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _path_identity(path: str) -> str:
    return _sha256_bytes(path.encode("utf-8"))


def _assert_material_safe(payload: bytes) -> None:
    if any(pattern.search(payload) for pattern in _SECRET_MATERIAL_PATTERNS):
        raise ApplySessionError(
            "SECRET_MATERIAL_BLOCKED",
            "A Candidate file contains credential-shaped material that cannot be journaled.",
        )


def _safe_failure(
    code: str,
    *,
    phase: str,
    entry: ApplySessionEntry | None = None,
    exception: BaseException | None = None,
    details: dict[str, Any] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "code": code,
        "phase": phase,
    }
    if entry is not None:
        evidence["path_identity"] = entry.path_identity
        evidence["operation"] = entry.operation
    if exception is not None:
        evidence["exception_type"] = type(exception).__name__
    if details:
        evidence["details"] = details
    if message:
        evidence["message"] = message
    return evidence


def _append_audit(
    session: Session,
    apply_session: ApplySession,
    *,
    phase: str,
    event_type: str,
    entry: ApplySessionEntry | None = None,
    evidence: dict[str, Any] | None = None,
) -> ApplySessionAudit:
    audit = ApplySessionAudit(
        apply_session_id=apply_session.id,
        owner_id=apply_session.owner_id,
        phase=phase,
        event_type=event_type,
        state=apply_session.state,
        entry_id=entry.id if entry is not None else None,
        path_identity=entry.path_identity if entry is not None else "",
        evidence_json=canonical_json(evidence or {}),
    )
    session.add(audit)
    return audit


def _verified_repository_root(
    run: CodexRun,
    source_repo: Path,
    *,
    expected_source_workspace_identity: str = "",
    expected_source_snapshot_identity: str = "",
    require_strong_source_identity: bool = False,
) -> Path:
    try:
        configured_root = source_repo.resolve(strict=True)
        verified_root = Path(
            run_git(
                configured_root,
                "rev-parse",
                "--show-toplevel",
                hardened_read_only=True,
            ).stdout.strip()
        ).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ApplySessionError(
            "REPOSITORY_UNAVAILABLE",
            "The source repository cannot be verified safely.",
        ) from exc
    if verified_root != configured_root:
        raise ApplySessionError(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The configured source path is not the exact repository root.",
        )
    try:
        stored_root = Path(run.source_repo).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ApplySessionError(
            "REPOSITORY_UNAVAILABLE",
            "The Run-bound repository identity is unavailable.",
        ) from exc
    if stored_root != configured_root:
        raise ApplySessionError(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The Run no longer binds the configured repository.",
        )
    if (
        expected_source_workspace_identity
        or expected_source_snapshot_identity
        or require_strong_source_identity
    ):
        approved_snapshot = (
            _decoded_object(run.pack.source_snapshot_json)
            if run.pack is not None
            else {}
        )
        identity_method = str(
            approved_snapshot.get("source_repository_identity_method") or ""
        )
        try:
            calculated_snapshot_digest = _source_snapshot_digest(approved_snapshot)
            observed_repository_identity = _source_repository_identity(
                configured_root,
                hardened_read_only=True,
                method=identity_method,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ApplySessionError(
                "SOURCE_WORKSPACE_IDENTITY_MISMATCH",
                "The exact approved source repository identity cannot be verified.",
            ) from exc
        if require_strong_source_identity and not (
            identity_method == SOURCE_REPOSITORY_IDENTITY_METHOD
            and source_snapshot_has_strong_repository_identity(approved_snapshot)
        ):
            raise ApplySessionError(
                "SOURCE_WORKSPACE_IDENTITY_MISMATCH",
                "The Result-derived Plan lacks a strong source repository identity.",
            )
        approved_snapshot_digest = str(approved_snapshot.get("digest") or "")
        approved_repository_identity = str(
            approved_snapshot.get("source_repository_identity") or ""
        )
        if not (
            SHA256_PATTERN.fullmatch(approved_snapshot_digest)
            and calculated_snapshot_digest == approved_snapshot_digest
            and approved_snapshot_digest == run.source_snapshot_digest
            and (
                not expected_source_snapshot_identity
                or approved_snapshot_digest == expected_source_snapshot_identity
            )
            and SHA256_PATTERN.fullmatch(approved_repository_identity)
            and approved_repository_identity == observed_repository_identity
            and (
                not expected_source_workspace_identity
                or approved_repository_identity
                == expected_source_workspace_identity
            )
        ):
            raise ApplySessionError(
                "SOURCE_WORKSPACE_IDENTITY_MISMATCH",
                "The configured repository is not the exact source repository approved for this delivery.",
            )
    return configured_root


def _safe_target(root: Path, repository_path: str) -> tuple[Path, list[dict[str, Any]]]:
    normalized = normalize_repository_path(repository_path)
    root = root.resolve(strict=True)
    cursor = root
    parent_chain: list[dict[str, Any]] = []
    parts = PurePosixPath(normalized).parts
    for part in parts[:-1]:
        cursor = cursor / part
        relative = cursor.relative_to(root).as_posix()
        try:
            item_stat = cursor.lstat()
        except FileNotFoundError:
            parent_chain.append(
                {
                    "path": relative,
                    "path_identity": _path_identity(relative),
                    "present": False,
                    "mode": None,
                }
            )
            continue
        except OSError as exc:
            raise ApplySessionError(
                "PARENT_CHAIN_UNSAFE",
                "A target parent cannot be inspected safely.",
            ) from exc
        if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISDIR(item_stat.st_mode):
            raise ApplySessionError(
                "PARENT_CHAIN_UNSAFE",
                "A target parent is a symlink or unsupported file type.",
            )
        parent_chain.append(
            {
                "path": relative,
                "path_identity": _path_identity(relative),
                "present": True,
                "mode": item_stat.st_mode & 0o777,
            }
        )
    target = root.joinpath(*parts)
    if not target.parent.resolve(strict=False).is_relative_to(root):
        raise ApplySessionError(
            "UNSAFE_PATH",
            "The target path escapes the repository.",
        )
    return target, parent_chain


def _read_regular_file(path: Path) -> dict[str, Any]:
    try:
        before_stat = path.lstat()
    except FileNotFoundError:
        return {
            "present": False,
            "hash": None,
            "size": None,
            "mode": None,
            "file_type": "absent",
            "atime_ns": None,
            "mtime_ns": None,
            "material": None,
        }
    except OSError as exc:
        raise ApplySessionError(
            "PATH_UNAVAILABLE",
            "A target path cannot be inspected safely.",
        ) from exc
    if stat.S_ISLNK(before_stat.st_mode):
        raise ApplySessionError(
            "SYMLINK_UNSUPPORTED",
            "A target path is a symlink.",
        )
    if not stat.S_ISREG(before_stat.st_mode):
        raise ApplySessionError(
            "FILE_TYPE_UNSUPPORTED",
            "A target path is not a regular file.",
        )
    if before_stat.st_size > MAX_APPLY_FILE_BYTES:
        raise ApplySessionError(
            "FILE_TOO_LARGE",
            "A target file exceeds the bounded Apply evidence limit.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ApplySessionError(
            "PATH_UNAVAILABLE",
            "A target path cannot be opened safely.",
        ) from exc
    payload = bytearray()
    digest = hashlib.sha256()
    try:
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (before_stat.st_dev, before_stat.st_ino)
        ):
            raise ApplySessionError(
                "PATH_CHANGED_DURING_READ",
                "A target path changed during inspection.",
            )
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            digest.update(chunk)
            if len(payload) > MAX_APPLY_FILE_BYTES:
                raise ApplySessionError(
                    "FILE_TOO_LARGE",
                    "A target file exceeds the bounded Apply evidence limit.",
                )
        final_stat = os.fstat(fd)
    finally:
        os.close(fd)
    if (
        (final_stat.st_dev, final_stat.st_ino)
        != (opened_stat.st_dev, opened_stat.st_ino)
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
        or final_stat.st_ctime_ns != opened_stat.st_ctime_ns
        or len(payload) != opened_stat.st_size
    ):
        raise ApplySessionError(
            "PATH_CHANGED_DURING_READ",
            "A target path changed during inspection.",
        )
    material = bytes(payload)
    _assert_material_safe(material)
    return {
        "present": True,
        "hash": digest.hexdigest(),
        "size": len(payload),
        "mode": opened_stat.st_mode & 0o777,
        "file_type": "regular",
        "atime_ns": opened_stat.st_atime_ns,
        "mtime_ns": opened_stat.st_mtime_ns,
        "material": material,
    }


def _target_state(root: Path, repository_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target, parent_chain = _safe_target(root, repository_path)
    return _read_regular_file(target), parent_chain


def _state_matches(
    actual: dict[str, Any],
    *,
    present: bool,
    expected_hash: str | None,
    expected_size: int | None,
    expected_mode: int | None,
    expected_file_type: str,
) -> bool:
    if actual.get("present") is not present:
        return False
    if not present:
        return actual.get("file_type") == "absent"
    return (
        actual.get("hash") == expected_hash
        and actual.get("size") == expected_size
        and actual.get("mode") == expected_mode
        and actual.get("file_type") == expected_file_type == "regular"
    )


def _entry_matches_before(root: Path, entry: ApplySessionEntry) -> bool:
    actual, _ = _target_state(root, entry.repository_path)
    return _state_matches(
        actual,
        present=entry.before_present,
        expected_hash=entry.before_hash,
        expected_size=entry.before_size,
        expected_mode=entry.before_mode,
        expected_file_type=entry.before_file_type,
    )


def _entry_matches_after(root: Path, entry: ApplySessionEntry) -> bool:
    actual, _ = _target_state(root, entry.repository_path)
    return _state_matches(
        actual,
        present=entry.after_present,
        expected_hash=entry.after_hash,
        expected_size=entry.after_size,
        expected_mode=entry.after_mode,
        expected_file_type=entry.after_file_type,
    )


def _index_evidence(root: Path) -> dict[str, Any]:
    git_dir = Path(
        run_git(
            root,
            "rev-parse",
            "--absolute-git-dir",
            hardened_read_only=True,
        ).stdout.strip()
    ).resolve(strict=True)
    index_output = run_git(
        root,
        "rev-parse",
        "--git-path",
        "index",
        hardened_read_only=True,
    ).stdout.strip()
    candidate = Path(index_output)
    if not candidate.is_absolute():
        candidate = root / candidate
    unresolved_stat = candidate.lstat()
    if stat.S_ISLNK(unresolved_stat.st_mode):
        raise ApplySessionError(
            "INDEX_UNAVAILABLE",
            "The Git index identity is unsafe.",
        )
    index_path = candidate.resolve(strict=True)
    index_stat = index_path.lstat()
    if (
        not stat.S_ISREG(index_stat.st_mode)
        or stat.S_ISLNK(index_stat.st_mode)
        or not index_path.is_relative_to(git_dir)
    ):
        raise ApplySessionError(
            "INDEX_UNAVAILABLE",
            "The Git index identity is unavailable.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(index_path, flags)
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(fd)
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        final = os.fstat(fd)
    finally:
        os.close(fd)
    if (
        size != opened.st_size
        or final.st_size != opened.st_size
        or final.st_mtime_ns != opened.st_mtime_ns
        or (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise ApplySessionError(
            "INDEX_CHANGED_DURING_READ",
            "The Git index changed during inspection.",
        )
    staged = run_git(
        root,
        "diff",
        "--cached",
        "--name-only",
        "-z",
        hardened_read_only=True,
    ).stdout
    staged_paths = [item for item in staged.split("\0") if item]
    return {
        "fingerprint": digest.hexdigest(),
        "size": size,
        "mode": opened.st_mode & 0o777,
        "mtime_ns": opened.st_mtime_ns,
        "staged_path_count": len(staged_paths),
        "staged_path_identities": sorted(
            _sha256_bytes(item.encode("utf-8", errors="replace"))
            for item in staged_paths
        ),
    }


def _snapshot_unrelated_evidence(
    snapshot: dict[str, Any],
    target_paths: set[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    changed_paths: list[dict[str, Any]] = []
    for raw in snapshot.get("included_manifest", []):
        if not isinstance(raw, dict):
            raise ApplySessionError(
                "SOURCE_EVIDENCE_INVALID",
                "Repository source evidence is malformed.",
            )
        path = normalize_repository_path(raw.get("path"))
        if path in target_paths:
            continue
        row = {
            "path": path,
            "path_identity": _path_identity(path),
            "kind": str(raw.get("kind") or "unknown"),
            "staged": raw.get("staged") is True,
            "unstaged": raw.get("unstaged") is True,
            "deleted": raw.get("deleted") is True,
            "sha256": raw.get("sha256"),
            "size": raw.get("size"),
            "mode": raw.get("mode"),
        }
        rows.append(row)
        if row["kind"] != "tracked" or row["staged"] or row["unstaged"]:
            changed_paths.append(
                {
                    "path": path,
                    "path_identity": row["path_identity"],
                    "kind": row["kind"],
                }
            )
    excluded_identities = sorted(
        {
            canonical_sha256(
                {
                    "path": str(raw.get("path") or ""),
                    "reason": str(raw.get("reason") or "excluded"),
                }
            )
            for raw in snapshot.get("excluded_manifest", [])
            if isinstance(raw, dict)
        }
    )
    rows.sort(key=lambda item: item["path"].encode("utf-8"))
    changed_paths.sort(key=lambda item: item["path"].encode("utf-8"))
    return {
        "state_fingerprint": canonical_sha256(rows),
        "entries": rows,
        "changed_paths": changed_paths,
        "excluded_path_identities": excluded_identities,
        "excluded_fingerprint": canonical_sha256(excluded_identities),
    }


def _hash_regular_without_material(path: Path) -> tuple[str, int, int, int]:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ApplySessionError(
            "FILE_TYPE_UNSUPPORTED",
            "A direct filesystem evidence path is not a regular file.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(fd)
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        final = os.fstat(fd)
    finally:
        os.close(fd)
    if (
        (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        or (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino)
        or final.st_mtime_ns != opened.st_mtime_ns
        or size != opened.st_size
    ):
        raise ApplySessionError(
            "PATH_CHANGED_DURING_READ",
            "A filesystem evidence path changed during inspection.",
        )
    return digest.hexdigest(), size, opened.st_mode & 0o777, opened.st_mtime_ns


def _direct_filesystem_evidence(
    root: Path,
    target_paths: set[str],
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            child = directory_path / name
            relative = child.relative_to(root).as_posix()
            reason = _snapshot_exclusion_reason(relative)
            try:
                child_stat = child.lstat()
            except OSError as exc:
                raise ApplySessionError(
                    "SOURCE_EVIDENCE_UNAVAILABLE",
                    "A repository path cannot be inspected safely.",
                ) from exc
            if reason is not None or stat.S_ISLNK(child_stat.st_mode):
                excluded.append(
                    {
                        "path_identity": _path_identity(relative),
                        "reason": reason or "symlink",
                        "file_type": (
                            "symlink"
                            if stat.S_ISLNK(child_stat.st_mode)
                            else "directory"
                        ),
                        "mode": child_stat.st_mode & 0o777,
                        "size": child_stat.st_size,
                        "mtime_ns": child_stat.st_mtime_ns,
                    }
                )
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in sorted(file_names):
            child = directory_path / name
            relative = child.relative_to(root).as_posix()
            if relative in target_paths:
                continue
            reason = _snapshot_exclusion_reason(relative)
            try:
                child_stat = child.lstat()
            except OSError as exc:
                raise ApplySessionError(
                    "SOURCE_EVIDENCE_UNAVAILABLE",
                    "A repository file cannot be inspected safely.",
                ) from exc
            if reason is not None or not stat.S_ISREG(child_stat.st_mode):
                excluded.append(
                    {
                        "path_identity": _path_identity(relative),
                        "reason": reason or "unsupported_file_type",
                        "file_type": (
                            "symlink"
                            if stat.S_ISLNK(child_stat.st_mode)
                            else "unsupported"
                        ),
                        "mode": child_stat.st_mode & 0o777,
                        "size": child_stat.st_size,
                        "mtime_ns": child_stat.st_mtime_ns,
                    }
                )
                continue
            normalized = normalize_repository_path(relative)
            digest, size, mode, mtime_ns = _hash_regular_without_material(child)
            rows.append(
                {
                    "path": normalized,
                    "path_identity": _path_identity(normalized),
                    "sha256": digest,
                    "size": size,
                    "mode": mode,
                    "mtime_ns": mtime_ns,
                    "file_type": "regular",
                }
            )
    rows.sort(key=lambda item: item["path"].encode("utf-8"))
    excluded.sort(
        key=lambda item: (
            item["path_identity"],
            str(item["reason"]),
        )
    )
    return {
        "state_fingerprint": canonical_sha256(rows),
        "excluded_fingerprint": canonical_sha256(excluded),
        "entries": rows,
        "excluded_entries": excluded,
    }


def _global_evidence(
    run: CodexRun,
    root: Path,
    *,
    target_paths: Iterable[str],
) -> dict[str, Any]:
    observation = observe_repository(run, root)
    snapshot = observation["snapshot"]
    targets = {normalize_repository_path(path) for path in target_paths}
    index = _index_evidence(root)
    refs_output = run_git(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    config_output = run_git(
        root,
        "config",
        "--local",
        "--null",
        "--list",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    remote_output = run_git(
        root,
        "remote",
        "-v",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    unrelated = _snapshot_unrelated_evidence(snapshot, targets)
    direct_filesystem = _direct_filesystem_evidence(root, targets)
    return {
        "schema": "twos.apply_global_evidence.v1",
        "repository_locator_fingerprint": observation[
            "repository_locator_fingerprint"
        ],
        "repository_fingerprint": observation["repository_fingerprint"],
        "sanitized_repository_identity": observation[
            "sanitized_repository_identity"
        ],
        "branch": observation["branch"],
        "head": observation["observed_head"],
        "source_digest": observation["current_source_digest"],
        "worktree_fingerprint": observation["worktree_fingerprint"],
        "index": index,
        "unrelated": unrelated,
        "direct_filesystem": direct_filesystem,
        "refs_fingerprint": _sha256_bytes(refs_output),
        "local_config_fingerprint": _sha256_bytes(config_output),
        "remote_fingerprint": _sha256_bytes(remote_output),
        "git_command_policy": "explicit_read_only_allowlist",
        "git_commands": list(APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST),
    }


def _global_evidence_after_mutation(
    run: CodexRun,
    root: Path,
    *,
    target_paths: Iterable[str],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    root = _verified_repository_root(run, root)
    targets = {normalize_repository_path(path) for path in target_paths}
    index = _index_evidence(root)
    branch = run_git(
        root,
        "branch",
        "--show-current",
        hardened_read_only=True,
    ).stdout.strip()
    head = run_git(
        root,
        "rev-parse",
        "HEAD",
        hardened_read_only=True,
    ).stdout.strip()
    refs_output = run_git(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    config_output = run_git(
        root,
        "config",
        "--local",
        "--null",
        "--list",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    remote_output = run_git(
        root,
        "remote",
        "-v",
        hardened_read_only=True,
    ).stdout.encode("utf-8", errors="surrogateescape")
    direct_filesystem = _direct_filesystem_evidence(root, targets)
    direct_fingerprint = str(direct_filesystem["state_fingerprint"])
    return {
        "schema": "twos.apply_global_evidence.v1",
        "repository_locator_fingerprint": baseline.get(
            "repository_locator_fingerprint", ""
        ),
        "repository_fingerprint": canonical_sha256(
            {
                "schema": "twos.apply_repository_direct.v1",
                "locator": baseline.get("repository_locator_fingerprint", ""),
                "branch": branch,
                "head": head,
                "index": index["fingerprint"],
                "direct_filesystem": direct_fingerprint,
            }
        ),
        "sanitized_repository_identity": baseline.get(
            "sanitized_repository_identity", ""
        ),
        "branch": branch,
        "head": head,
        "source_digest": direct_fingerprint,
        "worktree_fingerprint": direct_fingerprint,
        "index": index,
        "unrelated": baseline.get("unrelated", {}),
        "direct_filesystem": direct_filesystem,
        "refs_fingerprint": _sha256_bytes(refs_output),
        "local_config_fingerprint": _sha256_bytes(config_output),
        "remote_fingerprint": _sha256_bytes(remote_output),
        "git_command_policy": "post_mutation_non_worktree_git_allowlist",
        "git_commands": [
            "rev-parse --show-toplevel",
            "rev-parse --absolute-git-dir",
            "rev-parse --git-path index",
            "branch --show-current",
            "rev-parse HEAD",
            "diff --cached --name-only -z",
            "for-each-ref --format=<fixed ref/object format>",
            "config --local --null --list (fingerprint only)",
            "remote -v (fingerprint only)",
        ],
    }


def _global_static_mismatches(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    preserve_unrelated: bool = True,
    metadata_is_semantic: bool = False,
) -> list[str]:
    first = before if metadata_is_semantic else semantic_projection(before)
    second = after if metadata_is_semantic else semantic_projection(after)
    mismatches: list[str] = []
    for key, code in (
        ("repository_locator_fingerprint", "REPOSITORY_IDENTITY_CHANGED"),
        ("sanitized_repository_identity", "REPOSITORY_IDENTITY_CHANGED"),
        ("branch", "BRANCH_CHANGED"),
        ("head", "HEAD_CHANGED"),
        ("refs_fingerprint", "REFS_CHANGED"),
        ("local_config_fingerprint", "CONFIG_CHANGED"),
        ("remote_fingerprint", "REMOTE_CHANGED"),
    ):
        if first.get(key) != second.get(key):
            mismatches.append(code)
    if first.get("index") != second.get("index"):
        mismatches.append("INDEX_CHANGED")
    if preserve_unrelated:
        before_direct = _decoded_object(first.get("direct_filesystem"))
        after_direct = _decoded_object(second.get("direct_filesystem"))
        if before_direct.get("entries") != after_direct.get("entries"):
            mismatches.append("UNRELATED_SOURCE_CHANGED")
        if before_direct.get("excluded_entries") != after_direct.get(
            "excluded_entries"
        ):
            mismatches.append("EXCLUDED_PATH_SET_CHANGED")
    return sorted(set(mismatches))


def _run_worktree_root(
    run: CodexRun,
    source_root: Path,
    *,
    plan: ApplyPlan,
) -> Path:
    if not run.worktree_path:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_MISSING",
            "The persisted Run worktree is unavailable.",
        )
    try:
        run_root = Path(run.worktree_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_MISSING",
            "The persisted Run worktree is unavailable.",
        ) from exc
    if not run_root.is_dir() or run_root == source_root:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_UNSAFE",
            "The persisted Run worktree is not an isolated source of postimages.",
        )
    result_lineage = _plan_has_result_lineage(plan)
    if result_lineage:
        expected_identities = (
            plan.run_workspace_identity,
            plan.run_workspace_baseline_identity,
            plan.run_workspace_post_state_identity,
        )
        if any(
            not SHA256_PATTERN.fullmatch(value or "")
            for value in expected_identities
        ):
            raise ApplySessionError(
                "RUN_WORKSPACE_BINDING_INCOMPLETE",
                "The immutable Plan lacks complete Run workspace lineage.",
            )
        if plan.run_workspace_baseline_identity != run.source_snapshot_digest:
            raise ApplySessionError(
                "RUN_WORKSPACE_BASELINE_MISMATCH",
                "The Run workspace baseline no longer matches the immutable Plan.",
            )
        run_root_stat = run_root.stat()
        observed_workspace_identity = canonical_sha256(
            {
                "device": run_root_stat.st_dev,
                "inode": run_root_stat.st_ino,
                "resolved_location": str(run_root),
                "source_snapshot_identity": run.source_snapshot_digest,
                "worktree_branch": run.worktree_branch,
            }
        )
        if observed_workspace_identity != plan.run_workspace_identity:
            raise ApplySessionError(
                "RUN_WORKSPACE_IDENTITY_MISMATCH",
                "The persisted Run workspace is not the workspace bound to the immutable Candidate and Plan.",
            )
    verified_root = Path(
        run_git(
            run_root,
            "rev-parse",
            "--show-toplevel",
            hardened_read_only=True,
        ).stdout.strip()
    ).resolve(strict=True)
    if verified_root != run_root:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_UNSAFE",
            "The persisted Run worktree is not an exact Git worktree root.",
        )
    head = run_git(
        run_root,
        "rev-parse",
        "HEAD",
        hardened_read_only=True,
    ).stdout.strip()
    if head != run.source_commit:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_INVALID",
            "The persisted Run worktree HEAD does not match the Run baseline.",
        )
    git_dir = Path(
        run_git(
            run_root,
            "rev-parse",
            "--absolute-git-dir",
            hardened_read_only=True,
        ).stdout.strip()
    ).resolve(strict=True)
    common_output = run_git(
        run_root,
        "rev-parse",
        "--git-common-dir",
        hardened_read_only=True,
    ).stdout.strip()
    common_candidate = Path(common_output)
    if not common_candidate.is_absolute():
        common_candidate = run_root / common_candidate
    common_dir = common_candidate.resolve(strict=True)
    source_common_output = run_git(
        source_root,
        "rev-parse",
        "--git-common-dir",
        hardened_read_only=True,
    ).stdout.strip()
    source_common_candidate = Path(source_common_output)
    if not source_common_candidate.is_absolute():
        source_common_candidate = source_root / source_common_candidate
    source_common_dir = source_common_candidate.resolve(strict=True)
    unsafe_git_relationship = (
        common_dir != source_common_dir
        if result_lineage
        else (
            not git_dir.is_relative_to(run_root)
            and common_dir != source_common_dir
        )
    )
    if (
        not git_dir.is_dir()
        or not common_dir.is_dir()
        or unsafe_git_relationship
    ):
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_UNSAFE",
            "The persisted Run Git worktree relationship is unsafe.",
        )
    result = _decoded_object(run.structured_result)
    expected_snapshot_digest = str(
        result.get("post_run_snapshot_digest") or ""
    )
    if not SHA256_PATTERN.fullmatch(expected_snapshot_digest):
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_MISSING",
            "The persisted Run postimage snapshot identity is unavailable.",
        )
    approved_source_snapshot = (
        _decoded_object(run.pack.source_snapshot_json)
        if run.pack is not None
        else {}
    )
    source_identity_method = str(
        approved_source_snapshot.get("source_repository_identity_method") or ""
    )
    post_snapshot = capture_source_snapshot(
        run_root,
        hardened_read_only=True,
        source_repository_identity_method=(
            source_identity_method
            if source_identity_method in SOURCE_REPOSITORY_IDENTITY_METHODS
            else SOURCE_REPOSITORY_IDENTITY_METHOD
        ),
    )
    if not approved_source_snapshot.get("source_repository_identity"):
        post_snapshot.pop("source_repository_identity_method", None)
        post_snapshot.pop("source_repository_identity", None)
        post_snapshot["digest"] = _source_snapshot_digest(post_snapshot)
    if post_snapshot.get("digest") != expected_snapshot_digest:
        raise ApplySessionError(
            "POSTIMAGE_MATERIAL_INVALID",
            "The persisted Run worktree no longer matches its exact postimage snapshot.",
        )
    if (
        result_lineage
        and plan.verification_policy == "required"
        and plan.run_workspace_post_state_identity != expected_snapshot_digest
    ):
        raise ApplySessionError(
            "RUN_WORKSPACE_POST_STATE_MISMATCH",
            "The verified Run workspace post-state no longer matches the immutable Plan.",
        )
    return run_root


def _reverse_operation(operation: str) -> str:
    return {
        "CREATE": "DELETE_EXACT",
        "MODIFY": "RESTORE_EXACT",
        "DELETE": "RECREATE_EXACT",
    }[operation]


def _expected_plan_entry_state(
    entry: ApplyPlanEntry,
    *,
    before: bool,
) -> tuple[bool, str | None, int | None, int | None, str]:
    present = entry.operation in ({"MODIFY", "DELETE"} if before else {"CREATE", "MODIFY"})
    return (
        present,
        entry.before_hash if before else entry.after_hash,
        entry.before_size if before else entry.after_size,
        entry.before_mode if before else entry.after_mode,
        "regular" if present else "absent",
    )


def _assert_state_matches_plan(
    actual: dict[str, Any],
    entry: ApplyPlanEntry,
    *,
    before: bool,
) -> None:
    present, expected_hash, expected_size, expected_mode, file_type = (
        _expected_plan_entry_state(entry, before=before)
    )
    if not _state_matches(
        actual,
        present=present,
        expected_hash=expected_hash,
        expected_size=expected_size,
        expected_mode=expected_mode,
        expected_file_type=file_type,
    ):
        raise ApplySessionError(
            "CANDIDATE_PREIMAGE_CONFLICT" if before else "POSTIMAGE_MATERIAL_INVALID",
            (
                "A Candidate target no longer matches its approved preimage."
                if before
                else "The persisted Run postimage does not match the immutable Plan."
            ),
        )


def _required_plan_approval(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
) -> ApplyPlanApproval | None:
    if not _plan_has_result_lineage(plan):
        return None
    approval = get_apply_plan_approval(
        session,
        owner_id=owner_id,
        plan=plan,
    )
    if approval is None:
        raise ApplySessionError(
            "PLAN_APPROVAL_REQUIRED",
            "The Owner must explicitly approve this exact current Apply Plan before Apply.",
        )
    if not validate_apply_plan_approval(
        session,
        approval,
        plan=plan,
        owner_id=owner_id,
    ):
        raise ApplySessionError(
            "PLAN_APPROVAL_INVALID",
            "The persisted Apply Plan approval failed its delivery-lineage integrity check.",
        )
    return approval


def _confirmation_digest(
    plan: ApplyPlan,
    candidate: DeliveryCandidate,
    approval: ApplyPlanApproval | None,
) -> str:
    payload: dict[str, Any] = {
            "schema": "twos.apply_confirmation.v1",
            "policy": APPLY_SESSION_POLICY_VERSION,
            "owner_id": plan.owner_id,
            "plan_id": plan.plan_id,
            "plan_digest": plan.plan_digest,
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.candidate_digest,
            "explicit_confirmation": True,
    }
    if approval is not None:
        payload.update(
            {
                "delivery_lineage_schema": "twos.result_apply_confirmation.v1",
                "candidate_version": plan.candidate_version,
                "result_envelope_id": plan.result_envelope_id,
                "result_envelope_public_id": plan.result_envelope_public_id,
                "result_digest": plan.result_digest,
                "owner_acceptance_id": plan.owner_acceptance_id,
                "result_review_decision_digest": (
                    plan.result_review_decision_digest
                ),
                "apply_plan_approval_id": approval.id,
                "apply_plan_approval_public_id": approval.approval_id,
                "apply_plan_approval_digest": approval.approval_digest,
                "source_workspace_identity": plan.source_workspace_identity,
                "run_workspace_identity": plan.run_workspace_identity,
                "run_workspace_baseline_identity": (
                    plan.run_workspace_baseline_identity
                ),
                "run_workspace_post_state_identity": (
                    plan.run_workspace_post_state_identity
                ),
            }
        )
    return canonical_sha256(payload)


def _revert_confirmation_digest(apply_session: ApplySession) -> str:
    return canonical_sha256(
        {
            "schema": "twos.revert_confirmation.v1",
            "policy": APPLY_SESSION_POLICY_VERSION,
            "owner_id": apply_session.owner_id,
            "apply_session_id": apply_session.session_id,
            "apply_plan_digest": apply_session.apply_plan_digest,
            "candidate_digest": apply_session.candidate_digest,
            "explicit_confirmation": True,
        }
    )


def _owned_existing_for_plan(
    session: Session,
    *,
    owner_id: int,
    plan_id: int,
) -> ApplySession | None:
    return session.scalar(
        select(ApplySession).where(
            ApplySession.owner_id == owner_id,
            ApplySession.apply_plan_id == plan_id,
        )
    )


_REPOSITORY_MUTATION_BLOCKING_STATES = frozenset(
    {
        "APPLYING",
        "REVERTING",
        "APPLY_FAILED_PARTIAL",
        "REVERT_FAILED_PARTIAL",
    }
)


def _repository_mutation_blocker(
    session: Session,
    *,
    repository_locator_fingerprint: str,
    exclude_plan_id: int | None = None,
) -> ApplySession | None:
    conditions = [
        ApplySession.repository_locator_fingerprint
        == repository_locator_fingerprint,
        ApplySession.state.in_(_REPOSITORY_MUTATION_BLOCKING_STATES),
    ]
    if exclude_plan_id is not None:
        conditions.append(ApplySession.apply_plan_id != exclude_plan_id)
    return session.scalar(
        select(ApplySession).where(*conditions).order_by(ApplySession.id)
    )


def find_owned_apply_session(
    session: Session,
    *,
    owner_id: int,
    session_id: str,
) -> ApplySession | None:
    return session.scalar(
        select(ApplySession).where(
            ApplySession.owner_id == owner_id,
            ApplySession.session_id == session_id,
        )
    )


def apply_session_entries(
    session: Session,
    apply_session: ApplySession,
) -> list[ApplySessionEntry]:
    return list(
        session.scalars(
            select(ApplySessionEntry)
            .where(ApplySessionEntry.apply_session_id == apply_session.id)
            .order_by(ApplySessionEntry.operation_ordinal)
        ).all()
    )


def validate_apply_session_journal(
    session: Session,
    apply_session: ApplySession,
) -> bool:
    plan = session.get(ApplyPlan, apply_session.apply_plan_id)
    candidate = session.get(
        DeliveryCandidate,
        apply_session.delivery_candidate_id,
    )
    approval = (
        session.get(ApplyPlanApproval, apply_session.apply_plan_approval_id)
        if apply_session.apply_plan_approval_id is not None
        else None
    )
    if (
        plan is None
        or candidate is None
        or plan.plan_id != apply_session.apply_plan_public_id
        or plan.plan_digest != apply_session.apply_plan_digest
        or candidate.candidate_id != apply_session.candidate_public_id
        or candidate.candidate_digest != apply_session.candidate_digest
        or not SHA256_PATTERN.fullmatch(apply_session.journal_digest or "")
    ):
        return False
    if _plan_has_result_lineage(plan):
        if (
            approval is None
            or not validate_apply_plan_approval(
                session,
                approval,
                plan=plan,
                owner_id=apply_session.owner_id,
            )
            or candidate.candidate_version != apply_session.candidate_version
            or plan.candidate_version != apply_session.candidate_version
            or plan.result_envelope_id != apply_session.result_envelope_id
            or plan.result_envelope_public_id
            != apply_session.result_envelope_public_id
            or plan.result_digest != apply_session.result_digest
            or plan.owner_acceptance_id != apply_session.owner_acceptance_id
            or plan.result_review_decision_digest
            != apply_session.result_review_decision_digest
            or approval.id != apply_session.apply_plan_approval_id
            or approval.approval_id
            != apply_session.apply_plan_approval_public_id
            or approval.approval_digest
            != apply_session.apply_plan_approval_digest
            or plan.source_workspace_identity
            != apply_session.source_workspace_identity
            or plan.run_workspace_identity
            != apply_session.run_workspace_identity
            or plan.run_workspace_baseline_identity
            != apply_session.run_workspace_baseline_identity
            or plan.run_workspace_post_state_identity
            != apply_session.run_workspace_post_state_identity
        ):
            return False
    elif any(
        (
            approval is not None,
            apply_session.result_envelope_id is not None,
            bool(apply_session.result_envelope_public_id),
            bool(apply_session.result_digest),
            apply_session.owner_acceptance_id is not None,
            bool(apply_session.result_review_decision_digest),
            apply_session.apply_plan_approval_id is not None,
            bool(apply_session.apply_plan_approval_public_id),
            bool(apply_session.apply_plan_approval_digest),
            bool(apply_session.source_workspace_identity),
            bool(apply_session.run_workspace_identity),
            bool(apply_session.run_workspace_baseline_identity),
            bool(apply_session.run_workspace_post_state_identity),
        )
    ):
        return False
    rows = apply_session_entries(session, apply_session)
    if len(rows) != apply_session.included_path_count:
        return False
    entry_material: list[dict[str, Any]] = []
    for row in rows:
        plan_entry = session.get(ApplyPlanEntry, row.apply_plan_entry_id)
        if (
            plan_entry is None
            or plan_entry.apply_plan_id != plan.id
            or plan_entry.disposition != "INCLUDED"
            or plan_entry.repository_path != row.repository_path
            or plan_entry.path_identity != row.path_identity
            or plan_entry.operation != row.operation
            or plan_entry.operation_ordinal != row.operation_ordinal
        ):
            return False
        before_material = row.before_material
        after_material = row.after_material
        if (
            (row.before_present and before_material is None)
            or (not row.before_present and before_material is not None)
            or (row.after_present and after_material is None)
            or (not row.after_present and after_material is not None)
        ):
            return False
        if before_material is not None:
            try:
                _assert_material_safe(before_material)
            except ApplySessionError:
                return False
            if (
                _sha256_bytes(before_material) != row.before_hash
                or len(before_material) != row.before_size
            ):
                return False
        if after_material is not None:
            try:
                _assert_material_safe(after_material)
            except ApplySessionError:
                return False
            if (
                _sha256_bytes(after_material) != row.after_hash
                or len(after_material) != row.after_size
            ):
                return False
        before = {
            "present": row.before_present,
            "hash": row.before_hash,
            "size": row.before_size,
            "mode": row.before_mode,
            "file_type": row.before_file_type,
            "atime_ns": row.before_atime_ns,
            "mtime_ns": row.before_mtime_ns,
            "material": before_material,
        }
        after = {
            "present": row.after_present,
            "hash": row.after_hash,
            "size": row.after_size,
            "mode": row.after_mode,
            "file_type": row.after_file_type,
            "atime_ns": row.after_atime_ns,
            "mtime_ns": row.after_mtime_ns,
            "material": after_material,
        }
        entry_material.append(
            _journal_entry_digest_material(
                plan_entry=plan_entry,
                before=before,
                after=after,
                parent_chain=[
                    item
                    for item in _decoded_list(row.parent_chain_json)
                    if isinstance(item, dict)
                ],
                created_parent_dirs=[
                    item
                    for item in _decoded_list(row.created_parent_dirs_json)
                    if isinstance(item, dict)
                ],
                temporary_material_identity=row.temporary_material_identity,
            )
        )
    journal_payload: dict[str, Any] = {
            "schema": "twos.apply_journal.v1",
            "policy": APPLY_SESSION_POLICY_VERSION,
            "owner_id": apply_session.owner_id,
            "apply_plan_id": apply_session.apply_plan_id,
            "apply_plan_public_id": apply_session.apply_plan_public_id,
            "apply_plan_digest": apply_session.apply_plan_digest,
            "delivery_candidate_id": apply_session.delivery_candidate_id,
            "candidate_public_id": apply_session.candidate_public_id,
            "candidate_digest": apply_session.candidate_digest,
            "run_id": apply_session.run_id,
            "task_id": apply_session.task_id,
            "task_version": apply_session.task_version,
            "pack_id": apply_session.pack_id,
            "pack_version": apply_session.pack_version,
            "source_snapshot_identity": apply_session.source_snapshot_identity,
            "source_drift_evaluation_id": (
                apply_session.source_drift_evaluation_id
            ),
            "confirmation_digest": apply_session.apply_confirmation_digest,
            "before_evidence": _decoded_object(
                apply_session.before_evidence_json
            ),
            "entries": entry_material,
    }
    if approval is not None:
        journal_payload.update(
            {
                "delivery_lineage_schema": "twos.result_apply_journal.v1",
                "candidate_version": apply_session.candidate_version,
                "result_envelope_id": apply_session.result_envelope_id,
                "result_envelope_public_id": (
                    apply_session.result_envelope_public_id
                ),
                "result_digest": apply_session.result_digest,
                "owner_acceptance_id": apply_session.owner_acceptance_id,
                "result_review_decision_digest": (
                    apply_session.result_review_decision_digest
                ),
                "apply_plan_approval_id": (
                    apply_session.apply_plan_approval_id
                ),
                "apply_plan_approval_public_id": (
                    apply_session.apply_plan_approval_public_id
                ),
                "apply_plan_approval_digest": (
                    apply_session.apply_plan_approval_digest
                ),
                "source_workspace_identity": (
                    apply_session.source_workspace_identity
                ),
                "run_workspace_identity": apply_session.run_workspace_identity,
                "run_workspace_baseline_identity": (
                    apply_session.run_workspace_baseline_identity
                ),
                "run_workspace_post_state_identity": (
                    apply_session.run_workspace_post_state_identity
                ),
            }
        )
    calculated = canonical_sha256(journal_payload)
    return calculated == apply_session.journal_digest


def _plan_entries(session: Session, plan: ApplyPlan) -> list[ApplyPlanEntry]:
    return list(
        session.scalars(
            select(ApplyPlanEntry)
            .where(ApplyPlanEntry.apply_plan_id == plan.id)
            .order_by(
                ApplyPlanEntry.operation_ordinal.is_(None),
                ApplyPlanEntry.operation_ordinal,
                ApplyPlanEntry.manifest_ordinal,
            )
        ).all()
    )


def _journal_entry_digest_material(
    *,
    plan_entry: ApplyPlanEntry,
    before: dict[str, Any],
    after: dict[str, Any],
    parent_chain: list[dict[str, Any]],
    created_parent_dirs: list[dict[str, Any]],
    temporary_material_identity: str,
) -> dict[str, Any]:
    before_material = before.get("material")
    after_material = after.get("material")
    return {
        "apply_plan_entry_id": plan_entry.id,
        "operation_ordinal": plan_entry.operation_ordinal,
        "repository_path": plan_entry.repository_path,
        "path_identity": plan_entry.path_identity,
        "operation": plan_entry.operation,
        "reverse_operation": _reverse_operation(plan_entry.operation),
        "before": {
            "present": before.get("present"),
            "hash": before.get("hash"),
            "size": before.get("size"),
            "mode": before.get("mode"),
            "file_type": before.get("file_type"),
            "atime_ns": before.get("atime_ns"),
            "mtime_ns": before.get("mtime_ns"),
            "material_digest": (
                _sha256_bytes(before_material)
                if isinstance(before_material, bytes)
                else None
            ),
        },
        "after": {
            "present": after.get("present"),
            "hash": after.get("hash"),
            "size": after.get("size"),
            "mode": after.get("mode"),
            "file_type": after.get("file_type"),
            "atime_ns": after.get("atime_ns"),
            "mtime_ns": after.get("mtime_ns"),
            "material_digest": (
                _sha256_bytes(after_material)
                if isinstance(after_material, bytes)
                else None
            ),
        },
        "temporary_material_identity": temporary_material_identity,
        "parent_chain": parent_chain,
        "created_parent_dirs": created_parent_dirs,
    }


def _journal_digest_from_material(
    *,
    plan: ApplyPlan,
    candidate: DeliveryCandidate,
    approval: ApplyPlanApproval | None,
    confirmation_digest: str,
    drift_id: int,
    before_evidence: dict[str, Any],
    journal_material: list[dict[str, Any]],
) -> str:
    payload: dict[str, Any] = {
            "schema": "twos.apply_journal.v1",
            "policy": APPLY_SESSION_POLICY_VERSION,
            "owner_id": plan.owner_id,
            "apply_plan_id": plan.id,
            "apply_plan_public_id": plan.plan_id,
            "apply_plan_digest": plan.plan_digest,
            "delivery_candidate_id": candidate.id,
            "candidate_public_id": candidate.candidate_id,
            "candidate_digest": candidate.candidate_digest,
            "run_id": plan.run_id,
            "task_id": plan.task_id,
            "task_version": plan.task_version,
            "pack_id": plan.pack_id,
            "pack_version": plan.pack_version,
            "source_snapshot_identity": plan.source_snapshot_identity,
            "source_drift_evaluation_id": drift_id,
            "confirmation_digest": confirmation_digest,
            "before_evidence": before_evidence,
            "entries": [
                _journal_entry_digest_material(
                    plan_entry=item["plan_entry"],
                    before=item["before"],
                    after=item["after"],
                    parent_chain=item["parent_chain"],
                    created_parent_dirs=item["created_parent_dirs"],
                    temporary_material_identity=item[
                        "temporary_material_identity"
                    ],
                )
                for item in journal_material
            ],
    }
    if approval is not None:
        payload.update(
            {
                "delivery_lineage_schema": "twos.result_apply_journal.v1",
                "candidate_version": plan.candidate_version,
                "result_envelope_id": plan.result_envelope_id,
                "result_envelope_public_id": plan.result_envelope_public_id,
                "result_digest": plan.result_digest,
                "owner_acceptance_id": plan.owner_acceptance_id,
                "result_review_decision_digest": (
                    plan.result_review_decision_digest
                ),
                "apply_plan_approval_id": approval.id,
                "apply_plan_approval_public_id": approval.approval_id,
                "apply_plan_approval_digest": approval.approval_digest,
                "source_workspace_identity": plan.source_workspace_identity,
                "run_workspace_identity": plan.run_workspace_identity,
                "run_workspace_baseline_identity": (
                    plan.run_workspace_baseline_identity
                ),
                "run_workspace_post_state_identity": (
                    plan.run_workspace_post_state_identity
                ),
            }
        )
    return canonical_sha256(payload)


def _session_base(
    *,
    plan: ApplyPlan,
    candidate: DeliveryCandidate,
    approval: ApplyPlanApproval | None,
    drift_id: int,
    state: str,
    before_evidence: dict[str, Any],
    confirmation_digest: str,
    journal_digest: str,
    plan_entries: list[ApplyPlanEntry],
    failure_evidence: list[dict[str, Any]] | None = None,
) -> ApplySession:
    included = [
        {
            "path": row.display_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
        }
        for row in plan_entries
        if row.disposition == "INCLUDED"
    ]
    excluded = [
        {
            "path": row.display_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
        }
        for row in plan_entries
        if row.disposition == "EXCLUDED"
    ]
    blocked = [
        {
            "path": row.display_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
            "reason_code": row.reason_code,
        }
        for row in plan_entries
        if row.disposition == "BLOCKED"
    ]
    ordered = [
        {
            "ordinal": row.operation_ordinal,
            "path": row.repository_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
        }
        for row in plan_entries
        if row.disposition == "INCLUDED"
    ]
    session_identity = canonical_sha256(
        {
            "schema": APPLY_SESSION_SCHEMA,
            "policy": APPLY_SESSION_POLICY_VERSION,
            "owner_id": plan.owner_id,
            "plan_id": plan.plan_id,
            "plan_digest": plan.plan_digest,
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.candidate_digest,
            "confirmation_digest": confirmation_digest,
            **(
                {
                    "candidate_version": plan.candidate_version,
                    "result_digest": plan.result_digest,
                    "result_review_decision_digest": (
                        plan.result_review_decision_digest
                    ),
                    "apply_plan_approval_digest": approval.approval_digest,
                    "source_workspace_identity": plan.source_workspace_identity,
                    "run_workspace_identity": plan.run_workspace_identity,
                    "run_workspace_baseline_identity": (
                        plan.run_workspace_baseline_identity
                    ),
                    "run_workspace_post_state_identity": (
                        plan.run_workspace_post_state_identity
                    ),
                }
                if approval is not None
                else {}
            ),
        }
    )
    index = _decoded_object(before_evidence.get("index"))
    return ApplySession(
        session_id="as_" + session_identity[:40],
        owner_id=plan.owner_id,
        apply_plan_id=plan.id,
        apply_plan_public_id=plan.plan_id,
        apply_plan_digest=plan.plan_digest,
        delivery_candidate_id=candidate.id,
        candidate_public_id=candidate.candidate_id,
        candidate_digest=candidate.candidate_digest,
        candidate_version=plan.candidate_version,
        result_envelope_id=plan.result_envelope_id,
        result_envelope_public_id=plan.result_envelope_public_id,
        result_digest=plan.result_digest,
        owner_acceptance_id=plan.owner_acceptance_id,
        result_review_decision_digest=plan.result_review_decision_digest,
        apply_plan_approval_id=approval.id if approval is not None else None,
        apply_plan_approval_public_id=(
            approval.approval_id if approval is not None else ""
        ),
        apply_plan_approval_digest=(
            approval.approval_digest if approval is not None else ""
        ),
        run_id=plan.run_id,
        task_id=plan.task_id,
        task_version=plan.task_version,
        pack_id=plan.pack_id,
        pack_version=plan.pack_version,
        source_snapshot_identity=plan.source_snapshot_identity,
        source_workspace_identity=plan.source_workspace_identity,
        run_workspace_identity=plan.run_workspace_identity,
        run_workspace_baseline_identity=plan.run_workspace_baseline_identity,
        run_workspace_post_state_identity=plan.run_workspace_post_state_identity,
        source_drift_evaluation_id=drift_id,
        repository_locator_fingerprint=str(
            before_evidence.get("repository_locator_fingerprint")
            or plan.repository_locator_fingerprint
        ),
        repository_fingerprint=str(
            before_evidence.get("repository_fingerprint")
            or plan.repository_fingerprint
        ),
        sanitized_repository_identity=str(
            before_evidence.get("sanitized_repository_identity")
            or plan.sanitized_repository_identity
        ),
        branch=str(before_evidence.get("branch") or plan.branch),
        pre_apply_head=str(before_evidence.get("head") or plan.observed_head),
        pre_apply_index_fingerprint=str(
            index.get("fingerprint") or plan.index_fingerprint
        ),
        pre_apply_worktree_fingerprint=str(
            before_evidence.get("worktree_fingerprint")
            or plan.worktree_fingerprint
        ),
        included_path_count=len(included),
        excluded_path_count=len(excluded),
        blocked_path_count=len(blocked),
        included_paths_json=canonical_json(included),
        excluded_paths_json=canonical_json(excluded),
        blocked_paths_json=canonical_json(blocked),
        ordered_operations_json=canonical_json(ordered),
        apply_confirmation_digest=confirmation_digest,
        journal_digest=journal_digest,
        before_evidence_json=canonical_json(before_evidence),
        state=state,
        integrity_check_result=(
            "BLOCKED" if state == "PREFLIGHT_BLOCKED" else "NOT_RUN"
        ),
        failure_evidence_json=canonical_json(failure_evidence or []),
        started_at=utc_now() if state == "APPLYING" else None,
        finished_at=utc_now() if state == "PREFLIGHT_BLOCKED" else None,
    )


def _persist_blocked_session(
    session: Session,
    *,
    plan: ApplyPlan,
    candidate: DeliveryCandidate,
    approval: ApplyPlanApproval | None,
    plan_entries: list[ApplyPlanEntry],
    confirmation_digest: str,
    drift_id: int,
    before_evidence: dict[str, Any],
    failure: dict[str, Any],
) -> tuple[ApplySession, bool]:
    blocked = _session_base(
        plan=plan,
        candidate=candidate,
        approval=approval,
        drift_id=drift_id,
        state="PREFLIGHT_BLOCKED",
        before_evidence=before_evidence,
        confirmation_digest=confirmation_digest,
        journal_digest=canonical_sha256(
            {
                "schema": "twos.apply_blocked_journal.v1",
                "policy": APPLY_SESSION_POLICY_VERSION,
                "owner_id": plan.owner_id,
                "plan_digest": plan.plan_digest,
                "candidate_digest": candidate.candidate_digest,
                **(
                    {
                        "delivery_lineage_schema": "twos.result_apply_blocked_journal.v1",
                        "candidate_version": plan.candidate_version,
                        "result_envelope_id": plan.result_envelope_id,
                        "result_envelope_public_id": (
                            plan.result_envelope_public_id
                        ),
                        "apply_plan_approval_digest": approval.approval_digest,
                        "apply_plan_approval_id": approval.id,
                        "apply_plan_approval_public_id": approval.approval_id,
                        "result_digest": plan.result_digest,
                        "owner_acceptance_id": plan.owner_acceptance_id,
                        "result_review_decision_digest": (
                            plan.result_review_decision_digest
                        ),
                        "source_workspace_identity": (
                            plan.source_workspace_identity
                        ),
                        "run_workspace_identity": plan.run_workspace_identity,
                        "run_workspace_baseline_identity": (
                            plan.run_workspace_baseline_identity
                        ),
                        "run_workspace_post_state_identity": (
                            plan.run_workspace_post_state_identity
                        ),
                        "run_workspace_identity": plan.run_workspace_identity,
                        "run_workspace_baseline_identity": (
                            plan.run_workspace_baseline_identity
                        ),
                        "run_workspace_post_state_identity": (
                            plan.run_workspace_post_state_identity
                        ),
                    }
                    if approval is not None
                    else {}
                ),
                "confirmation_digest": confirmation_digest,
                "failure": failure,
            }
        ),
        plan_entries=plan_entries,
        failure_evidence=[failure],
    )
    session.add(blocked)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = _owned_existing_for_plan(
            session,
            owner_id=plan.owner_id,
            plan_id=plan.id,
        )
        if existing is None:
            raise ApplySessionError(
                "CONCURRENT_APPLY",
                "Another Apply or Revert session is active for this repository.",
            )
        return existing, False
    _append_audit(
        session,
        blocked,
        phase="PREFLIGHT",
        event_type="PREFLIGHT_BLOCKED",
        evidence=failure,
    )
    session.commit()
    return blocked, True


def _preflight_blocker_evidence(
    code: str,
    *,
    message: str,
    difference: object = None,
) -> dict[str, Any]:
    details = difference.as_dict() if hasattr(difference, "as_dict") else {}
    return {
        "code": code,
        "phase": "PREFLIGHT",
        "message": message,
        "details": details,
    }


def _prepare_apply_journal(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
    approval: ApplyPlanApproval | None,
    source_repo: Path,
) -> tuple[
    CodexRun,
    DeliveryCandidate,
    Path,
    list[ApplyPlanEntry],
    list[dict[str, Any]],
    dict[str, Any],
    int,
]:
    if plan.owner_id != owner_id:
        raise ApplySessionError(
            "APPLY_PLAN_NOT_FOUND",
            "The Apply Plan is unavailable.",
        )
    required_approval = _required_plan_approval(
        session,
        owner_id=owner_id,
        plan=plan,
    )
    if (
        (required_approval is None) != (approval is None)
        or (
            required_approval is not None
            and approval is not None
            and required_approval.id != approval.id
        )
    ):
        raise ApplySessionError(
            "PLAN_APPROVAL_BINDING_CHANGED",
            "The Apply Plan approval changed before preflight.",
        )
    if not validate_apply_plan_integrity(session, plan):
        raise ApplySessionError(
            "PLAN_INTEGRITY_INVALID",
            "The immutable Apply Plan failed its integrity check.",
        )
    if plan.policy_version != APPLY_PLAN_POLICY_VERSION:
        raise ApplySessionError(
            "PLAN_EXPIRED",
            "The Apply Plan uses an expired policy version.",
        )
    run = session.get(CodexRun, plan.run_id)
    candidate = (
        session.get(DeliveryCandidate, plan.delivery_candidate_id)
        if plan.delivery_candidate_id is not None
        else None
    )
    if (
        run is None
        or candidate is None
        or candidate.owner_id != owner_id
        or run.task_id != plan.task_id
    ):
        raise ApplySessionError(
            "CANDIDATE_UNAVAILABLE",
            "The Plan-bound Candidate and Run are unavailable.",
        )
    candidate_eligibility = validate_delivery_candidate(
        session,
        owner_id,
        run,
        candidate,
    )
    if candidate_eligibility.get("eligible") is not True:
        raise ApplySessionError(
            "CANDIDATE_INTEGRITY_INVALID",
            "The immutable Candidate no longer satisfies its exact bindings.",
        )
    root = _verified_repository_root(
        run,
        source_repo,
        expected_source_workspace_identity=plan.source_workspace_identity,
        expected_source_snapshot_identity=plan.source_snapshot_identity,
        require_strong_source_identity=_plan_has_result_lineage(plan),
    )
    plan_entries = _plan_entries(session, plan)
    blocked_entries = [row for row in plan_entries if row.disposition == "BLOCKED"]
    included_entries = [row for row in plan_entries if row.disposition == "INCLUDED"]
    if blocked_entries:
        raise ApplySessionError(
            "BLOCKED_PATH_PRESENT",
            "The Apply Plan contains a BLOCKED Candidate path.",
        )
    if not included_entries:
        raise ApplySessionError(
            "NO_INCLUDED_PATHS",
            "The Apply Plan contains no INCLUDED Candidate paths.",
        )
    if any(
        row.operation not in {"CREATE", "MODIFY", "DELETE"}
        or row.operation_ordinal is None
        or not row.repository_path
        for row in included_entries
    ):
        raise ApplySessionError(
            "PLAN_ENTRY_INVALID",
            "The Apply Plan operation order is incomplete.",
        )
    included_entries.sort(key=lambda row: int(row.operation_ordinal or 0))
    if [row.operation_ordinal for row in included_entries] != list(
        range(1, len(included_entries) + 1)
    ):
        raise ApplySessionError(
            "PLAN_ENTRY_INVALID",
            "The Apply Plan operation order is not contiguous.",
        )

    initial_observation = observe_repository(run, root)
    if initial_observation["branch"] != "main":
        raise ApplySessionError(
            "WRONG_BRANCH",
            "Apply is permitted only on branch main.",
        )
    if initial_observation["staged_path_count"] != 0:
        raise ApplySessionError(
            "STAGED_PATHS_PRESENT",
            "Apply requires an index with zero staged paths.",
        )
    if (
        initial_observation["repository_locator_fingerprint"]
        != plan.repository_locator_fingerprint
    ):
        raise ApplySessionError(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The current repository does not match the immutable Plan.",
        )
    if initial_observation["observed_head"] != plan.observed_head:
        raise ApplySessionError(
            "HEAD_CHANGED",
            "HEAD no longer matches the immutable Apply Plan.",
        )
    if initial_observation["index_fingerprint"] != plan.index_fingerprint:
        raise ApplySessionError(
            "INDEX_FINGERPRINT_CHANGED",
            "The Git index bytes no longer match the immutable Apply Plan.",
        )
    fresh_drift = evaluate_source_drift(
        session,
        owner_id=owner_id,
        run=run,
        candidate=candidate,
        source_repo=root,
    )
    if fresh_drift.status not in {
        "ready_to_apply",
        "source_changed_since_run",
    }:
        raise ApplySessionError(
            {
                "conflict_detected": "CONFLICT_DETECTED",
                "candidate_unavailable": "CANDIDATE_UNAVAILABLE",
                "repository_unavailable": "REPOSITORY_UNAVAILABLE",
            }.get(fresh_drift.status, "SOURCE_DRIFT_BLOCKED"),
            "A fresh Source Drift evaluation blocked Apply.",
        )
    observation = observe_repository(run, root)
    if (
        observation["current_source_digest"] != fresh_drift.current_source_digest
        or observation["observed_head"] != fresh_drift.current_head
    ):
        changed_components = []
        if observation["current_source_digest"] != fresh_drift.current_source_digest:
            changed_components.append("SOURCE_CHANGED")
        if observation["observed_head"] != fresh_drift.current_head:
            changed_components.append("HEAD_CHANGED")
        raise ApplySessionError(
            "REPOSITORY_CHANGED_DURING_PREFLIGHT",
            "The repository changed during the fresh preflight.",
            details={"codes": changed_components},
        )
    effective_state, blockers = effective_apply_plan_state(
        session,
        plan,
        source_repo=root,
        repository_observation=observation,
    )
    if effective_state not in APPLY_ELIGIBLE_PLAN_STATES:
        code = (
            str(blockers[0].get("code") or "PLAN_EXPIRED")
            if blockers
            else "PLAN_NOT_APPLY_READY"
        )
        raise ApplySessionError(
            code,
            "The immutable Apply Plan is not current and Apply-ready.",
        )
    if (
        observation["repository_locator_fingerprint"]
        != plan.repository_locator_fingerprint
        or observation["observed_head"] != plan.observed_head
        or observation["index_fingerprint"] != plan.index_fingerprint
    ):
        raise ApplySessionError(
            "PLAN_REPOSITORY_BINDING_CHANGED",
            "The repository, HEAD, or index no longer matches the Plan.",
        )

    target_paths = [row.repository_path for row in included_entries]
    before_evidence_first = _global_evidence(
        run,
        root,
        target_paths=target_paths,
    )
    run_root = _run_worktree_root(run, root, plan=plan)
    journal_material: list[dict[str, Any]] = []
    for row in included_entries:
        before_state, parent_chain = _target_state(root, row.repository_path)
        _assert_state_matches_plan(before_state, row, before=True)
        if row.operation in {"CREATE", "MODIFY"}:
            after_state, _ = _target_state(run_root, row.repository_path)
            _assert_state_matches_plan(after_state, row, before=False)
        else:
            after_state = {
                "present": False,
                "hash": None,
                "size": None,
                "mode": None,
                "file_type": "absent",
                "atime_ns": None,
                "mtime_ns": None,
                "material": None,
            }
        missing_parents = [
            {
                "path": item["path"],
                "path_identity": item["path_identity"],
                "mode": 0o755,
            }
            for item in parent_chain
            if item.get("present") is False
        ]
        if row.operation != "CREATE" and missing_parents:
            raise ApplySessionError(
                "PARENT_CHAIN_UNSAFE",
                "A non-CREATE target has a missing parent.",
            )
        if row.operation == "CREATE":
            present_after_missing = False
            seen_missing = False
            for item in parent_chain:
                if item.get("present") is False:
                    seen_missing = True
                elif seen_missing:
                    present_after_missing = True
            if present_after_missing:
                raise ApplySessionError(
                    "PARENT_CHAIN_UNSAFE",
                    "A CREATE parent chain is internally inconsistent.",
                )
        journal_material.append(
            {
                "plan_entry": row,
                "before": before_state,
                "after": after_state,
                "parent_chain": parent_chain,
                "created_parent_dirs": missing_parents,
                "temporary_material_identity": canonical_sha256(
                    {
                        "schema": "twos.apply_temporary_material.v1",
                        "plan_digest": plan.plan_digest,
                        "path_identity": row.path_identity,
                        "after_hash": row.after_hash,
                    }
                ),
            }
        )
    # A missing directory is session-owned exactly once, even when multiple
    # CREATE entries share it. The earliest operation owns its creation and
    # the matching reverse cleanup; later siblings only consume it.
    claimed_created_parents: set[str] = set()
    for item in journal_material:
        owned_parents: list[dict[str, Any]] = []
        for record in item["created_parent_dirs"]:
            path = str(record["path"])
            if path in claimed_created_parents:
                continue
            claimed_created_parents.add(path)
            owned_parents.append(record)
        item["created_parent_dirs"] = owned_parents
    before_evidence = _global_evidence(
        run,
        root,
        target_paths=target_paths,
    )
    preflight_difference = semantic_diff(
        before_evidence_first,
        before_evidence,
        candidate_paths=target_paths,
    )
    if preflight_difference.changed:
        raise ApplySessionError(
            "REPOSITORY_CHANGED_DURING_PREFLIGHT",
            preflight_difference.safe_message(
                "Repository delivery state changed while the durable journal was prepared."
            ),
            details={
                "semantic_difference": preflight_difference.as_dict(),
                "preflight_observations": {
                    "observation_a": before_evidence_first,
                    "observation_b": before_evidence,
                },
            },
        )
    observation_b = {
        key: value
        for key, value in before_evidence.items()
        if key != "preflight_observations"
    }
    before_evidence["preflight_observations"] = {
        "observation_a": before_evidence_first,
        "observation_b": observation_b,
        "semantic_difference": preflight_difference.as_dict(),
        "metadata_diagnostics": {
            "observation_a": metadata_diagnostics(before_evidence_first),
            "observation_b": metadata_diagnostics(observation_b),
        },
    }
    if _decoded_object(before_evidence["index"]).get("staged_path_count") != 0:
        raise ApplySessionError(
            "STAGED_PATHS_PRESENT",
            "Apply requires an index with zero staged paths.",
        )
    return (
        run,
        candidate,
        root,
        plan_entries,
        journal_material,
        before_evidence,
        fresh_drift.id,
    )


def _persist_applying_session(
    session: Session,
    *,
    plan: ApplyPlan,
    candidate: DeliveryCandidate,
    approval: ApplyPlanApproval | None,
    drift_id: int,
    before_evidence: dict[str, Any],
    confirmation_digest: str,
    plan_entries: list[ApplyPlanEntry],
    journal_material: list[dict[str, Any]],
) -> tuple[ApplySession, bool]:
    applying = _session_base(
        plan=plan,
        candidate=candidate,
        approval=approval,
        drift_id=drift_id,
        state="APPLYING",
        before_evidence=before_evidence,
        confirmation_digest=confirmation_digest,
        journal_digest=_journal_digest_from_material(
            plan=plan,
            candidate=candidate,
            approval=approval,
            confirmation_digest=confirmation_digest,
            drift_id=drift_id,
            before_evidence=before_evidence,
            journal_material=journal_material,
        ),
        plan_entries=plan_entries,
    )
    session.add(applying)
    try:
        session.flush()
        for item in journal_material:
            row = item["plan_entry"]
            before = item["before"]
            after = item["after"]
            entry = ApplySessionEntry(
                apply_session_id=applying.id,
                apply_plan_entry_id=row.id,
                operation_ordinal=int(row.operation_ordinal),
                repository_path=row.repository_path,
                path_identity=row.path_identity,
                operation=row.operation,
                reverse_operation=_reverse_operation(row.operation),
                before_present=bool(before["present"]),
                before_hash=before["hash"],
                before_size=before["size"],
                before_mode=before["mode"],
                before_file_type=before["file_type"],
                before_atime_ns=before["atime_ns"],
                before_mtime_ns=before["mtime_ns"],
                before_material=before["material"],
                after_present=bool(after["present"]),
                after_hash=after["hash"],
                after_size=after["size"],
                after_mode=after["mode"],
                after_file_type=after["file_type"],
                after_atime_ns=after["atime_ns"],
                after_mtime_ns=after["mtime_ns"],
                after_material=after["material"],
                temporary_material_identity=item["temporary_material_identity"],
                parent_chain_json=canonical_json(item["parent_chain"]),
                created_parent_dirs_json=canonical_json(
                    item["created_parent_dirs"]
                ),
            )
            session.add(entry)
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = _owned_existing_for_plan(
            session,
            owner_id=plan.owner_id,
            plan_id=plan.id,
        )
        if existing is None:
            raise ApplySessionError(
                "CONCURRENT_APPLY",
                "Another Apply or Revert session is active for this repository.",
            )
        return existing, False
    _append_audit(
        session,
        applying,
        phase="APPLY",
        event_type="DURABLE_JOURNAL_READY",
        evidence={
            "included_path_count": applying.included_path_count,
            "excluded_path_count": applying.excluded_path_count,
            "blocked_path_count": applying.blocked_path_count,
            "index_staged_path_count": _decoded_object(
                before_evidence.get("index")
            ).get("staged_path_count"),
            "journal_is_durable_before_mutation": True,
        },
    )
    # This commit is intentionally inside the service boundary: source mutation
    # is forbidden until the complete journal and APPLYING claim are durable.
    session.commit()
    return applying, True


_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


def _open_directory_at_root(root: Path, relative_directory: str) -> int:
    root_fd = os.open(root, _DIRECTORY_FLAGS)
    current_fd = root_fd
    try:
        if relative_directory:
            normalized = normalize_repository_path(
                relative_directory + "/placeholder"
            )
            parts = PurePosixPath(normalized).parts[:-1]
            for part in parts:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
        if current_fd == root_fd:
            return root_fd
        os.close(root_fd)
        return current_fd
    except BaseException:
        if current_fd != root_fd:
            os.close(current_fd)
        os.close(root_fd)
        raise


def _open_parent_directory(root: Path, repository_path: str) -> tuple[int, str]:
    normalized = normalize_repository_path(repository_path)
    pure = PurePosixPath(normalized)
    parent = "" if pure.parent == PurePosixPath(".") else pure.parent.as_posix()
    return _open_directory_at_root(root, parent), pure.name


def _revalidate_parent_directory(
    root: Path,
    repository_path: str,
    parent_fd: int,
) -> None:
    check_fd, _ = _open_parent_directory(root, repository_path)
    try:
        current = os.fstat(parent_fd)
        checked = os.fstat(check_fd)
        if (current.st_dev, current.st_ino) != (checked.st_dev, checked.st_ino):
            raise ApplySessionError(
                "PARENT_CHAIN_CHANGED",
                "The anchored target parent changed immediately before mutation.",
            )
    finally:
        os.close(check_fd)


def _fsync_directory_fd(directory_fd: int) -> None:
    os.fsync(directory_fd)


def _write_fd(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _temporary_name(target_name: str) -> str:
    safe_stem = target_name[:80].replace("/", "_")
    return f".{safe_stem}.twos-apply-{secrets.token_hex(12)}.tmp"


def _immediate_entry_guard_at(
    root: Path,
    entry: ApplySessionEntry,
    *,
    expected: str,
    parent_fd: int,
    target_name: str,
) -> int | None:
    present = entry.before_present if expected == "before" else entry.after_present
    expected_hash = entry.before_hash if expected == "before" else entry.after_hash
    expected_size = entry.before_size if expected == "before" else entry.after_size
    expected_mode = entry.before_mode if expected == "before" else entry.after_mode
    _revalidate_parent_directory(root, entry.repository_path, parent_fd)
    if not present:
        try:
            os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            _revalidate_parent_directory(root, entry.repository_path, parent_fd)
            return None
        raise ApplySessionError(
            "PATH_PRECONDITION_CONFLICT",
            "An exact absent-path precondition no longer holds.",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target_name, flags, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        pathname = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(pathname.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (pathname.st_dev, pathname.st_ino)
            or opened.st_size != expected_size
            or (opened.st_mode & 0o777) != expected_mode
        ):
            raise ApplySessionError(
                "PATH_PRECONDITION_CONFLICT",
                "An exact file identity precondition no longer holds.",
            )
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        final = os.fstat(fd)
        final_pathname = os.stat(
            target_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        _revalidate_parent_directory(root, entry.repository_path, parent_fd)
        if (
            size != expected_size
            or digest.hexdigest() != expected_hash
            or (final.st_dev, final.st_ino) != (opened.st_dev, opened.st_ino)
            or final.st_mtime_ns != opened.st_mtime_ns
            or (final_pathname.st_dev, final_pathname.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise ApplySessionError(
                "PATH_PRECONDITION_CONFLICT",
                "An exact file identity changed immediately before mutation.",
            )
        return fd
    except BaseException:
        os.close(fd)
        raise


def _prepare_temporary_material(
    parent_fd: int,
    target_name: str,
    payload: bytes,
    mode: int,
    *,
    atime_ns: int | None,
    mtime_ns: int | None,
) -> str:
    if len(payload) > MAX_APPLY_FILE_BYTES:
        raise ApplySessionError(
            "FILE_TOO_LARGE",
            "Apply material exceeds the bounded file limit.",
        )
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    temporary = ""
    fd = -1
    for _ in range(32):
        temporary = _temporary_name(target_name)
        try:
            fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            break
        except FileExistsError:
            continue
    if fd < 0:
        raise ApplySessionError(
            "TEMPORARY_MATERIAL_UNAVAILABLE",
            "Safe temporary material could not be allocated.",
        )
    try:
        _write_fd(fd, payload)
        os.fchmod(fd, mode & 0o777)
        if atime_ns is not None and mtime_ns is not None:
            os.utime(fd, ns=(atime_ns, mtime_ns))
        os.fsync(fd)
        item_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(item_stat.st_mode)
            or item_stat.st_size != len(payload)
            or (item_stat.st_mode & 0o777) != (mode & 0o777)
            or (
                mtime_ns is not None
                and item_stat.st_mtime_ns != mtime_ns
            )
        ):
            raise ApplySessionError(
                "TEMPORARY_MATERIAL_INVALID",
                "Safe temporary material failed its integrity check.",
            )
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != _sha256_bytes(payload):
            raise ApplySessionError(
                "TEMPORARY_MATERIAL_INVALID",
                "Safe temporary material failed its hash check.",
            )
    except BaseException:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    os.close(fd)
    return temporary


def _atomic_create_file(
    root: Path,
    entry: ApplySessionEntry,
    payload: bytes,
    mode: int,
    *,
    atime_ns: int | None,
    mtime_ns: int | None,
) -> None:
    parent_fd, target_name = _open_parent_directory(root, entry.repository_path)
    temporary = _prepare_temporary_material(
        parent_fd,
        target_name,
        payload,
        mode,
        atime_ns=atime_ns,
        mtime_ns=mtime_ns,
    )
    guard_fd: int | None = None
    try:
        guard_fd = _immediate_entry_guard_at(
            root,
            entry,
            expected="before" if not entry.before_present else "after",
            parent_fd=parent_fd,
            target_name=target_name,
        )
        try:
            os.link(
                temporary,
                target_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise ApplySessionError(
                "CREATE_TARGET_EXISTS",
                "A CREATE target is no longer absent.",
            ) from exc
        os.unlink(temporary, dir_fd=parent_fd)
        _fsync_directory_fd(parent_fd)
    finally:
        if guard_fd is not None:
            os.close(guard_fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _atomic_replace_file(
    root: Path,
    entry: ApplySessionEntry,
    payload: bytes,
    mode: int,
    *,
    atime_ns: int | None,
    mtime_ns: int | None,
    expected: str,
) -> None:
    parent_fd, target_name = _open_parent_directory(root, entry.repository_path)
    temporary = _prepare_temporary_material(
        parent_fd,
        target_name,
        payload,
        mode,
        atime_ns=atime_ns,
        mtime_ns=mtime_ns,
    )
    guard_fd: int | None = None
    try:
        guard_fd = _immediate_entry_guard_at(
            root,
            entry,
            expected=expected,
            parent_fd=parent_fd,
            target_name=target_name,
        )
        os.replace(
            temporary,
            target_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        _fsync_directory_fd(parent_fd)
    finally:
        if guard_fd is not None:
            os.close(guard_fd)
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        os.close(parent_fd)


def _unlink_entry_file(
    root: Path,
    entry: ApplySessionEntry,
    *,
    expected: str,
) -> None:
    parent_fd, target_name = _open_parent_directory(root, entry.repository_path)
    guard_fd: int | None = None
    try:
        guard_fd = _immediate_entry_guard_at(
            root,
            entry,
            expected=expected,
            parent_fd=parent_fd,
            target_name=target_name,
        )
        os.unlink(target_name, dir_fd=parent_fd)
        _fsync_directory_fd(parent_fd)
    finally:
        if guard_fd is not None:
            os.close(guard_fd)
        os.close(parent_fd)


def _created_parent_records(entry: ApplySessionEntry) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in _decoded_list(entry.created_parent_dirs_json):
        if isinstance(raw, str):
            path = normalize_repository_path(raw)
            records.append(
                {
                    "path": path,
                    "path_identity": _path_identity(path),
                    "mode": 0o755,
                }
            )
        elif isinstance(raw, dict):
            path = normalize_repository_path(raw.get("path"))
            records.append(
                {
                    "path": path,
                    "path_identity": _path_identity(path),
                    "mode": int(raw.get("mode", 0o755)) & 0o777,
                }
            )
    return records


def _create_recorded_parents(root: Path, entry: ApplySessionEntry) -> None:
    records = _created_parent_records(entry)
    for record in records:
        try:
            parent_fd, name = _open_parent_directory(root, record["path"])
        except FileNotFoundError:
            continue
        try:
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ApplySessionError(
                "CREATE_PARENT_EXISTS",
                "A parent recorded as absent now exists.",
            )
        finally:
            os.close(parent_fd)
    created: list[str] = []
    try:
        for record in records:
            parent_fd, name = _open_parent_directory(root, record["path"])
            try:
                os.mkdir(name, record["mode"], dir_fd=parent_fd)
                created.append(record["path"])
                created_stat = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISDIR(created_stat.st_mode):
                    raise ApplySessionError(
                        "PARENT_CHAIN_UNSAFE",
                        "A recorded parent was not created as a directory.",
                    )
                _fsync_directory_fd(parent_fd)
            finally:
                os.close(parent_fd)
    except Exception:
        for relative_path in reversed(created):
            try:
                parent_fd, name = _open_parent_directory(root, relative_path)
                try:
                    os.rmdir(name, dir_fd=parent_fd)
                    _fsync_directory_fd(parent_fd)
                finally:
                    os.close(parent_fd)
            except OSError:
                pass
        raise


def _remove_recorded_empty_parents(root: Path, entry: ApplySessionEntry) -> None:
    for record in reversed(_created_parent_records(entry)):
        try:
            parent_fd, name = _open_parent_directory(root, record["path"])
        except FileNotFoundError:
            continue
        try:
            try:
                item_stat = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(item_stat.st_mode):
                raise ApplySessionError(
                    "CREATED_PARENT_CONFLICT",
                    "A parent created by Apply is no longer an empty directory.",
                )
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError as exc:
                raise ApplySessionError(
                    "CREATED_PARENT_NOT_EMPTY",
                    "A parent created by Apply is no longer empty.",
                ) from exc
            _fsync_directory_fd(parent_fd)
        finally:
            os.close(parent_fd)


def _apply_entry(root: Path, entry: ApplySessionEntry) -> None:
    if not _entry_matches_before(root, entry):
        raise ApplySessionError(
            "CANDIDATE_PREIMAGE_CONFLICT",
            "A target changed after the durable Apply journal was captured.",
        )
    if entry.operation == "CREATE":
        _create_recorded_parents(root, entry)
        entry.apply_result = "PARENTS_CREATED"
        if entry.after_material is None or entry.after_mode is None:
            raise ApplySessionError(
                "POSTIMAGE_MATERIAL_MISSING",
                "CREATE postimage material is unavailable.",
            )
        _atomic_create_file(
            root,
            entry,
            entry.after_material,
            entry.after_mode,
            atime_ns=entry.after_atime_ns,
            mtime_ns=entry.after_mtime_ns,
        )
    elif entry.operation == "MODIFY":
        if entry.after_material is None or entry.after_mode is None:
            raise ApplySessionError(
                "POSTIMAGE_MATERIAL_MISSING",
                "MODIFY postimage material is unavailable.",
            )
        if not _entry_matches_before(root, entry):
            raise ApplySessionError(
                "CANDIDATE_PREIMAGE_CONFLICT",
                "A MODIFY target changed immediately before replacement.",
            )
        _atomic_replace_file(
            root,
            entry,
            entry.after_material,
            entry.after_mode,
            atime_ns=entry.after_atime_ns,
            mtime_ns=entry.after_mtime_ns,
            expected="before",
        )
    elif entry.operation == "DELETE":
        if not _entry_matches_before(root, entry):
            raise ApplySessionError(
                "CANDIDATE_PREIMAGE_CONFLICT",
                "A DELETE target changed immediately before deletion.",
            )
        _unlink_entry_file(root, entry, expected="before")
    else:
        raise ApplySessionError(
            "UNSUPPORTED_OPERATION",
            "The Apply operation is unsupported.",
        )
    if not _entry_matches_after(root, entry):
        raise ApplySessionError(
            "APPLY_POSTIMAGE_MISMATCH",
            "An Apply operation did not produce its exact intended state.",
        )


def _restore_entry_before(root: Path, entry: ApplySessionEntry) -> None:
    if _entry_matches_before(root, entry):
        if entry.operation == "CREATE" and entry.apply_result in {
            "PARENTS_CREATED",
            "APPLIED",
        }:
            _remove_recorded_empty_parents(root, entry)
        return
    if not _entry_matches_after(root, entry):
        raise ApplySessionError(
            "COMPENSATION_PRECONDITION_CONFLICT",
            "An affected path matches neither its before nor intended after state.",
        )
    if entry.operation == "CREATE":
        _unlink_entry_file(root, entry, expected="after")
        _remove_recorded_empty_parents(root, entry)
    elif entry.operation == "MODIFY":
        if entry.before_material is None or entry.before_mode is None:
            raise ApplySessionError(
                "RESTORATION_MATERIAL_MISSING",
                "MODIFY restoration material is unavailable.",
            )
        _atomic_replace_file(
            root,
            entry,
            entry.before_material,
            entry.before_mode,
            atime_ns=entry.before_atime_ns,
            mtime_ns=entry.before_mtime_ns,
            expected="after",
        )
    elif entry.operation == "DELETE":
        if entry.before_material is None or entry.before_mode is None:
            raise ApplySessionError(
                "RESTORATION_MATERIAL_MISSING",
                "DELETE restoration material is unavailable.",
            )
        _atomic_create_file(
            root,
            entry,
            entry.before_material,
            entry.before_mode,
            atime_ns=entry.before_atime_ns,
            mtime_ns=entry.before_mtime_ns,
        )
    if not _entry_matches_before(root, entry):
        raise ApplySessionError(
            "COMPENSATION_INTEGRITY_FAILED",
            "Compensation did not restore the exact captured before state.",
        )


def _restore_entry_after(root: Path, entry: ApplySessionEntry) -> None:
    if _entry_matches_after(root, entry):
        return
    if not _entry_matches_before(root, entry):
        raise ApplySessionError(
            "REVERT_COMPENSATION_PRECONDITION_CONFLICT",
            "A reversed path matches neither the before nor applied state.",
        )
    if entry.operation == "CREATE":
        _create_recorded_parents(root, entry)
        if entry.after_material is None or entry.after_mode is None:
            raise ApplySessionError(
                "POSTIMAGE_MATERIAL_MISSING",
                "CREATE postimage material is unavailable.",
            )
        _atomic_create_file(
            root,
            entry,
            entry.after_material,
            entry.after_mode,
            atime_ns=entry.after_atime_ns,
            mtime_ns=entry.after_mtime_ns,
        )
    elif entry.operation == "MODIFY":
        if entry.after_material is None or entry.after_mode is None:
            raise ApplySessionError(
                "POSTIMAGE_MATERIAL_MISSING",
                "MODIFY postimage material is unavailable.",
            )
        _atomic_replace_file(
            root,
            entry,
            entry.after_material,
            entry.after_mode,
            atime_ns=entry.after_atime_ns,
            mtime_ns=entry.after_mtime_ns,
            expected="before",
        )
    elif entry.operation == "DELETE":
        _unlink_entry_file(root, entry, expected="before")
    if not _entry_matches_after(root, entry):
        raise ApplySessionError(
            "REVERT_COMPENSATION_INTEGRITY_FAILED",
            "Revert compensation did not restore the exact applied state.",
        )


def _owned_parent_expectations(
    entries: list[ApplySessionEntry],
) -> tuple[dict[str, dict[str, Any]], bool]:
    records: dict[str, dict[str, Any]] = {}
    duplicate = False
    for entry in entries:
        for record in _created_parent_records(entry):
            path = str(record["path"])
            if path in records:
                duplicate = True
            else:
                records[path] = record
    for path, record in records.items():
        allowed_children: set[str] = set()
        pure_parent = PurePosixPath(path)
        for entry in entries:
            if entry.operation != "CREATE":
                continue
            pure_target = PurePosixPath(entry.repository_path)
            if pure_target.parent == pure_parent:
                allowed_children.add(pure_target.name)
        for child_path in records:
            pure_child = PurePosixPath(child_path)
            if pure_child.parent == pure_parent:
                allowed_children.add(pure_child.name)
        record["allowed_children"] = sorted(allowed_children)
    return records, duplicate


def _owned_parent_state(
    root: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    try:
        directory_fd = _open_directory_at_root(root, str(record["path"]))
    except FileNotFoundError:
        return {
            "present": False,
            "path_identity": record["path_identity"],
        }
    except OSError:
        return {
            "present": True,
            "path_identity": record["path_identity"],
            "safe_directory": False,
        }
    try:
        item_stat = os.fstat(directory_fd)
        names = sorted(os.listdir(directory_fd))
        return {
            "present": True,
            "path_identity": record["path_identity"],
            "safe_directory": stat.S_ISDIR(item_stat.st_mode),
            "mode": item_stat.st_mode & 0o777,
            "device": item_stat.st_dev,
            "inode": item_stat.st_ino,
            "child_name_identities": [
                _sha256_bytes(name.encode("utf-8", errors="surrogateescape"))
                for name in names
            ],
            "unexpected_child_count": len(
                set(names) - set(record.get("allowed_children", []))
            ),
        }
    finally:
        os.close(directory_fd)


def _validate_revert_owned_parents(
    root: Path,
    entries: list[ApplySessionEntry],
    apply_session: ApplySession,
) -> None:
    records, duplicate = _owned_parent_expectations(entries)
    if duplicate:
        raise ApplySessionError(
            "CREATED_PARENT_CONFLICT",
            "A session-owned parent has conflicting journal ownership.",
        )
    applied_evidence = _decoded_object(apply_session.after_evidence_json)
    captured = {
        str(item.get("path_identity")): item
        for item in _decoded_list(applied_evidence.get("owned_parents"))
        if isinstance(item, dict)
    }
    for record in records.values():
        current = _owned_parent_state(root, record)
        prior = captured.get(str(record["path_identity"]))
        if (
            current.get("present") is not True
            or current.get("safe_directory") is not True
            or current.get("mode") != record["mode"]
            or prior is None
            or current.get("device") != prior.get("device")
            or current.get("inode") != prior.get("inode")
        ):
            raise ApplySessionError(
                "CREATED_PARENT_CONFLICT",
                "A parent created by Apply no longer has its exact identity.",
            )
        if current.get("unexpected_child_count") != 0:
            raise ApplySessionError(
                "CREATED_PARENT_NOT_EMPTY",
                "A parent created by Apply contains an unrelated path.",
            )


def _integrity_evidence(
    session: Session,
    *,
    run: CodexRun,
    apply_session: ApplySession,
    root: Path,
    expected: str,
    unrelated_baseline: dict[str, Any],
    preserve_unrelated: bool = True,
) -> tuple[bool, dict[str, Any]]:
    entries = apply_session_entries(session, apply_session)
    target_results: list[dict[str, Any]] = []
    all_match = True
    parent_records, duplicate_parent_ownership = _owned_parent_expectations(entries)
    parent_results: list[dict[str, Any]] = []
    if duplicate_parent_ownership:
        all_match = False
    for record in parent_records.values():
        parent_state = _owned_parent_state(root, record)
        if expected == "after":
            parent_matches = (
                parent_state.get("present") is True
                and parent_state.get("safe_directory") is True
                and parent_state.get("mode") == record["mode"]
                and parent_state.get("unexpected_child_count") == 0
            )
        else:
            parent_matches = parent_state.get("present") is False
        parent_state["expected_state"] = expected
        parent_state["matches"] = parent_matches
        parent_results.append(parent_state)
        all_match = all_match and parent_matches
    for entry in entries:
        matches = (
            _entry_matches_after(root, entry)
            if expected == "after"
            else _entry_matches_before(root, entry)
        )
        all_match = all_match and matches
        target_results.append(
            {
                "path_identity": entry.path_identity,
                "operation": entry.operation,
                "expected_state": expected,
                "matches": matches,
            }
        )
    current = _global_evidence_after_mutation(
        run,
        root,
        target_paths=[entry.repository_path for entry in entries],
        baseline=unrelated_baseline,
    )
    global_mismatches = _global_static_mismatches(
        unrelated_baseline,
        current,
        preserve_unrelated=preserve_unrelated,
    )
    all_match = all_match and not global_mismatches
    return all_match, {
        "schema": "twos.apply_integrity_evidence.v1",
        "expected_target_state": expected,
        "targets": target_results,
        "owned_parents": parent_results,
        "duplicate_parent_ownership": duplicate_parent_ownership,
        "global_mismatches": global_mismatches,
        "global": current,
        "post_apply_verification": False,
    }


def _compensate_apply(
    session: Session,
    *,
    run: CodexRun,
    apply_session: ApplySession,
    root: Path,
    attempted_entries: list[ApplySessionEntry],
    fault_injector: FaultInjector | None,
) -> bool:
    compensation: list[dict[str, Any]] = []
    success = True
    apply_session_id = apply_session.id
    for original_entry in reversed(attempted_entries):
        entry_id = original_entry.id
        try:
            if fault_injector is not None:
                fault_injector("before_apply_compensation", original_entry)
            _restore_entry_before(root, original_entry)
            compensation.append(
                {
                    "path_identity": original_entry.path_identity,
                    "result": "RESTORED",
                }
            )
        except BaseException as exc:
            success = False
            failure = _safe_failure(
                "APPLY_COMPENSATION_FAILED",
                phase="APPLY_COMPENSATION",
                entry=original_entry,
                exception=exc,
            )
            compensation.append(
                {
                    "path_identity": original_entry.path_identity,
                    "result": "FAILED",
                    "exception_type": type(exc).__name__,
                }
            )
            session.rollback()
            apply_session = session.get(ApplySession, apply_session_id)
            entry = session.get(ApplySessionEntry, entry_id)
            if apply_session is None or entry is None:
                continue
            entry.apply_result = "COMPENSATION_FAILED"
            entry.failure_evidence_json = canonical_json(
                _decoded_list(entry.failure_evidence_json) + [failure]
            )
            _append_audit(
                session,
                apply_session,
                phase="APPLY_COMPENSATION",
                event_type="ENTRY_RESTORE_FAILED",
                entry=entry,
                evidence=failure,
            )
            try:
                session.commit()
            except Exception:
                session.rollback()
            continue
        # Recording success is deliberately separate from the source restore.
        # A database failure cannot turn a successful filesystem compensation
        # into a reason to skip the remaining entries.
        session.rollback()
        apply_session = session.get(ApplySession, apply_session_id)
        entry = session.get(ApplySessionEntry, entry_id)
        if apply_session is None or entry is None:
            continue
        entry.apply_result = "COMPENSATED"
        _append_audit(
            session,
            apply_session,
            phase="APPLY_COMPENSATION",
            event_type="ENTRY_RESTORED",
            entry=entry,
        )
        try:
            session.commit()
        except Exception:
            session.rollback()
    session.rollback()
    apply_session = session.get(ApplySession, apply_session_id)
    if apply_session is None:
        raise ApplySessionError(
            "DURABLE_JOURNAL_UNAVAILABLE",
            "The durable Apply journal is unavailable after compensation.",
        )
    before = _decoded_object(apply_session.before_evidence_json)
    try:
        integrity_ok, integrity = _integrity_evidence(
            session,
            run=run,
            apply_session=apply_session,
            root=root,
            expected="before",
            unrelated_baseline=before,
            preserve_unrelated=False,
        )
    except BaseException as exc:
        integrity_ok = False
        integrity = {
            "schema": "twos.apply_integrity_evidence.v1",
            "expected_target_state": "before",
            "global_mismatches": ["EVIDENCE_UNAVAILABLE"],
            "exception_type": type(exc).__name__,
            "post_apply_verification": False,
        }
    success = success and integrity_ok
    apply_session.compensation_evidence_json = canonical_json(compensation)
    apply_session.after_evidence_json = canonical_json(integrity)
    apply_session.integrity_check_result = (
        "COMPENSATED" if success else "PARTIAL"
    )
    apply_session.state = (
        "APPLY_FAILED_RECOVERED" if success else "APPLY_FAILED_PARTIAL"
    )
    apply_session.finished_at = utc_now()
    _append_audit(
        session,
        apply_session,
        phase="APPLY_COMPENSATION",
        event_type=apply_session.state,
        evidence={"compensation_complete": success},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        apply_session = session.get(ApplySession, apply_session_id)
        if apply_session is None:
            raise
        apply_session.compensation_evidence_json = canonical_json(compensation)
        apply_session.after_evidence_json = canonical_json(integrity)
        apply_session.integrity_check_result = (
            "COMPENSATED" if success else "PARTIAL"
        )
        apply_session.state = (
            "APPLY_FAILED_RECOVERED"
            if success
            else "APPLY_FAILED_PARTIAL"
        )
        apply_session.finished_at = utc_now()
        _append_audit(
            session,
            apply_session,
            phase="APPLY_COMPENSATION",
            event_type=apply_session.state,
            evidence={
                "compensation_complete": success,
                "terminal_evidence_commit_retried": True,
            },
        )
        session.commit()
    return success


def _reconcile_apply_session_locked(
    session: Session,
    *,
    apply_session: ApplySession,
    source_repo: Path,
) -> ApplySession:
    if apply_session.state not in {"APPLYING", "REVERTING"}:
        return apply_session
    if not validate_apply_session_journal(session, apply_session):
        apply_session.state = (
            "APPLY_FAILED_PARTIAL"
            if apply_session.state == "APPLYING"
            else "REVERT_FAILED_PARTIAL"
        )
        apply_session.integrity_check_result = "JOURNAL_INVALID"
        failure = _safe_failure(
            "DURABLE_JOURNAL_INVALID",
            phase="RECONCILIATION",
        )
        apply_session.failure_evidence_json = canonical_json(
            _decoded_list(apply_session.failure_evidence_json) + [failure]
        )
        _append_audit(
            session,
            apply_session,
            phase="RECONCILIATION",
            event_type=apply_session.state,
            evidence=failure,
        )
        session.commit()
        return apply_session
    run = session.get(CodexRun, apply_session.run_id)
    if run is None:
        apply_session.state = (
            "APPLY_FAILED_PARTIAL"
            if apply_session.state == "APPLYING"
            else "REVERT_FAILED_PARTIAL"
        )
        apply_session.integrity_check_result = "EVIDENCE_UNAVAILABLE"
        failure = _safe_failure(
            "RUN_BINDING_UNAVAILABLE",
            phase="RECONCILIATION",
        )
        apply_session.failure_evidence_json = canonical_json(
            _decoded_list(apply_session.failure_evidence_json) + [failure]
        )
        _append_audit(
            session,
            apply_session,
            phase="RECONCILIATION",
            event_type=apply_session.state,
            evidence=failure,
        )
        session.commit()
        return apply_session
    try:
        root = _verified_repository_root(
            run,
            source_repo,
            expected_source_workspace_identity=(
                apply_session.source_workspace_identity
            ),
            expected_source_snapshot_identity=(
                apply_session.source_snapshot_identity
            ),
            require_strong_source_identity=bool(
                apply_session.result_envelope_id is not None
                or apply_session.result_digest
            ),
        )
        if (
            _sha256_bytes(str(root).encode("utf-8"))
            != apply_session.repository_locator_fingerprint
        ):
            raise ApplySessionError(
                "REPOSITORY_IDENTITY_MISMATCH",
                "The configured repository does not match the durable journal.",
            )
        baseline = (
            _decoded_object(apply_session.before_evidence_json)
            if apply_session.state == "APPLYING"
            else _decoded_object(apply_session.pre_revert_evidence_json)
        )
        expected_primary = "after" if apply_session.state == "APPLYING" else "before"
        primary_ok, primary = _integrity_evidence(
            session,
            run=run,
            apply_session=apply_session,
            root=root,
            expected=expected_primary,
            unrelated_baseline=baseline,
            preserve_unrelated=False,
        )
        if primary_ok:
            if apply_session.state == "APPLYING":
                apply_session.state = "APPLIED"
                apply_session.after_evidence_json = canonical_json(primary)
                apply_session.finished_at = utc_now()
            else:
                apply_session.state = "REVERTED"
                apply_session.post_revert_evidence_json = canonical_json(primary)
                apply_session.revert_finished_at = utc_now()
            apply_session.integrity_check_result = "PASSED"
        else:
            expected_recovered = (
                "before" if apply_session.state == "APPLYING" else "after"
            )
            recovered_ok, recovered = _integrity_evidence(
                session,
                run=run,
                apply_session=apply_session,
                root=root,
                expected=expected_recovered,
                unrelated_baseline=baseline,
                preserve_unrelated=False,
            )
            if apply_session.state == "APPLYING":
                apply_session.state = (
                    "APPLY_FAILED_RECOVERED"
                    if recovered_ok
                    else "APPLY_FAILED_PARTIAL"
                )
                apply_session.after_evidence_json = canonical_json(recovered)
                apply_session.finished_at = utc_now()
            else:
                apply_session.state = (
                    "REVERT_BLOCKED"
                    if recovered_ok
                    else "REVERT_FAILED_PARTIAL"
                )
                apply_session.post_revert_evidence_json = canonical_json(
                    recovered
                )
                apply_session.revert_finished_at = utc_now()
            apply_session.integrity_check_result = (
                "RECOVERED" if recovered_ok else "PARTIAL"
            )
    except Exception as exc:
        apply_session.state = (
            "APPLY_FAILED_PARTIAL"
            if apply_session.state == "APPLYING"
            else "REVERT_FAILED_PARTIAL"
        )
        apply_session.integrity_check_result = "EVIDENCE_UNAVAILABLE"
        failure = _safe_failure(
            "RECONCILIATION_EVIDENCE_UNAVAILABLE",
            phase="RECONCILIATION",
            exception=exc,
        )
        apply_session.failure_evidence_json = canonical_json(
            _decoded_list(apply_session.failure_evidence_json) + [failure]
        )
    _append_audit(
        session,
        apply_session,
        phase="RECONCILIATION",
        event_type=apply_session.state,
        evidence={"automatic_mutation": False},
    )
    session.commit()
    return apply_session


def reconcile_apply_session(
    session: Session,
    *,
    apply_session: ApplySession,
    source_repo: Path,
) -> ApplySession:
    with _repository_mutation_lock(
        apply_session.repository_locator_fingerprint
    ):
        return _reconcile_apply_session_locked(
            session,
            apply_session=apply_session,
            source_repo=source_repo,
        )


def _apply_accepted_changes_locked(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
    source_repo: Path,
    confirmed: bool,
    expected_plan_digest: str | None = None,
    expected_candidate_digest: str | None = None,
    expected_plan_approval_digest: str | None = None,
    expected_result_digest: str | None = None,
    expected_result_review_decision_digest: str | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[ApplySession, bool]:
    """Apply one exact immutable Plan after a separate explicit confirmation.

    The optional fault injector is an internal deterministic-test seam. It is
    never accepted from an HTTP client and receives no secret or absolute path.
    """
    if plan.owner_id != owner_id:
        raise ApplySessionError(
            "APPLY_PLAN_NOT_FOUND",
            "The Apply Plan is unavailable.",
        )
    if confirmed is not True:
        raise ApplySessionError(
            "APPLY_CONFIRMATION_REQUIRED",
            "Apply Accepted Changes requires a separate explicit Owner confirmation.",
        )
    if (
        expected_plan_digest is not None
        and expected_plan_digest != plan.plan_digest
    ):
        raise ApplySessionError(
            "EXPECTED_PLAN_DIGEST_MISMATCH",
            "The confirmed Apply Plan digest is stale.",
        )
    if (
        expected_candidate_digest is not None
        and expected_candidate_digest != plan.candidate_digest
    ):
        raise ApplySessionError(
            "EXPECTED_CANDIDATE_DIGEST_MISMATCH",
            "The confirmed Candidate digest is stale.",
        )
    approval = _required_plan_approval(
        session,
        owner_id=owner_id,
        plan=plan,
    )
    expected_lineage = (
        (
            expected_plan_approval_digest,
            approval.approval_digest if approval is not None else None,
            "EXPECTED_PLAN_APPROVAL_DIGEST_MISMATCH",
            "The confirmed Apply Plan approval digest is stale.",
        ),
        (
            expected_result_digest,
            plan.result_digest or None,
            "EXPECTED_RESULT_DIGEST_MISMATCH",
            "The confirmed Result digest is stale.",
        ),
        (
            expected_result_review_decision_digest,
            plan.result_review_decision_digest or None,
            "EXPECTED_RESULT_REVIEW_DIGEST_MISMATCH",
            "The confirmed Owner Result decision digest is stale.",
        ),
    )
    for expected, actual, code, message in expected_lineage:
        if expected is not None and expected != actual:
            raise ApplySessionError(code, message)
    existing = _owned_existing_for_plan(
        session,
        owner_id=owner_id,
        plan_id=plan.id,
    )
    if existing is not None:
        return existing, False
    if _repository_mutation_blocker(
        session,
        repository_locator_fingerprint=plan.repository_locator_fingerprint,
        exclude_plan_id=plan.id,
    ) is not None:
        raise ApplySessionError(
            "CONCURRENT_APPLY",
            "Another Apply or Revert session is active for this repository.",
        )

    candidate = (
        session.get(DeliveryCandidate, plan.delivery_candidate_id)
        if plan.delivery_candidate_id is not None
        else None
    )
    if candidate is None or candidate.owner_id != owner_id:
        raise ApplySessionError(
            "CANDIDATE_UNAVAILABLE",
            "The Plan-bound Candidate is unavailable.",
        )
    confirmation_digest = _confirmation_digest(plan, candidate, approval)
    plan_entries = _plan_entries(session, plan)
    try:
        (
            run,
            candidate,
            root,
            plan_entries,
            journal_material,
            before_evidence,
            drift_id,
        ) = _prepare_apply_journal(
            session,
            owner_id=owner_id,
            plan=plan,
            approval=approval,
            source_repo=source_repo,
        )
    except ApplySessionError as exc:
        # A failed fresh evaluation, when one was appended, is still durable
        # evidence. Otherwise bind the immutable Plan evaluation.
        latest_drift = session.scalar(
            select(SourceDriftEvaluation)
            .where(
                SourceDriftEvaluation.owner_id == owner_id,
                SourceDriftEvaluation.run_id == plan.run_id,
            )
            .order_by(SourceDriftEvaluation.id.desc())
        )
        latest_drift_id = (
            latest_drift.id
            if latest_drift is not None
            else plan.source_drift_evaluation_id
        )
        blocker_evidence = _decoded_object(exc.details).get(
            "preflight_observations", {}
        )
        if blocker_evidence:
            blocker_evidence = {"preflight_observations": blocker_evidence}
        blocked, created = _persist_blocked_session(
            session,
            plan=plan,
            candidate=candidate,
            approval=approval,
            plan_entries=plan_entries,
            confirmation_digest=confirmation_digest,
            drift_id=latest_drift_id,
            before_evidence=blocker_evidence,
            failure=_safe_failure(
                exc.code,
                phase="PREFLIGHT",
                exception=exc,
                details=exc.details,
                message=exc.message,
            ),
        )
        return blocked, created

    try:
        applying, created = _persist_applying_session(
            session,
            plan=plan,
            candidate=candidate,
            approval=approval,
            drift_id=drift_id,
            before_evidence=before_evidence,
            confirmation_digest=confirmation_digest,
            plan_entries=plan_entries,
            journal_material=journal_material,
        )
    except ApplySessionError as exc:
        if exc.code == "CONCURRENT_APPLY":
            raise
        blocked, blocked_created = _persist_blocked_session(
            session,
            plan=plan,
            candidate=candidate,
            approval=approval,
            plan_entries=plan_entries,
            confirmation_digest=confirmation_digest,
            drift_id=plan.source_drift_evaluation_id,
            before_evidence=before_evidence,
            failure=_safe_failure(
                exc.code,
                phase="PREFLIGHT",
                exception=exc,
            ),
        )
        return blocked, blocked_created
    if not created:
        return applying, False

    applying_id = applying.id
    session.expire_all()
    durable_applying = session.get(ApplySession, applying_id)
    if durable_applying is None or not validate_apply_session_journal(
        session,
        durable_applying,
    ):
        if durable_applying is None:
            raise ApplySessionError(
                "DURABLE_JOURNAL_UNAVAILABLE",
                "The durable Apply journal could not be reloaded.",
            )
        durable_applying.state = "PREFLIGHT_BLOCKED"
        durable_applying.integrity_check_result = "JOURNAL_INVALID"
        durable_applying.finished_at = utc_now()
        failure = _safe_failure(
            "DURABLE_JOURNAL_INVALID",
            phase="PREFLIGHT",
        )
        durable_applying.failure_evidence_json = canonical_json([failure])
        _append_audit(
            session,
            durable_applying,
            phase="PREFLIGHT",
            event_type="PREFLIGHT_BLOCKED",
            evidence=failure,
        )
        session.commit()
        return durable_applying, True
    applying = durable_applying
    entries = apply_session_entries(session, applying)
    attempted: list[ApplySessionEntry] = []
    try:
        immediate_evidence = _global_evidence(
            run,
            root,
            target_paths=[entry.repository_path for entry in entries],
        )
        persisted_before = _decoded_object(applying.before_evidence_json)
        comparison_before = _decoded_object(
            persisted_before.get("preflight_observations")
        ).get("observation_b")
        if not isinstance(comparison_before, dict):
            comparison_before = persisted_before
        immediate_difference = semantic_diff(comparison_before, immediate_evidence)
        if immediate_difference.changed:
            applying.state = "PREFLIGHT_BLOCKED"
            applying.integrity_check_result = "BLOCKED"
            applying.finished_at = utc_now()
            failure = _safe_failure(
                "REPOSITORY_CHANGED_BEFORE_MUTATION",
                phase="PREFLIGHT",
                details=immediate_difference.as_dict(),
            )
            applying.failure_evidence_json = canonical_json([failure])
            _append_audit(
                session,
                applying,
                phase="PREFLIGHT",
                event_type="PREFLIGHT_BLOCKED",
                evidence=failure,
            )
            session.commit()
            return applying, True
        for entry in entries:
            attempted.append(entry)
            if fault_injector is not None:
                fault_injector("before_apply_operation", entry)
            _apply_entry(root, entry)
            if fault_injector is not None:
                fault_injector("after_apply_operation", entry)
            entry.apply_result = "APPLIED"
            entry.applied_at = utc_now()
            _append_audit(
                session,
                applying,
                phase="APPLY",
                event_type="ENTRY_APPLIED",
                entry=entry,
                evidence={"operation_ordinal": entry.operation_ordinal},
            )
            session.commit()
        integrity_ok, integrity = _integrity_evidence(
            session,
            run=run,
            apply_session=applying,
            root=root,
            expected="after",
            unrelated_baseline=before_evidence,
        )
        if not integrity_ok:
            raise ApplySessionError(
                "NARROW_APPLY_INTEGRITY_FAILED",
                "The narrow Apply integrity check failed.",
            )
        applying.state = "APPLIED"
        applying.integrity_check_result = "PASSED"
        applying.after_evidence_json = canonical_json(integrity)
        applying.finished_at = utc_now()
        _append_audit(
            session,
            applying,
            phase="APPLY_INTEGRITY",
            event_type="APPLIED",
            evidence={
                "narrow_integrity_check": "PASSED",
                "post_apply_verification": False,
            },
        )
        session.commit()
        return applying, True
    except Exception as exc:
        applying_id = applying.id
        attempted_entry_ids = [entry.id for entry in attempted]
        failed_entry_id = attempted[-1].id if attempted else None
        failure = _safe_failure(
            exc.code if isinstance(exc, ApplySessionError) else "APPLY_OPERATION_FAILED",
            phase="APPLY",
            entry=attempted[-1] if attempted else None,
            exception=exc,
        )
        # A database write may itself be the failure that brought us here.
        # Clear SQLAlchemy's failed transaction before any recovery work, then
        # reload durable rows. Filesystem compensation must never depend on
        # successfully recording the failure evidence first.
        session.rollback()
        applying = session.get(ApplySession, applying_id)
        if applying is None:
            raise ApplySessionError(
                "DURABLE_JOURNAL_UNAVAILABLE",
                "The durable Apply journal could not be reloaded for recovery.",
            ) from exc
        attempted_by_id = {
            row.id: row
            for row in session.scalars(
                select(ApplySessionEntry).where(
                    ApplySessionEntry.id.in_(attempted_entry_ids)
                )
            ).all()
        }
        attempted = [
            attempted_by_id[entry_id]
            for entry_id in attempted_entry_ids
            if entry_id in attempted_by_id
        ]
        try:
            failed_entry = (
                session.get(ApplySessionEntry, failed_entry_id)
                if failed_entry_id is not None
                else None
            )
            applying.failure_evidence_json = canonical_json(
                _decoded_list(applying.failure_evidence_json) + [failure]
            )
            _append_audit(
                session,
                applying,
                phase="APPLY",
                event_type="APPLY_FAILED",
                entry=failed_entry,
                evidence=failure,
            )
            session.commit()
        except Exception:
            session.rollback()
            applying = session.get(ApplySession, applying_id)
            if applying is None:
                raise ApplySessionError(
                    "DURABLE_JOURNAL_UNAVAILABLE",
                    "The durable Apply journal could not be reloaded for recovery.",
                ) from exc
            attempted_by_id = {
                row.id: row
                for row in session.scalars(
                    select(ApplySessionEntry).where(
                        ApplySessionEntry.id.in_(attempted_entry_ids)
                    )
                ).all()
            }
            attempted = [
                attempted_by_id[entry_id]
                for entry_id in attempted_entry_ids
                if entry_id in attempted_by_id
            ]
        _compensate_apply(
            session,
            run=run,
            apply_session=applying,
            root=root,
            attempted_entries=attempted,
            fault_injector=fault_injector,
        )
        reloaded = session.get(ApplySession, applying_id)
        return (reloaded if reloaded is not None else applying), True


def apply_accepted_changes(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
    source_repo: Path,
    confirmed: bool,
    expected_plan_digest: str | None = None,
    expected_candidate_digest: str | None = None,
    expected_plan_approval_digest: str | None = None,
    expected_result_digest: str | None = None,
    expected_result_review_decision_digest: str | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[ApplySession, bool]:
    try:
        with _repository_mutation_lock(plan.repository_locator_fingerprint):
            return _apply_accepted_changes_locked(
                session,
                owner_id=owner_id,
                plan=plan,
                source_repo=source_repo,
                confirmed=confirmed,
                expected_plan_digest=expected_plan_digest,
                expected_candidate_digest=expected_candidate_digest,
                expected_plan_approval_digest=expected_plan_approval_digest,
                expected_result_digest=expected_result_digest,
                expected_result_review_decision_digest=(
                    expected_result_review_decision_digest
                ),
                fault_injector=fault_injector,
            )
    except ApplySessionError as exc:
        if exc.code != "CONCURRENT_APPLY":
            raise
        session.rollback()
        existing = _owned_existing_for_plan(
            session,
            owner_id=owner_id,
            plan_id=plan.id,
        )
        if existing is not None:
            return existing, False
        raise


def reconcile_incomplete_apply_sessions(
    session: Session,
    *,
    source_repo: Path,
) -> list[ApplySession]:
    """Reconcile crash-interrupted sessions without replaying a mutation.

    This is intended for runtime startup, before requests are served. Duplicate
    in-flight HTTP requests simply return the durable APPLYING/REVERTING row and
    never race a live executor.
    """
    rows = list(
        session.scalars(
            select(ApplySession)
            .where(ApplySession.state.in_({"APPLYING", "REVERTING"}))
            .order_by(ApplySession.id)
        ).all()
    )
    reconciled: list[ApplySession] = []
    for row in rows:
        try:
            reconciled.append(
                reconcile_apply_session(
                    session,
                    apply_session=row,
                    source_repo=source_repo,
                )
            )
        except ApplySessionError as exc:
            if exc.code != "CONCURRENT_APPLY":
                raise
            session.rollback()
            reloaded = session.get(ApplySession, row.id)
            if reloaded is not None:
                reconciled.append(reloaded)
    return reconciled


def _revert_entry(root: Path, entry: ApplySessionEntry) -> None:
    if not _entry_matches_after(root, entry):
        raise ApplySessionError(
            "REVERT_PRECONDITION_CONFLICT",
            "An applied path no longer matches the exact session after-state.",
        )
    if entry.operation == "CREATE":
        _unlink_entry_file(root, entry, expected="after")
        _remove_recorded_empty_parents(root, entry)
    elif entry.operation == "MODIFY":
        if entry.before_material is None or entry.before_mode is None:
            raise ApplySessionError(
                "RESTORATION_MATERIAL_MISSING",
                "MODIFY reverse material is unavailable.",
            )
        _atomic_replace_file(
            root,
            entry,
            entry.before_material,
            entry.before_mode,
            atime_ns=entry.before_atime_ns,
            mtime_ns=entry.before_mtime_ns,
            expected="after",
        )
    elif entry.operation == "DELETE":
        if entry.before_material is None or entry.before_mode is None:
            raise ApplySessionError(
                "RESTORATION_MATERIAL_MISSING",
                "DELETE reverse material is unavailable.",
            )
        _atomic_create_file(
            root,
            entry,
            entry.before_material,
            entry.before_mode,
            atime_ns=entry.before_atime_ns,
            mtime_ns=entry.before_mtime_ns,
        )
    else:
        raise ApplySessionError(
            "UNSUPPORTED_OPERATION",
            "The Revert operation is unsupported.",
        )
    if not _entry_matches_before(root, entry):
        raise ApplySessionError(
            "REVERT_INTEGRITY_FAILED",
            "A reverse operation did not restore its exact captured before state.",
        )


def _compensate_revert(
    session: Session,
    *,
    run: CodexRun,
    apply_session: ApplySession,
    root: Path,
    attempted_entries: list[ApplySessionEntry],
    fault_injector: FaultInjector | None,
) -> bool:
    compensation: list[dict[str, Any]] = []
    success = True
    apply_session_id = apply_session.id
    for original_entry in reversed(attempted_entries):
        entry_id = original_entry.id
        try:
            if fault_injector is not None:
                fault_injector("before_revert_compensation", original_entry)
            _restore_entry_after(root, original_entry)
            compensation.append(
                {
                    "path_identity": original_entry.path_identity,
                    "result": "APPLIED_STATE_RESTORED",
                }
            )
        except Exception as exc:
            success = False
            failure = _safe_failure(
                "REVERT_COMPENSATION_FAILED",
                phase="REVERT_COMPENSATION",
                entry=original_entry,
                exception=exc,
            )
            compensation.append(
                {
                    "path_identity": original_entry.path_identity,
                    "result": "FAILED",
                    "exception_type": type(exc).__name__,
                }
            )
            session.rollback()
            apply_session = session.get(ApplySession, apply_session_id)
            entry = session.get(ApplySessionEntry, entry_id)
            if apply_session is None or entry is None:
                continue
            entry.revert_result = "COMPENSATION_FAILED"
            entry.failure_evidence_json = canonical_json(
                _decoded_list(entry.failure_evidence_json) + [failure]
            )
            _append_audit(
                session,
                apply_session,
                phase="REVERT_COMPENSATION",
                event_type="ENTRY_APPLIED_STATE_RESTORE_FAILED",
                entry=entry,
                evidence=failure,
            )
            try:
                session.commit()
            except Exception:
                session.rollback()
            continue
        session.rollback()
        apply_session = session.get(ApplySession, apply_session_id)
        entry = session.get(ApplySessionEntry, entry_id)
        if apply_session is None or entry is None:
            continue
        entry.revert_result = "COMPENSATED_TO_APPLIED"
        _append_audit(
            session,
            apply_session,
            phase="REVERT_COMPENSATION",
            event_type="ENTRY_APPLIED_STATE_RESTORED",
            entry=entry,
        )
        try:
            session.commit()
        except Exception:
            session.rollback()
    session.rollback()
    apply_session = session.get(ApplySession, apply_session_id)
    if apply_session is None:
        raise ApplySessionError(
            "DURABLE_JOURNAL_UNAVAILABLE",
            "The durable Revert journal is unavailable after compensation.",
        )
    baseline = _decoded_object(apply_session.pre_revert_evidence_json)
    try:
        integrity_ok, integrity = _integrity_evidence(
            session,
            run=run,
            apply_session=apply_session,
            root=root,
            expected="after",
            unrelated_baseline=baseline,
            preserve_unrelated=False,
        )
    except Exception as exc:
        integrity_ok = False
        integrity = {
            "schema": "twos.apply_integrity_evidence.v1",
            "expected_target_state": "after",
            "global_mismatches": ["EVIDENCE_UNAVAILABLE"],
            "exception_type": type(exc).__name__,
            "post_apply_verification": False,
        }
    success = success and integrity_ok
    apply_session.compensation_evidence_json = canonical_json(
        _decoded_list(apply_session.compensation_evidence_json) + compensation
    )
    apply_session.post_revert_evidence_json = canonical_json(integrity)
    apply_session.integrity_check_result = (
        "REVERT_COMPENSATED" if success else "REVERT_PARTIAL"
    )
    apply_session.state = "REVERT_BLOCKED" if success else "REVERT_FAILED_PARTIAL"
    apply_session.revert_finished_at = utc_now()
    _append_audit(
        session,
        apply_session,
        phase="REVERT_COMPENSATION",
        event_type=apply_session.state,
        evidence={"compensation_complete": success},
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        apply_session = session.get(ApplySession, apply_session_id)
        if apply_session is None:
            raise
        apply_session.compensation_evidence_json = canonical_json(
            _decoded_list(apply_session.compensation_evidence_json) + compensation
        )
        apply_session.post_revert_evidence_json = canonical_json(integrity)
        apply_session.integrity_check_result = (
            "REVERT_COMPENSATED" if success else "REVERT_PARTIAL"
        )
        apply_session.state = (
            "REVERT_BLOCKED" if success else "REVERT_FAILED_PARTIAL"
        )
        apply_session.revert_finished_at = utc_now()
        _append_audit(
            session,
            apply_session,
            phase="REVERT_COMPENSATION",
            event_type=apply_session.state,
            evidence={
                "compensation_complete": success,
                "terminal_evidence_commit_retried": True,
            },
        )
        session.commit()
    return success


def _block_revert(
    session: Session,
    *,
    apply_session: ApplySession,
    failure: dict[str, Any],
) -> ApplySession:
    apply_session.state = "REVERT_BLOCKED"
    apply_session.integrity_check_result = "REVERT_BLOCKED"
    apply_session.failure_evidence_json = canonical_json(
        _decoded_list(apply_session.failure_evidence_json) + [failure]
    )
    apply_session.revert_finished_at = utc_now()
    _append_audit(
        session,
        apply_session,
        phase="REVERT_PREFLIGHT",
        event_type="REVERT_BLOCKED",
        evidence=failure,
    )
    session.commit()
    return apply_session


def _revert_applied_changes_locked(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
    source_repo: Path,
    confirmed: bool,
    expected_journal_digest: str | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[ApplySession, bool]:
    requested_session_id = apply_session.id
    session.expire_all()
    apply_session = session.scalar(
        select(ApplySession).where(
            ApplySession.id == requested_session_id,
            ApplySession.owner_id == owner_id,
        )
    )
    if apply_session is None:
        raise ApplySessionError(
            "APPLY_SESSION_NOT_FOUND",
            "The Apply session is unavailable.",
        )
    repository_blocker = _repository_mutation_blocker(
        session,
        repository_locator_fingerprint=(
            apply_session.repository_locator_fingerprint
        ),
    )
    if (
        repository_blocker is not None
        and repository_blocker.id != apply_session.id
    ):
        raise ApplySessionError(
            "CONCURRENT_APPLY",
            "Another Apply or Revert session is active for this repository.",
        )
    if confirmed is not True:
        raise ApplySessionError(
            "REVERT_CONFIRMATION_REQUIRED",
            "Revert Applied Changes requires a separate explicit Owner confirmation.",
        )
    if (
        expected_journal_digest is not None
        and expected_journal_digest != apply_session.journal_digest
    ):
        raise ApplySessionError(
            "EXPECTED_JOURNAL_DIGEST_MISMATCH",
            "The confirmed Apply journal digest is stale.",
        )
    if apply_session.state == "REVERTED":
        return apply_session, False
    if apply_session.state in {
        "REVERTING",
        "REVERT_BLOCKED",
        "REVERT_FAILED_PARTIAL",
    }:
        return apply_session, False
    if apply_session.state != "APPLIED":
        raise ApplySessionError(
            "REVERT_NOT_AVAILABLE",
            "Only one exact successful Apply session may be reverted.",
        )
    run = session.get(CodexRun, apply_session.run_id)
    plan = session.get(ApplyPlan, apply_session.apply_plan_id)
    candidate = session.get(
        DeliveryCandidate,
        apply_session.delivery_candidate_id,
    )
    if (
        run is None
        or plan is None
        or candidate is None
        or plan.owner_id != owner_id
        or candidate.owner_id != owner_id
        or plan.plan_digest != apply_session.apply_plan_digest
        or candidate.candidate_digest != apply_session.candidate_digest
    ):
        return (
            _block_revert(
                session,
                apply_session=apply_session,
                failure=_safe_failure(
                    "REVERT_BINDING_INVALID",
                    phase="REVERT_PREFLIGHT",
                ),
            ),
            True,
        )
    try:
        if not validate_apply_session_journal(session, apply_session):
            raise ApplySessionError(
                "DURABLE_JOURNAL_INVALID",
                "The immutable Apply journal failed its integrity check.",
            )
        root = _verified_repository_root(
            run,
            source_repo,
            expected_source_workspace_identity=(
                apply_session.source_workspace_identity
            ),
            expected_source_snapshot_identity=(
                apply_session.source_snapshot_identity
            ),
            require_strong_source_identity=bool(
                apply_session.result_envelope_id is not None
                or apply_session.result_digest
            ),
        )
        entries = apply_session_entries(session, apply_session)
        if len(entries) != apply_session.included_path_count or not entries:
            raise ApplySessionError(
                "REVERSE_EVIDENCE_INCOMPLETE",
                "The exact reverse-entry journal is incomplete.",
            )
        _validate_revert_owned_parents(root, entries, apply_session)
        for entry in entries:
            if (
                not SHA256_PATTERN.fullmatch(entry.path_identity or "")
                or entry.operation not in {"CREATE", "MODIFY", "DELETE"}
                or entry.reverse_operation != _reverse_operation(entry.operation)
                or (entry.before_present and entry.before_material is None)
                or (entry.after_present and entry.after_material is None)
                or not _entry_matches_after(root, entry)
            ):
                raise ApplySessionError(
                    "REVERT_PRECONDITION_CONFLICT",
                    "An applied path changed or reverse evidence is incomplete.",
                )
        pre_revert_first = _global_evidence(
            run,
            root,
            target_paths=[entry.repository_path for entry in entries],
        )
        original_before = _decoded_object(apply_session.before_evidence_json)
        static_mismatches = _global_static_mismatches(
            original_before,
            pre_revert_first,
            preserve_unrelated=False,
            metadata_is_semantic=True,
        )
        if static_mismatches:
            raise ApplySessionError(
                static_mismatches[0],
                "The repository, branch, HEAD, index, refs, or remote boundary changed.",
            )
        index = _decoded_object(pre_revert_first.get("index"))
        if index.get("staged_path_count") != 0:
            raise ApplySessionError(
                "STAGED_PATHS_PRESENT",
                "Revert requires an index with zero staged paths.",
            )
        if pre_revert_first.get("branch") != "main":
            raise ApplySessionError(
                "WRONG_BRANCH",
                "Revert is permitted only on branch main.",
            )
        pre_revert = _global_evidence(
            run,
            root,
            target_paths=[entry.repository_path for entry in entries],
        )
        if canonical_json(pre_revert_first) != canonical_json(pre_revert):
            raise ApplySessionError(
                "REPOSITORY_CHANGED_DURING_REVERT_PREFLIGHT",
                "Repository evidence changed during Revert preflight.",
            )
    except Exception as exc:
        return (
            _block_revert(
                session,
                apply_session=apply_session,
                failure=_safe_failure(
                    (
                        exc.code
                        if isinstance(exc, ApplySessionError)
                        else "REVERT_PREFLIGHT_FAILED"
                    ),
                    phase="REVERT_PREFLIGHT",
                    exception=exc,
                ),
            ),
            True,
        )

    revert_confirmation_digest = _revert_confirmation_digest(apply_session)
    revert_started_at = utc_now()
    claim = session.execute(
        update(ApplySession)
        .where(
            ApplySession.id == apply_session.id,
            ApplySession.owner_id == owner_id,
            ApplySession.state == "APPLIED",
        )
        .values(
            state="REVERTING",
            revert_confirmation_digest=revert_confirmation_digest,
            pre_revert_evidence_json=canonical_json(pre_revert),
            revert_started_at=revert_started_at,
            integrity_check_result="REVERT_NOT_RUN",
        )
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        session.rollback()
        reloaded = session.scalar(
            select(ApplySession).where(
                ApplySession.id == requested_session_id,
                ApplySession.owner_id == owner_id,
            )
        )
        if reloaded is None:
            raise ApplySessionError(
                "APPLY_SESSION_NOT_FOUND",
                "The Apply session is unavailable.",
            )
        if reloaded.state in {
            "REVERTING",
            "REVERTED",
            "REVERT_BLOCKED",
            "REVERT_FAILED_PARTIAL",
        }:
            return reloaded, False
        raise ApplySessionError(
            "REVERT_NOT_AVAILABLE",
            "Only one exact successful Apply session may be reverted.",
        )
    session.expire_all()
    apply_session = session.get(ApplySession, requested_session_id)
    if apply_session is None:
        session.rollback()
        raise ApplySessionError(
            "APPLY_SESSION_NOT_FOUND",
            "The Apply session is unavailable.",
        )
    _append_audit(
        session,
        apply_session,
        phase="REVERT",
        event_type="REVERSE_JOURNAL_CONFIRMED",
        evidence={
            "path_count": len(entries),
            "all_path_preflight": "PASSED",
            "separate_owner_confirmation": True,
        },
    )
    # As with Apply, no reverse mutation begins before this claim is durable.
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        reloaded = session.get(ApplySession, apply_session.id)
        if reloaded is None:
            raise ApplySessionError(
                "APPLY_SESSION_NOT_FOUND",
                "The Apply session is unavailable.",
            )
        if reloaded.state != "APPLIED":
            return reloaded, False
        raise ApplySessionError(
            "REVERT_CLAIM_UNAVAILABLE",
            "The durable Revert claim could not be recorded.",
        ) from exc

    attempted: list[ApplySessionEntry] = []
    try:
        immediate = _global_evidence(
            run,
            root,
            target_paths=[entry.repository_path for entry in entries],
        )
        if canonical_json(immediate) != apply_session.pre_revert_evidence_json:
            return (
                _block_revert(
                    session,
                    apply_session=apply_session,
                    failure=_safe_failure(
                        "REPOSITORY_CHANGED_BEFORE_REVERT_MUTATION",
                        phase="REVERT_PREFLIGHT",
                    ),
                ),
                True,
            )
        for entry in reversed(entries):
            attempted.append(entry)
            if fault_injector is not None:
                fault_injector("before_revert_operation", entry)
            _revert_entry(root, entry)
            if fault_injector is not None:
                fault_injector("after_revert_operation", entry)
            entry.revert_result = "REVERTED"
            entry.reverted_at = utc_now()
            _append_audit(
                session,
                apply_session,
                phase="REVERT",
                event_type="ENTRY_REVERTED",
                entry=entry,
                evidence={"reverse_operation": entry.reverse_operation},
            )
            session.commit()
        integrity_ok, integrity = _integrity_evidence(
            session,
            run=run,
            apply_session=apply_session,
            root=root,
            expected="before",
            unrelated_baseline=pre_revert,
        )
        if not integrity_ok:
            raise ApplySessionError(
                "NARROW_REVERT_INTEGRITY_FAILED",
                "The narrow Revert integrity check failed.",
            )
        apply_session.state = "REVERTED"
        apply_session.integrity_check_result = "REVERT_PASSED"
        apply_session.post_revert_evidence_json = canonical_json(integrity)
        apply_session.revert_finished_at = utc_now()
        _append_audit(
            session,
            apply_session,
            phase="REVERT_INTEGRITY",
            event_type="REVERTED",
            evidence={
                "narrow_integrity_check": "PASSED",
                "post_apply_verification": False,
            },
        )
        session.commit()
        return apply_session, True
    except Exception as exc:
        apply_session_id = apply_session.id
        attempted_entry_ids = [entry.id for entry in attempted]
        failed_entry_id = attempted[-1].id if attempted else None
        failure = _safe_failure(
            (
                exc.code
                if isinstance(exc, ApplySessionError)
                else "REVERT_OPERATION_FAILED"
            ),
            phase="REVERT",
            entry=attempted[-1] if attempted else None,
            exception=exc,
        )
        session.rollback()
        apply_session = session.get(ApplySession, apply_session_id)
        if apply_session is None:
            raise ApplySessionError(
                "DURABLE_JOURNAL_UNAVAILABLE",
                "The durable Revert journal could not be reloaded for recovery.",
            ) from exc
        attempted_by_id = {
            row.id: row
            for row in session.scalars(
                select(ApplySessionEntry).where(
                    ApplySessionEntry.id.in_(attempted_entry_ids)
                )
            ).all()
        }
        attempted = [
            attempted_by_id[entry_id]
            for entry_id in attempted_entry_ids
            if entry_id in attempted_by_id
        ]
        try:
            failed_entry = (
                session.get(ApplySessionEntry, failed_entry_id)
                if failed_entry_id is not None
                else None
            )
            apply_session.failure_evidence_json = canonical_json(
                _decoded_list(apply_session.failure_evidence_json) + [failure]
            )
            _append_audit(
                session,
                apply_session,
                phase="REVERT",
                event_type="REVERT_FAILED",
                entry=failed_entry,
                evidence=failure,
            )
            session.commit()
        except Exception:
            session.rollback()
            apply_session = session.get(ApplySession, apply_session_id)
            if apply_session is None:
                raise ApplySessionError(
                    "DURABLE_JOURNAL_UNAVAILABLE",
                    "The durable Revert journal could not be reloaded for recovery.",
                ) from exc
            attempted_by_id = {
                row.id: row
                for row in session.scalars(
                    select(ApplySessionEntry).where(
                        ApplySessionEntry.id.in_(attempted_entry_ids)
                    )
                ).all()
            }
            attempted = [
                attempted_by_id[entry_id]
                for entry_id in attempted_entry_ids
                if entry_id in attempted_by_id
            ]
        _compensate_revert(
            session,
            run=run,
            apply_session=apply_session,
            root=root,
            attempted_entries=attempted,
            fault_injector=fault_injector,
        )
        reloaded = session.get(ApplySession, apply_session_id)
        return (reloaded if reloaded is not None else apply_session), True


def revert_applied_changes(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
    source_repo: Path,
    confirmed: bool,
    expected_journal_digest: str | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[ApplySession, bool]:
    fingerprint = apply_session.repository_locator_fingerprint
    try:
        with _repository_mutation_lock(fingerprint):
            return _revert_applied_changes_locked(
                session,
                owner_id=owner_id,
                apply_session=apply_session,
                source_repo=source_repo,
                confirmed=confirmed,
                expected_journal_digest=expected_journal_digest,
                fault_injector=fault_injector,
            )
    except ApplySessionError as exc:
        if exc.code != "CONCURRENT_APPLY":
            raise
        session.rollback()
        reloaded = session.scalar(
            select(ApplySession).where(
                ApplySession.id == apply_session.id,
                ApplySession.owner_id == owner_id,
            )
        )
        if reloaded is not None:
            return reloaded, False
        raise


def apply_confirmation_out(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
    source_repo: Path,
) -> dict[str, Any]:
    if plan.owner_id != owner_id:
        raise ApplySessionError(
            "APPLY_PLAN_NOT_FOUND",
            "The Apply Plan is unavailable.",
        )
    candidate = (
        session.get(DeliveryCandidate, plan.delivery_candidate_id)
        if plan.delivery_candidate_id is not None
        else None
    )
    run = session.get(CodexRun, plan.run_id)
    if candidate is None or run is None or candidate.owner_id != owner_id:
        raise ApplySessionError(
            "CANDIDATE_UNAVAILABLE",
            "The Plan-bound Candidate is unavailable.",
        )
    approval = (
        get_apply_plan_approval(session, owner_id=owner_id, plan=plan)
        if _plan_has_result_lineage(plan)
        else None
    )
    approval_valid = bool(
        approval is not None
        and validate_apply_plan_approval(
            session,
            approval,
            plan=plan,
            owner_id=owner_id,
        )
    )
    observation: dict[str, Any] | None = None
    preview_before: dict[str, Any] = {}
    preview_drift_id: int | None = None
    blockers: list[dict[str, str]] = []
    try:
        root = _verified_repository_root(
            run,
            source_repo,
            expected_source_workspace_identity=plan.source_workspace_identity,
            expected_source_snapshot_identity=plan.source_snapshot_identity,
            require_strong_source_identity=_plan_has_result_lineage(plan),
        )
        with _repository_mutation_lock(plan.repository_locator_fingerprint):
            observation = observe_repository(run, root)
            effective_state, state_blockers = effective_apply_plan_state(
                session,
                plan,
                source_repo=root,
                repository_observation=observation,
            )
        if effective_state not in APPLY_ELIGIBLE_PLAN_STATES:
            blockers = state_blockers or [
                {
                    "code": "PLAN_NOT_APPLY_READY",
                    "message": "The immutable Apply Plan is not current and Apply-ready.",
                }
            ]
    except ApplySessionError as exc:
        effective_state = "expired"
        blockers = [{"code": exc.code, "message": exc.message}]
        try:
            observation = observe_repository(run, source_repo)
        except Exception:
            observation = None
    rows = _plan_entries(session, plan)
    included = [row for row in rows if row.disposition == "INCLUDED"]
    excluded = [row for row in rows if row.disposition == "EXCLUDED"]
    blocked = [row for row in rows if row.disposition == "BLOCKED"]
    operations = {
        operation: sum(1 for row in included if row.operation == operation)
        for operation in ("CREATE", "MODIFY", "DELETE")
    }
    scope = _decoded_list(plan.scope_findings_json)
    staged_count = (
        int(observation["staged_path_count"])
        if observation is not None
        else plan.staged_path_count
    )
    return {
        "action": "Apply Accepted Changes",
        "explicit_confirmation_required": True,
        "preselected_confirmation": False,
        "first_source_mutation_warning": (
            "Apply Accepted Changes is the first action in this workflow that "
            "modifies the real source repository."
        ),
        "eligible": (
            not blockers
            and
            effective_state in APPLY_ELIGIBLE_PLAN_STATES
            and not blocked
            and bool(included)
            and staged_count == 0
        ),
        "apply_plan": {
            "id": plan.plan_id,
            "digest": plan.plan_digest,
            "version": plan.plan_version,
        },
        "expected_plan_digest": plan.plan_digest,
        "expected_candidate_digest": candidate.candidate_digest,
        "expected_plan_approval_digest": (
            approval.approval_digest if approval_valid and approval else None
        ),
        "expected_result_digest": plan.result_digest or None,
        "expected_result_review_decision_digest": (
            plan.result_review_decision_digest or None
        ),
        "approval_required": _plan_has_result_lineage(plan),
        "approval_state": (
            "APPROVED"
            if approval_valid
            else "INVALID"
            if approval is not None
            else "PENDING"
            if _plan_has_result_lineage(plan)
            else "LEGACY_CONFIRMATION_ONLY"
        ),
        "apply_plan_approval": (
            {
                "id": approval.approval_id,
                "approved_at": approval.approved_at.isoformat() + "Z",
            }
            if approval_valid and approval is not None
            else None
        ),
        "candidate": {
            "id": candidate.candidate_id,
            "digest": candidate.candidate_digest,
        },
        "drift_state": plan.source_drift_state,
        "fresh_drift_evaluation_id": preview_drift_id,
        "plan_state": effective_state,
        "included_files": [
            {
                "path": row.display_path,
                "operation": row.operation,
            }
            for row in included
        ],
        "excluded_files": [
            {
                "path": row.display_path,
                "operation": row.operation,
                "reason": row.reason,
            }
            for row in excluded
        ],
        "blocked_files": [
            {
                "path": row.display_path,
                "operation": row.operation,
                "reason": row.reason,
            }
            for row in blocked
        ],
        "operation_counts": operations,
        "unrelated_source_changes": scope,
        "index_boundary": {
            "staged_path_count": staged_count,
            "requires_zero_staged_paths": True,
            "index_will_change": False,
        },
        "boundaries": [
            "Apply changes only INCLUDED paths.",
            "EXCLUDED and unrelated paths remain untouched.",
            "No Stage, Commit, or Push occurs.",
            "Complete rollback evidence is durable before the first source mutation.",
        ],
        "blockers": blockers,
    }


def revert_confirmation_out(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
    source_repo: Path,
) -> dict[str, Any]:
    if apply_session.owner_id != owner_id:
        raise ApplySessionError(
            "APPLY_SESSION_NOT_FOUND",
            "The Apply session is unavailable.",
        )
    entries = apply_session_entries(session, apply_session)
    run = session.get(CodexRun, apply_session.run_id)
    blockers: list[dict[str, str]] = []
    unrelated: list[Any] = []
    staged_count: int | None = None
    if apply_session.state != "APPLIED":
        blockers.append(
            {
                "code": "REVERT_NOT_AVAILABLE",
                "message": "Only an exact successful Apply session can be reverted.",
            }
        )
    elif run is None:
        blockers.append(
            {
                "code": "RUN_BINDING_UNAVAILABLE",
                "message": "The Apply-session Run is unavailable.",
            }
        )
    else:
        try:
            root = _verified_repository_root(
                run,
                source_repo,
                expected_source_workspace_identity=(
                    apply_session.source_workspace_identity
                ),
                expected_source_snapshot_identity=(
                    apply_session.source_snapshot_identity
                ),
                require_strong_source_identity=bool(
                    apply_session.result_envelope_id is not None
                    or apply_session.result_digest
                ),
            )
            for entry in entries:
                if not _entry_matches_after(root, entry):
                    blockers.append(
                        {
                            "code": "REVERT_PRECONDITION_CONFLICT",
                            "message": (
                                "An applied path changed after Apply; Revert will "
                                "not overwrite it."
                            ),
                        }
                    )
                    break
            evidence = _global_evidence(
                run,
                root,
                target_paths=[entry.repository_path for entry in entries],
            )
            unrelated = _decoded_object(evidence.get("unrelated")).get(
                "changed_paths", []
            )
            staged_count = int(
                _decoded_object(evidence.get("index")).get(
                    "staged_path_count", 0
                )
            )
            if staged_count:
                blockers.append(
                    {
                        "code": "STAGED_PATHS_PRESENT",
                        "message": "Revert requires zero staged paths.",
                    }
                )
        except Exception:
            blockers.append(
                {
                    "code": "REPOSITORY_UNAVAILABLE",
                    "message": "The repository cannot be verified safely.",
                }
            )
    return {
        "action": "Revert Applied Changes",
        "explicit_confirmation_required": True,
        "preselected_confirmation": False,
        "eligible": not blockers,
        "apply_session_id": apply_session.session_id,
        "expected_journal_digest": apply_session.journal_digest,
        "paths": [
            {
                "path": entry.repository_path,
                "operation": entry.operation,
                "reverse_operation": entry.reverse_operation,
                "after_hash": entry.after_hash,
            }
            for entry in reversed(entries)
        ],
        "unrelated_source_changes": unrelated,
        "index_boundary": {
            "staged_path_count": staged_count,
            "requires_zero_staged_paths": True,
            "index_will_change": False,
        },
        "boundaries": [
            "Revert affects only this exact Apply session.",
            "Every applied path must still match its captured after-state.",
            "Unrelated source paths remain untouched.",
            "No reset or clean occurs.",
            "No Stage, Commit, or Push occurs.",
        ],
        "blockers": blockers,
    }


def _next_action(state: str) -> str:
    return {
        "PREFLIGHT_BLOCKED": (
            "Resolve the preflight blocker and review a newly current Apply Plan."
        ),
        "APPLYING": (
            "Wait for the current path-scoped Apply to finish; do not submit a "
            "duplicate mutation."
        ),
        "APPLIED": (
            "Review the narrow integrity result. Revert Applied Changes is available "
            "as a separate explicit action while all after-state preconditions hold."
        ),
        "APPLY_FAILED_RECOVERED": (
            "The source was restored. Review failure evidence before creating a "
            "new Apply Plan."
        ),
        "APPLY_FAILED_PARTIAL": (
            "Focused source remediation is required; Apply, Revert, and later phases "
            "remain blocked."
        ),
        "REVERTING": (
            "Wait for the current path-scoped Revert to finish; do not submit a "
            "duplicate mutation."
        ),
        "REVERTED": "The exact Apply session has been restored to its pre-Apply state.",
        "REVERT_BLOCKED": (
            "Review the Revert blocker or recovered failure evidence; no newer "
            "source change was overwritten."
        ),
        "REVERT_FAILED_PARTIAL": (
            "Focused source remediation is required; later phases remain blocked."
        ),
    }[state]


def apply_session_out(
    session: Session,
    apply_session: ApplySession,
) -> dict[str, Any]:
    entries = apply_session_entries(session, apply_session)
    audits = list(
        session.scalars(
            select(ApplySessionAudit)
            .where(ApplySessionAudit.apply_session_id == apply_session.id)
            .order_by(ApplySessionAudit.id)
        ).all()
    )
    before = _decoded_object(apply_session.before_evidence_json)
    before_index = _decoded_object(before.get("index"))
    failures = _decoded_list(apply_session.failure_evidence_json)
    compensation = _decoded_list(apply_session.compensation_evidence_json)
    return {
        "id": apply_session.session_id,
        "journal_digest": apply_session.journal_digest,
        "state": apply_session.state,
        "status_label": APPLY_SESSION_STATE_LABELS[apply_session.state],
        "integrity_check_result": apply_session.integrity_check_result,
        "apply_plan": {
            "id": apply_session.apply_plan_public_id,
            "digest": apply_session.apply_plan_digest,
        },
        "candidate": {
            "id": apply_session.candidate_public_id,
            "version": apply_session.candidate_version,
            "digest": apply_session.candidate_digest,
        },
        "result_lineage": (
            {
                "result_envelope_id": (
                    apply_session.result_envelope_public_id
                ),
                "owner_review": "accepted_for_delivery",
                "apply_plan_approval_id": (
                    apply_session.apply_plan_approval_public_id
                ),
            }
            if apply_session.result_envelope_id is not None
            else None
        ),
        "files": [
            {
                "path": entry.repository_path,
                "operation": entry.operation,
                "reverse_operation": entry.reverse_operation,
                "apply_result": entry.apply_result,
                "revert_result": entry.revert_result,
            }
            for entry in entries
        ],
        "included_path_count": apply_session.included_path_count,
        "excluded_path_count": apply_session.excluded_path_count,
        "blocked_path_count": apply_session.blocked_path_count,
        "unrelated_source_changes": _decoded_object(
            before.get("unrelated")
        ).get("changed_paths", []),
        "index_boundary": {
            "fingerprint": before_index.get("fingerprint"),
            "staged_path_count": before_index.get("staged_path_count"),
            "index_changed_by_apply": False,
        },
        "revert_available": apply_session.state == "APPLIED",
        "blockers": failures,
        "next_action": _next_action(apply_session.state),
        "boundaries": [
            "No Stage, Commit, or Push occurred.",
            "Post-Apply Verification requires a separate explicit Owner action.",
            "No Provider was invoked.",
        ],
        "created_at": apply_session.created_at.isoformat() + "Z",
        "started_at": (
            apply_session.started_at.isoformat() + "Z"
            if apply_session.started_at is not None
            else None
        ),
        "finished_at": (
            apply_session.finished_at.isoformat() + "Z"
            if apply_session.finished_at is not None
            else None
        ),
        "revert_started_at": (
            apply_session.revert_started_at.isoformat() + "Z"
            if apply_session.revert_started_at is not None
            else None
        ),
        "revert_finished_at": (
            apply_session.revert_finished_at.isoformat() + "Z"
            if apply_session.revert_finished_at is not None
            else None
        ),
        "advanced": {
            "policy_version": APPLY_SESSION_POLICY_VERSION,
            "run_id": apply_session.run_id,
            "task_binding": {
                "task_id": apply_session.task_id,
                "task_version": apply_session.task_version,
            },
            "pack_binding": {
                "pack_id": apply_session.pack_id,
                "pack_version": apply_session.pack_version,
            },
            "source_snapshot_identity": apply_session.source_snapshot_identity,
            "source_workspace_identity": (
                apply_session.source_workspace_identity or None
            ),
            "run_workspace_identity": (
                apply_session.run_workspace_identity or None
            ),
            "run_workspace_baseline_identity": (
                apply_session.run_workspace_baseline_identity or None
            ),
            "run_workspace_post_state_identity": (
                apply_session.run_workspace_post_state_identity or None
            ),
            "run_workspace_identity": (
                apply_session.run_workspace_identity or None
            ),
            "run_workspace_baseline_identity": (
                apply_session.run_workspace_baseline_identity or None
            ),
            "run_workspace_post_state_identity": (
                apply_session.run_workspace_post_state_identity or None
            ),
            "result_envelope_id": (
                apply_session.result_envelope_public_id or None
            ),
            "result_digest": apply_session.result_digest or None,
            "owner_acceptance_id": apply_session.owner_acceptance_id,
            "result_review_decision_digest": (
                apply_session.result_review_decision_digest or None
            ),
            "apply_plan_approval": {
                "id": apply_session.apply_plan_approval_public_id or None,
                "digest": apply_session.apply_plan_approval_digest or None,
            },
            "source_drift_evaluation_id": (
                apply_session.source_drift_evaluation_id
            ),
            "repository_identity": (
                apply_session.sanitized_repository_identity
            ),
            "repository_locator_fingerprint": (
                apply_session.repository_locator_fingerprint
            ),
            "repository_fingerprint": apply_session.repository_fingerprint,
            "branch": apply_session.branch,
            "head": apply_session.pre_apply_head,
            "index_fingerprint": apply_session.pre_apply_index_fingerprint,
            "worktree_fingerprint": (
                apply_session.pre_apply_worktree_fingerprint
            ),
            "apply_confirmation_digest": (
                apply_session.apply_confirmation_digest
            ),
            "revert_confirmation_digest": (
                apply_session.revert_confirmation_digest or None
            ),
            "entries": [
                {
                    "path": entry.repository_path,
                    "path_identity": entry.path_identity,
                    "operation_ordinal": entry.operation_ordinal,
                    "operation": entry.operation,
                    "reverse_operation": entry.reverse_operation,
                    "before_hash": entry.before_hash,
                    "after_hash": entry.after_hash,
                    "before_size": entry.before_size,
                    "after_size": entry.after_size,
                    "before_mode": entry.before_mode,
                    "after_mode": entry.after_mode,
                    "before_file_type": entry.before_file_type,
                    "after_file_type": entry.after_file_type,
                    "before_mtime_ns": entry.before_mtime_ns,
                    "after_mtime_ns": entry.after_mtime_ns,
                    "temporary_material_identity": (
                        entry.temporary_material_identity
                    ),
                    "created_parent_dirs": _decoded_list(
                        entry.created_parent_dirs_json
                    ),
                }
                for entry in entries
            ],
            "compensation": compensation,
            "preflight_observations": _decoded_object(
                before.get("preflight_observations")
            ),
            "audit": [
                {
                    "phase": audit.phase,
                    "event_type": audit.event_type,
                    "state": audit.state,
                    "path_identity": audit.path_identity or None,
                    "created_at": audit.created_at.isoformat() + "Z",
                }
                for audit in audits
            ],
            "diagnostics": {
                "path_mutation": "explicit_path_scoped",
                "git_mutation": False,
                "index_mutation": False,
                "head_ref_config_remote_mutation": False,
                "post_apply_verification": False,
                "git_metadata_refresh": _decoded_object(
                    _decoded_object(before.get("preflight_observations")).get(
                        "semantic_difference"
                    )
                ).get("metadata_refresh_categories", []),
            },
        },
    }


def apply_session_history(
    session: Session,
    *,
    owner_id: int,
    run_id: int,
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(ApplySession)
            .where(
                ApplySession.owner_id == owner_id,
                ApplySession.run_id == run_id,
            )
            .order_by(ApplySession.id.desc())
            .limit(50)
        ).all()
    )
    return [
        {
            "id": row.session_id,
            "state": row.state,
            "status_label": APPLY_SESSION_STATE_LABELS[row.state],
            "created_at": row.created_at.isoformat() + "Z",
        }
        for row in rows
    ]
