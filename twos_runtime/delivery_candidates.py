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
from sqlalchemy.exc import IntegrityError
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
    AuditEvent,
    CodexExecutionAttempt,
    CodexInstructionPack,
    CodexResultArtifact,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
    DeliveryCandidate,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    SourceDriftEvaluation,
    Task,
)
from .self_hosting import (
    SOURCE_REPOSITORY_IDENTITY_METHOD,
    SOURCE_REPOSITORY_IDENTITY_METHODS,
    SOURCE_SNAPSHOT_SCHEMA,
    _snapshot_exclusion_reason,
    _source_snapshot_digest,
    capture_source_snapshot,
    development_task_digest,
    git_source_state,
    run_git,
    source_snapshot_has_strong_repository_identity,
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
LEGACY_CANDIDATE_DERIVATION_VERSION = "twos.delivery_candidate.v1"
RESULT_CANDIDATE_DERIVATION_VERSION = "twos.result_delivery_candidate.v1"
RESULT_REVIEW_POLICY_VERSION = "twos.result_delivery_review.v1"
ATTEMPT_ID_PATTERN = re.compile(r"^attempt-[0-9a-f]{32}$")
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


def _execution_attempt(
    session: Session,
    *,
    owner_id: int,
    run_id: int,
    phase: str,
) -> CodexExecutionAttempt | None:
    return session.scalar(
        select(CodexExecutionAttempt)
        .where(
            CodexExecutionAttempt.owner_id == owner_id,
            CodexExecutionAttempt.run_id == run_id,
            CodexExecutionAttempt.phase == phase,
        )
        .order_by(
            CodexExecutionAttempt.attempt_number.desc(),
            CodexExecutionAttempt.id.desc(),
        )
        .limit(1)
    )


def _result_review_status(value: object) -> str:
    normalized = str(value or "owner_review").strip().lower()
    return {
        "owner_review": "pending",
        "pending": "pending",
        "accepted": "accepted_for_delivery",
        "accepted_for_delivery": "accepted_for_delivery",
        "rejected": "rejected",
    }.get(normalized, "pending")


def result_review_decision_payload(
    acceptance: OwnerAcceptanceSession,
    *,
    decision_status: str | None = None,
) -> dict[str, Any]:
    """Canonical immutable Owner decision binding shared with delivery gates."""
    status = str(decision_status or acceptance.status or "").strip().lower()
    return {
        "schema": "twos.result_delivery_review_decision.v1",
        "review_policy_version": acceptance.review_policy_version,
        "decision_version": acceptance.decision_version,
        "acceptance_id": acceptance.id,
        "owner_id": acceptance.owner_id,
        "result_envelope_id": acceptance.result_envelope_id,
        "result_envelope_public_id": acceptance.result_envelope_public_id,
        "result_digest": acceptance.result_digest,
        "result_task_version": acceptance.result_task_version,
        "result_pack_id": acceptance.result_pack_id,
        "result_pack_version": acceptance.result_pack_version,
        "approved_instruction_digest": acceptance.approved_instruction_digest,
        "delivery_candidate_id": acceptance.delivery_candidate_id,
        "candidate_public_id": acceptance.candidate_public_id,
        "candidate_version": acceptance.candidate_version,
        "candidate_digest": acceptance.candidate_digest,
        "status": status,
        "owner_note_digest": hashlib.sha256(
            (acceptance.owner_note or "").encode("utf-8")
        ).hexdigest(),
        "decided_by_user_id": acceptance.decided_by_user_id,
        "decided_at": _iso(acceptance.decided_at),
    }


def result_review_decision_digest(
    acceptance: OwnerAcceptanceSession,
    *,
    decision_status: str | None = None,
) -> str:
    return canonical_sha256(
        result_review_decision_payload(
            acceptance,
            decision_status=decision_status,
        )
    )


def _result_candidate_blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _result_artifact_manifest(
    session: Session,
    envelope: CodexResultEnvelope,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = list(
        session.scalars(
            select(CodexResultArtifact)
            .where(CodexResultArtifact.result_envelope_id == envelope.id)
            .order_by(CodexResultArtifact.ordinal)
        ).all()
    )
    blockers: list[dict[str, str]] = []
    manifest: list[dict[str, Any]] = []
    ordinals: list[int] = []
    seen_paths: set[str] = set()
    for row in rows:
        try:
            path = normalize_repository_path(row.repository_path)
        except ManifestError:
            blockers.append(
                _result_candidate_blocker(
                    "ATTRIBUTED_PATH_UNSAFE",
                    "A Run-attributed path failed the authorized workspace boundary.",
                )
            )
            continue
        if path in seen_paths:
            blockers.append(
                _result_candidate_blocker(
                    "ATTRIBUTION_DUPLICATE_PATH",
                    "Run attribution contains a duplicate path.",
                )
            )
            continue
        seen_paths.add(path)
        ordinals.append(row.ordinal)
        operation = str(row.operation or "").upper()
        if operation not in {"CREATE", "MODIFY", "DELETE"}:
            blockers.append(
                _result_candidate_blocker(
                    "ATTRIBUTION_OPERATION_UNSUPPORTED",
                    "A Run-attributed file action is unsupported.",
                )
            )
            continue
        artifact_payload = {
            "result_digest": envelope.result_digest,
            "ordinal": row.ordinal,
            "path": row.repository_path,
            "display_path": row.display_path,
            "path_identity": row.path_identity,
            "operation": row.operation,
            "before_hash": row.before_hash,
            "after_hash": row.after_hash,
            "before_size": row.before_size,
            "after_size": row.after_size,
            "before_mode": row.before_mode,
            "after_mode": row.after_mode,
            "content_kind": row.content_kind,
            "unexpected": row.unexpected,
            "evidence_identity": row.evidence_identity,
        }
        if (
            not SHA256_PATTERN.fullmatch(row.path_identity or "")
            or row.path_identity != canonical_sha256(path)
            or not SHA256_PATTERN.fullmatch(row.evidence_identity or "")
            or not SHA256_PATTERN.fullmatch(row.artifact_digest or "")
            or row.artifact_digest != canonical_sha256(artifact_payload)
        ):
            blockers.append(
                _result_candidate_blocker(
                    "ATTRIBUTION_INTEGRITY_INVALID",
                    "A Run-attributed file action failed its immutable evidence check.",
                )
            )
            continue
        manifest.append(
            {
                "name": PurePosixPath(path).name,
                "path": path,
                "operation": operation,
                "unexpected": bool(row.unexpected),
                "before_hash": row.before_hash,
                "after_hash": row.after_hash,
                "before_size": row.before_size,
                "after_size": row.after_size,
                "before_mode": row.before_mode,
                "after_mode": row.after_mode,
                "content_kind": row.content_kind,
                "evidence_identity": row.evidence_identity,
                "artifact_digest": row.artifact_digest,
            }
        )
    if ordinals and ordinals != list(range(1, len(rows) + 1)):
        blockers.append(
            _result_candidate_blocker(
                "ATTRIBUTION_ORDINAL_INVALID",
                "Run attribution contains incomplete file-action ordering.",
            )
        )
    return manifest, blockers


def _attribution_material(
    envelope: CodexResultEnvelope,
    manifest: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    workspace = _decoded_object(envelope.workspace_evidence_json)
    raw_attribution = workspace.get("attribution")
    attribution = raw_attribution if isinstance(raw_attribution, dict) else {}
    blockers: list[dict[str, str]] = []
    if not isinstance(raw_attribution, dict):
        blockers.append(
            _result_candidate_blocker(
                "ATTRIBUTION_EVIDENCE_INCOMPLETE",
                "Run-produced workspace attribution evidence is unavailable.",
            )
        )

    def safe_paths(key: str) -> list[str]:
        raw = attribution.get(key, [])
        if not isinstance(raw, list):
            blockers.append(
                _result_candidate_blocker(
                    "ATTRIBUTION_EVIDENCE_INCOMPLETE",
                    "Run attribution evidence is incomplete.",
                )
            )
            return []
        output: list[str] = []
        for value in raw:
            try:
                output.append(normalize_repository_path(value))
            except ManifestError:
                blockers.append(
                    _result_candidate_blocker(
                        "ATTRIBUTION_EXCLUDED_PATH_UNSAFE",
                        "An excluded attribution path failed the workspace boundary.",
                    )
                )
        return sorted(set(output))

    baseline_preexisting = safe_paths("baseline_preexisting")
    run_produced = safe_paths("run_produced")
    origin_unproven = safe_paths("origin_unproven")
    included_paths = sorted(str(item["path"]) for item in manifest)
    if run_produced != included_paths:
        blockers.append(
            _result_candidate_blocker(
                "ATTRIBUTION_RESULT_MISMATCH",
                "Run-produced attribution does not match the immutable Result artifacts.",
            )
        )
    if set(baseline_preexisting) & set(run_produced):
        blockers.append(
            _result_candidate_blocker(
                "ATTRIBUTION_ORIGIN_CONFLICT",
                "A Run-produced path is also classified as pre-existing content.",
            )
        )
    excluded = [
        {
            "path": path,
            "reason_code": "BASELINE_PREEXISTING",
            "reason": "The path pre-existed this Run and is excluded from delivery.",
        }
        for path in baseline_preexisting
    ] + [
        {
            "path": path,
            "reason_code": "ORIGIN_UNPROVEN",
            "reason": "The file origin was not proven as a Run-created deliverable.",
        }
        for path in origin_unproven
        if path not in set(baseline_preexisting)
    ]
    summary = {
        "schema": "twos.result_candidate_attribution.v1",
        "baseline_preexisting": baseline_preexisting,
        "run_produced": included_paths,
        "origin_unproven": origin_unproven,
        "included_count": len(included_paths),
        "excluded_count": len(excluded),
    }
    return summary, excluded, blockers


def _attempt_succeeded(
    attempt: CodexExecutionAttempt | None,
    *,
    owner_id: int,
    envelope: CodexResultEnvelope,
    phase: str,
) -> bool:
    expected_assignment_id = (
        envelope.coding_assignment_id
        if phase == "CODING"
        else envelope.verification_assignment_id
    )
    expected_assignment_version = (
        envelope.coding_assignment_version
        if phase == "CODING"
        else envelope.verification_assignment_version
    )
    return bool(
        attempt is not None
        and ATTEMPT_ID_PATTERN.fullmatch(attempt.attempt_id or "")
        and attempt.owner_id == owner_id
        and attempt.task_id == envelope.task_id
        and attempt.task_version == envelope.task_version
        and attempt.run_id == envelope.run_id
        and attempt.pack_id == envelope.pack_id
        and attempt.pack_version == envelope.pack_version
        and attempt.coding_assignment_id == envelope.coding_assignment_id
        and attempt.coding_assignment_version
        == envelope.coding_assignment_version
        and attempt.verification_assignment_id
        == envelope.verification_assignment_id
        and attempt.verification_assignment_version
        == envelope.verification_assignment_version
        and (
            attempt.coding_assignment_id
            if phase == "CODING"
            else attempt.verification_assignment_id
        )
        == expected_assignment_id
        and (
            attempt.coding_assignment_version
            if phase == "CODING"
            else attempt.verification_assignment_version
        )
        == expected_assignment_version
        and attempt.routing_snapshot_identity == envelope.routing_snapshot_identity
        and attempt.source_snapshot_identity == envelope.source_snapshot_identity
        and attempt.monitor_id == envelope.monitor_id
        and attempt.phase == phase
        and attempt.attempt_state == "COMPLETED"
        and attempt.process_exit_known
        and attempt.process_exit_code == 0
        and attempt.terminal_event_observed
    )


def _result_candidate_digest_payload(material: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_CANDIDATE_DERIVATION_VERSION,
        "candidate_id": material["candidate_id"],
        "candidate_version": material["candidate_version"],
        "derivation_version": material["derivation_version"],
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
        "result_envelope_id": material["result_envelope_id"],
        "result_envelope_public_id": material["result_envelope_public_id"],
        "result_digest": material["result_digest"],
        "approved_instruction_digest": material["approved_instruction_digest"],
        "coding_attempt_id": material["coding_attempt_id"],
        "coding_attempt_identity": material["coding_attempt_identity"],
        "coding_outcome": material["coding_outcome"],
        "coding_evidence_id": material["coding_evidence_id"],
        "coding_evidence_identity": material["coding_evidence_identity"],
        "coding_evidence_digest": material["coding_evidence_digest"],
        "verification_policy": material["verification_policy"],
        "verification_attempt_id": material["verification_attempt_id"],
        "verification_attempt_identity": material[
            "verification_attempt_identity"
        ],
        "verification_receipt_identity": material[
            "verification_receipt_identity"
        ],
        "verification_evidence_id": material["verification_evidence_id"],
        "verification_evidence_identity": material[
            "verification_evidence_identity"
        ],
        "verification_evidence_digest": material[
            "verification_evidence_digest"
        ],
        "verification_verdict": material["verification_verdict"],
        "result_integrity_state": material["result_integrity_state"],
        "source_workspace_identity": material["source_workspace_identity"],
        "run_workspace_identity": material["run_workspace_identity"],
        "run_workspace_baseline_identity": material[
            "run_workspace_baseline_identity"
        ],
        "run_workspace_post_state_identity": material[
            "run_workspace_post_state_identity"
        ],
        "acceptance_id": material["acceptance_id"],
        "acceptance_status": material["acceptance_status"],
        "file_manifest": material["file_manifest"],
        "excluded_manifest": material["excluded_manifest"],
        "attribution_summary": material["attribution_summary"],
        "readiness_state": material["readiness_state"],
        "readiness_reason": material["readiness_reason"],
        "readiness_blockers": material["readiness_blockers"],
        "patch_identity": material["patch_identity"],
    }


def _result_candidate_material(
    session: Session,
    *,
    owner_id: int,
    envelope: CodexResultEnvelope,
    acceptance: OwnerAcceptanceSession,
) -> dict[str, Any]:
    run = session.get(CodexRun, envelope.run_id)
    monitor = session.get(CodexRunMonitor, envelope.monitor_id)
    if run is None:
        raise ManifestError("The Result-bound Run is unavailable.")
    coding_attempt = _execution_attempt(
        session,
        owner_id=owner_id,
        run_id=run.id,
        phase="CODING",
    )
    verification_attempt = _execution_attempt(
        session,
        owner_id=owner_id,
        run_id=run.id,
        phase="VERIFICATION",
    )
    coding_evidence = _verified_evidence(
        session,
        run,
        "coding",
        envelope.coding_assignment_id,
    )
    verification_evidence = _verified_evidence(
        session,
        run,
        "verification",
        envelope.verification_assignment_id,
    )
    manifest, blockers = _result_artifact_manifest(session, envelope)
    attribution, excluded, attribution_blockers = _attribution_material(
        envelope,
        manifest,
    )
    blockers.extend(attribution_blockers)
    coding_summary = _decoded_object(envelope.coding_evidence_json)
    verification_summary = _decoded_object(envelope.verification_evidence_json)
    workspace = _decoded_object(envelope.workspace_evidence_json)
    approved_source_snapshot = (
        _decoded_object(run.pack.source_snapshot_json)
        if run.pack is not None
        else {}
    )
    try:
        approved_source_snapshot_digest = _source_snapshot_digest(
            approved_source_snapshot
        )
    except (TypeError, ValueError):
        approved_source_snapshot_digest = ""
    strong_source_binding = bool(
        source_snapshot_has_strong_repository_identity(approved_source_snapshot)
        and approved_source_snapshot_digest
        == approved_source_snapshot.get("digest")
        == run.source_snapshot_digest
        == envelope.source_snapshot_identity
        and approved_source_snapshot.get("source_repository_identity")
        == envelope.authorized_workspace_identity
    )

    binding_valid = bool(
        envelope.owner_id == owner_id
        and envelope.task_id == run.task_id
        and envelope.task_version == run.task_version
        and envelope.pack_id == run.pack_id
        and run.pack is not None
        and envelope.pack_version == run.pack.version
        and monitor is not None
        and monitor.owner_id == owner_id
        and monitor.run_id == run.id
        and monitor.task_id == envelope.task_id
        and monitor.task_version == envelope.task_version
        and monitor.pack_id == envelope.pack_id
        and monitor.pack_version == envelope.pack_version
        and monitor.coding_assignment_id == envelope.coding_assignment_id
        and monitor.coding_assignment_version
        == envelope.coding_assignment_version
        and monitor.verification_assignment_id
        == envelope.verification_assignment_id
        and monitor.verification_assignment_version
        == envelope.verification_assignment_version
        and envelope.routing_snapshot_identity == run.routing_snapshot_hash
        and monitor.routing_snapshot_identity == envelope.routing_snapshot_identity
        and envelope.source_snapshot_identity == run.source_snapshot_digest
        and monitor.source_snapshot_identity == envelope.source_snapshot_identity
        and SHA256_PATTERN.fullmatch(envelope.result_digest or "")
        and SHA256_PATTERN.fullmatch(envelope.approved_instruction_digest or "")
    )
    if not binding_valid:
        blockers.append(
            _result_candidate_blocker(
                "RESULT_BINDING_INVALID",
                "The immutable Result no longer matches its Run, Task, or approved Pack binding.",
            )
        )
    if not strong_source_binding:
        blockers.append(
            _result_candidate_blocker(
                "SOURCE_WORKSPACE_IDENTITY_WEAK",
                "The Result is not bound to the exact approved source repository identity. Regenerate and run an approved Pack before delivery.",
            )
        )

    coding_succeeded = bool(
        envelope.terminal_status == "completed"
        and envelope.process_exit_code == 0
        and coding_summary.get("outcome") == "succeeded"
        and _attempt_succeeded(
            coding_attempt,
            owner_id=owner_id,
            envelope=envelope,
            phase="CODING",
        )
    )
    coding_outcome = (
        "succeeded"
        if coding_succeeded
        else "cancelled"
        if envelope.terminal_status == "cancelled"
        else "timed_out"
        if envelope.terminal_status == "timed_out"
        else "failed"
    )
    if not coding_succeeded:
        blockers.append(
            _result_candidate_blocker(
                "CODING_NOT_SUCCEEDED",
                "Coding did not produce a sealed successful process outcome.",
            )
        )
    if coding_attempt is None:
        blockers.append(
            _result_candidate_blocker(
                "CODING_ATTEMPT_UNAVAILABLE",
                "The sealed Coding attempt identity is unavailable.",
            )
        )

    result_integrity = str(envelope.integrity_state or "").upper()
    if result_integrity != "VERIFIED":
        blockers.append(
            _result_candidate_blocker(
                "RESULT_INTEGRITY_INVALID",
                "The Result evidence envelope is not integrity-verified.",
            )
        )

    verification_required = envelope.verification_assignment_id is not None
    verification_policy = "required" if verification_required else "not_required"
    raw_verdict = str(envelope.verification_verdict or "UNAVAILABLE").upper()
    if not verification_required:
        verification_verdict = "not_required"
    elif raw_verdict == "PASS":
        verification_verdict = "passed"
    elif raw_verdict == "FAIL":
        verification_verdict = "failed"
    else:
        verification_verdict = "unavailable"
    if verification_required:
        verification_attempt_valid = bool(
            _attempt_succeeded(
                verification_attempt,
                owner_id=owner_id,
                envelope=envelope,
                phase="VERIFICATION",
            )
            and verification_attempt is not None
            and SHA256_PATTERN.fullmatch(verification_attempt.receipt_digest or "")
            and verification_summary.get("outcome") == "succeeded"
        )
        if verification_verdict != "passed":
            blockers.append(
                _result_candidate_blocker(
                    "VERIFICATION_GATE_NOT_PASSED",
                    "Required independent Verification did not pass.",
                )
            )
        if not verification_attempt_valid:
            blockers.append(
                _result_candidate_blocker(
                    "VERIFICATION_ATTEMPT_UNAVAILABLE",
                    "Required independent Verification lacks a sealed passing attempt and receipt.",
                )
            )

    boundary_violations = workspace.get("boundary_violations")
    boundary_codes = (
        [str(value) for value in boundary_violations]
        if isinstance(boundary_violations, list)
        else []
    )
    workspace_available = bool(
        workspace
        and workspace.get("status") != "unavailable"
        and envelope.completion_classification
        in {"succeeded_with_changes", "succeeded_without_workspace_changes"}
    )
    if not workspace_available or boundary_codes:
        blockers.append(
            _result_candidate_blocker(
                "WORKSPACE_EVIDENCE_BLOCKED",
                (
                    "Workspace evidence reported a boundary conflict: "
                    + ", ".join(sorted(set(boundary_codes)))
                    if boundary_codes
                    else "Workspace evidence is incomplete or conflicted."
                ),
            )
        )

    source_workspace_identity = envelope.authorized_workspace_identity or ""
    run_workspace_identity = (
        monitor.isolated_worktree_identity if monitor is not None else ""
    )
    baseline_identity = envelope.workspace_baseline_identity or ""
    verification_repository_identity = (
        verification_attempt.repository_state_identity
        if verification_attempt is not None
        else ""
    )
    post_state_identity = (
        verification_repository_identity
        if SHA256_PATTERN.fullmatch(verification_repository_identity)
        else canonical_sha256(
            {
                "schema": "twos.result_candidate_post_state.v1",
                "result_digest": envelope.result_digest,
                "diff_identity": envelope.diff_identity,
                "artifacts": [item.get("artifact_digest") for item in manifest],
                "workspace_evidence": workspace,
            }
        )
    )
    if any(
        not SHA256_PATTERN.fullmatch(value or "")
        for value in (
            source_workspace_identity,
            run_workspace_identity,
            baseline_identity,
            post_state_identity,
        )
    ):
        blockers.append(
            _result_candidate_blocker(
                "WORKSPACE_BINDING_INCOMPLETE",
                "Source and isolated Run workspace identities are incomplete.",
            )
        )

    unique_blockers = {
        str(item["code"]): item for item in blockers if item.get("code")
    }
    blockers = [unique_blockers[code] for code in unique_blockers]
    if blockers:
        readiness_state = "blocked"
        readiness_reason = blockers[0]["message"]
    elif not manifest:
        readiness_state = "no_changes"
        readiness_reason = (
            "Coding completed, but the immutable Result contains no attributed "
            "deliverable file change."
        )
    else:
        readiness_state = "ready"
        readiness_reason = (
            "The immutable Run Result and its Verification and workspace evidence "
            "are ready for explicit Owner delivery review."
        )

    patch_identity = canonical_sha256(
        {
            "schema": "twos.result_delivery_patch.v1",
            "result_digest": envelope.result_digest,
            "source_workspace_identity": source_workspace_identity,
            "run_workspace_identity": run_workspace_identity,
            "run_workspace_baseline_identity": baseline_identity,
            "run_workspace_post_state_identity": post_state_identity,
            "manifest": manifest,
            "excluded_manifest": excluded,
        }
    )
    candidate_id = "dc_" + canonical_sha256(
        {
            "schema": "twos.result_delivery_candidate_public_id.v1",
            "owner_id": owner_id,
            "result_envelope_id": envelope.envelope_id,
            "result_digest": envelope.result_digest,
            "candidate_version": 1,
        }
    )[:40]
    material: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_version": 1,
        "derivation_version": RESULT_CANDIDATE_DERIVATION_VERSION,
        "owner_id": owner_id,
        "task_id": envelope.task_id,
        "task_version": envelope.task_version,
        "pack_id": envelope.pack_id,
        "pack_version": envelope.pack_version,
        "coding_assignment_id": envelope.coding_assignment_id,
        "coding_assignment_version": envelope.coding_assignment_version,
        "verification_assignment_id": envelope.verification_assignment_id,
        "verification_assignment_version": envelope.verification_assignment_version,
        "routing_snapshot_identity": envelope.routing_snapshot_identity,
        "source_snapshot_identity": envelope.source_snapshot_identity,
        "source_baseline_commit": run.source_commit,
        "run_id": envelope.run_id,
        "result_envelope_id": envelope.id,
        "result_envelope_public_id": envelope.envelope_id,
        "result_digest": envelope.result_digest,
        "approved_instruction_digest": envelope.approved_instruction_digest,
        "coding_attempt_id": coding_attempt.id if coding_attempt is not None else None,
        "coding_attempt_identity": (
            coding_attempt.attempt_id if coding_attempt is not None else ""
        ),
        "coding_outcome": coding_outcome,
        "coding_evidence_id": coding_evidence.id if coding_evidence is not None else None,
        "coding_evidence_identity": (
            coding_evidence.invocation_ref if coding_evidence is not None else ""
        ),
        "coding_evidence_digest": (
            _evidence_digest(coding_evidence) if coding_evidence is not None else ""
        ),
        "verification_policy": verification_policy,
        "verification_attempt_id": (
            verification_attempt.id if verification_attempt is not None else None
        ),
        "verification_attempt_identity": (
            verification_attempt.attempt_id if verification_attempt is not None else ""
        ),
        "verification_receipt_identity": (
            verification_attempt.receipt_digest
            if verification_attempt is not None
            else ""
        ),
        "verification_evidence_id": (
            verification_evidence.id if verification_evidence is not None else None
        ),
        "verification_evidence_identity": (
            verification_evidence.invocation_ref
            if verification_evidence is not None
            else ""
        ),
        "verification_evidence_digest": (
            _evidence_digest(verification_evidence)
            if verification_evidence is not None
            else ""
        ),
        "verification_verdict": verification_verdict,
        "result_integrity_state": result_integrity,
        "source_workspace_identity": source_workspace_identity,
        "run_workspace_identity": run_workspace_identity,
        "run_workspace_baseline_identity": baseline_identity,
        "run_workspace_post_state_identity": post_state_identity,
        "acceptance_id": acceptance.id,
        "acceptance_status": "owner_review",
        "file_manifest": manifest,
        "excluded_manifest": excluded,
        "attribution_summary": attribution,
        "readiness_state": readiness_state,
        "readiness_reason": readiness_reason,
        "readiness_blockers": blockers,
        "patch_identity": patch_identity,
    }
    material["candidate_digest"] = canonical_sha256(
        _result_candidate_digest_payload(material)
    )
    return material


def _stored_result_candidate_material(candidate: DeliveryCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "candidate_version": candidate.candidate_version,
        "derivation_version": candidate.derivation_version,
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
        "result_envelope_id": candidate.result_envelope_id,
        "result_envelope_public_id": candidate.result_envelope_public_id,
        "result_digest": candidate.result_digest,
        "approved_instruction_digest": candidate.approved_instruction_digest,
        "coding_attempt_id": candidate.coding_attempt_id,
        "coding_attempt_identity": candidate.coding_attempt_identity,
        "coding_outcome": candidate.coding_outcome,
        "coding_evidence_id": candidate.coding_evidence_id,
        "coding_evidence_identity": candidate.coding_evidence_identity,
        "coding_evidence_digest": candidate.coding_evidence_digest,
        "verification_policy": candidate.verification_policy,
        "verification_attempt_id": candidate.verification_attempt_id,
        "verification_attempt_identity": candidate.verification_attempt_identity,
        "verification_receipt_identity": candidate.verification_receipt_identity,
        "verification_evidence_id": candidate.verification_evidence_id,
        "verification_evidence_identity": candidate.verification_evidence_identity,
        "verification_evidence_digest": candidate.verification_evidence_digest,
        "verification_verdict": candidate.verification_verdict,
        "result_integrity_state": candidate.result_integrity_state,
        "source_workspace_identity": candidate.source_workspace_identity,
        "run_workspace_identity": candidate.run_workspace_identity,
        "run_workspace_baseline_identity": candidate.run_workspace_baseline_identity,
        "run_workspace_post_state_identity": candidate.run_workspace_post_state_identity,
        "acceptance_id": candidate.acceptance_id,
        "acceptance_status": candidate.acceptance_status,
        "file_manifest": _decoded_list(candidate.file_manifest_json),
        "excluded_manifest": _decoded_list(candidate.excluded_manifest_json),
        "attribution_summary": _decoded_object(candidate.attribution_summary_json),
        "readiness_state": candidate.readiness_state,
        "readiness_reason": candidate.readiness_reason,
        "readiness_blockers": _decoded_list(candidate.readiness_blockers_json),
        "patch_identity": candidate.patch_identity,
        "candidate_digest": candidate.candidate_digest,
    }


def _bind_result_acceptance(
    acceptance: OwnerAcceptanceSession,
    *,
    owner_id: int,
    envelope: CodexResultEnvelope,
    candidate: DeliveryCandidate | None = None,
) -> None:
    terminal_binding_valid = bool(
        acceptance.status in {"accepted", "rejected"}
        and acceptance.owner_id == owner_id
        and acceptance.result_envelope_id == envelope.id
        and acceptance.result_envelope_public_id == envelope.envelope_id
        and acceptance.result_digest == envelope.result_digest
        and acceptance.result_task_version == envelope.task_version
        and acceptance.result_pack_id == envelope.pack_id
        and acceptance.result_pack_version == envelope.pack_version
        and acceptance.approved_instruction_digest
        == envelope.approved_instruction_digest
        and acceptance.delivery_candidate_id is not None
        and acceptance.candidate_public_id
        and acceptance.candidate_version is not None
        and acceptance.candidate_digest
        and acceptance.decided_by_user_id == owner_id
        and acceptance.decided_at is not None
        and SHA256_PATTERN.fullmatch(acceptance.decision_digest or "")
        and acceptance.decision_digest == result_review_decision_digest(acceptance)
    )
    if acceptance.status in {"accepted", "rejected"} and not terminal_binding_valid:
        if acceptance.result_envelope_id is None and not acceptance.decision_digest:
            # A pre-19.1C task-acceptance decision is not a delivery decision
            # for this immutable Result. Reconcile it once to Owner review.
            acceptance.status = "owner_review"
            acceptance.owner_note = ""
            acceptance.decided_by_user_id = None
            acceptance.decided_at = None
        else:
            raise ManifestError(
                "The final Owner review decision failed its immutable binding check."
            )
    expected = {
        "owner_id": owner_id,
        "result_envelope_id": envelope.id,
        "result_envelope_public_id": envelope.envelope_id,
        "result_digest": envelope.result_digest,
        "result_task_version": envelope.task_version,
        "result_pack_id": envelope.pack_id,
        "result_pack_version": envelope.pack_version,
        "approved_instruction_digest": envelope.approved_instruction_digest,
        "review_policy_version": RESULT_REVIEW_POLICY_VERSION,
    }
    for field, value in expected.items():
        observed = getattr(acceptance, field)
        if observed not in {None, "", value}:
            raise ManifestError("Owner review is already bound to another Result.")
        if observed in {None, ""}:
            setattr(acceptance, field, value)
    if acceptance.status not in {"accepted", "rejected"}:
        acceptance.status = "owner_review"
        acceptance.decided_by_user_id = None
        acceptance.decided_at = None
        acceptance.decision_digest = ""
    if candidate is not None:
        candidate_expected = {
            "delivery_candidate_id": candidate.id,
            "candidate_public_id": candidate.candidate_id,
            "candidate_version": candidate.candidate_version,
            "candidate_digest": candidate.candidate_digest,
        }
        for field, value in candidate_expected.items():
            observed = getattr(acceptance, field)
            if observed not in {None, "", value}:
                raise ManifestError("Owner review is already bound to another Candidate.")
            if observed in {None, ""}:
                setattr(acceptance, field, value)


def materialize_result_delivery_candidate(
    session: Session,
    *,
    owner_id: int,
    envelope: CodexResultEnvelope,
) -> tuple[DeliveryCandidate, bool, dict[str, Any]]:
    """Idempotently create metadata for one immutable Result; never mutate source."""
    if envelope.owner_id != owner_id:
        raise ManifestError("The Result is unavailable for this Owner.")
    run = session.get(CodexRun, envelope.run_id)
    if run is None or run.task_id != envelope.task_id:
        raise ManifestError("The Result-bound Run is unavailable.")
    existing = session.scalar(
        select(DeliveryCandidate).where(
            DeliveryCandidate.owner_id == owner_id,
            DeliveryCandidate.run_id == run.id,
        )
    )
    if (
        existing is not None
        and existing.derivation_version == LEGACY_CANDIDATE_DERIVATION_VERSION
        and existing.result_envelope_id is None
    ):
        # Historical Vol.18 Candidates and their accepted review decisions are
        # immutable evidence. Result settlement may coexist with that history,
        # but it must not reinterpret or reset the prior Candidate as a new
        # 19.1C Result-delivery decision.
        return existing, False, validate_delivery_candidate(
            session,
            owner_id,
            run,
            existing,
        )
    acceptance = session.scalar(
        select(OwnerAcceptanceSession).where(
            OwnerAcceptanceSession.codex_run_id == run.id,
            OwnerAcceptanceSession.task_id == run.task_id,
        )
    )
    if acceptance is None:
        acceptance = OwnerAcceptanceSession(
            task_id=run.task_id,
            codex_run_id=run.id,
            owner_id=owner_id,
            status="owner_review",
            review_policy_version=RESULT_REVIEW_POLICY_VERSION,
        )
        session.add(acceptance)
        session.flush()
    _bind_result_acceptance(
        acceptance,
        owner_id=owner_id,
        envelope=envelope,
    )
    if existing is not None:
        if existing.result_envelope_id == envelope.id:
            _bind_result_acceptance(
                acceptance,
                owner_id=owner_id,
                envelope=envelope,
                candidate=existing,
            )
        return existing, False, validate_delivery_candidate(
            session,
            owner_id,
            run,
            existing,
        )

    material = _result_candidate_material(
        session,
        owner_id=owner_id,
        envelope=envelope,
        acceptance=acceptance,
    )
    candidate = DeliveryCandidate(
        candidate_id=material["candidate_id"],
        candidate_version=material["candidate_version"],
        derivation_version=material["derivation_version"],
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
        result_envelope_id=material["result_envelope_id"],
        result_envelope_public_id=material["result_envelope_public_id"],
        result_digest=material["result_digest"],
        approved_instruction_digest=material["approved_instruction_digest"],
        coding_attempt_id=material["coding_attempt_id"],
        coding_attempt_identity=material["coding_attempt_identity"],
        coding_outcome=material["coding_outcome"],
        coding_evidence_id=material["coding_evidence_id"],
        coding_evidence_identity=material["coding_evidence_identity"],
        coding_evidence_digest=material["coding_evidence_digest"],
        verification_policy=material["verification_policy"],
        verification_attempt_id=material["verification_attempt_id"],
        verification_attempt_identity=material["verification_attempt_identity"],
        verification_receipt_identity=material[
            "verification_receipt_identity"
        ],
        verification_evidence_id=material["verification_evidence_id"],
        verification_evidence_identity=material["verification_evidence_identity"],
        verification_evidence_digest=material["verification_evidence_digest"],
        verification_verdict=material["verification_verdict"],
        result_integrity_state=material["result_integrity_state"],
        source_workspace_identity=material["source_workspace_identity"],
        run_workspace_identity=material["run_workspace_identity"],
        run_workspace_baseline_identity=material[
            "run_workspace_baseline_identity"
        ],
        run_workspace_post_state_identity=material[
            "run_workspace_post_state_identity"
        ],
        acceptance_id=material["acceptance_id"],
        acceptance_status=material["acceptance_status"],
        file_manifest_json=canonical_json(material["file_manifest"]),
        excluded_manifest_json=canonical_json(material["excluded_manifest"]),
        attribution_summary_json=canonical_json(material["attribution_summary"]),
        readiness_state=material["readiness_state"],
        readiness_reason=material["readiness_reason"],
        readiness_blockers_json=canonical_json(material["readiness_blockers"]),
        patch_identity=material["patch_identity"],
        candidate_digest=material["candidate_digest"],
    )
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
    except IntegrityError as exc:
        winner = session.scalar(
            select(DeliveryCandidate).where(
                DeliveryCandidate.owner_id == owner_id,
                DeliveryCandidate.run_id == run.id,
            )
        )
        if winner is None or winner.result_envelope_id != envelope.id:
            raise ManifestError(
                "A different Candidate is already bound to this Run."
            ) from exc
        _bind_result_acceptance(
            acceptance,
            owner_id=owner_id,
            envelope=envelope,
            candidate=winner,
        )
        session.flush()
        return winner, False, validate_delivery_candidate(
            session,
            owner_id,
            run,
            winner,
        )
    _bind_result_acceptance(
        acceptance,
        owner_id=owner_id,
        envelope=envelope,
        candidate=candidate,
    )
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="delivery_candidate_materialized",
            entity_type="delivery_candidate",
            entity_id=candidate.id,
            details=(
                f"run={run.id}; result={envelope.envelope_id}; "
                f"candidate={candidate.candidate_id}; readiness={candidate.readiness_state}"
            ),
        )
    )
    session.flush()
    return candidate, True, validate_delivery_candidate(
        session,
        owner_id,
        run,
        candidate,
    )


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


