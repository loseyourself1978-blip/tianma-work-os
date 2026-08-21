from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .apply_plans import POST_APPLY_CHECK_DEFINITIONS, validate_apply_plan_integrity
from .apply_sessions import (
    APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST,
    ApplySessionError,
    _global_evidence_after_mutation,
    _path_identity,
    _repository_mutation_lock,
    _snapshot_exclusion_reason,
    _state_matches,
    _target_state,
    _verified_repository_root,
    apply_session_entries,
    validate_apply_session_journal,
)
from .delivery_candidates import canonical_json, canonical_sha256, find_owner_run
from .models import (
    ApplyPlan,
    ApplySession,
    CodexInstructionPack,
    CodexRun,
    DeliveryCandidate,
    PostApplyVerification,
)
from .repository_observer import (
    metadata_diagnostics as canonical_metadata_diagnostics,
    semantic_diff as canonical_semantic_diff,
    semantic_projection,
)
from .self_hosting import _source_repository_identity


POST_APPLY_VERIFICATION_POLICY_VERSION = "twos.post_apply_verification.v2"

_GIT_DIRECTORY_PATH_IDENTITY = _path_identity(".git")
_GIT_DIRECTORY_VOLATILE_KEYS = frozenset({"inode", "mtime_ns", "size"})
_INDEX_SEMANTIC_KEYS = (
    "fingerprint",
    "size",
    "mode",
    "staged_path_count",
    "staged_path_identities",
)
_INDEX_VOLATILE_KEYS = ("inode", "mtime_ns")

STATUS_LABELS = {
    "READY": "READY TO VERIFY",
    "VERIFYING": "VERIFYING",
    "PASSED": "PASSED",
    "BLOCKED": "BLOCKED",
    "FAILED": "FAILED",
}

BOUNDARIES = (
    "Verification reads the repository and Git evidence without changing source.",
    "Post-Apply Verification itself performs no Stage, Commit, Push, merge, rebase, tag, branch, or remote change.",
    "Apply, Revert, Candidate creation, and Codex execution are not triggered.",
    "Stage and Local Commit require separate explicit Owner actions after a PASS.",
)

BLOCKER_MESSAGES = {
    "APPLY_SESSION_NOT_APPLIED": "Apply Accepted Changes must finish successfully before verification.",
    "APPLY_INTEGRITY_NOT_PASSED": "The Apply session does not have a passed narrow integrity result.",
    "APPLY_JOURNAL_INVALID": "The immutable Apply journal failed its integrity check.",
    "APPLY_BINDING_INVALID": "The Apply session no longer matches its Plan, Candidate, Run, or source snapshot binding.",
    "APPLIED_PATH_CHANGED": "An applied path no longer matches its approved after-state.",
    "UNEXPECTED_FILE_CREATED": "A non-Candidate file was created after Apply.",
    "UNEXPECTED_FILE_MODIFIED": "A non-Candidate file changed after Apply.",
    "UNEXPECTED_FILE_DELETED": "A non-Candidate file was deleted after Apply.",
    "UNSAFE_OR_EXCLUDED_PATH_CHANGED": "An excluded or unsupported repository path changed after Apply.",
    "STAGED_PATHS_PRESENT": "The Git index contains staged paths.",
    "INDEX_CHANGED": "The Git index no longer matches the captured Apply boundary.",
    "BRANCH_CHANGED": "The repository branch changed after Apply.",
    "HEAD_CHANGED": "HEAD changed after Apply.",
    "REFS_CHANGED": "Git refs changed after Apply.",
    "CONFIG_CHANGED": "Local Git configuration changed after Apply.",
    "REMOTE_CHANGED": "Git remote configuration changed after Apply.",
    "REPOSITORY_IDENTITY_CHANGED": "The repository identity no longer matches the approved source.",
    "UNRELATED_SOURCE_CHANGED": "A previously preserved unrelated path changed after Apply.",
    "REPOSITORY_CHANGED_DURING_VERIFICATION": "The repository changed while verification evidence was being collected.",
    "REPOSITORY_UNAVAILABLE": "The repository cannot be inspected safely.",
    "VERIFICATION_EVIDENCE_UNAVAILABLE": "Post-Apply verification evidence cannot be constructed safely.",
}


class PostApplyVerificationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
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


def _blocker(code: str) -> dict[str, str]:
    return {
        "code": code,
        "message": BLOCKER_MESSAGES.get(
            code,
            "Post-Apply Verification is blocked by repository evidence.",
        ),
    }


def find_owned_post_apply_verification(
    session: Session,
    *,
    owner_id: int,
    verification_id: str,
) -> PostApplyVerification | None:
    return session.scalar(
        select(PostApplyVerification).where(
            PostApplyVerification.owner_id == owner_id,
            PostApplyVerification.verification_id == verification_id,
        )
    )


