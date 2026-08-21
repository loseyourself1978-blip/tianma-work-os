from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_orchestration import (
    assignment_binding,
    has_complete_verified_codex_run_evidence,
    is_verified_real_invocation,
    latest_model_assignments,
)
from .models import (
    AIModelAssignment,
    AIModelInvocationEvidence,
    CodexInstructionPack,
    CodexRun,
    DeliveryCandidate,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    SourceDriftEvaluation,
    Task,
)
from .self_hosting import (
    SOURCE_SNAPSHOT_SCHEMA,
    _snapshot_exclusion_reason,
    _source_snapshot_digest,
    capture_source_snapshot,
    development_task_digest,
    git_source_state,
    run_git,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:")

DRIFT_STATUS_LABELS = {
    "ready_to_apply": "Ready to apply",
    "source_changed_since_run": "Source changed since Run",
    "conflict_detected": "Conflict detected",
    "candidate_unavailable": "Candidate unavailable",
    "repository_unavailable": "Repository unavailable",
}

# Source Drift delegates snapshot capture to the established Vol.17 snapshot
# service. These are the complete read-only Git command families that service
# uses. No command capable of changing a worktree, index, ref, configuration,
# or remote is admitted by the Phase 18.1 service.
SOURCE_DRIFT_READ_ONLY_GIT_ALLOWLIST = (
    "rev-parse --show-toplevel",
    "branch --show-current",
    "rev-parse HEAD",
    "status --porcelain --untracked-files=all",
    "ls-files -z",
    "ls-files --others --exclude-standard -z",
    "diff --name-status",
    "diff --name-only",
    "diff --cached --name-only",
    "diff --binary",
    "diff --cached --binary",
)

TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "failed", "blocked", "cancelled", "timed_out"}
)
VERIFICATION_INDEPENDENCE_STATES = frozenset(
    {"independent", "independent_fallback", "separate_invocation"}
)

BLOCKER_MESSAGES = {
    "RUN_FAILED": "The Codex Run failed and cannot produce a Delivery Candidate.",
    "RUN_BLOCKED": "The Codex Run was blocked and cannot produce a Delivery Candidate.",
    "RUN_CANCELLED": "The Codex Run was cancelled and cannot produce a Delivery Candidate.",
    "RUN_TIMED_OUT": "The Codex Run timed out and cannot produce a Delivery Candidate.",
    "RUN_NOT_TERMINAL": "The Codex Run is not terminal.",
    "RUN_EVIDENCE_INCOMPLETE": "The successful Run is missing complete terminal process evidence.",
    "RUN_RESULT_BINDING_STALE": "The persisted Run result no longer matches the exact Task, Pack, prompt, or source binding.",
    "VERIFICATION_MISSING": "Independent Verification evidence is missing.",
    "VERIFICATION_FAILED": "Independent Verification did not return PASS.",
    "VERIFICATION_UNAVAILABLE": "Independent Verification did not complete successfully.",
    "CODING_PROCESS_IDENTITY_INCOMPLETE": "Coding process and thread identities are incomplete.",
    "VERIFICATION_PROCESS_IDENTITY_INCOMPLETE": "Verification process and thread identities are incomplete.",
    "PROCESS_IDENTITY_NOT_SEPARATE": "Coding and Verification must use separate persisted process identities.",
    "THREAD_IDENTITY_NOT_SEPARATE": "Coding and Verification must use separate persisted thread identities.",
    "VERIFICATION_PROOF_INCOMPLETE": "Verification-specific read-only and boundary proof is incomplete.",
    "ACCEPTANCE_INVALID": "Current Task acceptance is not satisfied for this exact Run.",
    "RESULT_REJECTED": "The Owner rejected this Run result.",
    "TASK_BINDING_STALE": "The Run no longer matches the exact current Task version.",
    "PACK_BINDING_STALE": "The Run no longer matches the exact current approved Pack version.",
    "ASSIGNMENT_BINDING_STALE": "Coding or Verification assignments no longer match the Run.",
    "ROUTING_SNAPSHOT_UNAVAILABLE": "The exact routing snapshot is unavailable or invalid.",
    "SOURCE_SNAPSHOT_UNAVAILABLE": "The approved source snapshot is unavailable or invalid.",
    "CODING_EVIDENCE_INCOMPLETE": "Complete Coding process, turn, and result evidence is required.",
    "VERIFICATION_EVIDENCE_INCOMPLETE": "Complete independent Verification process, turn, and verdict evidence is required.",
    "MANIFEST_UNAVAILABLE": "The Run-produced file manifest cannot be reconstructed safely.",
    "MANIFEST_PATH_UNSAFE": "The Run-produced file manifest contains an unsafe or malformed path.",
    "MANIFEST_DUPLICATE_CONFLICT": "The Run-produced file manifest contains duplicate or conflicting operations.",
    "CANDIDATE_INTEGRITY_INVALID": "The immutable Delivery Candidate failed its integrity check.",
}

NEXT_ACTIONS = {
    "RUN_NOT_TERMINAL": "Wait for the Run to finish.",
    "ACCEPTANCE_INVALID": "Complete Owner Acceptance for this exact Run.",
    "RESULT_REJECTED": "Review the rejected result and run an approved Pack again if needed.",
    "TASK_BINDING_STALE": "Regenerate Codex Pack for the current Task.",
    "RUN_RESULT_BINDING_STALE": "Run a newly approved Pack for the current Task.",
    "PACK_BINDING_STALE": "Regenerate and approve the current Codex Pack.",
    "ASSIGNMENT_BINDING_STALE": "Review assignments and regenerate Codex Pack.",
    "ROUTING_SNAPSHOT_UNAVAILABLE": "Review assignments and regenerate Codex Pack.",
    "SOURCE_SNAPSHOT_UNAVAILABLE": "Regenerate Codex Pack from an available source repository.",
}


class ManifestError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"


def _decoded_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decoded_list(value: str) -> list[Any]:
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _blocker(code: str, message: str | None = None) -> dict[str, str]:
    return {"code": code, "message": message or BLOCKER_MESSAGES[code]}


def _next_action(blockers: list[dict[str, str]]) -> str:
    if not blockers:
        return "Review Change Candidate"
    return NEXT_ACTIONS.get(
        blockers[0]["code"],
        "Review the Run result and its evidence before trying again.",
    )


def _safe_sha256(value: object) -> str | None:
    if value is None or value == "":
        return None
    candidate = str(value)
    if not SHA256_PATTERN.fullmatch(candidate):
        raise ManifestError("File evidence contains an invalid SHA-256 value.")
    return candidate


