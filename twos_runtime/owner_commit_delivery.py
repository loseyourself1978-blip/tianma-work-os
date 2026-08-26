from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .apply_sessions import (
    _global_evidence_after_mutation,
    _repository_mutation_blocker,
)
from .commit_builder import (
    COMMIT_BUILDER_POLICY_VERSION,
    CommitBuilderError,
    _assert_targets_match,
    _bound_verification,
    _branch_ref,
    _commit_builder_repository_lock,
    _commit_object,
    _current_boundary_locked,
    _decoded_list,
    _decoded_object,
    _failure,
    _git_environment,
    _git_text,
    _index_entries,
    _planned_stage_entries,
    _post_commit_paths,
    _redact_sensitive_text,
    _refs_fingerprint_excluding,
    _run_git,
    _safe_global_evidence,
    _safe_message,
    _sha256_bytes,
    _staged_path_set,
    _verified_root,
    _verify_exact_stage,
    get_or_create_commit_plan,
)
from .delivery_candidates import canonical_json, canonical_sha256, normalize_repository_path
from .models import (
    ApplyPlanApproval,
    CodexResultEnvelope,
    CommitPlan,
    CommitProposal,
    CommitProposalApproval,
    LocalCommitExecution,
    OwnerAcceptanceSession,
    PostApplyVerification,
    StageExecution,
    utc_now,
)


OWNER_COMMIT_POLICY_VERSION = "twos.owner_commit_delivery.vol19.003.v1"
COMMIT_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_OUTPUT_BYTES = 16_384
MAX_IDENTITY_COMPONENT_BYTES = 512
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_IDENT = re.compile(r"^(.*) <([^<>\r\n]+)> [0-9]+ [+-][0-9]{4}$")
_SAFE_HOOK_NAME = re.compile(r"[A-Za-z0-9._-]{1,120}")
_OUTPUT_PRIVACY_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<![A-Za-z0-9:])/(?:Users|private|tmp|var|home)/[^\s\r\n]+"),
)
_NON_BLOCKING_COMMIT_DRIFT_CODES = frozenset(
    {
        "STAGED_PATHS_PRESENT",
        "INDEX_CHANGED",
        "UNRELATED_SOURCE_CHANGED",
        "UNEXPECTED_FILE_CREATED",
        "UNEXPECTED_FILE_MODIFIED",
        "UNEXPECTED_FILE_DELETED",
    }
)


def find_owned_commit_proposal(
    session: Session,
    *,
    owner_id: int,
    proposal_id: str,
) -> CommitProposal | None:
    return session.scalar(
        select(CommitProposal).where(
            CommitProposal.owner_id == owner_id,
            CommitProposal.proposal_id == proposal_id,
        )
    )


def find_owned_commit_proposal_approval(
    session: Session,
    *,
    owner_id: int,
    approval_id: str,
) -> CommitProposalApproval | None:
    return session.scalar(
        select(CommitProposalApproval).where(
            CommitProposalApproval.owner_id == owner_id,
            CommitProposalApproval.approval_id == approval_id,
        )
    )


def _latest_proposal(
    session: Session,
    *,
    owner_id: int,
    verification_id: int,
) -> CommitProposal | None:
    return session.scalar(
        select(CommitProposal)
        .where(
            CommitProposal.owner_id == owner_id,
            CommitProposal.post_apply_verification_id == verification_id,
        )
        .order_by(CommitProposal.version.desc(), CommitProposal.id.desc())
        .limit(1)
    )


def _approval_for_proposal(
    session: Session,
    *,
    owner_id: int,
    proposal_id: int,
) -> CommitProposalApproval | None:
    return session.scalar(
        select(CommitProposalApproval).where(
            CommitProposalApproval.owner_id == owner_id,
            CommitProposalApproval.commit_proposal_id == proposal_id,
        )
    )


def _execution_for_approval(
    session: Session,
    *,
    owner_id: int,
    approval_id: int,
) -> LocalCommitExecution | None:
    return session.scalar(
        select(LocalCommitExecution).where(
            LocalCommitExecution.owner_id == owner_id,
            LocalCommitExecution.commit_proposal_approval_id == approval_id,
        )
    )


def _result_lineage(
    session: Session,
    *,
    owner_id: int,
    verification: PostApplyVerification,
) -> tuple[Any, Any, Any, Any, Any, list[Any], CodexResultEnvelope, OwnerAcceptanceSession, ApplyPlanApproval]:
    apply_session, apply_plan, candidate, run, pack, entries = _bound_verification(
        session,
        owner_id=owner_id,
        verification=verification,
    )
    result = (
        session.get(CodexResultEnvelope, apply_session.result_envelope_id)
        if apply_session.result_envelope_id is not None
        else None
    )
    acceptance = (
        session.get(OwnerAcceptanceSession, apply_session.owner_acceptance_id)
        if apply_session.owner_acceptance_id is not None
        else None
    )
    approval = (
        session.get(ApplyPlanApproval, apply_session.apply_plan_approval_id)
        if apply_session.apply_plan_approval_id is not None
        else None
    )
    if (
        result is None
        or acceptance is None
        or approval is None
        or result.owner_id != owner_id
        or acceptance.owner_id != owner_id
        or approval.owner_id != owner_id
        or result.integrity_state != "VERIFIED"
        or acceptance.status != "accepted"
        or approval.approval_state != "APPROVED"
        or result.id != candidate.result_envelope_id
        or result.id != apply_plan.result_envelope_id
        or result.id != approval.result_envelope_id
        or result.id != acceptance.result_envelope_id
        or result.id != apply_session.result_envelope_id
        or result.envelope_id != apply_session.result_envelope_public_id
        or result.result_digest != apply_session.result_digest
        or result.run_id != run.id
        or result.task_id != apply_session.task_id
        or result.task_version != apply_session.task_version
        or result.pack_id != apply_session.pack_id
        or result.pack_version != apply_session.pack_version
        or candidate.candidate_version != apply_session.candidate_version
        or candidate.candidate_digest != apply_session.candidate_digest
        or candidate.source_workspace_identity
        != apply_session.source_workspace_identity
        or candidate.run_workspace_identity != apply_session.run_workspace_identity
        or acceptance.id != apply_session.owner_acceptance_id
        or acceptance.decision_digest != apply_session.result_review_decision_digest
        or acceptance.delivery_candidate_id != candidate.id
        or approval.id != apply_session.apply_plan_approval_id
        or approval.approval_id != apply_session.apply_plan_approval_public_id
        or approval.approval_digest != apply_session.apply_plan_approval_digest
        or approval.apply_plan_id != apply_plan.id
        or approval.plan_digest != apply_plan.plan_digest
        or approval.delivery_candidate_id != candidate.id
        or approval.result_digest != result.result_digest
        or approval.owner_acceptance_id != acceptance.id
        or approval.result_review_decision_digest != acceptance.decision_digest
        or apply_session.state != "APPLIED"
    ):
        raise _failure(
            "COMMIT_LINEAGE_INVALID",
            "The local Commit is not bound to one complete accepted delivery lineage.",
        )
    return (
        apply_session,
        apply_plan,
        candidate,
        run,
        pack,
        entries,
        result,
        acceptance,
        approval,
    )


def _run_git_without_hook_suppression(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    index_file: Path | None = None,
    timeout: int = COMMIT_COMMAND_TIMEOUT_SECONDS,
) -> tuple[subprocess.CompletedProcess[bytes] | None, bool, bytes, bytes]:
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "commit.gpgSign=false",
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            env=_git_environment(index_file=index_file),
            check=False,
        )
        return result, False, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        return (
            None,
            True,
            bytes(exc.stdout or b""),
            bytes(exc.stderr or b""),
        )
    except OSError as exc:
        raise _failure(
            "GIT_COMMAND_FAILED",
            "The local Git operation could not be launched safely.",
        ) from exc


def _identity_from_git_var(root: Path, variable: str) -> dict[str, str]:
    result, timed_out, stdout, _stderr = _run_git_without_hook_suppression(
        root,
        "var",
        variable,
        timeout=15,
    )
    if timed_out or result is None or result.returncode != 0:
        raise _failure(
            "GIT_IDENTITY_MISSING",
            "Git author identity is not configured for this workspace.",
        )
    try:
        value = stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise _failure(
            "GIT_IDENTITY_INVALID",
            "Git author identity is not valid UTF-8.",
        ) from exc
    match = _IDENT.fullmatch(value)
    if not match or not match.group(1).strip() or not match.group(2).strip():
        raise _failure(
            "GIT_IDENTITY_INVALID",
            "Git author identity is incomplete.",
        )
    name = match.group(1).strip()
    email = match.group(2).strip()
    for component in (name, email):
        if (
            len(component.encode("utf-8")) > MAX_IDENTITY_COMPONENT_BYTES
            or any(ord(character) < 32 or ord(character) == 127 for character in component)
        ):
            raise _failure(
                "GIT_IDENTITY_INVALID",
                "Git author identity contains unsupported characters or is too long.",
            )
    return {
        "sanitized": f"{name[:120]} <configured-email>",
        "identity_digest": canonical_sha256({"name": name, "email": email}),
    }


