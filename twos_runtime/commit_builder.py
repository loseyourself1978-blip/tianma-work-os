from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .apply_sessions import (
    ApplySessionError,
    _global_evidence_after_mutation,
    _repository_mutation_blocker,
    _repository_mutation_lock,
    _repository_observation_lock,
    _verified_repository_root,
    apply_session_entries,
    validate_apply_session_journal,
)
from .delivery_candidates import canonical_json, canonical_sha256, normalize_repository_path
from .models import (
    ApplySession,
    CommitPlan,
    LocalCommitExecution,
    PostApplyVerification,
    StageExecution,
    utc_now,
)
from .post_apply_verifications import (
    POST_APPLY_VERIFICATION_POLICY_VERSION,
    _bound_records,
    _evaluate_observation,
    _expected_paths,
    _repository_observation,
    _safe_target_observation,
    _semantic_observation,
)


COMMIT_BUILDER_POLICY_VERSION = "twos.local_commit_builder.vol18.008.v1"
MAX_COMMIT_SUBJECT_BYTES = 200
MAX_COMMIT_BODY_BYTES = 4_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BRANCH_REF = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,299}")
_SENSITIVE_TEXT_REDACTIONS = (
    (
        re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.I),
        r"\1<redacted>@",
    ),
    (
        re.compile(r"\b(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{12,}\b"),
        "<redacted-token>",
    ),
    (
        re.compile(
            r"(\bauthorization\s*[:=]\s*bearer\s+)[^\s,;]+",
            re.I,
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(
            r"((?<![A-Za-z0-9_-])"
            r"(?:api[_-]?key|access[_-]?token|password|client[_-]?secret|token)"
            r"\s*[:=]\s*)[^\s,;]+",
            re.I,
        ),
        r"\1<redacted>",
    ),
)
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", re.I),
    *(pattern for pattern, _replacement in _SENSITIVE_TEXT_REDACTIONS),
)


class CommitBuilderError(ValueError):
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


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _failure(code: str, message: str) -> CommitBuilderError:
    return CommitBuilderError(code, message)


def _redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SENSITIVE_TEXT_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _safe_message(subject: object, body: object) -> tuple[str, str]:
    if not isinstance(subject, str) or not isinstance(body, str):
        raise _failure("COMMIT_MESSAGE_INVALID", "The Commit message is invalid.")
    try:
        subject_bytes = subject.encode("utf-8")
        body_bytes = body.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _failure("COMMIT_MESSAGE_INVALID", "The Commit message is invalid.") from exc
    if (
        not subject
        or subject != subject.strip()
        or "\n" in subject
        or "\r" in subject
        or "\x00" in subject
        or len(subject_bytes) > MAX_COMMIT_SUBJECT_BYTES
        or len(body_bytes) > MAX_COMMIT_BODY_BYTES
        or "\x00" in body
        or "\r" in body
        or any(ord(character) < 32 or ord(character) == 127 for character in subject)
        or any(
            (ord(character) < 32 and character not in {"\n", "\t"})
            or ord(character) == 127
            for character in body
        )
    ):
        raise _failure("COMMIT_MESSAGE_INVALID", "The Commit message is invalid.")
    combined = subject + "\n" + body
    if any(pattern.search(combined) for pattern in _SECRET_PATTERNS):
        raise _failure(
            "COMMIT_MESSAGE_SENSITIVE",
            "The Commit message appears to contain sensitive material.",
        )
    return subject, body


def _git_environment(*, index_file: Path | None = None) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "PAGER": "cat",
            "LC_ALL": "C",
        }
    )
    if index_file is not None:
        environment["GIT_INDEX_FILE"] = str(index_file)
    return environment


def _assert_unredirected_git_context() -> None:
    inherited = sorted(key for key in os.environ if key.startswith("GIT_"))
    if inherited:
        raise _failure(
            "GIT_ENVIRONMENT_BLOCKED",
            "Inherited Git process overrides are not permitted for Stage or Commit.",
        )


@contextmanager
def _commit_builder_repository_lock(
    repository_locator_fingerprint: str,
    *,
    wait_timeout_seconds: float = 0.0,
):
    """Translate lock-acquisition failures without changing lock semantics."""
    acquired = False
    try:
        lock = (
            _repository_mutation_lock(repository_locator_fingerprint)
            if wait_timeout_seconds <= 0
            else _repository_mutation_lock(
                repository_locator_fingerprint,
                wait_timeout_seconds=wait_timeout_seconds,
            )
        )
        with lock:
            acquired = True
            yield
    except ApplySessionError as exc:
        # ApplySessionError raised by work inside the acquired lock retains its
        # existing handling.  Only lock-acquisition failures cross the public
        # Commit Builder boundary as sanitized CommitBuilderError values.
        if acquired:
            raise
        if exc.code == "CONCURRENT_APPLY":
            raise _failure(
                "REPOSITORY_MUTATION_ACTIVE",
                "Another repository mutation is active.",
            ) from exc
        if exc.code == "REPOSITORY_LOCK_UNAVAILABLE":
            raise _failure(
                "REPOSITORY_LOCK_UNAVAILABLE",
                "The repository mutation lock is unavailable.",
            ) from exc
        raise _failure(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The repository identity cannot be locked safely.",
        ) from exc


@contextmanager
def _commit_builder_repository_observation_lock(
    repository_locator_fingerprint: str,
):
    """Translate the shared read-only repository lock at the Commit boundary."""
    acquired = False
    try:
        with _repository_observation_lock(repository_locator_fingerprint):
            acquired = True
            yield
    except ApplySessionError as exc:
        if acquired:
            raise
        if exc.code == "CONCURRENT_APPLY":
            raise _failure(
                "REPOSITORY_MUTATION_ACTIVE",
                "Another repository mutation is active.",
            ) from exc
        if exc.code == "REPOSITORY_LOCK_UNAVAILABLE":
            raise _failure(
                "REPOSITORY_LOCK_UNAVAILABLE",
                "The repository mutation lock is unavailable.",
            ) from exc
        raise _failure(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The repository identity cannot be locked safely.",
        ) from exc


def _git_command(args: Iterable[str]) -> list[str]:
    arguments = list(args)
    if arguments and arguments[0] == "diff":
        arguments[1:1] = ["--no-ext-diff", "--no-textconv"]
    return [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "commit.gpgSign=false",
        *arguments,
    ]


def _run_git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
    timeout: int = 60,
    index_file: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            _git_command(args),
            cwd=root,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            env=_git_environment(index_file=index_file),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _failure("GIT_COMMAND_FAILED", "The local Git operation did not complete safely.") from exc
    if check and result.returncode != 0:
        raise _failure(
            "GIT_COMMAND_FAILED",
            "The local Git operation did not complete safely.",
        )
    return result


def _git_text(root: Path, *args: str) -> str:
    output = _run_git(root, *args).stdout
    try:
        return output.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise _failure("GIT_EVIDENCE_INVALID", "Git returned invalid repository evidence.") from exc


def _branch_ref(root: Path, expected_branch: str) -> str:
    reference = _git_text(root, "symbolic-ref", "--quiet", "HEAD")
    if (
        not _BRANCH_REF.fullmatch(reference)
        or reference.removeprefix("refs/heads/") != expected_branch
    ):
        raise _failure(
            "BRANCH_CHANGED",
            "The current branch no longer matches the verified Apply boundary.",
        )
    return reference


def _refs_fingerprint_excluding(root: Path, excluded_ref: str) -> str:
    output = _run_git(
        root,
        "for-each-ref",
        "--format=%(refname) %(objectname)",
    ).stdout
    rows: list[dict[str, str]] = []
    try:
        for raw_line in output.splitlines():
            if not raw_line:
                continue
            raw_ref, raw_oid = raw_line.split(b" ", 1)
            ref = raw_ref.decode("ascii")
            oid = raw_oid.decode("ascii")
            if ref == excluded_ref:
                continue
            if not ref.startswith("refs/") or not re.fullmatch(
                r"[0-9a-f]{40}|[0-9a-f]{64}", oid
            ):
                raise ValueError("invalid ref evidence")
            rows.append({"ref": ref, "oid": oid})
    except (ValueError, UnicodeDecodeError) as exc:
        raise _failure(
            "GIT_EVIDENCE_INVALID",
            "Git returned invalid ref evidence.",
        ) from exc
    rows.sort(key=lambda item: item["ref"].encode("ascii"))
    return canonical_sha256(rows)


def _verified_root(run: Any, source_repo: Path) -> Path:
    _assert_unredirected_git_context()
    try:
        configured = source_repo.resolve(strict=True)
        observed = Path(_git_text(configured, "rev-parse", "--show-toplevel")).resolve(
            strict=True
        )
        stored = Path(run.source_repo).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _failure(
            "REPOSITORY_UNAVAILABLE",
            "The source repository cannot be verified safely.",
        ) from exc
    if configured != observed or configured != stored:
        raise _failure(
            "REPOSITORY_IDENTITY_MISMATCH",
            "The configured repository does not match the Run binding.",
        )
    return configured