def _result_candidate_validation(
    session: Session,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate,
) -> dict[str, Any]:
    integrity_blocker = _result_candidate_blocker(
        "CANDIDATE_INTEGRITY_INVALID",
        "The immutable Result-derived Delivery Candidate failed its integrity check.",
    )

    def invalid() -> dict[str, Any]:
        return {
            "eligible": False,
            "reviewable": False,
            "readiness_state": "blocked",
            "result_review_state": "pending",
            "blockers": [integrity_blocker],
            "next_action": "Review the immutable Run Result evidence.",
        }

    if (
        candidate.owner_id != owner_id
        or candidate.run_id != run.id
        or candidate.task_id != run.task_id
        or candidate.candidate_version < 1
        or candidate.derivation_version != RESULT_CANDIDATE_DERIVATION_VERSION
        or candidate.result_envelope_id is None
    ):
        return invalid()
    stored = _stored_result_candidate_material(candidate)
    if (
        not SHA256_PATTERN.fullmatch(candidate.candidate_digest or "")
        or canonical_sha256(_result_candidate_digest_payload(stored))
        != candidate.candidate_digest
    ):
        return invalid()
    envelope = session.get(CodexResultEnvelope, candidate.result_envelope_id)
    acceptance = session.get(OwnerAcceptanceSession, candidate.acceptance_id)
    if envelope is None or acceptance is None:
        return invalid()
    exact_acceptance_binding = bool(
        acceptance.id == candidate.acceptance_id
        and acceptance.owner_id == owner_id
        and acceptance.task_id == candidate.task_id
        and acceptance.codex_run_id == candidate.run_id
        and acceptance.result_envelope_id == envelope.id
        and acceptance.result_envelope_public_id == envelope.envelope_id
        and acceptance.result_digest == envelope.result_digest
        and acceptance.result_task_version == envelope.task_version
        and acceptance.result_pack_id == envelope.pack_id
        and acceptance.result_pack_version == envelope.pack_version
        and acceptance.approved_instruction_digest
        == envelope.approved_instruction_digest
        and acceptance.delivery_candidate_id == candidate.id
        and acceptance.candidate_public_id == candidate.candidate_id
        and acceptance.candidate_version == candidate.candidate_version
        and acceptance.candidate_digest == candidate.candidate_digest
        and acceptance.review_policy_version == RESULT_REVIEW_POLICY_VERSION
        and acceptance.decision_version >= 1
    )
    if not exact_acceptance_binding:
        return invalid()
    try:
        current = _result_candidate_material(
            session,
            owner_id=owner_id,
            envelope=envelope,
            acceptance=acceptance,
        )
    except ManifestError:
        return invalid()
    if canonical_json(_result_candidate_digest_payload(stored)) != canonical_json(
        _result_candidate_digest_payload(current)
    ):
        return invalid()

    review_state = _result_review_status(acceptance.status)
    readiness_state = str(candidate.readiness_state or "blocked")
    readiness_blockers = [
        item
        for item in _decoded_list(candidate.readiness_blockers_json)
        if isinstance(item, dict)
        and isinstance(item.get("code"), str)
        and isinstance(item.get("message"), str)
    ]
    if readiness_state not in {"ready", "blocked", "no_changes"}:
        return invalid()
    if readiness_state == "blocked" and not readiness_blockers:
        readiness_blockers = [
            _result_candidate_blocker(
                "CANDIDATE_BLOCKED",
                candidate.readiness_reason
                or "The Result-derived Candidate is blocked by its immutable evidence.",
            )
        ]
    if readiness_state == "no_changes":
        readiness_blockers = [
            _result_candidate_blocker(
                "NO_DELIVERABLE_CHANGES",
                candidate.readiness_reason
                or "The immutable Result contains no attributed deliverable changes.",
            )
        ]

    decision_valid = bool(
        acceptance.status in {"accepted", "rejected"}
        and acceptance.decided_by_user_id == owner_id
        and acceptance.decided_at is not None
        and SHA256_PATTERN.fullmatch(acceptance.decision_digest or "")
        and acceptance.decision_digest == result_review_decision_digest(acceptance)
    )
    if review_state in {"accepted_for_delivery", "rejected"} and not decision_valid:
        return {
            "eligible": False,
            "reviewable": True,
            "readiness_state": readiness_state,
            "result_review_state": review_state,
            "blockers": [
                _result_candidate_blocker(
                    "OWNER_DECISION_INTEGRITY_INVALID",
                    "The final Owner review decision failed its immutable binding check.",
                )
            ],
            "next_action": "Review the bound Owner decision evidence.",
        }
    if review_state == "pending" and (
        acceptance.decision_digest
        or acceptance.decided_by_user_id is not None
        or acceptance.decided_at is not None
    ):
        return invalid()

    blockers = list(readiness_blockers)
    eligible = bool(
        readiness_state == "ready"
        and review_state == "accepted_for_delivery"
        and decision_valid
    )
    if readiness_state == "ready" and review_state == "pending":
        blockers.append(
            _result_candidate_blocker(
                "OWNER_REVIEW_PENDING",
                "The Owner has not accepted this exact Result and Candidate for delivery.",
            )
        )
    elif readiness_state == "ready" and review_state == "rejected":
        blockers.append(
            _result_candidate_blocker(
                "RESULT_REJECTED",
                "The Owner rejected this exact Result and Candidate for delivery.",
            )
        )
    if eligible:
        next_action = "Create or review the exact Apply Plan."
    elif readiness_state == "no_changes":
        next_action = "Review the no-change Result; there is nothing to deliver."
    elif readiness_state == "blocked":
        next_action = "Review the exact Candidate blockers and Run evidence."
    elif review_state == "rejected":
        next_action = "Review the rejected Result and run a new approved Pack if needed."
    else:
        next_action = "Accept or reject this exact Result and Candidate."
    return {
        "eligible": eligible,
        "reviewable": True,
        "readiness_state": readiness_state,
        "readiness_reason": candidate.readiness_reason,
        "result_review_state": review_state,
        "decision_digest": acceptance.decision_digest or None,
        "blockers": blockers,
        "next_action": next_action,
    }