def _author_readiness(root: Path) -> dict[str, Any]:
    local_values: dict[str, str] = {}
    for key in ("user.name", "user.email"):
        result, timed_out, stdout, _stderr = _run_git_without_hook_suppression(
            root,
            "config",
            "--local",
            "--get",
            key,
            timeout=15,
        )
        if timed_out or result is None or result.returncode != 0:
            raise _failure(
                "GIT_IDENTITY_MISSING",
                "Git author identity needs setup in this repository.",
            )
        try:
            value = stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise _failure(
                "GIT_IDENTITY_INVALID",
                "Git author identity is not valid UTF-8.",
            ) from exc
        if (
            not value
            or len(value.encode("utf-8")) > MAX_IDENTITY_COMPONENT_BYTES
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise _failure(
                "GIT_IDENTITY_INVALID",
                "Git author identity contains unsupported characters or is too long.",
            )
        local_values[key] = value
    author = _identity_from_git_var(root, "GIT_AUTHOR_IDENT")
    committer = _identity_from_git_var(root, "GIT_COMMITTER_IDENT")
    configured_digest = canonical_sha256(
        {"name": local_values["user.name"], "email": local_values["user.email"]}
    )
    if (
        author["identity_digest"] != configured_digest
        or committer["identity_digest"] != configured_digest
    ):
        raise _failure(
            "GIT_IDENTITY_INVALID",
            "Git author identity does not match the repository-local configuration.",
        )
    return {
        "schema": "twos.git_identity_readiness.v1",
        "ready": True,
        "author": author,
        "committer": committer,
        "identity_digest": canonical_sha256(
            {
                "author": author["identity_digest"],
                "committer": committer["identity_digest"],
            }
        ),
        "configuration_scope": "repository_local",
    }


def _sanitize_output(material: bytes, *, root: Path) -> str:
    text = material[:MAX_COMMAND_OUTPUT_BYTES].decode("utf-8", errors="replace")
    root_text = str(root)
    if root_text:
        text = text.replace(root_text, "<repository>")
    text = _redact_sensitive_text(text)
    text = _OUTPUT_PRIVACY_PATTERNS[0].sub("<redacted-email>", text)
    text = _OUTPUT_PRIVACY_PATTERNS[1].sub("<local-path>", text)
    return "".join(character for character in text if character in "\n\t" or ord(character) >= 32)


def _hook_inventory(root: Path) -> dict[str, Any]:
    configured, timed_out, stdout, _stderr = _run_git_without_hook_suppression(
        root,
        "config",
        "--path",
        "--get",
        "core.hooksPath",
        timeout=15,
    )
    hook_path_text = ""
    explicitly_configured = False
    if not timed_out and configured is not None and configured.returncode == 0:
        hook_path_text = stdout.decode("utf-8", errors="replace").strip()
        explicitly_configured = bool(hook_path_text)
    if not hook_path_text:
        fallback, fallback_timeout, fallback_stdout, _ = _run_git_without_hook_suppression(
            root,
            "rev-parse",
            "--git-path",
            "hooks",
            timeout=15,
        )
        if not fallback_timeout and fallback is not None and fallback.returncode == 0:
            hook_path_text = fallback_stdout.decode("utf-8", errors="replace").strip()
    hook_path = Path(hook_path_text)
    if hook_path_text and not hook_path.is_absolute():
        hook_path = root / hook_path
    executable_names: list[str] = []
    try:
        for candidate in hook_path.iterdir():
            name = candidate.name
            mode = candidate.stat().st_mode
            if (
                _SAFE_HOOK_NAME.fullmatch(name)
                and not name.endswith(".sample")
                and stat.S_ISREG(mode)
                and mode & 0o111
            ):
                executable_names.append(name)
    except OSError:
        executable_names = []
    executable_names.sort()
    return {
        "schema": "twos.commit_hooks_readiness.v1",
        "hooks_enabled": True,
        "bypass_flags_used": [],
        "hooks_path_explicitly_configured": explicitly_configured,
        "hooks_path_identity": hashlib.sha256(hook_path_text.encode("utf-8")).hexdigest(),
        "executable_hook_names": executable_names,
    }


def _proposal_binding(
    *,
    owner_id: int,
    verification: PostApplyVerification,
    apply_session: Any,
    apply_plan: Any,
    candidate: Any,
    run: Any,
    pack: Any,
    result: CodexResultEnvelope,
    acceptance: OwnerAcceptanceSession,
    approval: ApplyPlanApproval,
    branch_ref: str,
) -> dict[str, Any]:
    return {
        "schema": "twos.commit_proposal_binding.v1",
        "owner_id": owner_id,
        "verification_id": verification.verification_id,
        "verification_digest": verification.verification_digest,
        "apply_session_id": apply_session.session_id,
        "journal_digest": apply_session.journal_digest,
        "apply_plan_id": apply_plan.plan_id,
        "apply_plan_digest": apply_plan.plan_digest,
        "apply_plan_approval_id": approval.approval_id,
        "apply_plan_approval_digest": approval.approval_digest,
        "candidate_id": candidate.candidate_id,
        "candidate_version": candidate.candidate_version,
        "candidate_digest": candidate.candidate_digest,
        "result_id": result.envelope_id,
        "result_digest": result.result_digest,
        "owner_acceptance_id": acceptance.id,
        "result_review_decision_digest": acceptance.decision_digest,
        "run_id": run.id,
        "task_id": run.task_id,
        "task_version": apply_session.task_version,
        "pack_id": pack.id,
        "pack_version": apply_session.pack_version,
        "source_snapshot_identity": apply_session.source_snapshot_identity,
        "source_workspace_identity": apply_session.source_workspace_identity,
        "run_workspace_identity": apply_session.run_workspace_identity,
        "repository_locator_fingerprint": apply_session.repository_locator_fingerprint,
        "branch": apply_session.branch,
        "branch_ref": branch_ref,
        "base_head": apply_session.pre_apply_head,
    }


def _commit_boundary_decision(
    *,
    root: Path,
    base_head: str,
    planned_paths: list[str],
    blockers: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, str]], list[dict[str, str]], list[str]]:
    staged_paths = _staged_path_set(root, base_head)
    hard: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for raw in blockers:
        code = str(raw.get("code") or "REPOSITORY_CHANGED")
        row = {
            "code": code,
            "message": str(raw.get("message") or "Repository evidence changed."),
        }
        if code in _NON_BLOCKING_COMMIT_DRIFT_CODES:
            warnings.append(row)
        else:
            hard.append(row)
    overlapping = sorted(set(staged_paths).intersection(planned_paths))
    if overlapping:
        hard.append(
            {
                "code": "PLANNED_PATH_ALREADY_STAGED",
                "message": "A planned path is already staged outside this Commit proposal.",
            }
        )
    return not hard, hard, warnings, staged_paths


def _decoded_git_paths(payload: bytes) -> list[str]:
    try:
        values = [
            normalize_repository_path(item.decode("utf-8"))
            for item in payload.split(b"\0")
            if item
        ]
    except (UnicodeDecodeError, ValueError) as exc:
        raise _failure(
            "GIT_EVIDENCE_INVALID",
            "Git returned an invalid changed-path summary.",
        ) from exc
    return sorted(set(values), key=lambda value: value.encode("utf-8"))


