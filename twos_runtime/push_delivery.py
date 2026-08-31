from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .apply_sessions import apply_session_out
from .commit_builder import (
    COMMIT_BUILDER_POLICY_VERSION,
    CommitBuilderError,
    _assert_targets_match,
    _bound_verification,
    _commit_builder_repository_lock,
    _commit_builder_repository_observation_lock,
    _commit_message,
    _commit_object,
    _commit_out,
    _decoded_list,
    _decoded_object,
    _git_environment,
    _git_text,
    _index_entries,
    _post_commit_paths,
    _refs_fingerprint_excluding,
    _run_git,
    _safe_global_evidence,
    _stage_out,
    _staged_path_set,
    _verified_root,
)
from .delivery_candidates import (
    canonical_json,
    canonical_sha256,
    delivery_candidate_out,
    source_drift_out,
)
from .models import (
    ApplySession,
    AuditEvent,
    CodexResultEnvelope,
    CommitProposal,
    CommitProposalApproval,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    PostApplyVerification,
    PushExecution,
    PushPlan,
    PushPlanApproval,
    SourceDriftEvaluation,
    StageExecution,
    utc_now,
)
from .post_apply_verifications import post_apply_verification_out
from .result_intake import result_envelope_out
from .self_hosting import (
    SOURCE_REPOSITORY_IDENTITY_METHODS,
    _source_repository_identity,
)
from .apply_sessions import _global_evidence_after_mutation


PUSH_DELIVERY_POLICY_VERSION = "twos.push_delivery.vol18.009.v1"
PUSH_CONFIRMATION = "PUSH_TO_ORIGIN_MAIN"
PUSH_PLAN_APPROVAL_CONFIRMATION = "APPROVE_PUSH_PLAN"
PUSH_REMOTE = "origin"
PUSH_BRANCH = "main"
PUSH_BRANCH_REF = "refs/heads/main"
PUSH_TRACKING_REF = "refs/remotes/origin/main"
PUSH_TRACKING_HEAD_REF = "refs/remotes/origin/HEAD"
MAX_PUSH_COMMAND_OUTPUT_BYTES = 16_384
MAX_CREDENTIAL_HELPER_CONFIG_BYTES = 65_536
MAX_CREDENTIAL_HELPER_CONFIG_ENTRIES = 64
PUSH_FINAL_LOCK_WAIT_SECONDS = 5.0
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_REMOTE_SCHEMES = frozenset({"file", "https", "ssh"})
_DANGEROUS_REMOTE_CONFIG = re.compile(
    r"^(core\.sshcommand|remote\.origin\.(receivepack|uploadpack)|"
    r"protocol\.ext\.allow|core\.(gitproxy|askpass)|"
    r"http(\..*)?\.(extraheader|cookiefile)|"
    r"url\..*\.(insteadof|pushinsteadof))$",
    re.IGNORECASE,
)
_SAFE_CREDENTIAL_HELPERS = frozenset(
    {
        "cache",
        "libsecret",
        "manager",
        "manager-core",
        "osxkeychain",
        "store",
        "wincred",
    }
)
_OUTPUT_SECRET_PATTERNS = (
    re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.I),
    re.compile(r"\b(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(\bAuthorization\s*:\s*Bearer\s+)[^\s]+", re.I),
    re.compile(
        r"((?:api[_-]?key|access[_-]?token|token|password|client[_-]?secret|secret)"
        r"\s*[:=]\s*)[^\s]+",
        re.I,
    ),
    re.compile(
        r"\b(?:secret[-_]?token|access[-_]?token)"
        r"(?:\s*[:=]\s*[^\s]+)?",
        re.I,
    ),
    re.compile(r"(?<![A-Za-z0-9:])/(?:Users|private|tmp|var|home)/[^\s\r\n]+"),
)
_TRANSPORT_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "USER",
        "LOGNAME",
        "SSH_AUTH_SOCK",
        "SYSTEMROOT",
    }
)
_TERMINAL_STATES = frozenset(
    {
        "PUSHED",
        "PUSH_BLOCKED",
        "REMOTE_MOVED",
        "PUSH_FAILED",
        "RECONCILIATION_BLOCKED",
    }
)


class PushDeliveryError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