def validate_delivery_candidate(
    session: Session,
    owner_id: int,
    run: CodexRun,
    candidate: DeliveryCandidate,
) -> dict[str, Any]:
    if (
        candidate.result_envelope_id is not None
        or candidate.derivation_version == RESULT_CANDIDATE_DERIVATION_VERSION
    ):
        return _result_candidate_validation(
            session,
            owner_id,
            run,
            candidate,
        )
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
    envelope = session.scalar(
        select(CodexResultEnvelope).where(
            CodexResultEnvelope.owner_id == owner_id,
            CodexResultEnvelope.run_id == run.id,
        )
    )
    if envelope is not None:
        return materialize_result_delivery_candidate(
            session,
            owner_id=owner_id,
            envelope=envelope,
        )
    material, eligibility = _candidate_material(session, owner_id, run)
    if material is None:
        return None, False, eligibility
    candidate = DeliveryCandidate(
        candidate_id=material["candidate_id"],
        candidate_version=1,
        derivation_version=LEGACY_CANDIDATE_DERIVATION_VERSION,
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
            approved_source_snapshot = (
                _decoded_object(run.pack.source_snapshot_json)
                if run.pack is not None
                else {}
            )
            approved_identity_method = str(
                approved_source_snapshot.get(
                    "source_repository_identity_method"
                )
                or ""
            )
            snapshot = capture_source_snapshot(
                verified_root,
                hardened_read_only=True,
                verified_source_state=source,
                source_repository_identity_method=(
                    approved_identity_method
                    if approved_identity_method
                    in SOURCE_REPOSITORY_IDENTITY_METHODS
                    else SOURCE_REPOSITORY_IDENTITY_METHOD
                ),
            )
            if not approved_source_snapshot.get("source_repository_identity"):
                snapshot.pop("source_repository_identity_method", None)
                snapshot.pop("source_repository_identity", None)
                snapshot["digest"] = _source_snapshot_digest(snapshot)
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
    if (
        candidate.result_envelope_id is not None
        or candidate.derivation_version == RESULT_CANDIDATE_DERIVATION_VERSION
    ):
        excluded = [
            item
            for item in _decoded_list(candidate.excluded_manifest_json)
            if isinstance(item, dict)
        ]
        review_status = _result_review_status(
            candidate.acceptance.status
            if candidate.acceptance is not None
            else candidate.acceptance_status
        )
        verification_status = (
            "NOT_REQUIRED"
            if candidate.verification_policy == "not_required"
            else str(candidate.verification_verdict or "unavailable").upper()
        )
        primary_files = [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "operation": item.get("operation"),
                "unexpected": item.get("unexpected"),
            }
            for item in manifest
            if isinstance(item, dict)
        ]
        return {
            "id": candidate.candidate_id,
            "status": "available",
            "status_label": "Available",
            "candidate_version": candidate.candidate_version,
            "readiness_state": candidate.readiness_state,
            "readiness_reason": candidate.readiness_reason,
            "readiness_blockers": _decoded_list(
                candidate.readiness_blockers_json
            ),
            "result_review_state": review_status,
            "acceptance_status": review_status,
            "verification_policy": candidate.verification_policy,
            "verification_status": verification_status,
            "result_integrity_state": candidate.result_integrity_state,
            "changed_files": primary_files,
            "changed_file_count": len(primary_files),
            "unexpected_file_count": sum(
                1 for item in primary_files if item.get("unexpected") is True
            ),
            "excluded_files": [
                {
                    "path": item.get("path"),
                    "reason_code": item.get("reason_code"),
                    "reason": item.get("reason"),
                }
                for item in excluded
            ],
            "excluded_file_count": len(excluded),
            "created_at": _iso(candidate.created_at),
            "advanced": {
                "derivation_version": candidate.derivation_version,
                "candidate_digest": candidate.candidate_digest,
                "patch_identity": candidate.patch_identity,
                "result_envelope_id": candidate.result_envelope_public_id,
                "result_digest": candidate.result_digest,
                "approved_instruction_digest": (
                    candidate.approved_instruction_digest
                ),
                "task_id": candidate.task_id,
                "task_version": candidate.task_version,
                "pack_id": candidate.pack_id,
                "pack_version": candidate.pack_version,
                "run_id": candidate.run_id,
                "coding_assignment_id": candidate.coding_assignment_id,
                "coding_assignment_version": candidate.coding_assignment_version,
                "verification_assignment_id": candidate.verification_assignment_id,
                "verification_assignment_version": (
                    candidate.verification_assignment_version
                ),
                "routing_snapshot_identity": candidate.routing_snapshot_identity,
                "source_snapshot_identity": candidate.source_snapshot_identity,
                "coding_outcome": candidate.coding_outcome,
                "coding_attempt_identity": candidate.coding_attempt_identity,
                "coding_evidence_identity": candidate.coding_evidence_identity,
                "verification_attempt_identity": (
                    candidate.verification_attempt_identity
                ),
                "verification_receipt_identity": (
                    candidate.verification_receipt_identity
                ),
                "verification_evidence_identity": (
                    candidate.verification_evidence_identity
                ),
                "source_workspace_identity": candidate.source_workspace_identity,
                "run_workspace_identity": candidate.run_workspace_identity,
                "run_workspace_baseline_identity": (
                    candidate.run_workspace_baseline_identity
                ),
                "run_workspace_post_state_identity": (
                    candidate.run_workspace_post_state_identity
                ),
                "attribution_summary": _decoded_object(
                    candidate.attribution_summary_json
                ),
                "file_evidence": manifest,
            },
        }
    payload = {
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
    return payload


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