def _unrelated_path_summary(
    root: Path,
    *,
    base_head: str,
    planned_paths: list[str],
    inherited_exclusions: list[Any],
) -> list[dict[str, Any]]:
    planned = set(planned_paths)
    categories: dict[str, set[str]] = {}
    for path in _staged_path_set(root, base_head):
        if path not in planned:
            categories.setdefault(path, set()).add("staged")
    unstaged = _decoded_git_paths(
        _run_git(root, "diff", "--name-only", "--no-renames", "-z").stdout
    )
    for path in unstaged:
        if path not in planned:
            categories.setdefault(path, set()).add("modified")
    untracked = _decoded_git_paths(
        _run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    )
    for path in untracked:
        if path not in planned:
            categories.setdefault(path, set()).add("untracked")
    rows: dict[str, dict[str, Any]] = {}
    for raw in inherited_exclusions:
        if not isinstance(raw, dict):
            continue
        path = raw.get("path")
        if not isinstance(path, str) or not path or path in planned:
            continue
        rows[path] = dict(raw)
    for path, states in categories.items():
        rows[path] = {
            "path": path,
            "path_identity": _sha256_bytes(path.encode("utf-8")),
            "reason_code": "UNRELATED_OWNER_CHANGE_EXCLUDED",
            "reason": "Unrelated Owner content is excluded from this Commit proposal and preserved.",
            "states": sorted(states),
        }
    return [rows[path] for path in sorted(rows, key=lambda value: value.encode("utf-8"))]


def create_commit_proposal(
    session: Session,
    *,
    owner_id: int,
    post_apply_verification: PostApplyVerification,
    source_repo: Path,
    subject: object,
    body: object = "",
) -> tuple[CommitProposal, bool]:
    subject_value, body_value = _safe_message(subject, body)
    (
        apply_session,
        apply_plan,
        candidate,
        run,
        pack,
        entries,
        result,
        acceptance,
        apply_approval,
    ) = _result_lineage(
        session,
        owner_id=owner_id,
        verification=post_apply_verification,
    )
    root = _verified_root(run, source_repo)
    with _commit_builder_repository_lock(apply_session.repository_locator_fingerprint):
        status, blockers, tests, current_global = _current_boundary_locked(
            run=run,
            pack=pack,
            apply_session=apply_session,
            entries=entries,
            source_repo=root,
        )
        branch_ref = _branch_ref(root, apply_session.branch)
        author = _author_readiness(root)
        planned = _planned_stage_entries(root, entries)
    latest = _latest_proposal(
        session,
        owner_id=owner_id,
        verification_id=post_apply_verification.id,
    )
    latest_approval = (
        _approval_for_proposal(
            session,
            owner_id=owner_id,
            proposal_id=latest.id,
        )
        if latest is not None
        else None
    )
    if latest is not None and latest_approval is not None:
        latest_execution = _execution_for_approval(
            session,
            owner_id=owner_id,
            approval_id=latest_approval.id,
        )
        if latest_execution is not None:
            if latest.subject == subject_value and latest.body == body_value:
                return latest, False
            raise _failure(
                "COMMIT_PROPOSAL_ALREADY_EXECUTED",
                "A Commit attempt already owns the approved proposal.",
            )
        if latest.subject == subject_value and latest.body == body_value:
            return latest, False
    boundary = _safe_global_evidence(current_global)
    binding = _proposal_binding(
        owner_id=owner_id,
        verification=post_apply_verification,
        apply_session=apply_session,
        apply_plan=apply_plan,
        candidate=candidate,
        run=run,
        pack=pack,
        result=result,
        acceptance=acceptance,
        approval=apply_approval,
        branch_ref=branch_ref,
    )
    binding_digest = canonical_sha256(binding)
    version = (latest.version + 1) if latest is not None else 1
    planned_paths = [
        {
            "path": item["path"],
            "path_identity": item["path_identity"],
            "operation": item["operation"],
        }
        for item in planned
    ]
    excluded_paths = _unrelated_path_summary(
        root,
        base_head=apply_session.pre_apply_head,
        planned_paths=[str(item["path"]) for item in planned],
        inherited_exclusions=_decoded_list(apply_session.excluded_paths_json),
    )
    boundary_allowed, blocker_rows, drift_warnings, unrelated_staged_paths = (
        _commit_boundary_decision(
            root=root,
            base_head=apply_session.pre_apply_head,
            planned_paths=[str(item["path"]) for item in planned],
            blockers=[item for item in blockers if isinstance(item, dict)],
        )
    )
    status_at_creation = "READY" if boundary_allowed else "EXPIRED"
    boundary["non_blocking_drift_warnings"] = drift_warnings
    boundary["unrelated_staged_path_count"] = len(unrelated_staged_paths)
    boundary["unrelated_staged_path_identities"] = sorted(
        _sha256_bytes(path.encode("utf-8")) for path in unrelated_staged_paths
    )
    if (
        latest is not None
        and latest_approval is None
        and latest.subject == subject_value
        and latest.body == body_value
        and latest.author_identity_digest == author["identity_digest"]
        and latest.status_at_creation == status_at_creation
        and canonical_json(_decoded_list(latest.planned_paths_json))
        == canonical_json(planned_paths)
        and canonical_json(_decoded_list(latest.excluded_paths_json))
        == canonical_json(excluded_paths)
        and canonical_json(_decoded_list(latest.blocker_codes_json))
        == canonical_json(blocker_rows)
        and canonical_json(_decoded_object(latest.boundary_evidence_json))
        == canonical_json(boundary)
    ):
        return latest, False
    proposal_material = {
        "schema": "twos.commit_proposal.v1",
        "policy_version": OWNER_COMMIT_POLICY_VERSION,
        "version": version,
        "supersedes_digest": latest.proposal_digest if latest is not None else "",
        "binding_digest": binding_digest,
        "planned_paths": planned_paths,
        "excluded_paths": excluded_paths,
        "subject": subject_value,
        "body": body_value,
        "author_identity_digest": author["identity_digest"],
        "validation": tests,
        "blockers": blocker_rows,
        "boundary": boundary,
        "status_at_creation": status_at_creation,
    }
    proposal_digest = canonical_sha256(proposal_material)
    if latest is not None and latest.proposal_digest == proposal_digest:
        return latest, False
    row = CommitProposal(
        proposal_id="cproposal_" + proposal_digest[:40],
        owner_id=owner_id,
        post_apply_verification_id=post_apply_verification.id,
        apply_session_id=apply_session.id,
        apply_plan_id=apply_plan.id,
        delivery_candidate_id=candidate.id,
        run_id=run.id,
        task_id=run.task_id,
        pack_id=pack.id,
        result_envelope_id=result.id,
        owner_acceptance_id=acceptance.id,
        apply_plan_approval_id=apply_approval.id,
        version=version,
        supersedes_proposal_id=latest.id if latest is not None else None,
        verification_public_id=post_apply_verification.verification_id,
        verification_digest=post_apply_verification.verification_digest,
        apply_session_public_id=apply_session.session_id,
        journal_digest=apply_session.journal_digest,
        apply_plan_public_id=apply_plan.plan_id,
        apply_plan_digest=apply_plan.plan_digest,
        apply_plan_approval_public_id=apply_approval.approval_id,
        apply_plan_approval_digest=apply_approval.approval_digest,
        candidate_public_id=candidate.candidate_id,
        candidate_version=candidate.candidate_version,
        candidate_digest=candidate.candidate_digest,
        result_envelope_public_id=result.envelope_id,
        result_digest=result.result_digest,
        result_review_decision_digest=acceptance.decision_digest,
        task_version=apply_session.task_version,
        pack_version=apply_session.pack_version,
        repository_locator_fingerprint=apply_session.repository_locator_fingerprint,
        repository_fingerprint=str(boundary.get("repository_fingerprint") or ""),
        sanitized_repository_identity=apply_session.sanitized_repository_identity,
        branch=apply_session.branch,
        branch_ref=branch_ref,
        base_head=apply_session.pre_apply_head,
        source_snapshot_identity=apply_session.source_snapshot_identity,
        source_workspace_identity=apply_session.source_workspace_identity,
        run_workspace_identity=apply_session.run_workspace_identity,
        planned_paths_json=canonical_json(planned_paths),
        planned_paths_digest=canonical_sha256(planned_paths),
        excluded_paths_json=canonical_json(excluded_paths),
        subject=subject_value,
        body=body_value,
        subject_digest=_sha256_bytes(subject_value.encode("utf-8")),
        body_digest=_sha256_bytes(body_value.encode("utf-8")),
        message_digest=_sha256_bytes(_message_bytes(subject_value, body_value)),
        author_identity_sanitized=str(author["author"]["sanitized"]),
        author_identity_digest=str(author["identity_digest"]),
        validation_json=canonical_json(tests),
        blocker_codes_json=canonical_json(blocker_rows),
        boundary_evidence_json=canonical_json(boundary),
        policy_version=OWNER_COMMIT_POLICY_VERSION,
        status_at_creation=status_at_creation,
        binding_digest=binding_digest,
        proposal_digest=proposal_digest,
    )
    session.add(row)
    session.flush()
    return row, True


