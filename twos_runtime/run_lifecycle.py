from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import codex_exec_bridge
from .models import (
    CodexActivityAggregate,
    CodexActivityEvent,
    CodexExecutionAttempt,
    CodexLifecycleNotification,
    CodexLifecycleSnapshot,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
    Task,
    utc_now,
)


LIFECYCLE_POLICY = "twos.codex_execution_lifecycle.vol18.006"
MAX_ACTIVITY_EVENTS_PER_ATTEMPT = 256
MAX_ACTIVITY_AGGREGATES_PER_ATTEMPT = 64
MAX_JSONL_LINE_BYTES = 256 * 1024
MAX_ACTIVITY_JSONL_BYTES = 64 * 1024 * 1024

ACTIVE_ATTEMPT_STATES = frozenset({"QUEUED", "STARTING", "RUNNING", "SETTLING"})
TERMINAL_ATTEMPT_STATES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
        "VERIFICATION_ELIGIBLE",
    }
)
TERMINAL_LIFECYCLE_STATES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "BLOCKED",
        "CANCELLED",
        "TIMED_OUT",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
        "RESULT_INTEGRITY_BLOCKED",
        "RESULT_AVAILABLE",
    }
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_DELTA_TOKEN = re.compile(r"(?:delta|chunk|progress)", re.IGNORECASE)
_RECONCILIATION_LOCKS_GUARD = threading.Lock()


class _ReconciliationLockEntry:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.users = 0


_RECONCILIATION_LOCKS: dict[
    tuple[str, str, int], _ReconciliationLockEntry
] = {}


class LifecycleReconciliationError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _canonical_json(value: object) -> str:
    def default(item: object) -> object:
        if isinstance(item, datetime):
            return _iso(item)
        if isinstance(item, (Path, PurePosixPath)):
            return str(item)
        raise TypeError(f"Unsupported canonical lifecycle value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _manager_phase_integrity_blocker(
    run: CodexRun,
    phase: str,
) -> str:
    """Read the server-produced phase contract verdict, never client truth.

    The transport can be internally consistent while the selected message
    still fails the exact Coding handoff schema.  That higher-layer verdict is
    persisted inside the Run result by the execution manager and must converge
    into the same authoritative lifecycle instead of leaving the attempt in
    SETTLING after the Run itself is terminal.
    """

    if not run.structured_result:
        return ""
    try:
        result = json.loads(run.structured_result)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(result, dict):
        return ""
    if phase == "VERIFICATION":
        verification_process = result.get("verification_process")
        if not (
            isinstance(verification_process, dict)
            and verification_process.get("status") == "integrity_blocked"
        ):
            return ""
        code = str(verification_process.get("failure_classification") or "")
        return code if _SAFE_IDENTIFIER.fullmatch(code) else ""
    if phase != "CODING":
        return ""
    bridge = result.get("exec_bridge") if isinstance(result, dict) else None
    if not isinstance(bridge, dict) or bridge.get("integrity_state") != "blocked":
        return ""
    code = str(bridge.get("integrity_blocker") or "")
    return code if _SAFE_IDENTIFIER.fullmatch(code) else ""


def _manager_phase_handoff_unavailable(run: CodexRun, phase: str) -> bool:
    """Recognize a settled Coding process whose result content is incomplete.

    This is deliberately separate from transport integrity: an exact,
    same-turn JSONL message can be retained successfully while failing the
    TWOS structured handoff contract.  Such evidence is reviewable and must
    not launch Verification, but it is not corrupted process evidence.
    """

    if phase != "CODING" or run.status != "failed" or not run.structured_result:
        return False
    try:
        result = json.loads(run.structured_result)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(result, dict):
        return False
    bridge = result.get("exec_bridge")
    coding_process = result.get("coding_process")
    handoff = result.get("structured_handoff")
    return bool(
        isinstance(bridge, dict)
        and bridge.get("integrity_state") == "verified"
        and isinstance(coding_process, dict)
        and coding_process.get("status") == "completed"
        and (not isinstance(handoff, dict) or not handoff)
    )


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _bounded_identifier(value: object, *, maximum: int = 160) -> str:
    candidate = str(value or "").strip()[:maximum]
    return candidate if _SAFE_IDENTIFIER.fullmatch(candidate) else ""


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return ""
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return ""
    normalized = candidate.as_posix()
    return normalized[:1024]


def _owner_id_for_run(run: CodexRun) -> int | None:
    if run.pack is None or run.pack.approved_by_user_id is None:
        return None
    return int(run.pack.approved_by_user_id)


def _require_owner(run: CodexRun, owner_id: int) -> None:
    if _owner_id_for_run(run) != int(owner_id):
        raise LifecycleReconciliationError("RUN_UNAVAILABLE", "Run not found.")


def _assignment_version(run: CodexRun, *, verification: bool) -> int:
    assignment = run.verification_assignment if verification else run.execution_assignment
    return int(
        assignment.assignment_version
        if assignment is not None
        else run.assignment_version
    )


def _phase_directory(monitor: CodexRunMonitor, run: CodexRun, phase: str) -> Path:
    return (
        Path(monitor.protected_result_locator)
        / f"run-{int(run.id)}-{phase.lower()}"
    )


def _bridge_handle(
    monitor: CodexRunMonitor,
    run: CodexRun,
    phase: str,
) -> codex_exec_bridge.ExecutionHandle | None:
    if monitor.result_source != "codex_exec_jsonl_spool":
        return None
    if not monitor.protected_result_locator:
        return None
    directory = _phase_directory(monitor, run, phase)
    ticket = directory / "ticket.json"
    seal = directory / "ticket.seal.json"
    if not ticket.exists() or not seal.exists():
        return None
    try:
        return codex_exec_bridge.handle_from_ticket_path(ticket)
    except codex_exec_bridge.CodexExecBridgeError as exc:
        raise LifecycleReconciliationError(exc.code, exc.safe_message) from exc


def _validate_ticket_binding(
    ticket: Mapping[str, object],
    run: CodexRun,
    owner_id: int,
    phase: str,
) -> None:
    identity = ticket.get("identity")
    if not isinstance(identity, Mapping) or run.pack is None:
        raise LifecycleReconciliationError(
            "LIFECYCLE_TICKET_BINDING_INVALID",
            "The durable execution ticket binding is invalid.",
        )
    requested_model = (
        run.verification_model_identifier
        if phase == "VERIFICATION"
        else run.requested_model_identifier
    )
    expected = {
        "owner_id": owner_id,
        "run_id": int(run.id),
        "task_id": int(run.task_id),
        "task_version": int(run.task_version),
        "pack_id": int(run.pack_id),
        "pack_version": int(run.pack.version),
        "coding_assignment_id": int(run.execution_assignment_id or 0),
        "coding_assignment_version": _assignment_version(run, verification=False),
        "verification_assignment_id": int(run.verification_assignment_id or 0),
        "verification_assignment_version": _assignment_version(run, verification=True),
        "routing_snapshot_identity": run.routing_snapshot_hash,
        "source_snapshot_identity": run.source_snapshot_digest,
        "requested_model_identifier": requested_model,
    }
    if (
        ticket.get("phase") != phase.lower()
        or ticket.get("phase_key") != f"run-{int(run.id)}-{phase.lower()}"
        or any(identity.get(key) != value for key, value in expected.items())
    ):
        raise LifecycleReconciliationError(
            "LIFECYCLE_TICKET_BINDING_MISMATCH",
            "The durable execution ticket does not match this Run.",
        )


def _safe_histogram(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, int] = {}
    for raw_key, raw_count in list(value.items())[:64]:
        key = _bounded_identifier(raw_key, maximum=120)
        if key and type(raw_count) is int and 0 <= raw_count <= 100_000_000:
            output[key] = raw_count
    return dict(sorted(output.items()))