def post_apply_verification_history(
    session: Session,
    *,
    owner_id: int,
    apply_session_id: int,
) -> list[PostApplyVerification]:
    return list(
        session.scalars(
            select(PostApplyVerification)
            .where(
                PostApplyVerification.owner_id == owner_id,
                PostApplyVerification.apply_session_id == apply_session_id,
            )
            .order_by(PostApplyVerification.id.desc())
        ).all()
    )


def _bound_records(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
) -> tuple[ApplyPlan, DeliveryCandidate, CodexRun, CodexInstructionPack]:
    if apply_session.owner_id != owner_id:
        raise PostApplyVerificationError(
            "APPLY_SESSION_NOT_FOUND",
            "Apply session not found.",
        )
    if apply_session.state != "APPLIED":
        raise PostApplyVerificationError(
            "APPLY_SESSION_NOT_APPLIED",
            BLOCKER_MESSAGES["APPLY_SESSION_NOT_APPLIED"],
        )
    if apply_session.integrity_check_result != "PASSED":
        raise PostApplyVerificationError(
            "APPLY_INTEGRITY_NOT_PASSED",
            BLOCKER_MESSAGES["APPLY_INTEGRITY_NOT_PASSED"],
        )
    if not validate_apply_session_journal(session, apply_session):
        raise PostApplyVerificationError(
            "APPLY_JOURNAL_INVALID",
            BLOCKER_MESSAGES["APPLY_JOURNAL_INVALID"],
        )
    plan = session.get(ApplyPlan, apply_session.apply_plan_id)
    candidate = session.get(DeliveryCandidate, apply_session.delivery_candidate_id)
    run = session.get(CodexRun, apply_session.run_id)
    pack = session.get(CodexInstructionPack, apply_session.pack_id)
    if (
        plan is None
        or candidate is None
        or run is None
        or pack is None
        or plan.owner_id != owner_id
        or candidate.owner_id != owner_id
        or find_owner_run(session, owner_id, run.id) is None
        or not validate_apply_plan_integrity(session, plan)
        or plan.plan_id != apply_session.apply_plan_public_id
        or plan.plan_digest != apply_session.apply_plan_digest
        or candidate.candidate_id != apply_session.candidate_public_id
        or candidate.candidate_digest != apply_session.candidate_digest
        or plan.delivery_candidate_id != candidate.id
        or plan.run_id != run.id
        or candidate.run_id != run.id
        or plan.pack_id != pack.id
        or run.pack_id != pack.id
        or run.task_id != apply_session.task_id
        or run.task_version != apply_session.task_version
        or pack.version != apply_session.pack_version
        or plan.source_snapshot_identity != apply_session.source_snapshot_identity
        or candidate.source_snapshot_identity != apply_session.source_snapshot_identity
        or pack.source_snapshot_digest != apply_session.source_snapshot_identity
    ):
        raise PostApplyVerificationError(
            "APPLY_BINDING_INVALID",
            BLOCKER_MESSAGES["APPLY_BINDING_INVALID"],
        )
    return plan, candidate, run, pack


def post_apply_verification_eligibility(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
) -> dict[str, Any]:
    try:
        _bound_records(
            session,
            owner_id=owner_id,
            apply_session=apply_session,
        )
    except PostApplyVerificationError as exc:
        blockers = [_blocker(exc.code)]
        return {
            "status": "BLOCKED",
            "status_label": STATUS_LABELS["BLOCKED"],
            "can_verify": False,
            "blockers": blockers,
            "next_action": blockers[0]["message"],
        }
    return {
        "status": "READY",
        "status_label": STATUS_LABELS["READY"],
        "can_verify": True,
        "blockers": [],
        "next_action": "Select Verify Applied Changes.",
    }


def _expected_paths(entries: Iterable[Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "operation_ordinal": entry.operation_ordinal,
            "path": entry.repository_path,
            "path_identity": entry.path_identity,
            "operation": entry.operation,
            "present": entry.after_present,
            "hash": entry.after_hash,
            "size": entry.after_size,
            "mode": entry.after_mode,
            "file_type": entry.after_file_type,
        }
        for entry in entries
    ]
    rows.sort(key=lambda item: int(item["operation_ordinal"]))
    for row in rows:
        row.pop("operation_ordinal", None)
    return rows