@contextmanager
def _stable_index_snapshot(root: Path):
    git_dir = Path(_git_text(root, "rev-parse", "--absolute-git-dir")).resolve(
        strict=True
    )
    raw_index = Path(_git_text(root, "rev-parse", "--git-path", "index"))
    if not raw_index.is_absolute():
        raw_index = root / raw_index
    try:
        unresolved = raw_index.lstat()
        if stat.S_ISLNK(unresolved.st_mode):
            raise OSError("unsafe index")
        index_path = raw_index.resolve(strict=True)
        if not index_path.is_relative_to(git_dir):
            raise OSError("index outside git directory")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(index_path, flags)
        try:
            before = os.fstat(source_fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(source_fd)
        finally:
            os.close(source_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise OSError("index changed during snapshot")
        snapshot_fd, snapshot_name = tempfile.mkstemp(
            prefix="twos-local-commit-index-",
            suffix=".idx",
        )
        if Path(snapshot_name).resolve().is_relative_to(root):
            os.close(snapshot_fd)
            Path(snapshot_name).unlink(missing_ok=True)
            raise OSError("temporary index is inside repository")
        try:
            os.fchmod(snapshot_fd, 0o600)
            material = b"".join(chunks)
            offset = 0
            while offset < len(material):
                offset += os.write(snapshot_fd, material[offset:])
            os.fsync(snapshot_fd)
        finally:
            os.close(snapshot_fd)
    except OSError as exc:
        raise _failure(
            "INDEX_SNAPSHOT_UNAVAILABLE",
            "The exact staged index cannot be snapshotted safely.",
        ) from exc
    snapshot = Path(snapshot_name)
    try:
        yield snapshot
    finally:
        try:
            snapshot.unlink()
        except FileNotFoundError:
            pass


def _verification_digest(row: PostApplyVerification) -> str:
    return canonical_sha256(
        {
            "schema": "twos.post_apply_verification.v2",
            "observation_digest": row.observation_digest,
            "status": row.status,
            "tests": _decoded_list(row.test_results_json),
            "blockers": _decoded_list(row.blocker_codes_json),
            "boundaries": _decoded_object(row.boundary_evidence_json),
        }
    )


def _bound_verification(
    session: Session,
    *,
    owner_id: int,
    verification: PostApplyVerification,
) -> tuple[ApplySession, Any, Any, Any, Any, list[Any]]:
    if verification.owner_id != owner_id:
        raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
    apply_session = session.get(ApplySession, verification.apply_session_id)
    if apply_session is None or apply_session.owner_id != owner_id:
        raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
    latest = session.scalar(
        select(PostApplyVerification)
        .where(
            PostApplyVerification.owner_id == owner_id,
            PostApplyVerification.apply_session_id == apply_session.id,
        )
        .order_by(PostApplyVerification.id.desc())
        .limit(1)
    )
    if latest is None or latest.id != verification.id:
        raise _failure(
            "VERIFICATION_SUPERSEDED",
            "A newer Post-Apply Verification must be reviewed before staging.",
        )
    if (
        verification.status != "PASSED"
        or verification.policy_version != POST_APPLY_VERIFICATION_POLICY_VERSION
        or _decoded_list(verification.blocker_codes_json)
        or any(
            not isinstance(item, dict) or item.get("status") != "PASS"
            for item in _decoded_list(verification.test_results_json)
        )
    ):
        raise _failure(
            "VERIFICATION_NOT_PASSED",
            "The latest Post-Apply Verification has not passed.",
        )
    calculated_digest = _verification_digest(verification)
    if (
        calculated_digest != verification.verification_digest
        or verification.verification_id != "pav_" + calculated_digest[:40]
    ):
        raise _failure(
            "VERIFICATION_INTEGRITY_BLOCKED",
            "The Post-Apply Verification integrity binding is invalid.",
        )
    try:
        apply_plan, candidate, run, pack = _bound_records(
            session,
            owner_id=owner_id,
            apply_session=apply_session,
        )
    except Exception as exc:
        raise _failure(
            "VERIFICATION_BINDING_INVALID",
            "The Post-Apply Verification no longer matches the Apply evidence.",
        ) from exc
    entries = apply_session_entries(session, apply_session)
    if (
        not entries
        or verification.apply_plan_id != apply_plan.id
        or verification.delivery_candidate_id != candidate.id
        or verification.run_id != run.id
        or verification.apply_session_public_id != apply_session.session_id
        or verification.apply_plan_public_id != apply_plan.plan_id
        or verification.candidate_public_id != candidate.candidate_id
        or verification.journal_digest != apply_session.journal_digest
        or verification.apply_plan_digest != apply_plan.plan_digest
        or verification.candidate_digest != candidate.candidate_digest
        or verification.repository_locator_fingerprint
        != apply_session.repository_locator_fingerprint
        or verification.expected_branch != apply_session.branch
        or verification.observed_branch != apply_session.branch
        or verification.expected_head != apply_session.pre_apply_head
        or verification.observed_head != apply_session.pre_apply_head
        or verification.source_snapshot_identity
        != apply_session.source_snapshot_identity
        or canonical_json(_decoded_list(verification.expected_paths_json))
        != canonical_json(_expected_paths(entries))
        or not validate_apply_session_journal(session, apply_session)
    ):
        raise _failure(
            "VERIFICATION_BINDING_INVALID",
            "The Post-Apply Verification no longer matches the Apply evidence.",
        )
    return apply_session, apply_plan, candidate, run, pack, entries


def _safe_global_evidence(global_evidence: dict[str, Any]) -> dict[str, Any]:
    index = _decoded_object(global_evidence.get("index"))
    return {
        "schema": "twos.commit_repository_boundary.v1",
        "repository_locator_fingerprint": global_evidence.get(
            "repository_locator_fingerprint"
        ),
        "repository_fingerprint": global_evidence.get("repository_fingerprint"),
        "sanitized_repository_identity": global_evidence.get(
            "sanitized_repository_identity"
        ),
        "branch": global_evidence.get("branch"),
        "head": global_evidence.get("head"),
        "source_digest": global_evidence.get("source_digest"),
        "worktree_fingerprint": global_evidence.get("worktree_fingerprint"),
        "index": {
            "fingerprint": index.get("fingerprint"),
            "size": index.get("size"),
            "mode": index.get("mode"),
            "staged_path_count": index.get("staged_path_count"),
            "staged_path_identities": index.get("staged_path_identities"),
        },
        "refs_fingerprint": global_evidence.get("refs_fingerprint"),
        "local_config_fingerprint": global_evidence.get(
            "local_config_fingerprint"
        ),
        "remote_fingerprint": global_evidence.get("remote_fingerprint"),
    }


def _assert_targets_match(root: Path, entries: list[Any]) -> None:
    observations = _safe_target_observation(root, entries)
    if (
        len(observations) != len(entries)
        or any(not bool(item.get("matches")) for item in observations)
    ):
        raise _failure(
            "APPLIED_PATH_CHANGED",
            "A verified applied path changed during Stage or Commit.",
        )


def _current_boundary_locked(
    *,
    run: Any,
    pack: Any,
    apply_session: ApplySession,
    entries: list[Any],
    source_repo: Path,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    _assert_unredirected_git_context()
    baseline = _decoded_object(
        _decoded_object(apply_session.after_evidence_json).get("global")
    )
    if not baseline:
        raise _failure(
            "VERIFICATION_EVIDENCE_UNAVAILABLE",
            "The verified repository boundary is unavailable.",
        )
    try:
        first = _repository_observation(
            run=run,
            pack=pack,
            source_repo=source_repo,
            entries=entries,
            baseline_global=baseline,
        )
        second = _repository_observation(
            run=run,
            pack=pack,
            source_repo=source_repo,
            entries=entries,
            baseline_global=baseline,
        )
        stable = canonical_json(_semantic_observation(first)) == canonical_json(
            _semantic_observation(second)
        )
        status, blockers, _unexpected, _preserved, tests = _evaluate_observation(
            apply_session=apply_session,
            baseline_global=baseline,
            observation=second,
            stable=stable,
        )
    except (ApplySessionError, OSError, RuntimeError, ValueError) as exc:
        raise _failure(
            "REPOSITORY_UNAVAILABLE",
            "The repository cannot be validated safely for a local Commit.",
        ) from exc
    return status, blockers, tests, _decoded_object(second.get("global"))


def find_owned_commit_plan(
    session: Session,
    *,
    owner_id: int,
    commit_plan_id: str,
) -> CommitPlan | None:
    return session.scalar(
        select(CommitPlan).where(
            CommitPlan.owner_id == owner_id,
            CommitPlan.commit_plan_id == commit_plan_id,
        )
    )


def find_owned_stage_execution(
    session: Session,
    *,
    owner_id: int,
    stage_execution_id: str,
) -> StageExecution | None:
    return session.scalar(
        select(StageExecution).where(
            StageExecution.owner_id == owner_id,
            StageExecution.stage_execution_id == stage_execution_id,
        )
    )


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


def _plan_for_verification(
    session: Session,
    *,
    owner_id: int,
    verification_id: int,
) -> CommitPlan | None:
    return session.scalar(
        select(CommitPlan).where(
            CommitPlan.owner_id == owner_id,
            CommitPlan.post_apply_verification_id == verification_id,
        )
    )


def get_or_create_commit_plan(
    session: Session,
    *,
    owner_id: int,
    post_apply_verification: PostApplyVerification,
    source_repo: Path,
    subject: object,
    body: object = "",
) -> tuple[CommitPlan, bool]:
    subject_value, body_value = _safe_message(subject, body)
    existing = _plan_for_verification(
        session,
        owner_id=owner_id,
        verification_id=post_apply_verification.id,
    )
    if existing is not None:
        if existing.subject != subject_value or existing.body != body_value:
            raise _failure(
                "COMMIT_PLAN_ALREADY_EXISTS",
                "This verification already has an immutable Commit Plan.",
            )
        return existing, False
    (
        apply_session,
        apply_plan,
        candidate,
        run,
        pack,
        entries,
    ) = _bound_verification(
        session,
        owner_id=owner_id,
        verification=post_apply_verification,
    )
    root = _verified_root(run, source_repo)
    with _commit_builder_repository_lock(
        apply_session.repository_locator_fingerprint
    ):
        status, blockers, tests, current_global = _current_boundary_locked(
            run=run,
            pack=pack,
            apply_session=apply_session,
            entries=entries,
            source_repo=root,
        )
        branch_ref = _branch_ref(root, apply_session.branch)
    verified_paths = _expected_paths(entries)
    excluded_paths = _decoded_list(apply_session.excluded_paths_json)
    boundary = _safe_global_evidence(current_global)
    status_at_creation = "READY" if status == "PASSED" else "EXPIRED"
    blocker_codes = [
        {
            "code": str(item.get("code") or "REPOSITORY_CHANGED"),
            "message": str(item.get("message") or "Repository evidence changed."),
        }
        for item in blockers
        if isinstance(item, dict)
    ]
    binding_material = {
        "schema": "twos.commit_plan_binding.v1",
        "owner_id": owner_id,
        "verification_id": post_apply_verification.verification_id,
        "verification_digest": post_apply_verification.verification_digest,
        "apply_session_id": apply_session.session_id,
        "journal_digest": apply_session.journal_digest,
        "apply_plan_id": apply_plan.plan_id,
        "apply_plan_digest": apply_plan.plan_digest,
        "candidate_id": candidate.candidate_id,
        "candidate_digest": candidate.candidate_digest,
        "run_id": run.id,
        "repository_locator_fingerprint": apply_session.repository_locator_fingerprint,
        "branch": apply_session.branch,
        "branch_ref": branch_ref,
        "base_head": apply_session.pre_apply_head,
        "source_snapshot_identity": apply_session.source_snapshot_identity,
    }
    binding_digest = canonical_sha256(binding_material)
    plan_material = {
        "schema": "twos.commit_plan.v1",
        "policy_version": COMMIT_BUILDER_POLICY_VERSION,
        "binding_digest": binding_digest,
        "verified_paths": verified_paths,
        "excluded_paths": excluded_paths,
        "subject": subject_value,
        "body": body_value,
        "validation": tests,
        "blockers": blocker_codes,
        "boundary": boundary,
        "status_at_creation": status_at_creation,
    }
    plan_digest = canonical_sha256(plan_material)
    row = CommitPlan(
        commit_plan_id="cplan_" + plan_digest[:40],
        owner_id=owner_id,
        post_apply_verification_id=post_apply_verification.id,
        apply_session_id=apply_session.id,
        apply_plan_id=apply_plan.id,
        delivery_candidate_id=candidate.id,
        run_id=run.id,
        verification_public_id=post_apply_verification.verification_id,
        verification_digest=post_apply_verification.verification_digest,
        apply_session_public_id=apply_session.session_id,
        journal_digest=apply_session.journal_digest,
        apply_plan_public_id=apply_plan.plan_id,
        apply_plan_digest=apply_plan.plan_digest,
        candidate_public_id=candidate.candidate_id,
        candidate_digest=candidate.candidate_digest,
        repository_locator_fingerprint=apply_session.repository_locator_fingerprint,
        repository_fingerprint=str(boundary.get("repository_fingerprint") or ""),
        sanitized_repository_identity=apply_session.sanitized_repository_identity,
        branch=apply_session.branch,
        branch_ref=branch_ref,
        base_head=apply_session.pre_apply_head,
        source_snapshot_identity=apply_session.source_snapshot_identity,
        verified_paths_json=canonical_json(verified_paths),
        excluded_paths_json=canonical_json(excluded_paths),
        subject=subject_value,
        body=body_value,
        validation_json=canonical_json(tests),
        blocker_codes_json=canonical_json(blocker_codes),
        boundary_evidence_json=canonical_json(boundary),
        policy_version=COMMIT_BUILDER_POLICY_VERSION,
        status_at_creation=status_at_creation,
        binding_digest=binding_digest,
        plan_digest=plan_digest,
    )
    session.add(row)
    session.flush()
    return row, True


def _plan_verification(session: Session, plan: CommitPlan) -> PostApplyVerification:
    verification = session.get(PostApplyVerification, plan.post_apply_verification_id)
    if verification is None:
        raise _failure("COMMIT_PLAN_BINDING_INVALID", "The Commit Plan binding is unavailable.")
    return verification


def _refresh_latest_plan_verification(
    session: Session,
    *,
    owner_id: int,
    plan: CommitPlan,
) -> tuple[CommitPlan, tuple[ApplySession, Any, Any, Any, Any, list[Any]]]:
    """End the prior read snapshot and revalidate the exact latest PAV."""
    plan_pk = plan.id
    expected_plan_digest = plan.plan_digest
    # Callers use this only after their durable intent is committed and while
    # holding the repository lock.  Ending the read transaction here makes a
    # concurrently persisted newer verification visible before Git mutation.
    session.commit()
    session.expire_all()
    current_plan = session.get(CommitPlan, plan_pk)
    if (
        current_plan is None
        or current_plan.owner_id != owner_id
        or current_plan.plan_digest != expected_plan_digest
    ):
        raise _failure(
            "COMMIT_PLAN_CHANGED",
            "The Commit Plan identity changed.",
        )
    verification = _plan_verification(session, current_plan)
    return current_plan, _bound_verification(
        session,
        owner_id=owner_id,
        verification=verification,
    )


def _effective_status_locked(
    session: Session,
    *,
    owner_id: int,
    plan: CommitPlan,
    source_repo: Path,
) -> tuple[str, list[dict[str, str]]]:
    commit_execution = session.scalar(
        select(LocalCommitExecution).where(
            LocalCommitExecution.owner_id == owner_id,
            LocalCommitExecution.commit_plan_id == plan.id,
        )
    )
    if commit_execution is not None and commit_execution.state == "COMMITTED":
        return "COMMITTED", []
    if commit_execution is not None and commit_execution.state in {
        "BLOCKED",
        "INTEGRITY_BLOCKED",
    }:
        failures = _decoded_list(commit_execution.failure_evidence_json)
        blockers = [
            {
                "code": (
                    str(item.get("code"))
                    if isinstance(item, dict)
                    and re.fullmatch(r"[A-Z0-9_]{1,80}", str(item.get("code") or ""))
                    else "LOCAL_COMMIT_INTEGRITY_BLOCKED"
                ),
                "message": "The local Commit evidence is blocked.",
            }
            for item in failures
        ]
        return "BLOCKED", blockers or [
            {
                "code": "LOCAL_COMMIT_INTEGRITY_BLOCKED",
                "message": "The local Commit evidence is blocked.",
            }
        ]
    if plan.status_at_creation != "READY":
        return plan.status_at_creation, _decoded_list(plan.blocker_codes_json)
    try:
        verification = _plan_verification(session, plan)
        apply_session, _apply_plan, _candidate, run, pack, entries = _bound_verification(
            session,
            owner_id=owner_id,
            verification=verification,
        )
        root = _verified_root(run, source_repo)
        stage = session.scalar(
            select(StageExecution).where(
                StageExecution.owner_id == owner_id,
                StageExecution.commit_plan_id == plan.id,
            )
        )
        if (
            stage is not None
            and commit_execution is not None
            and commit_execution.state in {"COMMITTING", "FAILED"}
            and commit_execution.commit_oid
            and _git_text(root, "rev-parse", "HEAD")
            == commit_execution.commit_oid
        ):
            _validated_committed_state(
                execution=commit_execution,
                stage_execution=stage,
                plan=plan,
                root=root,
                run=run,
                entries=entries,
                apply_session=apply_session,
                commit_oid=commit_execution.commit_oid,
            )
            return "STAGED", [
                {
                    "code": "COMMIT_RECOVERY_REQUIRED",
                    "message": "Select Create Local Commit again to settle the exact existing Commit receipt.",
                }
            ]
        if stage is not None:
            if stage.state in {"BLOCKED", "INTEGRITY_BLOCKED"}:
                return "BLOCKED", [
                    {
                        "code": "STAGE_NOT_VERIFIED",
                        "message": "The Stage execution is not verified.",
                    }
                ]
            if stage.state in {"STAGING", "FAILED"}:
                staged_paths = _staged_path_set(root, plan.base_head)
                if staged_paths:
                    staged = _verify_exact_stage(
                        root,
                        head=plan.base_head,
                        planned=_decoded_list(stage.planned_entries_json),
                    )
                    if canonical_sha256(staged) != canonical_sha256(
                        _decoded_list(stage.planned_entries_json)
                    ):
                        raise _failure(
                            "STAGE_INTEGRITY_BLOCKED",
                            "The recoverable Stage evidence is invalid.",
                        )
                    _assert_targets_match(root, entries)
                    return "READY", [
                        {
                            "code": "STAGE_RECOVERY_REQUIRED",
                            "message": "Select Stage Approved Files again to settle the existing exact Stage intent.",
                        }
                    ]
                # No index mutation is present. Fall through to the ordinary
                # clean-boundary validation; an explicit retry may resume the
                # same durable intent when that validation still passes.
            elif stage.state != "STAGED" or not stage.stage_digest:
                return "BLOCKED", [
                    {
                        "code": "STAGE_NOT_VERIFIED",
                        "message": "The Stage execution is not verified.",
                    }
                ]
            else:
                if (
                    stage.commit_plan_digest != plan.plan_digest
                    or stage.verification_digest != plan.verification_digest
                    or stage.base_head != plan.base_head
                    or stage.branch_ref != plan.branch_ref
                ):
                    raise _failure("STAGE_INTEGRITY_BLOCKED", "The Stage binding is invalid.")
                if _branch_ref(root, plan.branch) != plan.branch_ref:
                    raise _failure("BRANCH_CHANGED", "The branch binding changed.")
                if _git_text(root, "rev-parse", "HEAD") != plan.base_head:
                    raise _failure("HEAD_CHANGED", "HEAD changed after Stage.")
                planned = _decoded_list(stage.planned_entries_json)
                staged, current = _stable_exact_stage_evidence(
                    root=root,
                    run=run,
                    apply_session=apply_session,
                    entries=entries,
                    plan=plan,
                    planned=planned,
                )
                if canonical_sha256(staged) != stage.staged_entries_digest:
                    raise _failure("STAGE_INTEGRITY_BLOCKED", "The Stage receipt is invalid.")
                stage_boundary = _decoded_object(stage.post_stage_evidence_json)
                for key in (
                    "branch",
                    "head",
                    "source_digest",
                    "worktree_fingerprint",
                    "refs_fingerprint",
                    "local_config_fingerprint",
                    "remote_fingerprint",
                ):
                    if current.get(key) != stage_boundary.get(key):
                        raise _failure(
                            "STAGE_BOUNDARY_CHANGED",
                            "Repository evidence changed after Stage.",
                        )
                if _decoded_object(current.get("index")).get("fingerprint") != _decoded_object(
                    stage_boundary.get("index")
                ).get("fingerprint"):
                    raise _failure(
                        "STAGE_BOUNDARY_CHANGED",
                        "The Git index changed after Stage.",
                    )
                return "STAGED", []
        status, blockers, _tests, _global = _current_boundary_locked(
            run=run,
            pack=pack,
            apply_session=apply_session,
            entries=entries,
            source_repo=root,
        )
        if _branch_ref(root, plan.branch) != plan.branch_ref:
            raise _failure("BRANCH_CHANGED", "The branch binding changed.")
        if status != "PASSED":
            return "EXPIRED", blockers
    except CommitBuilderError as exc:
        return "BLOCKED", [{"code": exc.code, "message": exc.message}]
    except ApplySessionError:
        return "BLOCKED", [
            {
                "code": "COMMIT_PLAN_BOUNDARY_BLOCKED",
                "message": "The Commit Plan boundary cannot be verified safely.",
            }
        ]
    return "READY", []


def commit_plan_effective_status(
    session: Session,
    *,
    owner_id: int,
    plan: CommitPlan,
    source_repo: Path,
) -> tuple[str, list[dict[str, str]]]:
    if plan.owner_id != owner_id:
        raise _failure("COMMIT_PLAN_NOT_FOUND", "Commit Plan not found.")
    with _commit_builder_repository_lock(plan.repository_locator_fingerprint):
        return _effective_status_locked(
            session,
            owner_id=owner_id,
            plan=plan,
            source_repo=source_repo,
        )


def _planned_stage_entries(
    root: Path,
    entries: list[Any],
) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = []
    for entry in entries:
        path = normalize_repository_path(entry.repository_path)
        if entry.operation not in {"CREATE", "MODIFY", "DELETE"}:
            raise _failure("STAGE_ENTRY_INVALID", "A verified path has an unsupported operation.")
        if entry.operation == "DELETE":
            if entry.after_present:
                raise _failure("STAGE_ENTRY_INVALID", "A DELETE path has invalid after-state evidence.")
            planned.append(
                {
                    "path": path,
                    "path_identity": entry.path_identity,
                    "operation": entry.operation,
                    "present": False,
                    "mode": None,
                    "blob_oid": None,
                    "sha256": None,
                }
            )
            continue
        material = entry.after_material
        if (
            not entry.after_present
            or entry.after_file_type != "regular"
            or not isinstance(material, bytes)
            or _sha256_bytes(material) != entry.after_hash
        ):
            raise _failure("STAGE_ENTRY_INVALID", "A verified path lacks exact after-state material.")
        mode = "100755" if int(entry.after_mode or 0) & 0o111 else "100644"
        result = _run_git(
            root,
            "hash-object",
            "--no-filters",
            "--stdin",
            input_bytes=material,
        )
        try:
            oid = result.stdout.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise _failure("GIT_EVIDENCE_INVALID", "Git returned an invalid object identity.") from exc
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
            raise _failure("GIT_EVIDENCE_INVALID", "Git returned an invalid object identity.")
        planned.append(
            {
                "path": path,
                "path_identity": entry.path_identity,
                "operation": entry.operation,
                "present": True,
                "mode": mode,
                "blob_oid": oid,
                "sha256": entry.after_hash,
            }
        )
    return planned


def _index_entries(
    root: Path,
    *,
    index_file: Path | None = None,
) -> dict[str, dict[str, str]]:
    output = _run_git(
        root,
        "ls-files",
        "--stage",
        "-z",
        index_file=index_file,
    ).stdout
    result: dict[str, dict[str, str]] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise _failure("GIT_EVIDENCE_INVALID", "The Git index evidence is malformed.") from exc
        result[path] = {"mode": mode, "blob_oid": oid, "stage": stage}
    return result


def _staged_path_set(
    root: Path,
    head: str,
    *,
    index_file: Path | None = None,
) -> list[str]:
    output = _run_git(
        root,
        "diff",
        "--cached",
        "--name-only",
        "--no-renames",
        "-z",
        head,
        index_file=index_file,
    ).stdout
    try:
        return sorted(
            (item.decode("utf-8") for item in output.split(b"\0") if item),
            key=lambda value: value.encode("utf-8"),
        )
    except UnicodeDecodeError as exc:
        raise _failure("GIT_EVIDENCE_INVALID", "The staged path evidence is malformed.") from exc


def _verify_exact_stage(
    root: Path,
    *,
    head: str,
    planned: list[dict[str, Any]],
    index_file: Path | None = None,
) -> list[dict[str, Any]]:
    expected_paths = sorted(
        (str(item["path"]) for item in planned),
        key=lambda value: value.encode("utf-8"),
    )
    if _staged_path_set(root, head, index_file=index_file) != expected_paths:
        raise _failure(
            "STAGE_INTEGRITY_BLOCKED",
            "The staged path set does not exactly match the Commit Plan.",
        )
    index = _index_entries(root, index_file=index_file)
    receipt: list[dict[str, Any]] = []
    for item in planned:
        path = str(item["path"])
        actual = index.get(path)
        if item["present"] is False:
            if actual is not None:
                raise _failure("STAGE_INTEGRITY_BLOCKED", "A DELETE path remains in the Git index.")
        elif (
            actual is None
            or actual.get("stage") != "0"
            or actual.get("mode") != item.get("mode")
            or actual.get("blob_oid") != item.get("blob_oid")
        ):
            raise _failure(
                "STAGE_INTEGRITY_BLOCKED",
                "A staged entry does not match its verified content identity.",
            )
        receipt.append(dict(item))
    return receipt


def _stable_exact_stage_evidence(
    *,
    root: Path,
    run: Any,
    apply_session: ApplySession,
    entries: list[Any],
    plan: CommitPlan,
    planned: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baseline = _decoded_object(apply_session.after_evidence_json).get("global")

    def sample() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        staged = _verify_exact_stage(
            root,
            head=plan.base_head,
            planned=planned,
        )
        _assert_targets_match(root, entries)
        boundary = _safe_global_evidence(
            _global_evidence_after_mutation(
                run,
                root,
                target_paths=[entry.repository_path for entry in entries],
                baseline=_decoded_object(baseline),
            )
        )
        _assert_targets_match(root, entries)
        final_staged = _verify_exact_stage(
            root,
            head=plan.base_head,
            planned=planned,
        )
        if canonical_json(staged) != canonical_json(final_staged):
            raise _failure(
                "STAGE_INTEGRITY_BLOCKED",
                "The exact Git index changed during Stage settlement.",
            )
        return final_staged, boundary

    first_entries, first_boundary = sample()
    second_entries, second_boundary = sample()
    if (
        canonical_json(first_entries) != canonical_json(second_entries)
        or canonical_json(first_boundary) != canonical_json(second_boundary)
    ):
        raise _failure(
            "STAGE_INTEGRITY_BLOCKED",
            "Repository evidence changed during Stage settlement.",
        )
    return second_entries, second_boundary


def _other_stage_blocker(
    session: Session,
    *,
    plan: CommitPlan,
) -> StageExecution | None:
    candidates = list(
        session.scalars(
            select(StageExecution).where(
            StageExecution.repository_locator_fingerprint
            == plan.repository_locator_fingerprint,
            StageExecution.commit_plan_id != plan.id,
            StageExecution.state.in_(["STAGING", "STAGED", "INTEGRITY_BLOCKED"]),
            )
        ).all()
    )
    for candidate in candidates:
        if candidate.state == "STAGED":
            completed = session.scalar(
                select(LocalCommitExecution).where(
                    LocalCommitExecution.stage_execution_id == candidate.id,
                    LocalCommitExecution.state == "COMMITTED",
                )
            )
            if completed is not None:
                continue
        return candidate
    return None


def _settle_existing_stage_if_present(
    session: Session,
    *,
    execution: StageExecution,
    plan: CommitPlan,
    root: Path,
    run: Any,
    apply_session: ApplySession,
    entries: list[Any],
) -> bool:
    planned = _decoded_list(execution.planned_entries_json)
    staged_paths = _staged_path_set(root, plan.base_head)
    if not staged_paths:
        return False
    try:
        execution_pk = execution.id
        plan, refreshed_binding = _refresh_latest_plan_verification(
            session,
            owner_id=execution.owner_id,
            plan=plan,
        )
        (
            apply_session,
            _apply_plan,
            _candidate,
            run,
            _pack,
            entries,
        ) = refreshed_binding
        execution = session.get(StageExecution, execution_pk)
        if (
            execution is None
            or execution.owner_id != plan.owner_id
            or execution.commit_plan_id != plan.id
            or execution.state not in {"STAGING", "FAILED"}
        ):
            raise _failure(
                "STAGE_INTEGRITY_BLOCKED",
                "The recoverable Stage intent changed before settlement.",
            )
        first_entries, first_post = _stable_exact_stage_evidence(
            root=root,
            run=run,
            apply_session=apply_session,
            entries=entries,
            plan=plan,
            planned=planned,
        )
        plan, refreshed_binding = _refresh_latest_plan_verification(
            session,
            owner_id=execution.owner_id,
            plan=plan,
        )
        (
            apply_session,
            _apply_plan,
            _candidate,
            run,
            _pack,
            entries,
        ) = refreshed_binding
        execution = session.get(StageExecution, execution_pk)
        if (
            execution is None
            or execution.owner_id != plan.owner_id
            or execution.commit_plan_id != plan.id
            or execution.state not in {"STAGING", "FAILED"}
        ):
            raise _failure(
                "STAGE_INTEGRITY_BLOCKED",
                "The recoverable Stage intent changed during settlement.",
            )
        staged_entries, post_stage = _stable_exact_stage_evidence(
            root=root,
            run=run,
            apply_session=apply_session,
            entries=entries,
            plan=plan,
            planned=planned,
        )
        if (
            canonical_json(first_entries) != canonical_json(staged_entries)
            or canonical_json(first_post) != canonical_json(post_stage)
        ):
            raise _failure(
                "STAGE_INTEGRITY_BLOCKED",
                "Repository evidence changed during Stage recovery.",
            )
        pre_stage = _decoded_object(execution.pre_stage_evidence_json)
        for key in (
            "branch",
            "head",
            "source_digest",
            "worktree_fingerprint",
            "refs_fingerprint",
            "local_config_fingerprint",
            "remote_fingerprint",
        ):
            if post_stage.get(key) != pre_stage.get(key):
                raise _failure(
                    "STAGE_INTEGRITY_BLOCKED",
                    "Repository boundaries changed during Stage recovery.",
                )
        staged_digest = canonical_sha256(staged_entries)
        stage_digest = canonical_sha256(
            {
                "schema": "twos.stage_receipt.v1",
                "stage_execution_id": execution.stage_execution_id,
                "plan_digest": plan.plan_digest,
                "staged_entries_digest": staged_digest,
                "post_stage": post_stage,
            }
        )
        execution.post_stage_evidence_json = canonical_json(post_stage)
        execution.staged_entries_json = canonical_json(staged_entries)
        execution.staged_entries_digest = staged_digest
        execution.stage_digest = stage_digest
        execution.state = "STAGED"
        execution.finished_at = execution.finished_at or utc_now()
        session.commit()
        return True
    except (CommitBuilderError, ApplySessionError, OSError, RuntimeError, ValueError) as exc:
        session.rollback()
        current = session.get(StageExecution, execution.id) or execution
        current.state = "INTEGRITY_BLOCKED"
        current.failure_evidence_json = canonical_json(
            [{"code": getattr(exc, "code", "STAGE_RECOVERY_BLOCKED")}]
        )
        current.finished_at = current.finished_at or utc_now()
        session.commit()
        if isinstance(exc, CommitBuilderError):
            raise
        raise _failure(
            "STAGE_INTEGRITY_BLOCKED",
            "The existing Stage state cannot be reconciled safely.",
        ) from exc


def stage_commit_plan(
    session: Session,
    *,
    owner_id: int,
    plan: CommitPlan,
    source_repo: Path,
    expected_plan_digest: str | None = None,
) -> tuple[StageExecution, bool]:
    if plan.owner_id != owner_id:
        raise _failure("COMMIT_PLAN_NOT_FOUND", "Commit Plan not found.")
    if expected_plan_digest is not None and expected_plan_digest != plan.plan_digest:
        raise _failure("COMMIT_PLAN_CHANGED", "The Commit Plan identity changed.")
    existing = session.scalar(
        select(StageExecution).where(
            StageExecution.owner_id == owner_id,
            StageExecution.commit_plan_id == plan.id,
        )
    )
    if existing is not None and existing.state == "STAGED":
        return existing, False
    verification = _plan_verification(session, plan)
    apply_session, _apply_plan, _candidate, run, pack, entries = _bound_verification(
        session,
        owner_id=owner_id,
        verification=verification,
    )
    root = _verified_root(run, source_repo)
    with _commit_builder_repository_lock(plan.repository_locator_fingerprint):
        plan_pk = plan.id
        session.expire_all()
        plan = session.get(CommitPlan, plan_pk)
        if plan is None or plan.owner_id != owner_id:
            raise _failure("COMMIT_PLAN_NOT_FOUND", "Commit Plan not found.")
        if (
            plan.status_at_creation != "READY"
            or plan.policy_version != COMMIT_BUILDER_POLICY_VERSION
        ):
            raise _failure("COMMIT_PLAN_EXPIRED", "The Commit Plan is not eligible for Stage.")
        if expected_plan_digest is not None and expected_plan_digest != plan.plan_digest:
            raise _failure("COMMIT_PLAN_CHANGED", "The Commit Plan identity changed.")
        verification = _plan_verification(session, plan)
        apply_session, _apply_plan, _candidate, run, pack, entries = _bound_verification(
            session,
            owner_id=owner_id,
            verification=verification,
        )
        existing = session.scalar(
            select(StageExecution).where(
                StageExecution.owner_id == owner_id,
                StageExecution.commit_plan_id == plan.id,
            )
        )
        if existing is not None and existing.state == "STAGED":
            return existing, False
        if _repository_mutation_blocker(
            session,
            repository_locator_fingerprint=plan.repository_locator_fingerprint,
            exclude_plan_id=apply_session.apply_plan_id,
        ) is not None or _other_stage_blocker(session, plan=plan) is not None:
            raise _failure("REPOSITORY_MUTATION_ACTIVE", "Another repository mutation is active.")
        if (
            existing is not None
            and existing.state in {"STAGING", "FAILED"}
            and _settle_existing_stage_if_present(
            session,
            execution=existing,
            plan=plan,
            root=root,
            run=run,
            apply_session=apply_session,
            entries=entries,
            )
        ):
            return existing, False
        status, blockers, _tests, current_global = _current_boundary_locked(
            run=run,
            pack=pack,
            apply_session=apply_session,
            entries=entries,
            source_repo=root,
        )
        if status != "PASSED" or blockers:
            raise _failure("COMMIT_PLAN_EXPIRED", "Repository evidence changed after Commit Plan review.")
        if _branch_ref(root, plan.branch) != plan.branch_ref:
            raise _failure("BRANCH_CHANGED", "The branch binding changed.")
        planned = _planned_stage_entries(root, entries)
        planned_digest = canonical_sha256(planned)
        pre_stage = _safe_global_evidence(current_global)
        pre_stage_digest = canonical_sha256(pre_stage)
        if existing is None:
            intent = canonical_sha256(
                {
                    "schema": "twos.stage_intent.v1",
                    "plan_digest": plan.plan_digest,
                    "planned_entries_digest": planned_digest,
                    "pre_stage_evidence_digest": pre_stage_digest,
                }
            )
            existing = StageExecution(
                stage_execution_id="stage_" + intent[:40],
                owner_id=owner_id,
                commit_plan_id=plan.id,
                commit_plan_public_id=plan.commit_plan_id,
                commit_plan_digest=plan.plan_digest,
                verification_digest=plan.verification_digest,
                repository_locator_fingerprint=plan.repository_locator_fingerprint,
                branch=plan.branch,
                branch_ref=plan.branch_ref,
                base_head=plan.base_head,
                planned_entries_json=canonical_json(planned),
                planned_entries_digest=planned_digest,
                pre_stage_evidence_json=canonical_json(pre_stage),
                pre_stage_evidence_digest=pre_stage_digest,
                state="STAGING",
            )
            session.add(existing)
            session.flush()
            created = True
            session.commit()
            existing = session.get(StageExecution, existing.id) or existing
        else:
            created = False
            if (
                existing.commit_plan_digest != plan.plan_digest
                or existing.planned_entries_digest != planned_digest
                or canonical_json(_decoded_list(existing.planned_entries_json))
                != canonical_json(planned)
            ):
                raise _failure("STAGE_INTEGRITY_BLOCKED", "The Stage intent binding is invalid.")
            if existing.state in {"BLOCKED", "INTEGRITY_BLOCKED"}:
                return existing, False
            existing.state = "STAGING"
            session.commit()
        index_mutation_attempted = False
        try:
            stage_pk = existing.id
            plan, refreshed_binding = _refresh_latest_plan_verification(
                session,
                owner_id=owner_id,
                plan=plan,
            )
            (
                apply_session,
                _apply_plan,
                _candidate,
                run,
                pack,
                entries,
            ) = refreshed_binding
            existing = session.get(StageExecution, stage_pk)
            if (
                existing is None
                or existing.owner_id != owner_id
                or existing.commit_plan_id != plan.id
                or existing.state != "STAGING"
            ):
                raise _failure(
                    "STAGE_INTEGRITY_BLOCKED",
                    "The durable Stage intent changed before Git mutation.",
                )
            # Revalidate after the durable intent is committed and immediately
            # before changing the object database or index.
            status, blockers, _tests, immediate_global = _current_boundary_locked(
                run=run,
                pack=pack,
                apply_session=apply_session,
                entries=entries,
                source_repo=root,
            )
            if status != "PASSED" or blockers:
                raise _failure("COMMIT_PLAN_EXPIRED", "Repository evidence changed before Stage.")
            for item, entry in zip(planned, entries, strict=True):
                if item["present"] is not True:
                    continue
                written = _run_git(
                    root,
                    "hash-object",
                    "-w",
                    "--no-filters",
                    "--stdin",
                    input_bytes=entry.after_material,
                ).stdout.decode("ascii").strip()
                if written != item["blob_oid"]:
                    raise _failure("STAGE_INTEGRITY_BLOCKED", "Git wrote an unexpected blob identity.")
            object_format = _git_text(root, "rev-parse", "--show-object-format")
            zero_oid = "0" * (64 if object_format == "sha256" else 40)
            index_info = bytearray()
            for item in planned:
                if item["present"] is True:
                    prefix = f"{item['mode']} {item['blob_oid']}\t".encode("ascii")
                else:
                    prefix = f"0 {zero_oid}\t".encode("ascii")
                index_info.extend(prefix)
                index_info.extend(str(item["path"]).encode("utf-8"))
                index_info.append(0)
            index_mutation_attempted = True
            _run_git(
                root,
                "update-index",
                "-z",
                "--index-info",
                input_bytes=bytes(index_info),
            )
            present_paths = [
                str(item["path"])
                for item in planned
                if item["present"] is True
            ]
            if present_paths:
                # ``--index-info`` installs the exact cache entries without
                # populating their filesystem stat cache.  Settle only the
                # approved present paths before fingerprinting the durable
                # Stage receipt so a later ordinary read-only status refresh
                # cannot rewrite otherwise identical index bytes.
                _run_git(
                    root,
                    "update-index",
                    "--add",
                    "--",
                    *present_paths,
                )
            plan, refreshed_binding = _refresh_latest_plan_verification(
                session,
                owner_id=owner_id,
                plan=plan,
            )
            (
                apply_session,
                _apply_plan,
                _candidate,
                run,
                _pack,
                entries,
            ) = refreshed_binding
            existing = session.get(StageExecution, stage_pk)
            if (
                existing is None
                or existing.owner_id != owner_id
                or existing.commit_plan_id != plan.id
                or existing.state != "STAGING"
            ):
                raise _failure(
                    "STAGE_INTEGRITY_BLOCKED",
                    "The durable Stage intent changed during Git mutation.",
                )
            staged_entries, post_stage = _stable_exact_stage_evidence(
                root=root,
                run=run,
                apply_session=apply_session,
                entries=entries,
                plan=plan,
                planned=planned,
            )
            if (
                post_stage.get("branch") != pre_stage.get("branch")
                or post_stage.get("head") != pre_stage.get("head")
                or post_stage.get("source_digest") != pre_stage.get("source_digest")
                or post_stage.get("refs_fingerprint") != pre_stage.get("refs_fingerprint")
                or post_stage.get("local_config_fingerprint")
                != pre_stage.get("local_config_fingerprint")
                or post_stage.get("remote_fingerprint")
                != pre_stage.get("remote_fingerprint")
            ):
                raise _failure("STAGE_INTEGRITY_BLOCKED", "Repository boundaries changed during Stage.")
            staged_digest = canonical_sha256(staged_entries)
            stage_digest = canonical_sha256(
                {
                    "schema": "twos.stage_receipt.v1",
                    "stage_execution_id": existing.stage_execution_id,
                    "plan_digest": plan.plan_digest,
                    "staged_entries_digest": staged_digest,
                    "post_stage": post_stage,
                }
            )
            existing.post_stage_evidence_json = canonical_json(post_stage)
            existing.staged_entries_json = canonical_json(staged_entries)
            existing.staged_entries_digest = staged_digest
            existing.stage_digest = stage_digest
            existing.state = "STAGED"
            existing.finished_at = utc_now()
            session.commit()
            return existing, created
        except (CommitBuilderError, ApplySessionError, OSError, RuntimeError, ValueError) as exc:
            session.rollback()
            current = session.get(StageExecution, existing.id) or existing
            current.state = (
                "INTEGRITY_BLOCKED"
                if index_mutation_attempted
                or (
                    isinstance(exc, CommitBuilderError)
                    and exc.code in {"STAGE_INTEGRITY_BLOCKED", "APPLIED_PATH_CHANGED"}
                )
                else "FAILED"
            )
            current.failure_evidence_json = canonical_json(
                [{"code": getattr(exc, "code", "STAGE_FAILED")}]
            )
            if current.state == "INTEGRITY_BLOCKED":
                current.finished_at = current.finished_at or utc_now()
            session.commit()
            if isinstance(exc, CommitBuilderError):
                raise
            raise _failure("STAGE_FAILED", "The exact Stage operation failed safely.") from exc


def _commit_message(plan: CommitPlan) -> bytes:
    text = plan.subject
    if plan.body:
        text += "\n\n" + plan.body
    return (text + "\n").encode("utf-8")


def _commit_object(root: Path, oid: str) -> dict[str, Any]:
    raw = _run_git(root, "cat-file", "commit", oid).stdout
    header, separator, message = raw.partition(b"\n\n")
    if not separator:
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "The local Commit object is malformed.")
    tree = ""
    parents: list[str] = []
    for line in header.splitlines():
        if line.startswith(b"tree "):
            tree = line[5:].decode("ascii", errors="strict")
        elif line.startswith(b"parent "):
            parents.append(line[7:].decode("ascii", errors="strict"))
    return {
        "tree": tree,
        "parents": parents,
        "message_digest": _sha256_bytes(message),
        "message": message,
    }


def _post_commit_paths(root: Path, parent: str, commit_oid: str) -> list[str]:
    output = _run_git(
        root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "-r",
        "-z",
        parent,
        commit_oid,
    ).stdout
    try:
        return sorted(
            (item.decode("utf-8") for item in output.split(b"\0") if item),
            key=lambda value: value.encode("utf-8"),
        )
    except UnicodeDecodeError as exc:
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "The Commit path evidence is malformed.") from exc


def _validated_committed_state(
    *,
    execution: LocalCommitExecution,
    stage_execution: StageExecution,
    plan: CommitPlan,
    root: Path,
    run: Any,
    entries: list[Any],
    apply_session: ApplySession,
    commit_oid: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if (
        execution.commit_plan_id != plan.id
        or execution.stage_execution_id != stage_execution.id
        or execution.commit_plan_digest != plan.plan_digest
        or execution.stage_digest != stage_execution.stage_digest
        or execution.staged_entries_digest != stage_execution.staged_entries_digest
        or execution.base_head != plan.base_head
        or execution.branch_ref != plan.branch_ref
        or execution.commit_oid not in {None, commit_oid}
        or execution.parent_oid not in {None, plan.base_head}
    ):
        raise _failure(
            "COMMIT_INTEGRITY_BLOCKED",
            "The recoverable local Commit binding is invalid.",
        )
    _assert_targets_match(root, entries)
    commit = _commit_object(root, commit_oid)
    expected_paths = sorted(
        (str(item.get("path")) for item in _decoded_list(execution.staged_entries_json)),
        key=lambda value: value.encode("utf-8"),
    )
    if (
        commit["parents"] != [plan.base_head]
        or commit["message"] != _commit_message(plan)
        or commit["message_digest"] != execution.message_digest
        or (execution.tree_oid is not None and execution.tree_oid != commit["tree"])
        or _post_commit_paths(root, plan.base_head, commit_oid) != expected_paths
        or _git_text(root, "rev-parse", "HEAD") != commit_oid
        or _branch_ref(root, plan.branch) != plan.branch_ref
        or _staged_path_set(root, commit_oid)
    ):
        raise _failure(
            "COMMIT_INTEGRITY_BLOCKED",
            "The resulting local Commit does not match its reviewed intent.",
        )
    baseline = _decoded_object(apply_session.after_evidence_json).get("global")
    post_global = _global_evidence_after_mutation(
        run,
        root,
        target_paths=[entry.repository_path for entry in entries],
        baseline=_decoded_object(baseline),
    )
    post = _safe_global_evidence(post_global)
    post["refs_excluding_current_fingerprint"] = _refs_fingerprint_excluding(
        root, plan.branch_ref
    )
    pre = _decoded_object(execution.pre_commit_evidence_json)
    stage_boundary = _decoded_object(stage_execution.post_stage_evidence_json)
    post_index = _decoded_object(post.get("index"))
    stage_index = _decoded_object(stage_boundary.get("index"))
    if (
        post.get("branch") != pre.get("branch")
        or post.get("head") != commit_oid
        or post.get("source_digest") != pre.get("source_digest")
        or post.get("local_config_fingerprint") != pre.get("local_config_fingerprint")
        or post.get("remote_fingerprint") != pre.get("remote_fingerprint")
        or post.get("refs_excluding_current_fingerprint")
        != pre.get("refs_excluding_current_fingerprint")
        or post_index.get("fingerprint") != stage_index.get("fingerprint")
        or int(post_index.get("staged_path_count") or 0) != 0
    ):
        raise _failure("COMMIT_INTEGRITY_BLOCKED", "Repository boundaries changed during Commit.")
    _assert_targets_match(root, entries)
    if (
        _git_text(root, "rev-parse", "HEAD") != commit_oid
        or _branch_ref(root, plan.branch) != plan.branch_ref
        or _staged_path_set(root, commit_oid)
    ):
        raise _failure(
            "COMMIT_INTEGRITY_BLOCKED",
            "The local Commit boundary changed during receipt settlement.",
        )
    return commit, post, expected_paths


def _finalize_commit_receipt(
    session: Session,
    *,
    execution: LocalCommitExecution,
    stage_execution: StageExecution,
    plan: CommitPlan,
    root: Path,
    run: Any,
    entries: list[Any],
    apply_session: ApplySession,
    commit_oid: str,
) -> LocalCommitExecution:
    execution_pk = execution.id
    stage_pk = stage_execution.id
    first_commit, first_post, first_paths = _validated_committed_state(
        execution=execution,
        stage_execution=stage_execution,
        plan=plan,
        root=root,
        run=run,
        entries=entries,
        apply_session=apply_session,
        commit_oid=commit_oid,
    )
    plan, refreshed_binding = _refresh_latest_plan_verification(
        session,
        owner_id=execution.owner_id,
        plan=plan,
    )
    (
        apply_session,
        _apply_plan,
        _candidate,
        run,
        _pack,
        entries,
    ) = refreshed_binding
    stage_execution = session.get(StageExecution, stage_pk)
    execution = session.get(LocalCommitExecution, execution_pk)
    if (
        stage_execution is None
        or execution is None
        or stage_execution.owner_id != plan.owner_id
        or execution.owner_id != plan.owner_id
        or stage_execution.commit_plan_id != plan.id
        or execution.commit_plan_id != plan.id
        or execution.stage_execution_id != stage_execution.id
        or stage_execution.state != "STAGED"
        or execution.state not in {"COMMITTING", "FAILED"}
        or execution.commit_oid != commit_oid
    ):
        raise _failure(
            "COMMIT_INTEGRITY_BLOCKED",
            "The recoverable Commit intent changed during receipt settlement.",
        )
    commit, post, expected_paths = _validated_committed_state(
        execution=execution,
        stage_execution=stage_execution,
        plan=plan,
        root=root,
        run=run,
        entries=entries,
        apply_session=apply_session,
        commit_oid=commit_oid,
    )
    if (
        first_commit != commit
        or canonical_json(first_post) != canonical_json(post)
        or first_paths != expected_paths
    ):
        raise _failure(
            "COMMIT_INTEGRITY_BLOCKED",
            "Repository evidence changed during Commit receipt settlement.",
        )
    receipt = {
        "schema": "twos.local_commit_receipt.v1",
        "commit_execution_id": execution.commit_execution_id,
        "commit_plan_digest": plan.plan_digest,
        "stage_digest": execution.stage_digest,
        "parent_oid": plan.base_head,
        "commit_oid": commit_oid,
        "tree_oid": commit["tree"],
        "message_digest": commit["message_digest"],
        "changed_path_identities": sorted(
            _sha256_bytes(path.encode("utf-8")) for path in expected_paths
        ),
        "post_commit": post,
    }
    execution.tree_oid = execution.tree_oid or str(commit["tree"])
    execution.commit_oid = execution.commit_oid or commit_oid
    execution.parent_oid = execution.parent_oid or plan.base_head
    execution.post_commit_evidence_json = canonical_json(post)
    execution.receipt_digest = canonical_sha256(receipt)
    execution.state = "COMMITTED"
    execution.finished_at = execution.finished_at or utc_now()
    session.commit()
    return execution


def create_local_commit(
    session: Session,
    *,
    owner_id: int,
    plan: CommitPlan,
    stage_execution: StageExecution,
    source_repo: Path,
    expected_plan_digest: str | None = None,
    expected_stage_digest: str | None = None,
) -> tuple[LocalCommitExecution, bool]:
    if (
        plan.owner_id != owner_id
        or stage_execution.owner_id != owner_id
        or stage_execution.commit_plan_id != plan.id
    ):
        raise _failure("COMMIT_PLAN_NOT_FOUND", "Commit Plan not found.")
    if expected_plan_digest is not None and expected_plan_digest != plan.plan_digest:
        raise _failure("COMMIT_PLAN_CHANGED", "The Commit Plan identity changed.")
    if (
        stage_execution.state != "STAGED"
        or not stage_execution.stage_digest
        or (
            expected_stage_digest is not None
            and expected_stage_digest != stage_execution.stage_digest
        )
    ):
        raise _failure("STAGE_NOT_VERIFIED", "The exact Stage result is not verified.")
    existing = session.scalar(
        select(LocalCommitExecution).where(
            LocalCommitExecution.owner_id == owner_id,
            LocalCommitExecution.stage_execution_id == stage_execution.id,
        )
    )
    if existing is not None and existing.state == "COMMITTED":
        return existing, False
    verification = _plan_verification(session, plan)
    apply_session, _apply_plan, _candidate, run, _pack, entries = _bound_verification(
        session,
        owner_id=owner_id,
        verification=verification,
    )
    root = _verified_root(run, source_repo)
    with _commit_builder_repository_lock(plan.repository_locator_fingerprint):
        plan_pk = plan.id
        stage_pk = stage_execution.id
        session.expire_all()
        plan = session.get(CommitPlan, plan_pk)
        stage_execution = session.get(StageExecution, stage_pk)
        if (
            plan is None
            or stage_execution is None
            or plan.owner_id != owner_id
            or stage_execution.owner_id != owner_id
            or stage_execution.commit_plan_id != plan.id
            or stage_execution.state != "STAGED"
            or not stage_execution.stage_digest
        ):
            raise _failure("STAGE_NOT_VERIFIED", "The exact Stage result is not verified.")
        if (
            plan.status_at_creation != "READY"
            or plan.policy_version != COMMIT_BUILDER_POLICY_VERSION
        ):
            raise _failure("COMMIT_PLAN_EXPIRED", "The Commit Plan is not eligible for Commit.")
        if expected_plan_digest is not None and expected_plan_digest != plan.plan_digest:
            raise _failure("COMMIT_PLAN_CHANGED", "The Commit Plan identity changed.")
        if (
            expected_stage_digest is not None
            and expected_stage_digest != stage_execution.stage_digest
        ):
            raise _failure("STAGE_NOT_VERIFIED", "The exact Stage result is not verified.")
        existing = session.scalar(
            select(LocalCommitExecution).where(
                LocalCommitExecution.owner_id == owner_id,
                LocalCommitExecution.stage_execution_id == stage_execution.id,
            )
        )
        if existing is not None and existing.state == "COMMITTED":
            return existing, False
        if existing is not None and existing.state in {"BLOCKED", "INTEGRITY_BLOCKED"}:
            return existing, False
        verification = _plan_verification(session, plan)
        apply_session, _apply_plan, _candidate, run, _pack, entries = _bound_verification(
            session,
            owner_id=owner_id,
            verification=verification,
        )
        if _repository_mutation_blocker(
            session,
            repository_locator_fingerprint=plan.repository_locator_fingerprint,
            exclude_plan_id=apply_session.apply_plan_id,
        ) is not None:
            raise _failure("REPOSITORY_MUTATION_ACTIVE", "Another repository mutation is active.")
        if _branch_ref(root, plan.branch) != plan.branch_ref:
            raise _failure("BRANCH_CHANGED", "The branch binding changed.")
        head = _git_text(root, "rev-parse", "HEAD")
        if existing is not None and head != plan.base_head:
            if existing.commit_oid and head == existing.commit_oid:
                return (
                    _finalize_commit_receipt(
                        session,
                        execution=existing,
                        stage_execution=stage_execution,
                        plan=plan,
                        root=root,
                        run=run,
                        entries=entries,
                        apply_session=apply_session,
                        commit_oid=head,
                    ),
                    False,
                )
            existing.state = "INTEGRITY_BLOCKED"
            existing.failure_evidence_json = canonical_json([{"code": "HEAD_CHANGED"}])
            session.commit()
            raise _failure("COMMIT_INTEGRITY_BLOCKED", "HEAD changed before Commit settlement.")
        if head != plan.base_head:
            raise _failure("HEAD_CHANGED", "HEAD changed after Commit Plan review.")
        planned = _decoded_list(stage_execution.planned_entries_json)
        staged_entries = _verify_exact_stage(
            root,
            head=plan.base_head,
            planned=planned,
        )
        _assert_targets_match(root, entries)
        if canonical_sha256(staged_entries) != stage_execution.staged_entries_digest:
            raise _failure("STAGE_INTEGRITY_BLOCKED", "The Stage receipt no longer matches the index.")
        baseline = _decoded_object(apply_session.after_evidence_json).get("global")
        pre_global = _global_evidence_after_mutation(
            run,
            root,
            target_paths=[entry.repository_path for entry in entries],
            baseline=_decoded_object(baseline),
        )
        pre_commit = _safe_global_evidence(pre_global)
        pre_commit["refs_excluding_current_fingerprint"] = _refs_fingerprint_excluding(
            root, plan.branch_ref
        )
        stage_post = _decoded_object(stage_execution.post_stage_evidence_json)
        if (
            pre_commit.get("head") != plan.base_head
            or pre_commit.get("branch") != plan.branch
            or pre_commit.get("source_digest") != stage_post.get("source_digest")
            or pre_commit.get("local_config_fingerprint")
            != stage_post.get("local_config_fingerprint")
            or pre_commit.get("remote_fingerprint") != stage_post.get("remote_fingerprint")
            or pre_commit.get("refs_fingerprint") != stage_post.get("refs_fingerprint")
            or _decoded_object(pre_commit.get("index")).get("fingerprint")
            != _decoded_object(stage_post.get("index")).get("fingerprint")
        ):
            raise _failure("COMMIT_PLAN_EXPIRED", "Repository evidence changed after Stage.")
        _assert_targets_match(root, entries)
        pre_digest = canonical_sha256(pre_commit)
        message = _commit_message(plan)
        intent_digest = canonical_sha256(
            {
                "schema": "twos.local_commit_intent.v1",
                "plan_digest": plan.plan_digest,
                "stage_digest": stage_execution.stage_digest,
                "base_head": plan.base_head,
                "branch_ref": plan.branch_ref,
                "staged_entries_digest": stage_execution.staged_entries_digest,
                "message_digest": _sha256_bytes(message),
                "pre_commit_evidence_digest": pre_digest,
            }
        )
        if existing is None:
            existing = LocalCommitExecution(
                commit_execution_id="commit_" + intent_digest[:40],
                owner_id=owner_id,
                commit_plan_id=plan.id,
                stage_execution_id=stage_execution.id,
                commit_plan_public_id=plan.commit_plan_id,
                commit_plan_digest=plan.plan_digest,
                stage_execution_public_id=stage_execution.stage_execution_id,
                stage_digest=str(stage_execution.stage_digest),
                repository_locator_fingerprint=plan.repository_locator_fingerprint,
                branch=plan.branch,
                branch_ref=plan.branch_ref,
                base_head=plan.base_head,
                staged_entries_json=stage_execution.staged_entries_json,
                staged_entries_digest=stage_execution.staged_entries_digest,
                subject_digest=_sha256_bytes(plan.subject.encode("utf-8")),
                body_digest=_sha256_bytes(plan.body.encode("utf-8")),
                message_digest=_sha256_bytes(message),
                intent_digest=intent_digest,
                pre_commit_evidence_json=canonical_json(pre_commit),
                pre_commit_evidence_digest=pre_digest,
                state="COMMITTING",
            )
            session.add(existing)
            session.flush()
            created = True
            session.commit()
            existing = session.get(LocalCommitExecution, existing.id) or existing
        else:
            created = False
            if existing.intent_digest != intent_digest:
                raise _failure("COMMIT_INTEGRITY_BLOCKED", "The Commit intent binding is invalid.")
            if existing.state == "INTEGRITY_BLOCKED":
                return existing, False
            existing.state = "COMMITTING"
            session.commit()
        try:
            commit_pk = existing.id
            stage_pk = stage_execution.id
            plan, refreshed_binding = _refresh_latest_plan_verification(
                session,
                owner_id=owner_id,
                plan=plan,
            )
            (
                apply_session,
                _apply_plan,
                _candidate,
                run,
                _pack,
                entries,
            ) = refreshed_binding
            stage_execution = session.get(StageExecution, stage_pk)
            existing = session.get(LocalCommitExecution, commit_pk)
            if (
                stage_execution is None
                or existing is None
                or stage_execution.owner_id != owner_id
                or existing.owner_id != owner_id
                or stage_execution.commit_plan_id != plan.id
                or existing.commit_plan_id != plan.id
                or existing.stage_execution_id != stage_execution.id
                or existing.state != "COMMITTING"
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The durable Commit intent changed before Git mutation.",
                )
            if existing.commit_oid:
                commit_oid = existing.commit_oid
                commit = _commit_object(root, commit_oid)
                tree_oid = str(commit["tree"])
            else:
                if _branch_ref(root, plan.branch) != plan.branch_ref or _git_text(root, "rev-parse", "HEAD") != plan.base_head:
                    raise _failure("HEAD_CHANGED", "HEAD changed immediately before Commit.")
                _verify_exact_stage(root, head=plan.base_head, planned=planned)
                _assert_targets_match(root, entries)
                with _stable_index_snapshot(root) as index_snapshot:
                    _verify_exact_stage(
                        root,
                        head=plan.base_head,
                        planned=planned,
                        index_file=index_snapshot,
                    )
                    tree_oid_bytes = _run_git(
                        root,
                        "write-tree",
                        index_file=index_snapshot,
                    ).stdout
                    try:
                        tree_oid = tree_oid_bytes.decode("ascii").strip()
                    except UnicodeDecodeError as exc:
                        raise _failure(
                            "COMMIT_INTEGRITY_BLOCKED",
                            "Git returned an invalid tree identity.",
                        ) from exc
                if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", tree_oid):
                    raise _failure(
                        "COMMIT_INTEGRITY_BLOCKED",
                        "Git returned an invalid tree identity.",
                    )
                commit_oid = _run_git(
                    root,
                    "commit-tree",
                    tree_oid,
                    "-p",
                    plan.base_head,
                    input_bytes=message,
                ).stdout.decode("ascii").strip()
                if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit_oid):
                    raise _failure("COMMIT_INTEGRITY_BLOCKED", "Git returned an invalid Commit identity.")
                commit = _commit_object(root, commit_oid)
                if (
                    commit["tree"] != tree_oid
                    or commit["parents"] != [plan.base_head]
                    or commit["message"] != message
                ):
                    raise _failure("COMMIT_INTEGRITY_BLOCKED", "The Commit object does not match its intent.")
                existing.tree_oid = tree_oid
                existing.commit_oid = commit_oid
                existing.parent_oid = plan.base_head
                session.commit()
            plan, refreshed_binding = _refresh_latest_plan_verification(
                session,
                owner_id=owner_id,
                plan=plan,
            )
            (
                apply_session,
                _apply_plan,
                _candidate,
                run,
                _pack,
                entries,
            ) = refreshed_binding
            stage_execution = session.get(StageExecution, stage_pk)
            existing = session.get(LocalCommitExecution, commit_pk)
            if (
                stage_execution is None
                or existing is None
                or stage_execution.owner_id != owner_id
                or existing.owner_id != owner_id
                or stage_execution.commit_plan_id != plan.id
                or existing.commit_plan_id != plan.id
                or existing.stage_execution_id != stage_execution.id
                or existing.state != "COMMITTING"
                or existing.commit_oid != commit_oid
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The durable Commit intent changed before ref settlement.",
                )
            _run_git(
                root,
                "update-ref",
                plan.branch_ref,
                commit_oid,
                plan.base_head,
            )
            plan, refreshed_binding = _refresh_latest_plan_verification(
                session,
                owner_id=owner_id,
                plan=plan,
            )
            (
                apply_session,
                _apply_plan,
                _candidate,
                run,
                _pack,
                entries,
            ) = refreshed_binding
            stage_execution = session.get(StageExecution, stage_pk)
            existing = session.get(LocalCommitExecution, commit_pk)
            if (
                stage_execution is None
                or existing is None
                or stage_execution.owner_id != owner_id
                or existing.owner_id != owner_id
                or stage_execution.commit_plan_id != plan.id
                or existing.commit_plan_id != plan.id
                or existing.stage_execution_id != stage_execution.id
                or existing.state != "COMMITTING"
                or existing.commit_oid != commit_oid
            ):
                raise _failure(
                    "COMMIT_INTEGRITY_BLOCKED",
                    "The durable Commit intent changed during ref settlement.",
                )
            return (
                _finalize_commit_receipt(
                    session,
                    execution=existing,
                    stage_execution=stage_execution,
                    plan=plan,
                    root=root,
                    run=run,
                    entries=entries,
                    apply_session=apply_session,
                    commit_oid=commit_oid,
                ),
                created,
            )
        except (CommitBuilderError, ApplySessionError, OSError, RuntimeError, ValueError) as exc:
            session.rollback()
            current = session.get(LocalCommitExecution, existing.id) or existing
            current_head = ""
            try:
                current_head = _git_text(root, "rev-parse", "HEAD")
            except CommitBuilderError:
                pass
            current.state = (
                "INTEGRITY_BLOCKED"
                if current_head != plan.base_head
                or (
                    isinstance(exc, CommitBuilderError)
                    and exc.code == "COMMIT_INTEGRITY_BLOCKED"
                )
                else "FAILED"
            )
            current.failure_evidence_json = canonical_json(
                [{"code": getattr(exc, "code", "COMMIT_FAILED")}]
            )
            if current.state == "INTEGRITY_BLOCKED":
                current.finished_at = current.finished_at or utc_now()
            session.commit()
            if isinstance(exc, CommitBuilderError):
                raise
            raise _failure("COMMIT_FAILED", "The local Commit operation failed safely.") from exc


def _stage_out(row: StageExecution | None) -> dict[str, Any] | None:
    if row is None:
        return None
    active_failures = (
        [] if row.state == "STAGED" else _decoded_list(row.failure_evidence_json)
    )
    return {
        "id": row.stage_execution_id,
        "state": row.state,
        "status": row.state,
        "status_label": {
            "STAGING": "STAGE RECOVERY REQUIRED",
            "STAGED": "STAGED",
            "BLOCKED": "BLOCKED",
            "FAILED": "FAILED",
            "INTEGRITY_BLOCKED": "INTEGRITY BLOCKED",
        }.get(row.state, row.state),
        "approved_files": [
            {
                "path": item.get("path"),
                "operation": item.get("operation"),
            }
            for item in _decoded_list(row.staged_entries_json)
            if isinstance(item, dict)
        ],
        "staged_path_count": len(_decoded_list(row.staged_entries_json)),
        "stage_digest": row.stage_digest,
        "blockers": active_failures,
        "failure_evidence": active_failures,
        "next_action": (
            "Select Create Local Commit."
            if row.state == "STAGED"
            else (
                "Select Stage Approved Files again to reconcile the existing exact Stage intent."
                if row.state in {"STAGING", "FAILED"}
                else "Review the Stage evidence before trying again."
            )
        ),
        "created_at": row.created_at.isoformat() + "Z",
        "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
        "advanced": {
            "stage_digest": row.stage_digest,
            "planned_entries_digest": row.planned_entries_digest,
            "staged_entries_digest": row.staged_entries_digest,
            "staged_path_identities": [
                item.get("path_identity")
                for item in _decoded_list(row.staged_entries_json)
                if isinstance(item, dict) and item.get("path_identity")
            ],
            "historical_failure_evidence": _decoded_list(row.failure_evidence_json),
        },
    }


def _commit_out(row: LocalCommitExecution | None) -> dict[str, Any] | None:
    if row is None:
        return None
    active_failures = (
        [] if row.state == "COMMITTED" else _decoded_list(row.failure_evidence_json)
    )
    return {
        "id": row.commit_execution_id,
        "state": row.state,
        "status": row.state,
        "status_label": {
            "COMMITTING": "COMMIT RECOVERY REQUIRED",
            "COMMITTED": "LOCAL COMMIT CREATED",
            "BLOCKED": "BLOCKED",
            "FAILED": "FAILED",
            "INTEGRITY_BLOCKED": "INTEGRITY BLOCKED",
        }.get(row.state, row.state),
        "commit_oid": row.commit_oid,
        "commit_sha": row.commit_oid,
        "parent_sha": row.parent_oid,
        "message_digest": row.message_digest,
        "receipt_digest": row.receipt_digest,
        "blockers": active_failures,
        "failure_evidence": active_failures,
        "next_action": (
            "Review the local Commit evidence, then continue to the separate explicit Push readiness action."
            if row.state == "COMMITTED"
            else (
                "Select Create Local Commit again to reconcile the existing exact Commit intent."
                if row.state in {"COMMITTING", "FAILED"}
                else "Review the local Commit blocker evidence."
            )
        ),
        "created_at": row.created_at.isoformat() + "Z",
        "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
        "advanced": {
            "commit_oid": row.commit_oid,
            "parent_oid": row.parent_oid,
            "tree_oid": row.tree_oid,
            "message_digest": row.message_digest,
            "receipt_digest": row.receipt_digest,
            "intent_digest": row.intent_digest,
            "historical_failure_evidence": _decoded_list(row.failure_evidence_json),
        },
    }


def commit_plan_out(
    plan: CommitPlan,
    *,
    effective_status: str | None = None,
    blockers: list[dict[str, Any]] | None = None,
    stage_execution: StageExecution | None = None,
    commit_execution: LocalCommitExecution | None = None,
) -> dict[str, Any]:
    status = effective_status or plan.status_at_creation
    verified_paths = _decoded_list(plan.verified_paths_json)
    return {
        "id": plan.commit_plan_id,
        "plan_digest": plan.plan_digest,
        "status": status,
        "status_label": {
            "DRAFT": "DRAFT",
            "READY": "READY TO STAGE",
            "STAGED": "STAGED",
            "EXPIRED": "EXPIRED",
            "BLOCKED": "BLOCKED",
            "COMMITTED": "LOCAL COMMIT CREATED",
        }.get(status, status),
        "status_at_creation": plan.status_at_creation,
        "subject": plan.subject,
        "body": plan.body,
        "created_at": plan.created_at.isoformat() + "Z",
        "verified_paths": [
            {
                "path": item.get("path"),
                "operation": item.get("operation"),
            }
            for item in verified_paths
            if isinstance(item, dict)
        ],
        "excluded_paths": _decoded_list(plan.excluded_paths_json),
        "validation": _decoded_list(plan.validation_json),
        "blockers": blockers if blockers is not None else _decoded_list(plan.blocker_codes_json),
        "stage": _stage_out(stage_execution),
        "commit": _commit_out(commit_execution),
        "actions": {
            "can_stage": bool(
                status == "READY"
                and (
                    stage_execution is None
                    or stage_execution.state in {"STAGING", "FAILED"}
                )
            ),
            "can_commit": bool(
                status in {"READY", "STAGED"}
                and stage_execution is not None
                and stage_execution.state == "STAGED"
                and (
                    commit_execution is None
                    or commit_execution.state in {"COMMITTING", "FAILED"}
                )
            ),
        },
        "boundaries": [
            "Stage includes only the exact verified paths.",
            "Local Commit requires a separate explicit Owner action.",
            "This Stage + Local Commit workflow never performs Push, merge, rebase, tag, branch change, or remote change.",
        ],
        "advanced": {
            "policy_version": plan.policy_version,
            "plan_digest": plan.plan_digest,
            "binding_digest": plan.binding_digest,
            "verification_id": plan.verification_public_id,
            "verification_digest": plan.verification_digest,
            "apply_session_id": plan.apply_session_public_id,
            "journal_digest": plan.journal_digest,
            "apply_plan_id": plan.apply_plan_public_id,
            "apply_plan_digest": plan.apply_plan_digest,
            "candidate_id": plan.candidate_public_id,
            "candidate_digest": plan.candidate_digest,
            "repository_identity": plan.sanitized_repository_identity,
            "repository_locator_fingerprint": plan.repository_locator_fingerprint,
            "branch": plan.branch,
            "base_head": plan.base_head,
            "source_snapshot_identity": plan.source_snapshot_identity,
            "boundary_evidence": _decoded_object(plan.boundary_evidence_json),
        },
    }


def commit_builder_review(
    session: Session,
    *,
    owner_id: int,
    post_apply_verification: PostApplyVerification,
    source_repo: Path,
    effective_status_override: str | None = None,
) -> dict[str, Any]:
    if post_apply_verification.owner_id != owner_id:
        raise _failure("VERIFICATION_NOT_FOUND", "Post-Apply Verification not found.")
    plan = _plan_for_verification(
        session,
        owner_id=owner_id,
        verification_id=post_apply_verification.id,
    )
    if plan is None:
        try:
            _bound_verification(
                session,
                owner_id=owner_id,
                verification=post_apply_verification,
            )
            eligibility = {
                "status": "READY",
                "can_review": True,
                "next_action": "Review Commit Plan.",
                "blockers": [],
            }
        except CommitBuilderError as exc:
            eligibility = {
                "status": "BLOCKED",
                "can_review": False,
                "next_action": exc.message,
                "blockers": [{"code": exc.code, "message": exc.message}],
            }
        return {
            "post_apply_verification_id": post_apply_verification.verification_id,
            "eligibility": eligibility,
            "plan": None,
            "stage": None,
            "commit": None,
            "actions": {
                "can_review_commit_plan": eligibility["can_review"],
                "can_stage_approved_files": False,
                "can_create_local_commit": False,
            },
        }
    stage_execution = session.scalar(
        select(StageExecution).where(
            StageExecution.owner_id == owner_id,
            StageExecution.commit_plan_id == plan.id,
        )
    )
    commit_execution = (
        session.scalar(
            select(LocalCommitExecution).where(
                LocalCommitExecution.owner_id == owner_id,
                LocalCommitExecution.stage_execution_id == stage_execution.id,
            )
        )
        if stage_execution is not None
        else None
    )
    if effective_status_override is None:
        effective, blockers = commit_plan_effective_status(
            session,
            owner_id=owner_id,
            plan=plan,
            source_repo=source_repo,
        )
    else:
        effective = str(effective_status_override).upper()
        if effective not in {"READY", "STAGED", "COMMITTED", "EXPIRED", "BLOCKED"}:
            raise _failure(
                "COMMIT_BUILDER_STATUS_INVALID",
                "The durable Commit workflow result cannot be rendered safely.",
            )
        if effective == "READY" and (
            plan.status_at_creation != "READY"
            or stage_execution is not None
            or commit_execution is not None
        ):
            raise _failure(
                "COMMIT_BUILDER_STATUS_INVALID",
                "The durable Commit workflow result cannot be rendered safely.",
            )
        if effective == "STAGED" and (
            stage_execution is None
            or stage_execution.state != "STAGED"
            or commit_execution is not None
        ):
            raise _failure(
                "COMMIT_BUILDER_STATUS_INVALID",
                "The durable Stage result cannot be rendered safely.",
            )
        if effective == "COMMITTED" and (
            stage_execution is None
            or stage_execution.state != "STAGED"
            or commit_execution is None
            or commit_execution.state != "COMMITTED"
        ):
            raise _failure(
                "COMMIT_BUILDER_STATUS_INVALID",
                "The durable local Commit result cannot be rendered safely.",
            )
        blockers = (
            _decoded_list(plan.blocker_codes_json)
            if effective in {"EXPIRED", "BLOCKED"}
            else []
        )
    plan_payload = commit_plan_out(
        plan,
        effective_status=effective,
        blockers=blockers,
        stage_execution=stage_execution,
        commit_execution=commit_execution,
    )
    stage_payload = _stage_out(stage_execution)
    commit_payload = _commit_out(commit_execution)
    return {
        "post_apply_verification_id": post_apply_verification.verification_id,
        "eligibility": {
            "status": effective,
            "can_review": True,
            "next_action": {
                "READY": "Stage Approved Files.",
                "STAGED": "Create Local Commit.",
                "COMMITTED": "Review the local Commit result.",
                "EXPIRED": "Run Verify Applied Changes again.",
                "BLOCKED": "Review the Commit Plan blockers.",
            }.get(effective, "Review the Commit Plan."),
            "blockers": blockers,
        },
        "plan": plan_payload,
        "stage": stage_payload,
        "commit": commit_payload,
        "actions": {
            "can_review_commit_plan": True,
            "can_stage_approved_files": bool(
                effective == "READY"
                and (
                    stage_execution is None
                    or stage_execution.state in {"STAGING", "FAILED"}
                )
            ),
            "can_create_local_commit": bool(
                effective == "STAGED"
                and stage_execution is not None
                and stage_execution.state == "STAGED"
                and (
                    commit_execution is None
                    or commit_execution.state in {"COMMITTING", "FAILED"}
                )
            ),
        },
    }