def _failure(code: str, message: str) -> PushDeliveryError:
    return PushDeliveryError(code, message)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_failure(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _status_label(state: str) -> str:
    return {
        "READY_TO_PUSH": "READY TO PUSH",
        "PUSHING": "PUSHING",
        "PUSHED": "PUSHED",
        "PUSH_BLOCKED": "PUSH BLOCKED",
        "REMOTE_MOVED": "REMOTE MOVED",
        "PUSH_FAILED": "PUSH FAILED",
        "RECONCILIATION_BLOCKED": "RECONCILIATION BLOCKED",
    }.get(state, state)


@contextmanager
def _push_repository_lock(
    repository_locator_fingerprint: str,
    *,
    observation: bool = False,
    wait_timeout_seconds: float = 0.0,
):
    try:
        if observation:
            lock = _commit_builder_repository_observation_lock(
                repository_locator_fingerprint
            )
        elif wait_timeout_seconds <= 0:
            lock = _commit_builder_repository_lock(
                repository_locator_fingerprint
            )
        else:
            lock = _commit_builder_repository_lock(
                repository_locator_fingerprint,
                wait_timeout_seconds=wait_timeout_seconds,
            )
        with lock:
            yield
    except CommitBuilderError as exc:
        code = getattr(exc, "code", "REPOSITORY_LOCK_UNAVAILABLE")
        if code not in {
            "REPOSITORY_MUTATION_ACTIVE",
            "REPOSITORY_LOCK_UNAVAILABLE",
            "REPOSITORY_IDENTITY_MISMATCH",
        }:
            code = "REPOSITORY_LOCK_UNAVAILABLE"
        message = {
            "REPOSITORY_MUTATION_ACTIVE": "Another repository mutation is active.",
            "REPOSITORY_LOCK_UNAVAILABLE": "The repository mutation lock is unavailable.",
            "REPOSITORY_IDENTITY_MISMATCH": "The repository identity cannot be locked safely.",
        }[code]
        raise _failure(code, message) from exc


@dataclass(frozen=True)
class BoundPushContext:
    local_commit: LocalCommitExecution
    stage: StageExecution
    plan: CommitPlan
    verification: PostApplyVerification
    apply_session: ApplySession
    candidate: DeliveryCandidate
    run: Any
    pack: Any
    entries: list[Any]
    root: Path


def find_owned_local_commit_execution(
    session: Session,
    *,
    owner_id: int,
    commit_execution_id: str,
) -> LocalCommitExecution | None:
    return session.scalar(
        select(LocalCommitExecution).where(
            LocalCommitExecution.owner_id == owner_id,
            LocalCommitExecution.commit_execution_id == commit_execution_id,
        )
    )


def find_owned_push_execution(
    session: Session,
    *,
    owner_id: int,
    push_execution_id: str,
) -> PushExecution | None:
    return session.scalar(
        select(PushExecution).where(
            PushExecution.owner_id == owner_id,
            PushExecution.push_execution_id == push_execution_id,
        )
    )


def find_owned_push_plan(
    session: Session,
    *,
    owner_id: int,
    push_plan_id: str,
) -> PushPlan | None:
    return session.scalar(
        select(PushPlan).where(
            PushPlan.owner_id == owner_id,
            PushPlan.push_plan_id == push_plan_id,
        )
    )


def find_owned_push_plan_approval(
    session: Session,
    *,
    owner_id: int,
    approval_id: str,
) -> PushPlanApproval | None:
    return session.scalar(
        select(PushPlanApproval).where(
            PushPlanApproval.owner_id == owner_id,
            PushPlanApproval.approval_id == approval_id,
        )
    )


def _bound_push_context(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
) -> BoundPushContext:
    if local_commit.owner_id != owner_id or local_commit.state != "COMMITTED":
        raise _failure("LOCAL_COMMIT_NOT_FOUND", "Local Commit result not found.")
    if (
        not local_commit.commit_oid
        or not _OID.fullmatch(local_commit.commit_oid)
        or not local_commit.parent_oid
        or not _OID.fullmatch(local_commit.parent_oid)
        or not local_commit.receipt_digest
        or not _SHA256.fullmatch(local_commit.receipt_digest)
    ):
        raise _failure(
            "LOCAL_COMMIT_INTEGRITY_BLOCKED",
            "The approved local Commit receipt is incomplete.",
        )
    stage = session.get(StageExecution, local_commit.stage_execution_id)
    plan = session.get(CommitPlan, local_commit.commit_plan_id)
    canonical_owner_commit = bool(
        local_commit.commit_proposal_id is not None
        and local_commit.commit_proposal_approval_id is not None
    )
    if (
        stage is None
        or plan is None
        or stage.owner_id != owner_id
        or plan.owner_id != owner_id
        or stage.id != local_commit.stage_execution_id
        or stage.commit_plan_id != plan.id
        or local_commit.commit_plan_id != plan.id
        or stage.state != "STAGED"
        or (
            not canonical_owner_commit
            and plan.status_at_creation != "READY"
        )
        or plan.policy_version != COMMIT_BUILDER_POLICY_VERSION
        or local_commit.commit_plan_digest != plan.plan_digest
        or local_commit.stage_digest != stage.stage_digest
        or local_commit.staged_entries_digest != stage.staged_entries_digest
        or local_commit.base_head != plan.base_head
        or local_commit.parent_oid != plan.base_head
        or local_commit.branch != plan.branch
        or local_commit.branch_ref != plan.branch_ref
        or local_commit.repository_locator_fingerprint
        != plan.repository_locator_fingerprint
    ):
        raise _failure(
            "LOCAL_COMMIT_BINDING_INVALID",
            "The local Commit no longer matches its approved evidence chain.",
        )
    verification = session.get(
        PostApplyVerification, plan.post_apply_verification_id
    )
    if verification is None or verification.owner_id != owner_id:
        raise _failure("LOCAL_COMMIT_NOT_FOUND", "Local Commit result not found.")
    try:
        (
            apply_session,
            _apply_plan,
            candidate,
            run,
            pack,
            entries,
        ) = _bound_verification(
            session,
            owner_id=owner_id,
            verification=verification,
        )
        root = _verified_root(run, source_repo)
    except (CommitBuilderError, OSError, RuntimeError, ValueError) as exc:
        raise _failure(
            "LOCAL_COMMIT_BINDING_INVALID",
            "The local Commit ownership and repository binding cannot be verified.",
        ) from exc
    if (
        plan.apply_session_id != apply_session.id
        or plan.delivery_candidate_id != candidate.id
        or plan.run_id != run.id
        or stage.verification_digest != verification.verification_digest
        or local_commit.commit_plan_public_id != plan.commit_plan_id
        or local_commit.stage_execution_public_id != stage.stage_execution_id
    ):
        raise _failure(
            "LOCAL_COMMIT_BINDING_INVALID",
            "The local Commit evidence chain is inconsistent.",
        )
    approved_source_snapshot = _decoded_object(pack.source_snapshot_json)
    expected_repository_identity = str(
        approved_source_snapshot.get("source_repository_identity") or ""
    )
    expected_repository_identity_method = str(
        approved_source_snapshot.get("source_repository_identity_method") or ""
    )
    try:
        if expected_repository_identity_method not in SOURCE_REPOSITORY_IDENTITY_METHODS:
            raise RuntimeError("Repository identity method is unsupported.")
        observed_repository_identity = _source_repository_identity(
            root,
            hardened_read_only=True,
            method=expected_repository_identity_method,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise _failure(
            "REPOSITORY_UNAVAILABLE",
            "The bound repository is unavailable.",
        ) from exc
    if (
        not expected_repository_identity
        or observed_repository_identity != expected_repository_identity
    ):
        raise _failure(
            "REPOSITORY_IDENTITY_CHANGED",
            "The bound repository identity changed.",
        )
    commit = _commit_object(root, local_commit.commit_oid)
    expected_paths = sorted(
        (
            str(item.get("path"))
            for item in _decoded_list(local_commit.staged_entries_json)
            if isinstance(item, dict)
        ),
        key=lambda value: value.encode("utf-8"),
    )
    expected_message = _commit_message(plan)
    receipt_valid = False
    canonical_lineage_valid = True
    if canonical_owner_commit:
        proposal, proposal_approval = _bound_commit_proposal(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
        )
        planned_rows = [
            {
                "path": str(item.get("path") or ""),
                "path_identity": str(item.get("path_identity") or ""),
                "operation": str(item.get("operation") or ""),
            }
            for item in _decoded_list(local_commit.staged_entries_json)
            if isinstance(item, dict)
        ]
        expected_message = (
            proposal.subject
            + (("\n\n" + proposal.body) if proposal.body else "")
            + "\n"
        ).encode("utf-8")
        hooks = _decoded_object(local_commit.hooks_evidence_json)
        hooks_digest = canonical_sha256(hooks) if hooks else ""
        canonical_lineage_valid = bool(
            proposal.post_apply_verification_id == verification.id
            and proposal.apply_session_id == apply_session.id
            and proposal.apply_plan_id == plan.apply_plan_id
            and proposal.delivery_candidate_id == candidate.id
            and proposal.run_id == run.id
            and proposal.task_id == run.task_id
            and proposal.pack_id == pack.id
            and proposal.verification_public_id == verification.verification_id
            and proposal.verification_digest == verification.verification_digest
            and proposal.apply_session_public_id == apply_session.session_id
            and proposal.journal_digest == apply_session.journal_digest
            and proposal.candidate_public_id == candidate.candidate_id
            and proposal.candidate_version == candidate.candidate_version
            and proposal.candidate_digest == candidate.candidate_digest
            and proposal.repository_locator_fingerprint
            == plan.repository_locator_fingerprint
            and proposal.sanitized_repository_identity
            == plan.sanitized_repository_identity
            and proposal.branch == plan.branch
            and proposal.branch_ref == plan.branch_ref
            and proposal.base_head == plan.base_head
            and proposal.source_snapshot_identity
            == apply_session.source_snapshot_identity
            and proposal.source_workspace_identity
            == apply_session.source_workspace_identity
            and proposal.run_workspace_identity
            == apply_session.run_workspace_identity
            and proposal.subject == plan.subject
            and proposal.body == plan.body
            and proposal.subject_digest == local_commit.subject_digest
            and proposal.body_digest == local_commit.body_digest
            and proposal.message_digest == local_commit.message_digest
            and proposal.planned_paths_digest == canonical_sha256(planned_rows)
            and proposal_approval.message_digest == proposal.message_digest
            and local_commit.author_identity_digest
            == proposal.author_identity_digest
            and local_commit.author_identity_sanitized
            == proposal.author_identity_sanitized
            and hooks_digest
            and local_commit.hooks_evidence_digest == hooks_digest
        )
        receipt = {
            "schema": "twos.owner_local_commit_receipt.v1",
            "commit_execution_id": local_commit.commit_execution_id,
            "proposal_digest": proposal.proposal_digest,
            "approval_digest": proposal_approval.approval_digest,
            "confirmation_digest": local_commit.owner_commit_confirmation_digest,
            "commit_plan_digest": local_commit.commit_plan_digest,
            "stage_digest": local_commit.stage_digest,
            "parent_oid": proposal.base_head,
            "commit_oid": local_commit.commit_oid,
            "tree_oid": commit["tree"],
            "message_digest": proposal.message_digest,
            "changed_path_identities": sorted(
                _sha256_bytes(path.encode("utf-8")) for path in expected_paths
            ),
            "author_identity_digest": proposal.author_identity_digest,
            "hooks_evidence_digest": local_commit.hooks_evidence_digest,
            "post_commit": _decoded_object(local_commit.post_commit_evidence_json),
        }
        recovered_receipt = {**receipt, "recovered": True}
        receipt_valid = local_commit.receipt_digest in {
            canonical_sha256(receipt),
            canonical_sha256(recovered_receipt),
        }
    else:
        receipt = {
            "schema": "twos.local_commit_receipt.v1",
            "commit_execution_id": local_commit.commit_execution_id,
            "commit_plan_digest": plan.plan_digest,
            "stage_digest": local_commit.stage_digest,
            "parent_oid": plan.base_head,
            "commit_oid": local_commit.commit_oid,
            "tree_oid": commit["tree"],
            "message_digest": commit["message_digest"],
            "changed_path_identities": sorted(
                _sha256_bytes(path.encode("utf-8")) for path in expected_paths
            ),
            "post_commit": _decoded_object(local_commit.post_commit_evidence_json),
        }
        receipt_valid = canonical_sha256(receipt) == local_commit.receipt_digest
    if (
        not canonical_lineage_valid
        or commit["parents"] != [plan.base_head]
        or commit["message"] != expected_message
        or commit["message_digest"] != local_commit.message_digest
        or commit["tree"] != local_commit.tree_oid
        or _post_commit_paths(root, plan.base_head, local_commit.commit_oid)
        != expected_paths
        or not receipt_valid
    ):
        raise _failure(
            "LOCAL_COMMIT_INTEGRITY_BLOCKED",
            "The approved local Commit object or receipt changed.",
        )
    return BoundPushContext(
        local_commit=local_commit,
        stage=stage,
        plan=plan,
        verification=verification,
        apply_session=apply_session,
        candidate=candidate,
        run=run,
        pack=pack,
        entries=entries,
        root=root,
    )


def _bound_commit_proposal(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
) -> tuple[CommitProposal, CommitProposalApproval]:
    proposal = (
        session.get(CommitProposal, local_commit.commit_proposal_id)
        if local_commit.commit_proposal_id is not None
        else None
    )
    approval = (
        session.get(
            CommitProposalApproval,
            local_commit.commit_proposal_approval_id,
        )
        if local_commit.commit_proposal_approval_id is not None
        else None
    )
    expected_confirmation_digest = (
        canonical_sha256(
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
        if proposal is not None
        else ""
    )
    expected_approval_digest = (
        canonical_sha256(
            {
                "schema": "twos.commit_proposal_approval.v1",
                "confirmation_digest": expected_confirmation_digest,
                "proposal_digest": proposal.proposal_digest,
                "approved_by_user_id": owner_id,
            }
        )
        if proposal is not None
        else ""
    )
    if (
        proposal is None
        or approval is None
        or proposal.owner_id != owner_id
        or approval.owner_id != owner_id
        or approval.commit_proposal_id != proposal.id
        or proposal.proposal_id != local_commit.proposal_public_id
        or proposal.proposal_digest != local_commit.proposal_digest
        or approval.approval_id != local_commit.proposal_approval_public_id
        or approval.approval_digest != local_commit.proposal_approval_digest
        or approval.proposal_public_id != proposal.proposal_id
        or approval.proposal_version != proposal.version
        or approval.proposal_digest != proposal.proposal_digest
        or approval.message_digest != proposal.message_digest
        or approval.approved_by_user_id != owner_id
        or approval.confirmation_digest != expected_confirmation_digest
        or approval.approval_digest != expected_approval_digest
        or approval.state != "APPROVED"
        or proposal.status_at_creation != "READY"
        or local_commit.commit_oid is None
        or local_commit.receipt_digest is None
    ):
        raise _failure(
            "LOCAL_COMMIT_APPROVAL_INVALID",
            "The local Commit is not bound to an exact approved Commit proposal.",
        )
    return proposal, approval


def _one_remote_url(root: Path, *, push: bool) -> bytes:
    args = ["remote", "get-url"]
    if push:
        args.append("--push")
    args.extend(["--all", PUSH_REMOTE])
    try:
        output = _run_git(root, *args).stdout
    except CommitBuilderError as exc:
        raise _failure("ORIGIN_UNAVAILABLE", "The origin remote is unavailable.") from exc
    rows = output.rstrip(b"\n").split(b"\n") if output else []
    if (
        len(rows) != 1
        or not rows[0]
        or b"\x00" in rows[0]
        or b"\r" in rows[0]
        or len(rows[0]) > 8_192
    ):
        raise _failure(
            "REMOTE_URL_UNSAFE",
            "origin must resolve to one bounded remote URL.",
        )
    return rows[0]


def _safe_remote_display(raw: bytes) -> str:
    digest = _sha256_bytes(raw)[:12]
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"origin (redacted:{digest})"
    if value.startswith("/") or value.startswith("./") or value.startswith("../"):
        return f"local origin (redacted:{digest})"
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() == "file":
            return f"local origin (redacted:{digest})"
        hostname = parsed.hostname or "redacted"
        port = f":{parsed.port}" if parsed.port is not None else ""
        sanitized = urlunsplit((parsed.scheme, hostname + port, "/[redacted path]", "", ""))
        return sanitized[:240]
    scp_like = re.fullmatch(r"(?:[^@/:\s]+@)?([^:/\s]+):(.+)", value)
    if scp_like:
        return f"{scp_like.group(1)}:[redacted path]"
    return f"origin (redacted:{digest})"


def _dangerous_remote_configuration(root: Path) -> bool:
    """Reject command-bearing Git configuration before any remote contact."""
    result = _run_git(
        root,
        "config",
        "--get-regexp",
        _DANGEROUS_REMOTE_CONFIG.pattern,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise _failure(
            "REMOTE_CONFIG_UNAVAILABLE",
            "The origin transport configuration cannot be inspected safely.",
        )
    return result.returncode == 0 and bool(result.stdout.strip())


def _credential_helper_fingerprint(root: Path) -> str:
    helpers = _run_git(
        root,
        "config",
        "--null",
        "--get-regexp",
        r"^credential(\..*)?\.helper$",
        check=False,
    )
    if helpers.returncode not in {0, 1}:
        raise _failure(
            "REMOTE_CONFIG_UNAVAILABLE",
            "The origin transport configuration cannot be inspected safely.",
        )
    if len(helpers.stdout) > MAX_CREDENTIAL_HELPER_CONFIG_BYTES:
        raise _failure(
            "REMOTE_CONFIG_UNSAFE",
            "The configured credential-helper boundary is too large.",
        )
    raw_entries = [entry for entry in helpers.stdout.split(b"\0") if entry]
    if len(raw_entries) > MAX_CREDENTIAL_HELPER_CONFIG_ENTRIES:
        raise _failure(
            "REMOTE_CONFIG_UNSAFE",
            "The configured credential-helper boundary has too many entries.",
        )
    bounded_entries: list[dict[str, str]] = []
    try:
        for raw_entry in raw_entries:
            raw_key, separator, raw_value = raw_entry.partition(b"\n")
            if not separator or not raw_key:
                raise ValueError("malformed credential helper entry")
            key = raw_key.decode("ascii").casefold()
            value = raw_value.decode("ascii").strip()
            if key != "credential.helper":
                # URL/context-scoped helpers participate in Git credential
                # resolution but are not returned by `--get-all
                # credential.helper`. Reject them instead of attempting to
                # reproduce Git's matching rules or permitting a shell helper.
                raise ValueError("scoped credential helper")
            if value and value.casefold() not in _SAFE_CREDENTIAL_HELPERS:
                raise ValueError("unsupported credential helper")
            bounded_entries.append(
                {
                    "key_digest": _sha256_bytes(raw_key),
                    "value_digest": _sha256_bytes(raw_value),
                }
            )
    except (UnicodeDecodeError, ValueError) as exc:
        raise _failure(
            "REMOTE_CONFIG_UNSAFE",
            "The configured credential helper is unsupported.",
        ) from exc
    return canonical_sha256(
        {
            "schema": "twos.credential_helper_boundary.v1",
            "helpers": bounded_entries,
        }
    )


def _sanitize_transport_output(material: bytes, *, root: Path) -> str:
    text = material[:MAX_PUSH_COMMAND_OUTPUT_BYTES].decode(
        "utf-8", errors="replace"
    )
    root_text = str(root)
    if root_text:
        text = text.replace(root_text, "<repository>")
    text = _OUTPUT_SECRET_PATTERNS[0].sub(r"\1<redacted>@", text)
    text = _OUTPUT_SECRET_PATTERNS[1].sub("<redacted-token>", text)
    text = _OUTPUT_SECRET_PATTERNS[2].sub(r"\1<redacted>", text)
    text = _OUTPUT_SECRET_PATTERNS[3].sub(r"\1<redacted>", text)
    text = _OUTPUT_SECRET_PATTERNS[4].sub("<redacted-token>", text)
    text = _OUTPUT_SECRET_PATTERNS[5].sub("<local-path>", text)
    return "".join(
        character
        for character in text
        if character in "\n\t" or ord(character) >= 32
    )


def _transport_output_evidence(
    *,
    root: Path,
    result: subprocess.CompletedProcess[bytes] | None,
    error: PushDeliveryError | None,
) -> dict[str, Any]:
    stdout = result.stdout if result is not None else (error.stdout if error else b"")
    stderr = result.stderr if result is not None else (error.stderr if error else b"")
    return {
        "schema": "twos.push_command_output.v1",
        "stdout": _sanitize_transport_output(stdout, root=root),
        "stderr": _sanitize_transport_output(stderr, root=root),
        "truncated": (
            len(stdout) > MAX_PUSH_COMMAND_OUTPUT_BYTES
            or len(stderr) > MAX_PUSH_COMMAND_OUTPUT_BYTES
        ),
        "timed_out": bool(error is not None and error.timed_out),
    }


def _local_remote_identity(root: Path, value: str) -> dict[str, Any]:
    if value.startswith("file://"):
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise _failure(
                "REMOTE_URL_UNSAFE",
                "The origin URL contains unsupported credential or query material.",
            )
        if parsed.netloc not in {"", "localhost"}:
            raise _failure("REMOTE_URL_UNSAFE", "The origin file URL is unsupported.")
        candidate = Path(parsed.path)
    else:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
    try:
        unresolved = candidate.lstat()
        if stat.S_ISLNK(unresolved.st_mode):
            raise OSError("symlink remote")
        resolved = candidate.resolve(strict=True)
        details = resolved.stat()
    except OSError as exc:
        raise _failure(
            "REMOTE_URL_UNSAFE",
            "The local origin repository cannot be identified safely.",
        ) from exc
    if not stat.S_ISDIR(details.st_mode):
        raise _failure(
            "REMOTE_URL_UNSAFE",
            "The local origin repository is unsupported.",
        )
    identity = canonical_sha256(
        {
            "schema": "twos.local_remote_identity.v1",
            "resolved_path_digest": _sha256_bytes(os.fsencode(resolved)),
            "device": details.st_dev,
            "inode": details.st_ino,
            "mode": stat.S_IMODE(details.st_mode),
        }
    )
    return {
        "kind": "local",
        "scheme": "file",
        "descriptor": f"local origin (identity:{identity[:12]})",
        "identity": identity,
    }


def _validated_remote_descriptor(root: Path, raw: bytes) -> dict[str, Any]:
    """Classify one bounded remote without persisting its raw URL."""
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _failure("REMOTE_URL_UNSAFE", "The origin URL is unsupported.") from exc
    if (
        not value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*::", value)
    ):
        raise _failure("REMOTE_URL_UNSAFE", "The origin URL is unsupported.")
    if value.startswith(("/", "./", "../", "file://")):
        return _local_remote_identity(root, value)
    if "://" in value:
        try:
            parsed = urlsplit(value)
            scheme = parsed.scheme.casefold()
            username = parsed.username
            password = parsed.password
            port = parsed.port
        except ValueError as exc:
            raise _failure("REMOTE_URL_UNSAFE", "The origin URL is unsupported.") from exc
        if (
            scheme not in _SAFE_REMOTE_SCHEMES
            or not parsed.hostname
            or password is not None
            or parsed.query
            or parsed.fragment
            or (scheme == "https" and username is not None)
        ):
            raise _failure(
                "REMOTE_URL_UNSAFE",
                "The origin URL contains unsupported credential or transport material.",
            )
        if scheme == "file":
            return _local_remote_identity(root, value)
        host = parsed.hostname.casefold()
        descriptor = (
            f"{scheme}://{host}{':' + str(port) if port else ''}/[redacted path]"
        )
        return {
            "kind": "network",
            "scheme": scheme,
            "descriptor": descriptor[:240],
            "identity": canonical_sha256(
                {
                    "schema": "twos.network_remote_descriptor.v1",
                    "scheme": scheme,
                    "host": host,
                    "port": port,
                    "url_digest": _sha256_bytes(raw),
                }
            ),
        }
    scp_like = re.fullmatch(r"(?:([^@/\s:]+)@)?([^:/\s]+):(.+)", value)
    if scp_like:
        host = scp_like.group(2).casefold()
        return {
            "kind": "network",
            "scheme": "ssh",
            "descriptor": f"{host}:[redacted path]",
            "identity": canonical_sha256(
                {
                    "schema": "twos.network_remote_descriptor.v1",
                    "scheme": "ssh",
                    "host": host,
                    "port": None,
                    "url_digest": _sha256_bytes(raw),
                }
            ),
        }
    return _local_remote_identity(root, value)


def _transport_command(*args: str) -> list[str]:
    return [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "push.followTags=false",
        "-c",
        "push.gpgSign=false",
        "-c",
        "remote.origin.mirror=false",
        "-c",
        "push.pushOption=",
        "-c",
        "push.negotiate=false",
        "-c",
        "push.useForceIfIncludes=false",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "protocol.ssh.allow=always",
        *args,
    ]


def _transport_environment() -> dict[str, str]:
    inherited = _git_environment()
    return {
        key: value
        for key, value in inherited.items()
        if key in _TRANSPORT_ENV_ALLOWLIST or key.startswith("GIT_")
    }


def _run_transport(
    root: Path,
    *args: str,
    timeout: int = 60,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            _transport_command(*args),
            cwd=root,
            capture_output=True,
            timeout=timeout,
            env=_transport_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PushDeliveryError(
            "REMOTE_TIMEOUT",
            "The remote Git operation timed out.",
            stdout=bytes(exc.stdout or b""),
            stderr=bytes(exc.stderr or b""),
            timed_out=True,
        ) from exc
    except OSError as exc:
        raise _failure(
            "REMOTE_UNAVAILABLE",
            "The remote Git operation could not start.",
        ) from exc


def _live_origin_main(root: Path) -> str:
    result = _run_transport(
        root,
        "ls-remote",
        "--refs",
        "--exit-code",
        PUSH_REMOTE,
        PUSH_BRANCH_REF,
        timeout=30,
    )
    if result.returncode != 0:
        code = "REMOTE_MAIN_UNAVAILABLE" if result.returncode == 2 else "REMOTE_UNAVAILABLE"
        raise _failure(code, "The live origin/main identity is unavailable.")
    rows = [row for row in result.stdout.splitlines() if row]
    if len(rows) != 1:
        raise _failure(
            "REMOTE_EVIDENCE_INVALID",
            "The live origin/main response is invalid.",
        )
    try:
        oid_bytes, ref_bytes = rows[0].split(b"\t", 1)
        oid = oid_bytes.decode("ascii")
        ref = ref_bytes.decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise _failure(
            "REMOTE_EVIDENCE_INVALID",
            "The live origin/main response is invalid.",
        ) from exc
    if not _OID.fullmatch(oid) or ref != PUSH_BRANCH_REF:
        raise _failure(
            "REMOTE_EVIDENCE_INVALID",
            "The live origin/main response is invalid.",
        )
    return oid


def _remote_evidence(context: BoundPushContext) -> dict[str, Any]:
    if _dangerous_remote_configuration(context.root):
        raise _failure(
            "REMOTE_CONFIG_UNSAFE",
            "The origin transport contains unsupported command configuration.",
        )
    credential_helper_fingerprint = _credential_helper_fingerprint(context.root)
    fetch_url = _one_remote_url(context.root, push=False)
    push_url = _one_remote_url(context.root, push=True)
    fetch_url_digest = _sha256_bytes(fetch_url)
    push_url_digest = _sha256_bytes(push_url)
    if fetch_url_digest != push_url_digest:
        raise _failure(
            "REMOTE_DESTINATION_MISMATCH",
            "origin fetch and Push destinations do not match exactly.",
        )
    descriptor = _validated_remote_descriptor(context.root, push_url)
    return {
        "fetch_url_digest": fetch_url_digest,
        "push_url_digest": push_url_digest,
        "display": descriptor["descriptor"],
        "remote_descriptor_identity": descriptor["identity"],
        "transport_kind": descriptor["kind"],
        "transport_scheme": descriptor["scheme"],
        "remote_credential_helper_fingerprint": credential_helper_fingerprint,
    }


def _delivery_refs_evidence(root: Path) -> dict[str, Any]:
    output = _run_git(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)%00%(symref)",
    ).stdout
    rows: list[dict[str, str]] = []
    tracking_oid: str | None = None
    tracking_head_target: str | None = None
    try:
        for raw_line in output.splitlines():
            if not raw_line:
                continue
            raw_ref, raw_oid, raw_symref = raw_line.split(b"\x00", 2)
            ref = raw_ref.decode("ascii")
            oid = raw_oid.decode("ascii")
            symref = raw_symref.decode("ascii")
            if not ref.startswith("refs/") or not _OID.fullmatch(oid):
                raise ValueError("invalid ref evidence")
            if symref and not symref.startswith("refs/"):
                raise ValueError("invalid symbolic ref evidence")
            if ref == PUSH_BRANCH_REF:
                continue
            if ref == PUSH_TRACKING_REF:
                if symref:
                    raise ValueError("tracking main cannot be symbolic")
                tracking_oid = oid
                continue
            if ref == PUSH_TRACKING_HEAD_REF:
                if not symref:
                    raise ValueError("tracking HEAD must be symbolic")
                tracking_head_target = symref
                continue
            rows.append(
                {"ref": ref, "symref": symref}
                if symref
                else {"ref": ref, "oid": oid}
            )
    except (ValueError, UnicodeDecodeError) as exc:
        raise _failure(
            "GIT_EVIDENCE_INVALID",
            "Git returned invalid delivery ref evidence.",
        ) from exc
    rows.sort(key=lambda item: item["ref"].encode("ascii"))
    return {
        "other_refs_fingerprint": canonical_sha256(rows),
        "origin_main_tracking_oid": tracking_oid,
        "origin_head_target": tracking_head_target,
        "other_ref_count": len(rows),
    }


def _local_observation(context: BoundPushContext) -> dict[str, Any]:
    root = context.root
    target_blocker: dict[str, str] | None = None
    try:
        _assert_targets_match(root, context.entries)
    except CommitBuilderError as exc:
        code = str(getattr(exc, "code", "DELIVERY_PATH_CHANGED"))
        if code not in {
            "APPLIED_PATH_CHANGED",
            "TARGET_CONTENT_CHANGED",
            "POST_APPLY_TARGET_CHANGED",
            "PATH_BOUNDARY_BLOCKED",
            "WORKSPACE_ESCAPE",
        }:
            code = "DELIVERY_PATH_CHANGED"
        target_blocker = _safe_failure(
            code,
            "An exact delivery path changed after the approved local Commit.",
        )
    head = _git_text(root, "rev-parse", "HEAD")
    branch_ref = _git_text(root, "symbolic-ref", "--quiet", "HEAD")
    status = _run_git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    staged_paths = _staged_path_set(root, head)
    owned_paths = {
        str(item.get("path"))
        for item in _decoded_list(context.local_commit.staged_entries_json)
        if isinstance(item, dict) and item.get("path")
    }
    owned_staged_paths = sorted(
        owned_paths.intersection(staged_paths),
        key=lambda value: value.encode("utf-8"),
    )
    unmerged = _run_git(root, "ls-files", "--unmerged", "-z").stdout
    index_entries = _index_entries(root)
    index_semantic_rows = [
        {
            "path_identity": _sha256_bytes(path.encode("utf-8")),
            "mode": entry.get("mode"),
            "blob_oid": entry.get("blob_oid"),
            "stage": entry.get("stage"),
        }
        for path, entry in sorted(
            index_entries.items(), key=lambda item: item[0].encode("utf-8")
        )
    ]
    baseline = _decoded_object(
        _decoded_object(context.apply_session.after_evidence_json).get("global")
    )
    global_evidence = _safe_global_evidence(
        _global_evidence_after_mutation(
            context.run,
            root,
            target_paths=[entry.repository_path for entry in context.entries],
            baseline=baseline,
        )
    )
    delivery_refs = _delivery_refs_evidence(root)
    return {
        "head": head,
        "branch": branch_ref.removeprefix("refs/heads/"),
        "branch_ref": branch_ref,
        "worktree_clean": not status,
        "index_clean": not staged_paths,
        "staged_path_count": len(staged_paths),
        "staged_paths": staged_paths,
        "owned_staged_path_count": len(owned_staged_paths),
        "owned_staged_path_identities": [
            _sha256_bytes(path.encode("utf-8")) for path in owned_staged_paths
        ],
        "unmerged_path_count": len([item for item in unmerged.split(b"\0") if item]),
        "target_blocker": target_blocker,
        "worktree_status_digest": _sha256_bytes(status),
        "index_semantic_digest": canonical_sha256(index_semantic_rows),
        "unrelated_change_count": len(
            [item for item in status.split(b"\0") if item]
        ),
        "unrelated_worktree_fingerprint": global_evidence.get(
            "worktree_fingerprint"
        ),
        "unrelated_source_digest": global_evidence.get("source_digest"),
        "remote_config_fingerprint": global_evidence.get("remote_fingerprint"),
        "local_config_fingerprint": global_evidence.get("local_config_fingerprint"),
        "repository_locator_fingerprint": global_evidence.get(
            "repository_locator_fingerprint"
        ),
        "refs_excluding_main_fingerprint": _refs_fingerprint_excluding(
            root, PUSH_BRANCH_REF
        ),
        "delivery_refs_fingerprint": delivery_refs["other_refs_fingerprint"],
        "origin_main_tracking_oid": delivery_refs[
            "origin_main_tracking_oid"
        ],
        "origin_head_target": delivery_refs["origin_head_target"],
        "other_ref_count": delivery_refs["other_ref_count"],
    }


def _command_evidence(approved_commit_oid: str) -> dict[str, Any]:
    refspec = f"{approved_commit_oid}:{PUSH_BRANCH_REF}"
    safe_argv = [
        "push",
        "--porcelain",
        "--no-follow-tags",
        "--recurse-submodules=no",
        "--",
        PUSH_REMOTE,
        refspec,
    ]
    return {
        "schema": "twos.standard_push_command.v1",
        "remote": PUSH_REMOTE,
        "destination_ref": PUSH_BRANCH_REF,
        "refspec": refspec,
        "refspec_count": 1,
        "force": False,
        "force_with_lease": False,
        "mirror": False,
        "all": False,
        "tags": False,
        "follow_tags": False,
        "set_upstream": False,
        "recurse_submodules": False,
        "automatic_retry": False,
        "fetch": False,
        "pull": False,
        "merge": False,
        "rebase": False,
        "remote_mutation": False,
        "safe_argv": safe_argv,
        "full_argv": _transport_command(*safe_argv),
        "environment": {
            "interactive_prompts": False,
            "terminal_prompts": False,
            "optional_locks": False,
            "pager": False,
        },
    }


def _preflight_observation(context: BoundPushContext) -> dict[str, Any]:
    local = _local_observation(context)
    remote = _remote_evidence(context)
    post_commit = _decoded_object(context.local_commit.post_commit_evidence_json)
    blockers: list[dict[str, str]] = []
    if isinstance(local.get("target_blocker"), dict):
        blockers.append(dict(local["target_blocker"]))
        blockers.append(
            _safe_failure(
                "WORKTREE_DIRTY",
                "An exact delivery path is modified in the working tree.",
            )
        )
    if context.plan.branch != PUSH_BRANCH or context.local_commit.branch != PUSH_BRANCH:
        blockers.append(_safe_failure("WRONG_BRANCH", "Push is limited to branch main."))
    if local["branch_ref"] != PUSH_BRANCH_REF:
        blockers.append(_safe_failure("WRONG_BRANCH", "The current branch is not main."))
    if local["head"] != context.local_commit.commit_oid:
        blockers.append(_safe_failure("HEAD_CHANGED", "Local HEAD changed after Commit."))
    if context.local_commit.parent_oid != context.plan.base_head:
        blockers.append(
            _safe_failure(
                "COMMIT_PARENT_CHANGED",
                "The approved Commit parent does not match the expected base.",
            )
        )
    if local["owned_staged_path_count"]:
        blockers.append(
            _safe_failure(
                "DELIVERY_PATH_STAGED",
                "An exact delivery path changed in the Git index after Commit.",
            )
        )
        blockers.append(
            _safe_failure(
                "INDEX_DIRTY",
                "An exact delivery path is modified in the Git index.",
            )
        )
    if local["unmerged_path_count"]:
        blockers.append(
            _safe_failure(
                "INDEX_CONFLICT",
                "The Git index contains an unresolved conflict.",
            )
        )
    if (
        local["repository_locator_fingerprint"]
        != context.local_commit.repository_locator_fingerprint
    ):
        blockers.append(
            _safe_failure(
                "REPOSITORY_IDENTITY_CHANGED",
                "The bound repository identity changed.",
            )
        )
    if local["remote_config_fingerprint"] != post_commit.get("remote_fingerprint"):
        blockers.append(
            _safe_failure("REMOTE_URL_CHANGED", "The origin remote configuration changed.")
        )
    if local["local_config_fingerprint"] != post_commit.get(
        "local_config_fingerprint"
    ):
        blockers.append(
            _safe_failure("CONFIG_CHANGED", "The local Git configuration changed.")
        )
    if local["refs_excluding_main_fingerprint"] != post_commit.get(
        "refs_excluding_current_fingerprint"
    ):
        blockers.append(
            _safe_failure("REFS_CHANGED", "A local Git ref changed after Commit.")
        )
    if local["origin_main_tracking_oid"] not in {
        None,
        context.local_commit.parent_oid,
    }:
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "The local origin/main tracking ref is not at the approved remote base.",
            )
        )
    if local["origin_head_target"] not in {None, PUSH_TRACKING_REF}:
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "The local origin/HEAD symbolic ref does not target origin/main.",
            )
        )
    # Never contact a remote until its complete local configuration still
    # matches the approved Local Commit receipt. This prevents a changed URL
    # or config rewrite from redirecting the live preflight.
    live_remote = None if blockers else _live_origin_main(context.root)
    already_delivered = live_remote == context.local_commit.commit_oid
    if (
        live_remote is not None
        and not already_delivered
        and live_remote != context.local_commit.parent_oid
    ):
        blockers.append(
            _safe_failure(
                "REMOTE_MOVED",
                "Live origin/main no longer matches the approved Commit parent.",
            )
        )
    command = _command_evidence(str(context.local_commit.commit_oid))
    return {
        "schema": "twos.push_preflight_observation.v1",
        "repository": context.plan.sanitized_repository_identity,
        "repository_locator_fingerprint": context.plan.repository_locator_fingerprint,
        "branch": PUSH_BRANCH,
        "branch_ref": PUSH_BRANCH_REF,
        "local_commit_sha": context.local_commit.commit_oid,
        "commit_subject": context.plan.subject,
        "expected_remote_base_sha": context.local_commit.parent_oid,
        "observed_remote_base_sha": live_remote,
        "destination": "origin/main",
        "ahead": (
            0
            if already_delivered
            else 1
            if live_remote == context.local_commit.parent_oid
            else None
        ),
        "behind": (
            0
            if already_delivered or live_remote == context.local_commit.parent_oid
            else None
        ),
        "worktree_clean": local["worktree_clean"],
        "index_clean": local["index_clean"],
        "staged_path_count": local["staged_path_count"],
        "owned_staged_path_count": local["owned_staged_path_count"],
        "unmerged_path_count": local["unmerged_path_count"],
        "unrelated_change_count": local["unrelated_change_count"],
        "unrelated_worktree_fingerprint": local[
            "unrelated_worktree_fingerprint"
        ],
        "unrelated_source_digest": local["unrelated_source_digest"],
        "worktree_status_digest": local["worktree_status_digest"],
        "index_semantic_digest": local["index_semantic_digest"],
        "remote_fetch_url_digest": remote["fetch_url_digest"],
        "remote_push_url_digest": remote["push_url_digest"],
        "remote_display": remote["display"],
        "remote_descriptor_identity": remote["remote_descriptor_identity"],
        "remote_transport_kind": remote["transport_kind"],
        "remote_transport_scheme": remote["transport_scheme"],
        "remote_credential_helper_fingerprint": remote[
            "remote_credential_helper_fingerprint"
        ],
        "remote_config_fingerprint": local["remote_config_fingerprint"],
        "delivery_refs_fingerprint": local["delivery_refs_fingerprint"],
        "origin_main_tracking_oid": local["origin_main_tracking_oid"],
        "origin_head_target": local["origin_head_target"],
        "other_ref_count": local["other_ref_count"],
        "command": command,
        "already_delivered": already_delivered,
        "blockers": blockers,
    }