def _bridge_evidence(
    monitor: CodexRunMonitor,
    run: CodexRun,
    owner_id: int,
    phase: str,
) -> tuple[dict[str, object], codex_exec_bridge.ExecutionHandle] | None:
    handle = _bridge_handle(monitor, run, phase)
    if handle is None:
        return None
    try:
        ticket = codex_exec_bridge.load_ticket(handle)
        _validate_ticket_binding(ticket, run, owner_id, phase)
        receipt = codex_exec_bridge.load_terminal_receipt(handle)
        state = None if receipt is not None else codex_exec_bridge.load_execution_state(handle)
        launch = codex_exec_bridge.load_launch_info(handle)
    except codex_exec_bridge.CodexExecBridgeError as exc:
        raise LifecycleReconciliationError(exc.code, exc.safe_message) from exc

    if (
        phase == "VERIFICATION"
        and run.cancellation_requested_at is not None
        and receipt is None
        and state is None
        and launch is None
        and not run.verification_process_spawned
    ):
        # A valid sealed ticket is only preparation evidence. When the Owner
        # has durably cancelled before launch, do not manufacture a process
        # attempt or let that non-process ticket regress the captured Coding
        # result during later reconciliation.
        return None

    source: Mapping[str, object] = receipt or state or {}
    ticket_identity = ticket.get("identity")
    ticket_identity = (
        ticket_identity if isinstance(ticket_identity, Mapping) else {}
    )
    stream_offsets = source.get("stream_offsets")
    stream_offsets = stream_offsets if isinstance(stream_offsets, Mapping) else {}
    stdout_jsonl = source.get("stdout_jsonl")
    stdout_jsonl = stdout_jsonl if isinstance(stdout_jsonl, Mapping) else {}
    settlement = source.get("stream_settlement")
    settlement = settlement if isinstance(settlement, Mapping) else {}
    final_message = source.get("final_message")
    final_message = final_message if isinstance(final_message, Mapping) else {}
    outcome_facts = source.get("outcome_facts")
    outcome_facts = outcome_facts if isinstance(outcome_facts, Mapping) else {}
    jsonl_recovery = final_message.get("jsonl_recovery")
    jsonl_recovery = (
        jsonl_recovery if isinstance(jsonl_recovery, Mapping) else {}
    )

    process_id = source.get("child_process_id")
    process_identity = source.get("child_process_start_identity")
    if (
        type(process_id) is not int
        or process_id <= 0
        or not isinstance(process_identity, str)
        or not process_identity
    ):
        process_id = None
        process_identity = ""
    child_alive = bool(
        receipt is None
        and type(process_id) is int
        and process_id > 0
        and isinstance(process_identity, str)
        and bool(process_identity)
        and codex_exec_bridge.process_identity_matches(process_id, process_identity)
    )
    sidecar_process_id = source.get("sidecar_process_id")
    sidecar_process_identity = str(
        source.get("sidecar_process_start_identity") or ""
    )
    if (
        (
            type(sidecar_process_id) is not int
            or sidecar_process_id <= 0
            or not sidecar_process_identity
        )
        and launch is not None
    ):
        sidecar_process_id = launch.process_id
        sidecar_process_identity = launch.process_start_identity
    if (
        type(sidecar_process_id) is not int
        or sidecar_process_id <= 0
        or not sidecar_process_identity
    ):
        sidecar_process_id = None
        sidecar_process_identity = ""
    sidecar_alive = bool(
        receipt is None
        and type(sidecar_process_id) is int
        and sidecar_process_id > 0
        and sidecar_process_identity
        and codex_exec_bridge.process_identity_matches(
            sidecar_process_id, sidecar_process_identity
        )
    )
    launch_alive = bool(
        receipt is None
        and launch is not None
        and codex_exec_bridge.process_identity_matches(
            launch.process_id, launch.process_start_identity
        )
    )
    process_live = child_alive or sidecar_alive or launch_alive
    child_bound = bool(
        type(process_id) is int and process_id > 0 and bool(process_identity)
    )
    bridge_stage = (
        "RUNNING"
        if child_alive
        else "SETTLING"
        if sidecar_alive and child_bound
        else "STARTING"
        if launch_alive or sidecar_alive
        else "UNAVAILABLE"
    )
    if receipt is None and not process_live:
        # Publication of state and the immutable terminal receipt are separate
        # atomic operations. Re-read the stronger receipt before declaring the
        # exact attempt lost during that narrow handoff.
        try:
            late_receipt = codex_exec_bridge.load_terminal_receipt(handle)
        except codex_exec_bridge.CodexExecBridgeError as exc:
            raise LifecycleReconciliationError(exc.code, exc.safe_message) from exc
        if late_receipt is not None:
            return _bridge_evidence(monitor, run, owner_id, phase)
    settlement_publication_pending = False
    preparation_publication_pending = False
    if receipt is None and not process_live:
        publication_times: list[float] = []
        for publication_path in (
            handle.ticket_path,
            handle.phase_directory / "ticket.seal.json",
            handle.phase_directory / "stdin.bin",
            handle.phase_directory / "state.json",
            handle.phase_directory / "launch.json",
            handle.phase_directory / "stdout.bin",
            handle.phase_directory / "stderr.bin",
        ):
            try:
                publication_times.append(os.lstat(publication_path).st_mtime)
            except OSError:
                continue
        publication_age = (
            max(0.0, utc_now().timestamp() - max(publication_times))
            if publication_times
            else float("inf")
        )
        if launch is None:
            preparation_publication_pending = publication_age <= 5.0
        else:
            settlement_publication_pending = publication_age <= (
                codex_exec_bridge.STREAM_SETTLEMENT_SECONDS
                + codex_exec_bridge.FINAL_MESSAGE_SETTLEMENT_SECONDS
                + 2.0
            )
    terminal_type = _bounded_identifier(
        stdout_jsonl.get("last_terminal_event_type"), maximum=120
    )
    terminal_turn = _bounded_identifier(
        stdout_jsonl.get("last_terminal_turn_identity"), maximum=160
    )
    terminal_sequence = stdout_jsonl.get("last_terminal_event_sequence")
    terminal_sequence = terminal_sequence if type(terminal_sequence) is int else 0
    terminal_identity = (
        _digest(
            {
                "ticket_digest": handle.ticket_digest,
                "type": terminal_type,
                "turn": terminal_turn,
                "sequence": terminal_sequence,
                "start": stdout_jsonl.get("last_terminal_event_start_offset"),
                "end": stdout_jsonl.get("last_terminal_event_end_offset"),
            }
        )
        if terminal_type
        else ""
    )
    receipt_digest = _digest(receipt) if receipt is not None else ""
    sidecar_present = final_message.get("present") is True
    sidecar_matches = final_message.get("matches_last_agent_message") is True
    if receipt is None:
        sidecar_state = "PENDING"
    elif sidecar_present and sidecar_matches:
        sidecar_state = "VALID"
    elif sidecar_present:
        sidecar_state = "MISMATCH"
    else:
        sidecar_state = "MISSING"
    evidence: dict[str, object] = {
        "ticket_digest": handle.ticket_digest,
        "receipt_digest": receipt_digest,
        "receipt_present": receipt is not None,
        "process_id": process_id,
        "process_start_identity": process_identity if isinstance(process_identity, str) else "",
        "sidecar_process_id": sidecar_process_id,
        "sidecar_process_start_identity": sidecar_process_identity,
        "child_alive": child_alive,
        "sidecar_alive": sidecar_alive,
        "launch_alive": launch_alive,
        "bridge_stage": bridge_stage,
        "settlement_publication_pending": settlement_publication_pending,
        "preparation_publication_pending": preparation_publication_pending,
        "process_live": process_live,
        "process_exit_known": receipt is not None,
        "process_exit_code": source.get("process_exit_code"),
        "process_exit_signal": source.get("process_exit_signal"),
        "terminal_state": str(source.get("terminal_state") or ""),
        "terminal_reason": _bounded_identifier(source.get("terminal_reason"), maximum=120),
        "terminal_blocker_code": _bounded_identifier(
            source.get("terminal_blocker_code"), maximum=120
        ),
        "started_at": _parse_time(source.get("started_at"))
        or (run.started_at if phase == "CODING" else None),
        "terminal_at": _parse_time(source.get("terminal_at")),
        "stdout_offset": int(stream_offsets.get("stdout_observed") or 0),
        "stderr_offset": int(stream_offsets.get("stderr_observed") or 0),
        "stdout_spool_bytes": int(stream_offsets.get("stdout_retained") or 0),
        "stderr_spool_bytes": int(stream_offsets.get("stderr_retained") or 0),
        "stdout_eof": settlement.get("stdout_eof") is True,
        "stderr_eof": settlement.get("stderr_eof") is True,
        "trailing_partial_line_present": (
            settlement.get("trailing_partial_line_present") is True
        ),
        "trailing_partial_line_resolved": (
            settlement.get("trailing_partial_line_resolved") is True
        ),
        "terminal_event_observed": bool(
            terminal_type and int(stdout_jsonl.get("terminal_event_count") or 0) > 0
        ),
        "terminal_event_type": terminal_type,
        "terminal_event_identity": terminal_identity,
        "terminal_event_at": _parse_time(
            stdout_jsonl.get("last_terminal_event_observed_at")
        ),
        "turn_identity": terminal_turn,
        "event_count": int(stdout_jsonl.get("event_count") or 0),
        "event_histogram": _safe_histogram(stdout_jsonl.get("type_histogram")),
        "last_event_type": terminal_type,
        "last_event_at": _parse_time(
            stdout_jsonl.get("last_terminal_event_observed_at")
        ),
        "sidecar_state": sidecar_state,
        "sidecar_digest": (
            str(final_message.get("normalized_sha256") or "")
            if _SHA256.fullmatch(str(final_message.get("normalized_sha256") or ""))
            else ""
        ),
        "sidecar_size": (
            int(final_message.get("normalized_size"))
            if type(final_message.get("normalized_size")) is int
            else None
        ),
        "jsonl_recovery_candidate": bool(
            jsonl_recovery.get("eligible_candidate") is True
            and outcome_facts.get("process_exit_known") is True
            and outcome_facts.get("terminal_success") is True
            and outcome_facts.get("streams_settled") is True
        ),
        "final_jsonl_message_observed": bool(
            outcome_facts.get("final_jsonl_message_observed") is True
            and outcome_facts.get("process_exit_known") is True
            and outcome_facts.get("terminal_success") is True
            and outcome_facts.get("streams_settled") is True
        ),
        "same_turn_final_message": (
            isinstance(stdout_jsonl.get("terminal_truth"), Mapping)
            and stdout_jsonl["terminal_truth"].get("same_turn_final_agent_message")
            is True
        ),
        "terminal_success": (
            isinstance(stdout_jsonl.get("terminal_truth"), Mapping)
            and stdout_jsonl["terminal_truth"].get("success") is True
        ),
        "terminal_failure": (
            isinstance(stdout_jsonl.get("terminal_truth"), Mapping)
            and stdout_jsonl["terminal_truth"].get("failure") is True
        ),
        "terminal_contradiction": (
            isinstance(stdout_jsonl.get("terminal_truth"), Mapping)
            and stdout_jsonl["terminal_truth"].get("contradiction") is True
        ),
        "timed_out": outcome_facts.get("timed_out") is True,
        "cancelled": outcome_facts.get("cancelled") is True,
        "phase": phase,
        "protected_spool_locator": str(handle.phase_directory),
        "spool_locator_identity": _digest(str(handle.phase_directory)),
        "executable_fingerprint": str(
            ticket_identity.get("executable_fingerprint") or ""
        ),
        "execution_location_identity": str(
            ticket_identity.get("execution_location_identity") or ""
        ),
        "repository_state_identity": str(
            ticket_identity.get("workspace_snapshot_digest") or ""
        ),
    }
    evidence["observation_digest"] = _digest(
        {
            key: value
            for key, value in evidence.items()
            if key not in {"protected_spool_locator", "last_event_at"}
        }
    )
    return evidence, handle


def _attempt_identity(
    monitor: CodexRunMonitor,
    run: CodexRun,
    phase: str,
    ticket_digest: str,
) -> str:
    return "attempt-" + _digest(
        {
            "policy": LIFECYCLE_POLICY,
            "monitor": monitor.monitor_digest,
            "run": int(run.id),
            "phase": phase,
            "ticket": ticket_digest,
        }
    )[:32]


def _ensure_attempt(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
    evidence: Mapping[str, object],
    phase: str,
) -> CodexExecutionAttempt:
    attempt_id = _attempt_identity(
        monitor, run, phase, str(evidence.get("ticket_digest") or "")
    )
    existing = session.scalar(
        select(CodexExecutionAttempt).where(
            CodexExecutionAttempt.owner_id == owner_id,
            CodexExecutionAttempt.run_id == run.id,
            CodexExecutionAttempt.phase == phase,
            CodexExecutionAttempt.attempt_number == 1,
        )
    )
    exact_binding = {
        "attempt_id": attempt_id,
        "owner_id": owner_id,
        "task_id": int(run.task_id),
        "task_version": int(run.task_version),
        "run_id": int(run.id),
        "pack_id": int(run.pack_id),
        "pack_version": int(run.pack.version) if run.pack is not None else 0,
        "coding_assignment_id": run.execution_assignment_id,
        "coding_assignment_version": _assignment_version(
            run, verification=False
        ),
        "verification_assignment_id": run.verification_assignment_id,
        "verification_assignment_version": _assignment_version(
            run, verification=True
        ),
        "routing_snapshot_identity": run.routing_snapshot_hash,
        "source_snapshot_identity": run.source_snapshot_digest,
        "monitor_id": int(monitor.id),
        "phase": phase,
        "attempt_number": 1,
    }
    if existing is not None:
        if any(
            getattr(existing, field) != value
            for field, value in exact_binding.items()
        ):
            raise LifecycleReconciliationError(
                "EXECUTION_ATTEMPT_IDENTITY_MISMATCH",
                "The persisted execution attempt does not match the sealed ticket.",
            )
        immutable_evidence_binding = {
            "ticket_digest": str(evidence.get("ticket_digest") or "")[:64],
            "spool_locator_identity": str(
                evidence.get("spool_locator_identity") or ""
            )[:64],
            "protected_spool_locator": str(
                evidence.get("protected_spool_locator") or ""
            ),
            "executable_fingerprint": str(
                evidence.get("executable_fingerprint")
                or monitor.executable_fingerprint
                or ""
            )[:64],
            "execution_location_identity": str(
                evidence.get("execution_location_identity")
                or monitor.execution_location_identity
                or ""
            )[:64],
        }
        if any(
            getattr(existing, field) != value
            for field, value in immutable_evidence_binding.items()
        ):
            raise LifecycleReconciliationError(
                "EXECUTION_ATTEMPT_EVIDENCE_BINDING_MISMATCH",
                "The persisted execution attempt evidence binding changed.",
            )
        return existing
    attempt = CodexExecutionAttempt(
        **exact_binding,
        attempt_state="STARTING",
        process_id=(
            int(evidence["process_id"])
            if type(evidence.get("process_id")) is int
            and int(evidence["process_id"]) > 0
            and bool(evidence.get("process_start_identity"))
            else None
        ),
        process_start_identity=str(evidence.get("process_start_identity") or "")[:64],
        sidecar_process_id=(
            int(evidence["sidecar_process_id"])
            if type(evidence.get("sidecar_process_id")) is int
            and int(evidence["sidecar_process_id"]) > 0
            and bool(evidence.get("sidecar_process_start_identity"))
            else None
        ),
        sidecar_process_start_identity=str(
            evidence.get("sidecar_process_start_identity") or ""
        )[:64],
        ticket_digest=str(evidence.get("ticket_digest") or "")[:64],
        executable_fingerprint=str(
            evidence.get("executable_fingerprint")
            or monitor.executable_fingerprint
            or ""
        )[:64],
        execution_location_identity=str(
            evidence.get("execution_location_identity")
            or monitor.execution_location_identity
            or ""
        )[:64],
        spool_locator_identity=str(evidence.get("spool_locator_identity") or "")[:64],
        protected_spool_locator=str(evidence.get("protected_spool_locator") or ""),
        repository_state_identity=str(
            evidence.get("repository_state_identity") or ""
        )[:64],
        safe_summary=(
            "Starting independent Verification."
            if phase == "VERIFICATION"
            else "The sealed Codex execution attempt is starting."
        ),
        started_at=evidence.get("started_at")
        if isinstance(evidence.get("started_at"), datetime)
        else run.started_at,
        last_observed_at=utc_now(),
    )
    session.add(attempt)
    session.flush()
    _record_event(
        session,
        attempt,
        category="PROCESS",
        event_type="process.launch",
        status="STARTED",
        summary=(
            "Starting independent Verification"
            if phase == "VERIFICATION"
            else "Launching Codex"
        ),
        event_at=attempt.started_at or attempt.created_at,
        source="sealed_exec_ticket",
        source_sequence=0,
    )
    return attempt