def approve_commit_proposal(
    session: Session,
    *,
    owner_id: int,
    proposal: CommitProposal,
    expected_proposal_digest: str,
    confirmation: object,
) -> tuple[CommitProposalApproval, bool]:
    if proposal.owner_id != owner_id:
        raise _failure("COMMIT_PROPOSAL_NOT_FOUND", "Commit proposal not found.")
    if confirmation is not True and confirmation != "APPROVE_COMMIT_PROPOSAL":
        raise _failure(
            "OWNER_APPROVAL_REQUIRED",
            "Explicit Owner approval of the exact Commit proposal is required.",
        )
    if expected_proposal_digest != proposal.proposal_digest:
        raise _failure("COMMIT_PROPOSAL_CHANGED", "The Commit proposal identity changed.")
    latest = _latest_proposal(
        session,
        owner_id=owner_id,
        verification_id=proposal.post_apply_verification_id,
    )
    if latest is None or latest.id != proposal.id:
        raise _failure("COMMIT_PROPOSAL_SUPERSEDED", "A newer Commit proposal requires review.")
    if proposal.status_at_creation != "READY":
        raise _failure("COMMIT_PROPOSAL_BLOCKED", "The Commit proposal is not ready for approval.")
    existing = _approval_for_proposal(
        session,
        owner_id=owner_id,
        proposal_id=proposal.id,
    )
    confirmation_digest = canonical_sha256(
        {
            "schema": "twos.commit_proposal_owner_approval.v1",
            "owner_id": owner_id,
            "proposal_id": proposal.proposal_id,
            "proposal_version": proposal.version,
            "proposal_digest": proposal.proposal_digest,
            "message_digest": proposal.message_digest,
            "confirmed": True,
        }
    )
    approval_digest = canonical_sha256(
        {
            "schema": "twos.commit_proposal_approval.v1",
            "confirmation_digest": confirmation_digest,
            "proposal_digest": proposal.proposal_digest,
            "approved_by_user_id": owner_id,
        }
    )
    if existing is not None:
        if (
            existing.proposal_digest != proposal.proposal_digest
            or existing.confirmation_digest != confirmation_digest
            or existing.approval_digest != approval_digest
        ):
            raise _failure("COMMIT_APPROVAL_INTEGRITY_BLOCKED", "Commit approval evidence is invalid.")
        return existing, False
    row = CommitProposalApproval(
        approval_id="capproval_" + approval_digest[:40],
        owner_id=owner_id,
        commit_proposal_id=proposal.id,
        proposal_public_id=proposal.proposal_id,
        proposal_version=proposal.version,
        proposal_digest=proposal.proposal_digest,
        message_digest=proposal.message_digest,
        approved_by_user_id=owner_id,
        approved_at=utc_now(),
        confirmation_digest=confirmation_digest,
        approval_digest=approval_digest,
        state="APPROVED",
    )
    session.add(row)
    session.flush()
    return row, True


def _message_bytes(subject: str, body: str) -> bytes:
    text = subject + (("\n\n" + body) if body else "")
    return (text + "\n").encode("utf-8")


def _index_info_bytes(root: Path, planned: list[dict[str, Any]]) -> bytes:
    object_format = _git_text(root, "rev-parse", "--show-object-format")
    zero_oid = "0" * (64 if object_format == "sha256" else 40)
    payload = bytearray()
    for item in planned:
        if item.get("present") is True:
            prefix = f"{item['mode']} {item['blob_oid']}\t".encode("ascii")
        else:
            prefix = f"0 {zero_oid}\t".encode("ascii")
        payload.extend(prefix)
        payload.extend(str(item["path"]).encode("utf-8"))
        payload.append(0)
    return bytes(payload)


def _temporary_index(root: Path, *, base_head: str, planned: list[dict[str, Any]]) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="twos-owner-commit-index-", suffix=".idx")
    os.close(descriptor)
    path = Path(name)
    path.unlink(missing_ok=True)
    if path.resolve().is_relative_to(root):
        raise _failure("INDEX_SNAPSHOT_UNAVAILABLE", "The alternate index is inside the repository.")
    try:
        _run_git(root, "read-tree", base_head, index_file=path)
        _run_git(
            root,
            "update-index",
            "-z",
            "--index-info",
            input_bytes=_index_info_bytes(root, planned),
            index_file=path,
        )
        _verify_exact_stage(root, head=base_head, planned=planned, index_file=path)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _actual_commit_identity(root: Path, commit_oid: str) -> dict[str, str]:
    result, timed_out, stdout, _stderr = _run_git_without_hook_suppression(
        root,
        "show",
        "-s",
        "--format=%an%x00%ae%x00%cn%x00%ce",
        commit_oid,
        timeout=15,
    )
    if timed_out or result is None or result.returncode != 0:
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "Commit author evidence is unavailable.")
    try:
        values = stdout.decode("utf-8").rstrip("\n").split("\x00")
    except UnicodeDecodeError as exc:
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "Commit author evidence is invalid.") from exc
    if len(values) != 4:
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "Commit author evidence is malformed.")
    author_name, author_email, committer_name, committer_email = values
    return {
        "author_digest": canonical_sha256({"name": author_name, "email": author_email}),
        "committer_digest": canonical_sha256({"name": committer_name, "email": committer_email}),
    }


def _record_failed_command(
    session: Session,
    *,
    execution: LocalCommitExecution,
    root: Path,
    base_head: str,
    result: subprocess.CompletedProcess[bytes] | None,
    timed_out: bool,
    stdout: bytes,
    stderr: bytes,
    hooks: dict[str, Any],
) -> None:
    try:
        head = _git_text(root, "rev-parse", "HEAD")
    except CommitBuilderError:
        head = ""
    exit_code = result.returncode if result is not None else None
    output = {
        "stdout": _sanitize_output(stdout, root=root),
        "stderr": _sanitize_output(stderr, root=root),
        "truncated": len(stdout) > MAX_COMMAND_OUTPUT_BYTES or len(stderr) > MAX_COMMAND_OUTPUT_BYTES,
    }
    command_evidence = {
        "schema": "twos.owner_local_commit_command.v1",
        "argv": ["git", "commit", "--no-status", "--file=-"],
        "shell": False,
        "alternate_index": True,
        "hooks_bypassed": False,
        "timed_out": timed_out,
        "exit_code": exit_code,
    }
    hooks = dict(hooks)
    hooks["command_outcome"] = "TIMED_OUT" if timed_out else "FAILED"
    execution.command_finished_at = utc_now()
    execution.command_exit_code = exit_code
    execution.command_output_json = canonical_json(output)
    execution.command_evidence_json = canonical_json(command_evidence)
    execution.command_evidence_digest = canonical_sha256(command_evidence)
    execution.hooks_evidence_json = canonical_json(hooks)
    execution.hooks_evidence_digest = canonical_sha256(hooks)
    execution.failure_evidence_json = canonical_json(
        [{"code": "COMMIT_COMMAND_TIMED_OUT" if timed_out else "COMMIT_COMMAND_FAILED"}]
    )
    execution.state = "FAILED" if head == base_head else "INTEGRITY_BLOCKED"
    execution.finished_at = utc_now()
    session.commit()


