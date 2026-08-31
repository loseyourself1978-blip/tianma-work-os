from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import codex_exec_bridge
from .ai_orchestration import (
    is_verified_real_invocation,
    verified_actual_model_identity,
)
from .models import (
    AIModelInvocationEvidence,
    AuditEvent,
    CodexExecutionAttempt,
    CodexResultArtifact,
    CodexResultEnvelope,
    CodexLifecycleSnapshot,
    CodexRun,
    CodexRunMonitor,
    HandoffInstructionDraft,
    HandoffReview,
    OwnerAcceptanceSession,
    utc_now,
)
from .run_lifecycle import (
    LifecycleReconciliationError,
    _reconciliation_lock,
    reconcile_execution_attempt,
    settle_reconciliation_error,
)


RESULT_INTAKE_SCHEMA = "twos.codex_result_envelope.v1"
RESULT_INTAKE_POLICY = "twos.result_intake.vol18.004"
# Explicit safety contract used by both the service and Owner-facing handoff.
AUTOMATION_BOUNDARIES = (
    "No automatic Result acceptance",
    "Automatic Candidate metadata materialization; no automatic Candidate acceptance",
    "No automatic Apply",
    "No automatic Revert",
    "No automatic next Codex Run",
)
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_RESULT_STRING = 64 * 1024
MAX_RESULT_ITEMS = 1000
MAX_RESULT_DEPTH = 12
PERSISTED_RESULT_SETTLEMENT_SECONDS = 5.0


def _materialize_result_delivery_candidate(
    session: Session,
    *,
    owner_id: int,
    envelope: CodexResultEnvelope,
) -> None:
    # Local import preserves the established result-intake/connectivity module
    # boundary while settlement adds only immutable Candidate metadata.
    from .delivery_candidates import (
        ManifestError,
        materialize_result_delivery_candidate,
    )

    try:
        materialize_result_delivery_candidate(
            session,
            owner_id=owner_id,
            envelope=envelope,
        )
    except ManifestError as exc:
        raise ResultIntakeError(
            "CANDIDATE_MATERIALIZATION_BLOCKED",
            str(exc),
            monitor_state="RESULT_INTEGRITY_BLOCKED",
        ) from exc


MONITOR_STATES = frozenset(
    {
        "QUEUED",
        "STARTING",
        "RUNNING",
        "VERIFYING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "PROCESS_LOST",
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    }
)
RECOVERY_STATES = frozenset(
    {
        "NONE",
        "MONITORING_RESUMED",
        "RESULT_RECOVERED",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
        "INTEGRITY_BLOCKED",
    }
)
ACTIVE_MONITOR_STATES = frozenset({"QUEUED", "STARTING", "RUNNING", "VERIFYING"})
PROCESS_TERMINAL_STATES = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "PROCESS_LOST"}
)
RESULT_TERMINAL_STATES = frozenset(
    {"RESULT_AVAILABLE", "RESULT_UNAVAILABLE", "RESULT_INTEGRITY_BLOCKED"}
)
RUN_TO_MONITOR_STATE = {
    "queued": "QUEUED",
    "starting": "STARTING",
    "running": "RUNNING",
    "verifying": "VERIFYING",
    "completed": "COMPLETED",
    "failed": "FAILED",
    "blocked": "FAILED",
    "cancelled": "CANCELLED",
    "timed_out": "TIMED_OUT",
}
TERMINAL_RUN_STATES = frozenset(
    {"completed", "failed", "blocked", "cancelled", "timed_out"}
)
SOURCE_SNAPSHOT_UNAVAILABLE = "SOURCE_SNAPSHOT_UNAVAILABLE"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|credential|authorization|cookie|"
    r"api[_-]?key|private[_-]?key|environment|env(?:iron)?(?:ment)?_?variables?)",
    re.IGNORECASE,
)
_CREDENTIAL_URL_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@"
)
_FILE_URI_RE = re.compile(r"\bfile://[^\s,;'\"<>]+", re.IGNORECASE)
_ABSOLUTE_POSIX_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.:/-])/(?!/)[^\s,;:'\"<>]+"
)
_ABSOLUTE_WINDOWS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:\\(?:[^\\\s]+\\?)+"
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_PROVIDER_TOKEN_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}\b")
_COMMON_CREDENTIAL_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|"
    r"AKIA[A-Z0-9]{16})\b"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:authorization|api[_ -]?key|password|passphrase|"
    r"client[_ -]?secret|session[_ -]?token|access[_ -]?token|"
    r"refresh[_ -]?token|cookie|[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|"
    r"PASSWORD|PASSPHRASE|API_KEY|PRIVATE_KEY|CREDENTIAL)[A-Z0-9_]*)"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


class ResultIntakeError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        monitor_state: str = "RESULT_INTEGRITY_BLOCKED",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.monitor_state = monitor_state


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sanitize_text(value: str) -> str:
    text = value.replace("\x00", "")
    text = _PRIVATE_KEY_RE.sub("[private key withheld]", text)
    text = _CREDENTIAL_URL_RE.sub(r"\g<scheme>[credentials withheld]@", text)
    text = _FILE_URI_RE.sub("[absolute file URI withheld]", text)
    text = _BEARER_RE.sub("Bearer [credential withheld]", text)
    text = _PROVIDER_TOKEN_RE.sub("[credential withheld]", text)
    text = _COMMON_CREDENTIAL_RE.sub("[credential withheld]", text)
    text = _CREDENTIAL_ASSIGNMENT_RE.sub(
        lambda match: f"[credential withheld]{match.group(1)}",
        text,
    )
    text = _ABSOLUTE_POSIX_PATH_RE.sub("[absolute path withheld]", text)
    text = _ABSOLUTE_WINDOWS_PATH_RE.sub("[absolute path withheld]", text)
    if len(text) > MAX_RESULT_STRING:
        text = text[:MAX_RESULT_STRING] + "… [truncated]"
    return text


def sanitize_result_value(
    value: object,
    *,
    _depth: int = 0,
) -> object:
    """Return a bounded, display-safe JSON value without secret-shaped fields."""
    if _depth > MAX_RESULT_DEPTH:
        return "[nested content withheld]"
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, bytes):
        return {
            "content_kind": "binary",
            "size": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
            "content_included": False,
        }
    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= MAX_RESULT_ITEMS:
                output["_truncated"] = True
                break
            key = _sanitize_text(str(raw_key))[:240]
            if _SENSITIVE_KEY_RE.search(key):
                output[key] = "[credential withheld]"
            elif key.lower() in {
                "stdout",
                "stderr",
                "raw_output",
                "raw_stdout",
                "raw_stderr",
                "process_command",
                "command_line",
            }:
                text = str(raw_value or "")
                output[key] = {
                    "present": bool(text),
                    "size": len(text.encode("utf-8", errors="replace")),
                    "sha256": hashlib.sha256(
                        text.encode("utf-8", errors="replace")
                    ).hexdigest(),
                    "content_included": False,
                }
            else:
                output[key] = sanitize_result_value(
                    raw_value,
                    _depth=_depth + 1,
                )
        return output
    if isinstance(value, (list, tuple)):
        output = [
            sanitize_result_value(item, _depth=_depth + 1)
            for item in value[:MAX_RESULT_ITEMS]
        ]
        if len(value) > MAX_RESULT_ITEMS:
            output.append("[additional items withheld]")
        return output
    return _sanitize_text(str(value))


def capture_process_start_identity(process_id: int) -> str:
    """Hash PID creation evidence without persisting a command line."""
    if type(process_id) is not int or process_id <= 0:
        return ""
    proc_stat = Path(f"/proc/{process_id}/stat")
    evidence = ""
    try:
        if proc_stat.is_file():
            fields = proc_stat.read_text(encoding="utf-8", errors="strict").split()
            if len(fields) > 21:
                evidence = f"proc:{fields[21]}"
    except (OSError, UnicodeError):
        evidence = ""
    if not evidence and os.uname().sysname == "Darwin":
        try:
            import ctypes

            class _ProcBSDInfo(ctypes.Structure):
                _fields_ = [
                    ("pbi_flags", ctypes.c_uint32),
                    ("pbi_status", ctypes.c_uint32),
                    ("pbi_xstatus", ctypes.c_uint32),
                    ("pbi_pid", ctypes.c_uint32),
                    ("pbi_ppid", ctypes.c_uint32),
                    ("pbi_uid", ctypes.c_uint32),
                    ("pbi_gid", ctypes.c_uint32),
                    ("pbi_ruid", ctypes.c_uint32),
                    ("pbi_rgid", ctypes.c_uint32),
                    ("pbi_svuid", ctypes.c_uint32),
                    ("pbi_svgid", ctypes.c_uint32),
                    ("pbi_rfu_1", ctypes.c_uint32),
                    ("pbi_comm", ctypes.c_char * 16),
                    ("pbi_name", ctypes.c_char * 32),
                    ("pbi_nfiles", ctypes.c_uint32),
                    ("pbi_pgid", ctypes.c_uint32),
                    ("pbi_pjobc", ctypes.c_uint32),
                    ("e_tdev", ctypes.c_uint32),
                    ("e_tpgid", ctypes.c_uint32),
                    ("pbi_nice", ctypes.c_int32),
                    ("pbi_start_tvsec", ctypes.c_uint64),
                    ("pbi_start_tvusec", ctypes.c_uint64),
                ]

            info = _ProcBSDInfo()
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            observed_size = libproc.proc_pidinfo(
                process_id,
                3,  # PROC_PIDTBSDINFO
                0,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if observed_size == ctypes.sizeof(info) and info.pbi_pid == process_id:
                evidence = (
                    f"libproc:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}:"
                    f"{info.pbi_ppid}"
                )
        except (AttributeError, OSError, ValueError):
            evidence = ""
    if not evidence:
        try:
            observed = subprocess.run(
                ["ps", "-p", str(process_id), "-o", "lstart="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if observed.returncode == 0 and observed.stdout.strip():
                evidence = f"ps:{observed.stdout.strip()}"
        except (OSError, subprocess.SubprocessError, UnicodeError):
            evidence = ""
    if not evidence:
        return ""
    return canonical_sha256(
        {
            "policy": RESULT_INTAKE_POLICY,
            "process_id": process_id,
            "start_evidence": evidence,
        }
    )


def process_identity_matches(process_id: int, expected_identity: str) -> bool:
    if not expected_identity or not _SHA256_RE.fullmatch(expected_identity):
        return False
    return bool(
        capture_process_start_identity(process_id) == expected_identity
        or codex_exec_bridge.process_identity_matches(process_id, expected_identity)
    )


def _safe_locator(value: str) -> str:
    if "\x00" in value or len(value) > 4096:
        raise ResultIntakeError(
            "RESULT_LOCATOR_INVALID",
            "The durable result location is invalid.",
        )
    if _CREDENTIAL_URL_RE.search(value):
        raise ResultIntakeError(
            "RESULT_LOCATOR_CREDENTIALS",
            "A credential-bearing result location is not allowed.",
        )
    return value


def _owner_run(session: Session, owner_id: int, run: CodexRun | int) -> CodexRun:
    candidate = session.get(CodexRun, run) if isinstance(run, int) else run
    acceptance = (
        session.scalar(
            select(OwnerAcceptanceSession).where(
                OwnerAcceptanceSession.codex_run_id == candidate.id
            )
        )
        if candidate is not None
        else None
    )
    if (
        candidate is None
        or candidate.pack is None
        or candidate.pack.approved_by_user_id != owner_id
        or (
            acceptance is not None
            and acceptance.decided_by_user_id is not None
            and acceptance.decided_by_user_id != owner_id
        )
    ):
        raise ResultIntakeError(
            "RUN_NOT_FOUND",
            "Run not found.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    return candidate


def source_snapshot_unavailable_for_run(
    session: Session,
    run: CodexRun,
    monitor: CodexRunMonitor | None = None,
) -> bool:
    """Derive the pre-launch snapshot blocker from server-owned state.

    The monitor is a useful projection, but it is not the sole source of
    truth: a monitor transition can fail while the authoritative Run and exact
    Pack invalidation commit successfully.  The fallback intentionally needs
    the complete pre-launch state so an unrelated blocked Run cannot be
    mistaken for a snapshot failure.
    """

    if monitor is not None and monitor.failure_code == SOURCE_SNAPSHOT_UNAVAILABLE:
        return True
    pack = run.pack
    blocker_audit_id = session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.action == "codex_run_blocked",
            AuditEvent.entity_type == "codex_run",
            AuditEvent.entity_id == run.id,
            AuditEvent.details
            == (
                "code=SOURCE_SNAPSHOT_UNAVAILABLE; "
                "approved source snapshot preparation failed."
            ),
        )
    )
    return bool(
        run.status == "blocked"
        and run.finished_at is not None
        and run.process_spawned is False
        and run.launch_intent_at is None
        and not run.worktree_path
        and not run.worktree_branch
        and run.verification_status == "not_started"
        and run.verification_process_spawned is False
        and run.structured_result in {"", "{}"}
        and pack is not None
        and pack.id == run.pack_id
        and pack.status == "invalidated"
        and pack.invalidated_at is not None
        and blocker_audit_id is not None
    )


def _assignment_version(run: CodexRun, *, verification: bool) -> int:
    assignment = (
        run.verification_assignment if verification else run.execution_assignment
    )
    return int(
        assignment.assignment_version
        if assignment is not None
        else run.assignment_version
    )


def _default_executable_fingerprint(run: CodexRun) -> str:
    model = run.execution_model
    return canonical_sha256(
        {
            "adapter": getattr(model, "execution_adapter", "") if model else "",
            "model_stable_id": getattr(model, "stable_id", "") if model else "",
            "provider_id": run.execution_provider_id,
            "executable_status": run.executable_status,
        }
    )


def _monitor_binding(run: CodexRun, owner_id: int) -> dict[str, object]:
    execution_connectivity = run.execution_connectivity_evidence
    verification_connectivity = run.verification_connectivity_evidence
    return {
        "policy": RESULT_INTAKE_POLICY,
        "owner_id": owner_id,
        "run_id": run.id,
        "task_id": run.task_id,
        "task_version": run.task_version,
        "pack_id": run.pack_id,
        "pack_version": run.pack.version,
        "coding_assignment_id": run.execution_assignment_id,
        "coding_assignment_version": _assignment_version(run, verification=False),
        "verification_assignment_id": run.verification_assignment_id,
        "verification_assignment_version": _assignment_version(
            run,
            verification=True,
        ),
        "routing_snapshot_identity": run.routing_snapshot_hash,
        "source_snapshot_identity": run.source_snapshot_digest,
        "requested_model_identifier": run.requested_model_identifier,
        "verification_model_identifier": run.verification_model_identifier,
        "execution_connectivity_evidence_id": run.execution_connectivity_evidence_id,
        "execution_connectivity_evidence_digest": (
            execution_connectivity.evidence_digest
            if execution_connectivity is not None
            and execution_connectivity.id == run.execution_connectivity_evidence_id
            else ""
        ),
        "verification_connectivity_evidence_id": (
            run.verification_connectivity_evidence_id
        ),
        "verification_connectivity_evidence_digest": (
            verification_connectivity.evidence_digest
            if verification_connectivity is not None
            and verification_connectivity.id
            == run.verification_connectivity_evidence_id
            else ""
        ),
    }


def ensure_run_monitor(
    session: Session,
    owner_id: int,
    run: CodexRun,
    *,
    process_id: int | None = None,
    process_start_identity: str = "",
    codex_session_identity: str = "",
    executable_fingerprint: str = "",
    result_source: str = "persisted_run",
    result_path: str = "",
) -> CodexRunMonitor:
    run = _owner_run(session, owner_id, run)
    existing = session.scalar(
        select(CodexRunMonitor).where(
            CodexRunMonitor.owner_id == owner_id,
            CodexRunMonitor.run_id == run.id,
        )
    )
    if existing is not None:
        return existing
    binding = _monitor_binding(run, owner_id)
    binding_digest = canonical_sha256(binding)
    if process_id is not None:
        observed_identity = process_start_identity or capture_process_start_identity(
            process_id
        )
        if not observed_identity:
            raise ResultIntakeError(
                "PROCESS_IDENTITY_UNAVAILABLE",
                "The Codex process start identity could not be verified.",
            )
        process_start_identity = observed_identity
    result_path = _safe_locator(result_path) if result_path else ""
    monitor = CodexRunMonitor(
        monitor_id=f"monitor-{binding_digest[:24]}",
        owner_id=owner_id,
        task_id=run.task_id,
        task_version=run.task_version,
        pack_id=run.pack_id,
        pack_version=run.pack.version,
        coding_assignment_id=run.execution_assignment_id,
        coding_assignment_version=_assignment_version(run, verification=False),
        verification_assignment_id=run.verification_assignment_id,
        verification_assignment_version=_assignment_version(
            run,
            verification=True,
        ),
        routing_snapshot_identity=run.routing_snapshot_hash,
        source_snapshot_identity=run.source_snapshot_digest,
        run_id=run.id,
        requested_model_identifier=run.requested_model_identifier,
        verification_model_identifier=run.verification_model_identifier,
        process_id=process_id,
        process_start_identity=process_start_identity,
        codex_session_identity=codex_session_identity,
        executable_fingerprint=(
            executable_fingerprint
            if _SHA256_RE.fullmatch(executable_fingerprint)
            else ""
        ),
        isolated_worktree_identity=(
            canonical_sha256(
                {
                    "worktree": run.worktree_path,
                    "worktree_branch": run.worktree_branch,
                    "source_snapshot": run.source_snapshot_digest,
                }
            )
            if run.worktree_path
            else ""
        ),
        execution_location_identity=(
            canonical_sha256(
                {
                    "source_repository": run.source_repo,
                    "source_branch": run.source_branch,
                    "source_commit": run.source_commit,
                    "isolated_worktree": run.worktree_path,
                }
            )
            if run.worktree_path
            else ""
        ),
        result_locator_identity=canonical_sha256(result_path) if result_path else "",
        protected_result_locator=result_path,
        monitor_digest=binding_digest,
        monitor_state=RUN_TO_MONITOR_STATE.get(run.status, "QUEUED"),
        result_source=_sanitize_text(result_source)[:80],
        recovery_state="NONE",
        process_exit_code=run.exit_code,
        heartbeat_sequence=0,
        safe_summary="Run monitoring is active independently of the browser.",
        started_at=run.started_at,
        last_heartbeat_at=utc_now(),
        terminal_at=run.finished_at if run.status in TERMINAL_RUN_STATES else None,
        last_observed_at=utc_now(),
    )
    session.add(monitor)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(CodexRunMonitor).where(
                CodexRunMonitor.owner_id == owner_id,
                CodexRunMonitor.run_id == run.id,
            )
        )
        if existing is None:
            raise
        return existing
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="codex_run_monitor_created",
            entity_type="codex_run_monitor",
            entity_id=monitor.id,
            details=(
                f"run={run.id}; state={monitor.monitor_state}; "
                f"policy={RESULT_INTAKE_POLICY}"
            ),
        )
    )
    return monitor


