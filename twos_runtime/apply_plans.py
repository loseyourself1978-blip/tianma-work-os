from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .delivery_candidates import (
    DRIFT_STATUS_LABELS,
    SHA256_PATTERN,
    canonical_json,
    canonical_sha256,
    normalize_repository_path,
    result_review_decision_digest,
    validate_delivery_candidate,
)
from .models import (
    ApplyPlan,
    ApplyPlanApproval,
    ApplyPlanEntry,
    CodexResultEnvelope,
    CodexRun,
    DeliveryCandidate,
    OwnerAcceptanceSession,
    SourceDriftEvaluation,
    utc_now,
)
from .self_hosting import (
    SOURCE_REPOSITORY_IDENTITY_METHOD,
    SOURCE_REPOSITORY_IDENTITY_METHODS,
    _snapshot_exclusion_reason,
    _source_snapshot_digest,
    capture_source_snapshot,
    git_source_state,
    run_git,
    source_snapshot_has_strong_repository_identity,
)


APPLY_PLAN_POLICY_VERSION = "twos.review_apply_plan.v2"
APPLY_PLAN_ORDER_POLICY = "delete-deepest_modify-lexical_create-shallowest.v1"
GIT_OBJECT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SECRETISH_REPOSITORY_IDENTITY = re.compile(
    r"(?:credential|secret|token|password|passwd|private[._-]?key|api[._-]?key|\.env)",
    re.IGNORECASE,
)
APPLY_PLAN_ORDER_EXPLANATION = (
    "INCLUDED deletes are ordered deepest first, modifies by repository-relative "
    "path, and creates shallowest first. An exact ancestor DELETE is ordered before "
    "a dependent CREATE; other ancestor/descendant file shapes are blocked."
)

READINESS_LABELS = {
    "awaiting_owner_approval": "AWAITING OWNER APPROVAL",
    "ready_for_owner_review": "READY FOR OWNER REVIEW",
    "review_with_source_changes": "REVIEW WITH SOURCE CHANGES",
    "blocked_by_conflict": "BLOCKED BY CONFLICT",
    "blocked_by_candidate": "BLOCKED BY CANDIDATE",
    "blocked_by_repository": "BLOCKED BY REPOSITORY",
    "expired": "EXPIRED",
}

READINESS_BY_DRIFT = {
    "ready_to_apply": "ready_for_owner_review",
    "source_changed_since_run": "review_with_source_changes",
    "conflict_detected": "blocked_by_conflict",
    "candidate_unavailable": "blocked_by_candidate",
    "repository_unavailable": "blocked_by_repository",
}

APPLY_PLAN_READ_ONLY_GIT_ALLOWLIST = (
    "rev-parse --show-toplevel",
    "rev-parse --absolute-git-dir",
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
)

EXPLICIT_BOUNDARIES = (
    "Review Apply Plan is not approval to apply changes.",
    "Apply Accepted Changes requires a separate explicit Owner confirmation.",
    "Revert Applied Changes requires a separate explicit Owner confirmation after a successful Apply.",
    "Reviewing this Plan changes no source file, index, HEAD, ref, Git configuration, or remote.",
    "No stage, commit, push, Provider invocation, broker, trade, bet, or scheduler action occurs.",
)

GLOBAL_PRECONDITION_DEFINITIONS = (
    ("OWNER_IDENTITY", "The authenticated Owner must remain the same."),
    ("CANDIDATE_IDENTITY", "The exact Candidate ID and digest must remain valid."),
    ("PLAN_IDENTITY", "The exact Plan ID and digest must remain valid and non-expired."),
    ("FRESH_SOURCE_DRIFT", "A fresh Source Drift Evaluation must be created."),
    ("REPOSITORY_IDENTITY", "The same authorized repository fingerprint must be observed."),
    ("MAIN_BRANCH", "The repository branch must be main."),
    ("HEAD_POLICY", "HEAD must satisfy the exact Plan-bound policy."),
    ("INDEX_FINGERPRINT", "The Git index fingerprint must remain unchanged."),
    ("ZERO_STAGED_PATHS", "The staged-file count must be zero."),
    ("WORKTREE_FINGERPRINT", "The worktree fingerprint must remain Plan-bound."),
    ("NO_TARGET_CONFLICTS", "No Candidate-target preimage conflict may exist."),
    ("INCLUDED_PRECONDITIONS", "Every INCLUDED path must pass all operation preconditions."),
    ("EXPLICIT_NON_INCLUDED", "Every EXCLUDED or BLOCKED path must remain explicitly non-applied."),
)

PRE_APPLY_CHECK_DEFINITIONS = (
    ("CANDIDATE_INTEGRITY", "Revalidate Candidate identity and canonical digest."),
    ("PLAN_INTEGRITY", "Revalidate Plan identity and canonical digest."),
    ("FRESH_DRIFT", "Create and bind a fresh Source Drift Evaluation."),
    ("REPOSITORY_ROOT", "Verify the exact authorized repository root."),
    ("BRANCH", "Verify branch main."),
    ("HEAD", "Verify the permitted exact HEAD policy."),
    ("INDEX", "Verify the exact index fingerprint and zero staged paths."),
    ("PATH_PRECONDITIONS", "Verify every INCLUDED path precondition."),
    ("UNEXPECTED_BOUNDARY", "Recheck unexpected and unrelated file boundaries."),
    ("SECRET_PATH_BOUNDARY", "Recheck secret, credential, and unsafe-path boundaries."),
)

POST_APPLY_CHECK_DEFINITIONS = (
    ("EXPECTED_PATHS", "Verify the exact expected paths and operations."),
    ("EXPECTED_CONTENT", "Verify expected postimage hashes, modes, and file types."),
    ("UNEXPECTED_FILES", "Verify that no unexpected file was created or changed."),
    ("UNRELATED_CHANGES", "Verify preservation of unrelated source changes."),
    ("CLEAN_INDEX", "Verify a clean index and zero staged paths."),
    ("UNCHANGED_HEAD", "Verify HEAD is unchanged."),
    ("UNCHANGED_REFS", "Verify refs are unchanged from captured pre-state."),
    ("UNCHANGED_REMOTE_CONFIG", "Verify remotes and Git configuration are unchanged."),
)

CONFLICT_REASON_CODES = frozenset(
    {
        "CANDIDATE_PREIMAGE_CONFLICT",
        "CREATE_TARGET_EXISTS",
        "MODIFY_TARGET_MISSING",
        "DELETE_TARGET_MISSING",
        "TARGET_NOT_REGULAR_FILE",
        "PARENT_CHAIN_UNSAFE",
        "SYMLINK_ESCAPE",
        "CASE_PATH_COLLISION",
        "DUPLICATE_PATH",
        "PATH_SHAPE_CONFLICT",
    }
)
_OBSERVATION_UNSET = object()


class ApplyPlanError(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        # Retain the historical one-argument exception contract while giving
        # new result-delivery callers stable, Owner-readable error codes.
        if message is None:
            message = code
            code = "APPLY_PLAN_INVALID"
        super().__init__(message)
        self.code = code
        self.message = message


def _decoded_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decoded_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timestamp_identity(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _planned_check(code: str, description: str, *, phase: str) -> dict[str, str]:
    return {
        "code": code,
        "description": description,
        "phase": phase,
        "status": "PLANNED CHECK",
    }


def global_preconditions() -> list[dict[str, str]]:
    return [
        _planned_check(code, description, phase="PRE_APPLY")
        for code, description in GLOBAL_PRECONDITION_DEFINITIONS
    ]


def planned_validation() -> dict[str, list[dict[str, str]]]:
    return {
        "pre_apply": [
            _planned_check(code, description, phase="PRE_APPLY")
            for code, description in PRE_APPLY_CHECK_DEFINITIONS
        ],
        "post_apply": [
            _planned_check(code, description, phase="POST_APPLY")
            for code, description in POST_APPLY_CHECK_DEFINITIONS
        ],
    }


def reversibility_requirements() -> dict[str, Any]:
    return {
        "state": "CAPTURED_ONLY_BY_EXPLICIT_APPLY",
        "requirements": [
            "Apply must create one unique durable apply-session identity.",
            "Every reverse-evidence record must bind to that exact apply session.",
            "Only INCLUDED paths may enter the reverse scope.",
            "Unrelated paths must remain outside the reverse scope.",
            "A separate explicit Owner action is required for Revert.",
            "No reset, clean, or broad checkout or restore may be used.",
            "Reviewing the Plan alone captures no restoration material and changes no source.",
        ],
    }


def _sanitize_repository_identity(root: Path) -> str:
    name = unicodedata.normalize("NFC", root.name)
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", name)
        and SECRETISH_REPOSITORY_IDENTITY.search(name) is None
    ):
        return name
    return f"repository-{_sha256_bytes(name.encode('utf-8'))[:12]}"


def _sanitize_branch_identity(branch: str) -> str:
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,239}", branch)
        and SECRETISH_REPOSITORY_IDENTITY.search(branch) is None
    ):
        return branch
    return f"branch-{_sha256_bytes(branch.encode('utf-8'))[:12]}"


def _safe_excluded_path(path: object, reason: str) -> tuple[str, str]:
    raw = str(path or "")
    identity = _sha256_bytes(raw.encode("utf-8", errors="replace"))
    if reason == "credential_or_secret":
        return "[credential-shaped path withheld]", identity
    if (
        not raw
        or raw.startswith(("/", "\\", "~"))
        or re.match(r"^[A-Za-z]:", raw)
        or "\\" in raw
        or "\x00" in raw
    ):
        return "[unsafe path withheld]", identity
    try:
        normalized = unicodedata.normalize("NFC", raw)
        pure = PurePosixPath(normalized)
        if (
            normalized
            and not pure.is_absolute()
            and normalized == pure.as_posix()
            and all(part not in {"", ".", ".."} for part in pure.parts)
        ):
            return normalized, identity
    except (TypeError, ValueError):
        pass
    return "[unsafe path withheld]", identity