def _reconcile_interrupted_commit(
    session: Session,
    *,
    execution: LocalCommitExecution,
    proposal: CommitProposal,
    approval: CommitProposalApproval,
    root: Path,
    run: Any,
    apply_session: Any,
    entries: list[Any],
) -> LocalCommitExecution | None:
    """Settle an exact already-created Commit without repeating hooks or mutation."""
    head = _git_text(root, "rev-parse", "HEAD")
    if head == proposal.base_head:
        if execution.command_started_at is not None:
            execution.state = "INTEGRITY_BLOCKED"
            execution.failure_evidence_json = canonical_json(
                [{"code": "COMMIT_COMMAND_OUTCOME_UNKNOWN"}]
            )
            execution.finished_at = utc_now()
            session.commit()
            return execution
        return None
    planned = _decoded_list(execution.staged_entries_json)
    planned_paths = sorted(str(item.get("path")) for item in planned)
    alternate_index: Path | None = None
    try:
        alternate_index = _temporary_index(
            root,
            base_head=proposal.base_head,
            planned=planned,
        )
        expected_tree = _run_git(
            root,
            "write-tree",
            index_file=alternate_index,
        ).stdout.decode("ascii").strip()
    finally:
        if alternate_index is not None:
            alternate_index.unlink(missing_ok=True)
    commit = _commit_object(root, head)
    identity = _actual_commit_identity(root, head)
    combined_identity = canonical_sha256(
        {
            "author": identity["author_digest"],
            "committer": identity["committer_digest"],
        }
    )
    if (
        not _OID.fullmatch(head)
        or commit["tree"] != expected_tree
        or commit["parents"] != [proposal.base_head]
        or commit["message"] != _message_bytes(proposal.subject, proposal.body)
        or commit["message_digest"] != proposal.message_digest
        or _post_commit_paths(root, proposal.base_head, head) != planned_paths
        or combined_identity != proposal.author_identity_digest
    ):
        execution.state = "INTEGRITY_BLOCKED"
        execution.failure_evidence_json = canonical_json(
            [{"code": "INTERRUPTED_COMMIT_MISMATCH"}]
        )
        execution.finished_at = utc_now()
        session.commit()
        return execution
    pre = _decoded_object(execution.pre_commit_evidence_json)
    real_index_before = _decoded_object(pre.get("real_index_entries"))
    staged_before = [str(value) for value in _decoded_list(pre.get("unrelated_staged_paths"))]
    if not real_index_before:
        execution.state = "INTEGRITY_BLOCKED"
        execution.failure_evidence_json = canonical_json(
            [{"code": "INDEX_RECOVERY_EVIDENCE_MISSING"}]
        )
        execution.finished_at = utc_now()
        session.commit()
        return execution
    current_index = _index_entries(root)
    planned_path_set = set(planned_paths)
    unrelated_before = {
        path: value for path, value in real_index_before.items() if path not in planned_path_set
    }
    unrelated_current = {
        path: value for path, value in current_index.items() if path not in planned_path_set
    }
    if unrelated_before != unrelated_current:
        execution.state = "INTEGRITY_BLOCKED"
        execution.failure_evidence_json = canonical_json(
            [{"code": "UNRELATED_INDEX_CHANGED_DURING_RECOVERY"}]
        )
        execution.finished_at = utc_now()
        session.commit()
        return execution
    _run_git(
        root,
        "update-index",
        "-z",
        "--index-info",
        input_bytes=_index_info_bytes(root, planned),
    )
    if _staged_path_set(root, head) != staged_before:
        execution.state = "INTEGRITY_BLOCKED"
        execution.failure_evidence_json = canonical_json(
            [{"code": "UNRELATED_STAGE_RECOVERY_MISMATCH"}]
        )
        execution.finished_at = utc_now()
        session.commit()
        return execution
    _assert_targets_match(root, entries)
    baseline = _decoded_object(apply_session.after_evidence_json).get("global")
    post_global = _global_evidence_after_mutation(
        run,
        root,
        target_paths=[entry.repository_path for entry in entries],
        baseline=_decoded_object(baseline),
    )
    post = _safe_global_evidence(post_global)
    post["refs_excluding_current_fingerprint"] = _refs_fingerprint_excluding(
        root, proposal.branch_ref
    )
    post["unrelated_staged_paths_preserved"] = True
    hooks = _decoded_object(execution.hooks_evidence_json)
    if not hooks:
        hooks = {
            "schema": "twos.commit_hooks_readiness.v1",
            "hooks_enabled": True,
            "bypass_flags_used": [],
            "command_outcome": "RECOVERED_EXACT_COMMIT",
            "completion_observation": "unavailable_after_interruption",
        }
        execution.hooks_evidence_json = canonical_json(hooks)
        execution.hooks_evidence_digest = canonical_sha256(hooks)
    receipt = {
        "schema": "twos.owner_local_commit_receipt.v1",
        "commit_execution_id": execution.commit_execution_id,
        "proposal_digest": proposal.proposal_digest,
        "approval_digest": approval.approval_digest,
        "confirmation_digest": execution.owner_commit_confirmation_digest,
        "commit_plan_digest": execution.commit_plan_digest,
        "stage_digest": execution.stage_digest,
        "parent_oid": proposal.base_head,
        "commit_oid": head,
        "tree_oid": expected_tree,
        "message_digest": proposal.message_digest,
        "changed_path_identities": sorted(
            _sha256_bytes(path.encode("utf-8")) for path in planned_paths
        ),
        "author_identity_digest": proposal.author_identity_digest,
        "hooks_evidence_digest": execution.hooks_evidence_digest,
        "post_commit": post,
        "recovered": True,
    }
    execution.tree_oid = execution.tree_oid or expected_tree
    execution.commit_oid = execution.commit_oid or head
    execution.parent_oid = execution.parent_oid or proposal.base_head
    execution.post_commit_evidence_json = canonical_json(post)
    execution.receipt_digest = canonical_sha256(receipt)
    execution.state = "COMMITTED"
    execution.finished_at = utc_now()
    session.commit()
    return execution