def _executable_identity(executable_path: str | Path, run: CodexRun) -> str:
    try:
        resolved = Path(executable_path).resolve(strict=True)
        details = resolved.stat()
        if not stat.S_ISREG(details.st_mode):
            return _default_executable_fingerprint(run)
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return canonical_sha256(
            {
                "content_sha256": digest.hexdigest(),
                "size": details.st_size,
                "mode": stat.S_IMODE(details.st_mode),
            }
        )
    except (OSError, ValueError):
        return _default_executable_fingerprint(run)


def record_monitor_process_start(
    session: Session,
    run: CodexRun,
    process_id: int,
    executable_path: str | Path,
    worktree: str | Path,
    *,
    phase: str = "coding",
    codex_session_identity: str = "",
    trusted_process_start_identity: str = "",
) -> CodexRunMonitor:
    """Bind a newly spawned local process to its persisted monitor exactly once."""
    if phase not in {"coding", "verification"}:
        raise ResultIntakeError(
            "PROCESS_PHASE_INVALID",
            "The Codex process phase is invalid.",
        )
    if run.pack is None or run.pack.approved_by_user_id is None:
        raise ResultIntakeError(
            "RUN_OWNER_UNAVAILABLE",
            "Run not found.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    owner_id = int(run.pack.approved_by_user_id)
    if trusted_process_start_identity and not _SHA256_RE.fullmatch(
        trusted_process_start_identity
    ):
        raise ResultIntakeError(
            "PROCESS_IDENTITY_INVALID",
            "The Codex process start identity is invalid.",
        )
    start_identity = (
        trusted_process_start_identity
        or capture_process_start_identity(process_id)
    )
    if not start_identity:
        raise ResultIntakeError(
            "PROCESS_IDENTITY_UNAVAILABLE",
            "The Codex process start identity could not be verified.",
        )
    worktree_path = Path(worktree)
    try:
        resolved_worktree = worktree_path.resolve(strict=True)
        worktree_stat = resolved_worktree.stat()
    except OSError as exc:
        raise ResultIntakeError(
            "WORKTREE_IDENTITY_UNAVAILABLE",
            "The isolated Codex worktree identity could not be verified.",
        ) from exc
    worktree_identity = canonical_sha256(
        {
            "device": worktree_stat.st_dev,
            "inode": worktree_stat.st_ino,
            "resolved_location": str(resolved_worktree),
            "source_snapshot_identity": run.source_snapshot_digest,
            "worktree_branch": run.worktree_branch,
        }
    )
    execution_location_identity = canonical_sha256(
        {
            "isolated_worktree_identity": worktree_identity,
            "source_commit": run.source_commit,
            "source_branch": run.source_branch,
        }
    )
    executable_fingerprint = _executable_identity(executable_path, run)
    monitor = ensure_run_monitor(
        session,
        owner_id,
        run,
        executable_fingerprint=executable_fingerprint,
    )
    # The monitor-level executable identity is the Coding executable. A
    # supported deterministic local Verification command can use a different
    # executable; its identity is bound independently on the sealed
    # Verification attempt and receipt.
    if (
        phase == "coding"
        and monitor.executable_fingerprint
        and monitor.executable_fingerprint != executable_fingerprint
    ):
        raise ResultIntakeError(
            "EXECUTABLE_IDENTITY_MISMATCH",
            "The spawned executable does not match this Run monitor.",
        )
    if (
        monitor.isolated_worktree_identity
        and monitor.isolated_worktree_identity != worktree_identity
    ):
        raise ResultIntakeError(
            "WORKTREE_IDENTITY_MISMATCH",
            "The spawned process worktree does not match this Run monitor.",
        )
    if (
        monitor.execution_location_identity
        and monitor.execution_location_identity != execution_location_identity
    ):
        raise ResultIntakeError(
            "EXECUTION_LOCATION_MISMATCH",
            "The spawned process location does not match this Run monitor.",
        )
    if phase == "coding":
        monitor.executable_fingerprint = executable_fingerprint
    monitor.isolated_worktree_identity = worktree_identity
    monitor.execution_location_identity = execution_location_identity
    if phase == "coding":
        if monitor.process_id is not None and (
            monitor.process_id != process_id
            or monitor.process_start_identity != start_identity
        ):
            raise ResultIntakeError(
                "PROCESS_IDENTITY_MISMATCH",
                "The Coding process does not match this Run monitor.",
            )
        monitor.process_id = process_id
        monitor.process_start_identity = start_identity
        target_state = "RUNNING"
    else:
        if monitor.verification_process_id is not None and (
            monitor.verification_process_id != process_id
            or monitor.verification_process_start_identity != start_identity
        ):
            raise ResultIntakeError(
                "PROCESS_IDENTITY_MISMATCH",
                "The Verification process does not match this Run monitor.",
            )
        monitor.verification_process_id = process_id
        monitor.verification_process_start_identity = start_identity
        target_state = "VERIFYING"
    if codex_session_identity:
        sanitized_session = (
            codex_session_identity
            if _SHA256_RE.fullmatch(codex_session_identity)
            else canonical_sha256(codex_session_identity)
        )
        if (
            monitor.codex_session_identity
            and monitor.codex_session_identity != sanitized_session
        ):
            raise ResultIntakeError(
                "CODEX_SESSION_MISMATCH",
                "The Codex session does not match this Run monitor.",
            )
        monitor.codex_session_identity = sanitized_session
    observe_monitor(
        session,
        monitor,
        state=target_state,
        safe_summary=(
            "Coding is running in the isolated worktree."
            if phase == "coding"
            else "Independent Verification is running."
        ),
    )
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="codex_run_monitor_process_bound",
            entity_type="codex_run_monitor",
            entity_id=monitor.id,
            details=f"run={run.id}; phase={phase}; start_identity_verified=true",
        )
    )
    return monitor