def normalize_repository_path(value: object) -> str:
    if not isinstance(value, str):
        raise ManifestError("Manifest paths must be strings.")
    if (
        not value
        or len(value) > 1024
        or "\x00" in value
        or "\\" in value
        or unicodedata.normalize("NFC", value) != value
        or WINDOWS_ABSOLUTE_PATTERN.match(value)
    ):
        raise ManifestError("Manifest contains a malformed repository path.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
        or _snapshot_exclusion_reason(value) is not None
    ):
        raise ManifestError("Manifest path is outside the authorized source boundary.")
    return value


def _safe_size(value: object, *, required: bool) -> int | None:
    if value is None:
        if required:
            raise ManifestError("Manifest file size evidence is missing.")
        return None
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ManifestError("Manifest file size evidence is invalid.")
    return value


def _safe_mode(value: object, *, required: bool) -> int | None:
    if value is None:
        if required:
            raise ManifestError("Manifest file mode evidence is missing.")
        return None
    if type(value) is not int or not 0 <= value <= 0o7777:
        raise ManifestError("Manifest file mode evidence is invalid.")
    return value


def _snapshot_manifest_state(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = snapshot.get("included_manifest")
    if not isinstance(rows, list):
        raise ManifestError("Approved source manifest is unavailable.")
    state: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ManifestError("Approved source manifest contains malformed evidence.")
        path = normalize_repository_path(raw.get("path"))
        if path in state:
            raise ManifestError("Approved source manifest contains duplicate paths.")
        deleted = raw.get("deleted") is True
        sha256 = _safe_sha256(raw.get("sha256"))
        size = _safe_size(raw.get("size"), required=not deleted)
        mode = _safe_mode(raw.get("mode"), required=not deleted)
        if deleted and (sha256 is not None or size is not None or mode is not None):
            raise ManifestError("Deleted source evidence contains conflicting file metadata.")
        state[path] = {
            "present": not deleted and sha256 is not None,
            "sha256": sha256,
            "size": size,
            "mode": mode,
        }
    return state


def _validated_source_snapshot(pack: CodexInstructionPack, run: CodexRun) -> dict[str, Any]:
    try:
        snapshot = json.loads(pack.source_snapshot_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ManifestError("Approved source snapshot is malformed.") from exc
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SOURCE_SNAPSHOT_SCHEMA:
        raise ManifestError("Approved source snapshot schema is unavailable.")
    digest = snapshot.get("digest")
    if (
        not isinstance(digest, str)
        or not SHA256_PATTERN.fullmatch(digest)
        or digest != pack.source_snapshot_digest
        or digest != run.source_snapshot_digest
    ):
        raise ManifestError("Approved source snapshot identity does not match the Run.")
    try:
        calculated = _source_snapshot_digest(snapshot)
    except (TypeError, ValueError, KeyError) as exc:
        raise ManifestError("Approved source snapshot cannot be validated.") from exc
    if calculated != digest:
        raise ManifestError("Approved source snapshot failed its integrity check.")
    if (
        snapshot.get("head_sha") != run.source_commit
        or snapshot.get("head_sha") != pack.source_baseline_commit
        or snapshot.get("source_branch") != run.source_branch
    ):
        raise ManifestError(
            "Approved source snapshot commit or branch does not match the Run and Pack."
        )
    _snapshot_manifest_state(snapshot)
    return snapshot


def _evidence_digest(evidence: AIModelInvocationEvidence) -> str:
    return canonical_sha256(
        {
            "schema": "twos.invocation_evidence_identity.v1",
            "id": evidence.id,
            "invocation_ref": evidence.invocation_ref,
            "capability": evidence.capability,
            "assignment_version": evidence.assignment_version,
            "configured_model_id": evidence.configured_model_id,
            "configured_provider_id": evidence.configured_provider_id,
            "assignment_id": evidence.assignment_id,
            "task_id": evidence.task_id,
            "codex_run_id": evidence.codex_run_id,
            "actual_invoked_model_identifier": evidence.actual_invoked_model_identifier,
            "invocation_mode": evidence.invocation_mode,
            "outcome": evidence.outcome,
            "process_evidence": _decoded_object(evidence.process_evidence),
            "provider_evidence": _decoded_object(evidence.provider_evidence),
            "timed_out": evidence.timed_out,
            "cancelled": evidence.cancelled,
            "output_truncated": evidence.output_truncated,
            "request_fingerprint": evidence.request_fingerprint,
            "response_fingerprint": evidence.response_fingerprint,
            "duration_ms": evidence.duration_ms,
            "diagnostic_code": evidence.diagnostic_code,
            "started_at": _iso(evidence.started_at),
            "completed_at": _iso(evidence.completed_at),
        }
    )


def _verified_evidence(
    session: Session,
    run: CodexRun,
    capability: str,
    assignment_id: int | None,
) -> AIModelInvocationEvidence | None:
    if run.id is None or assignment_id is None:
        return None
    rows = list(
        session.scalars(
            select(AIModelInvocationEvidence)
            .where(
                AIModelInvocationEvidence.codex_run_id == run.id,
                AIModelInvocationEvidence.capability == capability,
                AIModelInvocationEvidence.assignment_id == assignment_id,
            )
            .order_by(AIModelInvocationEvidence.id)
        ).all()
    )
    return next((row for row in rows if is_verified_real_invocation(row)), None)


def _unexpected_paths(result: dict[str, Any]) -> set[str]:
    values: list[object] = []
    run_changes = result.get("run_produced_changes")
    if isinstance(run_changes, dict):
        raw = run_changes.get("unexpected_files", [])
        if isinstance(raw, list):
            values.extend(raw)
    verification = result.get("verification")
    if isinstance(verification, dict):
        raw = verification.get("unexpected_files", [])
        if isinstance(raw, list):
            values.extend(raw)
    raw_artifacts = result.get("unexpected_excluded_artifacts", [])
    if isinstance(raw_artifacts, list):
        values.extend(
            item.get("path")
            for item in raw_artifacts
            if isinstance(item, dict) and item.get("path")
        )
    return {normalize_repository_path(item) for item in values}


def build_run_file_manifest(
    run: CodexRun,
    approved_snapshot: dict[str, Any],
    evidence_identity: str,
) -> list[dict[str, Any]]:
    result = _decoded_object(run.structured_result)
    changed_paths_raw = result.get("changed_files")
    evidence_rows = result.get("changed_file_evidence")
    run_changes = result.get("run_produced_changes")
    sanitized_diff = result.get("sanitized_diff_evidence")
    if (
        not isinstance(changed_paths_raw, list)
        or not all(isinstance(item, str) for item in changed_paths_raw)
        or not isinstance(evidence_rows, list)
        or not isinstance(run_changes, dict)
        or not isinstance(sanitized_diff, dict)
        or sanitized_diff.get("schema") != "twos.sanitized_diff.v1"
        or sanitized_diff.get("content_included") is not False
    ):
        raise ManifestError("Run-produced change evidence is incomplete.")
    if any(
        forbidden_key in sanitized_diff
        for forbidden_key in ("content", "patch", "raw_diff", "binary_content")
    ):
        raise ManifestError("Run-produced change evidence includes unsafe content.")
    changed_paths = [normalize_repository_path(item) for item in changed_paths_raw]
    if len(set(changed_paths)) != len(changed_paths):
        raise ManifestError("Run-produced changed paths contain duplicates.")
    persisted_change_paths = run_changes.get("changed_files")
    if (
        not isinstance(persisted_change_paths, list)
        or sorted(changed_paths)
        != sorted(normalize_repository_path(item) for item in persisted_change_paths)
    ):
        raise ManifestError("Run-produced changed-file evidence conflicts.")

    snapshot_state = _snapshot_manifest_state(approved_snapshot)
    unexpected = _unexpected_paths(result)
    rows_by_path: dict[str, dict[str, Any]] = {}
    for raw in evidence_rows:
        if not isinstance(raw, dict):
            raise ManifestError("Run-produced file evidence is malformed.")
        path = normalize_repository_path(raw.get("path"))
        if path in rows_by_path:
            raise ManifestError("Run-produced file evidence contains duplicate operations.")
        rows_by_path[path] = raw
    if set(rows_by_path) != set(changed_paths):
        raise ManifestError("Run-produced file evidence does not match changed files.")
    if not unexpected.issubset(set(changed_paths)):
        raise ManifestError("Unexpected-file evidence cannot be tied to the exact Run.")

    diff_records = sanitized_diff.get("records")
    record_count = sanitized_diff.get("record_count")
    truncated = sanitized_diff.get("truncated")
    if (
        not isinstance(diff_records, list)
        or type(record_count) is not int
        or record_count != len(changed_paths)
        or type(truncated) is not bool
    ):
        raise ManifestError("Sanitized diff metadata is unavailable.")
    diff_by_path: dict[str, dict[str, Any]] = {}
    for raw in diff_records:
        if not isinstance(raw, dict):
            raise ManifestError("Sanitized diff metadata is malformed.")
        path = normalize_repository_path(raw.get("path"))
        if path in diff_by_path:
            raise ManifestError("Sanitized diff metadata contains duplicate paths.")
        if raw.get("content_included") is not False:
            raise ManifestError("Sanitized diff metadata unexpectedly contains content.")
        diff_by_path[path] = raw
    changed_path_set = set(changed_paths)
    diff_path_set = set(diff_by_path)
    if not diff_path_set.issubset(changed_path_set):
        raise ManifestError("Sanitized diff metadata contains unrelated files.")
    if truncated is True:
        if not diff_records or len(diff_records) >= record_count:
            raise ManifestError("Sanitized diff truncation metadata is inconsistent.")
    elif diff_path_set != changed_path_set or len(diff_records) != record_count:
        raise ManifestError("Sanitized diff metadata does not match changed files.")

    manifest: list[dict[str, Any]] = []
    for path in sorted(changed_paths):
        raw = rows_by_path[path]
        before_hash = _safe_sha256(raw.get("before_sha256"))
        after_hash = _safe_sha256(raw.get("after_sha256"))
        before_deleted = raw.get("before_deleted") is True
        after_deleted = raw.get("after_deleted") is True
        before_present = before_hash is not None and not before_deleted
        after_present = after_hash is not None and not after_deleted
        if before_deleted and before_hash is not None:
            raise ManifestError("Before-file evidence is internally conflicting.")
        if after_deleted and after_hash is not None:
            raise ManifestError("After-file evidence is internally conflicting.")
        if not before_present and after_present:
            operation = "CREATE"
        elif before_present and not after_present:
            operation = "DELETE"
        elif before_present and after_present:
            operation = "MODIFY"
        else:
            raise ManifestError("Run-produced operation cannot be determined.")

        before_size = _safe_size(raw.get("before_size"), required=before_present)
        after_size = _safe_size(raw.get("after_size"), required=after_present)
        before_mode = _safe_mode(raw.get("before_mode"), required=before_present)
        after_mode = _safe_mode(raw.get("after_mode"), required=after_present)
        if not before_present and (
            before_hash is not None
            or before_size is not None
            or before_mode is not None
        ):
            raise ManifestError("Absent before-file evidence contains metadata.")
        if not after_present and (
            after_hash is not None
            or after_size is not None
            or after_mode is not None
        ):
            raise ManifestError("Absent after-file evidence contains metadata.")
        baseline = snapshot_state.get(path)
        baseline_present = bool(baseline and baseline["present"])
        if before_present:
            if (
                not baseline_present
                or baseline["sha256"] != before_hash
                or baseline["size"] != before_size
                or baseline["mode"] != before_mode
            ):
                raise ManifestError("Before-file evidence does not match the approved source snapshot.")
        elif baseline_present:
            raise ManifestError("Create evidence conflicts with the approved source snapshot.")
        if (
            operation == "MODIFY"
            and before_hash == after_hash
            and before_mode == after_mode
        ):
            raise ManifestError("Modify evidence does not contain a file-state change.")

        diff = diff_by_path.get(path, {})
        if diff:
            diff_metadata = (
                _safe_sha256(diff.get("before_sha256")),
                _safe_sha256(diff.get("after_sha256")),
                _safe_size(diff.get("before_size"), required=before_present),
                _safe_size(diff.get("after_size"), required=after_present),
                _safe_mode(diff.get("before_mode"), required=before_present),
                _safe_mode(diff.get("after_mode"), required=after_present),
            )
            if diff_metadata != (
                before_hash,
                after_hash,
                before_size,
                after_size,
                before_mode,
                after_mode,
            ):
                raise ManifestError(
                    "Sanitized diff metadata does not match file evidence."
                )
        content_kind = str(diff.get("content_kind") or "unknown")
        if content_kind not in {"text", "binary_or_oversized", "unknown"}:
            raise ManifestError("Sanitized diff content type is invalid.")
        claimed_type = diff.get("change_type")
        expected_types = {
            "CREATE": {"created"},
            "DELETE": {"deleted"},
            "MODIFY": {"modified", "mode_changed"},
        }[operation]
        if claimed_type is not None and claimed_type not in expected_types:
            raise ManifestError("Sanitized diff operation conflicts with file evidence.")
        evidence_row_identity = canonical_sha256(
            {
                "schema": "twos.delivery_manifest_evidence.v1",
                "run_id": run.id,
                "invocation": evidence_identity,
                "path": path,
                "operation": operation,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "before_size": before_size,
                "after_size": after_size,
                "before_mode": before_mode,
                "after_mode": after_mode,
            }
        )
        manifest.append(
            {
                "name": PurePosixPath(path).name,
                "path": path,
                "operation": operation,
                "unexpected": path in unexpected,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "before_size": before_size,
                "after_size": after_size,
                "before_mode": before_mode,
                "after_mode": after_mode,
                "content_kind": content_kind,
                "evidence_identity": evidence_row_identity,
            }
        )
    return manifest


def _assignment_bindings_valid(
    session: Session,
    task: Task,
    run: CodexRun,
    pack: CodexInstructionPack,
) -> bool:
    coding = run.execution_assignment
    verification = run.verification_assignment
    if (
        coding is None
        or verification is None
        or coding.id == verification.id
        or coding.capability != "coding"
        or verification.capability != "verification"
        or not verification.independence_required
        or verification.independence_status not in VERIFICATION_INDEPENDENCE_STATES
    ):
        return False
    for assignment in (coding, verification):
        if (
            assignment.task_id != task.id
            or assignment.task_version != task.task_version
            or assignment.task_version != run.task_version
            or assignment.task_version != pack.task_version
            or assignment.assignment_version != run.assignment_version
            or assignment.assignment_version != pack.assignment_version
            or assignment.routing_snapshot_hash != run.routing_snapshot_hash
            or assignment.routing_snapshot_hash != pack.routing_snapshot_hash
        ):
            return False
    current = latest_model_assignments(session, task.id)
    try:
        binding = assignment_binding(current)
    except ValueError:
        return False
    return (
        {item.id for item in current}.issuperset({coding.id, verification.id})
        and binding["task_version"] == run.task_version
        and binding["assignment_version"] == run.assignment_version
        and binding["routing_snapshot_hash"] == run.routing_snapshot_hash
    )


def _routing_snapshot_available(pack: CodexInstructionPack, run: CodexRun) -> bool:
    if (
        not SHA256_PATTERN.fullmatch(run.routing_snapshot_hash or "")
        or run.routing_snapshot_hash != pack.routing_snapshot_hash
    ):
        return False
    metadata = _decoded_object(pack.generation_metadata)
    snapshot = metadata.get("model_routing_snapshot")
    return bool(
        isinstance(snapshot, dict)
        and snapshot.get("routing_snapshot_hash") == run.routing_snapshot_hash
        and snapshot.get("assignment_version") == run.assignment_version
        and snapshot.get("task_version", run.task_version) == run.task_version
    )


def _run_result_evidence_complete(run: CodexRun, result: dict[str, Any]) -> bool:
    coding_process = result.get("coding_process")
    coding_invocation = result.get("coding_invocation")
    git_evidence = result.get("git_evidence")
    task_acceptance = result.get("task_acceptance")
    return bool(
        run.finished_at is not None
        and run.process_spawned
        and run.exit_code == 0
        and not run.timed_out
        and not run.cancelled
        and not run.output_truncated
        and isinstance(coding_process, dict)
        and coding_process.get("status") == "completed"
        and coding_process.get("process_started") is True
        and coding_process.get("exit_code") == 0
        and coding_process.get("timed_out") is False
        and coding_process.get("cancelled") is False
        and isinstance(coding_invocation, dict)
        and coding_invocation.get("process_execution_verified") is True
        and coding_invocation.get("codex_turn_verified") is True
        and coding_invocation.get("approved_prompt_delivery_complete", True) is True
        and isinstance(git_evidence, dict)
        and git_evidence.get("status") == "passed"
        and isinstance(task_acceptance, dict)
        and task_acceptance.get("status") == "passed"
    )


def _verification_result_state(run: CodexRun, result: dict[str, Any]) -> str:
    process = result.get("verification_process")
    invocation = result.get("verification_invocation")
    verdict = result.get("verification_verdict")
    if (
        run.verification_assignment_id is None
        or not isinstance(process, dict)
        or not isinstance(invocation, dict)
        or not isinstance(verdict, dict)
        or run.verification_status == "not_started"
    ):
        return "missing"
    if verdict.get("status") == "failed":
        return "failed"
    if (
        run.verification_status != "completed"
        or not run.verification_process_spawned
        or run.verification_exit_code != 0
        or run.verification_timed_out
        or run.verification_cancelled
        or run.verification_output_truncated
        or process.get("status") != "completed"
        or process.get("process_started") is not True
        or process.get("process_exit") != 0
        or invocation.get("process_execution_verified") is not True
        or invocation.get("codex_turn_verified") is not True
    ):
        return "unavailable"
    return "passed" if verdict.get("status") == "passed" else "failed"


VERIFICATION_PROOF_FIELDS = (
    "read_only_sandbox",
    "verification_verdict_observed",
    "workspace_unchanged_after_verification",
    "changed_files_checked",
    "unexpected_files_checked",
    "exact_content_checked",
    "test_evidence_checked",
    "git_boundary_checked",
    "remote_boundary_checked",
)


def _persisted_process_identity_blockers(
    coding_evidence: AIModelInvocationEvidence | None,
    verification_evidence: AIModelInvocationEvidence | None,
) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    coding_process = (
        _decoded_object(coding_evidence.process_evidence)
        if coding_evidence is not None
        else {}
    )
    verification_process = (
        _decoded_object(verification_evidence.process_evidence)
        if verification_evidence is not None
        else {}
    )
    coding_process_id = coding_process.get("process_id_fingerprint")
    coding_thread_id = coding_process.get("thread_id_fingerprint")
    verification_process_id = verification_process.get("process_id_fingerprint")
    verification_thread_id = verification_process.get("thread_id_fingerprint")
    coding_identity_complete = bool(
        isinstance(coding_process_id, str)
        and SHA256_PATTERN.fullmatch(coding_process_id)
        and isinstance(coding_thread_id, str)
        and SHA256_PATTERN.fullmatch(coding_thread_id)
    )
    verification_identity_complete = bool(
        isinstance(verification_process_id, str)
        and SHA256_PATTERN.fullmatch(verification_process_id)
        and isinstance(verification_thread_id, str)
        and SHA256_PATTERN.fullmatch(verification_thread_id)
    )
    if coding_evidence is not None and not coding_identity_complete:
        blockers.append(_blocker("CODING_PROCESS_IDENTITY_INCOMPLETE"))
    if verification_evidence is not None and not verification_identity_complete:
        blockers.append(_blocker("VERIFICATION_PROCESS_IDENTITY_INCOMPLETE"))
    if coding_identity_complete and verification_identity_complete:
        if coding_process_id == verification_process_id:
            blockers.append(_blocker("PROCESS_IDENTITY_NOT_SEPARATE"))
        if coding_thread_id == verification_thread_id:
            blockers.append(_blocker("THREAD_IDENTITY_NOT_SEPARATE"))
    if verification_evidence is not None and any(
        verification_process.get(field) is not True
        for field in VERIFICATION_PROOF_FIELDS
    ):
        blockers.append(_blocker("VERIFICATION_PROOF_INCOMPLETE"))
    return blockers


def _run_result_binding_valid(
    task: Task,
    pack: CodexInstructionPack,
    run: CodexRun,
    result: dict[str, Any],
) -> bool:
    expected = {
        "task_id": task.id,
        "task_version": run.task_version,
        "development_task_digest": run.development_task_digest,
        "pack_version": pack.version,
        "source_snapshot_digest": run.source_snapshot_digest,
        "pre_run_commit": run.source_commit,
        "coding_prompt_digest": hashlib.sha256(
            pack.content.encode("utf-8")
        ).hexdigest(),
    }
    return all(result.get(field) == value for field, value in expected.items())


def _accepted_for_run(
    session: Session,
    owner_id: int,
    task: Task,
    run: CodexRun,
) -> OwnerAcceptanceSession | None:
    acceptance = session.scalar(
        select(OwnerAcceptanceSession).where(
            OwnerAcceptanceSession.codex_run_id == run.id,
            OwnerAcceptanceSession.task_id == task.id,
        )
    )
    if acceptance is None:
        return None
    items = list(
        session.scalars(
            select(OwnerAcceptanceItem).where(
                OwnerAcceptanceItem.session_id == acceptance.id
            )
        ).all()
    )
    if (
        acceptance.status != "accepted"
        or acceptance.decided_by_user_id != owner_id
        or acceptance.decided_at is None
        or task.acceptance_state != "accepted"
        or task.status != "accepted"
        or not items
        or any(item.required and item.status != "pass" for item in items)
    ):
        return None
    return acceptance


def find_owner_run(session: Session, owner_id: int, run_id: int) -> CodexRun | None:
    """Resolve ownership without hiding truthful blockers for undecided results."""
    run = session.get(CodexRun, run_id)
    if run is None or run.pack is None:
        return None
    acceptance = session.scalar(
        select(OwnerAcceptanceSession).where(
            OwnerAcceptanceSession.codex_run_id == run.id,
            OwnerAcceptanceSession.task_id == run.task_id,
        )
    )
    if (
        run.pack.approved_by_user_id != owner_id
        or (
            acceptance is not None
            and acceptance.decided_by_user_id is not None
            and acceptance.decided_by_user_id != owner_id
        )
    ):
        return None
    return run


def _candidate_material(
    session: Session,
    owner_id: int,
    run: CodexRun,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    blockers: list[dict[str, str]] = []
    result = _decoded_object(run.structured_result)
    if run.status != "completed":
        status_code = {
            "failed": "RUN_FAILED",
            "blocked": "RUN_BLOCKED",
            "cancelled": "RUN_CANCELLED",
            "timed_out": "RUN_TIMED_OUT",
        }.get(run.status, "RUN_NOT_TERMINAL")
        blockers.append(_blocker(status_code))
        if run.status == "failed":
            verification_state = _verification_result_state(run, result)
            if verification_state == "missing":
                blockers.append(_blocker("VERIFICATION_MISSING"))
            elif verification_state == "failed":
                blockers.append(_blocker("VERIFICATION_FAILED"))
            elif verification_state != "passed":
                blockers.append(_blocker("VERIFICATION_UNAVAILABLE"))
        return None, {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    if run.status not in TERMINAL_RUN_STATUSES:
        blockers.append(_blocker("RUN_NOT_TERMINAL"))
        return None, {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }

    task = run.task
    pack = run.pack
    if task is None or pack is None or pack.task_id != run.task_id:
        blockers.append(_blocker("TASK_BINDING_STALE"))
        return None, {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    if not _run_result_evidence_complete(run, result):
        blockers.append(_blocker("RUN_EVIDENCE_INCOMPLETE"))
    if not _run_result_binding_valid(task, pack, run, result):
        blockers.append(_blocker("RUN_RESULT_BINDING_STALE"))

    verification_state = _verification_result_state(run, result)
    if verification_state == "missing":
        blockers.append(_blocker("VERIFICATION_MISSING"))
    elif verification_state == "failed":
        blockers.append(_blocker("VERIFICATION_FAILED"))
    elif verification_state != "passed":
        blockers.append(_blocker("VERIFICATION_UNAVAILABLE"))

    acceptance = _accepted_for_run(session, owner_id, task, run)
    acceptance_row = session.scalar(
        select(OwnerAcceptanceSession).where(
            OwnerAcceptanceSession.codex_run_id == run.id
        )
    )
    if acceptance is None:
        blockers.append(
            _blocker(
                "RESULT_REJECTED"
                if acceptance_row is not None
                and acceptance_row.status == "rejected"
                else "ACCEPTANCE_INVALID"
            )
        )

    current_task_digest = development_task_digest(task.development_task)
    if (
        task.task_version != run.task_version
        or pack.task_version != run.task_version
        or not run.development_task_digest
        or run.development_task_digest != current_task_digest
        or pack.development_task_digest != current_task_digest
        or run.development_task != task.development_task
        or pack.development_task != task.development_task
    ):
        blockers.append(_blocker("TASK_BINDING_STALE"))

    latest_pack = session.scalar(
        select(CodexInstructionPack)
        .where(CodexInstructionPack.task_id == task.id)
        .order_by(CodexInstructionPack.version.desc())
    )
    if (
        pack.id != run.pack_id
        or latest_pack is None
        or latest_pack.id != pack.id
        or pack.status != "approved"
        or pack.invalidated_at is not None
        or pack.approved_by_user_id != owner_id
    ):
        blockers.append(_blocker("PACK_BINDING_STALE"))

    if not _assignment_bindings_valid(session, task, run, pack):
        blockers.append(_blocker("ASSIGNMENT_BINDING_STALE"))
    if not _routing_snapshot_available(pack, run):
        blockers.append(_blocker("ROUTING_SNAPSHOT_UNAVAILABLE"))

    try:
        source_snapshot = _validated_source_snapshot(pack, run)
    except ManifestError:
        source_snapshot = None
        blockers.append(_blocker("SOURCE_SNAPSHOT_UNAVAILABLE"))

    coding_evidence = _verified_evidence(
        session, run, "coding", run.execution_assignment_id
    )
    verification_evidence = _verified_evidence(
        session, run, "verification", run.verification_assignment_id
    )
    if (
        coding_evidence is None
        or not has_complete_verified_codex_run_evidence(session, run)
    ):
        blockers.append(_blocker("CODING_EVIDENCE_INCOMPLETE"))
    if (
        verification_evidence is None
        or not has_complete_verified_codex_run_evidence(session, run)
    ):
        blockers.append(_blocker("VERIFICATION_EVIDENCE_INCOMPLETE"))
    if (
        coding_evidence is not None
        and verification_evidence is not None
        and (
            coding_evidence.id == verification_evidence.id
            or coding_evidence.invocation_ref == verification_evidence.invocation_ref
        )
    ):
        blockers.append(_blocker("VERIFICATION_EVIDENCE_INCOMPLETE"))
    blockers.extend(
        _persisted_process_identity_blockers(
            coding_evidence,
            verification_evidence,
        )
    )

    manifest: list[dict[str, Any]] | None = None
    if source_snapshot is not None and coding_evidence is not None:
        try:
            manifest = build_run_file_manifest(
                run,
                source_snapshot,
                coding_evidence.invocation_ref,
            )
        except ManifestError as exc:
            message = str(exc).casefold()
            code = (
                "MANIFEST_DUPLICATE_CONFLICT"
                if "duplicate" in message
                else "MANIFEST_PATH_UNSAFE"
                if "path" in message or "outside" in message
                else "MANIFEST_UNAVAILABLE"
            )
            blockers.append(_blocker(code))

    unique = {item["code"]: item for item in blockers}
    blockers = [unique[code] for code in unique]
    if blockers or acceptance is None or coding_evidence is None or verification_evidence is None or manifest is None:
        return None, {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }

    post_snapshot_digest = result.get("post_run_snapshot_digest")
    coding_prompt_digest = result.get("coding_prompt_digest")
    if (
        not isinstance(post_snapshot_digest, str)
        or not SHA256_PATTERN.fullmatch(post_snapshot_digest)
        or not isinstance(coding_prompt_digest, str)
        or not SHA256_PATTERN.fullmatch(coding_prompt_digest)
    ):
        blockers = [_blocker("MANIFEST_UNAVAILABLE")]
        return None, {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    patch_identity = canonical_sha256(
        {
            "schema": "twos.delivery_patch_identity.v1",
            "run_id": run.id,
            "source_snapshot_identity": run.source_snapshot_digest,
            "post_run_snapshot_identity": post_snapshot_digest,
            "coding_prompt_identity": coding_prompt_digest,
            "manifest": manifest,
        }
    )
    coding_evidence_digest = _evidence_digest(coding_evidence)
    verification_evidence_digest = _evidence_digest(verification_evidence)
    candidate_id = "dc_" + canonical_sha256(
        {
            "schema": "twos.delivery_candidate_public_id.v1",
            "owner_id": owner_id,
            "run_id": run.id,
        }
    )[:40]
    material = {
        "candidate_id": candidate_id,
        "owner_id": owner_id,
        "task_id": task.id,
        "task_version": task.task_version,
        "pack_id": pack.id,
        "pack_version": pack.version,
        "coding_assignment_id": run.execution_assignment_id,
        "coding_assignment_version": run.execution_assignment.assignment_version,
        "verification_assignment_id": run.verification_assignment_id,
        "verification_assignment_version": run.verification_assignment.assignment_version,
        "routing_snapshot_identity": run.routing_snapshot_hash,
        "source_snapshot_identity": run.source_snapshot_digest,
        "source_baseline_commit": run.source_commit,
        "run_id": run.id,
        "coding_evidence_id": coding_evidence.id,
        "coding_evidence_identity": coding_evidence.invocation_ref,
        "coding_evidence_digest": coding_evidence_digest,
        "verification_evidence_id": verification_evidence.id,
        "verification_evidence_identity": verification_evidence.invocation_ref,
        "verification_evidence_digest": verification_evidence_digest,
        "verification_verdict": "passed",
        "acceptance_id": acceptance.id,
        "acceptance_status": acceptance.status,
        "file_manifest": manifest,
        "patch_identity": patch_identity,
    }
    material["candidate_digest"] = canonical_sha256(
        _candidate_digest_payload(material)
    )
    return material, {
        "eligible": True,
        "blockers": [],
        "next_action": "Review the immutable Candidate and Source Drift status.",
    }


def delivery_candidate_eligibility(
    session: Session,
    owner_id: int,
    run: CodexRun,
) -> dict[str, Any]:
    _, eligibility = _candidate_material(session, owner_id, run)
    return eligibility


def _candidate_digest_payload(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "twos.delivery_candidate.v1",
        "candidate_id": material["candidate_id"],
        "owner_id": material["owner_id"],
        "task_id": material["task_id"],
        "task_version": material["task_version"],
        "pack_id": material["pack_id"],
        "pack_version": material["pack_version"],
        "coding_assignment_id": material["coding_assignment_id"],
        "coding_assignment_version": material["coding_assignment_version"],
        "verification_assignment_id": material["verification_assignment_id"],
        "verification_assignment_version": material[
            "verification_assignment_version"
        ],
        "routing_snapshot_identity": material["routing_snapshot_identity"],
        "source_snapshot_identity": material["source_snapshot_identity"],
        "source_baseline_commit": material["source_baseline_commit"],
        "run_id": material["run_id"],
        "coding_evidence_id": material["coding_evidence_id"],
        "coding_evidence_identity": material["coding_evidence_identity"],
        "coding_evidence_digest": material["coding_evidence_digest"],
        "verification_evidence_id": material["verification_evidence_id"],
        "verification_evidence_identity": material[
            "verification_evidence_identity"
        ],
        "verification_evidence_digest": material["verification_evidence_digest"],
        "verification_verdict": material["verification_verdict"],
        "acceptance_id": material["acceptance_id"],
        "acceptance_status": material["acceptance_status"],
        "file_manifest": material["file_manifest"],
        "patch_identity": material["patch_identity"],
    }


def _stored_candidate_material(candidate: DeliveryCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "owner_id": candidate.owner_id,
        "task_id": candidate.task_id,
        "task_version": candidate.task_version,
        "pack_id": candidate.pack_id,
        "pack_version": candidate.pack_version,
        "coding_assignment_id": candidate.coding_assignment_id,
        "coding_assignment_version": candidate.coding_assignment_version,
        "verification_assignment_id": candidate.verification_assignment_id,
        "verification_assignment_version": candidate.verification_assignment_version,
        "routing_snapshot_identity": candidate.routing_snapshot_identity,
        "source_snapshot_identity": candidate.source_snapshot_identity,
        "source_baseline_commit": candidate.source_baseline_commit,
        "run_id": candidate.run_id,
        "coding_evidence_id": candidate.coding_evidence_id,
        "coding_evidence_identity": candidate.coding_evidence_identity,
        "coding_evidence_digest": candidate.coding_evidence_digest,
        "verification_evidence_id": candidate.verification_evidence_id,
        "verification_evidence_identity": candidate.verification_evidence_identity,
        "verification_evidence_digest": candidate.verification_evidence_digest,
        "verification_verdict": candidate.verification_verdict,
        "acceptance_id": candidate.acceptance_id,
        "acceptance_status": candidate.acceptance_status,
        "file_manifest": _decoded_list(candidate.file_manifest_json),
        "patch_identity": candidate.patch_identity,
        "candidate_digest": candidate.candidate_digest,
    }


def validate_delivery_candidate(
    session: Session,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate,
) -> dict[str, Any]:
    if (
        candidate.owner_id != owner_id
        or candidate.run_id != run.id
        or candidate.task_id != run.task_id
    ):
        blockers = [_blocker("CANDIDATE_INTEGRITY_INVALID")]
        return {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    stored = _stored_candidate_material(candidate)
    if canonical_sha256(_candidate_digest_payload(stored)) != candidate.candidate_digest:
        blockers = [_blocker("CANDIDATE_INTEGRITY_INVALID")]
        return {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    material, eligibility = _candidate_material(session, owner_id, run)
    if material is None:
        return eligibility
    if canonical_json(_candidate_digest_payload(stored)) != canonical_json(
        _candidate_digest_payload(material)
    ):
        blockers = [_blocker("CANDIDATE_INTEGRITY_INVALID")]
        return {
            "eligible": False,
            "blockers": blockers,
            "next_action": _next_action(blockers),
        }
    return eligibility


def get_or_create_delivery_candidate(
    session: Session,
    owner_id: int,
    run: CodexRun,
) -> tuple[DeliveryCandidate | None, bool, dict[str, Any]]:
    existing = session.scalar(
        select(DeliveryCandidate).where(
            DeliveryCandidate.owner_id == owner_id,
            DeliveryCandidate.run_id == run.id,
        )
    )
    if existing is not None:
        return existing, False, validate_delivery_candidate(
            session, owner_id, run, existing
        )
    material, eligibility = _candidate_material(session, owner_id, run)
    if material is None:
        return None, False, eligibility
    candidate = DeliveryCandidate(
        candidate_id=material["candidate_id"],
        owner_id=material["owner_id"],
        task_id=material["task_id"],
        task_version=material["task_version"],
        pack_id=material["pack_id"],
        pack_version=material["pack_version"],
        coding_assignment_id=material["coding_assignment_id"],
        coding_assignment_version=material["coding_assignment_version"],
        verification_assignment_id=material["verification_assignment_id"],
        verification_assignment_version=material[
            "verification_assignment_version"
        ],
        routing_snapshot_identity=material["routing_snapshot_identity"],
        source_snapshot_identity=material["source_snapshot_identity"],
        source_baseline_commit=material["source_baseline_commit"],
        run_id=material["run_id"],
        coding_evidence_id=material["coding_evidence_id"],
        coding_evidence_identity=material["coding_evidence_identity"],
        coding_evidence_digest=material["coding_evidence_digest"],
        verification_evidence_id=material["verification_evidence_id"],
        verification_evidence_identity=material[
            "verification_evidence_identity"
        ],
        verification_evidence_digest=material["verification_evidence_digest"],
        verification_verdict=material["verification_verdict"],
        acceptance_id=material["acceptance_id"],
        acceptance_status=material["acceptance_status"],
        file_manifest_json=canonical_json(material["file_manifest"]),
        patch_identity=material["patch_identity"],
        candidate_digest=material["candidate_digest"],
    )
    session.add(candidate)
    session.flush()
    return candidate, True, eligibility


def _current_path_conflicts(
    repository_root: Path,
    manifest: Iterable[dict[str, Any]],
) -> list[str]:
    conflicts: list[str] = []
    resolved_root = repository_root.resolve(strict=True)
    for item in manifest:
        path = normalize_repository_path(item.get("path"))
        unresolved = resolved_root / path
        cursor = resolved_root
        final_mode: int | None = None
        unsafe_type = False
        parts = PurePosixPath(path).parts
        for index, part in enumerate(parts):
            cursor = cursor / part
            try:
                entry_mode = cursor.lstat().st_mode
            except FileNotFoundError:
                break
            except OSError:
                unsafe_type = True
                break
            if stat.S_ISLNK(entry_mode):
                unsafe_type = True
                break
            if index < len(parts) - 1 and not stat.S_ISDIR(entry_mode):
                unsafe_type = True
                break
            if index == len(parts) - 1:
                final_mode = entry_mode
        if unsafe_type:
            conflicts.append(path)
            continue
        candidate = unresolved.resolve(strict=False)
        if not candidate.is_relative_to(resolved_root):
            conflicts.append(path)
            continue
        if item.get("operation") == "CREATE":
            if final_mode is not None:
                conflicts.append(path)
            continue
        if final_mode is None or not stat.S_ISREG(final_mode):
            conflicts.append(path)
            continue
        try:
            payload = candidate.read_bytes()
            current_hash = hashlib.sha256(payload).hexdigest()
            current_stat = candidate.lstat()
            if not stat.S_ISREG(current_stat.st_mode):
                conflicts.append(path)
                continue
            current_mode = current_stat.st_mode & 0o777
        except OSError:
            conflicts.append(path)
            continue
        if (
            current_hash != item.get("before_hash")
            or len(payload) != item.get("before_size")
            or current_mode != item.get("before_mode")
        ):
            conflicts.append(path)
    return sorted(set(conflicts))


def evaluate_source_drift(
    session: Session,
    *,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate | None,
    source_repo: Path,
    unavailable_blockers: list[dict[str, str]] | None = None,
    unavailable_next_action: str | None = None,
) -> SourceDriftEvaluation:
    blockers = list(unavailable_blockers or [])
    baseline_digest = (
        candidate.source_snapshot_identity
        if candidate is not None
        else run.source_snapshot_digest or ""
    )
    status = "candidate_unavailable" if blockers or candidate is None else ""
    next_action = (
        unavailable_next_action
        or _next_action(blockers)
        if status == "candidate_unavailable"
        else ""
    )
    current_digest = ""
    current_head = ""
    conflict_paths: list[str] = []
    diagnostics: dict[str, Any] = {
        "inspection": "read_only",
        "git_command_policy": "explicit_allowlist",
        "git_commands": list(SOURCE_DRIFT_READ_ONLY_GIT_ALLOWLIST),
    }
    if not status:
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
            if verified_root != configured_root:
                raise RuntimeError("Configured source path is not the repository root.")
            stored_root = Path(run.source_repo).resolve(strict=True)
            if stored_root != verified_root:
                raise RuntimeError("Run source identity does not match configured source.")
            source = git_source_state(
                verified_root,
                hardened_read_only=True,
                verified_root=verified_root,
            )
            current_branch = str(source.get("branch") or "")
            branch_matches_baseline = (
                bool(current_branch) and current_branch == run.source_branch
            )
            diagnostics["branch_matches_baseline"] = branch_matches_baseline
            diagnostics["detached_head"] = not bool(current_branch)
            snapshot = capture_source_snapshot(
                verified_root,
                hardened_read_only=True,
                verified_source_state=source,
            )
            current_digest = str(snapshot.get("digest") or "")
            current_head = str(snapshot.get("head_sha") or "")
            if (
                not SHA256_PATTERN.fullmatch(current_digest)
                or not GIT_OBJECT_PATTERN.fullmatch(current_head)
            ):
                raise RuntimeError("Repository identities are invalid.")
            manifest = _decoded_list(candidate.file_manifest_json)
            conflict_paths = _current_path_conflicts(verified_root, manifest)
            diagnostics["repository"] = "available"
            diagnostics["candidate_preconditions"] = (
                "conflict" if conflict_paths else "satisfied"
            )
            diagnostics["source_matches_baseline"] = (
                current_digest == baseline_digest
            )
            if conflict_paths:
                status = "conflict_detected"
                blockers = [
                    {
                        "code": "CANDIDATE_PREIMAGE_CONFLICT",
                        "message": "One or more Candidate paths no longer match the approved preimage.",
                    }
                ]
                next_action = (
                    "Review the conflicting paths and run a newly approved Codex Pack."
                )
            elif current_digest != baseline_digest or not branch_matches_baseline:
                status = "source_changed_since_run"
                blockers = [
                    {
                        "code": "SOURCE_CHANGED_OUTSIDE_CANDIDATE",
                        "message": "Source changed outside Candidate-touched paths since this Run.",
                    }
                ]
                next_action = (
                    "Review the unrelated source changes before any future apply plan."
                )
            else:
                status = "ready_to_apply"
                blockers = []
                next_action = (
                    "Review the Candidate; applying changes is not available in Phase 18.1."
                )
        except (
            OSError,
            RuntimeError,
            ManifestError,
            ValueError,
            subprocess.SubprocessError,
        ):
            status = "repository_unavailable"
            blockers = [
                {
                    "code": "REPOSITORY_UNAVAILABLE",
                    "message": "The source repository could not be verified safely.",
                }
            ]
            next_action = "Restore read-only repository access and review again."
            current_digest = ""
            current_head = ""
            conflict_paths = []
            diagnostics["repository"] = "unavailable"
            diagnostics["reason_code"] = "repository_inspection_failed"
    else:
        diagnostics["candidate"] = "unavailable"
    evaluation = SourceDriftEvaluation(
        candidate_id=candidate.id if candidate is not None else None,
        owner_id=owner_id,
        task_id=run.task_id,
        run_id=run.id,
        status=status,
        blockers_json=canonical_json(blockers),
        next_action=next_action,
        baseline_source_digest=baseline_digest,
        current_source_digest=current_digest,
        current_head=current_head,
        conflict_paths_json=canonical_json(conflict_paths),
        diagnostics_json=canonical_json(diagnostics),
    )
    session.add(evaluation)
    session.flush()
    return evaluation


def delivery_candidate_out(candidate: DeliveryCandidate) -> dict[str, Any]:
    manifest = _decoded_list(candidate.file_manifest_json)
    return {
        "id": candidate.candidate_id,
        "status": "available",
        "status_label": "Available",
        "changed_files": [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "operation": item.get("operation"),
                "unexpected": item.get("unexpected"),
                "before_hash": item.get("before_hash"),
                "after_hash": item.get("after_hash"),
                "before_size": item.get("before_size"),
                "after_size": item.get("after_size"),
                "content_kind": (
                    "binary"
                    if item.get("content_kind") == "binary_or_oversized"
                    else item.get("content_kind")
                ),
                "evidence_identity": item.get("evidence_identity"),
            }
            for item in manifest
            if isinstance(item, dict)
        ],
        "unexpected_file_count": sum(
            1
            for item in manifest
            if isinstance(item, dict) and item.get("unexpected") is True
        ),
        "acceptance_status": candidate.acceptance_status,
        "verification_status": "PASS",
        "candidate_digest": candidate.candidate_digest,
        "patch_identity": candidate.patch_identity,
        "source_snapshot_identity": candidate.source_snapshot_identity,
        "task_id": candidate.task_id,
        "task_version": candidate.task_version,
        "pack_id": candidate.pack_id,
        "pack_version": candidate.pack_version,
        "coding_assignment_id": candidate.coding_assignment_id,
        "coding_assignment_version": candidate.coding_assignment_version,
        "verification_assignment_id": candidate.verification_assignment_id,
        "verification_assignment_version": candidate.verification_assignment_version,
        "routing_snapshot_identity": candidate.routing_snapshot_identity,
        "run_id": candidate.run_id,
        "coding_evidence_identity": candidate.coding_evidence_identity,
        "verification_evidence_identity": candidate.verification_evidence_identity,
        "created_at": _iso(candidate.created_at),
    }


def source_drift_out(evaluation: SourceDriftEvaluation) -> dict[str, Any]:
    return {
        "status": evaluation.status,
        "status_label": DRIFT_STATUS_LABELS[evaluation.status],
        "blockers": _decoded_list(evaluation.blockers_json),
        "next_action": evaluation.next_action,
        "evaluation_id": evaluation.id,
        "evaluated_at": _iso(evaluation.created_at),
        "baseline_source_digest": evaluation.baseline_source_digest or None,
        "current_source_digest": evaluation.current_source_digest or None,
        "current_head": evaluation.current_head or None,
        "conflict_paths": _decoded_list(evaluation.conflict_paths_json),
        "diagnostics": _decoded_object(evaluation.diagnostics_json),
    }