def _is_phase_final_agent_message(item: Mapping[str, object], phase: str) -> bool:
    text = item.get("text")
    if not isinstance(text, str):
        return False
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(value, dict):
        return False
    normalized_phase = phase.upper()
    if normalized_phase == "CODING":
        return bool(
            set(value) == {"schema", "status", "summary"}
            and value.get("schema") == "twos.coding_handoff.v1"
            and value.get("status") == "completed"
            and isinstance(value.get("summary"), str)
            and value["summary"].strip()
        )
    if normalized_phase == "VERIFICATION":
        expected_keys = {
            "schema",
            "verdict",
            "changed_files_checked",
            "unexpected_files",
            "exact_content",
            "tests",
            "git_boundary",
            "remote_boundary",
        }
        return bool(
            set(value) == expected_keys
            and value.get("schema") == "twos.verification.v1"
            and value.get("verdict") in {"pass", "fail"}
            and isinstance(value.get("changed_files_checked"), list)
            and all(isinstance(path, str) for path in value["changed_files_checked"])
            and isinstance(value.get("unexpected_files"), list)
            and all(isinstance(path, str) for path in value["unexpected_files"])
            and value.get("exact_content") in {"pass", "fail"}
            and value.get("tests") in {"pass", "fail", "not_applicable"}
            and value.get("git_boundary") in {"pass", "fail"}
            and value.get("remote_boundary") in {"pass", "fail"}
        )
    return False


def _event_descriptor(
    event: Mapping[str, object], *, phase: str = ""
) -> tuple[str, str, str, str]:
    event_type = _bounded_identifier(event.get("type"), maximum=120) or "unknown"
    item = event.get("item")
    item = item if isinstance(item, Mapping) else {}
    item_type = _bounded_identifier(item.get("type"), maximum=80).lower()
    lowered = event_type.lower()
    if event_type == "thread.started":
        return "PROCESS", "STARTED", "Codex process started", item_type
    if event_type == "turn.started":
        return "TURN", "STARTED", "Codex turn started", item_type
    if event_type == "turn.completed":
        return "TURN", "COMPLETED", "Codex turn completed", item_type
    if event_type == "turn.failed":
        return "TURN", "FAILED", "Codex turn failed", item_type
    if event_type == "error":
        return "WARNING", "FAILED", "Codex reported a safe execution error", item_type
    if "retry" in lowered:
        return "RETRY", "IN_PROGRESS", "Provider connection retrying", item_type
    if "reason" in item_type or "reason" in lowered:
        status = "COMPLETED" if event_type == "item.completed" else "IN_PROGRESS"
        return "REASONING_STATE", status, "Codex is reasoning", item_type
    item_category = _bounded_identifier(item.get("category"), maximum=80).lower()
    if (
        "validation" in item_type
        or "test" in item_type
        or item_category in {"validation", "test", "tests"}
    ):
        status = "COMPLETED" if event_type == "item.completed" else "IN_PROGRESS"
        return "VALIDATION", status, "Running validation", item_type
    if any(token in item_type for token in ("command", "shell", "exec")):
        status = "COMPLETED" if event_type == "item.completed" else "IN_PROGRESS"
        return "COMMAND", status, "Executing a command", item_type
    if any(token in item_type for token in ("file", "patch", "change")):
        status = "COMPLETED" if event_type == "item.completed" else "IN_PROGRESS"
        return "FILE", status, "Codex is updating repository files", item_type
    if item_type == "agent_message":
        if _is_phase_final_agent_message(item, phase):
            return "RESULT", "COMPLETED", "Codex final result message", item_type
        return "PROGRESS", "COMPLETED", "Codex progress message", item_type
    if event_type.startswith("item."):
        status = "COMPLETED" if event_type == "item.completed" else "IN_PROGRESS"
        return "TOOL", status, "Codex tool activity observed", item_type
    return "PROVIDER", "IN_PROGRESS", "Waiting for Provider response", item_type


def _event_time(
    event: Mapping[str, object],
    observed_at: datetime,
) -> datetime:
    for key in ("timestamp", "created_at", "occurred_at"):
        parsed = _parse_time(event.get(key))
        if parsed is not None:
            return parsed
    # Codex 0.144.4 JSONL does not promise a timestamp on every event. The
    # truthful fallback is when this server observed the durable spool, never
    # a fabricated start-plus-sequence clock.
    return observed_at


def _record_event(
    session: Session,
    attempt: CodexExecutionAttempt,
    *,
    category: str,
    event_type: str,
    status: str,
    summary: str,
    event_at: datetime,
    source: str,
    source_sequence: int,
    evidence_reference: str = "",
    repository_path: str = "",
) -> CodexActivityEvent | None:
    deduplication_identity = _digest(
        {
            "attempt": attempt.attempt_id,
            "sequence": source_sequence,
            "type": event_type,
            "category": category,
            "status": status,
            "evidence": evidence_reference,
            "repository_path": _safe_relative_path(repository_path),
        }
    )
    existing = session.scalar(
        select(CodexActivityEvent).where(
            CodexActivityEvent.deduplication_identity == deduplication_identity
        )
    )
    if existing is not None:
        return existing
    count = int(
        session.scalar(
            select(func.count(CodexActivityEvent.id)).where(
                CodexActivityEvent.execution_attempt_id == attempt.id
            )
        )
        or 0
    )
    critical = category in {"BLOCKER", "RESULT"} or event_type in {
        "turn.completed",
        "turn.failed",
    }
    if count >= MAX_ACTIVITY_EVENTS_PER_ATTEMPT and not critical:
        return None
    event_sequence = max(0, source_sequence)
    while session.scalar(
        select(CodexActivityEvent.id).where(
            CodexActivityEvent.execution_attempt_id == attempt.id,
            CodexActivityEvent.event_sequence == event_sequence,
        )
    ) is not None:
        event_sequence += 1_000_000
    row = CodexActivityEvent(
        owner_id=attempt.owner_id,
        task_id=attempt.task_id,
        run_id=attempt.run_id,
        execution_attempt_id=attempt.id,
        phase=attempt.phase,
        event_category=category,
        event_source=source[:80],
        event_sequence=event_sequence,
        safe_summary=summary[:300],
        event_at=event_at,
        repository_path=_safe_relative_path(repository_path),
        status=status,
        evidence_reference=(
            evidence_reference if _SHA256.fullmatch(evidence_reference) else ""
        ),
        deduplication_identity=deduplication_identity,
    )
    session.add(row)
    session.flush()
    return row


def _record_aggregate(
    session: Session,
    attempt: CodexExecutionAttempt,
    *,
    aggregation_identity: str,
    category: str,
    event_type: str,
    count: int,
    first_at: datetime,
    last_at: datetime,
    summary: str,
) -> None:
    existing = session.scalar(
        select(CodexActivityAggregate).where(
            CodexActivityAggregate.execution_attempt_id == attempt.id,
            CodexActivityAggregate.aggregation_identity == aggregation_identity,
        )
    )
    duration_ms = max(0, int((last_at - first_at).total_seconds() * 1000))
    if existing is not None:
        if count > 0:
            existing.event_count += count
            existing.last_event_at = max(existing.last_event_at, last_at)
            existing.duration_ms = max(
                existing.duration_ms,
                max(
                    0,
                    int(
                        (existing.last_event_at - existing.first_event_at).total_seconds()
                        * 1000
                    ),
                ),
            )
            existing.safe_last_sample = summary[:240]
            existing.sample_digest = _digest(
                {
                    "type": event_type,
                    "count": existing.event_count,
                    "first": _iso(existing.first_event_at),
                    "last": _iso(existing.last_event_at),
                }
            )
        return
    aggregate_count = int(
        session.scalar(
            select(func.count(CodexActivityAggregate.id)).where(
                CodexActivityAggregate.execution_attempt_id == attempt.id
            )
        )
        or 0
    )
    if aggregate_count >= MAX_ACTIVITY_AGGREGATES_PER_ATTEMPT:
        return
    row = CodexActivityAggregate(
        owner_id=attempt.owner_id,
        task_id=attempt.task_id,
        run_id=attempt.run_id,
        execution_attempt_id=attempt.id,
        phase=attempt.phase,
        event_category=category,
        event_type=event_type[:120],
        aggregation_identity=aggregation_identity,
        event_count=count,
        first_event_at=first_at,
        last_event_at=last_at,
        duration_ms=duration_ms,
        safe_first_sample=summary[:240],
        safe_last_sample=summary[:240],
        sample_digest=_digest(
            {
                "type": event_type,
                "count": count,
                "first": _iso(first_at),
                "last": _iso(last_at),
            }
        ),
        final_observable_outcome="IN_PROGRESS",
    )
    session.add(row)
    session.flush()


def _read_activity_events(
    session: Session,
    attempt: CodexExecutionAttempt,
    handle: codex_exec_bridge.ExecutionHandle,
) -> None:
    stdout_path = handle.phase_directory / "stdout.bin"
    try:
        details = os.lstat(stdout_path)
    except OSError:
        return
    if not os.path.isfile(stdout_path) or details.st_size > MAX_ACTIVITY_JSONL_BYTES:
        return
    if attempt.stdout_offset < 0 or attempt.stdout_offset > details.st_size:
        raise LifecycleReconciliationError(
            "ACTIVITY_STREAM_OFFSET_INVALID",
            "The persisted JSONL activity offset is invalid.",
        )
    observed_at = datetime.fromtimestamp(details.st_mtime, tz=UTC).replace(tzinfo=None)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(stdout_path, flags)
    except OSError:
        return
    delta_groups: dict[str, list[tuple[int, datetime, str, str]]] = defaultdict(list)
    aggregate_outcomes: dict[str, tuple[str, datetime, str]] = {}
    consumed_offset = attempt.stdout_offset
    latest_type = attempt.last_event_type
    latest_at = attempt.last_event_at
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            stream.seek(attempt.stdout_offset)
            while True:
                line_start = stream.tell()
                raw_line = stream.readline(MAX_JSONL_LINE_BYTES + 1)
                if not raw_line:
                    break
                line_end = stream.tell()
                if not raw_line.endswith(b"\n"):
                    # Keep the read offset before an unresolved partial line;
                    # the next reconciliation resumes from the same byte.
                    break
                consumed_offset = line_end
                if len(raw_line) > MAX_JSONL_LINE_BYTES:
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, Mapping):
                    continue
                event_type = _bounded_identifier(event.get("type"), maximum=120)
                if not event_type:
                    continue
                category, status, summary, item_type = _event_descriptor(
                    event, phase=attempt.phase
                )
                event_at = _event_time(event, observed_at)
                item = event.get("item")
                item = item if isinstance(item, Mapping) else {}
                item_id = _bounded_identifier(item.get("id"), maximum=160)
                turn_id = _bounded_identifier(event.get("turn_id"), maximum=160)
                thread_id = _bounded_identifier(event.get("thread_id"), maximum=160)
                if thread_id and not attempt.thread_identity:
                    attempt.thread_identity = thread_id
                if turn_id:
                    attempt.turn_identity = turn_id
                latest_type = event_type
                latest_at = event_at
                changes = item.get("changes")
                safe_changes = (
                    [change for change in changes[:64] if isinstance(change, Mapping)]
                    if isinstance(changes, list)
                    else []
                )
                first_change = safe_changes[0] if safe_changes else {}
                repository_path = _safe_relative_path(
                    item.get("path")
                    or item.get("file_path")
                    or first_change.get("path")
                    or event.get("path")
                    or ""
                )
                if category == "FILE" and repository_path:
                    operation = _bounded_identifier(
                        item.get("operation")
                        or item.get("change_type")
                        or first_change.get("kind"),
                        maximum=20,
                    ).upper()
                    summary = (
                        f"Creating {repository_path}"
                        if operation in {"CREATE", "ADD", "ADDED"}
                        else f"Deleting {repository_path}"
                        if operation in {"DELETE", "DELETED", "REMOVE", "REMOVED"}
                        else f"Modifying {repository_path}"
                    )
                if _DELTA_TOKEN.search(event_type) or event_type == "item.updated":
                    key = _digest(
                        {
                            "attempt": attempt.attempt_id,
                            "turn": turn_id,
                            "item": item_id,
                            "category": category,
                        }
                    )
                    delta_groups[key].append(
                        (line_end, event_at, category, summary)
                    )
                    continue
                aggregate_key = _digest(
                    {
                        "attempt": attempt.attempt_id,
                        "turn": turn_id,
                        "item": item_id,
                        "category": category,
                    }
                )
                if event_type == "item.completed" and item_id:
                    aggregate_outcomes[aggregate_key] = (
                        status,
                        event_at,
                        summary,
                    )
                if category == "FILE" and safe_changes:
                    for change_index, change in enumerate(safe_changes):
                        change_path = _safe_relative_path(change.get("path") or "")
                        if not change_path:
                            continue
                        operation = _bounded_identifier(
                            change.get("kind") or change.get("operation"), maximum=20
                        ).upper()
                        change_summary = (
                            f"Creating {change_path}"
                            if operation in {"CREATE", "ADD", "ADDED"}
                            else f"Deleting {change_path}"
                            if operation in {"DELETE", "DELETED", "REMOVE", "REMOVED"}
                            else f"Modifying {change_path}"
                        )
                        _record_event(
                            session,
                            attempt,
                            category=category,
                            event_type=event_type,
                            status=status,
                            summary=change_summary,
                            event_at=event_at,
                            source="codex_exec_jsonl",
                            source_sequence=line_end + change_index,
                            evidence_reference=_digest(
                                {
                                    "ticket": attempt.ticket_digest,
                                    "line_start": line_start,
                                    "line_end": line_end,
                                    "type": event_type,
                                    "item_type": item_type,
                                    "change_index": change_index,
                                    "path": change_path,
                                }
                            ),
                            repository_path=change_path,
                        )
                    continue
                _record_event(
                    session,
                    attempt,
                    category=category,
                    event_type=event_type,
                    status=status,
                    summary=summary,
                    event_at=event_at,
                    source="codex_exec_jsonl",
                    source_sequence=line_end,
                    evidence_reference=_digest(
                        {
                            "ticket": attempt.ticket_digest,
                            "line_start": line_start,
                            "line_end": line_end,
                            "type": event_type,
                            "item_type": item_type,
                        }
                    ),
                    repository_path=repository_path,
                )
    finally:
        # ``os.fdopen`` owns and closes the descriptor. This guard covers the
        # rare exception before ownership is transferred.
        try:
            os.close(descriptor)
        except OSError:
            pass
    attempt.stdout_offset = consumed_offset
    attempt.stdout_spool_bytes = details.st_size
    if latest_type:
        attempt.last_event_type = latest_type
    if latest_at is not None:
        attempt.last_event_at = latest_at
    for key, values in delta_groups.items():
        first = values[0]
        last = values[-1]
        _record_aggregate(
            session,
            attempt,
            aggregation_identity=key,
            category=first[2],
            event_type="delta.aggregate",
            count=len(values),
            first_at=first[1],
            last_at=last[1],
            summary=first[3],
        )
    for key, (outcome, outcome_at, summary) in aggregate_outcomes.items():
        aggregate = session.scalar(
            select(CodexActivityAggregate).where(
                CodexActivityAggregate.execution_attempt_id == attempt.id,
                CodexActivityAggregate.aggregation_identity == key,
            )
        )
        if aggregate is None:
            continue
        aggregate.final_observable_outcome = outcome
        aggregate.last_event_at = max(aggregate.last_event_at, outcome_at)
        aggregate.duration_ms = max(
            0,
            int(
                (aggregate.last_event_at - aggregate.first_event_at).total_seconds()
                * 1000
            ),
        )
        aggregate.safe_last_sample = summary[:240]
        aggregate.sample_digest = _digest(
            {
                "type": aggregate.event_type,
                "count": aggregate.event_count,
                "first": _iso(aggregate.first_event_at),
                "last": _iso(aggregate.last_event_at),
                "outcome": outcome,
            }
        )


