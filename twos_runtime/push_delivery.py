from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .apply_sessions import apply_session_out
from .commit_builder import (
    COMMIT_BUILDER_POLICY_VERSION,
    CommitBuilderError,
    _bound_verification,
    _commit_builder_repository_lock,
    _commit_message,
    _commit_object,
    _commit_out,
    _decoded_list,
    _decoded_object,
    _git_environment,
    _git_text,
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
    CodexResultEnvelope,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    PostApplyVerification,
    PushExecution,
    SourceDriftEvaluation,
    StageExecution,
    utc_now,
)
from .post_apply_verifications import post_apply_verification_out
from .result_intake import result_envelope_out
from .self_hosting import _source_repository_identity
from .apply_sessions import _global_evidence_after_mutation


PUSH_DELIVERY_POLICY_VERSION = "twos.push_delivery.vol18.009.v1"
PUSH_CONFIRMATION = "PUSH_TO_ORIGIN_MAIN"
PUSH_REMOTE = "origin"
PUSH_BRANCH = "main"
PUSH_BRANCH_REF = "refs/heads/main"
PUSH_TRACKING_REF = "refs/remotes/origin/main"
PUSH_TRACKING_HEAD_REF = "refs/remotes/origin/HEAD"
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
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
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
def _push_repository_lock(repository_locator_fingerprint: str):
    try:
        with _commit_builder_repository_lock(repository_locator_fingerprint):
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
    if (
        stage is None
        or plan is None
        or stage.owner_id != owner_id
        or plan.owner_id != owner_id
        or stage.id != local_commit.stage_execution_id
        or stage.commit_plan_id != plan.id
        or local_commit.commit_plan_id != plan.id
        or stage.state != "STAGED"
        or plan.status_at_creation != "READY"
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
    expected_repository_identity = str(
        _decoded_object(pack.source_snapshot_json).get(
            "source_repository_identity"
        )
        or ""
    )
    try:
        observed_repository_identity = _source_repository_identity(
            root,
            hardened_read_only=True,
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
    if (
        commit["parents"] != [plan.base_head]
        or commit["message"] != _commit_message(plan)
        or commit["message_digest"] != local_commit.message_digest
        or commit["tree"] != local_commit.tree_oid
        or _post_commit_paths(root, plan.base_head, local_commit.commit_oid)
        != expected_paths
        or canonical_sha256(receipt) != local_commit.receipt_digest
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
        *args,
    ]


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
            env=_git_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _failure(
            "REMOTE_TIMEOUT",
            "The remote Git operation timed out.",
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
    fetch_url = _one_remote_url(context.root, push=False)
    push_url = _one_remote_url(context.root, push=True)
    fetch_url_digest = _sha256_bytes(fetch_url)
    push_url_digest = _sha256_bytes(push_url)
    if fetch_url_digest != push_url_digest:
        raise _failure(
            "REMOTE_DESTINATION_MISMATCH",
            "origin fetch and Push destinations do not match exactly.",
        )
    return {
        "fetch_url_digest": fetch_url_digest,
        "push_url_digest": push_url_digest,
        "display": _safe_remote_display(push_url),
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
    if not local["worktree_clean"]:
        blockers.append(_safe_failure("WORKTREE_DIRTY", "The working tree is not clean."))
    if not local["index_clean"] or local["staged_path_count"] != 0:
        blockers.append(_safe_failure("INDEX_DIRTY", "The Git index is not clean."))
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
    if live_remote is not None and live_remote != context.local_commit.parent_oid:
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
        "ahead": 1 if live_remote == context.local_commit.parent_oid else None,
        "behind": 0 if live_remote == context.local_commit.parent_oid else None,
        "worktree_clean": local["worktree_clean"],
        "index_clean": local["index_clean"],
        "staged_path_count": local["staged_path_count"],
        "remote_fetch_url_digest": remote["fetch_url_digest"],
        "remote_push_url_digest": remote["push_url_digest"],
        "remote_display": remote["display"],
        "remote_config_fingerprint": local["remote_config_fingerprint"],
        "delivery_refs_fingerprint": local["delivery_refs_fingerprint"],
        "origin_main_tracking_oid": local["origin_main_tracking_oid"],
        "origin_head_target": local["origin_head_target"],
        "other_ref_count": local["other_ref_count"],
        "command": command,
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
    return {
        "id": row.push_execution_id,
        "state": row.state,
        "status": row.state,
        "status_label": _status_label(row.state),
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
            "failure_category": row.failure_category or None,
            "command_exit_code": row.command_exit_code,
        },
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
    if local["head"] != row.approved_commit_oid:
        blockers.append(_safe_failure("HEAD_CHANGED", "Local HEAD changed."))
    if local["branch_ref"] != PUSH_BRANCH_REF:
        blockers.append(_safe_failure("WRONG_BRANCH", "The current branch is not main."))
    if not local["worktree_clean"]:
        blockers.append(_safe_failure("WORKTREE_DIRTY", "The working tree is not clean."))
    if not local["index_clean"] or local["staged_path_count"] != 0:
        blockers.append(_safe_failure("INDEX_DIRTY", "The Git index is not clean."))
    if remote["fetch_url_digest"] != row.remote_fetch_url_digest or remote[
        "push_url_digest"
    ] != row.remote_push_url_digest:
        blockers.append(_safe_failure("REMOTE_URL_CHANGED", "The origin URL changed."))
    if local["remote_config_fingerprint"] != row.remote_config_fingerprint:
        blockers.append(
            _safe_failure("REMOTE_URL_CHANGED", "The origin configuration changed.")
        )
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


def push_delivery_review(
    session: Session,
    *,
    owner_id: int,
    local_commit: LocalCommitExecution,
    source_repo: Path,
) -> dict[str, Any]:
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
    with _push_repository_lock(local_commit.repository_locator_fingerprint):
        if latest is not None and latest.state != "READY_TO_PUSH":
            reconciliation = _reconciliation_locked(context, latest)
        if successful is None:
            try:
                observation = _safe_preflight_observation(context)
                blockers = list(observation.get("blockers") or [])
            except PushDeliveryError as exc:
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
    return {
        "local_commit_execution_id": local_commit.commit_execution_id,
        "action_state": action_state,
        "readiness": readiness,
        "push_execution": _execution_out(successful or latest),
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
    with _push_repository_lock(local_commit.repository_locator_fingerprint):
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
        state = "READY_TO_PUSH"
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
            failure_category=(str(blockers[0].get("code")) if blockers else ""),
            failure_evidence_json=canonical_json(blockers),
            finished_at=utc_now() if blockers else None,
        )
        session.add(row)
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
) -> PushExecution:
    """Reconcile a durable one-shot attempt without invoking transport again."""
    reconciliation = _reconciliation_locked(context, row)
    if reconciliation.get("complete") is not True:
        # Preserve PUSHING as the durable uncertainty state. A later explicit
        # confirmation may reconcile again, but never invokes Push transport.
        return row
    row.command_finished_at = utc_now()
    row.post_push_evidence_json = canonical_json(reconciliation)
    row.finished_at = utc_now()
    row.state = "PUSHED"
    row.receipt_digest = _push_receipt_digest(row, reconciliation)
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
    row.state = "PUSHED"
    row.receipt_digest = _push_receipt_digest(row, reconciliation)
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
    with _push_repository_lock(
        push_execution.repository_locator_fingerprint
    ):
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
        elif result is not None and result.returncode == 0:
            # The exact standard Push process completed successfully. Persist
            # that immutable Push receipt even if a subsequent read-only live
            # reconciliation is temporarily unavailable; Delivery completion
            # remains false until a GET observes exact local/remote equality.
            terminal_state = "PUSHED"
            row.failure_category = "RECONCILIATION_PENDING"
            row.failure_evidence_json = canonical_json(
                list(reconciliation.get("blockers") or [])
                or [
                    _safe_failure(
                        "RECONCILIATION_PENDING",
                        "The standard Push succeeded; live delivery reconciliation is pending.",
                    )
                ]
            )
        elif transport_error is not None:
            if transport_error.code != "REMOTE_TIMEOUT":
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
            # Timeout/unknown transport remains a durable one-shot uncertainty.
            # Only a future explicit confirmation may reconcile it, and that
            # recovery path never invokes transport again.
            return row, True
        row.command_finished_at = utc_now()
        row.command_exit_code = result.returncode if result is not None else None
        row.post_push_evidence_json = canonical_json(reconciliation)
        row.finished_at = utc_now()
        row.state = terminal_state
        if terminal_state == "PUSHED":
            row.receipt_digest = _push_receipt_digest(row, reconciliation)
        session.commit()
        return row, True