def confirm_local_commit(
    session: Session,
    *,
    owner_id: int,
    proposal: CommitProposal,
    approval: CommitProposalApproval,
    source_repo: Path,
    expected_proposal_digest: str,
    expected_approval_digest: str,
    confirmation: object,
) -> tuple[LocalCommitExecution, bool]:
    if confirmation is not True and confirmation != "CREATE_LOCAL_COMMIT":
        raise _failure(
            "OWNER_COMMIT_CONFIRMATION_REQUIRED",
            "A separate explicit Owner confirmation is required to create the local Commit.",
        )
    if (
        proposal.owner_id != owner_id
        or approval.owner_id != owner_id
        or approval.commit_proposal_id != proposal.id
    ):
        raise _failure("COMMIT_PROPOSAL_NOT_FOUND", "Commit proposal not found.")
    if expected_proposal_digest != proposal.proposal_digest:
        raise _failure("COMMIT_PROPOSAL_CHANGED", "The Commit proposal identity changed.")
    if expected_approval_digest != approval.approval_digest:
        raise _failure("COMMIT_APPROVAL_CHANGED", "The Commit approval identity changed.")
    if (
        approval.state != "APPROVED"
        or approval.proposal_public_id != proposal.proposal_id
        or approval.proposal_version != proposal.version
        or approval.proposal_digest != proposal.proposal_digest
        or approval.message_digest != proposal.message_digest
    ):
        raise _failure("COMMIT_APPROVAL_INTEGRITY_BLOCKED", "Commit approval evidence is invalid.")
    confirmation_digest = canonical_sha256(
        {
            "schema": "twos.owner_local_commit_confirmation.v1",
            "owner_id": owner_id,
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
            "approval_id": approval.approval_id,
            "approval_digest": approval.approval_digest,
            "confirmed": True,
        }
    )
    existing = _execution_for_approval(session, owner_id=owner_id, approval_id=approval.id)
    recovering_execution_id: int | None = None
    if existing is not None:
        if existing.owner_commit_confirmation_digest != confirmation_digest:
            raise _failure("COMMIT_CONFIRMATION_CHANGED", "Commit confirmation evidence changed.")
        if existing.state != "COMMITTING":
            return existing, False
        recovering_execution_id = existing.id
    latest = _latest_proposal(
        session,
        owner_id=owner_id,
        verification_id=proposal.post_apply_verification_id,
    )
    if latest is None or latest.id != proposal.id:
        raise _failure("COMMIT_PROPOSAL_SUPERSEDED", "A newer Commit proposal requires review.")
    verification = session.get(PostApplyVerification, proposal.post_apply_verification_id)
    if verification is None:
        raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
    (
        apply_session,
        _apply_plan,
        candidate,
        run,
        pack,
        entries,
        result_envelope,
        owner_acceptance,
        apply_plan_approval,
    ) = _result_lineage(session, owner_id=owner_id, verification=verification)
    root = _verified_root(run, source_repo)
    if recovering_execution_id is not None:
        recovering = session.get(LocalCommitExecution, recovering_execution_id)
        plan = (
            session.get(CommitPlan, recovering.commit_plan_id)
            if recovering is not None
            else None
        )
        if plan is None or plan.owner_id != owner_id:
            raise _failure(
                "COMMIT_INTEGRITY_BLOCKED",
                "The interrupted Commit Plan is unavailable.",
            )
    else:
        plan, _plan_created = get_or_create_commit_plan(
            session,
            owner_id=owner_id,
            post_apply_verification=verification,
            source_repo=root,
            subject=proposal.subject,
            body=proposal.body,
        )
        session.commit()
    with _commit_builder_repository_lock(proposal.repository_locator_fingerprint):
        session.expire_all()
        proposal = session.get(CommitProposal, proposal.id)
        approval = session.get(CommitProposalApproval, approval.id)
        plan = session.get(CommitPlan, plan.id)
        if proposal is None or approval is None or plan is None:
            raise _failure("COMMIT_CONFIRMATION_CHANGED", "Commit confirmation bindings are unavailable.")
        latest = _latest_proposal(
            session,
            owner_id=owner_id,
            verification_id=proposal.post_apply_verification_id,
        )
        if latest is None or latest.id != proposal.id:
            raise _failure("COMMIT_PROPOSAL_SUPERSEDED", "A newer Commit proposal requires review.")
        verification = session.get(PostApplyVerification, proposal.post_apply_verification_id)
        if verification is None:
            raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
        (
            apply_session,
            _apply_plan,
            candidate,
            run,
            pack,
            entries,
            result_envelope,
            owner_acceptance,
            apply_plan_approval,
        ) = _result_lineage(session, owner_id=owner_id, verification=verification)
        if recovering_execution_id is not None:
            recovering = session.get(LocalCommitExecution, recovering_execution_id)
            if recovering is None:
                raise _failure(
                    "COMMIT_CONFIRMATION_CHANGED",
                    "The durable Commit intent is unavailable.",
                )
            reconciled = _reconcile_interrupted_commit(
                session,
                execution=recovering,
                proposal=proposal,
                approval=approval,
                root=root,
                run=run,
                apply_session=apply_session,
                entries=entries,
            )
            if reconciled is not None:
                return reconciled, False
        if (
            proposal.status_at_creation != "READY"
            or proposal.policy_version != OWNER_COMMIT_POLICY_VERSION
            or plan.plan_digest == ""
            or plan.subject != proposal.subject
            or plan.body != proposal.body
            or proposal.base_head != apply_session.pre_apply_head
            or proposal.branch_ref != _branch_ref(root, proposal.branch)
            or _git_text(root, "rev-parse", "HEAD") != proposal.base_head
        ):
            raise _failure("COMMIT_PROPOSAL_EXPIRED", "The Commit proposal is no longer current.")
        if _repository_mutation_blocker(
            session,
            repository_locator_fingerprint=proposal.repository_locator_fingerprint,
            exclude_plan_id=apply_session.apply_plan_id,
        ) is not None:
            raise _failure("REPOSITORY_MUTATION_ACTIVE", "Another repository mutation is active.")
        status, blockers, _tests, current_global = _current_boundary_locked(
            run=run,
            pack=pack,
            apply_session=apply_session,
            entries=entries,
            source_repo=root,
        )
        author = _author_readiness(root)
        if author["identity_digest"] != proposal.author_identity_digest:
            raise _failure("GIT_IDENTITY_CHANGED", "Git author identity changed after proposal approval.")
        planned = _planned_stage_entries(root, entries)
        planned_paths = sorted(str(item["path"]) for item in planned)
        boundary_allowed, boundary_blockers, _drift_warnings, _staged_paths = (
            _commit_boundary_decision(
                root=root,
                base_head=proposal.base_head,
                planned_paths=planned_paths,
                blockers=[item for item in blockers if isinstance(item, dict)],
            )
        )
        if not boundary_allowed:
            code = (
                boundary_blockers[0]["code"]
                if boundary_blockers
                else "COMMIT_PROPOSAL_EXPIRED"
            )
            raise _failure(
                code,
                "Repository evidence affecting the approved Commit changed after approval.",
            )
        if canonical_sha256(
            [
                {
                    "path": item["path"],
                    "path_identity": item["path_identity"],
                    "operation": item["operation"],
                }
                for item in planned
            ]
        ) != proposal.planned_paths_digest:
            raise _failure("COMMIT_PROPOSAL_EXPIRED", "The approved path set changed.")
        existing_stage = session.scalar(
            select(StageExecution).where(StageExecution.commit_plan_id == plan.id)
        )
        message = _message_bytes(proposal.subject, proposal.body)
        if recovering_execution_id is not None:
            execution = session.get(LocalCommitExecution, recovering_execution_id)
            stage = existing_stage
            if (
                execution is None
                or stage is None
                or execution.stage_execution_id != stage.id
                or execution.state != "COMMITTING"
                or execution.command_started_at is not None
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The interrupted Commit intent cannot be resumed safely.",
                )
            pre_commit = _decoded_object(execution.pre_commit_evidence_json)
            real_index_before = _decoded_object(pre_commit.get("real_index_entries"))
            staged_before = [
                str(value) for value in _decoded_list(pre_commit.get("unrelated_staged_paths"))
            ]
            if (
                not real_index_before
                or canonical_json(planned) != canonical_json(
                    _decoded_list(execution.staged_entries_json)
                )
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The interrupted Commit recovery evidence is incomplete.",
                )
        else:
            if existing_stage is not None:
                raise _failure(
                    "COMMIT_STAGE_ALREADY_EXISTS",
                    "An earlier Stage workflow already owns this Commit evidence.",
                )
            real_index_before = _index_entries(root)
            staged_before = _staged_path_set(root, proposal.base_head)
            if set(planned_paths).intersection(staged_before):
                raise _failure(
                    "PLANNED_PATH_ALREADY_STAGED",
                    "A planned path is already staged outside this Commit proposal.",
                )
            boundary = _safe_global_evidence(current_global)
            pre_commit = dict(boundary)
            pre_commit["refs_excluding_current_fingerprint"] = _refs_fingerprint_excluding(
                root, proposal.branch_ref
            )
            pre_commit["real_index_semantic_digest"] = canonical_sha256(real_index_before)
            pre_commit["real_index_entries"] = real_index_before
            pre_commit["unrelated_staged_paths"] = staged_before
            pre_commit["unrelated_staged_path_identities"] = sorted(
                _sha256_bytes(path.encode("utf-8")) for path in staged_before
            )
            planned_digest = canonical_sha256(planned)
            stage_digest = canonical_sha256(
                {
                    "schema": "twos.alternate_index_stage_receipt.v1",
                    "plan_digest": plan.plan_digest,
                    "proposal_digest": proposal.proposal_digest,
                    "planned_entries_digest": planned_digest,
                    "real_index_semantic_digest": canonical_sha256(real_index_before),
                    "unrelated_staged_path_identities": pre_commit[
                        "unrelated_staged_path_identities"
                    ],
                }
            )
            stage = StageExecution(
                stage_execution_id="stage_" + stage_digest[:40],
                owner_id=owner_id,
                commit_plan_id=plan.id,
                commit_plan_public_id=plan.commit_plan_id,
                commit_plan_digest=plan.plan_digest,
                verification_digest=proposal.verification_digest,
                repository_locator_fingerprint=proposal.repository_locator_fingerprint,
                branch=proposal.branch,
                branch_ref=proposal.branch_ref,
                base_head=proposal.base_head,
                planned_entries_json=canonical_json(planned),
                planned_entries_digest=planned_digest,
                pre_stage_evidence_json=canonical_json(boundary),
                pre_stage_evidence_digest=canonical_sha256(boundary),
                post_stage_evidence_json=canonical_json(
                    {
                        **boundary,
                        "stage_storage": "isolated_alternate_index",
                        "real_index_preserved_before_commit": True,
                    }
                ),
                staged_entries_json=canonical_json(planned),
                staged_entries_digest=planned_digest,
                stage_digest=stage_digest,
                state="STAGED",
                finished_at=utc_now(),
            )
            session.add(stage)
            session.flush()
            pre_digest = canonical_sha256(pre_commit)
            intent_digest = canonical_sha256(
                {
                    "schema": "twos.owner_local_commit_intent.v1",
                    "proposal_digest": proposal.proposal_digest,
                    "approval_digest": approval.approval_digest,
                    "confirmation_digest": confirmation_digest,
                    "commit_plan_digest": plan.plan_digest,
                    "stage_digest": stage_digest,
                    "base_head": proposal.base_head,
                    "message_digest": proposal.message_digest,
                    "pre_commit_evidence_digest": pre_digest,
                }
            )
            execution = LocalCommitExecution(
                commit_execution_id="commit_" + intent_digest[:40],
                owner_id=owner_id,
                commit_proposal_id=proposal.id,
                commit_proposal_approval_id=approval.id,
                commit_plan_id=plan.id,
                stage_execution_id=stage.id,
                commit_plan_public_id=plan.commit_plan_id,
                commit_plan_digest=plan.plan_digest,
                stage_execution_public_id=stage.stage_execution_id,
                stage_digest=stage_digest,
                repository_locator_fingerprint=proposal.repository_locator_fingerprint,
                branch=proposal.branch,
                branch_ref=proposal.branch_ref,
                base_head=proposal.base_head,
                staged_entries_json=canonical_json(planned),
                staged_entries_digest=planned_digest,
                subject_digest=proposal.subject_digest,
                body_digest=proposal.body_digest,
                message_digest=proposal.message_digest,
                intent_digest=intent_digest,
                pre_commit_evidence_json=canonical_json(pre_commit),
                pre_commit_evidence_digest=pre_digest,
                proposal_public_id=proposal.proposal_id,
                proposal_digest=proposal.proposal_digest,
                proposal_approval_public_id=approval.approval_id,
                proposal_approval_digest=approval.approval_digest,
                owner_commit_confirmation_digest=confirmation_digest,
                owner_commit_confirmed_at=utc_now(),
                result_envelope_id=result_envelope.id,
                result_envelope_public_id=result_envelope.envelope_id,
                result_digest=result_envelope.result_digest,
                owner_acceptance_id=owner_acceptance.id,
                result_review_decision_digest=owner_acceptance.decision_digest,
                candidate_version=candidate.candidate_version,
                apply_plan_approval_id=apply_plan_approval.id,
                apply_plan_approval_public_id=apply_plan_approval.approval_id,
                apply_plan_approval_digest=apply_plan_approval.approval_digest,
                source_workspace_identity=apply_session.source_workspace_identity,
                run_workspace_identity=apply_session.run_workspace_identity,
                author_identity_sanitized=proposal.author_identity_sanitized,
                author_identity_digest=proposal.author_identity_digest,
                state="COMMITTING",
            )
            session.add(execution)
            session.flush()
            session.commit()
            execution = session.get(LocalCommitExecution, execution.id) or execution

        alternate_index: Path | None = None
        try:
            # Recheck the durable exact intent at the last safe point before Git mutation.
            if (
                _git_text(root, "rev-parse", "HEAD") != proposal.base_head
                or _branch_ref(root, proposal.branch) != proposal.branch_ref
                or _index_entries(root) != real_index_before
            ):
                raise _failure("COMMIT_PROPOSAL_EXPIRED", "Repository evidence changed before Commit.")
            _assert_targets_match(root, entries)
            for item, entry in zip(planned, entries, strict=True):
                if item.get("present") is not True:
                    continue
                written = _run_git(
                    root,
                    "hash-object",
                    "-w",
                    "--no-filters",
                    "--stdin",
                    input_bytes=entry.after_material,
                ).stdout.decode("ascii").strip()
                if written != item.get("blob_oid"):
                    raise _failure("COMMIT_INTEGRITY_BLOCKED", "Git wrote an unexpected blob.")
            alternate_index = _temporary_index(
                root,
                base_head=proposal.base_head,
                planned=planned,
            )
            expected_tree = _run_git(root, "write-tree", index_file=alternate_index).stdout.decode(
                "ascii"
            ).strip()
            if not _OID.fullmatch(expected_tree):
                raise _failure("COMMIT_INTEGRITY_BLOCKED", "Git returned an invalid tree identity.")
            hooks = _hook_inventory(root)
            execution.command_started_at = utc_now()
            session.commit()
            result, timed_out, stdout, stderr = _run_git_without_hook_suppression(
                root,
                "commit",
                "--no-status",
                "--file=-",
                input_bytes=message,
                index_file=alternate_index,
            )
            if timed_out or result is None or result.returncode != 0:
                _record_failed_command(
                    session,
                    execution=execution,
                    root=root,
                    base_head=proposal.base_head,
                    result=result,
                    timed_out=timed_out,
                    stdout=stdout,
                    stderr=stderr,
                    hooks=hooks,
                )
                raise _failure(
                    "COMMIT_COMMAND_TIMED_OUT" if timed_out else "COMMIT_COMMAND_FAILED",
                    "The hook-enabled local Commit did not complete successfully.",
                )
            output = {
                "stdout": _sanitize_output(stdout, root=root),
                "stderr": _sanitize_output(stderr, root=root),
                "truncated": len(stdout) > MAX_COMMAND_OUTPUT_BYTES
                or len(stderr) > MAX_COMMAND_OUTPUT_BYTES,
            }
            command_evidence = {
                "schema": "twos.owner_local_commit_command.v1",
                "argv": ["git", "commit", "--no-status", "--file=-"],
                "shell": False,
                "alternate_index": True,
                "hooks_bypassed": False,
                "timed_out": False,
                "exit_code": result.returncode,
            }
            hooks["command_outcome"] = "SUCCEEDED"
            hooks["configured_hooks_were_not_bypassed"] = True
            execution.command_finished_at = utc_now()
            execution.command_exit_code = result.returncode
            execution.command_output_json = canonical_json(output)
            execution.command_evidence_json = canonical_json(command_evidence)
            execution.command_evidence_digest = canonical_sha256(command_evidence)
            execution.hooks_evidence_json = canonical_json(hooks)
            execution.hooks_evidence_digest = canonical_sha256(hooks)
            session.commit()
            commit_oid = _git_text(root, "rev-parse", "HEAD")
            commit = _commit_object(root, commit_oid)
            actual_identity = _actual_commit_identity(root, commit_oid)
            expected_author = author["author"]["identity_digest"]
            expected_committer = author["committer"]["identity_digest"]
            if (
                not _OID.fullmatch(commit_oid)
                or commit_oid == proposal.base_head
                or commit["tree"] != expected_tree
                or commit["parents"] != [proposal.base_head]
                or commit["message"] != message
                or commit["message_digest"] != proposal.message_digest
                or _post_commit_paths(root, proposal.base_head, commit_oid) != planned_paths
                or actual_identity["author_digest"] != expected_author
                or actual_identity["committer_digest"] != expected_committer
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The resulting local Commit does not match the approved proposal.",
                )
            # Move only approved paths in the real index to the new committed tree.
            # Every unrelated staged entry is compared byte-for-byte by semantic fields.
            _run_git(
                root,
                "update-index",
                "-z",
                "--index-info",
                input_bytes=_index_info_bytes(root, planned),
            )
            real_index_after = _index_entries(root)
            unrelated_before = {
                path: value
                for path, value in real_index_before.items()
                if path not in set(planned_paths)
            }
            unrelated_after = {
                path: value
                for path, value in real_index_after.items()
                if path not in set(planned_paths)
            }
            if unrelated_before != unrelated_after:
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "An unrelated Git index entry changed during Commit.",
                )
            for item in planned:
                actual = real_index_after.get(str(item["path"]))
                if item.get("present") is False:
                    if actual is not None:
                        raise _failure("COMMIT_INTEGRITY_BLOCKED", "A committed deletion remains indexed.")
                elif actual != {
                    "mode": item.get("mode"),
                    "blob_oid": item.get("blob_oid"),
                    "stage": "0",
                }:
                    raise _failure("COMMIT_INTEGRITY_BLOCKED", "A committed index entry is invalid.")
            if _staged_path_set(root, commit_oid) != staged_before:
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "Unrelated staged paths were not preserved exactly.",
                )
            _assert_targets_match(root, entries)
            baseline = _decoded_object(apply_session.after_evidence_json).get("global")
            post_global = _global_evidence_after_mutation(
                run,
                root,
                target_paths=[entry.repository_path for entry in entries],
                baseline=_decoded_object(baseline),
            )
            post = _safe_global_evidence(post_global)
            post["refs_excluding_current_fingerprint"] = _refs_fingerprint_excluding(
                root, proposal.branch_ref
            )
            post["unrelated_staged_paths_preserved"] = True
            post["unrelated_staged_path_identities"] = sorted(
                _sha256_bytes(path.encode("utf-8")) for path in staged_before
            )
            receipt = {
                "schema": "twos.owner_local_commit_receipt.v1",
                "commit_execution_id": execution.commit_execution_id,
                "proposal_digest": proposal.proposal_digest,
                "approval_digest": approval.approval_digest,
                "confirmation_digest": confirmation_digest,
                "commit_plan_digest": plan.plan_digest,
                "stage_digest": stage.stage_digest,
                "parent_oid": proposal.base_head,
                "commit_oid": commit_oid,
                "tree_oid": expected_tree,
                "message_digest": proposal.message_digest,
                "changed_path_identities": sorted(
                    _sha256_bytes(path.encode("utf-8")) for path in planned_paths
                ),
                "author_identity_digest": proposal.author_identity_digest,
                "hooks_evidence_digest": canonical_sha256(hooks),
                "post_commit": post,
            }
            execution.tree_oid = expected_tree
            execution.commit_oid = commit_oid
            execution.parent_oid = proposal.base_head
            execution.post_commit_evidence_json = canonical_json(post)
            execution.receipt_digest = canonical_sha256(receipt)
            execution.state = "COMMITTED"
            execution.finished_at = utc_now()
            session.commit()
            return execution, True
        except CommitBuilderError as exc:
            session.rollback()
            current = session.get(LocalCommitExecution, execution.id) or execution
            if current.state == "COMMITTING":
                try:
                    current_head = _git_text(root, "rev-parse", "HEAD")
                except CommitBuilderError:
                    current_head = ""
                current.state = (
                    "INTEGRITY_BLOCKED" if current_head != proposal.base_head else "FAILED"
                )
                current.failure_evidence_json = canonical_json([{"code": exc.code}])
                current.finished_at = utc_now()
                session.commit()
            raise
        finally:
            if alternate_index is not None:
                alternate_index.unlink(missing_ok=True)