def _set_if_changed(target: object, field: str, value: object) -> bool:
    if getattr(target, field) == value:
        return False
    setattr(target, field, value)
    return True


def _apply_attempt_evidence(
    session: Session,
    attempt: CodexExecutionAttempt,
    evidence: Mapping[str, object],
    handle: codex_exec_bridge.ExecutionHandle,
) -> bool:
    observation_digest = str(evidence.get("observation_digest") or "")
    observed_process_id = (
        int(evidence["process_id"])
        if type(evidence.get("process_id")) is int
        else None
    )
    observed_process_identity = str(
        evidence.get("process_start_identity") or ""
    )[:64]
    if attempt.process_id is not None and (
        observed_process_id != attempt.process_id
        or observed_process_identity != attempt.process_start_identity
    ):
        raise LifecycleReconciliationError(
            "EXECUTION_PROCESS_IDENTITY_CHANGED",
            "The exact Codex child process identity changed.",
        )
    observed_sidecar_id = (
        int(evidence["sidecar_process_id"])
        if type(evidence.get("sidecar_process_id")) is int
        else None
    )
    observed_sidecar_identity = str(
        evidence.get("sidecar_process_start_identity") or ""
    )[:64]
    if attempt.sidecar_process_id is not None and (
        observed_sidecar_id != attempt.sidecar_process_id
        or observed_sidecar_identity
        != attempt.sidecar_process_start_identity
    ):
        raise LifecycleReconciliationError(
            "EXECUTION_SIDECAR_IDENTITY_CHANGED",
            "The exact Codex sidecar process identity changed.",
        )
    unchanged = bool(
        observation_digest
        and attempt.observation_digest == observation_digest
        and attempt.attempt_state in TERMINAL_ATTEMPT_STATES
    )
    if unchanged:
        return False
    _read_activity_events(session, attempt, handle)
    changed = False
    scalar_fields = {
        "process_id": observed_process_id,
        "process_start_identity": observed_process_identity,
        "sidecar_process_id": observed_sidecar_id,
        "sidecar_process_start_identity": observed_sidecar_identity,
        "process_live": evidence.get("process_live") is True,
        "process_exit_known": evidence.get("process_exit_known") is True,
        "process_exit_code": evidence.get("process_exit_code")
        if type(evidence.get("process_exit_code")) is int
        else None,
        "process_exit_signal": evidence.get("process_exit_signal")
        if type(evidence.get("process_exit_signal")) is int
        else None,
        "ticket_digest": str(evidence.get("ticket_digest") or "")[:64],
        "receipt_digest": str(evidence.get("receipt_digest") or "")[:64],
        "observation_digest": observation_digest[:64],
        "executable_fingerprint": str(
            evidence.get("executable_fingerprint")
            or attempt.executable_fingerprint
            or ""
        )[:64],
        "execution_location_identity": str(
            evidence.get("execution_location_identity")
            or attempt.execution_location_identity
            or ""
        )[:64],
        "spool_locator_identity": str(evidence.get("spool_locator_identity") or "")[:64],
        "protected_spool_locator": str(evidence.get("protected_spool_locator") or ""),
        "turn_identity": str(evidence.get("turn_identity") or "")[:160],
        "stderr_offset": int(evidence.get("stderr_offset") or 0),
        "stderr_spool_bytes": int(evidence.get("stderr_spool_bytes") or 0),
        "stdout_eof": evidence.get("stdout_eof") is True,
        "stderr_eof": evidence.get("stderr_eof") is True,
        "trailing_partial_line_present": (
            evidence.get("trailing_partial_line_present") is True
        ),
        "trailing_partial_line_resolved": (
            evidence.get("trailing_partial_line_resolved") is True
        ),
        "terminal_event_observed": evidence.get("terminal_event_observed") is True,
        "terminal_event_type": str(evidence.get("terminal_event_type") or "")[:120],
        "terminal_event_identity": str(evidence.get("terminal_event_identity") or "")[:64],
        "event_count": int(evidence.get("event_count") or 0),
        "event_histogram_json": _canonical_json(evidence.get("event_histogram") or {}),
        "sidecar_state": str(evidence.get("sidecar_state") or "NOT_OBSERVED")[:40],
        "sidecar_digest": str(evidence.get("sidecar_digest") or "")[:64],
        "sidecar_size": evidence.get("sidecar_size")
        if type(evidence.get("sidecar_size")) is int
        else None,
        "jsonl_recovery_candidate": (
            evidence.get("jsonl_recovery_candidate") is True
        ),
        "result_resolution_source": (
            "JSONL_FINAL_MESSAGE_RECOVERY"
            if evidence.get("jsonl_recovery_candidate") is True
            else "FINAL_MESSAGE_SIDECAR"
            if evidence.get("sidecar_state") == "VALID"
            else ""
        ),
        "repository_state_identity": str(
            evidence.get("repository_state_identity")
            or attempt.repository_state_identity
            or ""
        )[:64],
    }
    for field, value in scalar_fields.items():
        changed = _set_if_changed(attempt, field, value) or changed
    for field in ("started_at", "terminal_event_at", "terminal_at"):
        value = evidence.get(field)
        if isinstance(value, datetime):
            changed = _set_if_changed(attempt, field, value) or changed
    evidence_last_event_at = evidence.get("last_event_at")
    if (
        isinstance(evidence_last_event_at, datetime)
        and (
            attempt.last_event_at is None
            or evidence_last_event_at >= attempt.last_event_at
        )
    ):
        changed = _set_if_changed(
            attempt, "last_event_at", evidence_last_event_at
        ) or changed
        changed = _set_if_changed(
            attempt,
            "last_event_type",
            str(evidence.get("last_event_type") or "")[:120],
        ) or changed

    terminal_state = str(evidence.get("terminal_state") or "")
    terminal = evidence.get("receipt_present") is True
    now = utc_now()
    target_state = attempt.attempt_state
    safe_summary = attempt.safe_summary
    blocker = attempt.blocker_code
    verification_eligible = False
    if terminal:
        if attempt.settlement_started_at is None:
            attempt.settlement_started_at = (
                evidence.get("terminal_event_at")
                if isinstance(evidence.get("terminal_event_at"), datetime)
                else now
            )
            changed = True
        if (
            terminal_state == "RESULT_INTEGRITY_BLOCKED"
            and evidence.get("jsonl_recovery_candidate") is True
        ):
            # A sealed recovery candidate is not success yet. The execution
            # manager must validate its exact structured identity/schema after
            # this transaction; until then the one lifecycle is SETTLING.
            target_state = "SETTLING"
            blocker = "JSONL_FINAL_MESSAGE_RECOVERY_PENDING"
            safe_summary = "Verifying final result evidence"
        elif terminal_state == "RESULT_INTEGRITY_BLOCKED":
            target_state = "RESULT_INTEGRITY_BLOCKED"
            blocker = str(
                evidence.get("terminal_blocker_code")
                or evidence.get("terminal_reason")
                or "RESULT_INTEGRITY_BLOCKED"
            )[:120]
            safe_summary = "Final result evidence mismatch"
        elif terminal_state == "TIMED_OUT" or evidence.get("timed_out") is True:
            target_state = "TIMED_OUT"
            blocker = "CODEX_EXECUTION_TIMED_OUT"
            safe_summary = "The Codex execution timed out."
        elif terminal_state == "CANCELLED" or evidence.get("cancelled") is True:
            target_state = "CANCELLED"
            blocker = "CODEX_EXECUTION_CANCELLED"
            safe_summary = "The Codex execution was cancelled."
        elif terminal_state == "FAILED":
            target_state = "FAILED"
            blocker = str(evidence.get("terminal_reason") or "CODEX_EXECUTION_FAILED")[:120]
            safe_summary = "The Codex execution failed."
        elif terminal_state == "COMPLETED":
            settlement_complete = bool(
                evidence.get("process_exit_known") is True
                and evidence.get("stdout_eof") is True
                and evidence.get("stderr_eof") is True
                and not (
                    evidence.get("trailing_partial_line_present") is True
                    and evidence.get("trailing_partial_line_resolved") is not True
                )
                and evidence.get("terminal_event_observed") is True
                and evidence.get("terminal_success") is True
                and evidence.get("terminal_contradiction") is not True
                and (
                    evidence.get("sidecar_state") == "VALID"
                    or evidence.get("jsonl_recovery_candidate") is True
                    or evidence.get("final_jsonl_message_observed") is True
                )
            )
            if settlement_complete:
                # Transport settlement is necessary but not sufficient for
                # phase success. The higher-layer execution manager must still
                # validate the structured Coding/Verification result identity.
                target_state = "SETTLING"
                verification_eligible = False
                blocker = (
                    "CODING_RESULT_VALIDATION_PENDING"
                    if attempt.phase == "CODING"
                    else "VERIFICATION_RESULT_VALIDATION_PENDING"
                )
                safe_summary = "Verifying final result evidence"
            else:
                target_state = "RESULT_INTEGRITY_BLOCKED"
                blocker = "TERMINAL_SETTLEMENT_INCOMPLETE"
                safe_summary = "The terminal Codex evidence could not be settled safely."
        else:
            target_state = "RESULT_INTEGRITY_BLOCKED"
            blocker = "TERMINAL_STATE_UNRESOLVED"
            safe_summary = "The terminal Codex state could not be resolved safely."
    elif evidence.get("process_live") is True:
        if attempt.attempt_state not in TERMINAL_ATTEMPT_STATES:
            bridge_stage = str(evidence.get("bridge_stage") or "RUNNING")
            target_state = (
                bridge_stage
                if bridge_stage in {"STARTING", "RUNNING", "SETTLING"}
                else "RUNNING"
            )
            blocker = ""
            safe_summary = (
                "The exact detached launch is publishing its first durable state."
                if target_state == "STARTING"
                else "The Codex process exited and the sidecar is settling durable evidence."
                if target_state == "SETTLING"
                else
                "Independent Verification is running."
                if attempt.phase == "VERIFICATION"
                else "Coding is running in the isolated worktree."
            )
    elif evidence.get("settlement_publication_pending") is True:
        if attempt.attempt_state not in TERMINAL_ATTEMPT_STATES:
            target_state = "SETTLING"
            blocker = "TERMINAL_RECEIPT_PUBLICATION_PENDING"
            safe_summary = (
                "The exact Codex process exited and durable terminal evidence is settling."
            )
    elif evidence.get("preparation_publication_pending") is True:
        if attempt.attempt_state not in TERMINAL_ATTEMPT_STATES:
            target_state = "STARTING"
            blocker = ""
            safe_summary = "The sealed Codex launch is publishing its process identity."
    elif attempt.attempt_state not in TERMINAL_ATTEMPT_STATES:
        target_state = "PROCESS_LOST"
        blocker = "SEALED_PROCESS_IDENTITY_LOST"
        safe_summary = "The exact Codex process is no longer live and no terminal receipt exists."

    if attempt.attempt_state in TERMINAL_ATTEMPT_STATES:
        target_state = attempt.attempt_state
    changed = _set_if_changed(attempt, "attempt_state", target_state) or changed
    changed = _set_if_changed(attempt, "blocker_code", blocker) or changed
    changed = _set_if_changed(attempt, "safe_summary", safe_summary) or changed
    changed = (
        _set_if_changed(attempt, "verification_eligible", verification_eligible)
        or changed
    )
    if changed:
        attempt.last_observed_at = now
    if target_state in TERMINAL_ATTEMPT_STATES and attempt.terminal_at is None:
        attempt.terminal_at = (
            evidence.get("terminal_at")
            if isinstance(evidence.get("terminal_at"), datetime)
            else now
        )
        changed = True
    if terminal and target_state != "SETTLING":
        category = "BLOCKER" if target_state in {
            "RESULT_INTEGRITY_BLOCKED",
            "FAILED",
            "TIMED_OUT",
            "CANCELLED",
        } else "RESULT"
        status = "BLOCKED" if category == "BLOCKER" else "COMPLETED"
        _record_event(
            session,
            attempt,
            category=category,
            event_type=f"settlement.{target_state.lower()}",
            status=status,
            summary=safe_summary,
            event_at=attempt.terminal_at or now,
            source="sealed_terminal_receipt",
            source_sequence=max(1, attempt.event_count + 1),
            evidence_reference=attempt.receipt_digest,
        )
    return changed