def _safe_preflight_observation(
    context: BoundPushContext,
) -> dict[str, Any]:
    try:
        return _preflight_observation(context)
    except PushDeliveryError:
        raise
    except (CommitBuilderError, OSError, RuntimeError, ValueError) as exc:
        raise _failure(
            "REPOSITORY_UNAVAILABLE",
            "Push readiness could not inspect the bound repository safely.",
        ) from exc


def _latest_push_execution(
    session: Session,
    *,
    owner_id: int,
    local_commit_id: int,
) -> PushExecution | None:
    return session.scalar(
        select(PushExecution)
        .where(
            PushExecution.owner_id == owner_id,
            PushExecution.local_commit_execution_id == local_commit_id,
        )
        .order_by(PushExecution.id.desc())
        .limit(1)
    )


def _successful_push_execution(
    session: Session,
    *,
    owner_id: int,
    local_commit_id: int,
) -> PushExecution | None:
    return session.scalar(
        select(PushExecution).where(
            PushExecution.owner_id == owner_id,
            PushExecution.local_commit_execution_id == local_commit_id,
            PushExecution.state == "PUSHED",
        )
    )


def _active_push_execution(
    session: Session,
    *,
    owner_id: int,
    local_commit_id: int,
) -> PushExecution | None:
    return session.scalar(
        select(PushExecution).where(
            PushExecution.owner_id == owner_id,
            PushExecution.local_commit_execution_id == local_commit_id,
            PushExecution.state.in_(
                ["READY_TO_PUSH", "PUSHING", "RECONCILIATION_BLOCKED"]
            ),
        )
    )


def _execution_out(row: PushExecution | None) -> dict[str, Any] | None:
    if row is None:
        return None
    preflight = _decoded_object(row.preflight_evidence_json)
    recovery = _decoded_object(row.recovery_reconciliation_json)
    post = recovery or _decoded_object(row.post_push_evidence_json)
    blockers = (
        [] if row.state == "PUSHED" else _decoded_list(row.failure_evidence_json)
    )
    canonical_state = (
        "ALREADY_DELIVERED"
        if row.state == "PUSHED" and row.failure_category == "ALREADY_DELIVERED"
        else "NEEDS_REVIEW"
        if row.state == "RECONCILIATION_BLOCKED"
        else row.state
    )
    return {
        "id": row.push_execution_id,
        "state": row.state,
        "status": row.state,
        "status_label": _status_label(row.state),
        "canonical_state": canonical_state,
        "needs_review": canonical_state == "NEEDS_REVIEW",
        "already_delivered": canonical_state == "ALREADY_DELIVERED",
        "transport_attempted": row.command_attempt_count == 1,
        "remote_receipt_verified": bool(
            row.state == "PUSHED" and row.receipt_digest
        ),
        "confirmation_digest": row.confirmation_digest,
        "repository": row.sanitized_repository_identity,
        "branch": row.branch,
        "local_commit_sha": row.approved_commit_oid,
        "commit_subject": row.subject,
        "expected_remote_base_sha": row.observed_remote_base_oid,
        "destination": "origin/main",
        "ahead": preflight.get("ahead"),
        "behind": preflight.get("behind"),
        "worktree_clean": preflight.get("worktree_clean"),
        "index_clean": preflight.get("index_clean"),
        "staged_path_count": preflight.get("staged_path_count"),
        "unrelated_change_count": preflight.get("unrelated_change_count"),
        "unrelated_evidence_preserved": (
            post.get("unrelated_evidence_preserved") if post else None
        ),
        "refspec": row.refspec,
        "command_attempt_count": row.command_attempt_count,
        "post_push": post,
        "blockers": blockers,
        "next_action": {
            "READY_TO_PUSH": "Confirm Push to origin/main.",
            "PUSHING": "Review Push reconciliation before any new action.",
            "PUSHED": "View Delivery Result.",
            "PUSH_BLOCKED": "Resolve the Push blocker, then select Push to origin/main again.",
            "REMOTE_MOVED": "Review live origin/main before selecting Push again.",
            "PUSH_FAILED": "Review the Push failure before an explicit retry.",
            "RECONCILIATION_BLOCKED": "Review local and remote reconciliation.",
        }.get(row.state, "Review Push status."),
        "boundaries": [
            "One confirmation authorizes one standard Push attempt.",
            "No force, force-with-lease, tags, other branches, or remote mutation.",
            "No Fetch, Pull, Merge, Rebase, or automatic retry.",
        ],
        "created_at": row.created_at.isoformat() + "Z",
        "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
        "advanced": {
            "policy_version": PUSH_DELIVERY_POLICY_VERSION,
            "preflight_evidence_digest": row.preflight_evidence_digest,
            "command_evidence_digest": row.command_evidence_digest,
            "receipt_digest": row.receipt_digest,
            "recovery_reconciliation_digest": row.recovery_reconciliation_digest,
            "recovered_at": (
                row.recovered_at.isoformat() + "Z" if row.recovered_at else None
            ),
            "remote_fetch_url_digest": row.remote_fetch_url_digest,
            "remote_push_url_digest": row.remote_push_url_digest,
            "remote_config_fingerprint": row.remote_config_fingerprint,
            "command_evidence": _decoded_object(row.command_evidence_json),
            "command_output": _decoded_object(row.command_output_json),
            "failure_category": row.failure_category or None,
            "command_exit_code": row.command_exit_code,
        },
    }