def observe_repository(run: CodexRun, source_repo: Path) -> dict[str, Any]:
    configured_root = source_repo.resolve(strict=True)
    verified_root = Path(
        run_git(
            configured_root,
            "rev-parse",
            "--show-toplevel",
            hardened_read_only=True,
        ).stdout.strip()
    ).resolve(strict=True)
    if verified_root != configured_root:
        raise ApplyPlanError("Configured source path is not the repository root.")
    stored_root = Path(run.source_repo).resolve(strict=True)
    if stored_root != verified_root:
        raise ApplyPlanError("Run source identity does not match configured source.")

    source = git_source_state(
        verified_root,
        hardened_read_only=True,
        verified_root=verified_root,
    )
    approved_source_snapshot = (
        _decoded_object(run.pack.source_snapshot_json)
        if run.pack is not None
        else {}
    )
    approved_identity_method = str(
        approved_source_snapshot.get("source_repository_identity_method") or ""
    )
    snapshot = capture_source_snapshot(
        verified_root,
        hardened_read_only=True,
        verified_source_state=source,
        source_repository_identity_method=(
            approved_identity_method
            if approved_identity_method in SOURCE_REPOSITORY_IDENTITY_METHODS
            else SOURCE_REPOSITORY_IDENTITY_METHOD
        ),
    )
    if not approved_source_snapshot.get("source_repository_identity"):
        snapshot.pop("source_repository_identity_method", None)
        snapshot.pop("source_repository_identity", None)
        snapshot["digest"] = _source_snapshot_digest(snapshot)
    head = str(snapshot.get("head_sha") or "")
    current_source_digest = str(snapshot.get("digest") or "")
    observed_branch = str(source.get("branch") or "")
    if (
        not GIT_OBJECT_PATTERN.fullmatch(head)
        or not SHA256_PATTERN.fullmatch(current_source_digest)
        or not observed_branch
        or len(observed_branch) > 240
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in observed_branch
        )
    ):
        raise ApplyPlanError("Repository source identities are unavailable.")
    branch = _sanitize_branch_identity(observed_branch)

    absolute_git_dir = Path(
        run_git(
            verified_root,
            "rev-parse",
            "--absolute-git-dir",
            hardened_read_only=True,
        ).stdout.strip()
    ).resolve(strict=True)
    index_output = run_git(
        verified_root,
        "rev-parse",
        "--git-path",
        "index",
        hardened_read_only=True,
    ).stdout.strip()
    index_candidate = Path(index_output)
    if not index_candidate.is_absolute():
        index_candidate = verified_root / index_candidate
    unresolved_index_stat = index_candidate.lstat()
    if stat.S_ISLNK(unresolved_index_stat.st_mode):
        raise ApplyPlanError("Git index identity is unsafe or unavailable.")
    index_path = index_candidate.resolve(strict=True)
    index_stat = index_path.lstat()
    if (
        stat.S_ISLNK(index_stat.st_mode)
        or not stat.S_ISREG(index_stat.st_mode)
        or not index_path.is_relative_to(absolute_git_dir)
    ):
        raise ApplyPlanError("Git index identity is unsafe or unavailable.")
    index_fd = os.open(
        index_path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened_index_stat = os.fstat(index_fd)
        if (
            not stat.S_ISREG(opened_index_stat.st_mode)
            or (opened_index_stat.st_dev, opened_index_stat.st_ino)
            != (index_stat.st_dev, index_stat.st_ino)
        ):
            raise ApplyPlanError("Git index identity changed during inspection.")
        index_digest = hashlib.sha256()
        index_size = 0
        while True:
            chunk = os.read(index_fd, 1024 * 1024)
            if not chunk:
                break
            index_digest.update(chunk)
            index_size += len(chunk)
        final_index_stat = os.fstat(index_fd)
    finally:
        os.close(index_fd)
    if (
        final_index_stat.st_size != opened_index_stat.st_size
        or final_index_stat.st_mtime_ns != opened_index_stat.st_mtime_ns
        or final_index_stat.st_ctime_ns != opened_index_stat.st_ctime_ns
        or (final_index_stat.st_dev, final_index_stat.st_ino)
        != (opened_index_stat.st_dev, opened_index_stat.st_ino)
        or not stat.S_ISREG(final_index_stat.st_mode)
        or index_size != opened_index_stat.st_size
    ):
        raise ApplyPlanError("Git index changed during inspection.")

    staged_output = run_git(
        verified_root,
        "diff",
        "--cached",
        "--name-only",
        "-z",
        hardened_read_only=True,
    ).stdout
    staged_paths = [item for item in staged_output.split("\0") if item]
    status_digest = _sha256_bytes(str(source.get("status") or "").encode("utf-8"))
    staged_path_identities = sorted(
        _sha256_bytes(item.encode("utf-8", errors="replace"))
        for item in staged_paths
    )
    excluded_identities = sorted(
        {
            _sha256_bytes(str(item.get("path") or "").encode("utf-8", errors="replace"))
            for item in snapshot.get("excluded_manifest", [])
            if isinstance(item, dict)
        }
    )
    worktree_fingerprint = canonical_sha256(
        {
            "schema": "twos.apply_plan_worktree.v1",
            "source_snapshot_digest": current_source_digest,
            "status_digest": status_digest,
            "staged_path_identities": staged_path_identities,
            "excluded_path_identities": excluded_identities,
        }
    )
    index_fingerprint = index_digest.hexdigest()
    locator_fingerprint = _sha256_bytes(str(verified_root).encode("utf-8"))
    sanitized_identity = _sanitize_repository_identity(verified_root)
    repository_fingerprint = canonical_sha256(
        {
            "schema": "twos.apply_plan_repository.v1",
            "locator_fingerprint": locator_fingerprint,
            "sanitized_identity": sanitized_identity,
            "branch": branch,
            "head": head,
            "source_digest": current_source_digest,
            "index_fingerprint": index_fingerprint,
            "worktree_fingerprint": worktree_fingerprint,
        }
    )
    return {
        "sanitized_repository_identity": sanitized_identity,
        "repository_locator_fingerprint": locator_fingerprint,
        "repository_fingerprint": repository_fingerprint,
        "branch": branch,
        "observed_head": head,
        "current_source_digest": current_source_digest,
        "index_fingerprint": index_fingerprint,
        "worktree_fingerprint": worktree_fingerprint,
        "staged_path_count": len(staged_paths),
        "snapshot": snapshot,
        "verified_root": verified_root,
        "diagnostics": {
            "inspection": "read_only",
            "git_command_policy": "explicit_allowlist",
            "git_commands": list(APPLY_PLAN_READ_ONLY_GIT_ALLOWLIST),
            "index": "read_only_fingerprint",
            "repository": "verified",
        },
    }


def drift_semantic_fingerprint(evaluation: SourceDriftEvaluation) -> str:
    diagnostics = _decoded_object(evaluation.diagnostics_json)
    safe_diagnostics = {
        key: diagnostics.get(key)
        for key in (
            "repository",
            "candidate",
            "candidate_preconditions",
            "source_matches_baseline",
            "branch_matches_baseline",
            "detached_head",
            "reason_code",
        )
        if key in diagnostics
    }
    blocker_codes = sorted(
        {
            str(item.get("code") or "")
            for item in _decoded_list(evaluation.blockers_json)
            if isinstance(item, dict) and item.get("code")
        }
    )
    conflict_paths = sorted(
        str(item)
        for item in _decoded_list(evaluation.conflict_paths_json)
        if isinstance(item, str)
    )
    return canonical_sha256(
        {
            "schema": "twos.apply_plan_drift_binding.v1",
            "status": evaluation.status,
            "baseline_source_digest": evaluation.baseline_source_digest,
            "current_source_digest": evaluation.current_source_digest,
            "current_head": evaluation.current_head,
            "blocker_codes": blocker_codes,
            "conflict_paths": conflict_paths,
            "diagnostics": safe_diagnostics,
        }
    )


def _snapshot_state(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for raw in snapshot.get("included_manifest", []):
        if not isinstance(raw, dict):
            continue
        try:
            path = normalize_repository_path(raw.get("path"))
        except (TypeError, ValueError):
            continue
        state[path] = {
            "present": raw.get("deleted") is not True,
            "sha256": raw.get("sha256"),
            "size": raw.get("size"),
            "mode": raw.get("mode"),
            "kind": raw.get("kind"),
        }
    return state


def build_scope_findings(
    baseline_snapshot: dict[str, Any],
    current_snapshot: dict[str, Any],
    candidate_paths: Iterable[str],
) -> list[dict[str, Any]]:
    touched = set(candidate_paths)
    baseline = _snapshot_state(baseline_snapshot)
    current = _snapshot_state(current_snapshot)
    findings: list[dict[str, Any]] = []
    for path in sorted(set(baseline) | set(current)):
        if path in touched or baseline.get(path) == current.get(path):
            continue
        findings.append(
            {
                "path": path,
                "path_identity": _sha256_bytes(path.encode("utf-8")),
                "disposition": "EXCLUDED",
                "reason_code": "UNRELATED_CURRENT_SOURCE",
                "reason": "Current source evidence is outside the Candidate operation scope.",
                "unexpected": current.get(path, {}).get("kind") == "untracked",
            }
        )
    seen_identities = {item["path_identity"] for item in findings}
    for raw in current_snapshot.get("excluded_manifest", []):
        if not isinstance(raw, dict):
            continue
        reason = str(raw.get("reason") or "excluded")
        display_path, path_identity = _safe_excluded_path(raw.get("path"), reason)
        if path_identity in seen_identities:
            continue
        seen_identities.add(path_identity)
        findings.append(
            {
                "path": display_path,
                "path_identity": path_identity,
                "disposition": "EXCLUDED",
                "reason_code": (
                    "SECRET_PATH_EXCLUDED"
                    if reason == "credential_or_secret"
                    else "RUNTIME_PATH_EXCLUDED"
                ),
                "reason": "This current path is outside the Candidate operation scope.",
                "unexpected": True,
            }
        )
    return sorted(findings, key=lambda item: (item["path"], item["path_identity"]))


def _operation_preconditions(operation: str) -> list[dict[str, str]]:
    common = [
        _planned_check(
            "SAFE_PARENT_CHAIN",
            "The parent chain must remain inside the repository and contain no symlink escape.",
            phase="PRE_APPLY",
        )
    ]
    if operation == "CREATE":
        return common + [
            _planned_check("TARGET_ABSENT", "The exact target path must remain absent.", phase="PRE_APPLY"),
            _planned_check(
                "AFTER_IDENTITY_AVAILABLE",
                "The regular-file postimage hash, size, mode, and content material must be available.",
                phase="PRE_APPLY",
            ),
        ]
    if operation == "MODIFY":
        return common + [
            _planned_check(
                "EXPECTED_REGULAR_PREIMAGE",
                "The target must remain a regular file with the exact approved preimage hash, size, and mode.",
                phase="PRE_APPLY",
            ),
            _planned_check(
                "AFTER_IDENTITY_AVAILABLE",
                "The regular-file postimage hash, size, mode, and content material must be available.",
                phase="PRE_APPLY",
            ),
        ]
    if operation == "DELETE":
        return common + [
            _planned_check(
                "EXPECTED_REGULAR_PREIMAGE",
                "The target must remain a regular file with the exact approved preimage hash, size, and mode.",
                phase="PRE_APPLY",
            ),
            _planned_check(
                "EXACT_PATH_ONLY",
                "Deletion must remain limited to this exact path; no recursive cleanup is inferred.",
                phase="PRE_APPLY",
            ),
            _planned_check(
                "RESTORATION_MATERIAL",
                "Complete restoration material must be captured before any future deletion.",
                phase="PRE_APPLY",
            ),
        ]
    return [
        _planned_check(
            "SUPPORTED_OPERATION",
            "The operation must be a supported CREATE, MODIFY, or DELETE.",
            phase="PRE_APPLY",
        )
    ]


def _operation_reversibility(operation: str) -> dict[str, Any]:
    if operation == "CREATE":
        return {
            "state": "CAPTURED_ONLY_BY_EXPLICIT_APPLY",
            "capture": [
                "Proof that the exact path was absent.",
                "The exact created-content hash, mode, and regular-file type.",
            ],
            "future_reverse_operation": "DELETE_EXACT",
        }
    if operation == "MODIFY":
        return {
            "state": "CAPTURED_ONLY_BY_EXPLICIT_APPLY",
            "capture": [
                "Complete before content or a safe restoration reference.",
                "The before hash, mode, and regular-file type.",
                "The exact expected postimage identity.",
            ],
            "future_reverse_operation": "RESTORE_EXACT",
        }
    if operation == "DELETE":
        return {
            "state": "CAPTURED_ONLY_BY_EXPLICIT_APPLY",
            "capture": [
                "Complete restoration material.",
                "The before hash, mode, and regular-file type.",
            ],
            "future_reverse_operation": "RECREATE_EXACT",
        }
    return {
        "state": "UNAVAILABLE",
        "capture": ["A supported operation is required before reversibility can be planned."],
        "future_reverse_operation": "NONE",
    }


def _entry_validation(operation: str) -> list[dict[str, str]]:
    return [
        _planned_check(
            f"{operation}_PRECONDITION",
            f"Revalidate the exact {operation} path state before an explicit Apply.",
            phase="PRE_APPLY",
        ),
        _planned_check(
            f"{operation}_POSTIMAGE",
            f"Verify the exact {operation} outcome after an explicit Apply.",
            phase="POST_APPLY",
        ),
    ]


def _block_entry(entry: dict[str, Any], code: str, reason: str) -> None:
    entry["disposition"] = "BLOCKED"
    entry["reason_code"] = code
    entry["reason"] = reason
    entry["operation_ordinal"] = None
    conflicts = entry.setdefault("conflicts", [])
    if code not in conflicts:
        conflicts.append(code)


def _inspect_target(
    root: Path,
    path: str,
    operation: str,
    *,
    before_hash: str | None,
    before_size: int | None,
    before_mode: int | None,
    planned_delete_paths: frozenset[str] = frozenset(),
) -> tuple[str, str] | None:
    cursor = root
    parts = PurePosixPath(path).parts
    parent_parts: list[str] = []
    for part in parts[:-1]:
        parent_parts.append(part)
        cursor = cursor / part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError:
            return "PARENT_CHAIN_UNSAFE", "The target parent chain cannot be inspected safely."
        if stat.S_ISLNK(mode):
            return "SYMLINK_ESCAPE", "A target parent is a symlink."
        if not stat.S_ISDIR(mode):
            parent_path = PurePosixPath(*parent_parts).as_posix()
            if (
                operation == "CREATE"
                and stat.S_ISREG(mode)
                and parent_path in planned_delete_paths
            ):
                # The exact regular-file ancestor has Candidate DELETE evidence.
                # Topology validation below binds this CREATE to that DELETE and
                # blocks the CREATE if the DELETE is not ultimately INCLUDED.
                return None
            return "PATH_SHAPE_CONFLICT", "A target parent is not a directory."

    target = root / path
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    except OSError:
        return "TARGET_NOT_REGULAR_FILE", "The target cannot be inspected safely."
    if target_stat is not None and stat.S_ISLNK(target_stat.st_mode):
        return "SYMLINK_ESCAPE", "The target is a symlink."
    if operation == "CREATE":
        if target_stat is not None:
            return "CREATE_TARGET_EXISTS", "A CREATE target is no longer absent."
        return None
    if target_stat is None:
        return (
            "MODIFY_TARGET_MISSING" if operation == "MODIFY" else "DELETE_TARGET_MISSING",
            f"The {operation} target is missing.",
        )
    if not stat.S_ISREG(target_stat.st_mode):
        return "TARGET_NOT_REGULAR_FILE", "The target is not a supported regular file."
    try:
        target_fd = os.open(
            target,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return "TARGET_NOT_REGULAR_FILE", "The target content cannot be inspected safely."
    digest = hashlib.sha256()
    total_size = 0
    try:
        opened_stat = os.fstat(target_fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (target_stat.st_dev, target_stat.st_ino)
        ):
            return "TARGET_NOT_REGULAR_FILE", "The target changed during inspection."
        while True:
            chunk = os.read(target_fd, 1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            digest.update(chunk)
        final_stat = os.fstat(target_fd)
    except OSError:
        return "TARGET_NOT_REGULAR_FILE", "The target content cannot be inspected safely."
    finally:
        os.close(target_fd)
    if (
        final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
        or final_stat.st_ctime_ns != opened_stat.st_ctime_ns
        or (final_stat.st_dev, final_stat.st_ino)
        != (opened_stat.st_dev, opened_stat.st_ino)
        or not stat.S_ISREG(final_stat.st_mode)
        or digest.hexdigest() != before_hash
        or total_size != before_size
        or (final_stat.st_mode & 0o777) != before_mode
    ):
        return "CANDIDATE_PREIMAGE_CONFLICT", "The target no longer matches its approved preimage."
    return None


def construct_path_decisions(
    manifest: list[Any],
    *,
    repository_root: Path | None,
    conflict_paths: Iterable[str] = (),
    repository_blocker: tuple[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    conflict_path_set = set(conflict_paths)
    planned_delete_paths: set[str] = set()
    for raw in manifest:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("operation") or "").upper() != "DELETE":
            continue
        try:
            planned_delete_paths.add(normalize_repository_path(raw.get("path")))
        except (TypeError, ValueError):
            continue
    frozen_planned_delete_paths = frozenset(planned_delete_paths)

    entries: list[dict[str, Any]] = []
    for manifest_ordinal, raw in enumerate(manifest, start=1):
        record = raw if isinstance(raw, dict) else {}
        raw_path = record.get("path")
        path_identity = _sha256_bytes(
            str(raw_path if raw_path is not None else raw).encode(
                "utf-8", errors="replace"
            )
        )
        operation = str(record.get("operation") or "UNKNOWN").upper()
        if operation not in {"CREATE", "MODIFY", "DELETE"}:
            operation = "UNKNOWN"
        entry: dict[str, Any] = {
            "manifest_ordinal": manifest_ordinal,
            "operation_ordinal": None,
            "repository_path": "",
            "display_path": "[unsafe path withheld]",
            "path_identity": path_identity,
            "operation": operation,
            "disposition": "BLOCKED",
            "reason_code": "UNSAFE_PATH",
            "reason": "The Candidate path is unsafe or malformed.",
            "unexpected": record.get("unexpected") is True,
            "content_kind": (
                "binary"
                if record.get("content_kind") == "binary_or_oversized"
                else str(record.get("content_kind") or "unknown")
            ),
            "before_hash": record.get("before_hash"),
            "after_hash": record.get("after_hash"),
            "before_size": record.get("before_size"),
            "after_size": record.get("after_size"),
            "before_mode": record.get("before_mode"),
            "after_mode": record.get("after_mode"),
            "evidence_identity": (
                str(record.get("evidence_identity"))
                if SHA256_PATTERN.fullmatch(str(record.get("evidence_identity") or ""))
                else ""
            ),
            "conflicts": [],
            "preconditions": _operation_preconditions(operation),
            "reversibility": _operation_reversibility(operation),
            "validation": _entry_validation(operation),
        }
        try:
            path = normalize_repository_path(raw_path)
            entry["repository_path"] = path
            entry["display_path"] = path
            entry["path_identity"] = _sha256_bytes(path.encode("utf-8"))
        except (TypeError, ValueError):
            reason = _snapshot_exclusion_reason(str(raw_path or ""))
            if reason:
                entry["display_path"], entry["path_identity"] = _safe_excluded_path(
                    raw_path, reason
                )
                entry["reason_code"] = (
                    "SECRET_PATH_BLOCKED"
                    if reason == "credential_or_secret"
                    else "POLICY_PATH_BLOCKED"
                )
            entries.append(entry)
            continue

        if operation == "UNKNOWN":
            _block_entry(entry, "UNSUPPORTED_OPERATION", "The Candidate operation is unsupported.")
            entries.append(entry)
            continue
        before_required = operation in {"MODIFY", "DELETE"}
        after_required = operation in {"CREATE", "MODIFY"}
        evidence_invalid = False
        for field, required in (
            ("before_hash", before_required),
            ("after_hash", after_required),
        ):
            value = entry[field]
            if required and not SHA256_PATTERN.fullmatch(str(value or "")):
                evidence_invalid = True
            if not required and value not in {None, ""}:
                evidence_invalid = True
        for field, required in (
            ("before_size", before_required),
            ("after_size", after_required),
        ):
            value = entry[field]
            if required and (type(value) is not int or not 0 <= value <= 10**12):
                evidence_invalid = True
            if not required and value is not None:
                evidence_invalid = True
        for field, required in (
            ("before_mode", before_required),
            ("after_mode", after_required),
        ):
            value = entry[field]
            if required and (type(value) is not int or not 0 <= value <= 0o777):
                evidence_invalid = True
            if not required and value is not None:
                evidence_invalid = True
        if evidence_invalid or not entry["evidence_identity"]:
            _block_entry(
                entry,
                "EVIDENCE_INCOMPLETE",
                "The Candidate entry lacks complete safe hash, size, mode, or evidence identity.",
            )
        elif repository_blocker is not None:
            _block_entry(entry, repository_blocker[0], repository_blocker[1])
        elif path in conflict_path_set:
            _block_entry(
                entry,
                "CANDIDATE_PREIMAGE_CONFLICT",
                "The Candidate path no longer matches its approved preimage.",
            )
        elif repository_root is None:
            _block_entry(
                entry,
                "REPOSITORY_UNAVAILABLE",
                "The repository cannot be inspected safely.",
            )
        else:
            target_problem = _inspect_target(
                repository_root,
                path,
                operation,
                before_hash=entry["before_hash"],
                before_size=entry["before_size"],
                before_mode=entry["before_mode"],
                planned_delete_paths=frozen_planned_delete_paths,
            )
            if target_problem is not None:
                _block_entry(entry, target_problem[0], target_problem[1])
            elif entry["unexpected"]:
                entry["disposition"] = "EXCLUDED"
                entry["reason_code"] = "UNEXPECTED_FILE_POLICY_EXCLUDED"
                entry["reason"] = (
                    "Policy excludes an unexpected Candidate file from any future Apply."
                    " Policy never mutates this path."
                )
            else:
                entry["disposition"] = "INCLUDED"
                entry["reason_code"] = "POLICY_ELIGIBLE"
                entry["reason"] = (
                    "The Candidate entry is safe and policy-eligible for future review."
                )
        entries.append(entry)

    paths: dict[str, list[dict[str, Any]]] = {}
    casefolded: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        path = entry["repository_path"]
        if not path:
            continue
        paths.setdefault(path, []).append(entry)
        casefolded.setdefault(path.casefold(), []).append(entry)
    for duplicates in paths.values():
        if len(duplicates) > 1:
            for entry in duplicates:
                _block_entry(entry, "DUPLICATE_PATH", "The Candidate contains a duplicate path.")
    for collision in casefolded.values():
        distinct = {entry["repository_path"] for entry in collision}
        if len(distinct) > 1:
            for entry in collision:
                _block_entry(
                    entry,
                    "CASE_PATH_COLLISION",
                    "Candidate paths collide under case-insensitive path policy.",
                )

    safe_entries = [entry for entry in entries if entry["repository_path"]]
    dependencies_by_manifest_ordinal: dict[int, set[int]] = {
        entry["manifest_ordinal"]: set() for entry in safe_entries
    }
    for left in safe_entries:
        for right in safe_entries:
            if left is right:
                continue
            left_path = PurePosixPath(left["repository_path"])
            right_path = PurePosixPath(right["repository_path"])
            if left_path not in right_path.parents:
                continue
            if left["operation"] == "DELETE" and right["operation"] == "CREATE":
                dependencies_by_manifest_ordinal[right["manifest_ordinal"]].add(
                    left["manifest_ordinal"]
                )
                continue
            _block_entry(
                left,
                "PATH_SHAPE_CONFLICT",
                "Candidate file paths have an unsupported ancestor/descendant shape.",
            )
            _block_entry(
                right,
                "PATH_SHAPE_CONFLICT",
                "Candidate file paths have an unsupported ancestor/descendant shape.",
            )

    entries_by_manifest_ordinal = {
        entry["manifest_ordinal"]: entry for entry in safe_entries
    }
    for dependent_ordinal, prerequisite_ordinals in (
        dependencies_by_manifest_ordinal.items()
    ):
        dependent = entries_by_manifest_ordinal[dependent_ordinal]
        if dependent["disposition"] != "INCLUDED":
            continue
        for prerequisite_ordinal in prerequisite_ordinals:
            prerequisite = entries_by_manifest_ordinal[prerequisite_ordinal]
            if prerequisite["disposition"] == "INCLUDED":
                continue
            _block_entry(
                dependent,
                "PATH_SHAPE_CONFLICT",
                "A required ancestor DELETE is not eligible for this dependent CREATE.",
            )
            break

    included = [entry for entry in entries if entry["disposition"] == "INCLUDED"]
    included_ids = {entry["manifest_ordinal"] for entry in included}
    dependencies = {
        key: {item for item in values if item in included_ids}
        for key, values in dependencies_by_manifest_ordinal.items()
        if key in included_ids
    }

    def priority(entry: dict[str, Any]) -> tuple[Any, ...]:
        path = entry["repository_path"]
        depth = len(PurePosixPath(path).parts)
        operation_rank = {"DELETE": 0, "MODIFY": 1, "CREATE": 2}[entry["operation"]]
        depth_rank = -depth if entry["operation"] == "DELETE" else depth
        return (
            operation_rank,
            depth_rank,
            path.encode("utf-8"),
            entry["evidence_identity"],
        )

    remaining = {entry["manifest_ordinal"]: entry for entry in included}
    ordered: list[dict[str, Any]] = []
    while remaining:
        ready = [
            entry
            for key, entry in remaining.items()
            if not (dependencies.get(key, set()) & set(remaining))
        ]
        if not ready:
            for entry in remaining.values():
                _block_entry(
                    entry,
                    "PATH_SHAPE_CONFLICT",
                    "Candidate operation dependencies contain a cycle.",
                )
            ordered = []
            break
        selected = sorted(ready, key=priority)[0]
        ordinal = len(ordered) + 1
        selected["operation_ordinal"] = ordinal
        ordered.append(
            {
                "ordinal": ordinal,
                "manifest_ordinal": selected["manifest_ordinal"],
                "path": selected["repository_path"],
                "operation": selected["operation"],
                "dependencies": sorted(
                    dependencies.get(selected["manifest_ordinal"], set())
                ),
            }
        )
        remaining.pop(selected["manifest_ordinal"])

    conflict_findings = [
        {
            "path": entry["display_path"],
            "code": entry["reason_code"],
            "reason": entry["reason"],
        }
        for entry in entries
        if entry["disposition"] == "BLOCKED"
    ]
    return entries, ordered, conflict_findings


def _candidate_manifest(candidate: DeliveryCandidate) -> list[Any]:
    return _decoded_list(candidate.file_manifest_json)


def _candidate_blockers(
    eligibility: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {
            "code": str(item.get("code") or "CANDIDATE_UNAVAILABLE"),
            "message": str(item.get("message") or "The Candidate is unavailable."),
        }
        for item in eligibility.get("blockers", [])
        if isinstance(item, dict)
    ]


def _unique_blockers(blockers: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for blocker in blockers:
        code = str(blocker.get("code") or "APPLY_PLAN_BLOCKED")
        unique.setdefault(
            code,
            {
                "code": code,
                "message": str(blocker.get("message") or "The Apply Plan is blocked."),
            },
        )
    return list(unique.values())


def _plan_has_result_lineage(plan: ApplyPlan) -> bool:
    """Distinguish canonical Result delivery from historical Apply Plans.

    Vol.18/19.1A Plans predate Result-envelope delivery lineage. They keep
    their literal Apply-confirmation behavior, but they can never be silently
    converted into a canonical Plan approval.
    """
    return bool(
        plan.result_envelope_id is not None
        or plan.result_envelope_public_id
        or plan.result_digest
        or plan.owner_acceptance_id is not None
        or plan.result_review_decision_digest
        or plan.source_workspace_identity
        or plan.run_workspace_identity
    )


def _material_has_result_lineage(material: dict[str, Any]) -> bool:
    return bool(
        material.get("result_envelope_id") is not None
        or material.get("result_envelope_public_id")
        or material.get("result_digest")
        or material.get("owner_acceptance_id") is not None
        or material.get("result_review_decision_digest")
        or material.get("source_workspace_identity")
        or material.get("run_workspace_identity")
    )


def _candidate_result_lineage(
    session: Session,
    *,
    owner_id: int,
    candidate: DeliveryCandidate,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Resolve and validate immutable Result-to-Candidate delivery bindings."""
    lineage = {
        "candidate_version": max(int(candidate.candidate_version or 1), 1),
        "result_envelope_id": candidate.result_envelope_id,
        "result_envelope_public_id": candidate.result_envelope_public_id or "",
        "result_digest": candidate.result_digest or "",
        "owner_acceptance_id": None,
        "result_review_decision_digest": "",
        "approved_instruction_digest": candidate.approved_instruction_digest or "",
        "source_workspace_identity": candidate.source_workspace_identity or "",
        "run_workspace_identity": candidate.run_workspace_identity or "",
        "run_workspace_baseline_identity": (
            candidate.run_workspace_baseline_identity or ""
        ),
        "run_workspace_post_state_identity": (
            candidate.run_workspace_post_state_identity or ""
        ),
        "verification_policy": candidate.verification_policy or "required",
        "verification_verdict": candidate.verification_verdict or "unavailable",
        "verification_receipt_identity": (
            candidate.verification_receipt_identity or ""
        ),
    }
    # An empty Result binding is a historical Candidate, not a partially
    # trusted modern one. Its old Apply confirmation remains available, while
    # create_apply_plan_approval() rejects it explicitly.
    if (
        candidate.derivation_version != "twos.result_delivery_candidate.v1"
        and candidate.result_envelope_id is None
        and not any(
            (
                candidate.result_envelope_public_id,
                candidate.result_digest,
                candidate.approved_instruction_digest,
                candidate.source_workspace_identity,
                candidate.run_workspace_identity,
            )
        )
    ):
        return lineage, []

    lineage["owner_acceptance_id"] = candidate.acceptance_id

    blockers: list[dict[str, str]] = []
    envelope = (
        session.get(CodexResultEnvelope, candidate.result_envelope_id)
        if candidate.result_envelope_id is not None
        else None
    )
    run = session.get(CodexRun, candidate.run_id)
    acceptance = (
        session.get(OwnerAcceptanceSession, candidate.acceptance_id)
        if candidate.acceptance_id is not None
        else None
    )
    if envelope is None:
        blockers.append(
            {
                "code": "RESULT_BINDING_UNAVAILABLE",
                "message": "The Candidate-bound immutable Run Result is unavailable.",
            }
        )
    approved_source_snapshot = (
        _decoded_object(run.pack.source_snapshot_json)
        if run is not None and run.pack is not None
        else {}
    )
    try:
        approved_source_snapshot_digest = _source_snapshot_digest(
            approved_source_snapshot
        )
    except (TypeError, ValueError):
        approved_source_snapshot_digest = ""
    if not (
        run is not None
        and run.id == candidate.run_id
        and run.task_id == candidate.task_id
        and run.pack_id == candidate.pack_id
        and run.pack is not None
        and run.pack.version == candidate.pack_version
        and source_snapshot_has_strong_repository_identity(
            approved_source_snapshot
        )
        and approved_source_snapshot_digest
        == approved_source_snapshot.get("digest")
        == run.source_snapshot_digest
        == candidate.source_snapshot_identity
        and approved_source_snapshot.get("source_repository_identity")
        == candidate.source_workspace_identity
    ):
        blockers.append(
            {
                "code": "SOURCE_WORKSPACE_BINDING_INVALID",
                "message": "The Result-derived Candidate is not bound to the exact approved source repository identity.",
            }
        )
    if acceptance is None:
        blockers.append(
            {
                "code": "RESULT_REVIEW_UNAVAILABLE",
                "message": "The Candidate-bound Owner Result review is unavailable.",
            }
        )
    if candidate.readiness_state != "ready":
        blockers.append(
            {
                "code": (
                    "RESULT_HAS_NO_DELIVERABLE_CHANGES"
                    if candidate.readiness_state == "no_changes"
                    else "RESULT_CANDIDATE_BLOCKED"
                ),
                "message": candidate.readiness_reason
                or "The Result-derived Candidate is not ready for delivery.",
            }
        )
    if envelope is not None:
        envelope_binding = (
            envelope.owner_id == owner_id
            and envelope.id == candidate.result_envelope_id
            and envelope.envelope_id == candidate.result_envelope_public_id
            and envelope.result_digest == candidate.result_digest
            and envelope.run_id == candidate.run_id
            and envelope.task_id == candidate.task_id
            and envelope.task_version == candidate.task_version
            and envelope.pack_id == candidate.pack_id
            and envelope.pack_version == candidate.pack_version
            and envelope.approved_instruction_digest
            == candidate.approved_instruction_digest
            and envelope.authorized_workspace_identity
            == candidate.source_workspace_identity
            and envelope.integrity_state == "VERIFIED"
            and str(candidate.result_integrity_state or "").lower() == "verified"
        )
        if not envelope_binding:
            blockers.append(
                {
                    "code": "RESULT_BINDING_CHANGED",
                    "message": "The immutable Result, Candidate, or workspace binding changed.",
                }
            )
    if acceptance is not None:
        lineage["result_review_decision_digest"] = acceptance.decision_digest or ""
        acceptance_binding = (
            acceptance.owner_id == owner_id
            and acceptance.codex_run_id == candidate.run_id
            and acceptance.task_id == candidate.task_id
            and acceptance.result_envelope_id == candidate.result_envelope_id
            and acceptance.result_envelope_public_id
            == candidate.result_envelope_public_id
            and acceptance.result_digest == candidate.result_digest
            and acceptance.result_task_version == candidate.task_version
            and acceptance.result_pack_id == candidate.pack_id
            and acceptance.result_pack_version == candidate.pack_version
            and acceptance.approved_instruction_digest
            == candidate.approved_instruction_digest
            and acceptance.delivery_candidate_id == candidate.id
            and acceptance.candidate_public_id == candidate.candidate_id
            and acceptance.candidate_version == candidate.candidate_version
            and acceptance.candidate_digest == candidate.candidate_digest
        )
        if not acceptance_binding:
            blockers.append(
                {
                    "code": "RESULT_REVIEW_BINDING_CHANGED",
                    "message": "The Owner Result review no longer binds this exact Result and Candidate.",
                }
            )
        if acceptance.status != "accepted":
            blockers.append(
                {
                    "code": (
                        "RESULT_REVIEW_REJECTED"
                        if acceptance.status == "rejected"
                        else "RESULT_REVIEW_REQUIRED"
                    ),
                    "message": (
                        "The Owner rejected this Result for delivery."
                        if acceptance.status == "rejected"
                        else "The Owner must explicitly accept this Result for delivery before preparing an Apply Plan."
                    ),
                }
            )
        elif (
            acceptance.decided_by_user_id != owner_id
            or acceptance.decided_at is None
            or not SHA256_PATTERN.fullmatch(acceptance.decision_digest or "")
            or acceptance.decision_digest
            != result_review_decision_digest(acceptance)
        ):
            blockers.append(
                {
                    "code": "RESULT_REVIEW_DECISION_INVALID",
                    "message": "The accepted Owner Result decision lacks complete immutable evidence.",
                }
            )
    verification_policy = str(candidate.verification_policy or "required").lower()
    verification_verdict = str(candidate.verification_verdict or "unavailable").lower()
    if verification_policy == "required":
        if verification_verdict != "passed" or not SHA256_PATTERN.fullmatch(
            candidate.verification_receipt_identity or ""
        ):
            blockers.append(
                {
                    "code": "VERIFICATION_GATE_NOT_PASSED",
                    "message": "Required independent Verification has not produced a bound passing receipt.",
                }
            )
    elif verification_policy in {"not_required", "optional"}:
        if verification_verdict not in {"not_required", "passed"}:
            blockers.append(
                {
                    "code": "VERIFICATION_POLICY_UNSATISFIED",
                    "message": "The Result does not satisfy its declared Verification policy.",
                }
            )
    else:
        blockers.append(
            {
                "code": "VERIFICATION_POLICY_INVALID",
                "message": "The Candidate has an unsupported Verification policy.",
            }
        )
    for field in (
        "result_digest",
        "approved_instruction_digest",
        "source_workspace_identity",
        "run_workspace_identity",
        "run_workspace_baseline_identity",
        "run_workspace_post_state_identity",
    ):
        if not SHA256_PATTERN.fullmatch(str(lineage[field] or "")):
            blockers.append(
                {
                    "code": "RESULT_LINEAGE_INCOMPLETE",
                    "message": "The Result delivery lineage is incomplete.",
                }
            )
            break
    return lineage, _unique_blockers(blockers)


def _binding_digest_payload(material: dict[str, Any]) -> dict[str, Any]:
    """Return only server-observed, semantically stable Plan-binding inputs."""
    payload = {
        "schema": "twos.apply_plan_binding.v1",
        "owner_id": material["owner_id"],
        "delivery_candidate_id": material["delivery_candidate_id"],
        "candidate_public_id": material["candidate_public_id"],
        "candidate_digest": material["candidate_digest"],
        "run_id": material["run_id"],
        "task_id": material["task_id"],
        "task_version": material["task_version"],
        "pack_id": material["pack_id"],
        "pack_version": material["pack_version"],
        "source_snapshot_identity": material["source_snapshot_identity"],
        # The evaluation row ID and timestamp are deliberately excluded so a
        # repeated fresh evaluation of identical evidence remains idempotent.
        "source_drift_state": material["source_drift_state"],
        "drift_semantic_fingerprint": material["drift_semantic_fingerprint"],
        "sanitized_repository_identity": material[
            "sanitized_repository_identity"
        ],
        "repository_locator_fingerprint": material[
            "repository_locator_fingerprint"
        ],
        "repository_fingerprint": material["repository_fingerprint"],
        "branch": material["branch"],
        "observed_head": material["observed_head"],
        "current_source_digest": material["current_source_digest"],
        "index_fingerprint": material["index_fingerprint"],
        "worktree_fingerprint": material["worktree_fingerprint"],
        "staged_path_count": material["staged_path_count"],
        "policy_version": material["policy_version"],
        "status_at_creation": material["status_at_creation"],
        "candidate_entry_count": material["candidate_entry_count"],
        "classified_entry_count": material["classified_entry_count"],
        "entries": [
            _entry_digest_material(entry) for entry in material["entries"]
        ],
        "operation_order": material["operation_order"],
        "scope_findings": material["scope_findings"],
        "unexpected_findings": material["unexpected_findings"],
        "conflict_findings": material["conflict_findings"],
        "blockers": material["blockers"],
    }
    if _material_has_result_lineage(material):
        payload.update(
            {
                "delivery_lineage_schema": "twos.result_apply_plan_lineage.v1",
                "candidate_version": material["candidate_version"],
                "result_envelope_id": material["result_envelope_id"],
                "result_envelope_public_id": material[
                    "result_envelope_public_id"
                ],
                "result_digest": material["result_digest"],
                "owner_acceptance_id": material["owner_acceptance_id"],
                "result_review_decision_digest": material[
                    "result_review_decision_digest"
                ],
                "approved_instruction_digest": material[
                    "approved_instruction_digest"
                ],
                "source_workspace_identity": material[
                    "source_workspace_identity"
                ],
                "run_workspace_identity": material["run_workspace_identity"],
                "run_workspace_baseline_identity": material[
                    "run_workspace_baseline_identity"
                ],
                "run_workspace_post_state_identity": material[
                    "run_workspace_post_state_identity"
                ],
                "verification_policy": material["verification_policy"],
                "verification_verdict": material["verification_verdict"],
                "verification_receipt_identity": material[
                    "verification_receipt_identity"
                ],
            }
        )
    return payload


def build_apply_plan_material(
    session: Session,
    *,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate | None,
    candidate_eligibility: dict[str, Any],
    drift: SourceDriftEvaluation,
    source_repo: Path,
    policy_version: str = APPLY_PLAN_POLICY_VERSION,
) -> dict[str, Any]:
    candidate_valid = bool(candidate is not None and candidate_eligibility.get("eligible") is True)
    blockers: list[dict[str, str]] = []
    lineage: dict[str, Any] = {
        "candidate_version": int(getattr(candidate, "candidate_version", 1) or 1),
        "result_envelope_id": None,
        "result_envelope_public_id": "",
        "result_digest": "",
        "owner_acceptance_id": None,
        "result_review_decision_digest": "",
        "approved_instruction_digest": "",
        "source_workspace_identity": "",
        "run_workspace_identity": "",
        "run_workspace_baseline_identity": "",
        "run_workspace_post_state_identity": "",
        "verification_policy": "required",
        "verification_verdict": "unavailable",
        "verification_receipt_identity": "",
    }
    canonical_result_candidate = bool(
        candidate is not None
        and (
            candidate.derivation_version == "twos.result_delivery_candidate.v1"
            or candidate.result_envelope_id is not None
            or candidate.result_envelope_public_id
            or candidate.result_digest
            or candidate.source_workspace_identity
            or candidate.run_workspace_identity
        )
    )
    if candidate is not None:
        lineage, lineage_blockers = _candidate_result_lineage(
            session,
            owner_id=owner_id,
            candidate=candidate,
        )
        if canonical_result_candidate:
            if not candidate_valid:
                lineage_blockers = _unique_blockers(
                    [*lineage_blockers, *_candidate_blockers(candidate_eligibility)]
                )
            if lineage_blockers:
                first = lineage_blockers[0]
                raise ApplyPlanError(first["code"], first["message"])
    if not candidate_valid:
        blockers.extend(_candidate_blockers(candidate_eligibility))
        if not blockers:
            blockers.append(
                {
                    "code": "CANDIDATE_UNAVAILABLE",
                    "message": "An eligible immutable Delivery Candidate is unavailable.",
                }
            )

    observation: dict[str, Any] | None = None
    observation_error = ""
    try:
        observation = observe_repository(run, source_repo)
    except (OSError, ValueError, RuntimeError) as exc:
        observation_error = type(exc).__name__
        blockers.append(
            {
                "code": "REPOSITORY_UNAVAILABLE",
                "message": "The Candidate-bound repository cannot be verified safely.",
            }
        )

    repository_blocker: tuple[str, str] | None = None
    if observation is not None:
        if observation["branch"] != "main":
            repository_blocker = (
                "UNSUPPORTED_BRANCH",
                "The repository branch is not main.",
            )
            blockers.append(
                {
                    "code": repository_blocker[0],
                    "message": repository_blocker[1],
                }
            )
        elif observation["staged_path_count"] != 0:
            repository_blocker = (
                "STAGED_FILES_PRESENT",
                "The Git index contains staged paths.",
            )
            blockers.append(
                {
                    "code": repository_blocker[0],
                    "message": repository_blocker[1],
                }
            )
        elif (
            drift.status not in {"candidate_unavailable", "repository_unavailable"}
            and (
                drift.current_source_digest != observation["current_source_digest"]
                or drift.current_head != observation["observed_head"]
            )
        ):
            repository_blocker = (
                "REPOSITORY_CHANGED_DURING_REVIEW",
                "Repository state changed between Drift and Plan observations.",
            )
            blockers.append(
                {
                    "code": repository_blocker[0],
                    "message": repository_blocker[1],
                }
            )
    else:
        repository_blocker = (
            "REPOSITORY_UNAVAILABLE",
            "The repository cannot be inspected safely.",
        )

    conflict_paths = [
        str(item)
        for item in _decoded_list(drift.conflict_paths_json)
        if isinstance(item, str)
    ]
    manifest = _candidate_manifest(candidate) if candidate_valid and candidate is not None else []
    entries, operation_order, conflict_findings = construct_path_decisions(
        manifest,
        repository_root=observation["verified_root"] if observation else None,
        conflict_paths=conflict_paths,
        repository_blocker=repository_blocker,
    )
    scope_findings: list[dict[str, Any]] = []
    if observation is not None and candidate_valid and candidate is not None:
        pack = session.get(type(run.pack), candidate.pack_id) if run.pack is not None else None
        baseline_snapshot = (
            _decoded_object(pack.source_snapshot_json) if pack is not None else {}
        )
        scope_findings = build_scope_findings(
            baseline_snapshot,
            observation["snapshot"],
            [
                entry["repository_path"]
                for entry in entries
                if entry["repository_path"]
            ],
        )

    blocked_entries = [entry for entry in entries if entry["disposition"] == "BLOCKED"]
    if candidate_valid and blocked_entries:
        blockers.extend(
            {
                "code": entry["reason_code"],
                "message": entry["reason"],
            }
            for entry in blocked_entries
        )
    blockers = _unique_blockers(blockers)

    if not candidate_valid or drift.status == "candidate_unavailable":
        readiness = "blocked_by_candidate"
    elif (
        observation is None
        or repository_blocker is not None
        or drift.status == "repository_unavailable"
    ):
        readiness = "blocked_by_repository"
    elif drift.status == "conflict_detected" or any(
        entry["reason_code"] in CONFLICT_REASON_CODES for entry in blocked_entries
    ):
        readiness = "blocked_by_conflict"
    elif blocked_entries:
        readiness = "blocked_by_candidate"
    elif drift.status == "source_changed_since_run":
        readiness = "review_with_source_changes"
    else:
        readiness = READINESS_BY_DRIFT.get(
            drift.status, "blocked_by_repository"
        )

    if readiness == "ready_for_owner_review":
        next_action = (
            "Review the exact INCLUDED files, then explicitly choose Apply Accepted "
            "Changes if you want to modify the source repository."
        )
    elif readiness == "review_with_source_changes":
        next_action = (
            "Review the unrelated source changes. Apply Accepted Changes will require "
            "a fresh server-side preflight and a separate explicit confirmation."
        )
    else:
        blocker_message = (
            blockers[0]["message"]
            if blockers
            else "The Apply Plan is blocked by current evidence."
        )
        next_action = (
            f"{blocker_message} Review again after resolving the blocker; "
            "Apply Accepted Changes remains blocked."
        )

    observation_material = observation or {
        "sanitized_repository_identity": "",
        "repository_locator_fingerprint": "",
        "repository_fingerprint": "",
        "branch": "",
        "observed_head": "",
        "current_source_digest": "",
        "index_fingerprint": "",
        "worktree_fingerprint": "",
        "staged_path_count": 0,
        "diagnostics": {
            "inspection": "read_only",
            "repository": "unavailable",
            "reason_code": observation_error or "repository_inspection_failed",
        },
    }
    unexpected_findings = [
        {
            "path": entry["display_path"],
            "disposition": entry["disposition"],
            "reason": entry["reason"],
        }
        for entry in entries
        if entry["unexpected"]
    ]
    validation = planned_validation()
    plan_preconditions = global_preconditions()
    if canonical_result_candidate:
        plan_preconditions.extend(
            [
                _planned_check(
                    "RESULT_REVIEW_ACCEPTED",
                    "The exact immutable Result and Candidate must retain the accepted Owner decision binding.",
                    phase="PRE_APPLY",
                ),
                _planned_check(
                    "PLAN_APPROVAL",
                    "The exact current Apply Plan must retain a valid immutable Owner approval.",
                    phase="PRE_APPLY",
                ),
                _planned_check(
                    "DELIVERY_LINEAGE",
                    "Result, Candidate version, Verification receipt, and source workspace bindings must remain exact.",
                    phase="PRE_APPLY",
                ),
            ]
        )
        validation["pre_apply"] = [
            _planned_check(
                "PLAN_APPROVAL_INTEGRITY",
                "Revalidate the persisted Plan approval and exact delivery lineage.",
                phase="PRE_APPLY",
            ),
            *validation["pre_apply"],
        ]
    material: dict[str, Any] = {
        "owner_id": owner_id,
        "delivery_candidate_id": candidate.id if candidate is not None else None,
        "candidate_public_id": candidate.candidate_id if candidate is not None else "",
        "candidate_digest": candidate.candidate_digest if candidate is not None else "",
        "candidate_version": lineage["candidate_version"],
        "result_envelope_id": lineage["result_envelope_id"],
        "result_envelope_public_id": lineage["result_envelope_public_id"],
        "result_digest": lineage["result_digest"],
        "owner_acceptance_id": lineage["owner_acceptance_id"],
        "result_review_decision_digest": lineage[
            "result_review_decision_digest"
        ],
        "run_id": run.id,
        "task_id": run.task_id,
        "task_version": run.task_version,
        "pack_id": run.pack_id,
        "pack_version": run.pack.version if run.pack is not None else 0,
        "approved_instruction_digest": lineage["approved_instruction_digest"],
        "source_snapshot_identity": (
            candidate.source_snapshot_identity
            if candidate is not None
            else run.source_snapshot_digest
        ),
        "source_workspace_identity": lineage["source_workspace_identity"],
        "run_workspace_identity": lineage["run_workspace_identity"],
        "run_workspace_baseline_identity": lineage[
            "run_workspace_baseline_identity"
        ],
        "run_workspace_post_state_identity": lineage[
            "run_workspace_post_state_identity"
        ],
        "verification_policy": lineage["verification_policy"],
        "verification_verdict": lineage["verification_verdict"],
        "verification_receipt_identity": lineage[
            "verification_receipt_identity"
        ],
        "source_drift_evaluation_id": drift.id,
        "source_drift_state": drift.status,
        "drift_semantic_fingerprint": drift_semantic_fingerprint(drift),
        "sanitized_repository_identity": observation_material[
            "sanitized_repository_identity"
        ],
        "repository_locator_fingerprint": observation_material[
            "repository_locator_fingerprint"
        ],
        "repository_fingerprint": observation_material["repository_fingerprint"],
        "branch": observation_material["branch"],
        "observed_head": observation_material["observed_head"],
        "current_source_digest": observation_material["current_source_digest"],
        "index_fingerprint": observation_material["index_fingerprint"],
        "worktree_fingerprint": observation_material["worktree_fingerprint"],
        "staged_path_count": observation_material["staged_path_count"],
        "policy_version": policy_version,
        "status_at_creation": readiness,
        "candidate_entry_count": len(manifest),
        "classified_entry_count": len(entries),
        "entries": entries,
        "operation_order": {
            "policy": APPLY_PLAN_ORDER_POLICY,
            "explanation": APPLY_PLAN_ORDER_EXPLANATION,
            "operations": operation_order,
        },
        "scope_findings": scope_findings,
        "included_paths": [
            {
                "path": entry["display_path"],
                "operation": entry["operation"],
                "reason": entry["reason"],
            }
            for entry in entries
            if entry["disposition"] == "INCLUDED"
        ],
        "excluded_paths": [
            {
                "path": entry["display_path"],
                "operation": entry["operation"],
                "reason": entry["reason"],
            }
            for entry in entries
            if entry["disposition"] == "EXCLUDED"
        ],
        "blocked_paths": [
            {
                "path": entry["display_path"],
                "operation": entry["operation"],
                "reason": entry["reason"],
            }
            for entry in entries
            if entry["disposition"] == "BLOCKED"
        ],
        "unexpected_findings": unexpected_findings,
        "conflict_findings": conflict_findings,
        "global_preconditions": plan_preconditions,
        "reversibility_requirements": reversibility_requirements(),
        "pre_apply_checks": validation["pre_apply"],
        "post_apply_checks": validation["post_apply"],
        "explicit_boundaries": list(EXPLICIT_BOUNDARIES),
        "blockers": blockers,
        "diagnostics": observation_material["diagnostics"],
        "next_action": next_action,
    }
    material["binding_digest"] = canonical_sha256(
        _binding_digest_payload(material)
    )
    return material


def _entry_digest_material(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        key: entry.get(key)
        for key in (
            "manifest_ordinal",
            "operation_ordinal",
            "repository_path",
            "display_path",
            "path_identity",
            "operation",
            "disposition",
            "reason_code",
            "reason",
            "unexpected",
            "content_kind",
            "before_hash",
            "after_hash",
            "before_size",
            "after_size",
            "before_mode",
            "after_mode",
            "evidence_identity",
            "conflicts",
            "preconditions",
            "reversibility",
            "validation",
        )
    }


def _plan_digest_payload(
    material: dict[str, Any],
    *,
    plan_version: int,
    supersedes_plan_digest: str,
) -> dict[str, Any]:
    payload = {
        "schema": "twos.review_apply_plan.v1",
        "owner_id": material["owner_id"],
        "delivery_candidate_id": material["delivery_candidate_id"],
        "candidate_public_id": material["candidate_public_id"],
        "candidate_digest": material["candidate_digest"],
        "run_id": material["run_id"],
        "task_id": material["task_id"],
        "task_version": material["task_version"],
        "pack_id": material["pack_id"],
        "pack_version": material["pack_version"],
        "source_snapshot_identity": material["source_snapshot_identity"],
        "source_drift_evaluation_id": material["source_drift_evaluation_id"],
        "source_drift_state": material["source_drift_state"],
        "drift_semantic_fingerprint": material["drift_semantic_fingerprint"],
        "sanitized_repository_identity": material["sanitized_repository_identity"],
        "repository_locator_fingerprint": material["repository_locator_fingerprint"],
        "repository_fingerprint": material["repository_fingerprint"],
        "branch": material["branch"],
        "observed_head": material["observed_head"],
        "current_source_digest": material["current_source_digest"],
        "index_fingerprint": material["index_fingerprint"],
        "worktree_fingerprint": material["worktree_fingerprint"],
        "staged_path_count": material["staged_path_count"],
        "policy_version": material["policy_version"],
        "plan_version": plan_version,
        "status_at_creation": material["status_at_creation"],
        "candidate_entry_count": material["candidate_entry_count"],
        "classified_entry_count": material["classified_entry_count"],
        "entries": [_entry_digest_material(entry) for entry in material["entries"]],
        "operation_order": material["operation_order"],
        "scope_findings": material["scope_findings"],
        "included_paths": material["included_paths"],
        "excluded_paths": material["excluded_paths"],
        "blocked_paths": material["blocked_paths"],
        "unexpected_findings": material["unexpected_findings"],
        "conflict_findings": material["conflict_findings"],
        "global_preconditions": material["global_preconditions"],
        "reversibility_requirements": material["reversibility_requirements"],
        "pre_apply_checks": material["pre_apply_checks"],
        "post_apply_checks": material["post_apply_checks"],
        "explicit_boundaries": material["explicit_boundaries"],
        "blockers": material["blockers"],
        "diagnostics": material["diagnostics"],
        "binding_digest": material["binding_digest"],
        "supersedes_plan_digest": supersedes_plan_digest,
        "supersession_reason": material.get("supersession_reason", ""),
        "expires_at": material.get("expires_at"),
    }
    if _material_has_result_lineage(material):
        payload.update(
            {
                "delivery_lineage_schema": "twos.result_apply_plan_lineage.v1",
                "candidate_version": material["candidate_version"],
                "result_envelope_id": material["result_envelope_id"],
                "result_envelope_public_id": material[
                    "result_envelope_public_id"
                ],
                "result_digest": material["result_digest"],
                "owner_acceptance_id": material["owner_acceptance_id"],
                "result_review_decision_digest": material[
                    "result_review_decision_digest"
                ],
                "approved_instruction_digest": material[
                    "approved_instruction_digest"
                ],
                "source_workspace_identity": material[
                    "source_workspace_identity"
                ],
                "run_workspace_identity": material["run_workspace_identity"],
                "run_workspace_baseline_identity": material[
                    "run_workspace_baseline_identity"
                ],
                "run_workspace_post_state_identity": material[
                    "run_workspace_post_state_identity"
                ],
                "verification_policy": material["verification_policy"],
                "verification_verdict": material["verification_verdict"],
                "verification_receipt_identity": material[
                    "verification_receipt_identity"
                ],
            }
        )
    return payload


def latest_apply_plan(
    session: Session, owner_id: int, run_id: int
) -> ApplyPlan | None:
    return session.scalar(
        select(ApplyPlan)
        .where(ApplyPlan.owner_id == owner_id, ApplyPlan.run_id == run_id)
        .order_by(ApplyPlan.plan_version.desc(), ApplyPlan.id.desc())
    )


def get_or_create_apply_plan(
    session: Session,
    *,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate | None,
    candidate_eligibility: dict[str, Any],
    drift: SourceDriftEvaluation,
    source_repo: Path,
    policy_version: str = APPLY_PLAN_POLICY_VERSION,
) -> tuple[ApplyPlan, bool]:
    material = build_apply_plan_material(
        session,
        owner_id=owner_id,
        run=run,
        candidate=candidate,
        candidate_eligibility=candidate_eligibility,
        drift=drift,
        source_repo=source_repo,
        policy_version=policy_version,
    )
    latest = latest_apply_plan(session, owner_id, run.id)
    if latest is not None and latest.binding_digest == material["binding_digest"]:
        if not validate_apply_plan_integrity(session, latest):
            raise ApplyPlanError(
                "The latest immutable Apply Plan failed its integrity check."
            )
        return latest, False

    plan_version = (latest.plan_version + 1) if latest is not None else 1
    if latest is not None and not validate_apply_plan_integrity(session, latest):
        raise ApplyPlanError(
            "The latest immutable Apply Plan failed its integrity check."
        )
    supersedes_digest = latest.plan_digest if latest is not None else ""
    supersession_reason = (
        "Plan binding changed; the prior immutable Plan is now historical."
        if latest is not None
        else ""
    )
    material["supersession_reason"] = supersession_reason
    # R2 defines expiry through immutable supersession. This nullable field is
    # reserved for a future explicitly versioned time policy; no TTL is
    # invented by Phase 18.2A.
    material["expires_at"] = None
    plan_digest = canonical_sha256(
        _plan_digest_payload(
            material,
            plan_version=plan_version,
            supersedes_plan_digest=supersedes_digest,
        )
    )
    plan = ApplyPlan(
        plan_id="ap_" + plan_digest[:40],
        owner_id=material["owner_id"],
        delivery_candidate_id=material["delivery_candidate_id"],
        candidate_public_id=material["candidate_public_id"],
        candidate_digest=material["candidate_digest"],
        candidate_version=material["candidate_version"],
        result_envelope_id=material["result_envelope_id"],
        result_envelope_public_id=material["result_envelope_public_id"],
        result_digest=material["result_digest"],
        owner_acceptance_id=material["owner_acceptance_id"],
        result_review_decision_digest=material[
            "result_review_decision_digest"
        ],
        run_id=material["run_id"],
        task_id=material["task_id"],
        task_version=material["task_version"],
        pack_id=material["pack_id"],
        pack_version=material["pack_version"],
        approved_instruction_digest=material["approved_instruction_digest"],
        source_snapshot_identity=material["source_snapshot_identity"],
        source_workspace_identity=material["source_workspace_identity"],
        run_workspace_identity=material["run_workspace_identity"],
        run_workspace_baseline_identity=material[
            "run_workspace_baseline_identity"
        ],
        run_workspace_post_state_identity=material[
            "run_workspace_post_state_identity"
        ],
        verification_policy=material["verification_policy"],
        verification_verdict=material["verification_verdict"],
        verification_receipt_identity=material[
            "verification_receipt_identity"
        ],
        source_drift_evaluation_id=material["source_drift_evaluation_id"],
        source_drift_state=material["source_drift_state"],
        drift_semantic_fingerprint=material["drift_semantic_fingerprint"],
        sanitized_repository_identity=material["sanitized_repository_identity"],
        repository_locator_fingerprint=material["repository_locator_fingerprint"],
        repository_fingerprint=material["repository_fingerprint"],
        branch=material["branch"],
        observed_head=material["observed_head"],
        current_source_digest=material["current_source_digest"],
        index_fingerprint=material["index_fingerprint"],
        worktree_fingerprint=material["worktree_fingerprint"],
        staged_path_count=material["staged_path_count"],
        policy_version=material["policy_version"],
        plan_version=plan_version,
        status_at_creation=material["status_at_creation"],
        candidate_entry_count=material["candidate_entry_count"],
        classified_entry_count=material["classified_entry_count"],
        operation_order_json=canonical_json(material["operation_order"]),
        scope_findings_json=canonical_json(material["scope_findings"]),
        included_paths_json=canonical_json(material["included_paths"]),
        excluded_paths_json=canonical_json(material["excluded_paths"]),
        blocked_paths_json=canonical_json(material["blocked_paths"]),
        unexpected_findings_json=canonical_json(material["unexpected_findings"]),
        conflict_findings_json=canonical_json(material["conflict_findings"]),
        global_preconditions_json=canonical_json(material["global_preconditions"]),
        reversibility_requirements_json=canonical_json(
            material["reversibility_requirements"]
        ),
        pre_apply_checks_json=canonical_json(material["pre_apply_checks"]),
        post_apply_checks_json=canonical_json(material["post_apply_checks"]),
        explicit_boundaries_json=canonical_json(material["explicit_boundaries"]),
        blocker_codes_json=canonical_json(material["blockers"]),
        diagnostics_json=canonical_json(material["diagnostics"]),
        binding_digest=material["binding_digest"],
        plan_digest=plan_digest,
        supersedes_plan_id=latest.id if latest is not None else None,
        supersession_reason=(
            supersession_reason
        ),
        expires_at=None,
    )
    session.add(plan)
    session.flush()
    for entry in material["entries"]:
        session.add(
            ApplyPlanEntry(
                apply_plan_id=plan.id,
                manifest_ordinal=entry["manifest_ordinal"],
                operation_ordinal=entry["operation_ordinal"],
                repository_path=entry["repository_path"],
                display_path=entry["display_path"],
                path_identity=entry["path_identity"],
                operation=entry["operation"],
                disposition=entry["disposition"],
                reason_code=entry["reason_code"],
                reason=entry["reason"],
                unexpected=entry["unexpected"],
                content_kind=entry["content_kind"],
                before_hash=entry["before_hash"],
                after_hash=entry["after_hash"],
                before_size=entry["before_size"],
                after_size=entry["after_size"],
                before_mode=entry["before_mode"],
                after_mode=entry["after_mode"],
                evidence_identity=entry["evidence_identity"],
                conflicts_json=canonical_json(entry["conflicts"]),
                preconditions_json=canonical_json(entry["preconditions"]),
                reversibility_json=canonical_json(entry["reversibility"]),
                validation_json=canonical_json(entry["validation"]),
            )
        )
    session.flush()
    return plan, True


def _stored_entries(session: Session, plan: ApplyPlan) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(ApplyPlanEntry)
            .where(ApplyPlanEntry.apply_plan_id == plan.id)
            .order_by(ApplyPlanEntry.manifest_ordinal)
        ).all()
    )
    return [
        {
            "manifest_ordinal": row.manifest_ordinal,
            "operation_ordinal": row.operation_ordinal,
            "repository_path": row.repository_path,
            "display_path": row.display_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
            "disposition": row.disposition,
            "reason_code": row.reason_code,
            "reason": row.reason,
            "unexpected": row.unexpected,
            "content_kind": row.content_kind,
            "before_hash": row.before_hash,
            "after_hash": row.after_hash,
            "before_size": row.before_size,
            "after_size": row.after_size,
            "before_mode": row.before_mode,
            "after_mode": row.after_mode,
            "evidence_identity": row.evidence_identity,
            "conflicts": _decoded_list(row.conflicts_json),
            "preconditions": _decoded_list(row.preconditions_json),
            "reversibility": _decoded_object(row.reversibility_json),
            "validation": _decoded_list(row.validation_json),
        }
        for row in rows
    ]


def _stored_plan_material(session: Session, plan: ApplyPlan) -> dict[str, Any]:
    predecessor = (
        session.get(ApplyPlan, plan.supersedes_plan_id)
        if plan.supersedes_plan_id is not None
        else None
    )
    return {
        "owner_id": plan.owner_id,
        "delivery_candidate_id": plan.delivery_candidate_id,
        "candidate_public_id": plan.candidate_public_id,
        "candidate_digest": plan.candidate_digest,
        "candidate_version": plan.candidate_version,
        "result_envelope_id": plan.result_envelope_id,
        "result_envelope_public_id": plan.result_envelope_public_id,
        "result_digest": plan.result_digest,
        "owner_acceptance_id": plan.owner_acceptance_id,
        "result_review_decision_digest": plan.result_review_decision_digest,
        "run_id": plan.run_id,
        "task_id": plan.task_id,
        "task_version": plan.task_version,
        "pack_id": plan.pack_id,
        "pack_version": plan.pack_version,
        "approved_instruction_digest": plan.approved_instruction_digest,
        "source_snapshot_identity": plan.source_snapshot_identity,
        "source_workspace_identity": plan.source_workspace_identity,
        "run_workspace_identity": plan.run_workspace_identity,
        "run_workspace_baseline_identity": plan.run_workspace_baseline_identity,
        "run_workspace_post_state_identity": (
            plan.run_workspace_post_state_identity
        ),
        "verification_policy": plan.verification_policy,
        "verification_verdict": plan.verification_verdict,
        "verification_receipt_identity": plan.verification_receipt_identity,
        "source_drift_evaluation_id": plan.source_drift_evaluation_id,
        "source_drift_state": plan.source_drift_state,
        "drift_semantic_fingerprint": plan.drift_semantic_fingerprint,
        "sanitized_repository_identity": plan.sanitized_repository_identity,
        "repository_locator_fingerprint": plan.repository_locator_fingerprint,
        "repository_fingerprint": plan.repository_fingerprint,
        "branch": plan.branch,
        "observed_head": plan.observed_head,
        "current_source_digest": plan.current_source_digest,
        "index_fingerprint": plan.index_fingerprint,
        "worktree_fingerprint": plan.worktree_fingerprint,
        "staged_path_count": plan.staged_path_count,
        "policy_version": plan.policy_version,
        "status_at_creation": plan.status_at_creation,
        "candidate_entry_count": plan.candidate_entry_count,
        "classified_entry_count": plan.classified_entry_count,
        "entries": _stored_entries(session, plan),
        "operation_order": _decoded_object(plan.operation_order_json),
        "scope_findings": _decoded_list(plan.scope_findings_json),
        "included_paths": _decoded_list(plan.included_paths_json),
        "excluded_paths": _decoded_list(plan.excluded_paths_json),
        "blocked_paths": _decoded_list(plan.blocked_paths_json),
        "unexpected_findings": _decoded_list(plan.unexpected_findings_json),
        "conflict_findings": _decoded_list(plan.conflict_findings_json),
        "global_preconditions": _decoded_list(plan.global_preconditions_json),
        "reversibility_requirements": _decoded_object(
            plan.reversibility_requirements_json
        ),
        "pre_apply_checks": _decoded_list(plan.pre_apply_checks_json),
        "post_apply_checks": _decoded_list(plan.post_apply_checks_json),
        "explicit_boundaries": _decoded_list(plan.explicit_boundaries_json),
        "blockers": _decoded_list(plan.blocker_codes_json),
        "diagnostics": _decoded_object(plan.diagnostics_json),
        "binding_digest": plan.binding_digest,
        "supersedes_plan_digest": predecessor.plan_digest if predecessor else "",
        "supersession_reason": plan.supersession_reason,
        "expires_at": _timestamp_identity(plan.expires_at),
    }


def validate_apply_plan_integrity(session: Session, plan: ApplyPlan) -> bool:
    material = _stored_plan_material(session, plan)
    calculated_binding_digest = canonical_sha256(
        _binding_digest_payload(material)
    )
    calculated = canonical_sha256(
        _plan_digest_payload(
            material,
            plan_version=plan.plan_version,
            supersedes_plan_digest=material["supersedes_plan_digest"],
        )
    )
    if not (
        calculated == plan.plan_digest
        and calculated_binding_digest == plan.binding_digest
        and plan.plan_id == "ap_" + plan.plan_digest[:40]
        and plan.candidate_entry_count == plan.classified_entry_count
        and plan.classified_entry_count == len(material["entries"])
        and plan.plan_version >= 1
        and plan.staged_path_count >= 0
        and SHA256_PATTERN.fullmatch(plan.plan_digest or "")
        and SHA256_PATTERN.fullmatch(plan.binding_digest or "")
        and SHA256_PATTERN.fullmatch(plan.drift_semantic_fingerprint or "")
    ):
        return False

    predecessor = (
        session.get(ApplyPlan, plan.supersedes_plan_id)
        if plan.supersedes_plan_id is not None
        else None
    )
    if plan.plan_version == 1:
        if predecessor is not None or plan.supersedes_plan_id is not None:
            return False
    elif (
        predecessor is None
        or predecessor.owner_id != plan.owner_id
        or predecessor.run_id != plan.run_id
        or predecessor.plan_version + 1 != plan.plan_version
        or predecessor.plan_digest != material["supersedes_plan_digest"]
    ):
        return False

    drift = session.get(SourceDriftEvaluation, plan.source_drift_evaluation_id)
    if (
        drift is None
        or drift.owner_id != plan.owner_id
        or drift.run_id != plan.run_id
        or drift.task_id != plan.task_id
        or drift.candidate_id != plan.delivery_candidate_id
        or drift.status != plan.source_drift_state
        or drift_semantic_fingerprint(drift) != plan.drift_semantic_fingerprint
    ):
        return False

    run = session.get(CodexRun, plan.run_id)
    if run is None:
        return False

    candidate = (
        session.get(DeliveryCandidate, plan.delivery_candidate_id)
        if plan.delivery_candidate_id is not None
        else None
    )
    if candidate is None:
        if (
            plan.delivery_candidate_id is not None
            or plan.candidate_public_id
            or plan.candidate_digest
        ):
            return False
    elif (
        candidate.owner_id != plan.owner_id
        or candidate.run_id != plan.run_id
        or candidate.task_id != plan.task_id
        or candidate.task_version != plan.task_version
        or candidate.pack_id != plan.pack_id
        or candidate.pack_version != plan.pack_version
        or candidate.candidate_id != plan.candidate_public_id
        or candidate.candidate_digest != plan.candidate_digest
        or candidate.source_snapshot_identity != plan.source_snapshot_identity
    ):
        return False

    if _plan_has_result_lineage(plan):
        if candidate is None:
            return False
        lineage, lineage_blockers = _candidate_result_lineage(
            session,
            owner_id=plan.owner_id,
            candidate=candidate,
        )
        if lineage_blockers or (
            candidate.candidate_version != plan.candidate_version
            or lineage["result_envelope_id"] != plan.result_envelope_id
            or lineage["result_envelope_public_id"]
            != plan.result_envelope_public_id
            or lineage["result_digest"] != plan.result_digest
            or lineage["owner_acceptance_id"] != plan.owner_acceptance_id
            or lineage["result_review_decision_digest"]
            != plan.result_review_decision_digest
            or lineage["approved_instruction_digest"]
            != plan.approved_instruction_digest
            or lineage["source_workspace_identity"]
            != plan.source_workspace_identity
            or lineage["run_workspace_identity"]
            != plan.run_workspace_identity
            or lineage["run_workspace_baseline_identity"]
            != plan.run_workspace_baseline_identity
            or lineage["run_workspace_post_state_identity"]
            != plan.run_workspace_post_state_identity
            or lineage["verification_policy"] != plan.verification_policy
            or lineage["verification_verdict"] != plan.verification_verdict
            or lineage["verification_receipt_identity"]
            != plan.verification_receipt_identity
        ):
            return False
        if any(
            not SHA256_PATTERN.fullmatch(value or "")
            for value in (
                plan.result_digest,
                plan.result_review_decision_digest,
                plan.approved_instruction_digest,
                plan.source_workspace_identity,
                plan.run_workspace_identity,
                plan.run_workspace_baseline_identity,
                plan.run_workspace_post_state_identity,
            )
        ):
            return False
    elif any(
        (
            plan.result_envelope_id is not None,
            bool(plan.result_envelope_public_id),
            bool(plan.result_digest),
            plan.owner_acceptance_id is not None,
            bool(plan.result_review_decision_digest),
            bool(plan.source_workspace_identity),
            bool(plan.run_workspace_identity),
            bool(plan.run_workspace_baseline_identity),
            bool(plan.run_workspace_post_state_identity),
        )
    ):
        # Defensive completeness guard for a partially migrated Plan.
        return False

    if plan.expires_at is not None and plan.expires_at <= plan.created_at:
        return False
    if plan.sanitized_repository_identity and (
        "/" in plan.sanitized_repository_identity
        or "\\" in plan.sanitized_repository_identity
        or len(plan.sanitized_repository_identity) > 160
    ):
        return False
    for fingerprint in (
        plan.repository_locator_fingerprint,
        plan.repository_fingerprint,
        plan.current_source_digest,
        plan.index_fingerprint,
        plan.worktree_fingerprint,
    ):
        if fingerprint and not SHA256_PATTERN.fullmatch(fingerprint):
            return False
    return True


def get_apply_plan_approval(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
) -> ApplyPlanApproval | None:
    return session.scalar(
        select(ApplyPlanApproval).where(
            ApplyPlanApproval.owner_id == owner_id,
            ApplyPlanApproval.apply_plan_id == plan.id,
        )
    )


def _approval_digest_payload(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "twos.apply_plan_approval.v1",
        "policy_version": APPLY_PLAN_POLICY_VERSION,
        "owner_id": material["owner_id"],
        "apply_plan_id": material["apply_plan_id"],
        "plan_public_id": material["plan_public_id"],
        "plan_digest": material["plan_digest"],
        "delivery_candidate_id": material["delivery_candidate_id"],
        "candidate_public_id": material["candidate_public_id"],
        "candidate_version": material["candidate_version"],
        "candidate_digest": material["candidate_digest"],
        "result_envelope_id": material["result_envelope_id"],
        "result_envelope_public_id": material["result_envelope_public_id"],
        "result_digest": material["result_digest"],
        "owner_acceptance_id": material["owner_acceptance_id"],
        "result_review_decision_digest": material[
            "result_review_decision_digest"
        ],
        "source_workspace_identity": material["source_workspace_identity"],
        "run_workspace_identity": material["run_workspace_identity"],
        "run_workspace_baseline_identity": material[
            "run_workspace_baseline_identity"
        ],
        "run_workspace_post_state_identity": material[
            "run_workspace_post_state_identity"
        ],
        "approval_state": "APPROVED",
        "approved_by_user_id": material["approved_by_user_id"],
        "approved_at": material["approved_at"],
    }


def _stored_approval_material(approval: ApplyPlanApproval) -> dict[str, Any]:
    return {
        "owner_id": approval.owner_id,
        "apply_plan_id": approval.apply_plan_id,
        "plan_public_id": approval.plan_public_id,
        "plan_digest": approval.plan_digest,
        "delivery_candidate_id": approval.delivery_candidate_id,
        "candidate_public_id": approval.candidate_public_id,
        "candidate_version": approval.candidate_version,
        "candidate_digest": approval.candidate_digest,
        "result_envelope_id": approval.result_envelope_id,
        "result_envelope_public_id": approval.result_envelope_public_id,
        "result_digest": approval.result_digest,
        "owner_acceptance_id": approval.owner_acceptance_id,
        "result_review_decision_digest": (
            approval.result_review_decision_digest
        ),
        "source_workspace_identity": approval.source_workspace_identity,
        "run_workspace_identity": approval.run_workspace_identity,
        "run_workspace_baseline_identity": (
            approval.run_workspace_baseline_identity
        ),
        "run_workspace_post_state_identity": (
            approval.run_workspace_post_state_identity
        ),
        "approval_state": approval.approval_state,
        "approved_by_user_id": approval.approved_by_user_id,
        "approved_at": _timestamp_identity(approval.approved_at),
    }


def validate_apply_plan_approval(
    session: Session,
    approval: ApplyPlanApproval,
    *,
    plan: ApplyPlan | None = None,
    owner_id: int | None = None,
) -> bool:
    bound_plan = plan or session.get(ApplyPlan, approval.apply_plan_id)
    acceptance = (
        session.get(OwnerAcceptanceSession, bound_plan.owner_acceptance_id)
        if bound_plan is not None and bound_plan.owner_acceptance_id is not None
        else None
    )
    if (
        bound_plan is None
        or acceptance is None
        or not _plan_has_result_lineage(bound_plan)
        or not validate_apply_plan_integrity(session, bound_plan)
        or (owner_id is not None and approval.owner_id != owner_id)
    ):
        return False
    material = _stored_approval_material(approval)
    calculated = canonical_sha256(_approval_digest_payload(material))
    return bool(
        approval.approval_state == "APPROVED"
        and approval.approved_by_user_id == approval.owner_id
        and approval.approved_at is not None
        and acceptance.decided_at is not None
        and approval.approved_at >= acceptance.decided_at
        and approval.approved_at >= bound_plan.created_at
        and SHA256_PATTERN.fullmatch(approval.approval_digest or "")
        and calculated == approval.approval_digest
        and approval.approval_id == "apa_" + approval.approval_digest[:40]
        and approval.owner_id == bound_plan.owner_id
        and approval.apply_plan_id == bound_plan.id
        and approval.plan_public_id == bound_plan.plan_id
        and approval.plan_digest == bound_plan.plan_digest
        and approval.delivery_candidate_id == bound_plan.delivery_candidate_id
        and approval.candidate_public_id == bound_plan.candidate_public_id
        and approval.candidate_version == bound_plan.candidate_version
        and approval.candidate_digest == bound_plan.candidate_digest
        and approval.result_envelope_id == bound_plan.result_envelope_id
        and approval.result_envelope_public_id
        == bound_plan.result_envelope_public_id
        and approval.result_digest == bound_plan.result_digest
        and approval.owner_acceptance_id == bound_plan.owner_acceptance_id
        and approval.result_review_decision_digest
        == bound_plan.result_review_decision_digest
        and approval.source_workspace_identity
        == bound_plan.source_workspace_identity
        and approval.run_workspace_identity == bound_plan.run_workspace_identity
        and approval.run_workspace_baseline_identity
        == bound_plan.run_workspace_baseline_identity
        and approval.run_workspace_post_state_identity
        == bound_plan.run_workspace_post_state_identity
    )


def create_apply_plan_approval(
    session: Session,
    *,
    owner_id: int,
    plan: ApplyPlan,
    source_repo: Path,
    confirmed: bool,
    approved_by_user_id: int | None = None,
    expected_plan_digest: str | None = None,
    expected_candidate_digest: str | None = None,
    expected_result_digest: str | None = None,
    expected_result_review_decision_digest: str | None = None,
) -> tuple[ApplyPlanApproval, bool]:
    """Persist one immutable Owner approval for an exact current Plan.

    Approval is intentionally separate from the later literal Apply mutation
    confirmation. Historical Plans cannot acquire a synthesized approval.
    """
    if plan.owner_id != owner_id:
        raise ApplyPlanError("APPLY_PLAN_NOT_FOUND", "The Apply Plan is unavailable.")
    if confirmed is not True:
        raise ApplyPlanError(
            "PLAN_APPROVAL_CONFIRMATION_REQUIRED",
            "Apply Plan approval requires an explicit Owner confirmation.",
        )
    if approved_by_user_id not in {None, owner_id}:
        raise ApplyPlanError(
            "PLAN_APPROVAL_OWNER_MISMATCH",
            "Only the authenticated Owner may approve this Apply Plan.",
        )
    if not _plan_has_result_lineage(plan):
        raise ApplyPlanError(
            "LEGACY_PLAN_APPROVAL_UNSUPPORTED",
            "This historical Apply Plan retains its original Apply-confirmation boundary and cannot receive a Result-bound approval.",
        )
    if plan.candidate_entry_count <= 0 or not _decoded_list(
        plan.included_paths_json
    ):
        raise ApplyPlanError(
            "RESULT_HAS_NO_DELIVERABLE_CHANGES",
            "A no-change Result cannot produce an approvable Apply Plan.",
        )
    expected_bindings = (
        (expected_plan_digest, plan.plan_digest, "EXPECTED_PLAN_DIGEST_MISMATCH"),
        (
            expected_candidate_digest,
            plan.candidate_digest,
            "EXPECTED_CANDIDATE_DIGEST_MISMATCH",
        ),
        (expected_result_digest, plan.result_digest, "EXPECTED_RESULT_DIGEST_MISMATCH"),
        (
            expected_result_review_decision_digest,
            plan.result_review_decision_digest,
            "EXPECTED_RESULT_REVIEW_DIGEST_MISMATCH",
        ),
    )
    for expected, actual, code in expected_bindings:
        if expected is not None and expected != actual:
            raise ApplyPlanError(code, "The confirmed delivery binding is stale.")
    existing = get_apply_plan_approval(
        session,
        owner_id=owner_id,
        plan=plan,
    )
    if existing is not None:
        if not validate_apply_plan_approval(
            session,
            existing,
            plan=plan,
            owner_id=owner_id,
        ):
            raise ApplyPlanError(
                "PLAN_APPROVAL_INVALID",
                "The persisted Apply Plan approval failed its integrity check.",
            )
        return existing, False
    effective_state, blockers = effective_apply_plan_state(
        session,
        plan,
        source_repo=source_repo,
        require_approval=False,
    )
    if effective_state not in {
        "ready_for_owner_review",
        "review_with_source_changes",
    }:
        first = blockers[0] if blockers else {
            "code": "PLAN_NOT_APPROVABLE",
            "message": "The Apply Plan is not current and approvable.",
        }
        raise ApplyPlanError(str(first["code"]), str(first["message"]))
    approved_at = utc_now()
    material = {
        "owner_id": owner_id,
        "apply_plan_id": plan.id,
        "plan_public_id": plan.plan_id,
        "plan_digest": plan.plan_digest,
        "delivery_candidate_id": plan.delivery_candidate_id,
        "candidate_public_id": plan.candidate_public_id,
        "candidate_version": plan.candidate_version,
        "candidate_digest": plan.candidate_digest,
        "result_envelope_id": plan.result_envelope_id,
        "result_envelope_public_id": plan.result_envelope_public_id,
        "result_digest": plan.result_digest,
        "owner_acceptance_id": plan.owner_acceptance_id,
        "result_review_decision_digest": plan.result_review_decision_digest,
        "source_workspace_identity": plan.source_workspace_identity,
        "run_workspace_identity": plan.run_workspace_identity,
        "run_workspace_baseline_identity": plan.run_workspace_baseline_identity,
        "run_workspace_post_state_identity": (
            plan.run_workspace_post_state_identity
        ),
        "approval_state": "APPROVED",
        "approved_by_user_id": owner_id,
        "approved_at": _timestamp_identity(approved_at),
    }
    approval_digest = canonical_sha256(_approval_digest_payload(material))
    approval = ApplyPlanApproval(
        approval_id="apa_" + approval_digest[:40],
        owner_id=owner_id,
        apply_plan_id=plan.id,
        plan_public_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        delivery_candidate_id=int(plan.delivery_candidate_id),
        candidate_public_id=plan.candidate_public_id,
        candidate_version=plan.candidate_version,
        candidate_digest=plan.candidate_digest,
        result_envelope_id=int(plan.result_envelope_id),
        result_envelope_public_id=plan.result_envelope_public_id,
        result_digest=plan.result_digest,
        owner_acceptance_id=int(plan.owner_acceptance_id),
        result_review_decision_digest=plan.result_review_decision_digest,
        source_workspace_identity=plan.source_workspace_identity,
        run_workspace_identity=plan.run_workspace_identity,
        run_workspace_baseline_identity=plan.run_workspace_baseline_identity,
        run_workspace_post_state_identity=plan.run_workspace_post_state_identity,
        approval_state="APPROVED",
        approved_by_user_id=owner_id,
        approved_at=approved_at,
        approval_digest=approval_digest,
    )
    session.add(approval)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        replay = get_apply_plan_approval(session, owner_id=owner_id, plan=plan)
        if replay is None or not validate_apply_plan_approval(
            session, replay, plan=plan, owner_id=owner_id
        ):
            raise ApplyPlanError(
                "CONCURRENT_PLAN_APPROVAL",
                "A conflicting Apply Plan approval was created concurrently.",
            )
        return replay, False
    return approval, True


def get_or_create_apply_plan_approval(
    session: Session,
    **kwargs: Any,
) -> tuple[ApplyPlanApproval, bool]:
    """Stable service alias for route and bootstrap callers."""
    return create_apply_plan_approval(session, **kwargs)


def apply_plan_approval_out(approval: ApplyPlanApproval) -> dict[str, Any]:
    return {
        "id": approval.approval_id,
        "state": approval.approval_state,
        "approved_at": _timestamp_identity(approval.approved_at),
        "apply_plan_id": approval.plan_public_id,
        "candidate_id": approval.candidate_public_id,
        "candidate_version": approval.candidate_version,
        "result_envelope_id": approval.result_envelope_public_id,
        "advanced": {
            "approval_digest": approval.approval_digest,
            "plan_digest": approval.plan_digest,
            "candidate_digest": approval.candidate_digest,
            "result_digest": approval.result_digest,
            "result_review_decision_digest": (
                approval.result_review_decision_digest
            ),
            "source_workspace_identity": approval.source_workspace_identity,
            "run_workspace_identity": approval.run_workspace_identity,
            "run_workspace_baseline_identity": (
                approval.run_workspace_baseline_identity
            ),
            "run_workspace_post_state_identity": (
                approval.run_workspace_post_state_identity
            ),
        },
    }


def effective_apply_plan_state(
    session: Session,
    plan: ApplyPlan,
    *,
    source_repo: Path,
    policy_version: str = APPLY_PLAN_POLICY_VERSION,
    repository_observation: object = _OBSERVATION_UNSET,
    require_approval: bool = True,
) -> tuple[str, list[dict[str, str]]]:
    reasons: list[dict[str, str]] = []
    if not validate_apply_plan_integrity(session, plan):
        reasons.append(
            {
                "code": "PLAN_INTEGRITY_INVALID",
                "message": "The immutable Apply Plan failed its integrity check.",
            }
        )
    successor = session.scalar(
        select(ApplyPlan).where(ApplyPlan.supersedes_plan_id == plan.id)
    )
    if successor is not None:
        reasons.append(
            {
                "code": "PLAN_SUPERSEDED",
                "message": f"A newer immutable Plan version ({successor.plan_version}) supersedes this Plan.",
            }
        )
    if plan.expires_at is not None and plan.expires_at <= utc_now():
        reasons.append(
            {
                "code": "PLAN_TIME_EXPIRED",
                "message": "The immutable Plan reached its policy-defined expiry time.",
            }
        )
    if plan.policy_version != policy_version:
        reasons.append(
            {
                "code": "POLICY_VERSION_CHANGED",
                "message": "The server-defined Apply Plan policy version changed.",
            }
        )
    run = session.get(CodexRun, plan.run_id)
    if run is None:
        reasons.append(
            {
                "code": "RUN_BINDING_UNAVAILABLE",
                "message": "The Plan-bound Run is unavailable.",
            }
        )
    candidate = (
        session.get(DeliveryCandidate, plan.delivery_candidate_id)
        if plan.delivery_candidate_id is not None
        else None
    )
    if plan.delivery_candidate_id is not None:
        if candidate is None or candidate.candidate_digest != plan.candidate_digest:
            reasons.append(
                {
                    "code": "CANDIDATE_BINDING_CHANGED",
                    "message": "The Plan no longer binds the same immutable Candidate.",
                }
            )
        elif run is not None and not validate_delivery_candidate(
            session, plan.owner_id, run, candidate
        ).get("eligible"):
            reasons.append(
                {
                    "code": "CANDIDATE_NO_LONGER_CURRENT",
                    "message": "The Candidate no longer satisfies current eligibility bindings.",
                }
            )
    else:
        current_candidate = session.scalar(
            select(DeliveryCandidate).where(
                DeliveryCandidate.owner_id == plan.owner_id,
                DeliveryCandidate.run_id == plan.run_id,
            )
        )
        if current_candidate is not None:
            reasons.append(
                {
                    "code": "CANDIDATE_BINDING_CHANGED",
                    "message": "A Candidate is now available for the Plan-bound Run.",
                }
            )

    latest_drift = session.scalar(
        select(SourceDriftEvaluation)
        .where(
            SourceDriftEvaluation.owner_id == plan.owner_id,
            SourceDriftEvaluation.run_id == plan.run_id,
        )
        .order_by(SourceDriftEvaluation.id.desc())
    )
    if (
        latest_drift is not None
        and drift_semantic_fingerprint(latest_drift)
        != plan.drift_semantic_fingerprint
    ):
        reasons.append(
            {
                "code": "SOURCE_DRIFT_CHANGED",
                "message": "The latest Source Drift evidence no longer matches this Plan.",
            }
        )

    if run is not None:
        if repository_observation is _OBSERVATION_UNSET:
            try:
                observation = observe_repository(run, source_repo)
            except (OSError, ValueError, RuntimeError):
                observation = None
        else:
            observation = (
                repository_observation
                if isinstance(repository_observation, dict)
                else None
            )
        if observation is None:
            if plan.repository_fingerprint:
                reasons.append(
                    {
                        "code": "REPOSITORY_BINDING_UNAVAILABLE",
                        "message": "The current repository binding cannot be verified.",
                    }
                )
        else:
            current = (
                observation["repository_locator_fingerprint"],
                observation["repository_fingerprint"],
                observation["branch"],
                observation["observed_head"],
                observation["index_fingerprint"],
                observation["worktree_fingerprint"],
            )
            stored = (
                plan.repository_locator_fingerprint,
                plan.repository_fingerprint,
                plan.branch,
                plan.observed_head,
                plan.index_fingerprint,
                plan.worktree_fingerprint,
            )
            if current != stored:
                reasons.append(
                    {
                        "code": "REPOSITORY_BINDING_CHANGED",
                        "message": "Repository, branch, HEAD, index, or worktree binding changed.",
                    }
                )
    if reasons:
        return "expired", _unique_blockers(reasons)
    if (
        require_approval
        and _plan_has_result_lineage(plan)
        and plan.status_at_creation
        in {"ready_for_owner_review", "review_with_source_changes"}
    ):
        approval = get_apply_plan_approval(
            session,
            owner_id=plan.owner_id,
            plan=plan,
        )
        if approval is None:
            return (
                "awaiting_owner_approval",
                [
                    {
                        "code": "PLAN_APPROVAL_REQUIRED",
                        "message": "The Owner must explicitly approve this exact current Apply Plan before Apply.",
                    }
                ],
            )
        if not validate_apply_plan_approval(
            session,
            approval,
            plan=plan,
            owner_id=plan.owner_id,
        ):
            return (
                "expired",
                [
                    {
                        "code": "PLAN_APPROVAL_INVALID",
                        "message": "The persisted Apply Plan approval no longer matches the immutable delivery lineage.",
                    }
                ],
            )
    return plan.status_at_creation, []


def _next_action_for_state(
    state: str, blockers: list[dict[str, str]]
) -> str:
    if state == "awaiting_owner_approval":
        return "Explicitly approve this exact current Apply Plan before confirming Apply."
    if state == "ready_for_owner_review":
        return (
            "Explicitly choose Apply Accepted Changes to run a fresh preflight and "
            "open the final source-mutation confirmation."
        )
    if state == "review_with_source_changes":
        return (
            "Review the unrelated source changes before explicitly choosing Apply "
            "Accepted Changes."
        )
    if state == "expired":
        return (
            "Review Apply Plan again to create a freshly bound Plan before Apply."
        )
    reason = blockers[0]["message"] if blockers else "The Apply Plan is blocked."
    return f"{reason} Resolve the blocker and review again before Apply."


def apply_plan_out(
    session: Session,
    plan: ApplyPlan,
    *,
    source_repo: Path,
) -> dict[str, Any]:
    effective_state, expiry_reasons = effective_apply_plan_state(
        session, plan, source_repo=source_repo
    )
    approval = (
        get_apply_plan_approval(session, owner_id=plan.owner_id, plan=plan)
        if _plan_has_result_lineage(plan)
        else None
    )
    approval_valid = bool(
        approval is not None
        and validate_apply_plan_approval(
            session, approval, plan=plan, owner_id=plan.owner_id
        )
    )
    entries = _stored_entries(session, plan)
    blockers = (
        expiry_reasons
        if expiry_reasons
        else [
            {
                "code": str(item.get("code") or "APPLY_PLAN_BLOCKED"),
                "message": str(item.get("message") or "The Apply Plan is blocked."),
            }
            for item in _decoded_list(plan.blocker_codes_json)
            if isinstance(item, dict)
        ]
    )
    default_entries = [
        {
            "path": entry["display_path"],
            "operation": entry["operation"],
            "disposition": entry["disposition"],
            "reason": entry["reason"],
            "unexpected": entry["unexpected"],
            "content_kind": entry["content_kind"],
            "conflicts": entry["conflicts"],
            "preconditions": entry["preconditions"],
            "reversibility": entry["reversibility"],
        }
        for entry in entries
    ]
    advanced_entries = [
        {
            "path": entry["display_path"],
            "path_identity": entry["path_identity"],
            "manifest_ordinal": entry["manifest_ordinal"],
            "operation_ordinal": entry["operation_ordinal"],
            "operation": entry["operation"],
            "disposition": entry["disposition"],
            "reason_code": entry["reason_code"],
            "before_hash": entry["before_hash"],
            "after_hash": entry["after_hash"],
            "before_size": entry["before_size"],
            "after_size": entry["after_size"],
            "before_mode": entry["before_mode"],
            "after_mode": entry["after_mode"],
            "content_kind": entry["content_kind"],
            "evidence_identity": entry["evidence_identity"],
        }
        for entry in entries
    ]
    return {
        "id": plan.plan_id,
        "version": plan.plan_version,
        "effective_state": effective_state,
        "status_label": READINESS_LABELS[effective_state],
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
        "approval": (
            apply_plan_approval_out(approval) if approval_valid and approval else None
        ),
        "status_at_creation": plan.status_at_creation,
        "candidate_status_label": (
            "Available" if plan.delivery_candidate_id is not None else "Candidate unavailable"
        ),
        "candidate": {
            "id": plan.candidate_public_id or None,
            "version": plan.candidate_version,
        },
        "result_review_state": (
            "accepted_for_delivery" if _plan_has_result_lineage(plan) else None
        ),
        "drift_status": plan.source_drift_state,
        "drift_status_label": DRIFT_STATUS_LABELS.get(
            plan.source_drift_state, "Repository unavailable"
        ),
        "candidate_entry_count": plan.candidate_entry_count,
        "classified_entry_count": plan.classified_entry_count,
        "entries": default_entries,
        "scope_exclusions": _decoded_list(plan.scope_findings_json),
        "conflicts": _decoded_list(plan.conflict_findings_json),
        "unexpected_files": _decoded_list(plan.unexpected_findings_json),
        "future_preconditions": _decoded_list(plan.global_preconditions_json),
        "reversibility_requirements": _decoded_object(
            plan.reversibility_requirements_json
        ),
        "planned_validation": {
            "pre_apply": _decoded_list(plan.pre_apply_checks_json),
            "post_apply": _decoded_list(plan.post_apply_checks_json),
        },
        "boundaries": _decoded_list(plan.explicit_boundaries_json),
        "blockers": blockers,
        "next_action": _next_action_for_state(effective_state, blockers),
        "created_at": plan.created_at.isoformat() + "Z",
        "advanced": {
            "plan_digest": plan.plan_digest,
            "binding_digest": plan.binding_digest,
            "candidate_id": plan.candidate_public_id or None,
            "candidate_digest": plan.candidate_digest or None,
            "candidate_version": plan.candidate_version,
            "result_envelope_id": plan.result_envelope_public_id or None,
            "result_digest": plan.result_digest or None,
            "owner_acceptance_id": plan.owner_acceptance_id,
            "result_review_decision_digest": (
                plan.result_review_decision_digest or None
            ),
            "approved_instruction_digest": (
                plan.approved_instruction_digest or None
            ),
            "source_workspace_identity": (
                plan.source_workspace_identity or None
            ),
            "run_workspace_identity": plan.run_workspace_identity or None,
            "run_workspace_baseline_identity": (
                plan.run_workspace_baseline_identity or None
            ),
            "run_workspace_post_state_identity": (
                plan.run_workspace_post_state_identity or None
            ),
            "verification": {
                "policy": plan.verification_policy,
                "verdict": plan.verification_verdict,
                "receipt_identity": plan.verification_receipt_identity or None,
            },
            "apply_plan_approval_id": (
                approval.approval_id if approval_valid and approval else None
            ),
            "apply_plan_approval_digest": (
                approval.approval_digest if approval_valid and approval else None
            ),
            "drift_evaluation_id": plan.source_drift_evaluation_id,
            "drift_semantic_fingerprint": plan.drift_semantic_fingerprint,
            "repository_identity": plan.sanitized_repository_identity or None,
            "repository_locator_fingerprint": (
                plan.repository_locator_fingerprint or None
            ),
            "repository_fingerprint": plan.repository_fingerprint or None,
            "branch": plan.branch or None,
            "head": plan.observed_head or None,
            "current_source_digest": plan.current_source_digest or None,
            "index_fingerprint": plan.index_fingerprint or None,
            "worktree_fingerprint": plan.worktree_fingerprint or None,
            "staged_path_count": plan.staged_path_count,
            "policy_version": plan.policy_version,
            "operation_order": _decoded_object(plan.operation_order_json),
            "task_binding": {
                "task_id": plan.task_id,
                "task_version": plan.task_version,
            },
            "pack_binding": {
                "pack_id": plan.pack_id,
                "pack_version": plan.pack_version,
            },
            "run_id": plan.run_id,
            "source_snapshot_identity": plan.source_snapshot_identity,
            "supersedes_plan_record": plan.supersedes_plan_id,
            "supersession_reason": plan.supersession_reason or None,
            "expires_at": _timestamp_identity(plan.expires_at),
            "expiry_reasons": expiry_reasons,
            "entries": advanced_entries,
            "diagnostics": _decoded_object(plan.diagnostics_json),
        },
    }


def apply_plan_history(
    session: Session,
    *,
    owner_id: int,
    run_id: int,
    source_repo: Path,
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(ApplyPlan)
            .where(ApplyPlan.owner_id == owner_id, ApplyPlan.run_id == run_id)
            .order_by(ApplyPlan.plan_version.desc())
            .limit(50)
        ).all()
    )
    shared_observation: dict[str, Any] | None = None
    if rows:
        run = session.get(CodexRun, run_id)
        if run is not None:
            try:
                shared_observation = observe_repository(run, source_repo)
            except (OSError, ValueError, RuntimeError):
                shared_observation = None
    history: list[dict[str, Any]] = []
    for row in rows:
        state, _ = effective_apply_plan_state(
            session,
            row,
            source_repo=source_repo,
            repository_observation=shared_observation,
        )
        history.append(
            {
                "id": row.plan_id,
                "version": row.plan_version,
                "status_label": READINESS_LABELS[state],
                "created_at": row.created_at.isoformat() + "Z",
            }
        )
    return history