def _monitor_terminal_state(attempt_state: str) -> tuple[str, str]:
    if attempt_state == "TIMED_OUT":
        return "TIMED_OUT", "RESULT_UNAVAILABLE"
    if attempt_state == "CANCELLED":
        return "CANCELLED", "RESULT_UNAVAILABLE"
    if attempt_state == "PROCESS_LOST":
        return "PROCESS_LOST", "PROCESS_LOST"
    if attempt_state == "FAILED":
        return "FAILED", "RESULT_UNAVAILABLE"
    return "RESULT_INTEGRITY_BLOCKED", "INTEGRITY_BLOCKED"


def _settle_terminal_failure(
    session: Session,
    run: CodexRun,
    monitor: CodexRunMonitor,
    attempt: CodexExecutionAttempt,
) -> None:
    timeout_proved = attempt.attempt_state == "TIMED_OUT"
    try:
        terminal_receipt_stat = os.lstat(
            Path(attempt.protected_spool_locator) / "terminal.json"
        )
        terminal_receipt_available = stat.S_ISREG(terminal_receipt_stat.st_mode)
    except OSError:
        terminal_receipt_available = False
    try:
        persisted_result = json.loads(run.structured_result or "{}")
    except (TypeError, json.JSONDecodeError):
        persisted_result = {}
    verification_projection_pending = bool(
        attempt.phase == "VERIFICATION"
        and (
            not isinstance(persisted_result, dict)
            or not isinstance(persisted_result.get("verification_process"), dict)
        )
    )
    evidence_persistence_pending = bool(
        terminal_receipt_available
        and attempt.receipt_digest
        and (
            verification_projection_pending
            or (attempt.phase == "CODING" and not run.stdout and not run.stderr)
        )
        # Empty output is valid for a process that times out before emitting
        # anything.  Once the manager has committed an authoritative terminal
        # Run projection, a later monitor pass must not regress that terminal
        # state to ``settling`` merely because both output fields are empty.
        and str(run.status or "").upper() not in TERMINAL_LIFECYCLE_STATES
    )
    run_state = (
        "settling"
        if evidence_persistence_pending
        else "timed_out"
        if timeout_proved
        else "cancelled"
        if attempt.attempt_state == "CANCELLED"
        else "failed"
        if attempt.attempt_state == "FAILED"
        else "blocked"
    )
    monitor_state, recovery_state = _monitor_terminal_state(attempt.attempt_state)
    terminal_at = attempt.terminal_at or utc_now()
    verification_phase = attempt.phase == "VERIFICATION"
    monitor_before = (
        monitor.monitor_state,
        monitor.recovery_state,
        monitor.process_exit_code,
        monitor.failure_code,
        monitor.safe_summary,
        monitor.terminal_at,
    )
    run.status = run_state
    run.finished_at = terminal_at
    if verification_phase:
        run.verification_status = run_state
        run.verification_exit_code = attempt.process_exit_code
        run.verification_timed_out = timeout_proved
        run.verification_cancelled = attempt.attempt_state == "CANCELLED"
        run.verification_summary = attempt.safe_summary
        if attempt.started_at is not None:
            run.verification_duration_ms = max(
                0,
                int((terminal_at - attempt.started_at).total_seconds() * 1000),
            )
    else:
        run.exit_code = attempt.process_exit_code
        run.timed_out = timeout_proved
        run.cancelled = attempt.attempt_state == "CANCELLED"
    if not (
        attempt.attempt_state == "CANCELLED"
        and run.status == "cancelled"
        and run.owner_summary
    ):
        run.owner_summary = attempt.safe_summary
    if run.started_at is not None:
        run.duration_ms = max(
            0, int((terminal_at - run.started_at).total_seconds() * 1000)
        )
    task = session.get(Task, run.task_id)
    if task is not None:
        task.status = "cancelled" if run_state == "cancelled" else "needs_review"
        task.acceptance_state = "needs_review"
    monitor.monitor_state = monitor_state
    monitor.recovery_state = recovery_state
    monitor.process_exit_code = attempt.process_exit_code
    monitor.failure_code = attempt.blocker_code[:80]
    monitor.safe_summary = attempt.safe_summary
    monitor.terminal_at = terminal_at
    monitor.last_observed_at = terminal_at
    monitor.last_heartbeat_at = terminal_at
    monitor_after = (
        monitor.monitor_state,
        monitor.recovery_state,
        monitor.process_exit_code,
        monitor.failure_code,
        monitor.safe_summary,
        monitor.terminal_at,
    )
    if monitor_after != monitor_before:
        monitor.heartbeat_sequence += 1