def _safe_target_observation(
    root: Path,
    entries: Iterable[Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        inspection_code = ""
        try:
            actual, _parent_chain = _target_state(root, entry.repository_path)
        except ApplySessionError as exc:
            # A target that became a symlink, directory, unreadable path, or
            # otherwise unsafe is evidence that the applied after-state no
            # longer matches. Preserve only the safe category; never surface
            # exception text or a host path.
            inspection_code = exc.code
            actual = {
                "present": True,
                "hash": None,
                "size": None,
                "mode": None,
                "file_type": "unsupported",
            }
        presence_matches = (
            actual.get("present") is entry.after_present
            and actual.get("file_type") == entry.after_file_type
        )
        exact_matches = _state_matches(
            actual,
            present=entry.after_present,
            expected_hash=entry.after_hash,
            expected_size=entry.after_size,
            expected_mode=entry.after_mode,
            expected_file_type=entry.after_file_type,
        )
        rows.append(
            {
                "path": entry.repository_path,
                "path_identity": entry.path_identity,
                "operation": entry.operation,
                "present": actual.get("present") is True,
                "hash": actual.get("hash"),
                "size": actual.get("size"),
                "mode": actual.get("mode"),
                "file_type": actual.get("file_type"),
                "presence_matches": presence_matches,
                "matches": exact_matches,
                "result": "PASSED" if exact_matches else "BLOCKED",
                "inspection_code": inspection_code or None,
            }
        )
    return rows


def _assert_repository_tree_inspectable(root: Path) -> None:
    """Fail closed when an included directory cannot be enumerated safely.

    Apply/Revert's accepted evidence format intentionally records files and
    excluded paths, not ordinary directory rows.  Post-Apply Verification adds
    this read-only guard so ``os.walk`` cannot silently skip an inaccessible
    directory (and any unexpected files hidden below it) while preserving the
    accepted Apply evidence shape.
    """

    root = root.resolve(strict=True)

    def walk_error(exc: OSError) -> None:
        raise ApplySessionError(
            "SOURCE_EVIDENCE_UNAVAILABLE",
            "A repository directory cannot be inspected safely.",
        ) from exc

    for directory, directory_names, _file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            child = directory_path / name
            relative = child.relative_to(root).as_posix()
            try:
                before = child.lstat()
            except OSError as exc:
                walk_error(exc)
            reason = _snapshot_exclusion_reason(relative)
            if reason is not None or stat.S_ISLNK(before.st_mode):
                continue
            if not stat.S_ISDIR(before.st_mode):
                raise ApplySessionError(
                    "SOURCE_EVIDENCE_UNAVAILABLE",
                    "A repository directory cannot be inspected safely.",
                )
            permission_bits = stat.S_IMODE(before.st_mode)
            if not (permission_bits & 0o444) or not (permission_bits & 0o111):
                raise ApplySessionError(
                    "SOURCE_EVIDENCE_UNAVAILABLE",
                    "A repository directory cannot be inspected safely.",
                )
            try:
                with os.scandir(child) as iterator:
                    next(iterator, None)
                after = child.lstat()
            except OSError as exc:
                walk_error(exc)
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISDIR(after.st_mode)
                or (before.st_dev, before.st_ino)
                != (after.st_dev, after.st_ino)
                or before.st_mtime_ns != after.st_mtime_ns
            ):
                raise ApplySessionError(
                    "PATH_CHANGED_DURING_READ",
                    "A repository directory changed during inspection.",
                )
            retained_directories.append(name)
        directory_names[:] = retained_directories


def _repository_observation(
    *,
    run: CodexRun,
    pack: CodexInstructionPack,
    source_repo: Path,
    entries: list[Any],
    baseline_global: dict[str, Any],
) -> dict[str, Any]:
    root = _verified_repository_root(run, source_repo)
    approved_snapshot = _decoded_object(pack.source_snapshot_json)
    expected_repository_identity = str(
        approved_snapshot.get("source_repository_identity") or ""
    )
    expected_identity_method = str(
        approved_snapshot.get("source_repository_identity_method") or ""
    )
    if (
        expected_identity_method != "git-common-dir-sha256-v1"
        or not expected_repository_identity
    ):
        raise PostApplyVerificationError(
            "APPLY_BINDING_INVALID",
            BLOCKER_MESSAGES["APPLY_BINDING_INVALID"],
        )
    current_repository_identity = _source_repository_identity(
        root,
        hardened_read_only=True,
    )
    target_paths = [entry.repository_path for entry in entries]
    _assert_repository_tree_inspectable(root)
    global_evidence = _global_evidence_after_mutation(
        run,
        root,
        target_paths=target_paths,
        baseline=baseline_global,
    )
    return {
        "repository_identity_method": expected_identity_method,
        "expected_repository_identity": expected_repository_identity,
        "observed_repository_identity": current_repository_identity,
        "targets": _safe_target_observation(root, entries),
        "global": global_evidence,
    }


def _entry_map(direct_evidence: object) -> dict[str, dict[str, Any]]:
    evidence = _decoded_object(direct_evidence)
    result: dict[str, dict[str, Any]] = {}
    for raw in _decoded_list(evidence.get("entries")):
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        if path:
            result[path] = {
                "path": path,
                "path_identity": raw.get("path_identity"),
                "sha256": raw.get("sha256"),
                "size": raw.get("size"),
                "mode": raw.get("mode"),
                "mtime_ns": raw.get("mtime_ns"),
                "file_type": raw.get("file_type"),
            }
    return result


def _semantic_index(index_evidence: object) -> dict[str, Any]:
    """Return only delivery-relevant Git index evidence.

    Git may replace or touch its index while refreshing stat information even
    when the index bytes and staged set remain unchanged.  Those filesystem
    details are diagnostics; the content digest and staged-state evidence are
    the delivery boundary.
    """

    index = _decoded_object(index_evidence)
    return {key: index.get(key) for key in _INDEX_SEMANTIC_KEYS}


def _is_git_directory_metadata_row(row: dict[str, Any]) -> bool:
    return (
        row.get("path_identity") == _GIT_DIRECTORY_PATH_IDENTITY
        and row.get("file_type") == "directory"
        and row.get("reason") == "runtime_or_cache"
    )


def _semantic_excluded_entries(direct_evidence: object) -> list[dict[str, Any]]:
    """Normalize only volatile metadata for the exact Git directory row.

    Other excluded entries remain byte-for-byte evidence.  The Git directory
    must still retain its path identity, exclusion reason, type, and mode; only
    inode/mtime/size churn caused by internal lock and refresh lifecycles is
    non-blocking.
    """

    direct = _decoded_object(direct_evidence)
    normalized: list[dict[str, Any]] = []
    for raw in _decoded_list(direct.get("excluded_entries")):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        if _is_git_directory_metadata_row(row):
            for key in _GIT_DIRECTORY_VOLATILE_KEYS:
                row.pop(key, None)
        normalized.append(row)
    normalized.sort(key=canonical_json)
    return normalized


def _semantic_excluded_fingerprint(direct_evidence: object) -> str:
    direct = _decoded_object(direct_evidence)
    if "excluded_entries" not in direct:
        # Fail closed for legacy or incomplete evidence that cannot be
        # normalized without guessing which excluded path changed.
        return str(direct.get("excluded_fingerprint") or "")
    return canonical_sha256(_semantic_excluded_entries(direct))


def _semantic_global_mismatches(
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    """Phase 18.3-local semantic boundary comparison.

    Apply/Revert retain their accepted raw evidence comparator.  Post-Apply
    Verification compares repository delivery facts while treating only the
    exact Git-internal volatile fields documented above as diagnostics.
    """

    result = canonical_semantic_diff(before, after)
    mapped: list[str] = []
    for code in result.codes:
        mapped.append(
            {
                "INDEX_CONTENT_CHANGED": "INDEX_CHANGED",
                "STAGED_SET_CHANGED": "INDEX_CHANGED",
                "STAGED_ENTRY_IDENTITY_CHANGED": "INDEX_CHANGED",
                "INDEX_SEMANTICS_CHANGED": "INDEX_CHANGED",
                "UNSAFE_OR_EXCLUDED_PATH_CHANGED": "EXCLUDED_PATH_SET_CHANGED",
                "SOURCE_SEMANTICS_CHANGED": "UNRELATED_SOURCE_CHANGED",
            }.get(code, code)
        )
    return sorted(set(mapped))


def _semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Project an observation for stability and idempotency comparisons."""

    projected = _decoded_object(canonical_json(observation))
    global_evidence = _decoded_object(projected.get("global"))
    if global_evidence:
        projected["global"] = semantic_projection(global_evidence)
    return projected


def _git_directory_entry(direct_evidence: object) -> dict[str, Any] | None:
    direct = _decoded_object(direct_evidence)
    matches = [
        dict(raw)
        for raw in _decoded_list(direct.get("excluded_entries"))
        if isinstance(raw, dict)
        and _is_git_directory_metadata_row(raw)
    ]
    return matches[0] if len(matches) == 1 else None


def _git_metadata_refresh_categories(
    *global_evidence_pairs: tuple[dict[str, Any], dict[str, Any]],
) -> list[str]:
    """Describe safe non-blocking Git metadata churn without raw paths."""

    categories: set[str] = set()
    for before, after in global_evidence_pairs:
        categories.update(
            canonical_semantic_diff(before, after).metadata_refresh_categories
        )
        before_index = _decoded_object(before.get("index"))
        after_index = _decoded_object(after.get("index"))
        if _semantic_index(before_index) == _semantic_index(after_index) and any(
            before_index.get(key) != after_index.get(key)
            for key in _INDEX_VOLATILE_KEYS
        ):
            categories.add("index_metadata_refresh")
        before_git = _git_directory_entry(before.get("direct_filesystem"))
        after_git = _git_directory_entry(after.get("direct_filesystem"))
        if before_git is None or after_git is None:
            continue
        before_semantic = {
            key: value
            for key, value in before_git.items()
            if key not in _GIT_DIRECTORY_VOLATILE_KEYS
        }
        after_semantic = {
            key: value
            for key, value in after_git.items()
            if key not in _GIT_DIRECTORY_VOLATILE_KEYS
        }
        if before_semantic == after_semantic and before_git != after_git:
            categories.add("git_internal_directory_metadata_refresh")
    return sorted(categories)


def _unexpected_and_preserved(
    baseline_global: dict[str, Any],
    current_global: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    baseline_direct = _decoded_object(baseline_global.get("direct_filesystem"))
    current_direct = _decoded_object(current_global.get("direct_filesystem"))
    baseline = _entry_map(baseline_direct)
    current = _entry_map(current_direct)
    unexpected: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    for path in sorted(set(baseline) | set(current), key=lambda value: value.encode("utf-8")):
        before = baseline.get(path)
        after = current.get(path)
        if before is None:
            unexpected.append(
                {
                    "path": path,
                    "path_identity": after.get("path_identity") if after else None,
                    "operation": "CREATE",
                    "reason_code": "UNEXPECTED_FILE_CREATED",
                }
            )
        elif after is None:
            unexpected.append(
                {
                    "path": path,
                    "path_identity": before.get("path_identity"),
                    "operation": "DELETE",
                    "reason_code": "UNEXPECTED_FILE_DELETED",
                }
            )
        elif canonical_json(before) != canonical_json(after):
            unexpected.append(
                {
                    "path": path,
                    "path_identity": after.get("path_identity"),
                    "operation": "MODIFY",
                    "reason_code": "UNEXPECTED_FILE_MODIFIED",
                }
            )
        else:
            preserved.append(
                {
                    "path": path,
                    "path_identity": before.get("path_identity"),
                    "result": "PRESERVED",
                }
            )
    if _semantic_excluded_fingerprint(
        baseline_direct
    ) != _semantic_excluded_fingerprint(current_direct):
        unexpected.append(
            {
                "path": "[excluded path withheld]",
                "path_identity": None,
                "operation": "MODIFY",
                "reason_code": "UNSAFE_OR_EXCLUDED_PATH_CHANGED",
            }
        )
    return unexpected, preserved


def _test_result(
    code: str,
    description: str,
    passed: bool,
) -> dict[str, str]:
    return {
        "code": code,
        "description": description,
        "status": "PASS" if passed else "BLOCKED",
    }


def _evaluate_observation(
    *,
    apply_session: ApplySession,
    baseline_global: dict[str, Any],
    observation: dict[str, Any],
    stable: bool,
) -> tuple[str, list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    targets = _decoded_list(observation.get("targets"))
    current_global = _decoded_object(observation.get("global"))
    unexpected, preserved = _unexpected_and_preserved(
        baseline_global,
        current_global,
    )
    global_codes = set(_semantic_global_mismatches(baseline_global, current_global))
    blockers: list[dict[str, str]] = []
    if not stable:
        blockers.append(_blocker("REPOSITORY_CHANGED_DURING_VERIFICATION"))
    if any(not bool(row.get("matches")) for row in targets if isinstance(row, dict)):
        blockers.append(_blocker("APPLIED_PATH_CHANGED"))
    for item in unexpected:
        blockers.append(_blocker(str(item.get("reason_code") or "UNRELATED_SOURCE_CHANGED")))
    current_index = _decoded_object(current_global.get("index"))
    if int(current_index.get("staged_path_count") or 0) > 0:
        blockers.append(_blocker("STAGED_PATHS_PRESENT"))
    if (
        observation.get("expected_repository_identity")
        != observation.get("observed_repository_identity")
    ):
        blockers.append(_blocker("REPOSITORY_IDENTITY_CHANGED"))
    for code in (
        "REPOSITORY_IDENTITY_CHANGED",
        "BRANCH_CHANGED",
        "HEAD_CHANGED",
        "REFS_CHANGED",
        "CONFIG_CHANGED",
        "REMOTE_CHANGED",
        "INDEX_CHANGED",
        "UNRELATED_SOURCE_CHANGED",
        "EXCLUDED_PATH_SET_CHANGED",
    ):
        if code not in global_codes:
            continue
        mapped = (
            "UNSAFE_OR_EXCLUDED_PATH_CHANGED"
            if code == "EXCLUDED_PATH_SET_CHANGED"
            else code
        )
        blockers.append(_blocker(mapped))
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in blockers:
        if item["code"] in seen:
            continue
        seen.add(item["code"])
        deduplicated.append(item)
    presence_ok = all(
        bool(row.get("presence_matches"))
        for row in targets
        if isinstance(row, dict)
    )
    content_ok = all(
        bool(row.get("matches"))
        for row in targets
        if isinstance(row, dict)
    )
    checks = dict(POST_APPLY_CHECK_DEFINITIONS)
    test_results = [
        _test_result("EXPECTED_PATHS", checks["EXPECTED_PATHS"], presence_ok),
        _test_result("EXPECTED_CONTENT", checks["EXPECTED_CONTENT"], content_ok),
        _test_result("UNEXPECTED_FILES", checks["UNEXPECTED_FILES"], not unexpected),
        _test_result("UNRELATED_CHANGES", checks["UNRELATED_CHANGES"], not unexpected),
        _test_result(
            "CLEAN_INDEX",
            checks["CLEAN_INDEX"],
            int(current_index.get("staged_path_count") or 0) == 0
            and "INDEX_CHANGED" not in global_codes,
        ),
        _test_result("UNCHANGED_HEAD", checks["UNCHANGED_HEAD"], "HEAD_CHANGED" not in global_codes),
        _test_result("UNCHANGED_REFS", checks["UNCHANGED_REFS"], "REFS_CHANGED" not in global_codes),
        _test_result(
            "UNCHANGED_REMOTE_CONFIG",
            checks["UNCHANGED_REMOTE_CONFIG"],
            "REMOTE_CHANGED" not in global_codes and "CONFIG_CHANGED" not in global_codes,
        ),
        _test_result(
            "UNCHANGED_BRANCH",
            "Verify the repository branch is unchanged.",
            "BRANCH_CHANGED" not in global_codes,
        ),
        _test_result(
            "REPOSITORY_IDENTITY",
            "Verify the exact approved repository identity.",
            observation.get("expected_repository_identity")
            == observation.get("observed_repository_identity"),
        ),
        _test_result(
            "STABLE_OBSERVATION",
            "Verify repository evidence remained stable during inspection.",
            stable,
        ),
    ]
    return (
        "PASSED" if not deduplicated else "BLOCKED",
        deduplicated,
        unexpected,
        preserved,
        test_results,
    )


def _failure_material(
    *,
    code: str,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    blocker = _blocker(code)
    observation = {
        "error_code": code,
        "targets": [],
        "global": {},
    }
    tests = [
        {
            "code": "VERIFICATION_EVIDENCE",
            "description": "Collect complete read-only repository evidence.",
            "status": "FAILED",
        }
    ]
    return observation, [blocker], tests


def get_or_create_post_apply_verification(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
    source_repo: Path,
    expected_journal_digest: str | None = None,
) -> tuple[PostApplyVerification, bool]:
    plan, candidate, run, pack = _bound_records(
        session,
        owner_id=owner_id,
        apply_session=apply_session,
    )
    if (
        expected_journal_digest is not None
        and expected_journal_digest != apply_session.journal_digest
    ):
        raise PostApplyVerificationError(
            "APPLY_JOURNAL_BINDING_CHANGED",
            "The Apply journal identity changed. Review the Apply session again.",
        )
    entries = apply_session_entries(session, apply_session)
    expected_paths = _expected_paths(entries)
    after_evidence = _decoded_object(apply_session.after_evidence_json)
    baseline_global = _decoded_object(after_evidence.get("global"))
    if not entries or not baseline_global:
        raise PostApplyVerificationError(
            "VERIFICATION_EVIDENCE_UNAVAILABLE",
            BLOCKER_MESSAGES["VERIFICATION_EVIDENCE_UNAVAILABLE"],
        )
    status: str
    unexpected: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    git_metadata_refresh_categories: list[str] = []
    try:
        with _repository_mutation_lock(
            apply_session.repository_locator_fingerprint
        ):
            first = _repository_observation(
                run=run,
                pack=pack,
                source_repo=source_repo,
                entries=entries,
                baseline_global=baseline_global,
            )
            second = _repository_observation(
                run=run,
                pack=pack,
                source_repo=source_repo,
                entries=entries,
                baseline_global=baseline_global,
            )
        first_global = _decoded_object(first.get("global"))
        second_global = _decoded_object(second.get("global"))
        stable = canonical_json(_semantic_observation(first)) == canonical_json(
            _semantic_observation(second)
        )
        git_metadata_refresh_categories = _git_metadata_refresh_categories(
            (baseline_global, second_global),
            (first_global, second_global),
        )
        observation = second
        status, blockers, unexpected, preserved, test_results = _evaluate_observation(
            apply_session=apply_session,
            baseline_global=baseline_global,
            observation=observation,
            stable=stable,
        )
    except (ApplySessionError, PostApplyVerificationError, OSError, RuntimeError, ValueError) as exc:
        code = (
            exc.code
            if isinstance(exc, (ApplySessionError, PostApplyVerificationError))
            else "REPOSITORY_UNAVAILABLE"
        )
        if code == "CONCURRENT_APPLY":
            code = "REPOSITORY_CHANGED_DURING_VERIFICATION"
        if code not in BLOCKER_MESSAGES:
            code = "VERIFICATION_EVIDENCE_UNAVAILABLE"
        observation, blockers, test_results = _failure_material(code=code)
        status = (
            "BLOCKED"
            if code == "REPOSITORY_CHANGED_DURING_VERIFICATION"
            else "FAILED"
        )
    observation_material = {
        "schema": "twos.post_apply_observation.v2",
        "policy_version": POST_APPLY_VERIFICATION_POLICY_VERSION,
        "owner_id": owner_id,
        "apply_session_id": apply_session.session_id,
        "journal_digest": apply_session.journal_digest,
        "apply_plan_id": plan.plan_id,
        "apply_plan_digest": plan.plan_digest,
        "candidate_id": candidate.candidate_id,
        "candidate_digest": candidate.candidate_digest,
        "run_id": run.id,
        "source_snapshot_identity": apply_session.source_snapshot_identity,
        "expected_paths": expected_paths,
        "observation": _semantic_observation(observation),
    }
    observation_digest = canonical_sha256(observation_material)
    existing = session.scalar(
        select(PostApplyVerification).where(
            PostApplyVerification.owner_id == owner_id,
            PostApplyVerification.apply_session_id == apply_session.id,
            PostApplyVerification.observation_digest == observation_digest,
        )
    )
    if existing is not None:
        return existing, False
    current_global = _decoded_object(observation.get("global"))
    current_targets = _decoded_list(observation.get("targets"))
    boundary_evidence = {
        "inspection": "read_only",
        "git_policy": "explicit_read_only_allowlist",
        "git_commands": list(APPLY_SESSION_READ_ONLY_GIT_ALLOWLIST),
        "source_mutation": False,
        "index_mutation": False,
        "head_ref_config_remote_mutation": False,
        "stage_commit_push": False,
        "git_metadata_semantics": {
            "refresh_observed": bool(git_metadata_refresh_categories),
            "categories": git_metadata_refresh_categories,
            "blocking": False,
            "index_comparison": "content_digest_and_staged_state",
        },
        "git_fingerprints": {
            "expected": {
                "index": _decoded_object(baseline_global.get("index")).get(
                    "fingerprint"
                ),
                "refs": baseline_global.get("refs_fingerprint"),
                "local_config": baseline_global.get("local_config_fingerprint"),
                "remote": baseline_global.get("remote_fingerprint"),
            },
            "observed": {
                "index": _decoded_object(current_global.get("index")).get(
                    "fingerprint"
                ),
                "refs": current_global.get("refs_fingerprint"),
                "local_config": current_global.get("local_config_fingerprint"),
                "remote": current_global.get("remote_fingerprint"),
            },
            "staged_path_count": _decoded_object(current_global.get("index")).get(
                "staged_path_count"
            ),
        },
    }
    verification_material = {
        "schema": "twos.post_apply_verification.v2",
        "observation_digest": observation_digest,
        "status": status,
        "tests": test_results,
        "blockers": blockers,
        "boundaries": boundary_evidence,
    }
    verification_digest = canonical_sha256(verification_material)
    row = PostApplyVerification(
        verification_id="pav_" + verification_digest[:40],
        owner_id=owner_id,
        apply_session_id=apply_session.id,
        apply_plan_id=plan.id,
        delivery_candidate_id=candidate.id,
        run_id=run.id,
        apply_session_public_id=apply_session.session_id,
        apply_plan_public_id=plan.plan_id,
        candidate_public_id=candidate.candidate_id,
        journal_digest=apply_session.journal_digest,
        apply_plan_digest=plan.plan_digest,
        candidate_digest=candidate.candidate_digest,
        repository_locator_fingerprint=apply_session.repository_locator_fingerprint,
        sanitized_repository_identity=apply_session.sanitized_repository_identity,
        expected_repository_fingerprint=str(baseline_global.get("repository_fingerprint") or ""),
        observed_repository_fingerprint=str(current_global.get("repository_fingerprint") or ""),
        expected_branch=apply_session.branch,
        observed_branch=str(current_global.get("branch") or ""),
        expected_head=apply_session.pre_apply_head,
        observed_head=str(current_global.get("head") or ""),
        source_snapshot_identity=apply_session.source_snapshot_identity,
        policy_version=POST_APPLY_VERIFICATION_POLICY_VERSION,
        expected_paths_json=canonical_json(expected_paths),
        observed_paths_json=canonical_json(current_targets),
        preserved_paths_json=canonical_json(preserved),
        unexpected_paths_json=canonical_json(unexpected),
        test_results_json=canonical_json(test_results),
        blocker_codes_json=canonical_json(blockers),
        boundary_evidence_json=canonical_json(boundary_evidence),
        diagnostics_json=canonical_json(
            {
                "observation_stable": not any(
                    item.get("code") == "REPOSITORY_CHANGED_DURING_VERIFICATION"
                    for item in blockers
                ),
                "target_count": len(expected_paths),
                "unexpected_count": len(unexpected),
                "preserved_count": len(preserved),
                "staged_path_count": _decoded_object(current_global.get("index")).get(
                    "staged_path_count"
                ),
                "git_metadata_refresh_observed": bool(
                    git_metadata_refresh_categories
                ),
                "git_metadata_refresh_categories": git_metadata_refresh_categories,
                "git_metadata_refresh_summary": (
                    "Git metadata refresh observed"
                    if git_metadata_refresh_categories
                    else "No Git metadata refresh observed"
                ),
                "git_fingerprints": boundary_evidence["git_fingerprints"],
            }
        ),
        observation_digest=observation_digest,
        verification_digest=verification_digest,
        status=status,
    )
    session.add(row)
    session.flush()
    return row, True


def _next_action(status: str) -> str:
    return {
        "READY": "Select Verify Applied Changes.",
        "VERIFYING": "Wait for the read-only repository checks to finish.",
        "PASSED": "Review Commit Plan.",
        "BLOCKED": (
            "Resolve the verification blockers, then explicitly select "
            "Verify Applied Changes again."
        ),
        "FAILED": (
            "Restore safe repository access, then explicitly select "
            "Verify Applied Changes again."
        ),
    }[status]


def post_apply_verification_out(row: PostApplyVerification) -> dict[str, Any]:
    expected = _decoded_list(row.expected_paths_json)
    observed = _decoded_list(row.observed_paths_json)
    observed_by_identity = {
        str(item.get("path_identity") or ""): item
        for item in observed
        if isinstance(item, dict)
    }
    paired_path_evidence: list[dict[str, Any]] = []
    changed_files = []
    for item in expected:
        if not isinstance(item, dict):
            continue
        actual = observed_by_identity.get(str(item.get("path_identity") or ""), {})
        changed_files.append(
            {
                "path": item.get("path"),
                "operation": item.get("operation"),
                "result": actual.get("result") or "FAILED",
            }
        )
        paired_path_evidence.append(
            {
                "path": item.get("path"),
                "path_identity": item.get("path_identity"),
                "operation": item.get("operation"),
                "result": actual.get("result") or "FAILED",
                "expected_present": item.get("present"),
                "observed_present": actual.get("present"),
                "expected_hash": item.get("hash"),
                "observed_hash": actual.get("hash"),
                "expected_size": item.get("size"),
                "observed_size": actual.get("size"),
                "expected_mode": item.get("mode"),
                "observed_mode": actual.get("mode"),
                "expected_file_type": item.get("file_type"),
                "observed_file_type": actual.get("file_type"),
                "inspection_code": actual.get("inspection_code"),
            }
        )
    blockers = _decoded_list(row.blocker_codes_json)
    tests = _decoded_list(row.test_results_json)
    unexpected = _decoded_list(row.unexpected_paths_json)
    boundaries = list(BOUNDARIES)
    return {
        "id": row.verification_id,
        "status": row.status,
        "status_label": STATUS_LABELS[row.status],
        "changed_files": changed_files,
        "unexpected_files": [
            {
                "path": item.get("path"),
                "operation": item.get("operation"),
            }
            for item in unexpected
            if isinstance(item, dict)
        ],
        "tests": tests,
        "boundaries": boundaries,
        "blockers": blockers,
        "next_action": _next_action(row.status),
        "created_at": row.created_at.isoformat() + "Z",
        "advanced": {
            "policy_version": row.policy_version,
            "verification_digest": row.verification_digest,
            "observation_digest": row.observation_digest,
            "apply_session_id": row.apply_session_public_id,
            "apply_session_digest": row.journal_digest,
            "apply_plan_id": row.apply_plan_public_id,
            "apply_plan_digest": row.apply_plan_digest,
            "candidate_id": row.candidate_public_id,
            "candidate_digest": row.candidate_digest,
            "apply_session": {
                "id": row.apply_session_public_id,
                "journal_digest": row.journal_digest,
            },
            "apply_plan": {
                "id": row.apply_plan_public_id,
                "digest": row.apply_plan_digest,
            },
            "candidate": {
                "id": row.candidate_public_id,
                "digest": row.candidate_digest,
            },
            "run_id": row.run_id,
            "repository_identity": row.sanitized_repository_identity,
            "repository_locator_fingerprint": row.repository_locator_fingerprint,
            "expected_repository_fingerprint": row.expected_repository_fingerprint,
            "observed_repository_fingerprint": row.observed_repository_fingerprint,
            "repository_fingerprints": {
                "locator": row.repository_locator_fingerprint,
                "expected": row.expected_repository_fingerprint,
                "observed": row.observed_repository_fingerprint,
            },
            "expected_branch": row.expected_branch,
            "observed_branch": row.observed_branch,
            "expected_head": row.expected_head,
            "observed_head": row.observed_head,
            "source_snapshot_identity": row.source_snapshot_identity,
            "expected_paths": paired_path_evidence,
            "observed_paths": paired_path_evidence,
            "preserved_paths": _decoded_list(row.preserved_paths_json),
            "diagnostics": _decoded_object(row.diagnostics_json),
            "boundary_evidence": _decoded_object(row.boundary_evidence_json),
        },
    }


def post_apply_verification_review(
    session: Session,
    *,
    owner_id: int,
    apply_session: ApplySession,
) -> dict[str, Any]:
    eligibility = post_apply_verification_eligibility(
        session,
        owner_id=owner_id,
        apply_session=apply_session,
    )
    history = post_apply_verification_history(
        session,
        owner_id=owner_id,
        apply_session_id=apply_session.id,
    )
    latest = history[0] if history else None
    return {
        "apply_session_id": apply_session.session_id,
        "eligibility": eligibility,
        "verification": post_apply_verification_out(latest) if latest else None,
        "history": [
            {
                "id": row.verification_id,
                "status": row.status,
                "status_label": STATUS_LABELS[row.status],
                "verification_digest": row.verification_digest,
                "created_at": row.created_at.isoformat() + "Z",
            }
            for row in history
        ],
        "actions": {"can_verify": eligibility["can_verify"] is True},
    }