def _approval_out(row: CommitProposalApproval | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.approval_id,
        "state": row.state,
        "proposal_version": row.proposal_version,
        "approved_at": row.approved_at.isoformat() + "Z",
        "approval_digest": row.approval_digest,
    }


def _execution_out(row: LocalCommitExecution | None) -> dict[str, Any] | None:
    if row is None:
        return None
    failures = [] if row.state == "COMMITTED" else _decoded_list(row.failure_evidence_json)
    return {
        "id": row.commit_execution_id,
        "state": row.state,
        "commit_oid": row.commit_oid,
        "parent_oid": row.parent_oid,
        "changed_file_count": len(_decoded_list(row.staged_entries_json)),
        "author": row.author_identity_sanitized,
        "hooks": _decoded_object(row.hooks_evidence_json),
        "receipt_digest": row.receipt_digest,
        "failures": failures,
        "started_at": row.command_started_at.isoformat() + "Z" if row.command_started_at else None,
        "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
        "advanced": {
            "intent_digest": row.intent_digest,
            "proposal_digest": row.proposal_digest,
            "proposal_approval_digest": row.proposal_approval_digest,
            "confirmation_digest": row.owner_commit_confirmation_digest,
            "tree_oid": row.tree_oid,
            "command_evidence": _decoded_object(row.command_evidence_json),
            "command_output": _decoded_object(row.command_output_json),
            "hooks_evidence": _decoded_object(row.hooks_evidence_json),
        },
    }