def _ensure_snapshot(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
) -> CodexLifecycleSnapshot:
    snapshot = session.scalar(
        select(CodexLifecycleSnapshot).where(
            CodexLifecycleSnapshot.owner_id == owner_id,
            CodexLifecycleSnapshot.run_id == run.id,
        )
    )
    if snapshot is not None:
        return snapshot
    snapshot = CodexLifecycleSnapshot(
        owner_id=owner_id,
        task_id=run.task_id,
        run_id=run.id,
        monitor_id=monitor.id,
        lifecycle_state=str(run.status or "queued").upper(),
        phase="VERIFICATION" if run.status == "verifying" else "CODING",
        current_activity="Preparing execution environment",
        next_owner_action="TWOS is preparing the explicit Owner-started Run.",
        process_live=False,
        monitor_attached=True,
        terminal_evidence_observed=False,
        started_at=run.started_at,
        coding_started_at=run.started_at,
        last_activity_at=monitor.last_observed_at or run.started_at,
        terminal_at=run.finished_at,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _next_action(state: str) -> str:
    if state in {"QUEUED", "STARTING", "RUNNING", "VERIFYING"}:
        return "TWOS is monitoring this Run; no Owner action is required."
    if state in {"SETTLING", "VERIFICATION_ELIGIBLE"}:
        return "Wait for TWOS to settle the durable Run evidence."
    if state == "RESULT_AVAILABLE":
        return "Review Handoff"
    if state == "TIMED_OUT":
        return "Review the timeout evidence before starting a new Run."
    if state == "PROCESS_LOST":
        return "Review the process-loss evidence; do not rerun automatically."
    return "Review blocker evidence"


def _activity_label(attempt: CodexExecutionAttempt, state: str) -> str:
    if state == "RESULT_AVAILABLE":
        return "Result available"
    if state in {"RESULT_INTEGRITY_BLOCKED", "BLOCKED", "FAILED"}:
        return "Run blocked"
    if state == "TIMED_OUT":
        return "Run timed out"
    if state == "PROCESS_LOST":
        return "Process lost"
    if state in {"SETTLING", "VERIFICATION_ELIGIBLE"}:
        return (
            "Settling final Run Result"
            if attempt.phase == "VERIFICATION"
            else "Settling Coding result"
        )
    if attempt.phase == "VERIFICATION":
        return "Verification is running"
    return "Waiting for Provider response" if attempt.event_count <= 2 else "Coding is running"


def _sync_snapshot(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
    attempt: CodexExecutionAttempt,
) -> CodexLifecycleSnapshot:
    snapshot = _ensure_snapshot(session, owner_id, run, monitor)
    envelope = session.scalar(
        select(CodexResultEnvelope).where(
            CodexResultEnvelope.owner_id == owner_id,
            CodexResultEnvelope.run_id == run.id,
        )
    )
    if envelope is not None:
        envelope_blocked = envelope.integrity_state != "VERIFIED"
        _record_event(
            session,
            attempt,
            category="BLOCKER" if envelope_blocked else "RESULT",
            event_type=(
                "result.integrity_blocked"
                if envelope_blocked
                else "result.available"
            ),
            status="BLOCKED" if envelope_blocked else "COMPLETED",
            summary=(
                "The persisted Run Result is blocked by integrity validation."
                if envelope_blocked
                else "Result available"
            ),
            event_at=envelope.ingested_at,
            source="result_intake",
            source_sequence=max(1, attempt.event_count + 2),
            evidence_reference=envelope.result_digest,
        )
    latest_event = session.scalar(
        select(CodexActivityEvent)
        .where(CodexActivityEvent.execution_attempt_id == attempt.id)
        .order_by(CodexActivityEvent.event_at.desc(), CodexActivityEvent.id.desc())
        .limit(1)
    )
    latest_aggregate = session.scalar(
        select(CodexActivityAggregate)
        .where(CodexActivityAggregate.execution_attempt_id == attempt.id)
        .order_by(
            CodexActivityAggregate.last_event_at.desc(),
            CodexActivityAggregate.id.desc(),
        )
        .limit(1)
    )
    if attempt.attempt_state in {
        "RESULT_INTEGRITY_BLOCKED",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
    }:
        # A structurally valid failure envelope is useful review evidence, but
        # it cannot erase the execution-attempt integrity outcome that caused
        # the Run to stop before a trustworthy Coding result existed.
        state = attempt.attempt_state
        integrity = "BLOCKED"
        result_digest = envelope.result_digest if envelope is not None else attempt.result_digest
        blocker_code = attempt.blocker_code
    elif envelope is not None and envelope.integrity_state == "VERIFIED":
        state = "RESULT_AVAILABLE"
        integrity = "VERIFIED"
        result_digest = envelope.result_digest
        blocker_code = ""
    elif envelope is not None:
        state = "RESULT_INTEGRITY_BLOCKED"
        integrity = "BLOCKED"
        result_digest = envelope.result_digest
        blocker_code = "RESULT_ENVELOPE_INTEGRITY_BLOCKED"
    elif attempt.attempt_state == "VERIFICATION_ELIGIBLE":
        state = "SETTLING"
        integrity = "PENDING"
        result_digest = ""
        blocker_code = attempt.blocker_code
    elif attempt.attempt_state == "COMPLETED":
        state = "SETTLING"
        integrity = "PENDING"
        result_digest = ""
        blocker_code = attempt.blocker_code
    elif attempt.attempt_state in TERMINAL_ATTEMPT_STATES:
        state = attempt.attempt_state
        integrity = (
            "BLOCKED"
            if attempt.attempt_state
            in {"RESULT_INTEGRITY_BLOCKED", "PROCESS_LOST", "RESULT_UNAVAILABLE"}
            else "TERMINAL"
        )
        result_digest = attempt.result_digest
        blocker_code = attempt.blocker_code
    else:
        state = "VERIFYING" if attempt.phase == "VERIFICATION" else attempt.attempt_state
        integrity = "PENDING"
        result_digest = ""
        blocker_code = attempt.blocker_code
    if (
        snapshot.lifecycle_state in TERMINAL_LIFECYCLE_STATES
        and state not in TERMINAL_LIFECYCLE_STATES
    ):
        # A stale process observation can never regress a committed terminal
        # projection. A newer attempt would have a different exact identity
        # and is never created automatically by this reconciler.
        state = snapshot.lifecycle_state
        integrity = snapshot.result_integrity_state
        result_digest = snapshot.result_digest
        blocker_code = snapshot.blocker_code
    latest_summary = ""
    latest_activity_at: datetime | None = None
    if latest_event is not None:
        latest_summary = latest_event.safe_summary
        latest_activity_at = latest_event.event_at
    if (
        latest_aggregate is not None
        and (
            latest_activity_at is None
            or latest_aggregate.last_event_at > latest_activity_at
        )
    ):
        latest_summary = latest_aggregate.safe_last_sample
        latest_activity_at = latest_aggregate.last_event_at
    values = {
        "monitor_id": monitor.id,
        "current_attempt_id": attempt.id,
        "coding_attempt_identity": (
            attempt.attempt_id
            if attempt.phase == "CODING"
            else snapshot.coding_attempt_identity
        ),
        "verification_attempt_identity": (
            attempt.attempt_id
            if attempt.phase == "VERIFICATION"
            else snapshot.verification_attempt_identity
        ),
        "lifecycle_state": state,
        "phase": attempt.phase
        if state not in {"RESULT_AVAILABLE", "SETTLING"}
        else "RESULT_SETTLEMENT",
        "current_activity": latest_summary or _activity_label(attempt, state),
        "next_owner_action": _next_action(state),
        "process_live": attempt.process_live and state not in TERMINAL_LIFECYCLE_STATES,
        "monitor_attached": True,
        "terminal_evidence_observed": attempt.terminal_event_observed,
        "sidecar_state": attempt.sidecar_state,
        "result_integrity_state": integrity,
        "blocker_code": blocker_code,
        "coding_started": bool(
            snapshot.coding_started or attempt.phase == "CODING"
        ),
        "process_exited": attempt.process_exit_known,
        "verification_started": bool(
            snapshot.verification_started or attempt.phase == "VERIFICATION"
        ),
        "result_digest": result_digest,
        "started_at": snapshot.started_at or attempt.started_at or run.started_at,
        "coding_started_at": snapshot.coding_started_at
        or (attempt.started_at if attempt.phase == "CODING" else run.started_at),
        "verification_started_at": snapshot.verification_started_at
        or (attempt.started_at if attempt.phase == "VERIFICATION" else None),
        "settlement_started_at": snapshot.settlement_started_at
        or attempt.settlement_started_at,
        "last_activity_at": latest_activity_at
        or attempt.last_event_at
        or attempt.last_observed_at
        or snapshot.last_activity_at,
        "terminal_at": (
            envelope.ingested_at
            if envelope is not None
            else attempt.terminal_at
            if state in TERMINAL_LIFECYCLE_STATES
            else None
        ),
    }
    for field, value in values.items():
        _set_if_changed(snapshot, field, value)
    return snapshot


def _ensure_notification(
    session: Session,
    snapshot: CodexLifecycleSnapshot,
    run: CodexRun,
    attempt: CodexExecutionAttempt,
) -> None:
    if snapshot.lifecycle_state not in TERMINAL_LIFECYCLE_STATES:
        return
    deduplication_identity = _digest(
        {
            "policy": LIFECYCLE_POLICY,
            "run": run.id,
            "attempt": attempt.attempt_id,
            "state": snapshot.lifecycle_state,
            "blocker": snapshot.blocker_code,
            "result": snapshot.result_digest,
        }
    )
    if session.scalar(
        select(CodexLifecycleNotification.id).where(
            CodexLifecycleNotification.deduplication_identity
            == deduplication_identity
        )
    ) is not None:
        return
    session.add(
        CodexLifecycleNotification(
            owner_id=snapshot.owner_id,
            task_id=snapshot.task_id,
            run_id=snapshot.run_id,
            lifecycle_snapshot_id=snapshot.id,
            notification_kind="RUN_TERMINAL",
            terminal_state=snapshot.lifecycle_state,
            verification_result=(
                run.verification_status.upper()
                if run.verification_status
                else "UNAVAILABLE"
            ),
            safe_summary=attempt.safe_summary,
            owner_action=snapshot.next_owner_action,
            deduplication_identity=deduplication_identity,
        )
    )


def _database_reconciliation_scope(session: Session) -> str:
    """Return a secret-free identity shared by sessions for one database."""
    bind = session.get_bind()
    engine = getattr(bind, "engine", bind)
    url = getattr(engine, "url", None)
    rendered = (
        url.render_as_string(hide_password=True)
        if url is not None and hasattr(url, "render_as_string")
        else type(engine).__name__
    )
    if (
        url is not None
        and getattr(url, "get_backend_name", lambda: "")() == "sqlite"
        and getattr(url, "database", None) in {None, "", ":memory:"}
    ):
        rendered = f"{rendered}\0engine={id(engine)}"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@contextmanager
def _reconciliation_lock(
    session: Session,
    namespace: str,
    entity_id: int,
) -> Iterator[None]:
    """Serialize one database-local entity and evict the lock after all users."""
    key = (_database_reconciliation_scope(session), namespace, int(entity_id))
    with _RECONCILIATION_LOCKS_GUARD:
        entry = _RECONCILIATION_LOCKS.setdefault(key, _ReconciliationLockEntry())
        entry.users += 1
    try:
        with entry.lock:
            yield
    finally:
        with _RECONCILIATION_LOCKS_GUARD:
            entry.users -= 1
            if entry.users == 0 and _RECONCILIATION_LOCKS.get(key) is entry:
                _RECONCILIATION_LOCKS.pop(key, None)


def _reconciliation_lock_registry_size() -> int:
    """Expose only a count for deterministic shutdown/leak regression checks."""
    with _RECONCILIATION_LOCKS_GUARD:
        return len(_RECONCILIATION_LOCKS)


def reconcile_execution_attempt(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
) -> dict[str, object]:
    """Serialize same-Run reconciliation and apply one database transaction.

    The application is a single local SQLite runtime, but refresh endpoints
    and the watcher can execute concurrently.  Per-Run serialization closes
    the SELECT/INSERT window for attempt and snapshot rows; database uniqueness
    plus optimistic version columns remain the durable cross-transaction
    boundary.
    """
    with _reconciliation_lock(session, "run", int(run.id)):
        return _reconcile_execution_attempt_locked(
            session,
            owner_id,
            run,
            monitor,
        )


def _reconcile_execution_attempt_locked(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
) -> dict[str, object]:
    """Atomically reconcile all sealed attempts for one Run.

    The caller owns the database transaction.  This function never starts,
    signals, cancels or replaces a process.  SQLAlchemy's version columns on
    attempts and snapshots provide compare-and-swap conflict detection at
    flush/commit time.
    """

    _require_owner(run, owner_id)
    if monitor.owner_id != owner_id or monitor.run_id != run.id:
        raise LifecycleReconciliationError(
            "MONITOR_BINDING_MISMATCH", "The Run monitor binding is invalid."
        )
    observed: list[tuple[CodexExecutionAttempt, dict[str, object]]] = []
    coding_attempt: CodexExecutionAttempt | None = None
    for phase in ("CODING", "VERIFICATION"):
        phase_evidence = _bridge_evidence(monitor, run, owner_id, phase)
        if phase_evidence is None:
            continue
        if phase == "VERIFICATION" and (
            coding_attempt is None
            or coding_attempt.attempt_state != "COMPLETED"
            or not coding_attempt.verification_eligible
            or run.status
            not in {
                "verifying",
                "settling",
                "completed",
                "failed",
                "cancelled",
                "timed_out",
                "blocked",
            }
        ):
            raise LifecycleReconciliationError(
                "VERIFICATION_PRECONDITION_INVALID",
                "Verification evidence exists before Coding result integrity was validated.",
            )
        evidence, handle = phase_evidence
        attempt = _ensure_attempt(
            session, owner_id, run, monitor, evidence, phase
        )
        _apply_attempt_evidence(session, attempt, evidence, handle)
        phase_process_spawned = bool(
            run.process_spawned
            if phase == "CODING"
            else run.verification_process_spawned
        )
        if (
            run.status == "cancelled"
            and run.cancellation_requested_at is not None
            and attempt.attempt_state in ACTIVE_ATTEMPT_STATES
            and not phase_process_spawned
            and attempt.process_id is None
            and not attempt.process_live
            and not attempt.process_exit_known
            and not attempt.terminal_event_observed
        ):
            # A sealed launch ticket can exist before any child crosses the
            # process boundary. Once the manager persists an Owner cancellation
            # at that boundary, terminalize the ticket-bound attempt instead of
            # leaving the canonical lifecycle indefinitely STARTING.
            attempt.attempt_state = "CANCELLED"
            attempt.verification_eligible = False
            attempt.blocker_code = "CODEX_EXECUTION_CANCELLED"
            attempt.safe_summary = (
                "The Owner cancelled before the Codex process started."
            )
            attempt.process_live = False
            attempt.terminal_at = attempt.terminal_at or run.finished_at or utc_now()
            _record_event(
                session,
                attempt,
                category="BLOCKER",
                event_type="settlement.prelaunch_cancelled",
                status="BLOCKED",
                summary=attempt.safe_summary,
                event_at=attempt.terminal_at,
                source="execution_manager_validation",
                source_sequence=max(1, attempt.event_count + 2),
                evidence_reference=attempt.ticket_digest,
            )
        manager_integrity_blocker = _manager_phase_integrity_blocker(run, phase)
        if (
            manager_integrity_blocker
            and attempt.attempt_state == "SETTLING"
            and run.status == "blocked"
        ):
            attempt.attempt_state = "RESULT_INTEGRITY_BLOCKED"
            attempt.verification_eligible = False
            attempt.blocker_code = manager_integrity_blocker
            attempt.safe_summary = "Final result evidence mismatch"
            attempt.terminal_at = attempt.terminal_at or utc_now()
            _record_event(
                session,
                attempt,
                category="BLOCKER",
                event_type="settlement.result_schema_blocked",
                status="BLOCKED",
                summary="Final result evidence mismatch",
                event_at=attempt.terminal_at,
                source="execution_manager_validation",
                source_sequence=max(1, attempt.event_count + 2),
                evidence_reference=attempt.receipt_digest,
            )
        if (
            phase == "CODING"
            and attempt.attempt_state == "SETTLING"
            and str(evidence.get("terminal_state") or "") == "COMPLETED"
            and _manager_phase_handoff_unavailable(run, phase)
        ):
            attempt.attempt_state = "COMPLETED"
            attempt.verification_eligible = False
            attempt.blocker_code = "STRUCTURED_CODING_HANDOFF_UNAVAILABLE"
            attempt.safe_summary = (
                "Coding ended without a valid structured handoff; "
                "the captured result requires Owner review."
            )
            _record_event(
                session,
                attempt,
                category="BLOCKER",
                event_type="settlement.structured_handoff_unavailable",
                status="BLOCKED",
                summary=attempt.safe_summary,
                event_at=attempt.terminal_at or utc_now(),
                source="execution_manager_validation",
                source_sequence=max(1, attempt.event_count + 2),
                evidence_reference=attempt.receipt_digest,
            )
        if (
            phase == "CODING"
            and attempt.attempt_state == "SETTLING"
            and str(evidence.get("terminal_state") or "") == "COMPLETED"
            and run.status in {"verifying", "completed"}
        ):
            # The manager's persisted phase transition is the higher-layer
            # proof that structured Coding identity/integrity validation passed.
            attempt.attempt_state = "COMPLETED"
            attempt.verification_eligible = True
            attempt.blocker_code = ""
            attempt.safe_summary = "Final result verified"
            _record_event(
                session,
                attempt,
                category="RESULT",
                event_type="settlement.result_verified",
                status="COMPLETED",
                summary="Final result verified",
                event_at=attempt.terminal_at or utc_now(),
                source="lifecycle_reconciler",
                source_sequence=max(1, attempt.event_count + 2),
                evidence_reference=attempt.receipt_digest,
            )
            coding_attempt = attempt
        elif phase == "CODING":
            coding_attempt = attempt
        if (
            phase == "VERIFICATION"
            and attempt.attempt_state == "SETTLING"
            and str(evidence.get("terminal_state") or "") == "COMPLETED"
            and run.status in {"completed", "failed"}
            and run.structured_result not in {"", "{}"}
        ):
            attempt.attempt_state = "COMPLETED"
            attempt.blocker_code = ""
            attempt.safe_summary = "Independent Verification completed."
        observed.append((attempt, evidence))
    if not observed:
        return {"handled": False, "run_id": run.id}
    attempt, evidence = observed[-1]
    if attempt.attempt_state in {
        "RESULT_INTEGRITY_BLOCKED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
        "PROCESS_LOST",
        "RESULT_UNAVAILABLE",
    }:
        _settle_terminal_failure(session, run, monitor, attempt)
    elif attempt.attempt_state in {
        "VERIFICATION_ELIGIBLE",
        "COMPLETED",
        "SETTLING",
    }:
        if run.status not in {"completed", "failed", "blocked", "cancelled", "timed_out"}:
            monitor_before = (
                monitor.monitor_state,
                monitor.recovery_state,
                monitor.failure_code,
                monitor.safe_summary,
                monitor.process_exit_code,
                monitor.terminal_at,
            )
            # Once the higher-layer manager has validated Coding and committed
            # the separate Verification transition, the monitor must stay in
            # VERIFYING.  Regressing it to RESULT_PENDING creates a race with
            # binding the Verification child and can falsely block that exact
            # process as an invalid state transition.
            monitor.monitor_state = (
                "VERIFYING"
                if attempt.phase == "CODING" and run.status == "verifying"
                else "RESULT_PENDING"
            )
            monitor.recovery_state = "RESULT_RECOVERED"
            monitor.failure_code = ""
            monitor.safe_summary = attempt.safe_summary
            monitor.process_exit_code = attempt.process_exit_code
            monitor.terminal_at = attempt.terminal_at
            monitor.last_observed_at = attempt.last_observed_at
            monitor.last_heartbeat_at = attempt.last_observed_at
            monitor_after = (
                monitor.monitor_state,
                monitor.recovery_state,
                monitor.failure_code,
                monitor.safe_summary,
                monitor.process_exit_code,
                monitor.terminal_at,
            )
            if monitor_after != monitor_before:
                monitor.heartbeat_sequence += 1
    elif attempt.process_live:
        monitor_before = (
            monitor.monitor_state,
            monitor.recovery_state,
            monitor.failure_code,
            monitor.safe_summary,
            monitor.last_observed_at,
        )
        monitor.monitor_state = (
            "VERIFYING" if attempt.phase == "VERIFICATION" else "RUNNING"
        )
        monitor.recovery_state = "MONITORING_RESUMED"
        monitor.failure_code = ""
        monitor.safe_summary = attempt.safe_summary
        monitor.last_observed_at = attempt.last_observed_at
        monitor.last_heartbeat_at = attempt.last_observed_at
        monitor_after = (
            monitor.monitor_state,
            monitor.recovery_state,
            monitor.failure_code,
            monitor.safe_summary,
            monitor.last_observed_at,
        )
        if monitor_after != monitor_before:
            monitor.heartbeat_sequence += 1
    snapshot = _sync_snapshot(session, owner_id, run, monitor, attempt)
    _ensure_notification(session, snapshot, run, attempt)
    session.flush()
    recovery_needed = bool(
        (
            run.status
            not in {"completed", "failed", "blocked", "cancelled", "timed_out"}
            and attempt.process_exit_known
            and attempt.attempt_state
            in {"VERIFICATION_ELIGIBLE", "COMPLETED", "SETTLING"}
        )
        or (
            run.status == "settling"
            and attempt.attempt_state
            in {
                "RESULT_INTEGRITY_BLOCKED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "PROCESS_LOST",
                "RESULT_UNAVAILABLE",
            }
            and bool(attempt.receipt_digest)
            and (
                attempt.phase == "VERIFICATION"
                or (not run.stdout and not run.stderr)
            )
        )
    )
    return {
        "handled": True,
        "run_id": run.id,
        "state": snapshot.lifecycle_state,
        "phase": snapshot.phase,
        "attempt_id": attempt.attempt_id,
        "recovery_needed": recovery_needed,
        "blocker": attempt.blocker_code or None,
        "terminal_evidence_observed": attempt.terminal_event_observed,
        "process_live": attempt.process_live,
        "evidence_digest": evidence.get("observation_digest"),
    }


def settle_reconciliation_error(
    session: Session,
    owner_id: int,
    run: CodexRun,
    monitor: CodexRunMonitor,
    error: LifecycleReconciliationError,
) -> dict[str, object]:
    """Persist a strict lifecycle blocker without masking it as legacy RUNNING."""

    _require_owner(run, owner_id)
    phase = "VERIFICATION" if run.status == "verifying" else "CODING"
    stop_requested = False
    try:
        handle = _bridge_handle(monitor, run, phase)
        if handle is not None:
            ticket = codex_exec_bridge.load_ticket(handle)
            _validate_ticket_binding(ticket, run, owner_id, phase)
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            state = (
                None
                if receipt is not None
                else codex_exec_bridge.load_execution_state(handle)
            )
            launch = codex_exec_bridge.load_launch_info(handle)
            exact_live_identity = False
            if isinstance(state, Mapping):
                for pid_key, identity_key in (
                    ("child_process_id", "child_process_start_identity"),
                    ("sidecar_process_id", "sidecar_process_start_identity"),
                ):
                    pid = state.get(pid_key)
                    identity = state.get(identity_key)
                    if (
                        type(pid) is int
                        and pid > 0
                        and isinstance(identity, str)
                        and identity
                        and codex_exec_bridge.process_identity_matches(pid, identity)
                    ):
                        exact_live_identity = True
                        break
            if (
                not exact_live_identity
                and receipt is None
                and launch is not None
                and codex_exec_bridge.process_identity_matches(
                    launch.process_id,
                    launch.process_start_identity,
                )
            ):
                exact_live_identity = True
            if receipt is None and exact_live_identity:
                # The immutable cancel request is consumed by the exact sealed
                # sidecar.  Never signal a PID directly or use PID without its
                # start identity.
                codex_exec_bridge.request_cancel(handle)
                stop_requested = True
    except (LifecycleReconciliationError, codex_exec_bridge.CodexExecBridgeError):
        # If the ticket itself cannot be bound to this Run, no process is safe
        # to signal. Preserve the original strict blocker without guessing.
        stop_requested = False
    attempt = session.scalar(
        select(CodexExecutionAttempt)
        .where(
            CodexExecutionAttempt.owner_id == owner_id,
            CodexExecutionAttempt.run_id == run.id,
            CodexExecutionAttempt.phase == phase,
        )
        .order_by(CodexExecutionAttempt.attempt_number.desc())
        .limit(1)
    )
    if attempt is None:
        synthetic_evidence: dict[str, object] = {
            "ticket_digest": "",
            "process_id": (
                monitor.verification_process_id
                if phase == "VERIFICATION"
                else monitor.process_id
            ),
            "process_start_identity": (
                monitor.verification_process_start_identity
                if phase == "VERIFICATION"
                else monitor.process_start_identity
            ),
            "spool_locator_identity": monitor.result_locator_identity,
            "protected_spool_locator": monitor.protected_result_locator,
            "executable_fingerprint": monitor.executable_fingerprint,
            "execution_location_identity": monitor.execution_location_identity,
            "repository_state_identity": run.source_snapshot_digest,
            "started_at": run.started_at,
        }
        attempt = _ensure_attempt(
            session,
            owner_id,
            run,
            monitor,
            synthetic_evidence,
            phase,
        )
    if attempt.attempt_state not in TERMINAL_ATTEMPT_STATES:
        now = utc_now()
        attempt.attempt_state = "RESULT_INTEGRITY_BLOCKED"
        attempt.blocker_code = error.code[:120]
        attempt.safe_summary = (
            error.safe_message
            + (
                " Exact sealed process shutdown was requested."
                if stop_requested
                else ""
            )
        )[:300]
        attempt.process_live = False
        attempt.terminal_at = now
        attempt.last_observed_at = now
        _record_event(
            session,
            attempt,
            category="BLOCKER",
            event_type="reconciliation.integrity_blocked",
            status="BLOCKED",
            summary=attempt.safe_summary,
            event_at=now,
            source="lifecycle_reconciler",
            source_sequence=max(1, attempt.event_count + 1),
        )
        if stop_requested:
            _record_event(
                session,
                attempt,
                category="PROCESS",
                event_type="process.stop_requested",
                status="IN_PROGRESS",
                summary="Stopping the exact blocked Codex process",
                event_at=now,
                source="sealed_exec_ticket",
                source_sequence=max(2, attempt.event_count + 2),
            )
    _settle_terminal_failure(session, run, monitor, attempt)
    snapshot = _sync_snapshot(session, owner_id, run, monitor, attempt)
    _ensure_notification(session, snapshot, run, attempt)
    session.flush()
    return {
        "handled": True,
        "run_id": run.id,
        "state": snapshot.lifecycle_state,
        "phase": snapshot.phase,
        "attempt_id": attempt.attempt_id,
        "recovery_needed": False,
        "blocker": attempt.blocker_code,
        "terminal_evidence_observed": attempt.terminal_event_observed,
        "process_live": False,
    }


def _duration_ms(
    start: datetime | None,
    end: datetime | None,
    now: datetime,
) -> int | None:
    if start is None:
        return None
    effective_end = end or now
    return max(0, int((effective_end - start).total_seconds() * 1000))


def _activity_rows(
    session: Session,
    owner_id: int,
    run_id: int,
) -> list[dict[str, object]]:
    events = list(
        session.scalars(
            select(CodexActivityEvent)
            .where(
                CodexActivityEvent.owner_id == owner_id,
                CodexActivityEvent.run_id == run_id,
            )
            .order_by(CodexActivityEvent.event_at.desc(), CodexActivityEvent.id.desc())
            .limit(24)
        ).all()
    )
    aggregates = list(
        session.scalars(
            select(CodexActivityAggregate)
            .where(
                CodexActivityAggregate.owner_id == owner_id,
                CodexActivityAggregate.run_id == run_id,
            )
            .order_by(
                CodexActivityAggregate.last_event_at.desc(),
                CodexActivityAggregate.id.desc(),
            )
            .limit(12)
        ).all()
    )
    output: list[dict[str, object]] = [
        {
            "sequence": 0,
            "source_sequence": event.event_sequence,
            "type": event.event_category,
            "event_type": event.event_source,
            "phase": event.phase,
            "current_activity": event.safe_summary,
            "status": event.status,
            "occurred_at": _iso(event.event_at),
            "duration_ms": event.duration_ms,
            "repository_path": event.repository_path or None,
        }
        for event in events
    ]
    output.extend(
        {
            "sequence": 0,
            "source_sequence": None,
            "type": aggregate.event_category,
            "event_type": aggregate.event_type,
            "phase": aggregate.phase,
            "current_activity": aggregate.safe_last_sample,
            "status": aggregate.final_observable_outcome,
            "occurred_at": _iso(aggregate.last_event_at),
            "duration_ms": aggregate.duration_ms,
            "event_count": aggregate.event_count,
        }
        for aggregate in aggregates
    )
    output.sort(key=lambda row: str(row.get("occurred_at") or ""))
    output = output[-24:]
    for display_sequence, row in enumerate(output, start=1):
        row["sequence"] = display_sequence
    return output


def lifecycle_snapshot_out(
    session: Session,
    owner_id: int,
    run: CodexRun,
    *,
    advanced: bool = False,
) -> dict[str, object]:
    """Return the one privacy-safe lifecycle representation for all UI surfaces."""

    _require_owner(run, owner_id)
    snapshot = session.scalar(
        select(CodexLifecycleSnapshot).where(
            CodexLifecycleSnapshot.owner_id == owner_id,
            CodexLifecycleSnapshot.run_id == run.id,
        )
    )
    monitor = session.scalar(
        select(CodexRunMonitor).where(
            CodexRunMonitor.owner_id == owner_id,
            CodexRunMonitor.run_id == run.id,
        )
    )
    now = utc_now()
    if snapshot is None:
        monitor_state = str(monitor.monitor_state or "").upper() if monitor else ""
        state = (
            monitor_state
            if monitor_state
            in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "PROCESS_LOST",
                "RESULT_AVAILABLE",
                "RESULT_UNAVAILABLE",
                "RESULT_INTEGRITY_BLOCKED",
            }
            else str(run.status or "queued").upper()
        )
        phase = "VERIFICATION" if run.status == "verifying" else "CODING"
        live_process_id = (
            monitor.verification_process_id
            if monitor is not None and phase == "VERIFICATION"
            else monitor.process_id
            if monitor is not None
            else None
        )
        live_process_identity = (
            monitor.verification_process_start_identity
            if monitor is not None and phase == "VERIFICATION"
            else monitor.process_start_identity
            if monitor is not None
            else ""
        )
        process_live = False
        receipt_observed = False
        if state in {"RUNNING", "VERIFYING"}:
            bridge_observation: dict[str, object] | None = None
            if monitor is not None:
                try:
                    phase_evidence = _bridge_evidence(
                        monitor, run, owner_id, phase
                    )
                    bridge_observation = (
                        phase_evidence[0]
                        if phase_evidence is not None
                        else None
                    )
                except LifecycleReconciliationError:
                    bridge_observation = None
            if bridge_observation is not None:
                receipt_observed = (
                    bridge_observation.get("receipt_present") is True
                )
                process_live = bridge_observation.get("process_live") is True
                bridge_stage = str(
                    bridge_observation.get("bridge_stage") or ""
                )
                if receipt_observed:
                    state = "SETTLING"
                elif bridge_stage in {"STARTING", "SETTLING"}:
                    state = bridge_stage
                elif bridge_stage != "RUNNING" or not process_live:
                    state = (
                        "SETTLING"
                        if bridge_observation.get(
                            "settlement_publication_pending"
                        )
                        is True
                        else "STARTING"
                        if bridge_observation.get(
                            "preparation_publication_pending"
                        )
                        is True
                        else "PROCESS_LOST"
                    )
            else:
                process_live = bool(
                    live_process_id
                    and live_process_identity
                    and codex_exec_bridge.process_identity_matches(
                        int(live_process_id), live_process_identity
                    )
                )
                if not process_live:
                    state = "PROCESS_LOST"
        terminal = state in TERMINAL_LIFECYCLE_STATES
        integrity = (
            "blocked"
            if state
            in {"RESULT_INTEGRITY_BLOCKED", "RESULT_UNAVAILABLE", "PROCESS_LOST"}
            else "verified"
            if state == "RESULT_AVAILABLE"
            else "pending"
        )
        return {
            "snapshot_version": 0,
            "state": state.lower(),
            "phase": phase.lower(),
            "current_activity": (
                "Settling terminal Run evidence"
                if state == "SETTLING"
                else "Run blocked"
                if terminal
                else "Preparing execution environment"
            ),
            "next_action": _next_action(state),
            "server_now": _iso(now),
            "started_at": _iso(run.started_at),
            "terminal_at": _iso(run.finished_at),
            "elapsed_ms": _duration_ms(run.started_at, run.finished_at if terminal else None, now),
            "coding_elapsed_ms": _duration_ms(run.started_at, run.finished_at if terminal else None, now),
            "verification_elapsed_ms": None,
            "result_settlement_elapsed_ms": None,
            "last_activity_at": _iso(
                monitor.last_observed_at if monitor is not None else run.started_at
            ),
            "inactivity_ms": _duration_ms(
                monitor.last_observed_at if monitor is not None else run.started_at,
                now,
                now,
            ),
            "process_live": process_live,
            "monitor_attached": monitor is not None,
            "terminal_evidence_observed": receipt_observed,
            "sidecar_state": "not_observed",
            "result_integrity": integrity,
            "coding_started": bool(run.process_spawned or run.started_at),
            "process_exited": terminal,
            "verification_started": bool(run.verification_process_spawned),
            "events": [],
            "blocker_code": monitor.failure_code if monitor is not None else None,
        }
    attempt = (
        session.get(CodexExecutionAttempt, snapshot.current_attempt_id)
        if snapshot.current_attempt_id is not None
        else None
    )
    displayed_state = snapshot.lifecycle_state
    displayed_process_live = snapshot.process_live
    displayed_process_exited = snapshot.process_exited
    displayed_terminal_evidence = snapshot.terminal_evidence_observed
    displayed_activity = snapshot.current_activity
    if (
        displayed_state in {"RUNNING", "VERIFYING"}
        and attempt is not None
    ):
        # A persisted heartbeat is not authority to keep saying Running.
        # Observe the exact bridge child, sidecar and launch identities so the
        # child-exit/receipt-publication window is shown as Settling rather
        # than either stale Running or a false Process lost state.
        bridge_observation: dict[str, object] | None = None
        if monitor is not None:
            try:
                phase_evidence = _bridge_evidence(
                    monitor, run, owner_id, attempt.phase
                )
                bridge_observation = (
                    phase_evidence[0]
                    if phase_evidence is not None
                    else None
                )
            except LifecycleReconciliationError:
                bridge_observation = None
        if bridge_observation is not None:
            receipt_observed = (
                bridge_observation.get("receipt_present") is True
            )
            bridge_stage = str(
                bridge_observation.get("bridge_stage") or ""
            )
            displayed_process_live = (
                bridge_observation.get("process_live") is True
            )
            if receipt_observed:
                displayed_state = "SETTLING"
            elif bridge_stage in {"STARTING", "SETTLING"}:
                displayed_state = bridge_stage
            elif bridge_stage != "RUNNING" or not displayed_process_live:
                displayed_state = (
                    "SETTLING"
                    if bridge_observation.get(
                        "settlement_publication_pending"
                    )
                    is True
                    else "STARTING"
                    if bridge_observation.get(
                        "preparation_publication_pending"
                    )
                    is True
                    else "PROCESS_LOST"
                )
            if displayed_state != snapshot.lifecycle_state:
                displayed_process_exited = displayed_state in {
                    "SETTLING",
                    "PROCESS_LOST",
                }
                displayed_terminal_evidence = (
                    displayed_terminal_evidence or receipt_observed
                )
                displayed_activity = (
                    "Settling terminal Run evidence"
                    if displayed_state == "SETTLING"
                    else "Publishing the verified process identity"
                    if displayed_state == "STARTING"
                    else "Process identity is no longer live"
                )
        elif (
            not attempt.process_id
            or not attempt.process_start_identity
            or not codex_exec_bridge.process_identity_matches(
                int(attempt.process_id), attempt.process_start_identity
            )
        ):
            displayed_state = "PROCESS_LOST"
            displayed_process_live = False
            displayed_process_exited = True
            displayed_activity = "Process identity is no longer live"
    terminal = displayed_state in TERMINAL_LIFECYCLE_STATES
    terminal_at = snapshot.terminal_at if terminal else None
    last_activity = snapshot.last_activity_at or snapshot.started_at
    output: dict[str, object] = {
        "snapshot_version": snapshot.snapshot_version,
        "state": displayed_state.lower(),
        "phase": snapshot.phase.lower(),
        "current_activity": displayed_activity,
        "next_action": (
            _next_action(displayed_state)
            if displayed_state != snapshot.lifecycle_state
            else snapshot.next_owner_action or _next_action(snapshot.lifecycle_state)
        ),
        "server_now": _iso(now),
        "started_at": _iso(snapshot.started_at),
        "terminal_at": _iso(snapshot.terminal_at),
        "elapsed_ms": _duration_ms(snapshot.started_at, terminal_at, now),
        "coding_elapsed_ms": _duration_ms(
            snapshot.coding_started_at,
            (
                snapshot.verification_started_at
                or snapshot.settlement_started_at
                or terminal_at
            )
            if terminal or snapshot.verification_started_at or snapshot.settlement_started_at
            else None,
            now,
        ),
        "verification_elapsed_ms": _duration_ms(
            snapshot.verification_started_at,
            snapshot.settlement_started_at or terminal_at if terminal else None,
            now,
        ),
        "result_settlement_elapsed_ms": _duration_ms(
            snapshot.settlement_started_at,
            terminal_at,
            now,
        ),
        "last_activity_at": _iso(last_activity),
        "inactivity_ms": _duration_ms(last_activity, now, now),
        "process_live": displayed_process_live,
        "monitor_attached": snapshot.monitor_attached,
        "terminal_evidence_observed": displayed_terminal_evidence,
        "sidecar_state": snapshot.sidecar_state.lower(),
        "result_integrity": snapshot.result_integrity_state.lower(),
        "blocker_code": snapshot.blocker_code or None,
        "coding_started": snapshot.coding_started,
        "process_exited": displayed_process_exited,
        "verification_started": snapshot.verification_started,
        "events": _activity_rows(session, owner_id, run.id),
    }
    if advanced:
        histogram: object = {}
        if attempt is not None:
            try:
                histogram = json.loads(attempt.event_histogram_json or "{}")
            except json.JSONDecodeError:
                histogram = {}
        output["advanced"] = {
            "execution_attempt_id": attempt.attempt_id if attempt is not None else None,
            "monitor_id": monitor.monitor_id if monitor is not None else None,
            "execution_id": (
                attempt.ticket_digest[:24] if attempt is not None else None
            ),
            "process_id": attempt.process_id if attempt is not None else None,
            "sidecar_process_id": (
                attempt.sidecar_process_id if attempt is not None else None
            ),
            "executable_fingerprint": (
                attempt.executable_fingerprint if attempt is not None else None
            ),
            "protected_log_reference": (
                (
                    f"codex-run-log:{attempt.spool_locator_identity[:24]}"
                    if attempt is not None and attempt.spool_locator_identity
                    else None
                )
            ),
            "stream_offsets": {
                "stdout": attempt.stdout_offset if attempt is not None else 0,
                "stderr": attempt.stderr_offset if attempt is not None else 0,
            },
            "event_histogram": histogram,
            "sidecar_state": attempt.sidecar_state if attempt is not None else "NOT_OBSERVED",
            "exit_code": attempt.process_exit_code if attempt is not None else None,
            "reconciliation_version": (
                attempt.reconciliation_version if attempt is not None else snapshot.snapshot_version
            ),
            "snapshot_version": snapshot.snapshot_version,
            "process_start_identity": (
                attempt.process_start_identity if attempt is not None else None
            ),
            "terminal_event_identity": (
                attempt.terminal_event_identity if attempt is not None else None
            ),
            "receipt_digest": attempt.receipt_digest if attempt is not None else None,
        }
    return output


def nonterminal_attempt_run_ids(session: Session) -> Iterable[int]:
    """Startup-recovery selector; selection alone never launches a process."""

    return tuple(
        session.scalars(
            select(CodexExecutionAttempt.run_id)
            .where(CodexExecutionAttempt.attempt_state.in_(ACTIVE_ATTEMPT_STATES))
            .distinct()
            .order_by(CodexExecutionAttempt.run_id)
        ).all()
    )