def update_monitor_from_run(
    session: Session,
    run: CodexRun,
    *,
    owner_id: int | None = None,
    actual_model_identifier: str | None = None,
    codex_session_identity: str | None = None,
) -> CodexRunMonitor:
    """Persist a heartbeat/state observation from the execution manager."""
    effective_owner = owner_id or (
        int(run.pack.approved_by_user_id)
        if run.pack is not None and run.pack.approved_by_user_id is not None
        else None
    )
    if effective_owner is None:
        raise ResultIntakeError(
            "RUN_OWNER_UNAVAILABLE",
            "Run not found.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    monitor = ensure_run_monitor(session, effective_owner, run)
    target_state = RUN_TO_MONITOR_STATE.get(run.status, monitor.monitor_state)
    if monitor.monitor_state == "RESULT_AVAILABLE":
        return monitor
    if (
        target_state != monitor.monitor_state
        and target_state not in _STATE_TRANSITIONS.get(monitor.monitor_state, set())
    ):
        target_state = monitor.monitor_state
    return observe_monitor(
        session,
        monitor,
        state=target_state,
        actual_model_identifier=actual_model_identifier,
        codex_session_identity=codex_session_identity,
        exit_code=run.exit_code,
        safe_summary=(
            run.owner_summary
            or "The Codex Run state was persisted by the execution manager."
        ),
    )


_STATE_TRANSITIONS = {
    "QUEUED": MONITOR_STATES - {"QUEUED"},
    "STARTING": MONITOR_STATES - {"QUEUED", "STARTING"},
    # STARTING is allowed only for the exact detached launch/state handoff
    # correction; ordinary product flow remains monotonic.
    "RUNNING": MONITOR_STATES - {"QUEUED", "RUNNING"},
    "VERIFYING": MONITOR_STATES
    - {"QUEUED", "STARTING", "RUNNING", "VERIFYING"},
    "COMPLETED": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "FAILED": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "CANCELLED": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "TIMED_OUT": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "PROCESS_LOST": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "RESULT_PENDING": {
        "RESULT_AVAILABLE",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "RESULT_UNAVAILABLE": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
    },
    "RESULT_INTEGRITY_BLOCKED": {
        "RESULT_PENDING",
        "RESULT_AVAILABLE",
    },
    "RESULT_AVAILABLE": set(),
}


def observe_monitor(
    session: Session,
    monitor: CodexRunMonitor,
    *,
    state: str | None = None,
    process_id: int | None = None,
    process_start_identity: str | None = None,
    codex_session_identity: str | None = None,
    actual_model_identifier: str | None = None,
    exit_code: int | None = None,
    result_source: str | None = None,
    result_path: str | None = None,
    recovery_state: str | None = None,
    failure_code: str | None = None,
    safe_summary: str | None = None,
) -> CodexRunMonitor:
    if state is not None:
        if state not in MONITOR_STATES:
            raise ResultIntakeError("MONITOR_STATE_INVALID", "Monitor state is invalid.")
        if (
            state != monitor.monitor_state
            and state not in _STATE_TRANSITIONS.get(monitor.monitor_state, set())
        ):
            raise ResultIntakeError(
                "MONITOR_STATE_TRANSITION_INVALID",
                "The requested Run monitor transition is invalid.",
            )
    if recovery_state is not None and recovery_state not in RECOVERY_STATES:
        raise ResultIntakeError(
            "RECOVERY_STATE_INVALID",
            "Monitor recovery state is invalid.",
        )
    if process_id is not None:
        identity = process_start_identity or capture_process_start_identity(process_id)
        if not identity:
            raise ResultIntakeError(
                "PROCESS_IDENTITY_UNAVAILABLE",
                "The Codex process start identity could not be verified.",
            )
        if monitor.process_id is not None and (
            monitor.process_id != process_id
            or monitor.process_start_identity != identity
        ):
            raise ResultIntakeError(
                "PROCESS_IDENTITY_MISMATCH",
                "The observed Codex process does not match this Run.",
            )
        monitor.process_id = process_id
        monitor.process_start_identity = identity
    elif (
        process_start_identity is not None
        and process_start_identity != monitor.process_start_identity
    ):
        raise ResultIntakeError(
            "PROCESS_IDENTITY_MISMATCH",
            "The observed Codex process does not match this Run.",
        )
    if codex_session_identity is not None:
        if (
            monitor.codex_session_identity
            and monitor.codex_session_identity != codex_session_identity
        ):
            raise ResultIntakeError(
                "CODEX_SESSION_MISMATCH",
                "The observed Codex session does not match this Run.",
            )
        monitor.codex_session_identity = codex_session_identity[:64]
    if actual_model_identifier is not None:
        if (
            monitor.actual_model_identifier
            and monitor.actual_model_identifier != actual_model_identifier
        ):
            raise ResultIntakeError(
                "ACTUAL_MODEL_MISMATCH",
                "Conflicting actual model evidence was observed.",
            )
        monitor.actual_model_identifier = _sanitize_text(actual_model_identifier)[:240]
    if result_path is not None:
        locator = _safe_locator(result_path)
        identity = canonical_sha256(locator) if locator else ""
        if (
            monitor.result_locator_identity
            and monitor.result_locator_identity != identity
        ):
            raise ResultIntakeError(
                "RESULT_LOCATOR_MISMATCH",
                "The durable result location does not match this Run.",
            )
        monitor.protected_result_locator = locator
        monitor.result_locator_identity = identity
    if result_source is not None:
        monitor.result_source = _sanitize_text(result_source)[:80]
    if state is not None:
        monitor.monitor_state = state
    if recovery_state is not None:
        monitor.recovery_state = recovery_state
    if exit_code is not None:
        monitor.process_exit_code = exit_code
    if failure_code is not None:
        monitor.failure_code = _sanitize_text(failure_code)[:80]
    if safe_summary is not None:
        monitor.safe_summary = _sanitize_text(safe_summary)
    now = utc_now()
    monitor.heartbeat_sequence += 1
    monitor.last_heartbeat_at = now
    monitor.last_observed_at = now
    if monitor.started_at is None and monitor.monitor_state in {
        "STARTING",
        "RUNNING",
        "VERIFYING",
    }:
        monitor.started_at = now
    if (
        monitor.terminal_at is None
        and monitor.monitor_state
        in PROCESS_TERMINAL_STATES | RESULT_TERMINAL_STATES
    ):
        monitor.terminal_at = now
    session.flush()
    return monitor


def clear_stale_monitor_terminal_state(
    session: Session,
    monitor: CodexRunMonitor,
    *,
    reason: str,
) -> bool:
    """Clear only stale mutable terminal fields after exact live proof.

    Audit rows are append-only and remain untouched; a new audit row records
    why the mutable monitor projection was corrected.
    """
    had_stale_state = bool(
        monitor.failure_code
        or monitor.process_exit_code is not None
        or monitor.terminal_at is not None
    )
    if not had_stale_state:
        return False
    monitor.failure_code = ""
    monitor.process_exit_code = None
    monitor.terminal_at = None
    session.add(
        AuditEvent(
            actor_user_id=monitor.owner_id,
            action="codex_run_monitor_stale_terminal_cleared",
            entity_type="codex_run",
            entity_id=monitor.run_id,
            details=f"reason={_sanitize_text(reason)[:120]}",
        )
    )
    return True


def _coerce_payload(payload: dict[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(payload, bytes):
        if len(payload) > MAX_RESULT_BYTES:
            raise ResultIntakeError(
                "RESULT_TOO_LARGE",
                "The Codex result exceeded the safe intake limit.",
            )
        try:
            raw: object = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ResultIntakeError(
                "RESULT_MALFORMED",
                "The Codex result is not valid UTF-8 JSON.",
            ) from exc
    elif isinstance(payload, str):
        encoded = payload.encode("utf-8")
        if len(encoded) > MAX_RESULT_BYTES:
            raise ResultIntakeError(
                "RESULT_TOO_LARGE",
                "The Codex result exceeded the safe intake limit.",
            )
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ResultIntakeError(
                "RESULT_MALFORMED",
                "The Codex result is not valid JSON.",
            ) from exc
    elif isinstance(payload, dict):
        raw = payload
        try:
            encoded_size = len(canonical_json(raw).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ResultIntakeError(
                "RESULT_MALFORMED",
                "The Codex result contains non-JSON or binary values.",
            ) from exc
        if encoded_size > MAX_RESULT_BYTES:
            raise ResultIntakeError(
                "RESULT_TOO_LARGE",
                "The Codex result exceeded the safe intake limit.",
            )
    else:
        raise ResultIntakeError(
            "RESULT_MALFORMED",
            "The Codex result must be a structured JSON object.",
        )
    if not isinstance(raw, dict) or not raw:
        raise ResultIntakeError(
            "RESULT_INCOMPLETE",
            "The Codex result is empty or incomplete.",
        )
    _validate_raw_result_paths(raw)
    sanitized = sanitize_result_value(raw)
    if not isinstance(sanitized, dict):
        raise ResultIntakeError(
            "RESULT_MALFORMED",
            "The Codex result must be a structured JSON object.",
        )
    return sanitized


def _validate_raw_result_paths(payload: Mapping[str, object]) -> None:
    """Reject unsafe evidence before display redaction can replace the path."""
    path_values: list[object] = []
    for key in ("changed_file_evidence", "changed_file_manifest"):
        rows = payload.get(key)
        if isinstance(rows, list):
            path_values.extend(
                row.get("path")
                for row in rows
                if isinstance(row, Mapping) and "path" in row
            )
    diff = payload.get("sanitized_diff_evidence")
    if isinstance(diff, Mapping) and isinstance(diff.get("records"), list):
        path_values.extend(
            row.get("path")
            for row in diff["records"]
            if isinstance(row, Mapping) and "path" in row
        )
    changed_files = payload.get("changed_files")
    if isinstance(changed_files, list):
        path_values.extend(changed_files)
    produced = payload.get("run_produced_changes")
    if isinstance(produced, Mapping):
        for key in ("changed_files", "unexpected_files"):
            values = produced.get(key)
            if isinstance(values, list):
                path_values.extend(values)
    for raw_path in path_values:
        _normalized_relative_path(raw_path)


def _identity_value(payload: Mapping[str, object], key: str) -> object:
    identity = payload.get("identity")
    if isinstance(identity, Mapping) and key in identity:
        return identity.get(key)
    aliases = {
        "run_id": ("run_id", "codex_run_id"),
        "task_id": ("task_id",),
        "task_version": ("task_version",),
        "pack_id": ("pack_id",),
        "pack_version": ("pack_version",),
        "coding_assignment_id": ("coding_assignment_id", "execution_assignment_id"),
        "coding_assignment_version": (
            "coding_assignment_version",
            "assignment_version",
        ),
        "verification_assignment_id": ("verification_assignment_id",),
        "verification_assignment_version": (
            "verification_assignment_version",
            "assignment_version",
        ),
        "routing_snapshot_identity": (
            "routing_snapshot_identity",
            "routing_snapshot_hash",
        ),
        "source_snapshot_identity": (
            "source_snapshot_identity",
            "source_snapshot_digest",
        ),
    }
    for alias in aliases.get(key, (key,)):
        if alias in payload:
            return payload.get(alias)
    return None


def _validate_result_identity(
    payload: Mapping[str, object],
    monitor: CodexRunMonitor,
    *,
    require_explicit_identity: bool,
) -> None:
    expected = {
        "run_id": monitor.run_id,
        "task_id": monitor.task_id,
        "task_version": monitor.task_version,
        "pack_id": monitor.pack_id,
        "pack_version": monitor.pack_version,
        "coding_assignment_id": monitor.coding_assignment_id,
        "coding_assignment_version": monitor.coding_assignment_version,
        "verification_assignment_id": monitor.verification_assignment_id,
        "verification_assignment_version": monitor.verification_assignment_version,
        "routing_snapshot_identity": monitor.routing_snapshot_identity,
        "source_snapshot_identity": monitor.source_snapshot_identity,
    }
    for key, expected_value in expected.items():
        observed = _identity_value(payload, key)
        if require_explicit_identity and observed is None:
            raise ResultIntakeError(
                "RESULT_IDENTITY_INCOMPLETE",
                f"The structured Codex result is missing {key}.",
            )
        if observed is not None and observed != expected_value:
            raise ResultIntakeError(
                "RESULT_IDENTITY_MISMATCH",
                f"The structured Codex result does not match the selected Run ({key}).",
            )


def _validate_result_completeness(payload: Mapping[str, object]) -> None:
    required_mappings = (
        "coding_process",
        "coding_invocation",
        "verification_verdict",
        "task_acceptance",
        "boundary_confirmation",
    )
    missing = [
        key for key in required_mappings if not isinstance(payload.get(key), Mapping)
    ]
    if not isinstance(payload.get("changed_file_evidence"), list):
        missing.append("changed_file_evidence")
    if (
        not isinstance(payload.get("tests"), list)
        and not isinstance(payload.get("tests_reported"), list)
        and not isinstance(payload.get("validation"), Mapping)
    ):
        missing.append("tests")
    coding = payload.get("coding_process")
    if isinstance(coding, Mapping) and not str(coding.get("status", "")).strip():
        missing.append("coding_process.status")
    verdict = payload.get("verification_verdict")
    if isinstance(verdict, Mapping) and not str(verdict.get("status", "")).strip():
        missing.append("verification_verdict.status")
    if missing:
        raise ResultIntakeError(
            "RESULT_INCOMPLETE",
            "The structured Codex result is incomplete: "
            + ", ".join(dict.fromkeys(missing))
            + ".",
        )


def _normalized_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise ResultIntakeError(
            "RESULT_PATH_INVALID",
            "A changed-file path is malformed.",
        )
    path = value.strip()
    if (
        not path
        or len(path) > 4096
        or "\x00" in path
        or "\\" in path
        or PurePosixPath(path).is_absolute()
    ):
        raise ResultIntakeError(
            "RESULT_PATH_INVALID",
            "A changed-file path is malformed.",
        )
    parts = PurePosixPath(path).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ResultIntakeError(
            "RESULT_PATH_UNSAFE",
            "A changed-file path is outside the authorized repository.",
        )
    normalized = PurePosixPath(*parts).as_posix()
    if normalized != path:
        raise ResultIntakeError(
            "RESULT_PATH_INVALID",
            "A changed-file path is not normalized.",
        )
    return normalized


def _optional_hash(value: object) -> str | None:
    if value in {None, ""}:
        return None
    candidate = str(value).lower()
    if not _SHA256_RE.fullmatch(candidate):
        raise ResultIntakeError(
            "RESULT_HASH_INVALID",
            "Changed-file evidence contains an invalid SHA-256 value.",
        )
    return candidate


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ResultIntakeError(
            "RESULT_METADATA_INVALID",
            "Changed-file evidence contains invalid size or mode metadata.",
        )
    return value


def _manifest_from_payload(payload: Mapping[str, object]) -> list[dict[str, object]]:
    raw_rows = payload.get("changed_file_evidence")
    if not isinstance(raw_rows, list):
        raw_rows = payload.get("changed_file_manifest")
    if not isinstance(raw_rows, list):
        raw_rows = []
    diff_records = {}
    diff = payload.get("sanitized_diff_evidence")
    if isinstance(diff, Mapping) and isinstance(diff.get("records"), list):
        for row in diff["records"]:
            if isinstance(row, Mapping) and isinstance(row.get("path"), str):
                diff_records[str(row["path"])] = row
    unexpected_paths: set[str] = set()
    produced = payload.get("run_produced_changes")
    if isinstance(produced, Mapping) and isinstance(
        produced.get("unexpected_files"),
        list,
    ):
        unexpected_paths = {
            str(item) for item in produced["unexpected_files"] if isinstance(item, str)
        }
    output: list[dict[str, object]] = []
    observed_paths: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ResultIntakeError(
                "RESULT_MANIFEST_INVALID",
                "Changed-file evidence contains a malformed entry.",
            )
        path = _normalized_relative_path(raw.get("path"))
        if path in observed_paths:
            raise ResultIntakeError(
                "RESULT_MANIFEST_DUPLICATE",
                "Changed-file evidence contains a duplicate path.",
            )
        observed_paths.add(path)
        before_hash = _optional_hash(
            raw.get("before_sha256", raw.get("before_hash"))
        )
        after_hash = _optional_hash(raw.get("after_sha256", raw.get("after_hash")))
        before_deleted = raw.get("before_deleted") is True
        after_deleted = raw.get("after_deleted") is True
        if (before_hash is None or before_deleted) and after_hash is not None:
            operation = "CREATE"
        elif before_hash is not None and (after_hash is None or after_deleted):
            operation = "DELETE"
        elif before_hash is not None and after_hash is not None:
            operation = "MODIFY"
        else:
            operation = "UNKNOWN"
        diff_row = diff_records.get(path)
        content_kind = (
            str(diff_row.get("content_kind", "unknown"))
            if isinstance(diff_row, Mapping)
            else "unknown"
        )
        entry = {
            "path": path,
            "display_path": PurePosixPath(path).name,
            "operation": operation,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "before_size": _optional_nonnegative_int(raw.get("before_size")),
            "after_size": _optional_nonnegative_int(raw.get("after_size")),
            "before_mode": _optional_nonnegative_int(raw.get("before_mode")),
            "after_mode": _optional_nonnegative_int(raw.get("after_mode")),
            "content_kind": content_kind[:40],
            "unexpected": path in unexpected_paths,
        }
        entry["path_identity"] = canonical_sha256(path)
        entry["evidence_identity"] = canonical_sha256(entry)
        output.append(entry)
    return output


def _safe_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    sanitized = sanitize_result_value(value)
    return sanitized if isinstance(sanitized, list) else []


def _safe_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    sanitized = sanitize_result_value(value)
    return sanitized if isinstance(sanitized, dict) else {}


def _validated_coding_handoff(value: object) -> dict[str, object]:
    """Return only the already-supported Coding handoff contract."""
    candidate: object = value
    if isinstance(candidate, str):
        try:
            candidate = json.loads(candidate)
        except json.JSONDecodeError:
            return {}
    if not isinstance(candidate, Mapping):
        return {}
    if (
        set(candidate) != {"schema", "status", "summary"}
        or candidate.get("schema") != "twos.coding_handoff.v1"
        or candidate.get("status") != "completed"
        or not isinstance(candidate.get("summary"), str)
        or not str(candidate["summary"]).strip()
    ):
        return {}
    return _safe_mapping(candidate)


def _opaque_log_reference(monitor: CodexRunMonitor) -> str:
    """Expose a stable Run-local handle without returning a filesystem path."""
    locator_identity = (
        monitor.result_locator_identity
        if _SHA256_RE.fullmatch(monitor.result_locator_identity or "")
        else canonical_sha256(monitor.protected_result_locator)
        if monitor.protected_result_locator
        else ""
    )
    if not locator_identity:
        return ""
    identity = canonical_sha256(
        {
            "monitor": monitor.monitor_digest,
            "locator": locator_identity,
        }
    )
    return f"local-log-{identity[:24]}"


def _verification_verdict(payload: Mapping[str, object]) -> str:
    verdict = payload.get("verification_verdict")
    status = (
        str(verdict.get("status", ""))
        if isinstance(verdict, Mapping)
        else str(verdict or "")
    ).lower()
    if status in {"pass", "passed", "verified"}:
        return "PASS"
    if status in {"fail", "failed", "rejected"}:
        return "FAIL"
    return "UNAVAILABLE"


def _evidence_summary(
    session: Session,
    run: CodexRun,
    capability: str,
) -> dict[str, object]:
    evidence = session.scalar(
        select(AIModelInvocationEvidence)
        .where(
            AIModelInvocationEvidence.codex_run_id == run.id,
            AIModelInvocationEvidence.capability == capability,
        )
        .order_by(AIModelInvocationEvidence.id.desc())
    )
    if evidence is None:
        if capability == "verification":
            try:
                persisted_result = json.loads(run.structured_result or "{}")
            except (TypeError, json.JSONDecodeError):
                persisted_result = {}
            invocation = (
                persisted_result.get("verification_invocation", {})
                if isinstance(persisted_result, Mapping)
                else {}
            )
            verification = (
                persisted_result.get("verification", {})
                if isinstance(persisted_result, Mapping)
                else {}
            )
            verdict = (
                persisted_result.get("verification_verdict", {})
                if isinstance(persisted_result, Mapping)
                else {}
            )
            if (
                isinstance(invocation, Mapping)
                and invocation.get("mode") == "local_command"
                and invocation.get("model_provider_invoked") is False
            ):
                ticket_digest = str(invocation.get("ticket_digest") or "")
                command_digest = str(invocation.get("command_digest") or "")
                executable_fingerprint = str(
                    invocation.get("executable_fingerprint") or ""
                )
                binding_valid = all(
                    _SHA256_RE.fullmatch(value)
                    for value in (
                        ticket_digest,
                        command_digest,
                        executable_fingerprint,
                    )
                )
                attempt = session.scalar(
                    select(CodexExecutionAttempt)
                    .where(
                        CodexExecutionAttempt.run_id == run.id,
                        CodexExecutionAttempt.phase == "VERIFICATION",
                    )
                    .order_by(CodexExecutionAttempt.id.desc())
                )
                sealed_attempt_valid = bool(
                    binding_valid
                    and attempt is not None
                    and attempt.ticket_digest == ticket_digest
                    and _SHA256_RE.fullmatch(attempt.receipt_digest or "")
                    and attempt.executable_fingerprint == command_digest
                    and type(attempt.process_id) is int
                    and attempt.process_id > 0
                    and _SHA256_RE.fullmatch(
                        attempt.process_start_identity or ""
                    )
                    and attempt.process_exit_known
                    and attempt.terminal_event_observed
                    and attempt.result_resolution_source
                    in {
                        "FINAL_MESSAGE_SIDECAR",
                        "JSONL_FINAL_MESSAGE_RECOVERY",
                    }
                )
                process_verified = bool(
                    sealed_attempt_valid
                    and attempt is not None
                    and attempt.attempt_state == "COMPLETED"
                    and attempt.process_exit_code == 0
                    and invocation.get("process_execution_verified") is True
                )
                outcome = (
                    "succeeded"
                    if isinstance(verification, Mapping)
                    and verification.get("status") == "completed"
                    and isinstance(verdict, Mapping)
                    and verdict.get("status") == "passed"
                    else "failed"
                    if isinstance(verification, Mapping)
                    and verification.get("status")
                    in {"failed", "timed_out", "cancelled", "integrity_blocked"}
                    else "unavailable"
                )
                payload = {
                    "capability": "verification",
                    "mode": "local_command",
                    "identity": (
                        f"local-verification:{ticket_digest[:24]}"
                        if sealed_attempt_valid
                        else ""
                    ),
                    "outcome": outcome,
                    "verified_local_process": process_verified,
                    "model_provider_invoked": False,
                    "ticket_digest": ticket_digest if sealed_attempt_valid else "",
                    "command_digest": command_digest if sealed_attempt_valid else "",
                    "executable_fingerprint": (
                        executable_fingerprint if sealed_attempt_valid else ""
                    ),
                    "safe_summary": _sanitize_text(
                        str(
                            verification.get("summary")
                            if isinstance(verification, Mapping)
                            else "Deterministic Verification evidence is unavailable."
                        )
                    ),
                }
                return {
                    "available": sealed_attempt_valid,
                    **payload,
                    "digest": (
                        canonical_sha256(payload) if sealed_attempt_valid else ""
                    ),
                    "verified_real_invocation": False,
                    "actual_model_verified": False,
                    "requested_model": "",
                    "requested_model_accepted": False,
                    "configured_assignment_model": run.verification_model_identifier,
                    "effective_model_available": False,
                }
        requested_model = (
            run.requested_model_identifier
            if capability == "coding"
            else run.verification_model_identifier
            if capability == "verification"
            else ""
        )
        unavailable_summary = (
            run.verification_summary
            if capability == "verification" and run.verification_summary
            else "Evidence is unavailable."
        )
        return {
            "available": False,
            "capability": capability,
            "identity": "",
            "digest": "",
            "outcome": "unavailable",
            "verified_real_invocation": False,
            "actual_model_verified": False,
            "requested_model": requested_model,
            "requested_model_accepted": False,
            "effective_model_available": False,
            "safe_summary": _sanitize_text(unavailable_summary),
        }
    actual_model, model_identity_source, connectivity_digest = (
        verified_actual_model_identity(evidence)
    )
    verified_real = is_verified_real_invocation(evidence)
    requested_model = (
        run.requested_model_identifier
        if capability == "coding"
        else run.verification_model_identifier
        if capability == "verification"
        else ""
    )
    requested_model_accepted = bool(
        verified_real
        and evidence.outcome == "succeeded"
        and requested_model
    )
    evidence_payload = {
        "invocation_ref": evidence.invocation_ref,
        "capability": evidence.capability,
        "assignment_id": evidence.assignment_id,
        "assignment_version": evidence.assignment_version,
        "actual_model": actual_model,
        "actual_model_verified": bool(actual_model),
        "requested_model": requested_model,
        "requested_model_accepted": requested_model_accepted,
        "effective_model_available": bool(actual_model),
        "model_identity_source": model_identity_source,
        "connectivity_evidence_identity": connectivity_digest,
        "invocation_mode": evidence.invocation_mode,
        "outcome": evidence.outcome,
        "verified_real_invocation": verified_real,
        "request_fingerprint": evidence.request_fingerprint,
        "response_fingerprint": evidence.response_fingerprint,
        "duration_ms": evidence.duration_ms,
        "timed_out": evidence.timed_out,
        "cancelled": evidence.cancelled,
        "output_truncated": evidence.output_truncated,
        "diagnostic_code": evidence.diagnostic_code,
        "safe_summary": _sanitize_text(evidence.safe_summary),
    }
    return {
        "available": True,
        "capability": capability,
        "identity": evidence.invocation_ref,
        "digest": canonical_sha256(evidence_payload),
        "outcome": evidence.outcome,
        "safe_summary": _sanitize_text(evidence.safe_summary),
        "actual_model": _sanitize_text(actual_model),
        "actual_model_verified": bool(actual_model),
        "requested_model": _sanitize_text(requested_model),
        "requested_model_accepted": requested_model_accepted,
        "effective_model_available": bool(actual_model),
        "model_identity_source": model_identity_source or None,
        "connectivity_evidence_identity": connectivity_digest or None,
        "verified_real_invocation": verified_real,
        "duration_ms": evidence.duration_ms,
    }


def _result_material(
    session: Session,
    run: CodexRun,
    monitor: CodexRunMonitor,
    payload: dict[str, Any],
) -> dict[str, object]:
    manifest = _manifest_from_payload(payload)
    tests = _safe_list(payload.get("tests"))
    if not tests:
        tests = _safe_list(payload.get("tests_reported"))
    if not tests and isinstance(payload.get("validation"), Mapping):
        validation = _safe_mapping(payload.get("validation"))
        tests = [
            {
                "name": str(name),
                "status": (
                    "passed"
                    if outcome is True
                    else "failed"
                    if outcome is False
                    else "reported"
                ),
                "summary": (
                    f"{str(name).replace('_', ' ')}: "
                    f"{'passed' if outcome is True else 'failed' if outcome is False else outcome}"
                ),
            }
            for name, outcome in validation.items()
        ]
    warnings = _safe_list(payload.get("warnings"))
    limitations = _safe_list(payload.get("limitations"))
    boundaries = _safe_mapping(payload.get("boundary_confirmation"))
    coding_evidence = _evidence_summary(session, run, "coding")
    verification_evidence = _evidence_summary(session, run, "verification")
    try:
        persisted_result = json.loads(run.structured_result or "{}")
    except (TypeError, json.JSONDecodeError):
        persisted_result = {}
    reported_verdict = _verification_verdict(
        persisted_result if isinstance(persisted_result, Mapping) else {}
    )
    verdict = (
        "PASS"
        if reported_verdict == "PASS"
        and (
            verification_evidence.get("verified_real_invocation") is True
            or verification_evidence.get("verified_local_process") is True
        )
        else "FAIL"
        if reported_verdict == "FAIL"
        else "UNAVAILABLE"
    )
    final_response = ""
    for candidate in (
        payload.get("final_response"),
        (
            payload.get("advanced_diagnostics", {}).get(
                "coding_final_agent_message"
            )
            if isinstance(payload.get("advanced_diagnostics"), Mapping)
            else ""
        ),
    ):
        if isinstance(candidate, str) and candidate.strip():
            final_response = _sanitize_text(candidate.strip())
            break
    # Reconstruct the exact Vol.18 final-response fallback separately. Existing
    # immutable envelopes may have bound the Owner summary when Codex supplied
    # neither an explicit response nor a final agent message.
    legacy_final_response = final_response
    if not legacy_final_response and isinstance(run.owner_summary, str):
        if run.owner_summary.strip():
            legacy_final_response = _sanitize_text(run.owner_summary.strip())
    coding_process = _safe_mapping(payload.get("coding_process"))
    task_acceptance = _safe_mapping(payload.get("task_acceptance"))
    top_level_handoff_value = payload.get("structured_handoff") or payload.get(
        "handoff"
    )
    # Preserve the historical mapping only for legacy digest reconstruction.
    # Current evidence may be called captured only after the same strict
    # contract validation used for the terminal Codex message.
    top_level_structured_handoff = _safe_mapping(top_level_handoff_value)
    structured_handoff = _validated_coding_handoff(top_level_handoff_value)
    if not structured_handoff:
        advanced = payload.get("advanced_diagnostics")
        final_agent_message = (
            advanced.get("coding_final_agent_message")
            if isinstance(advanced, Mapping)
            else None
        )
        structured_handoff = _validated_coding_handoff(final_agent_message)
    structured_handoff_status = (
        "captured" if structured_handoff else "unavailable"
    )
    # The legacy digest accepted only an explicit top-level handoff. Do not let
    # the new extraction of a validated final agent message rewrite history.
    legacy_structured_handoff = top_level_structured_handoff
    if not legacy_structured_handoff:
        legacy_structured_handoff = {
            "schema": RESULT_INTAKE_SCHEMA,
            "run_outcome": run.status,
            "coding_result": coding_process,
            "verification_verdict": verdict,
            "task_acceptance": task_acceptance,
            "changed_files": [
                {
                    "path": row["path"],
                    "operation": row["operation"],
                    "unexpected": row["unexpected"],
                    "content_kind": row["content_kind"],
                }
                for row in manifest
            ],
            "tests": tests,
            "warnings": warnings,
            "limitations": limitations,
            "boundary_confirmation": boundaries,
        }
    captured_workspace_evidence = _safe_mapping(payload.get("workspace_evidence"))
    workspace_evidence_available = bool(captured_workspace_evidence)
    workspace_evidence = captured_workspace_evidence
    if not workspace_evidence_available:
        workspace_evidence = {
            "schema": "twos.codex_workspace_evidence.v1",
            "status": "unavailable",
            "availability_reason": (
                "Structured workspace evidence was not captured for this result."
            ),
        }
    diff_identity = canonical_sha256(
        {
            "manifest": manifest,
            "sanitized_diff": _safe_mapping(payload.get("sanitized_diff_evidence")),
        }
    )
    actual_model = str(
        coding_evidence.get("actual_model")
        if coding_evidence.get("actual_model_verified") is True
        else ""
    )
    monitor_binding = _monitor_binding(run, monitor.owner_id)
    connectivity_bindings = {
        "execution_evidence_id": monitor_binding.get(
            "execution_connectivity_evidence_id"
        ),
        "execution_evidence_digest": monitor_binding.get(
            "execution_connectivity_evidence_digest"
        ),
        "verification_evidence_id": monitor_binding.get(
            "verification_connectivity_evidence_id"
        ),
        "verification_evidence_digest": monitor_binding.get(
            "verification_connectivity_evidence_digest"
        ),
    }
    process_evidence_identity = canonical_sha256(
        {
            "monitor_digest": monitor.monitor_digest,
            "process_id": monitor.process_id,
            "process_start_identity": monitor.process_start_identity,
            "verification_process_id": monitor.verification_process_id,
            "verification_process_start_identity": (
                monitor.verification_process_start_identity
            ),
            "codex_session_identity": monitor.codex_session_identity,
            "executable_fingerprint": monitor.executable_fingerprint,
            "isolated_worktree_identity": monitor.isolated_worktree_identity,
            "execution_location_identity": monitor.execution_location_identity,
            "coding_evidence_digest": coding_evidence.get("digest"),
            "verification_evidence_digest": verification_evidence.get("digest"),
            "connectivity_bindings": connectivity_bindings,
        }
    )
    approved_instruction_digest = (
        run.approved_instruction_digest
        or hashlib.sha256((run.pack.content or "").encode("utf-8")).hexdigest()
    )
    try:
        approved_source_snapshot = json.loads(run.pack.source_snapshot_json or "{}")
    except (TypeError, json.JSONDecodeError):
        approved_source_snapshot = {}
    source_repository_identity = (
        approved_source_snapshot.get("source_repository_identity")
        if isinstance(approved_source_snapshot, Mapping)
        else None
    )
    authorized_workspace_identity = (
        str(source_repository_identity)
        if isinstance(source_repository_identity, str)
        and _SHA256_RE.fullmatch(source_repository_identity)
        else canonical_sha256(
            {
                "source_repository": str(run.source_repo or ""),
            }
        )
    )
    process_evidence = {
        "terminal_state": run.status,
        "exit_code": run.exit_code,
        "verification_exit_code": run.verification_exit_code,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "duration_ms": run.duration_ms,
        "timed_out": bool(run.timed_out or run.verification_timed_out),
        "cancelled": bool(run.cancelled or run.verification_cancelled),
        "coding_timed_out": run.timed_out,
        "coding_cancelled": run.cancelled,
        "verification_timed_out": run.verification_timed_out,
        "verification_cancelled": run.verification_cancelled,
        "stdout_summary": _sanitize_text(run.stdout)[:2000],
        "stderr_summary": _sanitize_text(run.stderr)[:2000],
        "output_truncated": run.output_truncated,
        "protected_log_reference": _opaque_log_reference(monitor),
        "process_evidence_identity": process_evidence_identity,
    }
    boundary_violations = workspace_evidence.get("boundary_violations")
    boundary_conflict = bool(
        isinstance(boundary_violations, list) and boundary_violations
    )
    process = _safe_mapping(payload.get("process"))
    process_loss_observed = bool(
        monitor.monitor_state == "PROCESS_LOST"
        or monitor.recovery_state == "PROCESS_LOST"
        or "PROCESS_LOST" in str(monitor.failure_code or "").upper()
        or "PROCESS_IDENTITY_LOST" in str(monitor.failure_code or "").upper()
    )
    coding_interrupted = bool(
        coding_process.get("runtime_interrupted") is True
        or process.get("runtime_interrupted") is True
    )
    coding_status = str(coding_process.get("status") or "").lower()
    coding_exit_code = coding_process.get("exit_code")
    effective_coding_exit_code = (
        coding_exit_code
        if type(coding_exit_code) is int
        else run.exit_code
        if type(run.exit_code) is int
        else None
    )
    coding_exit_conflict = bool(
        type(coding_exit_code) is int
        and type(run.exit_code) is int
        and coding_exit_code != run.exit_code
    )
    coding_cancelled = bool(
        coding_process.get("cancelled") is True
        or process.get("cancelled") is True
        or coding_status == "cancelled"
    )
    coding_timed_out = bool(
        coding_process.get("timed_out") is True
        or process.get("timed_out") is True
        or coding_status == "timed_out"
    )
    coding_succeeded = bool(
        coding_status in {"completed", "succeeded"}
        and not coding_exit_conflict
        and effective_coding_exit_code == 0
    )
    coding_failed = bool(
        coding_status in {"failed", "error"}
        or coding_exit_conflict
        or (
            type(effective_coding_exit_code) is int
            and effective_coding_exit_code != 0
        )
    )
    # Keep the immediately preceding policy's derived classification solely as
    # a replay digest. The source evidence is unchanged; only the presentation
    # rule separating Coding outcome from Verification outcome was corrected.
    verification = _safe_mapping(payload.get("verification"))
    verification_process = _safe_mapping(payload.get("verification_process"))
    prior_runtime_interrupted = bool(
        coding_interrupted
        or verification.get("runtime_interrupted") is True
        or verification_process.get("runtime_interrupted") is True
        or process_loss_observed
    )
    verification_status = str(
        verification_process.get("status")
        or verification.get("status")
        or ""
    ).lower()
    persisted_verification_status = str(run.verification_status or "").lower()
    verification_exit_code = verification_process.get("process_exit")
    if type(verification_exit_code) is not int:
        verification_exit_code = verification.get("exit_code")
    if type(verification_exit_code) is not int:
        verification_exit_code = run.verification_exit_code
    prior_verification_failed = bool(
        verification_status in {"failed", "error", "integrity_blocked"}
        or persisted_verification_status
        in {"failed", "blocked", "error", "integrity_blocked"}
        or (
            type(verification_exit_code) is int
            and verification_exit_code != 0
        )
        or reported_verdict == "FAIL"
    )
    exec_bridge = _safe_mapping(payload.get("exec_bridge"))
    execution_integrity_blocked = bool(
        str(exec_bridge.get("integrity_state") or "").lower() == "blocked"
    )
    if coding_cancelled:
        completion_classification = "cancelled"
    elif coding_timed_out:
        completion_classification = "timed_out"
    elif coding_interrupted or (process_loss_observed and not coding_succeeded):
        completion_classification = "interrupted"
    elif coding_failed:
        completion_classification = "failed"
    elif execution_integrity_blocked:
        completion_classification = "result_incomplete"
    elif coding_succeeded and structured_handoff_status != "captured":
        completion_classification = "result_incomplete"
    elif coding_succeeded and not workspace_evidence_available:
        completion_classification = "result_incomplete"
    elif coding_succeeded and boundary_conflict:
        completion_classification = "workspace_evidence_conflict"
    elif coding_succeeded and manifest:
        completion_classification = "succeeded_with_changes"
    elif coding_succeeded:
        completion_classification = "succeeded_without_workspace_changes"
    elif run.status == "cancelled":
        completion_classification = "cancelled"
    elif run.status == "timed_out":
        completion_classification = "timed_out"
    else:
        completion_classification = "result_incomplete"

    if prior_runtime_interrupted:
        prior_completion_classification = "interrupted"
    elif run.status == "cancelled":
        prior_completion_classification = "cancelled"
    elif run.status == "timed_out":
        prior_completion_classification = "timed_out"
    elif coding_cancelled:
        prior_completion_classification = "cancelled"
    elif coding_timed_out:
        prior_completion_classification = "timed_out"
    elif coding_failed:
        prior_completion_classification = "failed"
    elif execution_integrity_blocked:
        prior_completion_classification = "result_incomplete"
    elif prior_verification_failed:
        prior_completion_classification = "failed"
    elif coding_succeeded and structured_handoff_status != "captured":
        prior_completion_classification = "result_incomplete"
    elif coding_succeeded and not workspace_evidence_available:
        prior_completion_classification = "result_incomplete"
    elif coding_succeeded and boundary_conflict:
        prior_completion_classification = "workspace_evidence_conflict"
    elif coding_succeeded and manifest:
        prior_completion_classification = "succeeded_with_changes"
    elif coding_succeeded:
        prior_completion_classification = "succeeded_without_workspace_changes"
    else:
        prior_completion_classification = "result_incomplete"

    legacy_immutable_payload = {
        "schema": RESULT_INTAKE_SCHEMA,
        "owner_id": monitor.owner_id,
        "run_id": monitor.run_id,
        "task_id": monitor.task_id,
        "task_version": monitor.task_version,
        "pack_id": monitor.pack_id,
        "pack_version": monitor.pack_version,
        "coding_assignment_id": monitor.coding_assignment_id,
        "coding_assignment_version": monitor.coding_assignment_version,
        "verification_assignment_id": monitor.verification_assignment_id,
        "verification_assignment_version": monitor.verification_assignment_version,
        "routing_snapshot_identity": monitor.routing_snapshot_identity,
        "source_snapshot_identity": monitor.source_snapshot_identity,
        "requested_model_identifier": monitor.requested_model_identifier,
        "actual_model_identifier": actual_model,
        "terminal_status": run.status,
        "process_exit_code": run.exit_code,
        "final_response": legacy_final_response,
        "structured_handoff": legacy_structured_handoff,
        "tests": tests,
        "manifest": manifest,
        "diff_identity": diff_identity,
        "coding_evidence": coding_evidence,
        "verification_evidence": verification_evidence,
        "verification_verdict": verdict,
        "warnings": warnings,
        "limitations": limitations,
        "boundaries": boundaries,
        "execution_duration_ms": run.duration_ms,
        "process_evidence_identity": process_evidence_identity,
        "connectivity_bindings": connectivity_bindings,
    }
    immutable_payload = {
        **legacy_immutable_payload,
        "final_response": final_response,
        "structured_handoff": structured_handoff,
        "structured_handoff_status": structured_handoff_status,
        "task_acceptance": task_acceptance,
        "approved_instruction_digest": approved_instruction_digest,
        "authorized_workspace_identity": authorized_workspace_identity,
        "workspace_baseline_identity": monitor.source_snapshot_identity,
        "execution_started_at": _iso(run.started_at),
        "execution_finished_at": _iso(run.finished_at),
        "process_evidence": process_evidence,
        "workspace_evidence": workspace_evidence,
        "completion_classification": completion_classification,
    }
    prior_policy_payload = {
        **immutable_payload,
        "completion_classification": prior_completion_classification,
    }
    return {
        **immutable_payload,
        "result_digest": canonical_sha256(immutable_payload),
        "prior_policy_result_digest": canonical_sha256(prior_policy_payload),
        "legacy_result_digest": canonical_sha256(legacy_immutable_payload),
        "source_identity": canonical_sha256(payload),
    }


def _set_intake_blocked(
    session: Session,
    monitor: CodexRunMonitor,
    error: ResultIntakeError,
) -> None:
    if monitor.monitor_state == "RESULT_AVAILABLE":
        # A stale or conflicting later read cannot downgrade an already
        # verified immutable envelope. Record the rejection as audit evidence.
        session.add(
            AuditEvent(
                actor_user_id=monitor.owner_id,
                action="codex_result_intake_conflict_rejected",
                entity_type="codex_run_monitor",
                entity_id=monitor.id,
                details=f"code={error.code}; run={monitor.run_id}",
            )
        )
        return
    try:
        observe_monitor(
            session,
            monitor,
            state=error.monitor_state,
            recovery_state="INTEGRITY_BLOCKED",
            failure_code=error.code,
            safe_summary=error.safe_message,
        )
    except ResultIntakeError:
        monitor.monitor_state = error.monitor_state
        monitor.recovery_state = "INTEGRITY_BLOCKED"
        monitor.failure_code = error.code
        monitor.safe_summary = error.safe_message
        monitor.last_observed_at = utc_now()
        session.flush()
    session.add(
        AuditEvent(
            actor_user_id=monitor.owner_id,
            action="codex_result_intake_blocked",
            entity_type="codex_run_monitor",
            entity_id=monitor.id,
            details=f"code={error.code}; run={monitor.run_id}",
        )
    )


def _set_persisted_result_pending(
    session: Session,
    monitor: CodexRunMonitor,
) -> None:
    """Keep an exact terminal receipt in bounded settlement, not integrity failure.

    The execution manager and the result watcher use separate transactions. A
    watcher can observe the sealed terminal receipt immediately before the
    manager commits the final structured Run payload. That narrow publication
    race is not evidence corruption and must remain retryable until the bounded
    settlement window expires.
    """

    changed = (
        monitor.monitor_state != "RESULT_PENDING"
        or monitor.failure_code != "RESULT_SETTLEMENT_PENDING"
    )
    observe_monitor(
        session,
        monitor,
        state="RESULT_PENDING",
        recovery_state="RESULT_RECOVERED",
        failure_code="RESULT_SETTLEMENT_PENDING",
        safe_summary="The terminal Codex result is still being settled.",
    )
    if changed:
        session.add(
            AuditEvent(
                actor_user_id=monitor.owner_id,
                action="codex_result_intake_settlement_pending",
                entity_type="codex_run_monitor",
                entity_id=monitor.id,
                details=f"run={monitor.run_id}; bounded_retry=true",
            )
        )


def _execution_integrity_blocker(
    session: Session,
    monitor: CodexRunMonitor,
) -> str:
    if monitor.monitor_state in {
        "RESULT_INTEGRITY_BLOCKED",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
    }:
        return monitor.failure_code or monitor.monitor_state
    snapshot = session.scalar(
        select(CodexLifecycleSnapshot).where(
            CodexLifecycleSnapshot.owner_id == monitor.owner_id,
            CodexLifecycleSnapshot.run_id == monitor.run_id,
        )
    )
    if snapshot is None or snapshot.lifecycle_state not in {
        "RESULT_INTEGRITY_BLOCKED",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
    }:
        return ""
    return snapshot.blocker_code or snapshot.lifecycle_state


def _observe_ingested_result(
    session: Session,
    monitor: CodexRunMonitor,
    *,
    actual_model_identifier: str,
    exit_code: int | None,
    result_source: str,
    execution_integrity_blocked: bool,
) -> None:
    durable_result_source = (
        monitor.result_source
        if monitor.result_source == "codex_exec_jsonl_spool"
        else result_source
    )
    blocker = _execution_integrity_blocker(session, monitor) or (
        "CODING_RESULT_INTEGRITY_BLOCKED"
        if execution_integrity_blocked
        else ""
    )
    if blocker:
        observe_monitor(
            session,
            monitor,
            state="RESULT_INTEGRITY_BLOCKED",
            recovery_state="INTEGRITY_BLOCKED",
            exit_code=exit_code,
            result_source=durable_result_source,
            failure_code=blocker,
            safe_summary=(
                "The durable failure evidence is available, but Coding result "
                "integrity remains blocked."
            ),
        )
        return
    observe_monitor(
        session,
        monitor,
        state="RESULT_AVAILABLE",
        recovery_state=(
            "RESULT_RECOVERED"
            if monitor.recovery_state != "NONE"
            else monitor.recovery_state
        ),
        actual_model_identifier=actual_model_identifier or None,
        exit_code=exit_code,
        result_source=durable_result_source,
        failure_code="",
        safe_summary="The persisted Codex result is available for Owner review.",
    )


def ingest_result_payload(
    session: Session,
    owner_id: int,
    run: CodexRun | int,
    payload: dict[str, Any] | str | bytes,
    *,
    result_source: str = "persisted_run",
    require_explicit_identity: bool = False,
) -> CodexResultEnvelope:
    run = _owner_run(session, owner_id, run)
    monitor = ensure_run_monitor(
        session,
        owner_id,
        run,
        result_source=result_source,
    )
    try:
        parsed = _coerce_payload(payload)
        _validate_result_identity(
            parsed,
            monitor,
            require_explicit_identity=require_explicit_identity,
        )
        _validate_result_completeness(parsed)
        if run.status not in TERMINAL_RUN_STATES:
            raise ResultIntakeError(
                "RUN_NOT_TERMINAL",
                "The Codex Run has not reached a terminal state.",
                monitor_state="RESULT_PENDING",
            )
        material = _result_material(session, run, monitor, parsed)
        exec_bridge = parsed.get("exec_bridge")
        execution_integrity_blocked = bool(
            isinstance(exec_bridge, Mapping)
            and str(exec_bridge.get("integrity_state") or "").lower()
            == "blocked"
        )
        existing = session.scalar(
            select(CodexResultEnvelope).where(
                CodexResultEnvelope.owner_id == owner_id,
                CodexResultEnvelope.run_id == run.id,
            )
        )
        if existing is not None:
            compatible_digests = (
                {
                    material["result_digest"],
                    material["prior_policy_result_digest"],
                }
                if existing.approved_instruction_digest
                else {material["legacy_result_digest"]}
            )
            if existing.result_digest not in compatible_digests:
                raise ResultIntakeError(
                    "RESULT_IMMUTABILITY_CONFLICT",
                    "A different immutable result is already bound to this Run.",
                )
            _observe_ingested_result(
                session,
                monitor,
                actual_model_identifier=str(material["actual_model_identifier"]),
                exit_code=run.exit_code,
                result_source=result_source,
                execution_integrity_blocked=execution_integrity_blocked,
            )
            _materialize_result_delivery_candidate(
                session,
                owner_id=owner_id,
                envelope=existing,
            )
            return existing
        envelope = CodexResultEnvelope(
            envelope_id=f"result-{str(material['result_digest'])[:24]}",
            owner_id=owner_id,
            monitor_id=monitor.id,
            run_id=run.id,
            task_id=run.task_id,
            task_version=run.task_version,
            pack_id=run.pack_id,
            pack_version=run.pack.version,
            coding_assignment_id=monitor.coding_assignment_id,
            coding_assignment_version=monitor.coding_assignment_version,
            verification_assignment_id=monitor.verification_assignment_id,
            verification_assignment_version=monitor.verification_assignment_version,
            routing_snapshot_identity=monitor.routing_snapshot_identity,
            source_snapshot_identity=monitor.source_snapshot_identity,
            approved_instruction_digest=str(material["approved_instruction_digest"]),
            authorized_workspace_identity=str(
                material["authorized_workspace_identity"]
            ),
            workspace_baseline_identity=str(material["workspace_baseline_identity"]),
            requested_model_identifier=monitor.requested_model_identifier,
            actual_model_identifier=str(material["actual_model_identifier"]),
            terminal_status=run.status,
            process_exit_code=run.exit_code,
            final_response=str(material["final_response"]),
            structured_handoff_json=canonical_json(material["structured_handoff"]),
            structured_handoff_status=str(material["structured_handoff_status"]),
            task_acceptance_json=canonical_json(material["task_acceptance"]),
            tests_summary_json=canonical_json(material["tests"]),
            changed_file_manifest_json=canonical_json(material["manifest"]),
            diff_identity=str(material["diff_identity"]),
            coding_evidence_json=canonical_json(material["coding_evidence"]),
            verification_evidence_json=canonical_json(
                material["verification_evidence"]
            ),
            verification_verdict=str(material["verification_verdict"]),
            warnings_json=canonical_json(material["warnings"]),
            limitations_json=canonical_json(material["limitations"]),
            boundary_statements_json=canonical_json(material["boundaries"]),
            process_evidence_json=canonical_json(material["process_evidence"]),
            workspace_evidence_json=canonical_json(material["workspace_evidence"]),
            completion_classification=str(material["completion_classification"]),
            execution_duration_ms=run.duration_ms,
            execution_started_at=run.started_at,
            execution_finished_at=run.finished_at,
            result_source=_sanitize_text(result_source)[:80],
            result_source_identity=str(material["source_identity"]),
            process_evidence_identity=str(material["process_evidence_identity"]),
            result_digest=str(material["result_digest"]),
            integrity_state=(
                "BLOCKED" if execution_integrity_blocked else "VERIFIED"
            ),
            integrity_findings_json=canonical_json(
                ["CODING_RESULT_INTEGRITY_BLOCKED"]
                if execution_integrity_blocked
                else []
            ),
        )
        session.add(envelope)
        try:
            session.flush()
        except IntegrityError:
            # Concurrent bounded polling can race at the uniqueness boundary.
            # Reload the winner and accept it only when its immutable digest is
            # exactly the same.
            session.rollback()
            winner = session.scalar(
                select(CodexResultEnvelope).where(
                    CodexResultEnvelope.owner_id == owner_id,
                    CodexResultEnvelope.run_id == run.id,
                )
            )
            if (
                winner is not None
                and winner.result_digest
                in {
                    material["result_digest"],
                    material["prior_policy_result_digest"],
                }
            ):
                _materialize_result_delivery_candidate(
                    session,
                    owner_id=owner_id,
                    envelope=winner,
                )
                return winner
            raise ResultIntakeError(
                "RESULT_IMMUTABILITY_CONFLICT",
                "A different immutable result is already bound to this Run.",
            )
        for ordinal, raw in enumerate(material["manifest"], start=1):
            row = dict(raw)
            artifact_payload = {
                "result_digest": envelope.result_digest,
                "ordinal": ordinal,
                **row,
            }
            session.add(
                CodexResultArtifact(
                    result_envelope_id=envelope.id,
                    ordinal=ordinal,
                    repository_path=str(row["path"]),
                    display_path=str(row["display_path"]),
                    path_identity=str(row["path_identity"]),
                    operation=str(row["operation"]),
                    before_hash=row["before_hash"],
                    after_hash=row["after_hash"],
                    before_size=row["before_size"],
                    after_size=row["after_size"],
                    before_mode=row["before_mode"],
                    after_mode=row["after_mode"],
                    content_kind=str(row["content_kind"]),
                    unexpected=bool(row["unexpected"]),
                    evidence_identity=str(row["evidence_identity"]),
                    artifact_digest=canonical_sha256(artifact_payload),
                )
            )
        session.flush()
        _observe_ingested_result(
            session,
            monitor,
            actual_model_identifier=str(material["actual_model_identifier"]),
            exit_code=run.exit_code,
            result_source=result_source,
            execution_integrity_blocked=execution_integrity_blocked,
        )
        session.add(
            AuditEvent(
                actor_user_id=owner_id,
                action="codex_result_ingested",
                entity_type="codex_result_envelope",
                entity_id=envelope.id,
                details=(
                    f"run={run.id}; source={_sanitize_text(result_source)[:80]}; "
                    f"integrity={envelope.integrity_state}"
                ),
            )
        )
        _materialize_result_delivery_candidate(
            session,
            owner_id=owner_id,
            envelope=envelope,
        )
        return envelope
    except ResultIntakeError as error:
        settlement_anchor = monitor.terminal_at or run.finished_at
        settlement_age = (
            (utc_now() - settlement_anchor).total_seconds()
            if settlement_anchor is not None
            else PERSISTED_RESULT_SETTLEMENT_SECONDS + 1.0
        )
        if (
            result_source == "persisted_run"
            and monitor.result_source == "codex_exec_jsonl_spool"
            and error.code == "RESULT_INCOMPLETE"
            and settlement_age <= PERSISTED_RESULT_SETTLEMENT_SECONDS
        ):
            _set_persisted_result_pending(session, monitor)
        else:
            _set_intake_blocked(session, monitor, error)
        raise


def _read_result_file(path: str | Path, *, expected_root: str | Path) -> bytes:
    root = Path(expected_root).resolve(strict=True)
    requested = Path(path)
    if not requested.is_absolute():
        requested = root / requested
    if requested.is_symlink():
        raise ResultIntakeError(
            "RESULT_FILE_UNSAFE",
            "The result file is a symbolic link.",
        )
    resolved = requested.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ResultIntakeError(
            "RESULT_FILE_OUTSIDE_ROOT",
            "The result file is outside the authorized execution location.",
        )
    relative = resolved.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                raise ResultIntakeError(
                    "RESULT_FILE_UNSAFE",
                    "The result file path contains a symbolic link.",
                )
        except OSError as exc:
            raise ResultIntakeError(
                "RESULT_FILE_UNAVAILABLE",
                "The durable result file cannot be inspected safely.",
            ) from exc
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise ResultIntakeError(
            "RESULT_FILE_UNAVAILABLE",
            "The durable result file cannot be opened safely.",
        ) from exc
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_size < 0
        or before.st_size > MAX_RESULT_BYTES
    ):
        os.close(descriptor)
        raise ResultIntakeError(
            "RESULT_FILE_INVALID",
            "The result file is not a safe bounded regular file.",
        )
    try:
        payload = bytearray()
        while len(payload) <= MAX_RESULT_BYTES:
            chunk = os.read(
                descriptor,
                min(64 * 1024, MAX_RESULT_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(payload) > MAX_RESULT_BYTES:
        raise ResultIntakeError(
            "RESULT_TOO_LARGE",
            "The Codex result exceeded the safe intake limit.",
        )
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ResultIntakeError(
            "RESULT_FILE_REPLACED",
            "The result file changed while it was being read.",
        )
    return bytes(payload)


def ingest_result_file(
    session: Session,
    owner_id: int,
    run: CodexRun | int,
    result_path: str | Path,
    *,
    expected_root: str | Path,
    result_source: str = "durable_result_file",
) -> CodexResultEnvelope:
    run = _owner_run(session, owner_id, run)
    monitor = ensure_run_monitor(
        session,
        owner_id,
        run,
        result_source=result_source,
        result_path=str(result_path),
    )
    try:
        payload = _read_result_file(result_path, expected_root=expected_root)
        observe_monitor(
            session,
            monitor,
            result_path=str(result_path),
            result_source=result_source,
        )
        return ingest_result_payload(
            session,
            owner_id,
            run,
            payload,
            result_source=result_source,
            require_explicit_identity=False,
        )
    except ResultIntakeError as error:
        _set_intake_blocked(session, monitor, error)
        raise


def import_codex_result(
    session: Session,
    owner_id: int,
    run_id: int,
    payload: dict[str, Any] | str | bytes,
) -> CodexResultEnvelope:
    """Owner-scoped structured fallback; arbitrary handoff prose is rejected."""
    run = _owner_run(session, owner_id, run_id)
    if source_snapshot_unavailable_for_run(session, run):
        raise ResultIntakeError(
            SOURCE_SNAPSHOT_UNAVAILABLE,
            "Source snapshot unavailable. Regenerate Codex Pack.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    monitor = ensure_run_monitor(session, owner_id, run)
    if source_snapshot_unavailable_for_run(session, run, monitor):
        raise ResultIntakeError(
            SOURCE_SNAPSHOT_UNAVAILABLE,
            "Source snapshot unavailable. Regenerate Codex Pack.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    return ingest_result_payload(
        session,
        owner_id,
        run,
        payload,
        result_source="manual_structured_import",
        require_explicit_identity=True,
    )


def _active_process_binding(
    monitor: CodexRunMonitor,
    run: CodexRun,
) -> tuple[int | None, str]:
    if run.status == "verifying":
        return (
            monitor.verification_process_id,
            monitor.verification_process_start_identity,
        )
    return monitor.process_id, monitor.process_start_identity


def _bridge_publication_status(
    root: Path,
    run_id: int,
    phase: str,
) -> tuple[str, codex_exec_bridge.ExecutionHandle | None]:
    phase_directory = root / f"run-{run_id}-{phase}"
    ticket_path = phase_directory / "ticket.json"
    seal_path = phase_directory / "ticket.seal.json"
    if not phase_directory.exists() and not phase_directory.is_symlink():
        return "absent", None
    if ticket_path.exists() and seal_path.exists():
        try:
            return "ready", codex_exec_bridge.handle_from_ticket_path(ticket_path)
        except codex_exec_bridge.CodexExecBridgeError as exc:
            raise ResultIntakeError(exc.code, exc.safe_message) from exc
    try:
        newest_mtime = max(
            item.lstat().st_mtime
            for item in (phase_directory, ticket_path, seal_path)
            if item.exists() or item.is_symlink()
        )
    except (OSError, ValueError) as exc:
        raise ResultIntakeError(
            "BRIDGE_PREPARATION_STATE_INVALID",
            "The durable Codex preparation state could not be verified.",
        ) from exc
    if time.time() - newest_mtime <= 5.0:
        return "preparing", None
    raise ResultIntakeError(
        "BRIDGE_PREPARATION_INCOMPLETE",
        "The durable Codex ticket preparation did not complete within its bounded window.",
    )


def _bridge_terminal_monitor_evidence(
    phase: str,
    receipt: dict[str, object],
) -> dict[str, object]:
    terminal_state = str(receipt.get("terminal_state") or "")
    if terminal_state not in {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "RESULT_INTEGRITY_BLOCKED",
    }:
        raise ResultIntakeError(
            "BRIDGE_TERMINAL_STATE_INVALID",
            "The durable Codex terminal state is invalid.",
        )
    return {
        "phase": phase,
        "terminal": True,
        "terminal_state": terminal_state,
        "sidecar_alive": False,
        "child_alive": False,
    }


def _validated_bridge_monitor_evidence(
    monitor: CodexRunMonitor,
    run: CodexRun,
) -> dict[str, object] | None:
    """Read exact detached-bridge evidence without starting or signalling it.

    The protected locator is server-owned.  Every ticket binding is checked
    again here because the result watcher must never infer process truth from a
    PID, a client value, or a path alone.
    """
    if (
        monitor.result_source != "codex_exec_jsonl_spool"
        or not monitor.protected_result_locator
    ):
        return None
    if (
        run.pack is None
        or run.pack.approved_by_user_id is None
        or run.execution_assignment is None
        or run.verification_assignment is None
    ):
        raise ResultIntakeError(
            "BRIDGE_RUN_BINDING_INCOMPLETE",
            "The durable Codex Run binding is incomplete.",
        )
    root = Path(monitor.protected_result_locator)
    phase = "coding"
    handle: codex_exec_bridge.ExecutionHandle | None = None
    if run.status == "verifying":
        verification_publication, verification_handle = _bridge_publication_status(
            root,
            int(run.id),
            "verification",
        )
        if verification_publication == "preparing":
            return {
                "phase": "verification",
                "terminal": False,
                "terminal_state": "",
                "preparation_pending": True,
                "sidecar_alive": False,
                "child_alive": False,
            }
        if verification_publication == "ready":
            phase = "verification"
            handle = verification_handle
        elif (
            run.verification_process_spawned
            or monitor.verification_process_id is not None
        ):
            raise ResultIntakeError(
                "BRIDGE_VERIFICATION_TICKET_UNAVAILABLE",
                "Verification was spawned but its sealed ticket is unavailable.",
            )
    if handle is None:
        coding_publication, coding_handle = _bridge_publication_status(
            root,
            int(run.id),
            "coding",
        )
        if coding_publication == "preparing":
            return {
                "phase": "coding",
                "terminal": False,
                "terminal_state": "",
                "preparation_pending": True,
                "sidecar_alive": False,
                "child_alive": False,
            }
        if coding_publication != "ready" or coding_handle is None:
            raise ResultIntakeError(
                "BRIDGE_CODING_TICKET_UNAVAILABLE",
                "The sealed Coding ticket is unavailable.",
            )
        handle = coding_handle
    try:
        ticket = codex_exec_bridge.load_ticket(handle)
        identity = ticket.get("identity")
        connectivity = (
            run.verification_connectivity_evidence
            if phase == "verification"
            else run.execution_connectivity_evidence
        )
        expected_connectivity = str(
            connectivity.evidence_digest if connectivity is not None else ""
        )
        expected_model = (
            run.verification_model_identifier
            if phase == "verification"
            else run.requested_model_identifier
        )
        expected: dict[str, object] = {
            "owner_id": int(run.pack.approved_by_user_id),
            "run_id": int(run.id),
            "task_id": int(run.task_id),
            "task_version": int(run.task_version),
            "pack_id": int(run.pack_id),
            "pack_version": int(run.pack.version),
            "coding_assignment_id": int(run.execution_assignment.id),
            "coding_assignment_version": int(
                run.execution_assignment.assignment_version
            ),
            "verification_assignment_id": int(run.verification_assignment.id),
            "verification_assignment_version": int(
                run.verification_assignment.assignment_version
            ),
            "routing_snapshot_identity": run.routing_snapshot_hash,
            "source_snapshot_identity": run.source_snapshot_digest,
            "connectivity_evidence_identity": expected_connectivity,
            "requested_model_identifier": expected_model,
        }
        if (
            not isinstance(identity, dict)
            or ticket.get("phase") != phase
            or ticket.get("phase_key") != f"run-{int(run.id)}-{phase}"
            or any(identity.get(key) != value for key, value in expected.items())
            or any(
                not _SHA256_RE.fullmatch(str(identity.get(key) or ""))
                for key in (
                    "source_remote_fingerprint",
                    "git_boundary_fingerprint",
                    "workspace_snapshot_digest",
                )
            )
            or (
                phase == "coding"
                and identity.get("workspace_snapshot_digest")
                != run.source_snapshot_digest
            )
            or (
                phase == "verification"
                and identity.get("pre_verification_workspace_digest")
                != identity.get("workspace_snapshot_digest")
            )
        ):
            raise ResultIntakeError(
                "BRIDGE_TICKET_BINDING_MISMATCH",
                "The durable Codex execution ticket does not match this Run.",
            )
        try:
            ticket_worktree = Path(
                str(ticket.get("working_directory") or "")
            ).resolve(strict=True)
            persisted_worktree = Path(run.worktree_path).resolve(strict=True)
        except OSError as exc:
            raise ResultIntakeError(
                "BRIDGE_WORKTREE_UNAVAILABLE",
                "The isolated Codex workspace is unavailable.",
            ) from exc
        if ticket_worktree != persisted_worktree:
            raise ResultIntakeError(
                "BRIDGE_WORKTREE_BINDING_MISMATCH",
                "The durable Codex workspace does not match this Run.",
            )
        receipt = codex_exec_bridge.load_terminal_receipt(handle)
        state: dict[str, object] | None = None
        if receipt is None:
            try:
                state = codex_exec_bridge.load_execution_state(handle)
            except codex_exec_bridge.CodexExecBridgeError:
                # State publication and terminal publication are separate
                # atomic operations. Re-read the stronger immutable receipt
                # before classifying a failed state observation.
                receipt = codex_exec_bridge.load_terminal_receipt(handle)
                if receipt is None:
                    raise
    except codex_exec_bridge.CodexExecBridgeError as exc:
        raise ResultIntakeError(exc.code, exc.safe_message) from exc

    if receipt is not None:
        return _bridge_terminal_monitor_evidence(phase, receipt)
    if not isinstance(state, dict):
        receipt = codex_exec_bridge.load_terminal_receipt(handle)
        if receipt is not None:
            return _bridge_terminal_monitor_evidence(phase, receipt)
        try:
            launch = codex_exec_bridge.load_launch_info(handle)
        except codex_exec_bridge.CodexExecBridgeError as exc:
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            if receipt is not None:
                return _bridge_terminal_monitor_evidence(phase, receipt)
            raise ResultIntakeError(exc.code, exc.safe_message) from exc
        if (
            launch is not None
            and codex_exec_bridge.process_identity_matches(
                launch.process_id,
                launch.process_start_identity,
            )
        ):
            return {
                "phase": phase,
                "terminal": False,
                "terminal_state": "",
                "preparation_pending": True,
                "launch_alive": True,
                "sidecar_alive": True,
                "child_alive": False,
            }
        receipt = codex_exec_bridge.load_terminal_receipt(handle)
        if receipt is not None:
            return _bridge_terminal_monitor_evidence(phase, receipt)
        return {
            "phase": phase,
            "terminal": False,
            "terminal_state": "",
            "preparation_pending": False,
            "launch_alive": False,
            "sidecar_alive": False,
            "child_alive": False,
        }
    sidecar_pid = state.get("sidecar_process_id")
    sidecar_identity = state.get("sidecar_process_start_identity")
    sidecar_alive = bool(
        type(sidecar_pid) is int
        and isinstance(sidecar_identity, str)
        and codex_exec_bridge.process_identity_matches(
            sidecar_pid,
            sidecar_identity,
        )
    )
    child_pid = state.get("child_process_id")
    child_identity = state.get("child_process_start_identity")
    child_bound = bool(
        type(child_pid) is int
        and child_pid > 0
        and isinstance(child_identity, str)
        and _SHA256_RE.fullmatch(child_identity)
    )
    child_alive = bool(
        child_bound
        and codex_exec_bridge.process_identity_matches(child_pid, child_identity)
    )
    if not sidecar_alive:
        receipt = codex_exec_bridge.load_terminal_receipt(handle)
        if receipt is not None:
            return _bridge_terminal_monitor_evidence(phase, receipt)
    return {
        "phase": phase,
        "terminal": False,
        "terminal_state": "",
        "preparation_pending": False,
        "launch_alive": False,
        "sidecar_alive": sidecar_alive,
        "child_alive": child_alive,
        "child_bound": child_bound,
    }


def _reconcile_bridge_monitor(
    session: Session,
    monitor: CodexRunMonitor,
    run: CodexRun,
) -> dict[str, object] | None:
    try:
        evidence = _validated_bridge_monitor_evidence(monitor, run)
    except ResultIntakeError as error:
        observe_monitor(
            session,
            monitor,
            state="RESULT_INTEGRITY_BLOCKED",
            recovery_state="INTEGRITY_BLOCKED",
            failure_code=error.code,
            safe_summary=error.safe_message,
        )
        return {
            "run_id": run.id,
            "state": monitor.monitor_state,
            "blocker": error.code,
        }
    if evidence is None:
        return None
    if evidence.get("preparation_pending"):
        exact_launch_alive = bool(evidence.get("launch_alive"))
        if exact_launch_alive:
            clear_stale_monitor_terminal_state(
                session,
                monitor,
                reason="exact_bridge_launch_waiting_for_state",
            )
        observe_monitor(
            session,
            monitor,
            state=(
                "VERIFYING"
                if evidence.get("phase") == "verification"
                else "STARTING"
            ),
            recovery_state=(
                "MONITORING_RESUMED" if exact_launch_alive else "NONE"
            ),
            failure_code="",
            safe_summary=(
                "The exact detached Codex launch is live and publishing its first durable state."
                if exact_launch_alive
                else "The durable Codex execution boundary is still being prepared."
            ),
        )
        return {"run_id": run.id, "state": monitor.monitor_state}
    if evidence["terminal"]:
        if evidence["terminal_state"] == "RESULT_INTEGRITY_BLOCKED":
            observe_monitor(
                session,
                monitor,
                state="RESULT_INTEGRITY_BLOCKED",
                recovery_state="INTEGRITY_BLOCKED",
                failure_code="BRIDGE_RESULT_INTEGRITY_BLOCKED",
                safe_summary="The detached Codex result failed its sealed integrity checks.",
            )
            return {
                "run_id": run.id,
                "state": monitor.monitor_state,
                "blocker": monitor.failure_code,
            }
        # The receipt proves process termination, but only the execution
        # manager may parse it, continue the separate phase, and persist the
        # final Run result.  Keep the active phase state until that finalizer
        # commits, avoiding a false PROCESS_LOST transition in the handoff gap.
        observe_monitor(
            session,
            monitor,
            recovery_state="RESULT_RECOVERED",
            safe_summary=(
                "Terminal Coding evidence was recovered and is awaiting durable finalization."
                if evidence["phase"] == "coding"
                else "Terminal Verification evidence was recovered and is awaiting durable finalization."
            ),
        )
        return {"run_id": run.id, "state": monitor.monitor_state}
    if evidence["sidecar_alive"]:
        clear_stale_monitor_terminal_state(
            session,
            monitor,
            reason="exact_bridge_process_resumed",
        )
        target_state = RUN_TO_MONITOR_STATE.get(run.status, monitor.monitor_state)
        observe_monitor(
            session,
            monitor,
            state=target_state,
            recovery_state="MONITORING_RESUMED",
            failure_code="",
            safe_summary="Monitoring resumed from the exact sealed detached-process identity.",
        )
        return {"run_id": run.id, "state": monitor.monitor_state}
    observe_monitor(
        session,
        monitor,
        state="PROCESS_LOST",
        recovery_state="PROCESS_LOST",
        failure_code="BRIDGE_PROCESS_IDENTITY_LOST",
        safe_summary=(
            "The detached Codex process no longer matches its sealed start identity; "
            "no replacement process was launched."
        ),
    )
    return {
        "run_id": run.id,
        "state": monitor.monitor_state,
        "blocker": monitor.failure_code,
    }


def reconnect_run_monitor(
    session: Session,
    owner_id: int,
    run_id: int,
) -> CodexRunMonitor:
    run = _owner_run(session, owner_id, run_id)
    if source_snapshot_unavailable_for_run(session, run):
        raise ResultIntakeError(
            SOURCE_SNAPSHOT_UNAVAILABLE,
            "Source snapshot unavailable. Regenerate Codex Pack.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    monitor = ensure_run_monitor(session, owner_id, run)
    if source_snapshot_unavailable_for_run(session, run, monitor):
        raise ResultIntakeError(
            SOURCE_SNAPSHOT_UNAVAILABLE,
            "Source snapshot unavailable. Regenerate Codex Pack.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    if monitor.monitor_state not in ACTIVE_MONITOR_STATES | {
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
        "RESULT_PENDING",
    }:
        return monitor
    active_pid, active_identity = _active_process_binding(monitor, run)
    if active_pid is not None and process_identity_matches(
        active_pid,
        active_identity,
    ):
        observe_monitor(
            session,
            monitor,
            state=RUN_TO_MONITOR_STATE.get(run.status, monitor.monitor_state),
            recovery_state="MONITORING_RESUMED",
            safe_summary="Monitoring resumed for the exact persisted Codex process.",
        )
        return monitor
    if run.status in TERMINAL_RUN_STATES and run.structured_result not in {"", "{}"}:
        observe_monitor(
            session,
            monitor,
            state="RESULT_PENDING",
            recovery_state="RESULT_RECOVERED",
            safe_summary="A durable terminal result was found during reconnect.",
        )
        return monitor
    observe_monitor(
        session,
        monitor,
        state="PROCESS_LOST",
        recovery_state="PROCESS_LOST",
        failure_code="PROCESS_IDENTITY_UNAVAILABLE",
        safe_summary="The original Codex process could not be reconnected safely.",
    )
    return monitor


def _reconcile_one(
    session: Session,
    monitor: CodexRunMonitor,
    *,
    allow_process_handoff_window: bool = False,
) -> dict[str, object]:
    run = session.get(CodexRun, monitor.run_id)
    if run is None:
        observe_monitor(
            session,
            monitor,
            state="RESULT_UNAVAILABLE",
            recovery_state="RESULT_UNAVAILABLE",
            failure_code="RUN_UNAVAILABLE",
            safe_summary="The bound Codex Run is unavailable.",
        )
        return {"run_id": monitor.run_id, "state": monitor.monitor_state}
    envelope = session.scalar(
        select(CodexResultEnvelope).where(
            CodexResultEnvelope.owner_id == monitor.owner_id,
            CodexResultEnvelope.run_id == monitor.run_id,
        )
    )
    lifecycle_state = ""
    if (
        monitor.result_source == "codex_exec_jsonl_spool"
        and monitor.protected_result_locator
    ):
        try:
            lifecycle = reconcile_execution_attempt(
                session,
                monitor.owner_id,
                run,
                monitor,
            )
        except LifecycleReconciliationError as error:
            lifecycle = settle_reconciliation_error(
                session,
                monitor.owner_id,
                run,
                monitor,
                error,
            )
            return {
                "run_id": run.id,
                "state": monitor.monitor_state,
                "blocker": lifecycle.get("blocker") or error.code,
            }
        if lifecycle.get("handled") is True:
            lifecycle_state = str(lifecycle.get("state") or "")
            result: dict[str, object] = {
                "run_id": run.id,
                "state": monitor.monitor_state,
            }
            if lifecycle.get("blocker"):
                result["blocker"] = lifecycle["blocker"]
            if lifecycle.get("recovery_needed") is True:
                result["recovery_needed"] = True
            # An immutable envelope is stronger than an execution snapshot;
            # allow the existing envelope branch below to converge the monitor
            # to RESULT_AVAILABLE in the same transaction.
            terminal_payload_ready = bool(
                run.status in TERMINAL_RUN_STATES
                and run.structured_result
                and run.structured_result != "{}"
            )
            if (
                not terminal_payload_ready
                and (
                    lifecycle.get("recovery_needed") is True
                    or lifecycle.get("blocker")
                    or lifecycle_state
                    in {"STARTING", "RUNNING", "VERIFYING", "SETTLING"}
                    or envelope is None
                )
            ):
                return result
    if envelope is not None:
        _materialize_result_delivery_candidate(
            session,
            owner_id=monitor.owner_id,
            envelope=envelope,
        )
        if lifecycle_state in {
            "RESULT_INTEGRITY_BLOCKED",
            "PROCESS_LOST",
            "RESULT_UNAVAILABLE",
        }:
            blocker = _execution_integrity_blocker(session, monitor)
            if monitor.monitor_state != "RESULT_INTEGRITY_BLOCKED":
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_INTEGRITY_BLOCKED",
                    recovery_state="INTEGRITY_BLOCKED",
                    failure_code=blocker or lifecycle_state,
                    safe_summary=(
                        "The durable failure evidence is available, but Coding "
                        "result integrity remains blocked."
                    ),
                )
            return {
                "run_id": run.id,
                "state": monitor.monitor_state,
                "blocker": monitor.failure_code or blocker or lifecycle_state,
                "result_digest": envelope.result_digest,
            }
        if envelope.integrity_state != "VERIFIED":
            if monitor.monitor_state != "RESULT_INTEGRITY_BLOCKED":
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_INTEGRITY_BLOCKED",
                    recovery_state="INTEGRITY_BLOCKED",
                    failure_code="RESULT_ENVELOPE_INTEGRITY_BLOCKED",
                    safe_summary="The persisted Codex result failed integrity validation.",
                )
            return {
                "run_id": run.id,
                "state": monitor.monitor_state,
                "blocker": monitor.failure_code,
            }
        if monitor.monitor_state != "RESULT_AVAILABLE":
            observe_monitor(
                session,
                monitor,
                state="RESULT_AVAILABLE",
                recovery_state="RESULT_RECOVERED",
                failure_code="",
                safe_summary="The immutable Codex result was recovered.",
            )
        return {
            "run_id": run.id,
            "state": monitor.monitor_state,
            "result_digest": envelope.result_digest,
        }
    if run.status not in TERMINAL_RUN_STATES:
        bridge_reconciliation = _reconcile_bridge_monitor(
            session,
            monitor,
            run,
        )
        if bridge_reconciliation is not None:
            return bridge_reconciliation
    mapped_state = RUN_TO_MONITOR_STATE.get(run.status)
    if run.status in TERMINAL_RUN_STATES:
        if monitor.monitor_state not in {
            mapped_state,
            "PROCESS_LOST",
            "RESULT_PENDING",
            "RESULT_UNAVAILABLE",
            "RESULT_INTEGRITY_BLOCKED",
        }:
            observe_monitor(
                session,
                monitor,
                state=mapped_state,
                exit_code=run.exit_code,
                safe_summary="The Codex process reached a terminal state.",
            )
        if run.structured_result and run.structured_result != "{}":
            if monitor.monitor_state != "RESULT_PENDING":
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_PENDING",
                    recovery_state=(
                        "RESULT_RECOVERED"
                        if monitor.recovery_state != "NONE"
                        else "NONE"
                    ),
                    safe_summary="A terminal Codex result is being validated.",
                )
            try:
                envelope = ingest_result_payload(
                    session,
                    monitor.owner_id,
                    run,
                    run.structured_result,
                    result_source="persisted_run",
                )
                if (
                    monitor.result_source == "codex_exec_jsonl_spool"
                    and monitor.protected_result_locator
                ):
                    reconcile_execution_attempt(
                        session,
                        monitor.owner_id,
                        run,
                        monitor,
                    )
                return {
                    "run_id": run.id,
                    "state": "RESULT_AVAILABLE",
                    "result_digest": envelope.result_digest,
                }
            except ResultIntakeError as error:
                return {
                    "run_id": run.id,
                    "state": monitor.monitor_state,
                    "blocker": error.code,
                }
        if monitor.monitor_state == "PROCESS_LOST":
            return {
                "run_id": run.id,
                "state": "PROCESS_LOST",
                "blocker": monitor.failure_code or "PROCESS_LOST",
            }
        if monitor.monitor_state != "RESULT_UNAVAILABLE":
            observe_monitor(
                session,
                monitor,
                state="RESULT_UNAVAILABLE",
                recovery_state="RESULT_UNAVAILABLE",
                failure_code="RESULT_NOT_FOUND",
                safe_summary="The terminal Codex process did not provide a durable result.",
            )
        return {
            "run_id": run.id,
            "state": monitor.monitor_state,
            "blocker": monitor.failure_code,
        }
    if monitor.monitor_state in PROCESS_TERMINAL_STATES | RESULT_TERMINAL_STATES:
        # A stale CodexRun row must never regress stronger process/result
        # evidence already persisted by the execution manager.
        return {
            "run_id": run.id,
            "state": monitor.monitor_state,
            "blocker": monitor.failure_code or None,
        }
    active_pid, active_identity = _active_process_binding(monitor, run)
    if active_pid is not None:
        if process_identity_matches(active_pid, active_identity):
            target_state = mapped_state or monitor.monitor_state
            if target_state != monitor.monitor_state:
                observe_monitor(
                    session,
                    monitor,
                    state=target_state,
                    recovery_state="MONITORING_RESUMED",
                    safe_summary="The exact Codex process remains active.",
                )
            else:
                observe_monitor(
                    session,
                    monitor,
                    recovery_state=(
                        "MONITORING_RESUMED"
                        if monitor.recovery_state != "NONE"
                        else "NONE"
                    ),
                    safe_summary="The exact Codex process remains active.",
                )
            return {"run_id": run.id, "state": monitor.monitor_state}
        heartbeat_age = (
            (utc_now() - monitor.last_heartbeat_at).total_seconds()
            if monitor.last_heartbeat_at is not None
            else 999.0
        )
        if allow_process_handoff_window and heartbeat_age < 5.0:
            # A process may exit just before the execution worker durably
            # records its terminal/Verification transition. Allow one bounded
            # handoff window; the worker or next reconciliation resolves it.
            return {
                "run_id": run.id,
                "state": monitor.monitor_state,
            }
        observe_monitor(
            session,
            monitor,
            state="PROCESS_LOST",
            recovery_state="PROCESS_LOST",
            failure_code="PID_REUSED_OR_PROCESS_LOST",
            safe_summary=(
                "The persisted PID no longer has the exact Codex process start identity."
            ),
        )
        return {
            "run_id": run.id,
            "state": monitor.monitor_state,
            "blocker": monitor.failure_code,
        }
    if mapped_state and mapped_state != monitor.monitor_state:
        observe_monitor(
            session,
            monitor,
            state=mapped_state,
            safe_summary="The Codex Run state was reconciled from durable evidence.",
        )
    else:
        observe_monitor(
            session,
            monitor,
            safe_summary="Waiting for the persisted Codex process identity.",
        )
    return {"run_id": run.id, "state": monitor.monitor_state}


def reconcile_run_monitors(
    factory: sessionmaker[Session],
    *,
    run_ids: Iterable[int] | None = None,
    allow_process_handoff_window: bool = False,
    on_recovery_needed: Callable[[int], object] | None = None,
) -> list[dict[str, object]]:
    requested = set(run_ids) if run_ids is not None else None
    with factory() as session:
        statement = select(CodexRunMonitor.id, CodexRunMonitor.run_id).where(
            CodexRunMonitor.monitor_state != "RESULT_AVAILABLE"
        )
        if requested is not None:
            statement = statement.where(CodexRunMonitor.run_id.in_(requested))
        monitor_bindings = [
            (int(monitor_id), int(run_id))
            for monitor_id, run_id in session.execute(
                statement.order_by(CodexRunMonitor.id)
            ).all()
        ]
    results: list[dict[str, object]] = []
    recovery_run_ids: list[int] = []
    # One transaction per Run isolates a damaged historical attempt from all
    # other active monitors and gives the lifecycle CAS columns a clear commit
    # boundary.
    for monitor_id, run_id in monitor_bindings:
        # Database-scoped keyed locks coordinate concurrent app instances but
        # self-evict when the final holder/waiter exits, so disposed temporary
        # runtimes cannot serialize an unrelated database that reuses row id 1.
        with factory() as lock_scope_session, _reconciliation_lock(
            lock_scope_session,
            "monitor",
            int(monitor_id),
        ), _reconciliation_lock(
            lock_scope_session,
            "run",
            int(run_id),
        ):
            result: dict[str, object] | None = None
            fallback_run_id = 0
            fallback_state = "RESULT_UNAVAILABLE"
            # A uniqueness conflict can only mean another runtime committed
            # the same immutable attempt/snapshot boundary first. Roll back and
            # reload once so both reconcilers converge on that durable row.
            for retry_number in range(2):
                with factory() as session:
                    monitor = session.get(CodexRunMonitor, monitor_id)
                    if monitor is None:
                        break
                    fallback_run_id = int(monitor.run_id)
                    fallback_state = monitor.monitor_state
                    try:
                        result = _reconcile_one(
                            session,
                            monitor,
                            allow_process_handoff_window=allow_process_handoff_window,
                        )
                        session.commit()
                        break
                    except IntegrityError:
                        session.rollback()
                        if retry_number == 0:
                            continue
                    except Exception:
                        session.rollback()
                    # Failure isolation is deliberate. No exception detail is
                    # returned because it may include a protected spool location.
                    result = {
                        "run_id": fallback_run_id,
                        "state": fallback_state,
                        "blocker": "LIFECYCLE_RECONCILIATION_FAILED",
                    }
                    break
            if result is None:
                continue
            results.append(result)
            if result.get("recovery_needed") is True:
                recovery_run_ids.append(int(result["run_id"]))
    # The execution manager callback may parse/finalize a sealed receipt, so it
    # is intentionally invoked only after the lifecycle transaction commits.
    # Result Intake itself never launches a replacement process.
    if on_recovery_needed is not None:
        for run_id in dict.fromkeys(recovery_run_ids):
            try:
                on_recovery_needed(run_id)
            except Exception:
                # A later bounded polling pass may retry the idempotent manager
                # callback; one failed Run cannot terminate the watcher.
                continue
    return results


class ResultIntakeMonitor:
    """A bounded watcher for persisted active Runs, never a general scheduler."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        poll_seconds: float = 1.0,
        on_recovery_needed: Callable[[int], object] | None = None,
    ) -> None:
        self.factory = factory
        self.poll_seconds = min(5.0, max(0.25, float(poll_seconds)))
        self.on_recovery_needed = on_recovery_needed
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="twos-codex-result-intake",
                daemon=True,
            )
            self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def reconcile_now(self, run_ids: Iterable[int] | None = None) -> list[dict[str, object]]:
        return reconcile_run_monitors(
            self.factory,
            run_ids=run_ids,
            on_recovery_needed=self.on_recovery_needed,
        )

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _has_pending_monitors(self) -> bool:
        fast_poll_states = tuple(
            ACTIVE_MONITOR_STATES
            | {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "RESULT_PENDING",
            }
        )
        with self.factory() as session:
            ordinary_pending = session.scalar(
                select(CodexRunMonitor.id)
                .where(CodexRunMonitor.monitor_state.in_(fast_poll_states))
                .limit(1)
            )
            if ordinary_pending is not None:
                return True
            # A sealed bridge may publish an integrity blocker just before the
            # execution manager commits its terminal process/workspace payload.
            # Keep polling only that bounded evidence-without-envelope gap so a
            # missing structured handoff still receives an immutable, honestly
            # incomplete Run Result. Once the envelope exists, this query drops
            # the terminal monitor and avoids permanent busy polling.
            terminal_evidence_rows = session.execute(
                select(CodexRunMonitor.terminal_at, CodexRun.finished_at)
                .join(CodexRun, CodexRun.id == CodexRunMonitor.run_id)
                .outerjoin(
                    CodexResultEnvelope,
                    CodexResultEnvelope.run_id == CodexRunMonitor.run_id,
                )
                .where(
                    CodexRunMonitor.monitor_state.in_(
                        (
                            "RESULT_INTEGRITY_BLOCKED",
                            "RESULT_UNAVAILABLE",
                            "PROCESS_LOST",
                        )
                    ),
                    CodexRun.status.in_(tuple(TERMINAL_RUN_STATES)),
                    CodexRun.structured_result.not_in(("", "{}")),
                    CodexResultEnvelope.id.is_(None),
                )
            ).all()
            now = utc_now()
            return any(
                anchor is not None
                and (now - anchor).total_seconds()
                <= PERSISTED_RESULT_SETTLEMENT_SECONDS
                for monitor_terminal_at, run_finished_at in terminal_evidence_rows
                for anchor in (monitor_terminal_at or run_finished_at,)
            )

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._has_pending_monitors():
                try:
                    reconcile_run_monitors(
                        self.factory,
                        allow_process_handoff_window=True,
                        on_recovery_needed=self.on_recovery_needed,
                    )
                except Exception:
                    # A failed bounded pass must not terminate monitoring or
                    # launch a replacement process. The next pass retries.
                    pass
                delay = self.poll_seconds
            else:
                # No active/result-pending Run means no unrelated scheduler work.
                delay = 5.0
            self._wake.wait(delay)
            self._wake.clear()


def _decoded_json(value: str, fallback: object) -> object:
    try:
        decoded = json.loads(value or "")
    except json.JSONDecodeError:
        return fallback
    return decoded


def get_or_create_handoff_review(
    session: Session,
    owner_id: int,
    run_id: int,
) -> HandoffReview:
    run = _owner_run(session, owner_id, run_id)
    envelope = session.scalar(
        select(CodexResultEnvelope).where(
            CodexResultEnvelope.owner_id == owner_id,
            CodexResultEnvelope.run_id == run.id,
        )
    )
    if envelope is None or envelope.integrity_state != "VERIFIED":
        raise ResultIntakeError(
            "RESULT_NOT_AVAILABLE",
            "A verified Run Result is required before Review Handoff.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    public_result = result_envelope_out(envelope)
    existing = session.scalar(
        select(HandoffReview).where(
            HandoffReview.owner_id == owner_id,
            HandoffReview.result_envelope_id == envelope.id,
        )
    )
    if existing is not None:
        if (
            existing.recommended_reconciliation == "PASS"
            and public_result.get("execution_successful") is not True
        ):
            raise ResultIntakeError(
                "HANDOFF_PROVENANCE_BLOCKED",
                "The historical Handoff review lacks current verified model-execution provenance.",
                monitor_state="RESULT_INTEGRITY_BLOCKED",
            )
        return existing
    handoff = _decoded_json(envelope.structured_handoff_json, {})
    handoff = handoff if isinstance(handoff, dict) else {}
    tests = _decoded_json(envelope.tests_summary_json, [])
    warnings = _decoded_json(envelope.warnings_json, [])
    limitations = _decoded_json(envelope.limitations_json, [])
    boundaries = _decoded_json(envelope.boundary_statements_json, {})
    manifest = _decoded_json(envelope.changed_file_manifest_json, [])
    task_acceptance = handoff.get("task_acceptance", {})
    if not isinstance(task_acceptance, Mapping) or not task_acceptance:
        task_acceptance = _decoded_json(envelope.task_acceptance_json, {})
    acceptance_status = (
        str(task_acceptance.get("status", "")).lower()
        if isinstance(task_acceptance, Mapping)
        else ""
    )
    blockers: list[str] = []
    verification_required = envelope.verification_assignment_id is not None
    if envelope.terminal_status != "completed":
        blockers.append(f"Run ended as {envelope.terminal_status}.")
    if verification_required and envelope.verification_verdict != "PASS":
        verification_public = public_result.get("verification_result", {})
        verification_public_evidence = (
            verification_public.get("evidence", {})
            if isinstance(verification_public, Mapping)
            else {}
        )
        verification_summary = (
            _sanitize_text(
                str(verification_public_evidence.get("safe_summary", ""))
            )
            if isinstance(verification_public_evidence, Mapping)
            else ""
        )
        blockers.append(
            "Independent Verification did not report PASS"
            + (
                f": {verification_summary}"
                if verification_summary
                and verification_summary != "Evidence is unavailable."
                else "."
            )
        )
    if acceptance_status not in {"pass", "passed", "accepted"}:
        blockers.append("Task acceptance is not satisfied by the ingested result.")
    if envelope.integrity_state != "VERIFIED":
        blockers.append("Result integrity is blocked.")
    coding_public = public_result.get("coding_result", {})
    if not (
        isinstance(coding_public, Mapping)
        and coding_public.get("verified_real_invocation") is True
    ):
        blockers.append("Verified Coding process evidence is unavailable.")
    if public_result.get("requested_model_accepted") is not True:
        blockers.append("The requested Coding model was not verified as accepted for execution.")
    verification_public = public_result.get("verification_result", {})
    verification_public_evidence = (
        verification_public.get("evidence", {})
        if isinstance(verification_public, Mapping)
        else {}
    )
    if verification_required and not (
        isinstance(verification_public_evidence, Mapping)
        and (
            (
                verification_public_evidence.get("verified_real_invocation") is True
                and verification_public_evidence.get("requested_model_accepted")
                is True
            )
            or (
                verification_public_evidence.get("verified_local_process") is True
                and verification_public_evidence.get("mode") == "local_command"
                and verification_public_evidence.get("model_provider_invoked") is False
            )
        )
    ):
        blockers.append("Verified independent Verification process evidence is unavailable.")
    recommendation = "PASS" if not blockers else "BLOCKED"
    coding = _decoded_json(envelope.coding_evidence_json, {})
    coding_summary = (
        str(coding.get("safe_summary", ""))
        if isinstance(coding, Mapping)
        else ""
    ) or envelope.final_response or "Coding evidence is available."
    review_payload = {
        "policy": RESULT_INTAKE_POLICY,
        "owner_id": owner_id,
        "result_digest": envelope.result_digest,
        "run_id": run.id,
        "run_outcome": envelope.terminal_status,
        "coding_result": coding_summary,
        "verification_verdict": envelope.verification_verdict,
        "changed_files": manifest,
        "tests": tests,
        "warnings": warnings,
        "limitations": limitations,
        "boundaries": boundaries,
        "current_phase_gate": (
            "Owner review is required. No result acceptance, Candidate, Apply, "
            "next instruction, or next Run occurs automatically."
        ),
        "recommended_reconciliation": recommendation,
        "unresolved_blockers": blockers,
    }
    review_digest = canonical_sha256(review_payload)
    review = HandoffReview(
        review_id=f"handoff-{review_digest[:24]}",
        owner_id=owner_id,
        result_envelope_id=envelope.id,
        run_id=run.id,
        task_id=run.task_id,
        pack_id=run.pack_id,
        run_outcome=envelope.terminal_status,
        coding_result=_sanitize_text(coding_summary),
        verification_verdict=envelope.verification_verdict,
        changed_files_json=canonical_json(manifest),
        tests_json=canonical_json(tests),
        warnings_json=canonical_json(warnings),
        limitations_json=canonical_json(limitations),
        boundary_confirmation_json=canonical_json(boundaries),
        current_phase_gate=str(review_payload["current_phase_gate"]),
        recommended_reconciliation=recommendation,
        unresolved_blockers_json=canonical_json(blockers),
        review_digest=review_digest,
    )
    session.add(review)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="codex_handoff_review_created",
            entity_type="handoff_review",
            entity_id=review.id,
            details=(
                f"run={run.id}; recommendation={recommendation}; "
                "analysis_only=true"
            ),
        )
    )
    return review


def get_or_create_instruction_draft(
    session: Session,
    owner_id: int,
    handoff_review: HandoffReview | int,
) -> HandoffInstructionDraft:
    review = (
        session.get(HandoffReview, handoff_review)
        if isinstance(handoff_review, int)
        else handoff_review
    )
    if review is None or review.owner_id != owner_id:
        raise ResultIntakeError(
            "HANDOFF_REVIEW_NOT_FOUND",
            "Handoff Review not found.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    existing = session.scalar(
        select(HandoffInstructionDraft).where(
            HandoffInstructionDraft.handoff_review_id == review.id,
            HandoffInstructionDraft.owner_id == owner_id,
        )
    )
    if existing is not None:
        return existing
    envelope = session.get(CodexResultEnvelope, review.result_envelope_id)
    if envelope is None or envelope.owner_id != owner_id:
        raise ResultIntakeError(
            "RESULT_NOT_AVAILABLE",
            "The verified Run Result is unavailable.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    instruction_id = f"TWOS-RUN-{review.run_id}-HANDOFF-NEXT-R1"
    revision = 1
    scope = (
        "Resolve the blockers identified by Review Handoff."
        if review.recommended_reconciliation == "BLOCKED"
        else "Prepare the next Owner-approved implementation step after the verified Run result."
    )
    supersession = (
        "This draft does not supersede an instruction until the Owner explicitly "
        "approves and separately activates it."
    )
    completion_gate = [
        "The approved scope is completed.",
        "All identified blockers are resolved truthfully.",
        "Required focused and regression validation passes.",
        "No unauthorized action is performed.",
    ]
    required_handoff = [
        "Instruction identity and PASS/BLOCKED result.",
        "Changed-file inventory.",
        "Validation evidence and warnings.",
        "Final Git and authorization boundary state.",
    ]
    instruction_text = "\n".join(
        [
            f"INSTRUCTION ID: {instruction_id}",
            f"REVISION: R{revision}",
            "STATUS: DRAFT — OWNER APPROVAL REQUIRED",
            f"SCOPE: {scope}",
            f"SUPERSESSION: {supersession}",
            "COMPLETION GATE:",
            *[f"- {item}" for item in completion_gate],
            "REQUIRED HANDOFF:",
            *[f"- {item}" for item in required_handoff],
            "EXECUTION: NOT AUTHORIZED BY THIS DRAFT",
        ]
    )
    immutable = {
        "policy": RESULT_INTAKE_POLICY,
        "owner_id": owner_id,
        "handoff_review_digest": review.review_digest,
        "result_digest": envelope.result_digest,
        "run_id": review.run_id,
        "instruction_id": instruction_id,
        "revision": revision,
        "scope": scope,
        "supersession": supersession,
        "completion_gate": completion_gate,
        "required_handoff": required_handoff,
        "instruction_text": instruction_text,
    }
    draft_digest = canonical_sha256(immutable)
    draft = HandoffInstructionDraft(
        draft_id=f"draft-{draft_digest[:24]}",
        owner_id=owner_id,
        handoff_review_id=review.id,
        result_envelope_id=envelope.id,
        run_id=review.run_id,
        instruction_id=instruction_id,
        revision=revision,
        scope=scope,
        supersession=supersession,
        completion_gate_json=canonical_json(completion_gate),
        required_handoff_json=canonical_json(required_handoff),
        instruction_text=instruction_text,
        draft_digest=draft_digest,
        approval_state="OWNER_APPROVAL_REQUIRED",
    )
    session.add(draft)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="codex_instruction_draft_created",
            entity_type="handoff_instruction_draft",
            entity_id=draft.id,
            details=(
                f"run={review.run_id}; owner_approval_required=true; "
                "execution_started=false"
            ),
        )
    )
    return draft


def approve_instruction_draft(
    session: Session,
    owner_id: int,
    draft_id: int,
) -> HandoffInstructionDraft:
    draft = session.scalar(
        select(HandoffInstructionDraft).where(
            HandoffInstructionDraft.id == draft_id,
            HandoffInstructionDraft.owner_id == owner_id,
        )
    )
    if draft is None:
        raise ResultIntakeError(
            "INSTRUCTION_DRAFT_NOT_FOUND",
            "Instruction draft not found.",
            monitor_state="RESULT_UNAVAILABLE",
        )
    if draft.approval_state == "APPROVED":
        return draft
    draft.approval_state = "APPROVED"
    draft.approved_by_user_id = owner_id
    draft.approved_at = utc_now()
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=owner_id,
            action="codex_instruction_draft_approved",
            entity_type="handoff_instruction_draft",
            entity_id=draft.id,
            details="Draft approval recorded; no Codex Run was created or started.",
        )
    )
    return draft


def _sealed_envelope_execution_truth(
    envelope: CodexResultEnvelope,
) -> tuple[
    str,
    bool,
    bool,
    bool,
    dict[str, object],
    dict[str, object],
]:
    coding_value = _decoded_json(envelope.coding_evidence_json, {})
    verification_value = _decoded_json(envelope.verification_evidence_json, {})
    coding = dict(coding_value) if isinstance(coding_value, Mapping) else {}
    verification = (
        dict(verification_value)
        if isinstance(verification_value, Mapping)
        else {}
    )
    actual = str(coding.get("actual_model") or "")
    coding_requested_accepted = coding.get("requested_model_accepted")
    if coding_requested_accepted is None:
        # Immutable envelopes created by the immediately preceding policy did
        # not persist this derived presentation flag.  Their verified real
        # invocation + successful outcome is the same server-side proof.
        coding_requested_accepted = bool(
            coding.get("verified_real_invocation") is True
            and coding.get("outcome") == "succeeded"
        )
    verification_requested_accepted = verification.get(
        "requested_model_accepted"
    )
    if verification_requested_accepted is None:
        verification_requested_accepted = bool(
            verification.get("verified_real_invocation") is True
            and verification.get("outcome") == "succeeded"
        )
    coding["requested_model_accepted"] = bool(coding_requested_accepted)
    verification["requested_model_accepted"] = bool(
        verification_requested_accepted
    )
    coding_verified = bool(
        envelope.integrity_state == "VERIFIED"
        and envelope.process_exit_code == 0
        and coding.get("verified_real_invocation") is True
        and coding.get("outcome") == "succeeded"
        and coding_requested_accepted is True
    )
    actual_verified = bool(
        coding_verified
        and coding.get("actual_model_verified") is True
        and actual
        and actual == envelope.actual_model_identifier
    )
    verification_verified = bool(
        envelope.integrity_state == "VERIFIED"
        and verification.get("outcome") == "succeeded"
        and envelope.verification_verdict == "PASS"
        and (
            (
                verification.get("verified_real_invocation") is True
                and verification_requested_accepted is True
            )
            or (
                verification.get("verified_local_process") is True
                and verification.get("mode") == "local_command"
                and verification.get("model_provider_invoked") is False
            )
        )
    )
    if not actual_verified:
        actual = ""
        coding["actual_model"] = ""
        coding["actual_model_verified"] = False
        coding["model_identity_source"] = None
        coding["connectivity_evidence_identity"] = None
    if not verification_verified:
        verification["actual_model"] = ""
        verification["actual_model_verified"] = False
        verification["model_identity_source"] = None
        verification["connectivity_evidence_identity"] = None
    return (
        actual,
        actual_verified,
        coding_verified,
        verification_verified,
        coding,
        verification,
    )


def monitor_out(
    monitor: CodexRunMonitor,
    *,
    envelope: CodexResultEnvelope | None = None,
    advanced: bool = False,
) -> dict[str, object]:
    actual_model = ""
    actual_model_verified = False
    if (
        envelope is not None
        and envelope.owner_id == monitor.owner_id
        and envelope.run_id == monitor.run_id
    ):
        actual_model, actual_model_verified, _, _, _, _ = (
            _sealed_envelope_execution_truth(envelope)
        )
    output: dict[str, object] = {
        "id": monitor.monitor_id,
        "run_id": monitor.run_id,
        "task_id": monitor.task_id,
        "state": monitor.monitor_state,
        "requested_model": monitor.requested_model_identifier,
        "actual_model": actual_model or None,
        "actual_model_verified": actual_model_verified,
        "started_at": _iso(monitor.started_at),
        "last_heartbeat_at": _iso(monitor.last_heartbeat_at),
        "terminal_at": _iso(monitor.terminal_at),
        "result_source": monitor.result_source,
        "recovery_state": monitor.recovery_state,
        "failure_code": monitor.failure_code or None,
        "summary": monitor.safe_summary,
    }
    if advanced:
        output["advanced"] = {
            "monitor_digest": monitor.monitor_digest,
            "task_version": monitor.task_version,
            "pack_id": monitor.pack_id,
            "pack_version": monitor.pack_version,
            "coding_assignment_id": monitor.coding_assignment_id,
            "coding_assignment_version": monitor.coding_assignment_version,
            "verification_assignment_id": monitor.verification_assignment_id,
            "verification_assignment_version": monitor.verification_assignment_version,
            "routing_snapshot_identity": monitor.routing_snapshot_identity,
            "source_snapshot_identity": monitor.source_snapshot_identity,
            "process_id": monitor.process_id,
            "process_start_identity": monitor.process_start_identity,
            "codex_session_identity": monitor.codex_session_identity,
            "executable_fingerprint": monitor.executable_fingerprint,
            "isolated_worktree_identity": monitor.isolated_worktree_identity,
            "execution_location_identity": monitor.execution_location_identity,
            "result_locator_identity": monitor.result_locator_identity,
            "protected_log_reference": _opaque_log_reference(monitor),
            "heartbeat_sequence": monitor.heartbeat_sequence,
        }
    return output


def result_envelope_out(
    envelope: CodexResultEnvelope,
    *,
    advanced: bool = False,
) -> dict[str, object]:
    manifest = _decoded_json(envelope.changed_file_manifest_json, [])
    (
        actual_model,
        actual_model_verified,
        coding_verified,
        verification_verified,
        coding_evidence,
        verification_evidence,
    ) = _sealed_envelope_execution_truth(envelope)
    verification_required = envelope.verification_assignment_id is not None
    result_available = envelope.integrity_state == "VERIFIED"
    execution_successful = bool(
        envelope.terminal_status == "completed"
        and coding_verified
        and (verification_verified or not verification_required)
    )
    timed_out = envelope.terminal_status == "timed_out"
    canonical_terminal_state = {
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        "blocked": "blocked",
    }.get(envelope.terminal_status, envelope.terminal_status)
    if envelope.completion_classification == "interrupted":
        canonical_terminal_state = "interrupted"
    tests = _decoded_json(envelope.tests_summary_json, [])
    output: dict[str, object] = {
        "id": envelope.envelope_id,
        "run_id": envelope.run_id,
        "task_id": envelope.task_id,
        "terminal_status": envelope.terminal_status,
        "canonical_terminal_state": canonical_terminal_state,
        "completion_classification": envelope.completion_classification,
        "outcome_label": "Run timed out" if timed_out else canonical_terminal_state.replace("_", " ").title(),
        "result_available": result_available,
        "execution_successful": execution_successful,
        "requested_model": envelope.requested_model_identifier,
        "requested_model_accepted": coding_verified,
        "actual_model": actual_model or None,
        "actual_model_verified": actual_model_verified,
        "effective_model": actual_model or None,
        "effective_model_available": actual_model_verified,
        "effective_model_display": (
            actual_model
            if actual_model_verified
            else "Not exposed by the current Codex CLI protocol."
        ),
        "coding_result": coding_evidence,
        "verification_result": {
            "required": verification_required,
            "verdict": envelope.verification_verdict,
            "evidence": verification_evidence,
        },
        "tests": tests,
        "validation_summary": {
            "evidence_count": len(tests) if isinstance(tests, list) else 0,
            "available": bool(tests),
        },
        "changed_files": manifest,
        "changed_file_count": len(manifest) if isinstance(manifest, list) else 0,
        "warnings": _decoded_json(envelope.warnings_json, []),
        "limitations": _decoded_json(envelope.limitations_json, []),
        "result_integrity": envelope.integrity_state,
        "integrity_state": envelope.integrity_state,
        "integrity_is_not_execution_success": True,
        "accepted_source_result": False,
        "source_result_eligible_for_owner_review": (
            envelope.integrity_state == "VERIFIED"
        ),
        "handoff_reconciliation": "PASS" if execution_successful else "BLOCKED",
        "final_response": envelope.final_response,
        "structured_handoff_status": envelope.structured_handoff_status,
        "duration_ms": envelope.execution_duration_ms,
        "started_at": _iso(envelope.execution_started_at),
        "finished_at": _iso(envelope.execution_finished_at),
        "ingested_at": _iso(envelope.ingested_at),
        "owner_action": "Review Handoff",
    }
    if advanced:
        output["advanced"] = {
            "result_digest": envelope.result_digest,
            "diff_identity": envelope.diff_identity,
            "task_version": envelope.task_version,
            "pack_id": envelope.pack_id,
            "pack_version": envelope.pack_version,
            "coding_assignment_id": envelope.coding_assignment_id,
            "coding_assignment_version": envelope.coding_assignment_version,
            "verification_assignment_id": envelope.verification_assignment_id,
            "verification_assignment_version": envelope.verification_assignment_version,
            "routing_snapshot_identity": envelope.routing_snapshot_identity,
            "source_snapshot_identity": envelope.source_snapshot_identity,
            "approved_instruction_digest": envelope.approved_instruction_digest,
            "authorized_workspace_identity": envelope.authorized_workspace_identity,
            "workspace_baseline_identity": envelope.workspace_baseline_identity,
            "result_source_identity": envelope.result_source_identity,
            "process_evidence_identity": envelope.process_evidence_identity,
            "process_evidence": _decoded_json(envelope.process_evidence_json, {}),
            "workspace_evidence": _decoded_json(
                envelope.workspace_evidence_json,
                {},
            ),
            "boundary_statements": _decoded_json(
                envelope.boundary_statements_json,
                {},
            ),
            "integrity_findings": _decoded_json(
                envelope.integrity_findings_json,
                [],
            ),
        }
    return output


def handoff_review_out(review: HandoffReview) -> dict[str, object]:
    return {
        "id": review.review_id,
        "run_id": review.run_id,
        "run_outcome": review.run_outcome,
        "coding_result": review.coding_result,
        "verification_verdict": review.verification_verdict,
        "changed_files": _decoded_json(review.changed_files_json, []),
        "tests": _decoded_json(review.tests_json, []),
        "warnings": _decoded_json(review.warnings_json, []),
        "limitations": _decoded_json(review.limitations_json, []),
        "boundary_confirmation": _decoded_json(
            review.boundary_confirmation_json,
            {},
        ),
        "current_phase_gate": review.current_phase_gate,
        "recommended_reconciliation": review.recommended_reconciliation,
        "unresolved_blockers": _decoded_json(
            review.unresolved_blockers_json,
            [],
        ),
        "analysis_only": True,
        "review_digest": review.review_digest,
        "created_at": _iso(review.created_at),
    }


def instruction_draft_out(draft: HandoffInstructionDraft) -> dict[str, object]:
    return {
        "id": draft.draft_id,
        "run_id": draft.run_id,
        "label": "Draft — Owner approval required",
        "instruction_id": draft.instruction_id,
        "revision": f"R{draft.revision}",
        "scope": draft.scope,
        "supersession": draft.supersession,
        "completion_gate": _decoded_json(draft.completion_gate_json, []),
        "required_handoff": _decoded_json(draft.required_handoff_json, []),
        "instruction_text": draft.instruction_text,
        "draft_digest": draft.draft_digest,
        "approval_state": draft.approval_state,
        "approved_at": _iso(draft.approved_at),
        "execution_authorized": False,
        "created_at": _iso(draft.created_at),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")