def commit_proposal_out(
    session: Session,
    *,
    proposal: CommitProposal,
) -> dict[str, Any]:
    approval = _approval_for_proposal(
        session,
        owner_id=proposal.owner_id,
        proposal_id=proposal.id,
    )
    execution = (
        _execution_for_approval(
            session,
            owner_id=proposal.owner_id,
            approval_id=approval.id,
        )
        if approval is not None
        else None
    )
    latest = _latest_proposal(
        session,
        owner_id=proposal.owner_id,
        verification_id=proposal.post_apply_verification_id,
    )
    is_latest = latest is not None and latest.id == proposal.id
    return {
        "id": proposal.proposal_id,
        "version": proposal.version,
        "proposal_digest": proposal.proposal_digest,
        "status": proposal.status_at_creation,
        "is_latest": is_latest,
        "subject": proposal.subject,
        "body": proposal.body,
        "author": proposal.author_identity_sanitized,
        "files": [
            {"path": item.get("path"), "operation": item.get("operation")}
            for item in _decoded_list(proposal.planned_paths_json)
            if isinstance(item, dict)
        ],
        "excluded_paths": _decoded_list(proposal.excluded_paths_json),
        "validation": _decoded_list(proposal.validation_json),
        "blockers": _decoded_list(proposal.blocker_codes_json),
        "warnings": _decoded_list(
            _decoded_object(proposal.boundary_evidence_json).get(
                "non_blocking_drift_warnings"
            )
        ),
        "approval": _approval_out(approval),
        "commit": _execution_out(execution),
        "actions": {
            "can_edit": bool(is_latest and approval is None and execution is None),
            "can_approve": bool(
                is_latest
                and proposal.status_at_creation == "READY"
                and approval is None
                and execution is None
            ),
            "can_commit": bool(
                is_latest
                and proposal.status_at_creation == "READY"
                and approval is not None
                and execution is None
            ),
        },
        "boundaries": [
            "Commit requires approval of this exact proposal version and a separate final confirmation.",
            "Only approved paths enter the alternate Commit index; unrelated staged entries are preserved.",
            "Configured Git Commit hooks run. This action never Pushes, tags, merges, rebases, or invokes a provider.",
        ],
        "advanced": {
            "policy_version": proposal.policy_version,
            "binding_digest": proposal.binding_digest,
            "message_digest": proposal.message_digest,
            "verification_id": proposal.verification_public_id,
            "verification_digest": proposal.verification_digest,
            "apply_session_id": proposal.apply_session_public_id,
            "journal_digest": proposal.journal_digest,
            "apply_plan_id": proposal.apply_plan_public_id,
            "apply_plan_digest": proposal.apply_plan_digest,
            "apply_plan_approval_id": proposal.apply_plan_approval_public_id,
            "apply_plan_approval_digest": proposal.apply_plan_approval_digest,
            "candidate_id": proposal.candidate_public_id,
            "candidate_version": proposal.candidate_version,
            "candidate_digest": proposal.candidate_digest,
            "result_id": proposal.result_envelope_public_id,
            "result_digest": proposal.result_digest,
            "result_review_decision_digest": proposal.result_review_decision_digest,
            "repository_identity": proposal.sanitized_repository_identity,
            "repository_locator_fingerprint": proposal.repository_locator_fingerprint,
            "branch": proposal.branch,
            "base_head": proposal.base_head,
        },
    }


def owner_commit_review(
    session: Session,
    *,
    owner_id: int,
    post_apply_verification: PostApplyVerification,
    source_repo: Path,
) -> dict[str, Any]:
    if post_apply_verification.owner_id != owner_id:
        raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
    proposal = _latest_proposal(
        session,
        owner_id=owner_id,
        verification_id=post_apply_verification.id,
    )
    author_readiness: dict[str, Any]
    readiness_blockers: list[dict[str, str]] = []
    try:
        _apply_session, _apply_plan, _candidate, run, _pack, _entries, *_ = (
            _result_lineage(
                session,
                owner_id=owner_id,
                verification=post_apply_verification,
            )
        )
        root = _verified_root(run, source_repo)
        identity = _author_readiness(root)
        author_readiness = {
            "status": "READY",
            "status_label": "READY",
            "ready": True,
            "author": identity["author"]["sanitized"],
        }
        if proposal is not None and identity["identity_digest"] != proposal.author_identity_digest:
            author_readiness = {
                "status": "CHANGED",
                "status_label": "REVIEW REQUIRED",
                "ready": False,
                "author": identity["author"]["sanitized"],
            }
            readiness_blockers.append(
                {
                    "code": "GIT_IDENTITY_CHANGED",
                    "message": "Git author identity changed after the proposal was created.",
                }
            )
    except CommitBuilderError as exc:
        if exc.code not in {"GIT_IDENTITY_MISSING", "GIT_IDENTITY_INVALID"}:
            raise
        author_readiness = {
            "status": "NEEDS_SETUP",
            "status_label": "NEEDS SETUP",
            "ready": False,
            "author": None,
        }
        readiness_blockers.append({"code": exc.code, "message": exc.message})
    proposal_output = (
        commit_proposal_out(session, proposal=proposal) if proposal is not None else None
    )
    if proposal_output is not None and not author_readiness["ready"]:
        proposal_output["actions"]["can_approve"] = False
        proposal_output["actions"]["can_commit"] = False
        proposal_output["blockers"] = [
            *proposal_output.get("blockers", []),
            *readiness_blockers,
        ]
    status = (
        "NEEDS_SETUP"
        if author_readiness["status"] == "NEEDS_SETUP"
        else (
            "BLOCKED"
            if not author_readiness["ready"]
            else ("READY_FOR_PROPOSAL" if proposal is None else proposal.status_at_creation)
        )
    )
    return {
        "status": status,
        "proposal": proposal_output,
        "author_readiness": author_readiness,
        "blockers": readiness_blockers,
        "actions": {
            "can_create_proposal": proposal is None and author_readiness["ready"]
        },
        "next_action": (
            "Configure a local Git user name and email for this repository."
            if author_readiness["status"] == "NEEDS_SETUP"
            else (
                "Review the changed Git author identity before creating a new proposal."
                if not author_readiness["ready"]
                else (
                    "Create and review the local Commit proposal."
                    if proposal is None
                    else "Review the current local Commit proposal."
                )
            )
        ),
    }