def _confirmation_state(
    *,
    plan: PushPlan | None,
    approval: PushPlanApproval | None,
    execution: PushExecution | None,
    can_confirm: bool,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project one authoritative Owner state for the final confirmation."""
    if execution is None:
        state = "ready_for_confirmation" if can_confirm else "blocked"
    elif execution.state == "READY_TO_PUSH":
        state = "ready_for_confirmation" if can_confirm else "blocked"
    elif execution.state == "PUSHING":
        state = "running"
    elif execution.state == "PUSHED":
        state = (
            "already_delivered"
            if execution.failure_category == "ALREADY_DELIVERED"
            else "succeeded"
        )
    elif execution.state == "PUSH_FAILED":
        output = _decoded_object(execution.command_output_json)
        state = (
            "timed_out"
            if execution.failure_category == "REMOTE_TIMEOUT"
            or output.get("timed_out") is True
            else "failed"
        )
    elif execution.state in {"REMOTE_MOVED", "RECONCILIATION_BLOCKED"}:
        state = "needs_review"
    else:
        state = "blocked"
    reason = None
    if blockers:
        reason = str(blockers[0].get("message") or "Push is blocked.")
    elif plan is not None and approval is None and execution is None:
        reason = "Approve this exact Push Plan before final confirmation."
    elif execution is not None:
        failures = _decoded_list(execution.failure_evidence_json)
        if failures and isinstance(failures[0], dict):
            reason = str(failures[0].get("message") or "") or None
    request_identity = (
        execution.confirmation_digest
        if execution is not None
        else _push_plan_final_confirmation_digest(plan, approval)
        if plan is not None and approval is not None
        else None
    )
    progress = {
        "ready_for_confirmation": "Ready for explicit Owner confirmation.",
        "submitting": "Push request accepted; preparing the exact attempt.",
        "running": "Push execution is running independently of this dialog.",
        "succeeded": "Push completed and the exact remote SHA was verified.",
        "already_delivered": "The exact approved Commit is already delivered.",
        "blocked": reason or "Push confirmation is blocked.",
        "failed": reason or "Push failed before verified delivery.",
        "timed_out": reason or "Push timed out; review remote evidence before retry.",
        "needs_review": reason or "Remote effect needs review; automatic retry is blocked.",
    }[state]
    return {
        "state": state,
        "in_progress": state in {"submitting", "running"},
        "can_confirm": state == "ready_for_confirmation",
        "request_accepted": execution is not None and plan is not None,
        "reason": reason,
        "progress": progress,
        "plan_id": plan.push_plan_id if plan is not None else None,
        "request_identity": request_identity,
        "execution_id": (
            execution.push_execution_id if execution is not None else None
        ),
    }


def _readiness_out(
    observation: dict[str, Any] | None,
    *,
    blockers: list[dict[str, Any]],
    fallback_context: BoundPushContext | None = None,
) -> dict[str, Any]:
    ready = observation is not None and not blockers
    return {
        "status": "READY_TO_PUSH" if ready else "PUSH_BLOCKED",
        "status_label": "READY TO PUSH" if ready else "PUSH BLOCKED",
        "repository": (
            observation.get("repository")
            if observation is not None
            else (
                fallback_context.plan.sanitized_repository_identity
                if fallback_context is not None
                else "Unavailable"
            )
        ),
        "branch": observation.get("branch") if observation is not None else PUSH_BRANCH,
        "local_commit_sha": (
            observation.get("local_commit_sha")
            if observation is not None
            else (
                fallback_context.local_commit.commit_oid
                if fallback_context is not None
                else None
            )
        ),
        "commit_subject": (
            observation.get("commit_subject")
            if observation is not None
            else (fallback_context.plan.subject if fallback_context is not None else None)
        ),
        "expected_remote_base_sha": (
            observation.get("expected_remote_base_sha")
            if observation is not None
            else (
                fallback_context.local_commit.parent_oid
                if fallback_context is not None
                else None
            )
        ),
        "destination": "origin/main",
        "ahead": observation.get("ahead") if observation is not None else None,
        "behind": observation.get("behind") if observation is not None else None,
        "worktree_clean": (
            observation.get("worktree_clean") if observation is not None else None
        ),
        "index_clean": observation.get("index_clean") if observation is not None else None,
        "staged_path_count": (
            observation.get("staged_path_count") if observation is not None else None
        ),
        "blockers": blockers,
        "next_action": (
            "Push to origin/main."
            if ready
            else (blockers[0].get("message") if blockers else "Review Push readiness.")
        ),
    }


def _reconciliation_locked(
    context: BoundPushContext,
    row: PushExecution,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    try:
        local = _local_observation(context)
        remote = _remote_evidence(context)
    except (PushDeliveryError, CommitBuilderError, OSError, RuntimeError, ValueError) as exc:
        code = getattr(exc, "code", "RECONCILIATION_BLOCKED")
        message = getattr(
            exc,
            "message",
            "Final local/remote reconciliation could not be inspected safely.",
        )
        return {
            "status": "RECONCILIATION_BLOCKED",
            "complete": False,
            "local_head": None,
            "origin_main_sha": None,
            "approved_commit_sha": row.approved_commit_oid,
            "ahead": None,
            "behind": None,
            "worktree_clean": None,
            "index_clean": None,
            "staged_path_count": None,
            "blockers": [_safe_failure(str(code), str(message))],
        }
    post_commit = _decoded_object(context.local_commit.post_commit_evidence_json)
    preflight = _decoded_object(row.preflight_evidence_json)
    if isinstance(local.get("target_blocker"), dict):
        blockers.append(dict(local["target_blocker"]))
    if local["head"] != row.approved_commit_oid:
        blockers.append(_safe_failure("HEAD_CHANGED", "Local HEAD changed."))
    if local["branch_ref"] != PUSH_BRANCH_REF:
        blockers.append(_safe_failure("WRONG_BRANCH", "The current branch is not main."))
    if local["owned_staged_path_count"]:
        blockers.append(
            _safe_failure(
                "DELIVERY_PATH_STAGED",
                "An exact delivery path changed in the Git index.",
            )
        )
    if local["unmerged_path_count"]:
        blockers.append(
            _safe_failure("INDEX_CONFLICT", "The Git index contains a conflict.")
        )
    if remote["fetch_url_digest"] != row.remote_fetch_url_digest or remote[
        "push_url_digest"
    ] != row.remote_push_url_digest:
        blockers.append(_safe_failure("REMOTE_URL_CHANGED", "The origin URL changed."))
    if local["remote_config_fingerprint"] != row.remote_config_fingerprint:
        blockers.append(
            _safe_failure("REMOTE_URL_CHANGED", "The origin configuration changed.")
        )
    for observed, key, code, message in (
        (
            local,
            "worktree_status_digest",
            "WORKTREE_CHANGED_DURING_PUSH",
            "Unrelated working-tree evidence changed during Push.",
        ),
        (
            local,
            "index_semantic_digest",
            "INDEX_CHANGED_DURING_PUSH",
            "The Git index changed during Push.",
        ),
        (
            local,
            "unrelated_worktree_fingerprint",
            "WORKTREE_CHANGED_DURING_PUSH",
            "Unrelated file content changed during Push.",
        ),
        (
            local,
            "unrelated_source_digest",
            "WORKTREE_CHANGED_DURING_PUSH",
            "Unrelated source evidence changed during Push.",
        ),
        (
            remote,
            "remote_descriptor_identity",
            "REMOTE_URL_CHANGED",
            "The origin destination identity changed during Push.",
        ),
        (
            remote,
            "remote_credential_helper_fingerprint",
            "REMOTE_CONFIG_CHANGED",
            "The credential-helper boundary changed during Push.",
        ),
    ):
        if observed.get(key) != preflight.get(key):
            blockers.append(_safe_failure(code, message))
    if local["local_config_fingerprint"] != post_commit.get(
        "local_config_fingerprint"
    ):
        blockers.append(
            _safe_failure("CONFIG_CHANGED", "The local Git configuration changed.")
        )
    if local["delivery_refs_fingerprint"] != preflight.get(
        "delivery_refs_fingerprint"
    ):
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "A local tag or non-main ref changed during delivery.",
            )
        )
    if local["origin_main_tracking_oid"] not in {
        preflight.get("origin_main_tracking_oid"),
        row.approved_commit_oid,
    }:
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "The local origin/main tracking ref changed unexpectedly.",
            )
        )
    if local["origin_head_target"] != preflight.get("origin_head_target"):
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "The local origin/HEAD symbolic ref changed during delivery.",
            )
        )
    # A changed local remote/config boundary must never be contacted merely to
    # render or reconcile a result.
    live_remote: str | None = None
    if not blockers:
        try:
            live_remote = _live_origin_main(context.root)
        except (
            PushDeliveryError,
            CommitBuilderError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            blockers.append(
                _safe_failure(
                    str(getattr(exc, "code", "RECONCILIATION_BLOCKED")),
                    str(
                        getattr(
                            exc,
                            "message",
                            "Live origin/main could not be reconciled safely.",
                        )
                    ),
                )
            )
    if live_remote is not None and live_remote != row.approved_commit_oid:
        blockers.append(
            _safe_failure(
                "REMOTE_NOT_RECONCILED",
                "Live origin/main does not equal the approved Commit.",
            )
        )
    complete = not blockers
    if local["head"] == live_remote:
        ahead, behind = 0, 0
    elif (
        local["head"] == row.approved_commit_oid
        and live_remote == row.expected_parent_oid
    ):
        ahead, behind = 1, 0
    else:
        ahead, behind = None, None
    return {
        "status": "RECONCILED" if complete else "RECONCILIATION_BLOCKED",
        "complete": complete,
        "local_head": local["head"],
        "origin_main_sha": live_remote,
        "approved_commit_sha": row.approved_commit_oid,
        "ahead": ahead,
        "behind": behind,
        "worktree_clean": local["worktree_clean"],
        "index_clean": local["index_clean"],
        "staged_path_count": local["staged_path_count"],
        "owned_staged_path_count": local["owned_staged_path_count"],
        "unrelated_change_count": local["unrelated_change_count"],
        "unrelated_evidence_preserved": not any(
            item.get("code")
            in {"WORKTREE_CHANGED_DURING_PUSH", "INDEX_CHANGED_DURING_PUSH"}
            for item in blockers
        ),
        "blockers": blockers,
    }


def _delivery_result(
    session: Session,
    *,
    context: BoundPushContext,
    push_execution: PushExecution | None,
    reconciliation: dict[str, Any] | None,
    readiness_blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    envelope = session.scalar(
        select(CodexResultEnvelope).where(
            CodexResultEnvelope.owner_id == context.local_commit.owner_id,
            CodexResultEnvelope.run_id == context.run.id,
        )
    )
    drift = (
        session.get(
            SourceDriftEvaluation,
            context.apply_session.source_drift_evaluation_id,
        )
        if context.apply_session.source_drift_evaluation_id is not None
        else None
    )
    run_result = result_envelope_out(envelope) if envelope is not None else None
    local_commit_out = _commit_out(context.local_commit)
    push_out = _execution_out(push_execution)
    reconciliation_value = reconciliation or {
        "status": "NOT_PUSHED",
        "complete": False,
        "local_head": context.local_commit.commit_oid,
        "origin_main_sha": None,
        "approved_commit_sha": context.local_commit.commit_oid,
        "ahead": 1,
        "behind": 0,
        "worktree_clean": None,
        "index_clean": None,
        "staged_path_count": 0,
        "blockers": [],
    }
    complete = bool(
        push_execution is not None
        and push_execution.state == "PUSHED"
        and reconciliation_value.get("complete") is True
        and reconciliation_value.get("local_head")
        == context.local_commit.commit_oid
        and reconciliation_value.get("origin_main_sha")
        == context.local_commit.commit_oid
        and reconciliation_value.get("ahead") == 0
        and reconciliation_value.get("behind") == 0
    )
    blockers = list(reconciliation_value.get("blockers") or [])
    blockers.extend(readiness_blockers or [])
    if push_execution is not None and push_execution.state != "PUSHED":
        blockers.extend(_decoded_list(push_execution.failure_evidence_json))
    warnings: list[dict[str, str]] = []
    if (
        push_execution is not None
        and push_execution.state == "PUSHED"
        and push_execution.command_exit_code not in {None, 0}
    ):
        warnings.append(
            _safe_failure(
                "PUSH_EXIT_NONZERO_RECONCILED",
                "The command returned nonzero but final delivery reconciled exactly.",
            )
        )
    if (
        push_execution is not None
        and push_execution.state == "PUSHED"
        and push_execution.failure_category == "RECONCILIATION_PENDING"
    ):
        warnings.append(
            _safe_failure(
                "INITIAL_RECONCILIATION_PENDING",
                "The Push command succeeded before live reconciliation became available.",
            )
        )
    if (
        push_execution is not None
        and push_execution.state == "PUSHED"
        and push_execution.recovery_reconciliation_digest
    ):
        warnings.append(
            _safe_failure(
                "RECONCILIATION_RECOVERED",
                "A previously blocked Push reconciliation later completed exactly.",
            )
        )
    if complete:
        next_action = "Delivery complete."
    elif readiness_blockers:
        next_action = str(
            readiness_blockers[0].get("message") or "Review Push readiness."
        )
    elif push_execution is None:
        next_action = "Push to origin/main."
    elif push_execution.state == "PUSHED":
        next_action = "Review live local/remote reconciliation."
    else:
        next_action = str(
            (push_out or {}).get("next_action") or "Review Push readiness."
        )
    return {
        "status": "DELIVERED" if complete else "NOT_DELIVERED",
        "status_label": "DELIVERED" if complete else "NOT DELIVERED",
        "complete": complete,
        "run_result": run_result,
        "independent_verification": (
            run_result.get("verification_result")
            if isinstance(run_result, dict)
            else None
        ),
        "delivery_candidate": delivery_candidate_out(context.candidate),
        "source_drift": source_drift_out(drift) if drift is not None else None,
        "apply_result": apply_session_out(session, context.apply_session),
        "post_apply_verification": post_apply_verification_out(
            context.verification
        ),
        "staged_paths": [
            {
                "path": item.get("path"),
                "operation": item.get("operation"),
            }
            for item in _decoded_list(context.stage.staged_entries_json)
            if isinstance(item, dict)
        ],
        "local_commit": local_commit_out,
        "push_status": push_out,
        "reconciliation": reconciliation_value,
        "boundaries": [
            "Push is limited to the approved local Commit and origin/main.",
            "No force, force-with-lease, tags, other branches, or remote mutation.",
            "No automatic Push or automatic next Run.",
        ],
        "warnings": warnings,
        "blockers": blockers,
        "next_action": next_action,
        "advanced": {
            "run_id": context.run.id,
            "candidate_id": context.candidate.candidate_id,
            "apply_session_id": context.apply_session.session_id,
            "post_apply_verification_id": context.verification.verification_id,
            "commit_plan_id": context.plan.commit_plan_id,
            "stage_execution_id": context.stage.stage_execution_id,
            "local_commit_execution_id": context.local_commit.commit_execution_id,
            "push_execution_id": (
                push_execution.push_execution_id if push_execution is not None else None
            ),
            "repository_locator_fingerprint": context.plan.repository_locator_fingerprint,
        },
    }


def _push_plan_out(
    plan: PushPlan | None,
    approval: PushPlanApproval | None = None,
    execution: PushExecution | None = None,
) -> dict[str, Any] | None:
    if plan is None:
        return None
    expired = plan.expires_at is not None and utc_now() >= plan.expires_at
    effective_status = "EXPIRED" if expired and plan.status_at_creation == "READY" else plan.status_at_creation
    preflight = _decoded_object(plan.preflight_evidence_json)
    return {
        "id": plan.push_plan_id,
        "version": plan.version,
        "status": effective_status,
        "status_label": effective_status.replace("_", " "),
        "approval_state": (
            "APPROVED"
            if approval is not None
            else "NOT_REQUIRED"
            if plan.status_at_creation == "ALREADY_DELIVERED"
            else "PENDING"
        ),
        "local_commit_sha": plan.approved_commit_oid,
        "local_branch": plan.branch,
        "remote": plan.remote_name,
        "remote_display": preflight.get("remote_display"),
        "target_ref": plan.destination_ref,
        "remote_old_sha": plan.observed_remote_base_oid or None,
        "remote_new_sha": plan.expected_remote_oid,
        "remote_exists": plan.remote_exists,
        "fast_forward": bool(
            plan.status_at_creation in {"READY", "ALREADY_DELIVERED"}
        ),
        "refspec": plan.refspec,
        "no_force": True,
        "no_tags": True,
        "reversible": False,
        "final_confirmation_text": PUSH_CONFIRMATION,
        "blockers": _decoded_list(plan.blocker_codes_json),
        "created_at": plan.created_at.isoformat() + "Z",
        "expires_at": plan.expires_at.isoformat() + "Z" if plan.expires_at else None,
        "approval": (
            {
                "id": approval.approval_id,
                "state": approval.state,
                "approved_at": approval.approved_at.isoformat() + "Z",
            }
            if approval is not None
            else None
        ),
        "execution": _execution_out(execution),
        "advanced": {
            "policy_version": plan.policy_version,
            "plan_digest": plan.plan_digest,
            "binding_digest": plan.binding_digest,
            "preflight_evidence_digest": plan.preflight_evidence_digest,
            "remote_fetch_url_digest": plan.remote_fetch_url_digest,
            "remote_push_url_digest": plan.remote_push_url_digest,
            "remote_config_fingerprint": plan.remote_config_fingerprint,
            "commit_proposal_id": plan.commit_proposal_public_id or None,
            "commit_proposal_digest": plan.commit_proposal_digest or None,
            "commit_proposal_approval_id": (
                plan.commit_proposal_approval_public_id or None
            ),
        },
    }


def _push_approval_out(
    approval: PushPlanApproval | None,
) -> dict[str, Any] | None:
    if approval is None:
        return None
    return {
        "id": approval.approval_id,
        "state": approval.state,
        "approved_at": approval.approved_at.isoformat() + "Z",
        "confirmation_text": PUSH_PLAN_APPROVAL_CONFIRMATION,
        "advanced": {
            "approval_digest": approval.approval_digest,
            "confirmation_digest": approval.confirmation_digest,
            "push_plan_id": approval.push_plan_public_id,
            "push_plan_version": approval.push_plan_version,
            "push_plan_digest": approval.push_plan_digest,
            "approved_commit_oid": approval.approved_commit_oid,
            "expected_remote_oid": approval.expected_remote_oid,
            "remote_config_fingerprint": approval.remote_config_fingerprint,
        },
    }


def _latest_push_plan(
    session: Session,
    *,
    owner_id: int,
    local_commit_id: int,
) -> PushPlan | None:
    return session.scalar(
        select(PushPlan)
        .where(
            PushPlan.owner_id == owner_id,
            PushPlan.local_commit_execution_id == local_commit_id,
        )
        .order_by(PushPlan.version.desc(), PushPlan.id.desc())
        .limit(1)
    )


def _approval_for_push_plan(
    session: Session,
    *,
    owner_id: int,
    plan_id: int,
) -> PushPlanApproval | None:
    return session.scalar(
        select(PushPlanApproval).where(
            PushPlanApproval.owner_id == owner_id,
            PushPlanApproval.push_plan_id == plan_id,
        )
    )


def _execution_for_push_plan(
    session: Session,
    *,
    owner_id: int,
    plan_id: int,
) -> PushExecution | None:
    return session.scalar(
        select(PushExecution)
        .where(
            PushExecution.owner_id == owner_id,
            PushExecution.push_plan_id == plan_id,
        )
        .order_by(PushExecution.id.desc())
        .limit(1)
    )


def _push_plan_is_expired(plan: PushPlan) -> bool:
    return bool(plan.expires_at is not None and utc_now() >= plan.expires_at)


def _pre_effect_execution_allows_plan_renewal(
    execution: PushExecution | None,
    observation: dict[str, Any] | None = None,
) -> bool:
    """Permit re-review only when a terminal attempt provably had no effect."""
    if (
        execution is None
        or execution.command_attempt_count != 0
        or execution.state not in {"PUSH_BLOCKED", "REMOTE_MOVED"}
    ):
        return False
    if observation is None:
        return True
    return (
        observation.get("observed_remote_base_sha")
        == execution.observed_remote_base_oid
    )


def _push_plan_current_blockers(
    plan: PushPlan,
    observation: dict[str, Any],
) -> list[dict[str, str]]:
    blockers = [
        dict(item)
        for item in observation.get("blockers", [])
        if isinstance(item, dict)
    ]
    preflight = _decoded_object(plan.preflight_evidence_json)
    comparisons = (
        ("local_commit_sha", plan.approved_commit_oid, "HEAD_CHANGED"),
        (
            "observed_remote_base_sha",
            plan.observed_remote_base_oid,
            "REMOTE_MOVED",
        ),
        (
            "remote_fetch_url_digest",
            plan.remote_fetch_url_digest,
            "REMOTE_URL_CHANGED",
        ),
        (
            "remote_push_url_digest",
            plan.remote_push_url_digest,
            "REMOTE_URL_CHANGED",
        ),
        (
            "remote_config_fingerprint",
            plan.remote_config_fingerprint,
            "REMOTE_URL_CHANGED",
        ),
        (
            "worktree_status_digest",
            preflight.get("worktree_status_digest"),
            "WORKTREE_CHANGED",
        ),
        (
            "index_semantic_digest",
            preflight.get("index_semantic_digest"),
            "INDEX_CHANGED",
        ),
        (
            "unrelated_worktree_fingerprint",
            preflight.get("unrelated_worktree_fingerprint"),
            "WORKTREE_CHANGED",
        ),
        (
            "unrelated_source_digest",
            preflight.get("unrelated_source_digest"),
            "WORKTREE_CHANGED",
        ),
        (
            "remote_descriptor_identity",
            preflight.get("remote_descriptor_identity"),
            "REMOTE_URL_CHANGED",
        ),
        (
            "remote_credential_helper_fingerprint",
            preflight.get("remote_credential_helper_fingerprint"),
            "REMOTE_CONFIG_CHANGED",
        ),
        (
            "delivery_refs_fingerprint",
            preflight.get("delivery_refs_fingerprint"),
            "REFS_CHANGED",
        ),
        (
            "origin_main_tracking_oid",
            preflight.get("origin_main_tracking_oid"),
            "REFS_CHANGED",
        ),
        (
            "origin_head_target",
            preflight.get("origin_head_target"),
            "REFS_CHANGED",
        ),
    )
    messages = {
        "HEAD_CHANGED": "Local HEAD changed after Push Plan review.",
        "REMOTE_MOVED": "Live origin/main changed after Push Plan review.",
        "REMOTE_URL_CHANGED": "The origin destination changed after Push Plan review.",
        "REMOTE_CONFIG_CHANGED": "The credential-helper boundary changed after Push Plan review.",
        "WORKTREE_CHANGED": "Working-tree evidence changed after Push Plan review.",
        "INDEX_CHANGED": "The Git index changed after Push Plan review.",
        "REFS_CHANGED": "Local Git refs changed after Push Plan review.",
    }
    for key, expected, code in comparisons:
        if observation.get(key) != expected:
            blockers.append(_safe_failure(code, messages[code]))
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in blockers:
        code = str(item.get("code") or "PUSH_PLAN_CHANGED")
        if code in seen:
            continue
        seen.add(code)
        deduplicated.append(
            _safe_failure(code, str(item.get("message") or "Push Plan changed."))
        )
    return deduplicated


def _validate_push_plan_binding(
    plan: PushPlan,
    *,
    owner_id: int,
    context: BoundPushContext,
    proposal: CommitProposal,
    proposal_approval: CommitProposalApproval,
) -> None:
    preflight = _decoded_object(plan.preflight_evidence_json)
    blockers = _decoded_list(plan.blocker_codes_json)
    expected_preflight_digest = canonical_sha256(preflight)
    expected_binding_digest = canonical_sha256(
        {
            "schema": "twos.push_plan_binding.v1",
            "owner_id": owner_id,
            "local_commit_execution_id": context.local_commit.commit_execution_id,
            "local_commit_receipt_digest": context.local_commit.receipt_digest,
            "commit_proposal_id": proposal.proposal_id,
            "commit_proposal_digest": proposal.proposal_digest,
            "commit_proposal_approval_id": proposal_approval.approval_id,
            "commit_proposal_approval_digest": proposal_approval.approval_digest,
            "run_id": context.run.id,
            "task_id": context.run.task_id,
            "repository_locator_fingerprint": context.plan.repository_locator_fingerprint,
            "branch_ref": PUSH_BRANCH_REF,
            "remote": PUSH_REMOTE,
            "destination_ref": PUSH_BRANCH_REF,
            "approved_commit_oid": context.local_commit.commit_oid,
            "observed_remote_base_oid": preflight.get(
                "observed_remote_base_sha"
            ),
            "remote_config_fingerprint": preflight.get(
                "remote_config_fingerprint"
            ),
        }
    )
    command = _decoded_object(preflight.get("command"))
    expected_plan_digest = canonical_sha256(
        {
            "schema": "twos.push_plan.v1",
            "policy_version": PUSH_DELIVERY_POLICY_VERSION,
            "version": plan.version,
            "binding_digest": expected_binding_digest,
            "preflight_evidence_digest": expected_preflight_digest,
            "refspec": command.get("refspec"),
            "blockers": blockers,
            "status_at_creation": plan.status_at_creation,
            "expires_at": plan.expires_at.isoformat() if plan.expires_at else None,
        }
    )
    if (
        plan.owner_id != owner_id
        or plan.local_commit_execution_id != context.local_commit.id
        or plan.commit_proposal_id != proposal.id
        or plan.commit_proposal_approval_id != proposal_approval.id
        or plan.run_id != context.run.id
        or plan.task_id != context.run.task_id
        or plan.local_commit_public_id
        != context.local_commit.commit_execution_id
        or plan.local_commit_receipt_digest != context.local_commit.receipt_digest
        or plan.commit_proposal_public_id != proposal.proposal_id
        or plan.commit_proposal_digest != proposal.proposal_digest
        or plan.commit_proposal_approval_public_id != proposal_approval.approval_id
        or plan.commit_proposal_approval_digest
        != proposal_approval.approval_digest
        or plan.repository_locator_fingerprint
        != context.plan.repository_locator_fingerprint
        or plan.sanitized_repository_identity
        != context.plan.sanitized_repository_identity
        or plan.branch != PUSH_BRANCH
        or plan.branch_ref != PUSH_BRANCH_REF
        or plan.remote_name != PUSH_REMOTE
        or plan.destination_ref != PUSH_BRANCH_REF
        or plan.approved_commit_oid != context.local_commit.commit_oid
        or plan.expected_parent_oid != context.local_commit.parent_oid
        or plan.observed_remote_base_oid
        != str(preflight.get("observed_remote_base_sha") or "")
        or plan.expected_remote_oid != context.local_commit.commit_oid
        or plan.subject != proposal.subject
        or plan.subject_digest
        != _sha256_bytes(proposal.subject.encode("utf-8"))
        or plan.remote_fetch_url_digest
        != str(preflight.get("remote_fetch_url_digest") or "")
        or plan.remote_push_url_digest
        != str(preflight.get("remote_push_url_digest") or "")
        or plan.remote_config_fingerprint
        != str(preflight.get("remote_config_fingerprint") or "")
        or plan.refspec != str(command.get("refspec") or "")
        or plan.preflight_evidence_digest != expected_preflight_digest
        or plan.binding_digest != expected_binding_digest
        or plan.plan_digest != expected_plan_digest
        or plan.policy_version != PUSH_DELIVERY_POLICY_VERSION
    ):
        raise _failure(
            "PUSH_PLAN_BINDING_INVALID",
            "The Push Plan no longer matches its immutable delivery evidence.",
        )


def _validate_push_plan_approval(
    plan: PushPlan,
    approval: PushPlanApproval,
    *,
    owner_id: int,
    expected_approval_digest: str,
) -> None:
    expected_confirmation_digest = canonical_sha256(
        {
            "schema": "twos.push_plan_owner_approval.v1",
            "owner_id": owner_id,
            "push_plan_id": plan.push_plan_id,
            "push_plan_version": plan.version,
            "push_plan_digest": plan.plan_digest,
            "confirmation": PUSH_PLAN_APPROVAL_CONFIRMATION,
        }
    )
    expected_digest = canonical_sha256(
        {
            "schema": "twos.push_plan_approval.v1",
            "owner_id": owner_id,
            "push_plan_id": plan.push_plan_id,
            "push_plan_version": plan.version,
            "push_plan_digest": plan.plan_digest,
            "approved_commit_oid": plan.approved_commit_oid,
            "expected_remote_oid": plan.expected_remote_oid,
            "remote_config_fingerprint": plan.remote_config_fingerprint,
            "confirmation_digest": expected_confirmation_digest,
        }
    )
    if (
        approval.owner_id != owner_id
        or approval.push_plan_id != plan.id
        or approval.push_plan_public_id != plan.push_plan_id
        or approval.push_plan_version != plan.version
        or approval.push_plan_digest != plan.plan_digest
        or approval.approved_commit_oid != plan.approved_commit_oid
        or approval.expected_remote_oid != plan.expected_remote_oid
        or approval.remote_config_fingerprint != plan.remote_config_fingerprint
        or approval.approved_by_user_id != owner_id
        or approval.state != "APPROVED"
        or approval.confirmation_digest != expected_confirmation_digest
        or approval.approval_digest != expected_digest
        or expected_approval_digest != approval.approval_digest
    ):
        raise _failure(
            "PUSH_APPROVAL_BINDING_INVALID",
            "The exact approved Push Plan binding changed.",
        )


def _push_plan_final_confirmation_digest(
    plan: PushPlan,
    approval: PushPlanApproval,
) -> str:
    """Return the stable server identity for one approved final confirmation."""
    return canonical_sha256(
        {
            "schema": "twos.push_plan_final_confirmation.v1",
            "owner_id": plan.owner_id,
            "push_plan_id": plan.push_plan_id,
            "push_plan_digest": plan.plan_digest,
            "push_plan_approval_id": approval.approval_id,
            "push_plan_approval_digest": approval.approval_digest,
            "confirmation": PUSH_CONFIRMATION,
        }
    )


def get_or_create_push_plan(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
    expires_in_seconds: int = 900,
) -> tuple[PushPlan, bool]:
    if not 60 <= expires_in_seconds <= 86_400:
        raise _failure("PUSH_PLAN_EXPIRY_INVALID", "The Push Plan expiry is invalid.")
    context = _bound_push_context(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
        source_repo=source_repo,
    )
    proposal, proposal_approval = _bound_commit_proposal(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
    )
    latest = _latest_push_plan(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    if latest is not None:
        existing_approval = _approval_for_push_plan(
            session,
            owner_id=owner_id,
            plan_id=latest.id,
        )
        existing_execution = _execution_for_push_plan(
            session,
            owner_id=owner_id,
            plan_id=latest.id,
        )
        renewable_execution = _pre_effect_execution_allows_plan_renewal(
            existing_execution
        )
        if (
            latest.status_at_creation == "ALREADY_DELIVERED"
            or (existing_execution is not None and not renewable_execution)
            or (
                existing_approval is not None
                and not _push_plan_is_expired(latest)
                and not renewable_execution
            )
        ):
            return latest, False
    with _push_repository_lock(
        local_commit.repository_locator_fingerprint,
        observation=True,
    ):
        session.expire_all()
        local_commit = session.get(LocalCommitExecution, local_commit.id)
        if local_commit is None or local_commit.owner_id != owner_id:
            raise _failure("LOCAL_COMMIT_NOT_FOUND", "Local Commit result not found.")
        context = _bound_push_context(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
            source_repo=source_repo,
        )
        proposal, proposal_approval = _bound_commit_proposal(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
        )
        latest = _latest_push_plan(
            session,
            owner_id=owner_id,
            local_commit_id=local_commit.id,
        )
        existing_approval = (
            _approval_for_push_plan(
                session,
                owner_id=owner_id,
                plan_id=latest.id,
            )
            if latest is not None
            else None
        )
        existing_execution = (
            _execution_for_push_plan(
                session,
                owner_id=owner_id,
                plan_id=latest.id,
            )
            if latest is not None
            else None
        )
        if latest is not None:
            renewable_execution = _pre_effect_execution_allows_plan_renewal(
                existing_execution
            )
            if (
                latest.status_at_creation == "ALREADY_DELIVERED"
                or (
                    existing_execution is not None
                    and not renewable_execution
                )
                or (
                    existing_approval is not None
                    and not _push_plan_is_expired(latest)
                    and not renewable_execution
                )
            ):
                return latest, False
        observation = _safe_preflight_observation(context)
        if (
            existing_execution is not None
            and not _pre_effect_execution_allows_plan_renewal(
                existing_execution,
                observation,
            )
        ):
            return latest, False
        if (
            latest is not None
            and latest.status_at_creation == "READY"
            and latest.expires_at is not None
            and utc_now() < latest.expires_at
            and not _push_plan_current_blockers(latest, observation)
        ):
            return latest, False
        blockers = list(observation.get("blockers") or [])
        status = (
            "BLOCKED"
            if blockers
            else "ALREADY_DELIVERED"
            if observation.get("already_delivered") is True
            else "READY"
        )
        version = (latest.version + 1) if latest is not None else 1
        created_at = utc_now()
        expires_at = created_at + timedelta(seconds=expires_in_seconds)
        preflight_material = {
            **observation,
            "schema": "twos.push_plan_preflight.v1",
            "policy_version": PUSH_DELIVERY_POLICY_VERSION,
            "owner_id": owner_id,
            "local_commit_execution_id": local_commit.commit_execution_id,
            "local_commit_receipt_digest": local_commit.receipt_digest,
        }
        preflight_digest = canonical_sha256(preflight_material)
        binding_material = {
            "schema": "twos.push_plan_binding.v1",
            "owner_id": owner_id,
            "local_commit_execution_id": local_commit.commit_execution_id,
            "local_commit_receipt_digest": local_commit.receipt_digest,
            "commit_proposal_id": proposal.proposal_id,
            "commit_proposal_digest": proposal.proposal_digest,
            "commit_proposal_approval_id": proposal_approval.approval_id,
            "commit_proposal_approval_digest": proposal_approval.approval_digest,
            "run_id": context.run.id,
            "task_id": context.run.task_id,
            "repository_locator_fingerprint": context.plan.repository_locator_fingerprint,
            "branch_ref": PUSH_BRANCH_REF,
            "remote": PUSH_REMOTE,
            "destination_ref": PUSH_BRANCH_REF,
            "approved_commit_oid": local_commit.commit_oid,
            "observed_remote_base_oid": observation.get("observed_remote_base_sha"),
            "remote_config_fingerprint": observation.get(
                "remote_config_fingerprint"
            ),
        }
        binding_digest = canonical_sha256(binding_material)
        command = _decoded_object(observation.get("command"))
        plan_material = {
            "schema": "twos.push_plan.v1",
            "policy_version": PUSH_DELIVERY_POLICY_VERSION,
            "version": version,
            "binding_digest": binding_digest,
            "preflight_evidence_digest": preflight_digest,
            "refspec": command.get("refspec"),
            "blockers": blockers,
            "status_at_creation": status,
            "expires_at": expires_at.isoformat(),
        }
        plan_digest = canonical_sha256(plan_material)
        row = PushPlan(
            push_plan_id="pushplan_" + plan_digest[:40],
            owner_id=owner_id,
            local_commit_execution_id=local_commit.id,
            commit_proposal_id=proposal.id,
            commit_proposal_approval_id=proposal_approval.id,
            run_id=context.run.id,
            task_id=context.run.task_id,
            version=version,
            supersedes_push_plan_id=latest.id if latest is not None else None,
            local_commit_public_id=local_commit.commit_execution_id,
            local_commit_receipt_digest=str(local_commit.receipt_digest),
            commit_proposal_public_id=proposal.proposal_id,
            commit_proposal_digest=proposal.proposal_digest,
            commit_proposal_approval_public_id=proposal_approval.approval_id,
            commit_proposal_approval_digest=proposal_approval.approval_digest,
            repository_locator_fingerprint=context.plan.repository_locator_fingerprint,
            sanitized_repository_identity=context.plan.sanitized_repository_identity,
            branch=PUSH_BRANCH,
            branch_ref=PUSH_BRANCH_REF,
            remote_name=PUSH_REMOTE,
            destination_ref=PUSH_BRANCH_REF,
            approved_commit_oid=str(local_commit.commit_oid),
            expected_parent_oid=str(local_commit.parent_oid),
            observed_remote_base_oid=str(
                observation.get("observed_remote_base_sha") or ""
            ),
            expected_remote_oid=str(local_commit.commit_oid),
            remote_exists=bool(observation.get("observed_remote_base_sha")),
            subject=proposal.subject,
            subject_digest=_sha256_bytes(proposal.subject.encode("utf-8")),
            remote_fetch_url_digest=str(
                observation.get("remote_fetch_url_digest") or ""
            ),
            remote_push_url_digest=str(
                observation.get("remote_push_url_digest") or ""
            ),
            remote_config_fingerprint=str(
                observation.get("remote_config_fingerprint") or ""
            ),
            refspec=str(command.get("refspec") or ""),
            preflight_evidence_json=canonical_json(preflight_material),
            preflight_evidence_digest=preflight_digest,
            blocker_codes_json=canonical_json(blockers),
            binding_digest=binding_digest,
            plan_digest=plan_digest,
            policy_version=PUSH_DELIVERY_POLICY_VERSION,
            status_at_creation=status,
            expires_at=expires_at,
            created_at=created_at,
        )
        session.add(row)
        session.flush()
        if status == "ALREADY_DELIVERED":
            _create_push_execution_for_plan(
                session,
                context=context,
                plan=row,
                approval=None,
                already_delivered=True,
            )
        return row, True


def approve_push_plan(
    session: Session,
    *,
    owner_id: int,
    push_plan: PushPlan,
    source_repo: Path,
    expected_plan_digest: str,
) -> tuple[PushPlanApproval, bool]:
    if push_plan.owner_id != owner_id:
        raise _failure("PUSH_PLAN_NOT_FOUND", "Push Plan not found.")
    existing = _approval_for_push_plan(
        session,
        owner_id=owner_id,
        plan_id=push_plan.id,
    )
    if existing is not None:
        if expected_plan_digest != push_plan.plan_digest:
            raise _failure(
                "PUSH_PLAN_CHANGED",
                "The reviewed Push Plan digest changed.",
            )
        return existing, False
    if (
        push_plan.status_at_creation != "READY"
        or push_plan.plan_digest != expected_plan_digest
        or push_plan.policy_version != PUSH_DELIVERY_POLICY_VERSION
        or (push_plan.expires_at is not None and utc_now() >= push_plan.expires_at)
    ):
        raise _failure("PUSH_PLAN_EXPIRED", "The exact Push Plan is not approvable.")
    local_commit = session.get(
        LocalCommitExecution, push_plan.local_commit_execution_id
    )
    if local_commit is None or local_commit.owner_id != owner_id:
        raise _failure("PUSH_PLAN_NOT_FOUND", "Push Plan not found.")
    with _push_repository_lock(
        push_plan.repository_locator_fingerprint,
        observation=True,
    ):
        session.expire_all()
        push_plan = session.get(PushPlan, push_plan.id)
        local_commit = session.get(LocalCommitExecution, local_commit.id)
        if (
            push_plan is None
            or local_commit is None
            or push_plan.owner_id != owner_id
            or local_commit.owner_id != owner_id
        ):
            raise _failure("PUSH_PLAN_NOT_FOUND", "Push Plan not found.")
        existing = _approval_for_push_plan(
            session,
            owner_id=owner_id,
            plan_id=push_plan.id,
        )
        if existing is not None:
            if expected_plan_digest != push_plan.plan_digest:
                raise _failure(
                    "PUSH_PLAN_CHANGED",
                    "The reviewed Push Plan digest changed.",
                )
            return existing, False
        if (
            push_plan.status_at_creation != "READY"
            or push_plan.plan_digest != expected_plan_digest
            or push_plan.expires_at is None
            or utc_now() >= push_plan.expires_at
        ):
            raise _failure("PUSH_PLAN_EXPIRED", "The exact Push Plan is not approvable.")
        context = _bound_push_context(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
            source_repo=source_repo,
        )
        proposal, proposal_approval = _bound_commit_proposal(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
        )
        _validate_push_plan_binding(
            push_plan,
            owner_id=owner_id,
            context=context,
            proposal=proposal,
            proposal_approval=proposal_approval,
        )
        observation = _safe_preflight_observation(context)
        blockers = _push_plan_current_blockers(push_plan, observation)
        if blockers:
            raise _failure(
                str(blockers[0]["code"]),
                str(blockers[0]["message"]),
            )
        confirmation_digest = canonical_sha256(
            {
                "schema": "twos.push_plan_owner_approval.v1",
                "owner_id": owner_id,
                "push_plan_id": push_plan.push_plan_id,
                "push_plan_version": push_plan.version,
                "push_plan_digest": push_plan.plan_digest,
                "confirmation": PUSH_PLAN_APPROVAL_CONFIRMATION,
            }
        )
        approval_material = {
            "schema": "twos.push_plan_approval.v1",
            "owner_id": owner_id,
            "push_plan_id": push_plan.push_plan_id,
            "push_plan_version": push_plan.version,
            "push_plan_digest": push_plan.plan_digest,
            "approved_commit_oid": push_plan.approved_commit_oid,
            "expected_remote_oid": push_plan.expected_remote_oid,
            "remote_config_fingerprint": push_plan.remote_config_fingerprint,
            "confirmation_digest": confirmation_digest,
        }
        approval_digest = canonical_sha256(approval_material)
        row = PushPlanApproval(
            approval_id="pushapproval_" + approval_digest[:40],
            owner_id=owner_id,
            push_plan_id=push_plan.id,
            push_plan_public_id=push_plan.push_plan_id,
            push_plan_version=push_plan.version,
            push_plan_digest=push_plan.plan_digest,
            approved_commit_oid=push_plan.approved_commit_oid,
            expected_remote_oid=push_plan.expected_remote_oid,
            remote_config_fingerprint=push_plan.remote_config_fingerprint,
            approved_by_user_id=owner_id,
            approved_at=utc_now(),
            confirmation_digest=confirmation_digest,
            approval_digest=approval_digest,
            state="APPROVED",
        )
        session.add(row)
        session.flush()
        return row, True


def _create_push_execution_for_plan(
    session: Session,
    *,
    context: BoundPushContext,
    plan: PushPlan,
    approval: PushPlanApproval | None,
    already_delivered: bool,
) -> tuple[PushExecution, bool]:
    existing = _execution_for_push_plan(
        session,
        owner_id=plan.owner_id,
        plan_id=plan.id,
    )
    if existing is not None:
        return existing, False
    preflight = _decoded_object(plan.preflight_evidence_json)
    command = _decoded_object(preflight.get("command"))
    command_digest = canonical_sha256(command)
    confirmation_digest = (
        _push_plan_final_confirmation_digest(plan, approval)
        if approval is not None
        else canonical_sha256(
            {
                "schema": "twos.push_already_delivered.v1",
                "push_plan_id": plan.push_plan_id,
                "push_plan_digest": plan.plan_digest,
                "approved_commit_oid": plan.approved_commit_oid,
            }
        )
    )
    row = PushExecution(
        push_execution_id="push_"
        + canonical_sha256(
            {
                "schema": "twos.approved_push_execution.v1",
                "push_plan_digest": plan.plan_digest,
                "push_plan_approval_digest": (
                    approval.approval_digest if approval is not None else None
                ),
                "confirmation_digest": confirmation_digest,
            }
        )[:40],
        owner_id=plan.owner_id,
        push_plan_id=plan.id,
        push_plan_approval_id=approval.id if approval is not None else None,
        local_commit_execution_id=context.local_commit.id,
        stage_execution_id=context.stage.id,
        commit_plan_id=context.plan.id,
        post_apply_verification_id=context.verification.id,
        apply_session_id=context.apply_session.id,
        delivery_candidate_id=context.candidate.id,
        run_id=context.run.id,
        task_id=context.run.task_id,
        push_plan_public_id=plan.push_plan_id,
        push_plan_digest=plan.plan_digest,
        push_plan_approval_public_id=(
            approval.approval_id if approval is not None else ""
        ),
        push_plan_approval_digest=(
            approval.approval_digest if approval is not None else ""
        ),
        local_commit_public_id=context.local_commit.commit_execution_id,
        local_commit_receipt_digest=str(context.local_commit.receipt_digest),
        commit_plan_digest=context.plan.plan_digest,
        stage_digest=str(context.stage.stage_digest),
        verification_digest=context.verification.verification_digest,
        candidate_digest=context.candidate.candidate_digest,
        journal_digest=context.apply_session.journal_digest,
        repository_locator_fingerprint=plan.repository_locator_fingerprint,
        sanitized_repository_identity=plan.sanitized_repository_identity,
        branch=PUSH_BRANCH,
        branch_ref=PUSH_BRANCH_REF,
        remote_name=PUSH_REMOTE,
        destination_ref=PUSH_BRANCH_REF,
        approved_commit_oid=plan.approved_commit_oid,
        expected_parent_oid=plan.expected_parent_oid,
        subject=plan.subject,
        subject_digest=plan.subject_digest,
        remote_fetch_url_digest=plan.remote_fetch_url_digest,
        remote_push_url_digest=plan.remote_push_url_digest,
        remote_config_fingerprint=plan.remote_config_fingerprint,
        observed_remote_base_oid=plan.observed_remote_base_oid,
        preflight_evidence_json=plan.preflight_evidence_json,
        preflight_evidence_digest=plan.preflight_evidence_digest,
        confirmation_digest=confirmation_digest,
        refspec=plan.refspec,
        command_evidence_json=canonical_json(command),
        command_evidence_digest=command_digest,
        state="PUSHED" if already_delivered else "READY_TO_PUSH",
        failure_category="ALREADY_DELIVERED" if already_delivered else "",
        failure_evidence_json="[]",
        finished_at=utc_now() if already_delivered else None,
    )
    if already_delivered:
        reconciliation = {
            "status": "RECONCILED",
            "complete": True,
            "local_head": plan.approved_commit_oid,
            "origin_main_sha": plan.approved_commit_oid,
            "approved_commit_sha": plan.approved_commit_oid,
            "ahead": 0,
            "behind": 0,
            "worktree_clean": preflight.get("worktree_clean"),
            "index_clean": preflight.get("index_clean"),
            "staged_path_count": preflight.get("staged_path_count"),
            "owned_staged_path_count": preflight.get("owned_staged_path_count"),
            "unrelated_change_count": preflight.get("unrelated_change_count"),
            "unrelated_evidence_preserved": True,
            "transport_attempted": False,
            "settlement": "ALREADY_DELIVERED",
            "blockers": [],
        }
        row.post_push_evidence_json = canonical_json(reconciliation)
        row.receipt_digest = _push_receipt_digest(row, reconciliation)
    session.add(row)
    session.flush()
    return row, True


def _validate_push_execution_plan_binding(
    execution: PushExecution,
    *,
    plan: PushPlan,
    approval: PushPlanApproval,
) -> None:
    expected_final_confirmation_digest = _push_plan_final_confirmation_digest(
        plan,
        approval,
    )
    if (
        execution.owner_id != plan.owner_id
        or execution.push_plan_id != plan.id
        or execution.push_plan_approval_id != approval.id
        or execution.push_plan_public_id != plan.push_plan_id
        or execution.push_plan_digest != plan.plan_digest
        or execution.push_plan_approval_public_id != approval.approval_id
        or execution.push_plan_approval_digest != approval.approval_digest
        or execution.local_commit_execution_id != plan.local_commit_execution_id
        or execution.local_commit_public_id != plan.local_commit_public_id
        or execution.local_commit_receipt_digest != plan.local_commit_receipt_digest
        or execution.repository_locator_fingerprint
        != plan.repository_locator_fingerprint
        or execution.approved_commit_oid != plan.approved_commit_oid
        or execution.expected_parent_oid != plan.expected_parent_oid
        or execution.remote_fetch_url_digest != plan.remote_fetch_url_digest
        or execution.remote_push_url_digest != plan.remote_push_url_digest
        or execution.remote_config_fingerprint != plan.remote_config_fingerprint
        or execution.refspec != plan.refspec
        or execution.preflight_evidence_digest != plan.preflight_evidence_digest
        or execution.confirmation_digest != expected_final_confirmation_digest
    ):
        raise _failure(
            "PUSH_BINDING_INVALID",
            "The durable Push execution no longer matches the approved Push Plan.",
        )


def confirm_approved_push_plan(
    session: Session,
    *,
    owner_id: int,
    push_plan: PushPlan,
    approval: PushPlanApproval,
    local_commit: LocalCommitExecution,
    source_repo: Path,
    confirmation: str,
    expected_approval_digest: str,
    request_identity: str | None = None,
) -> tuple[PushExecution, bool]:
    """Confirm one exact approved plan; the bool reports transport attempted."""
    if confirmation != PUSH_CONFIRMATION:
        raise _failure(
            "PUSH_CONFIRMATION_CHANGED",
            "The exact Push confirmation text is required.",
        )
    if (
        push_plan.owner_id != owner_id
        or approval.owner_id != owner_id
        or local_commit.owner_id != owner_id
        or push_plan.local_commit_execution_id != local_commit.id
    ):
        raise _failure("PUSH_PLAN_NOT_FOUND", "Push Plan not found.")
    push_plan_database_id = int(push_plan.id)
    approval_database_id = int(approval.id)
    local_commit_database_id = int(local_commit.id)
    repository_locator_fingerprint = str(
        push_plan.repository_locator_fingerprint
    )
    # The HTTP ownership/binding lookups above establish an implicit SQLAlchemy
    # transaction. End it before waiting for the cross-process repository lock
    # so an admission waiter holds neither a SQLite transaction nor a checked-
    # out connection. Only primitive immutable identities cross this boundary;
    # every bound row is loaded and validated again under the acquired lock.
    session.rollback()
    with _push_repository_lock(
        repository_locator_fingerprint,
        wait_timeout_seconds=PUSH_FINAL_LOCK_WAIT_SECONDS,
    ):
        # Final confirmation uses one lock order everywhere: repository first,
        # then a fresh database transaction. This prevents a concurrent POST
        # from holding SQLite's writer lock while waiting for the repository.
        plan = session.get(PushPlan, push_plan_database_id)
        approval = session.get(PushPlanApproval, approval_database_id)
        local_commit = session.get(
            LocalCommitExecution,
            local_commit_database_id,
        )
        if (
            plan is None
            or approval is None
            or local_commit is None
            or plan.owner_id != owner_id
            or approval.owner_id != owner_id
            or local_commit.owner_id != owner_id
        ):
            raise _failure("PUSH_PLAN_NOT_FOUND", "Push Plan not found.")
        context = _bound_push_context(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
            source_repo=source_repo,
        )
        proposal, proposal_approval = _bound_commit_proposal(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
        )
        _validate_push_plan_binding(
            plan,
            owner_id=owner_id,
            context=context,
            proposal=proposal,
            proposal_approval=proposal_approval,
        )
        _validate_push_plan_approval(
            plan,
            approval,
            owner_id=owner_id,
            expected_approval_digest=expected_approval_digest,
        )
        expected_request_identity = _push_plan_final_confirmation_digest(
            plan,
            approval,
        )
        if (
            request_identity is not None
            and request_identity != expected_request_identity
        ):
            raise _failure(
                "PUSH_REQUEST_IDENTITY_CHANGED",
                "The final Push request identity changed; refresh the approved Plan.",
            )
        existing = _execution_for_push_plan(
            session,
            owner_id=owner_id,
            plan_id=plan.id,
        )
        if existing is not None:
            _validate_push_execution_plan_binding(
                existing,
                plan=plan,
                approval=approval,
            )
            execution = existing
        else:
            if (
                plan.status_at_creation != "READY"
                or plan.expires_at is None
                or utc_now() >= plan.expires_at
            ):
                raise _failure(
                    "PUSH_PLAN_EXPIRED",
                    "The exact approved Push Plan is no longer current.",
                )
            observation = _safe_preflight_observation(context)
            already_delivered = bool(observation.get("already_delivered")) and not list(
                observation.get("blockers") or []
            )
            if not already_delivered:
                # Persist the exact reviewed attempt surface even when current
                # evidence is blocked. The existing final-confirmation path
                # rechecks it and records the blocker without transport.
                execution, _ = _create_push_execution_for_plan(
                    session,
                    context=context,
                    plan=plan,
                    approval=approval,
                    already_delivered=False,
                )
            else:
                execution, _ = _create_push_execution_for_plan(
                    session,
                    context=context,
                    plan=plan,
                    approval=approval,
                    already_delivered=True,
                )
                session.commit()
                return execution, False
        return confirm_push_to_origin_main(
            session,
            owner_id=owner_id,
            push_execution=execution,
            source_repo=source_repo,
            confirmation=confirmation,
            expected_confirmation_digest=execution.confirmation_digest,
            _repository_lock_held=True,
        )


def push_plan_review(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
) -> dict[str, Any]:
    """Return the canonical Owner projection without creating or approving a plan."""
    context = _bound_push_context(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
        source_repo=source_repo,
    )
    proposal, proposal_approval = _bound_commit_proposal(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
    )
    plan = _latest_push_plan(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    approval = (
        _approval_for_push_plan(session, owner_id=owner_id, plan_id=plan.id)
        if plan is not None
        else None
    )
    execution = (
        _execution_for_push_plan(session, owner_id=owner_id, plan_id=plan.id)
        if plan is not None
        else None
    )
    observation: dict[str, Any] | None = None
    blockers: list[dict[str, str]] = []
    reconciliation: dict[str, Any] | None = None
    expired = bool(
        plan is not None
        and plan.status_at_creation == "READY"
        and plan.expires_at is not None
        and utc_now() >= plan.expires_at
    )
    if plan is not None:
        try:
            _validate_push_plan_binding(
                plan,
                owner_id=owner_id,
                context=context,
                proposal=proposal,
                proposal_approval=proposal_approval,
            )
            if approval is not None:
                _validate_push_plan_approval(
                    plan,
                    approval,
                    owner_id=owner_id,
                    expected_approval_digest=approval.approval_digest,
                )
            if execution is not None and approval is not None:
                _validate_push_execution_plan_binding(
                    execution,
                    plan=plan,
                    approval=approval,
                )
        except PushDeliveryError as exc:
            blockers.append(_safe_failure(exc.code, exc.message))
        if expired and execution is None:
            blockers.append(
                _safe_failure(
                    "PUSH_PLAN_EXPIRED",
                    "The Push Plan expired and must be reviewed again.",
                )
            )
        elif plan.status_at_creation == "BLOCKED":
            blockers.extend(
                item
                for item in _decoded_list(plan.blocker_codes_json)
                if isinstance(item, dict)
            )
        elif not blockers:
            try:
                with _push_repository_lock(
                    plan.repository_locator_fingerprint,
                    observation=True,
                ):
                    observation = _safe_preflight_observation(context)
                    if execution is None:
                        blockers.extend(
                            _push_plan_current_blockers(plan, observation)
                        )
                    elif execution.state == "PUSHING":
                        execution = _recover_uncertain_push(
                            session,
                            row=execution,
                            context=context,
                            settle_incomplete=True,
                        )
                        reconciliation = _decoded_object(
                            execution.recovery_reconciliation_json
                            or execution.post_push_evidence_json
                        )
                    elif execution.state == "READY_TO_PUSH":
                        _blocked_state, fresh_blockers = _pre_execution_blockers(
                            execution,
                            observation,
                        )
                        blockers.extend(fresh_blockers)
                    elif execution.state == "RECONCILIATION_BLOCKED":
                        execution = _recover_blocked_reconciliation(
                            session,
                            row=execution,
                            context=context,
                        )
                        reconciliation = (
                            _decoded_object(execution.recovery_reconciliation_json)
                            if execution.state == "PUSHED"
                            else _reconciliation_locked(context, execution)
                        )
                    elif execution.state != "READY_TO_PUSH":
                        reconciliation = _reconciliation_locked(
                            context,
                            execution,
                        )
            except PushDeliveryError as exc:
                if (
                    execution is not None
                    and execution.state == "PUSHING"
                    and exc.code == "REPOSITORY_MUTATION_ACTIVE"
                ):
                    # The accepted Push owns the exclusive repository lock.
                    # Refresh must expose its durable running state rather
                    # than turn expected lock ownership into a false blocker.
                    observation = _decoded_object(plan.preflight_evidence_json)
                else:
                    blockers.append(_safe_failure(exc.code, exc.message))
    plan_output = _push_plan_out(plan, approval, execution)
    readiness_observation = observation or (
        _decoded_object(plan.preflight_evidence_json) if plan is not None else None
    )
    readiness = _readiness_out(
        readiness_observation,
        blockers=blockers,
        fallback_context=context,
    )
    if execution is not None:
        canonical_execution_state = str(
            (_execution_out(execution) or {}).get("canonical_state")
            or execution.state
        )
        action_state = canonical_execution_state
    elif plan is None:
        action_state = "READY_TO_REVIEW_PUSH_PLAN"
    elif plan.status_at_creation == "ALREADY_DELIVERED":
        action_state = "ALREADY_DELIVERED"
    elif expired:
        action_state = "PUSH_PLAN_EXPIRED"
    elif blockers or plan.status_at_creation == "BLOCKED":
        action_state = "PUSH_BLOCKED"
    elif approval is None:
        action_state = "AWAITING_PUSH_APPROVAL"
    else:
        action_state = "READY_TO_CONFIRM_PUSH"
    can_review = bool(
        _pre_effect_execution_allows_plan_renewal(execution, observation)
        or (
            execution is None
            and (
                plan is None
                or expired
                or (
                    approval is None
                    and (
                        plan.status_at_creation == "BLOCKED"
                        or bool(blockers)
                    )
                )
            )
        )
    )
    can_approve = bool(
        plan is not None
        and plan.status_at_creation == "READY"
        and not expired
        and not blockers
        and approval is None
        and execution is None
    )
    can_confirm = bool(
        plan is not None
        and approval is not None
        and not expired
        and not blockers
        and (
            execution is None
            or (
                execution.state == "READY_TO_PUSH"
                and execution.command_attempt_count == 0
            )
        )
    )
    delivery = _delivery_result(
        session,
        context=context,
        push_execution=execution,
        reconciliation=reconciliation,
        readiness_blockers=blockers,
    )
    confirmation = _confirmation_state(
        plan=plan,
        approval=approval,
        execution=execution,
        can_confirm=can_confirm,
        blockers=blockers,
    )
    return {
        "local_commit_execution_id": local_commit.commit_execution_id,
        "action_state": action_state,
        "readiness": readiness,
        "push_plan": plan_output,
        "push_approval": _push_approval_out(approval),
        "push_execution": _execution_out(execution),
        "confirmation": confirmation,
        "delivery_result": delivery,
        "actions": {
            "can_review_push_plan": can_review,
            "can_approve_push_plan": can_approve,
            "can_confirm_push": can_confirm,
            "can_view_delivery_result": bool(
                execution is not None and execution.state in _TERMINAL_STATES
            ),
        },
    }


def push_delivery_review(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
) -> dict[str, Any]:
    if local_commit.commit_proposal_id is not None:
        return push_plan_review(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
            source_repo=source_repo,
        )
    context = _bound_push_context(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
        source_repo=source_repo,
    )
    latest = _latest_push_execution(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    successful = _successful_push_execution(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    observation: dict[str, Any] | None = None
    blockers: list[dict[str, Any]] = []
    reconciliation: dict[str, Any] | None = None
    try:
        with _push_repository_lock(
            local_commit.repository_locator_fingerprint,
            observation=True,
        ):
            if latest is not None and latest.state != "READY_TO_PUSH":
                reconciliation = _reconciliation_locked(context, latest)
            if successful is None:
                observation = _safe_preflight_observation(context)
                blockers = list(observation.get("blockers") or [])
    except PushDeliveryError as exc:
        if (
            latest is not None
            and latest.state == "PUSHING"
            and exc.code == "REPOSITORY_MUTATION_ACTIVE"
        ):
            observation = _decoded_object(latest.preflight_evidence_json)
        else:
            blockers = [_safe_failure(exc.code, exc.message)]
    active = latest is not None and latest.state in {
        "READY_TO_PUSH",
        "PUSHING",
        "RECONCILIATION_BLOCKED",
    }
    fresh_confirmation_ready = False
    if (
        latest is not None
        and latest.state == "READY_TO_PUSH"
        and latest.command_attempt_count == 0
        and observation is not None
        and not blockers
    ):
        fresh_state, fresh_blockers = _pre_execution_blockers(
            latest,
            observation,
        )
        if fresh_state is None:
            fresh_confirmation_ready = True
        else:
            blockers.extend(fresh_blockers)
    readiness = _readiness_out(
        observation,
        blockers=blockers,
        fallback_context=context,
    )
    if successful is not None:
        action_state = (
            "PUSHED"
            if reconciliation and reconciliation.get("complete") is True
            else "RECONCILIATION_BLOCKED"
        )
    elif latest is not None and latest.state == "READY_TO_PUSH" and blockers:
        action_state = (
            "REMOTE_MOVED"
            if any(item.get("code") == "REMOTE_MOVED" for item in blockers)
            else "PUSH_BLOCKED"
        )
    elif active:
        action_state = latest.state
    elif latest is not None and latest.state in _TERMINAL_STATES:
        action_state = latest.state
    else:
        action_state = "READY_TO_PUSH" if not blockers else "PUSH_BLOCKED"
    can_push = bool(
        successful is None
        and observation is not None
        and not blockers
        and (
            not active
            or (
                latest is not None
                and latest.state in {"PUSHING", "RECONCILIATION_BLOCKED"}
                and latest.command_attempt_count == 1
            )
        )
    )
    can_confirm = bool(
        latest is not None
        and (
            (
                latest.state == "READY_TO_PUSH"
                and latest.command_attempt_count == 0
                and fresh_confirmation_ready
            )
            or (
                latest.state in {"PUSHING", "RECONCILIATION_BLOCKED"}
                and latest.command_attempt_count == 1
            )
        )
    )
    delivery = _delivery_result(
        session,
        context=context,
        push_execution=successful or latest,
        reconciliation=reconciliation,
        readiness_blockers=blockers,
    )
    confirmation = _confirmation_state(
        plan=None,
        approval=None,
        execution=successful or latest,
        can_confirm=can_confirm,
        blockers=blockers,
    )
    return {
        "local_commit_execution_id": local_commit.commit_execution_id,
        "action_state": action_state,
        "readiness": readiness,
        "push_execution": _execution_out(successful or latest),
        "confirmation": confirmation,
        "delivery_result": delivery,
        "actions": {
            "can_push_to_origin_main": can_push,
            "can_confirm_push": can_confirm,
            "can_view_delivery_result": bool(
                (successful or latest) is not None
                and (successful or latest).state in _TERMINAL_STATES
            ),
        },
    }


def create_push_preflight(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
) -> tuple[PushExecution, bool]:
    if local_commit.commit_proposal_id is not None:
        raise _failure(
            "PUSH_PLAN_REQUIRED",
            "Review and separately approve an immutable Push Plan first.",
        )
    existing_success = _successful_push_execution(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    if existing_success is not None:
        return existing_success, False
    active = _active_push_execution(
        session,
        owner_id=owner_id,
        local_commit_id=local_commit.id,
    )
    if active is not None:
        return active, False
    context = _bound_push_context(
        session,
        owner_id=owner_id,
        local_commit=local_commit,
        source_repo=source_repo,
    )
    with _push_repository_lock(
        local_commit.repository_locator_fingerprint,
        observation=True,
    ):
        session.expire_all()
        local_commit = session.get(LocalCommitExecution, local_commit.id)
        if local_commit is None or local_commit.owner_id != owner_id:
            raise _failure("LOCAL_COMMIT_NOT_FOUND", "Local Commit result not found.")
        existing_success = _successful_push_execution(
            session,
            owner_id=owner_id,
            local_commit_id=local_commit.id,
        )
        if existing_success is not None:
            return existing_success, False
        active = _active_push_execution(
            session,
            owner_id=owner_id,
            local_commit_id=local_commit.id,
        )
        if active is not None:
            return active, False
        context = _bound_push_context(
            session,
            owner_id=owner_id,
            local_commit=local_commit,
            source_repo=source_repo,
        )
        observation = _safe_preflight_observation(context)
        blockers = list(observation.get("blockers") or [])
        already_delivered = bool(observation.get("already_delivered")) and not blockers
        state = "PUSHED" if already_delivered else "READY_TO_PUSH"
        if blockers:
            state = (
                "REMOTE_MOVED"
                if any(item.get("code") == "REMOTE_MOVED" for item in blockers)
                else "PUSH_BLOCKED"
            )
        preflight_material = {
            **observation,
            "policy_version": PUSH_DELIVERY_POLICY_VERSION,
            "owner_id": owner_id,
            "local_commit_execution_id": local_commit.commit_execution_id,
            "local_commit_receipt_digest": local_commit.receipt_digest,
            "attempt_nonce": secrets.token_hex(16),
        }
        preflight_digest = canonical_sha256(preflight_material)
        command = _decoded_object(observation.get("command"))
        command_digest = canonical_sha256(command)
        confirmation_digest = canonical_sha256(
            {
                "schema": "twos.push_confirmation.v1",
                "preflight_evidence_digest": preflight_digest,
                "command_evidence_digest": command_digest,
                "observed_remote_base_oid": observation.get(
                    "observed_remote_base_sha"
                ),
            }
        )
        row = PushExecution(
            push_execution_id="push_" + confirmation_digest[:40],
            owner_id=owner_id,
            local_commit_execution_id=local_commit.id,
            stage_execution_id=context.stage.id,
            commit_plan_id=context.plan.id,
            post_apply_verification_id=context.verification.id,
            apply_session_id=context.apply_session.id,
            delivery_candidate_id=context.candidate.id,
            run_id=context.run.id,
            task_id=context.run.task_id,
            local_commit_public_id=local_commit.commit_execution_id,
            local_commit_receipt_digest=str(local_commit.receipt_digest),
            commit_plan_digest=context.plan.plan_digest,
            stage_digest=str(context.stage.stage_digest),
            verification_digest=context.verification.verification_digest,
            candidate_digest=context.candidate.candidate_digest,
            journal_digest=context.apply_session.journal_digest,
            repository_locator_fingerprint=context.plan.repository_locator_fingerprint,
            sanitized_repository_identity=context.plan.sanitized_repository_identity,
            branch=PUSH_BRANCH,
            branch_ref=PUSH_BRANCH_REF,
            remote_name=PUSH_REMOTE,
            destination_ref=PUSH_BRANCH_REF,
            approved_commit_oid=str(local_commit.commit_oid),
            expected_parent_oid=str(local_commit.parent_oid),
            subject=context.plan.subject,
            subject_digest=_sha256_bytes(context.plan.subject.encode("utf-8")),
            remote_fetch_url_digest=str(
                observation.get("remote_fetch_url_digest") or ""
            ),
            remote_push_url_digest=str(
                observation.get("remote_push_url_digest") or ""
            ),
            remote_config_fingerprint=str(
                observation.get("remote_config_fingerprint") or ""
            ),
            observed_remote_base_oid=str(
                observation.get("observed_remote_base_sha") or ""
            ),
            preflight_evidence_json=canonical_json(preflight_material),
            preflight_evidence_digest=preflight_digest,
            confirmation_digest=confirmation_digest,
            refspec=str(command.get("refspec") or ""),
            command_evidence_json=canonical_json(command),
            command_evidence_digest=command_digest,
            state=state,
            failure_category=(
                str(blockers[0].get("code"))
                if blockers
                else "ALREADY_DELIVERED"
                if already_delivered
                else ""
            ),
            failure_evidence_json=canonical_json(blockers),
            finished_at=utc_now() if blockers or already_delivered else None,
        )
        session.add(row)
        if already_delivered:
            reconciliation = {
                "status": "RECONCILED",
                "complete": True,
                "local_head": local_commit.commit_oid,
                "origin_main_sha": local_commit.commit_oid,
                "approved_commit_sha": local_commit.commit_oid,
                "ahead": 0,
                "behind": 0,
                "worktree_clean": observation.get("worktree_clean"),
                "index_clean": observation.get("index_clean"),
                "staged_path_count": observation.get("staged_path_count"),
                "owned_staged_path_count": observation.get(
                    "owned_staged_path_count"
                ),
                "unrelated_change_count": observation.get(
                    "unrelated_change_count"
                ),
                "unrelated_evidence_preserved": True,
                "blockers": [],
            }
            row.post_push_evidence_json = canonical_json(reconciliation)
            row.receipt_digest = _push_receipt_digest(row, reconciliation)
        session.flush()
        return row, True


def _pre_execution_blockers(
    row: PushExecution,
    observation: dict[str, Any],
) -> tuple[str | None, list[dict[str, str]]]:
    blockers = [
        item
        for item in observation.get("blockers", [])
        if isinstance(item, dict)
    ]
    preflight = _decoded_object(row.preflight_evidence_json)
    if observation.get("local_commit_sha") != row.approved_commit_oid:
        blockers.append(_safe_failure("HEAD_CHANGED", "Local HEAD changed."))
    if observation.get("remote_fetch_url_digest") != row.remote_fetch_url_digest or observation.get(
        "remote_push_url_digest"
    ) != row.remote_push_url_digest:
        blockers.append(_safe_failure("REMOTE_URL_CHANGED", "The origin URL changed."))
    if observation.get("remote_config_fingerprint") != row.remote_config_fingerprint:
        blockers.append(
            _safe_failure("REMOTE_URL_CHANGED", "The origin configuration changed.")
        )
    for key, code, message in (
        (
            "worktree_status_digest",
            "WORKTREE_CHANGED",
            "Unrelated working-tree evidence changed after Push review.",
        ),
        (
            "index_semantic_digest",
            "INDEX_CHANGED",
            "The Git index changed after Push review.",
        ),
        (
            "unrelated_worktree_fingerprint",
            "WORKTREE_CHANGED",
            "Unrelated file content changed after Push review.",
        ),
        (
            "unrelated_source_digest",
            "WORKTREE_CHANGED",
            "Unrelated source evidence changed after Push review.",
        ),
        (
            "remote_descriptor_identity",
            "REMOTE_URL_CHANGED",
            "The origin destination identity changed after Push review.",
        ),
        (
            "remote_credential_helper_fingerprint",
            "REMOTE_CONFIG_CHANGED",
            "The credential-helper boundary changed after Push review.",
        ),
    ):
        if observation.get(key) != preflight.get(key):
            blockers.append(_safe_failure(code, message))
    if observation.get("delivery_refs_fingerprint") != preflight.get(
        "delivery_refs_fingerprint"
    ) or observation.get("origin_main_tracking_oid") != preflight.get(
        "origin_main_tracking_oid"
    ) or observation.get("origin_head_target") != preflight.get(
        "origin_head_target"
    ):
        blockers.append(
            _safe_failure(
                "REFS_CHANGED",
                "Local tags or non-main refs changed after Push confirmation review.",
            )
        )
    if blockers:
        state = (
            "REMOTE_MOVED"
            if any(item.get("code") == "REMOTE_MOVED" for item in blockers)
            else "PUSH_BLOCKED"
        )
        return state, blockers
    if observation.get("observed_remote_base_sha") != row.observed_remote_base_oid:
        return (
            "REMOTE_MOVED",
            [
                _safe_failure(
                    "REMOTE_MOVED",
                    "Live origin/main changed after confirmation review. No Push occurred.",
                )
            ],
        )
    return None, []


def _classify_push_failure(result: subprocess.CompletedProcess[bytes]) -> str:
    material = (result.stderr + b"\n" + result.stdout).lower()
    if b"non-fast-forward" in material or b"fetch first" in material:
        return "REMOTE_REJECTED_NON_FAST_FORWARD"
    if b"authentication" in material or b"publickey" in material or b"permission denied" in material:
        return "AUTHENTICATION_FAILED"
    if b"could not resolve" in material or b"unable to access" in material:
        return "REMOTE_UNAVAILABLE"
    if b"rejected" in material or b"remote rejected" in material:
        return "REMOTE_REJECTED"
    return "PUSH_COMMAND_FAILED"


def _run_standard_push(root: Path, refspec: str) -> subprocess.CompletedProcess[bytes]:
    if not re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64}):refs/heads/main",
        refspec,
    ):
        raise _failure("PUSH_COMMAND_BLOCKED", "The exact Push refspec is invalid.")
    return _run_transport(
        root,
        "push",
        "--porcelain",
        "--no-follow-tags",
        "--recurse-submodules=no",
        "--",
        PUSH_REMOTE,
        refspec,
        timeout=120,
    )


def _push_receipt_digest(
    row: PushExecution,
    reconciliation: dict[str, Any],
) -> str:
    return canonical_sha256(
        {
            "schema": "twos.push_receipt.v1",
            "push_execution_id": row.push_execution_id,
            "confirmation_digest": row.confirmation_digest,
            "command_evidence_digest": row.command_evidence_digest,
            "approved_commit_oid": row.approved_commit_oid,
            "expected_parent_oid": row.expected_parent_oid,
            "execution_remote_base_oid": row.execution_remote_base_oid,
            "destination_ref": row.destination_ref,
            "post_push": reconciliation,
        }
    )


def _recover_uncertain_push(
    session: Session,
    *,
    row: PushExecution,
    context: BoundPushContext,
    settle_incomplete: bool = False,
) -> PushExecution:
    """Reconcile a durable one-shot attempt without invoking transport again."""
    reconciliation = _reconciliation_locked(context, row)
    if reconciliation.get("complete") is not True:
        if not settle_incomplete:
            return row
        blockers = list(reconciliation.get("blockers") or []) or [
            _safe_failure(
                "REMOTE_EFFECT_UNCONFIRMED",
                "The interrupted Push could not be verified at origin/main.",
            )
        ]
        remote_oid = reconciliation.get("origin_main_sha")
        row.state = (
            "REMOTE_MOVED"
            if remote_oid
            not in {None, row.execution_remote_base_oid, row.approved_commit_oid}
            else "RECONCILIATION_BLOCKED"
        )
        row.failure_category = str(
            blockers[0].get("code") or "REMOTE_EFFECT_UNCONFIRMED"
        )
        row.failure_evidence_json = canonical_json(blockers)
        row.post_push_evidence_json = canonical_json(reconciliation)
        row.finished_at = utc_now()
        session.add(
            AuditEvent(
                actor_user_id=row.owner_id,
                action="push_execution_recovery_needs_review",
                entity_type="push_execution",
                entity_id=row.id,
                details=(
                    f"execution={row.push_execution_id}; prior_state=PUSHING; "
                    f"state={row.state}; remote_effect=unconfirmed; "
                    "transport_retried=false"
                ),
            )
        )
        session.commit()
        return row
    recovery_json = canonical_json(reconciliation)
    row.recovery_reconciliation_json = recovery_json
    row.recovery_reconciliation_digest = canonical_sha256(reconciliation)
    row.recovered_at = utc_now()
    row.command_finished_at = utc_now()
    row.post_push_evidence_json = recovery_json
    row.finished_at = utc_now()
    row.state = "PUSHED"
    row.receipt_digest = _push_receipt_digest(row, reconciliation)
    session.add(
        AuditEvent(
            actor_user_id=row.owner_id,
            action="push_execution_recovered_delivered",
            entity_type="push_execution",
            entity_id=row.id,
            details=(
                f"execution={row.push_execution_id}; prior_state=PUSHING; "
                "state=PUSHED; remote_effect=verified; transport_retried=false"
            ),
        )
    )
    session.commit()
    return row


def _recover_blocked_reconciliation(
    session: Session,
    *,
    row: PushExecution,
    context: BoundPushContext,
) -> PushExecution:
    reconciliation = _reconciliation_locked(context, row)
    if reconciliation.get("complete") is not True:
        return row
    recovery_json = canonical_json(reconciliation)
    row.recovery_reconciliation_json = recovery_json
    row.recovery_reconciliation_digest = canonical_sha256(reconciliation)
    row.recovered_at = utc_now()
    if row.command_finished_at is None:
        row.command_finished_at = utc_now()
    if row.finished_at is None:
        row.finished_at = utc_now()
    row.state = "PUSHED"
    row.receipt_digest = _push_receipt_digest(row, reconciliation)
    session.add(
        AuditEvent(
            actor_user_id=row.owner_id,
            action="push_execution_recovered_delivered",
            entity_type="push_execution",
            entity_id=row.id,
            details=(
                f"execution={row.push_execution_id}; "
                "prior_state=RECONCILIATION_BLOCKED; state=PUSHED; "
                "remote_effect=verified; transport_retried=false"
            ),
        )
    )
    session.commit()
    return row


def confirm_push_to_origin_main(
    session: Session,
    *,
    owner_id: int,
    push_execution: PushExecution,
    source_repo: Path,
    confirmation: str,
    expected_confirmation_digest: str,
    _repository_lock_held: bool = False,
) -> tuple[PushExecution, bool]:
    if push_execution.owner_id != owner_id:
        raise _failure("PUSH_NOT_FOUND", "Push workflow not found.")
    if push_execution.state == "PUSHED":
        return push_execution, False
    if (
        push_execution.state in _TERMINAL_STATES
        and push_execution.state != "RECONCILIATION_BLOCKED"
    ):
        return push_execution, False
    if (
        confirmation != PUSH_CONFIRMATION
        or expected_confirmation_digest != push_execution.confirmation_digest
    ):
        raise _failure(
            "PUSH_CONFIRMATION_CHANGED",
            "The reviewed Push confirmation binding changed.",
        )
    if (
        push_execution.state == "READY_TO_PUSH"
        and push_execution.command_attempt_count != 0
    ) or (
        push_execution.state in {"PUSHING", "RECONCILIATION_BLOCKED"}
        and push_execution.command_attempt_count != 1
    ) or push_execution.state not in {
        "READY_TO_PUSH",
        "PUSHING",
        "RECONCILIATION_BLOCKED",
    }:
        raise _failure(
            "PUSH_ATTEMPT_ALREADY_USED",
            "This Push confirmation has already been used.",
        )
    local_commit = session.get(
        LocalCommitExecution, push_execution.local_commit_execution_id
    )
    if local_commit is None or local_commit.owner_id != owner_id:
        raise _failure("PUSH_NOT_FOUND", "Push workflow not found.")
    if (
        local_commit.commit_proposal_id is not None
        and (
            push_execution.push_plan_id is None
            or push_execution.push_plan_approval_id is None
        )
    ):
        raise _failure(
            "PUSH_APPROVAL_REQUIRED",
            "The canonical Owner Push requires an exact approved Push Plan.",
        )
    repository_lock = (
        nullcontext()
        if _repository_lock_held
        # The legacy preflight endpoint enters here with SQLite's historical
        # BEGIN IMMEDIATE admission already active. It must never wait for the
        # repository lock while retaining that database-writer boundary. The
        # canonical approved-Plan path acquires its bounded repository-first
        # lock in confirm_approved_push_plan and passes _repository_lock_held.
        else _push_repository_lock(
            push_execution.repository_locator_fingerprint,
        )
    )
    with repository_lock:
        session.expire_all()
        row = session.get(PushExecution, push_execution.id)
        local_commit = session.get(LocalCommitExecution, local_commit.id)
        if row is None or local_commit is None or row.owner_id != owner_id or local_commit.owner_id != owner_id:
            raise _failure("PUSH_NOT_FOUND", "Push workflow not found.")
        if row.state == "PUSHED":
            return row, False
        if row.state in _TERMINAL_STATES and row.state != "RECONCILIATION_BLOCKED":
            return row, False
        if (
            row.state == "READY_TO_PUSH" and row.command_attempt_count != 0
        ) or (
            row.state in {"PUSHING", "RECONCILIATION_BLOCKED"}
            and row.command_attempt_count != 1
        ) or row.state not in {
            "READY_TO_PUSH",
            "PUSHING",
            "RECONCILIATION_BLOCKED",
        }:
            raise _failure(
                "PUSH_ATTEMPT_ALREADY_USED",
                "This Push confirmation has already been used.",
            )
        try:
            context = _bound_push_context(
                session,
                owner_id=owner_id,
                local_commit=local_commit,
                source_repo=source_repo,
            )
        except PushDeliveryError:
            if row.state in {"PUSHING", "RECONCILIATION_BLOCKED"}:
                return row, False
            raise
        if (
            row.local_commit_public_id != local_commit.commit_execution_id
            or row.local_commit_receipt_digest != local_commit.receipt_digest
            or row.commit_plan_digest != context.plan.plan_digest
            or row.stage_digest != context.stage.stage_digest
            or row.verification_digest != context.verification.verification_digest
            or row.candidate_digest != context.candidate.candidate_digest
            or row.journal_digest != context.apply_session.journal_digest
            or row.approved_commit_oid != local_commit.commit_oid
            or row.expected_parent_oid != local_commit.parent_oid
            or row.refspec != f"{local_commit.commit_oid}:{PUSH_BRANCH_REF}"
            or canonical_sha256(_decoded_object(row.preflight_evidence_json))
            != row.preflight_evidence_digest
            or canonical_sha256(_decoded_object(row.command_evidence_json))
            != row.command_evidence_digest
        ):
            raise _failure(
                "PUSH_BINDING_INVALID",
                "The durable Push confirmation binding is invalid.",
            )
        if row.state == "PUSHING":
            return _recover_uncertain_push(
                session,
                row=row,
                context=context,
            ), False
        if row.state == "RECONCILIATION_BLOCKED":
            return _recover_blocked_reconciliation(
                session,
                row=row,
                context=context,
            ), False
        observation = _safe_preflight_observation(context)
        blocked_state, blockers = _pre_execution_blockers(row, observation)
        if blocked_state is not None:
            row.state = blocked_state
            row.failure_category = str(blockers[0].get("code") or blocked_state)
            row.failure_evidence_json = canonical_json(blockers)
            row.finished_at = utc_now()
            session.commit()
            return row, False
        row.state = "PUSHING"
        row.command_attempt_count = 1
        row.command_started_at = utc_now()
        row.execution_remote_base_oid = str(
            observation.get("observed_remote_base_sha") or ""
        )
        session.commit()
        result: subprocess.CompletedProcess[bytes] | None = None
        transport_error: PushDeliveryError | None = None
        try:
            result = _run_standard_push(context.root, row.refspec)
        except PushDeliveryError as exc:
            transport_error = exc
        reconciliation = _reconciliation_locked(context, row)
        row = session.get(PushExecution, row.id) or row
        if row.state != "PUSHING" or row.command_attempt_count != 1:
            raise _failure(
                "PUSH_BINDING_INVALID",
                "The durable Push execution changed during the attempt.",
            )
        command_output = _transport_output_evidence(
            root=context.root,
            result=result,
            error=transport_error,
        )
        terminal_state: str | None = None
        if reconciliation.get("complete") is True:
            terminal_state = "PUSHED"
            if result is not None and result.returncode != 0:
                row.failure_category = "PUSH_EXIT_NONZERO_RECONCILED"
                row.failure_evidence_json = canonical_json(
                    [
                        _safe_failure(
                            "PUSH_EXIT_NONZERO_RECONCILED",
                            "The Push command returned nonzero but final delivery reconciled exactly.",
                        )
                    ]
                )
        elif reconciliation.get("origin_main_sha") not in {
            None,
            row.execution_remote_base_oid,
            row.approved_commit_oid,
        }:
            terminal_state = "REMOTE_MOVED"
            row.failure_category = "REMOTE_MOVED"
            row.failure_evidence_json = canonical_json(
                [
                    _safe_failure(
                        "REMOTE_MOVED",
                        "Live origin/main moved during the standard Push attempt; no force was used.",
                    )
                ]
            )
        elif reconciliation.get("origin_main_sha") is None and (
            result is not None
            or (transport_error is not None and transport_error.timed_out)
        ):
            terminal_state = "RECONCILIATION_BLOCKED"
            row.failure_category = "REMOTE_EFFECT_UNCONFIRMED"
            row.failure_evidence_json = canonical_json(
                list(reconciliation.get("blockers") or [])
                or [
                    _safe_failure(
                        "REMOTE_EFFECT_UNCONFIRMED",
                        "The Push process ended without exact remote-SHA evidence; automatic retry is blocked.",
                    )
                ]
            )
        elif result is not None and result.returncode == 0:
            # Process exit zero is not remote-delivery truth. Preserve the
            # single attempt as Needs Review until read-only remote evidence
            # proves the exact approved SHA at the exact destination ref.
            terminal_state = "RECONCILIATION_BLOCKED"
            row.failure_category = "REMOTE_VERIFICATION_UNAVAILABLE"
            row.failure_evidence_json = canonical_json(
                list(reconciliation.get("blockers") or [])
                or [
                    _safe_failure(
                        "REMOTE_VERIFICATION_UNAVAILABLE",
                        "The Push process exited successfully, but the exact remote SHA is not yet verified.",
                    )
                ]
            )
        elif transport_error is not None:
            terminal_state = "PUSH_FAILED"
            row.failure_category = transport_error.code
            row.failure_evidence_json = canonical_json(
                [_safe_failure(transport_error.code, transport_error.message)]
            )
        elif result is not None and result.returncode != 0:
            category = _classify_push_failure(result)
            terminal_state = "PUSH_FAILED"
            row.failure_category = category
            row.failure_evidence_json = canonical_json(
                [
                    _safe_failure(
                        category,
                        "The standard Push failed. No automatic retry occurred.",
                    )
                ]
            )
        if terminal_state is None:
            # An unclassified transport outcome retains one-shot uncertainty.
            # Only a future explicit confirmation may reconcile it, and that
            # recovery path never invokes transport again.
            return row, True
        row.command_finished_at = utc_now()
        row.command_exit_code = result.returncode if result is not None else None
        row.command_output_json = canonical_json(command_output)
        row.post_push_evidence_json = canonical_json(reconciliation)
        row.finished_at = utc_now()
        row.state = terminal_state
        if terminal_state == "PUSHED":
            row.receipt_digest = _push_receipt_digest(row, reconciliation)
        session.commit()
        return row, True
