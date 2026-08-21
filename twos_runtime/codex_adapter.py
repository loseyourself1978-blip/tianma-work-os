from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .ai_orchestration import is_verified_real_invocation, record_model_invocation_evidence
from .config import Settings
from . import codex_exec_bridge
from .codex_connectivity import (
    codex_child_environment,
    executable_identity,
    inspect_authentication,
)
from .models import (
    AICapability,
    AIModel,
    AIModelAssignment,
    AIModelInvocationEvidence,
    AuditEvent,
    CodexExecutionAttempt,
    CodexRun,
    CodexRunMonitor,
    Provider,
    Task,
    utc_now,
)
from .result_intake import (
    ResultIntakeError,
    canonical_sha256,
    clear_stale_monitor_terminal_state,
    ensure_run_monitor,
    observe_monitor,
    record_monitor_process_start,
    reconcile_run_monitors,
    update_monitor_from_run,
)
from .self_hosting import (
    capture_source_snapshot,
    codex_run_execution_target,
    create_owner_acceptance,
    git_source_state,
    hydrate_source_snapshot,
    invalidate_approved_packs,
    run_git,
)


OUTPUT_TRUNCATION_SUFFIX = "\n[output truncated by TWOS]"
BRIDGE_PREPARATION_GRACE_SECONDS = 5.0
CODING_HANDOFF_SCHEMA = "twos.coding_handoff.v1"


def _valid_coding_handoff_contract(value: str) -> bool:
    """Validate the only Coding message eligible for sidecar-loss recovery."""
    try:
        contract = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(contract, dict) or set(contract) != {
        "schema",
        "status",
        "summary",
    }:
        return False
    summary = contract.get("summary")
    return bool(
        contract.get("schema") == CODING_HANDOFF_SCHEMA
        and contract.get("status") == "completed"
        and isinstance(summary, str)
        and summary.strip()
        and len(summary.encode("utf-8")) <= 4000
    )


class _BridgeRuntimeHandoff(Exception):
    """Stop only the in-process waiter while the detached bridge continues."""

_MODEL_REROUTE = re.compile(
    r"^model rerouted: ([A-Za-z0-9][A-Za-z0-9._:/-]{0,239}) -> "
    r"([A-Za-z0-9][A-Za-z0-9._:/-]{0,239})(?: \([^\r\n]{0,500}\))?$"
)
_SENSITIVE_OUTPUT_KEY = re.compile(
    r"(?:^|_)(?:password|passphrase|secret|credential|token|api_key|authorization|auth|"
    r"cookie|private_key)(?:_|$)",
    re.IGNORECASE,
)
_SENSITIVE_OUTPUT_TEXT = re.compile(
    r"(?i)\b(?:authorization|api[_ -]?key|password|passphrase|client[_ -]?secret|"
    r"session[_ -]?token|access[_ -]?token|refresh[_ -]?token|cookie)\b"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_PROVIDER_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_COMMON_PROVIDER_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[A-Z0-9]{16})\b"
)
_ENV_CREDENTIAL_TEXT = re.compile(
    r"(?i)\b[A-Z][A-Z0-9_]*(?:PASSWORD|PASSPHRASE|SECRET|CREDENTIAL|TOKEN|API_KEY|"
    r"PRIVATE_KEY|AUTHORIZATION|COOKIE)[A-Z0-9_]*"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_THREAD_ID_TEXT = re.compile(r'("thread_id"\s*:\s*")([^"\\]{1,240})(")')
_ABSOLUTE_PATH_TEXT = re.compile(
    r"(?<![A-Za-z0-9._-])/(?:Users|private|tmp|var|home|workspace)/[^\s\"'`,;:]{1,500}"
)
CHILD_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "CODEX_HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    # Authentication values are inherited by the protected detached child,
    # while the immutable ticket records only these key names.
    "OPENAI_API_KEY",
    "CODEX_ACCESS_TOKEN",
    # Preserve the same bounded network/trust context proven by the direct
    # connection control without persisting any value in Run evidence.
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "NO_COLOR",
    "GIT_TERMINAL_PROMPT",
    "GIT_ALLOW_PROTOCOL",
)
SANITIZED_DIFF_MAX_FILES = 200
SANITIZED_DIFF_MAX_FILE_BYTES = 1_000_000
CODEX_MODEL_CATALOG_CACHE_SECONDS = 300.0
CODEX_MODEL_CATALOG_APP_SERVER_TIMEOUT_SECONDS = 8.0
CODEX_MODEL_CATALOG_MAX_BYTES = 4_000_000
CODEX_MODEL_CATALOG_MAX_ENTRIES = 200
CODEX_MODEL_CATALOG_FALLBACK_VERSION = "twos.codex_cli.compatibility.2026-07-21.v1"
CODEX_MODEL_CATALOG_FALLBACK_MINIMUM_CLI = (0, 144, 4)
_SAFE_MODEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")

# This fallback is a versioned compatibility statement, not an availability,
# account-entitlement, or invocation claim. Its entries were verified against
# the bundled machine-readable catalog shipped with Codex CLI 0.144.4.
_CODEX_CLI_COMPATIBILITY_MODELS = (
    ("gpt-5.6-sol", "GPT-5.6-Sol", "Latest frontier agentic coding model."),
    ("gpt-5.6-terra", "GPT-5.6-Terra", "Balanced agentic coding model for everyday work."),
    ("gpt-5.6-luna", "GPT-5.6-Luna", "Fast and affordable agentic coding model."),
    ("gpt-5.5", "GPT-5.5", "Frontier model for complex coding, research, and real-world work."),
    ("gpt-5.4", "GPT-5.4", "Strong model for everyday coding."),
    ("gpt-5.4-mini", "GPT-5.4-Mini", "Small, fast, and cost-efficient model for simpler coding tasks."),
    ("gpt-5.2", "GPT-5.2", "Optimized for professional work and long-running agents."),
)


def _bounded_event_text(value: object, *, maximum: int = 500) -> str:
    """Return a bounded, content-safe event diagnostic for default Result fields."""
    text_value = str(value or "").replace("\x00", " ")
    text_value = _PRIVATE_KEY_BLOCK.sub("[redacted private key]", text_value)
    text_value = _BEARER_TOKEN.sub("Bearer [redacted]", text_value)
    text_value = _PROVIDER_TOKEN.sub("[redacted provider token]", text_value)
    text_value = _COMMON_PROVIDER_TOKEN.sub("[redacted provider token]", text_value)
    text_value = _ENV_CREDENTIAL_TEXT.sub(lambda match: f"[redacted]{match.group(1)}", text_value)
    text_value = _SENSITIVE_OUTPUT_TEXT.sub(lambda match: f"[redacted]{match.group(1)}", text_value)
    text_value = _ABSOLUTE_PATH_TEXT.sub("[path redacted]", text_value)
    return " ".join(text_value.split())[:maximum]


def _failure_classification(message: str) -> str:
    normalized = message.casefold()
    if "model" in normalized and any(
        marker in normalized
        for marker in ("invalid", "unknown", "not found", "not available", "unavailable", "reject")
    ):
        return "invalid_model_identifier"
    if any(marker in normalized for marker in ("auth", "login", "credential", "unauthorized")):
        return "cli_authentication_failure"
    if "parse" in normalized or "json" in normalized:
        return "output_parser_failure"
    return "codex_turn_failed"


def _test_command_label(command: str) -> str:
    normalized = " ".join(command.split())
    patterns = (
        (r"(?:^|\s)(?:pytest|py\.test)(?:\s|$)|(?:^|\s)python(?:3)?\s+-m\s+pytest(?:\s|$)", "pytest"),
        (r"(?:^|\s)(?:npm|pnpm|yarn)\s+(?:run\s+)?test(?:\s|$)", "JavaScript test runner"),
        (r"(?:^|\s)node\s+--test(?:\s|$)", "Node test runner"),
        (r"(?:^|\s)cargo\s+test(?:\s|$)", "cargo test"),
        (r"(?:^|\s)go\s+test(?:\s|$)", "go test"),
        (r"(?:^|\s)swift\s+test(?:\s|$)", "swift test"),
        (r"(?:^|\s)xcodebuild\b[^\n]*\btest\b", "xcodebuild test"),
    )
    for pattern, label in patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return label
    return ""


def _test_output_summary(output: str, exit_code: int | None) -> str:
    candidates = []
    for line in output.splitlines():
        bounded = _bounded_event_text(line, maximum=240)
        if bounded and re.search(
            r"\b(?:\d+\s+)?(?:passed|failed|error|skipped)\b|\btest result\b",
            bounded,
            re.IGNORECASE,
        ):
            candidates.append(bounded)
    if candidates:
        return candidates[-1]
    return (
        f"Test command exited with code {exit_code}."
        if type(exit_code) is int
        else "Test command terminal status was not reported."
    )


class _SharedOutputBudget:
    """Drain both process streams while retaining a bounded combined payload."""

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, limit)
        self._lock = threading.Lock()

    def retain(self, chunk: bytes) -> tuple[bytes, bool]:
        with self._lock:
            retained = chunk[: self.remaining]
            self.remaining -= len(retained)
        return retained, len(retained) != len(chunk)


class _StreamCapture:
    def __init__(self, stream, budget: _SharedOutputBudget, *, observer=None) -> None:
        self.stream = stream
        self.budget = budget
        self.observer = observer
        self.chunks: list[bytes] = []
        self.truncated = False
        self.completed = False
        self.failed = False
        self.observer_failed = False
        self._lock = threading.Lock()

    def drain(self) -> None:
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    return
                if self.observer is not None:
                    try:
                        self.observer.feed(chunk)
                    except Exception:
                        with self._lock:
                            self.observer_failed = True
                        self.observer = None
                retained, truncated = self.budget.retain(chunk)
                with self._lock:
                    if retained:
                        self.chunks.append(retained)
                    self.truncated = self.truncated or truncated
        except Exception:
            with self._lock:
                self.failed = True
        finally:
            try:
                self.stream.close()
            except Exception:
                with self._lock:
                    self.failed = True
            finally:
                with self._lock:
                    self.completed = True

    def data(self) -> bytes:
        with self._lock:
            return b"".join(self.chunks)

    def was_truncated(self) -> bool:
        with self._lock:
            return self.truncated

    def collection_complete(self) -> bool:
        with self._lock:
            return self.completed and not self.failed and not self.observer_failed


class _StdinDelivery:
    def __init__(self, expected_bytes: int) -> None:
        self.expected_bytes = expected_bytes
        self.written_bytes = 0
        self.completed = False
        self.failed = False
        self._lock = threading.Lock()

    def finish(self, written_bytes: int, *, failed: bool = False) -> None:
        with self._lock:
            self.written_bytes = max(0, written_bytes)
            self.failed = failed
            self.completed = not failed and self.written_bytes == self.expected_bytes

    def delivered_exactly(self) -> bool:
        with self._lock:
            return self.completed and not self.failed and self.written_bytes == self.expected_bytes


class _CodexJsonlEvidenceCollector:
    """Parse bounded Codex exec JSONL without treating stdout as one opaque result."""

    MAX_LINE_BYTES = 256_000
    MAX_EVENT_BYTES = 4_000_000
    MAX_EVENTS = 10_000

    def __init__(self, requested_model_identifier: str) -> None:
        self.requested_model_identifier = requested_model_identifier
        self._lock = threading.Lock()
        self._finished = False
        self._buffer = bytearray()
        self._event_bytes = 0
        self._event_count = 0
        self._valid_event_count = 0
        self.evidence_truncated = False
        self._discarding_oversized_line = False
        self._completed_item_keys: set[str] = set()
        self.malformed = False
        self.malformed_line_count = 0
        self.malformed_diagnostics: list[str] = []
        self.limit_exceeded = False
        self.collection_incomplete = False
        self.thread_id_fingerprint = ""
        self.turn_id_fingerprint = ""
        self.thread_started = False
        self.turn_started = False
        self.turn_completed = False
        self.turn_failed = False
        self.terminal_turn_status = ""
        self.fatal_adapter_error = False
        self.failure_classification = ""
        self.failure_summary = ""
        self.final_agent_message = ""
        self.warning_count = 0
        self.command_execution_count = 0
        self.file_change_count = 0
        self.test_executions: list[dict[str, object]] = []
        self.rerouted_from = ""
        self.rerouted_to = ""
        self.unsupported_model_routing_observed = False
        self.resolved_model_identifier = ""
        self.actual_model_identity_verified = False
        self.model_identity_source = ""
        self.model_identity_conflict = False
        self.connectivity_evidence_identity = ""
        self.lifecycle_conflict = False
        self._turn_started_with_identity = False
        self._turn_terminal_with_identity = False
        self.executable_identity_fingerprint = ""
        self.process_id_fingerprint = ""
        self.usage: dict[str, int] = {}
        self.verification_result: dict[str, object] | None = None

    def feed(self, chunk: bytes) -> None:
        with self._lock:
            if self._finished:
                self.malformed = True
                return
            self._buffer.extend(chunk)
            while True:
                newline = self._buffer.find(b"\n")
                if newline < 0:
                    if len(self._buffer) > self.MAX_LINE_BYTES:
                        # Keep draining the transport after an unsafe frame.  A
                        # later, well-formed terminal event must never remain
                        # unread merely because one preceding line was too
                        # large for bounded evidence handling.
                        self.limit_exceeded = True
                        self.evidence_truncated = True
                        self._discarding_oversized_line = True
                        self._buffer.clear()
                    break
                line = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                if self._discarding_oversized_line:
                    self._discarding_oversized_line = False
                    continue
                self._consume_line(line)

    def finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            if self._buffer and not self._discarding_oversized_line:
                self._consume_line(bytes(self._buffer))
            self._buffer.clear()
            self._finished = True

    def mark_incomplete(self) -> None:
        with self._lock:
            self.collection_incomplete = True

    def clear_verified_model_identity(self) -> None:
        """Keep raw lifecycle diagnostics but remove an ineligible model claim."""
        with self._lock:
            self.resolved_model_identifier = ""
            self.actual_model_identity_verified = False
            self.model_identity_source = ""
            self.connectivity_evidence_identity = ""

    def _consume_line(self, line: bytes) -> None:
        if not line.strip():
            return
        self._event_count += 1
        self._event_bytes += len(line)
        if self._event_count > self.MAX_EVENTS or self._event_bytes > self.MAX_EVENT_BYTES:
            # MAX_EVENTS/MAX_EVENT_BYTES bound retained presentation evidence,
            # not transport consumption.  Continue classifying lifecycle
            # events so turn.completed/turn.failed cannot be displaced by a
            # high-volume additive stream.
            self.evidence_truncated = True
        if len(line) > self.MAX_LINE_BYTES:
            self.limit_exceeded = True
            self.evidence_truncated = True
            return
        try:
            event = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._record_malformed("Malformed JSONL line retained in bounded Advanced diagnostics.")
            return
        if not isinstance(event, dict):
            self._record_malformed("Non-object JSONL line retained in bounded Advanced diagnostics.")
            return
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            self._record_malformed("JSONL event did not contain a supported type.")
            return
        self._valid_event_count += 1
        if event_type in {"thread.started", "turn.started", "turn.completed"}:
            self._consume_trusted_model_metadata(event)
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 240:
                self._record_lifecycle_conflict(
                    "thread.started contained an invalid thread identity."
                )
                return
            fingerprint = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
            if self.thread_started or self.turn_started or self.turn_completed or self.turn_failed:
                self._record_lifecycle_conflict(
                    "JSONL stream emitted a duplicate or out-of-order thread.started event."
                )
                return
            if self.thread_id_fingerprint and self.thread_id_fingerprint != fingerprint:
                self._record_lifecycle_conflict("JSONL stream changed thread identity.")
                return
            self.thread_id_fingerprint = fingerprint
            self.thread_started = True
        elif event_type == "turn.started":
            if not self.thread_started or self.turn_started or self.turn_completed or self.turn_failed:
                self._record_lifecycle_conflict(
                    "JSONL stream emitted turn.started outside the single ordered lifecycle."
                )
                return
            self.turn_started = True
            turn_id = event.get("turn_id") or event.get("id")
            if turn_id is not None and (
                not isinstance(turn_id, str) or not 0 < len(turn_id) <= 240
            ):
                self._record_lifecycle_conflict(
                    "turn.started contained an invalid turn identity."
                )
                return
            if isinstance(turn_id, str):
                self._turn_started_with_identity = True
                fingerprint = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()
                if self.turn_id_fingerprint and self.turn_id_fingerprint != fingerprint:
                    self._record_lifecycle_conflict("JSONL stream changed turn identity.")
                else:
                    self.turn_id_fingerprint = fingerprint
        elif event_type == "turn.completed":
            if not self.thread_started or not self.turn_started or self.turn_completed or self.turn_failed:
                self._record_lifecycle_conflict(
                    "JSONL stream emitted turn.completed outside the single ordered lifecycle."
                )
                return
            terminal_turn_id = event.get("turn_id") or event.get("id")
            if terminal_turn_id is not None and (
                not isinstance(terminal_turn_id, str)
                or not 0 < len(terminal_turn_id) <= 240
            ):
                self._record_lifecycle_conflict(
                    "turn.completed contained an invalid turn identity."
                )
                return
            self._turn_terminal_with_identity = isinstance(terminal_turn_id, str)
            if self._turn_started_with_identity != self._turn_terminal_with_identity:
                self._record_lifecycle_conflict(
                    "JSONL stream exposed only a partial terminal turn identity."
                )
                return
            if isinstance(terminal_turn_id, str):
                terminal_fingerprint = hashlib.sha256(
                    terminal_turn_id.encode("utf-8")
                ).hexdigest()
                if terminal_fingerprint != self.turn_id_fingerprint:
                    self._record_lifecycle_conflict(
                        "JSONL stream completed a different turn identity."
                    )
                    return
            usage = event.get("usage")
            if isinstance(usage, dict):
                allowed = {
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                }
                bounded_usage: dict[str, int] = {}
                for key in allowed:
                    value = usage.get(key)
                    if value is None:
                        continue
                    if type(value) is not int or not 0 <= value <= 10**12:
                        self._record_malformed("turn.completed contained invalid usage metadata.")
                        bounded_usage = {}
                        break
                    bounded_usage[key] = value
                self.usage = bounded_usage
            self.terminal_turn_status = "completed"
            self.turn_completed = True
            self.turn_failed = False
        elif event_type == "turn.failed":
            if not self.thread_started or not self.turn_started or self.turn_completed or self.turn_failed:
                self._record_lifecycle_conflict(
                    "JSONL stream emitted turn.failed outside the single ordered lifecycle."
                )
                return
            terminal_turn_id = event.get("turn_id") or event.get("id")
            if terminal_turn_id is not None and (
                not isinstance(terminal_turn_id, str)
                or not 0 < len(terminal_turn_id) <= 240
            ):
                self._record_lifecycle_conflict(
                    "turn.failed contained an invalid turn identity."
                )
                return
            self._turn_terminal_with_identity = isinstance(terminal_turn_id, str)
            if self._turn_started_with_identity != self._turn_terminal_with_identity:
                self._record_lifecycle_conflict(
                    "JSONL stream exposed only a partial failed-turn identity."
                )
                return
            if isinstance(terminal_turn_id, str):
                terminal_fingerprint = hashlib.sha256(
                    terminal_turn_id.encode("utf-8")
                ).hexdigest()
                if terminal_fingerprint != self.turn_id_fingerprint:
                    self._record_lifecycle_conflict(
                        "JSONL stream failed a different turn identity."
                    )
                    return
            self.terminal_turn_status = "failed"
            self.turn_completed = False
            self.turn_failed = True
            self._record_failure(self._event_message(event), terminal=True)
        elif event_type == "error":
            message = self._event_message(event)
            if event.get("fatal") is True:
                self.fatal_adapter_error = True
                self._record_failure(message or "Codex reported a fatal adapter error.", terminal=True)
            elif message:
                self._record_failure(message, terminal=False)
        elif event_type == "warning":
            self.warning_count += 1
        elif event_type in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                return
            if event_type != "item.completed":
                return
            item_key = str(item.get("id") or hashlib.sha256(line).hexdigest())
            if item_key in self._completed_item_keys:
                return
            self._completed_item_keys.add(item_key)
            item_type = item.get("type")
            if item_type == "agent_message":
                message = item.get("text")
                if not isinstance(message, str):
                    return
                self.final_agent_message = _bounded_event_text(message, maximum=2000)
                try:
                    candidate = json.loads(message)
                except json.JSONDecodeError:
                    return
                if not isinstance(candidate, dict) or candidate.get("schema") != "twos.verification.v1":
                    return
                if self.verification_result is not None and self.verification_result != candidate:
                    self._record_malformed("Verification emitted conflicting structured verdicts.")
                    return
                self.verification_result = candidate
                return
            if item_type == "command_execution":
                self._consume_command_execution(item)
                return
            if item_type in {"file_change", "file_changes"}:
                self.file_change_count += 1
                return
            if item_type != "error":
                return
            message = item.get("message")
            if not isinstance(message, str):
                return
            match = _MODEL_REROUTE.fullmatch(message)
            if not match:
                if "rerout" in message.casefold():
                    self.unsupported_model_routing_observed = True
                    self._record_malformed("Codex emitted an unsupported model reroute diagnostic.")
                else:
                    self._record_failure(message, terminal=False)
                return
            rerouted_from, rerouted_to = match.groups()
            if self.rerouted_to and self.rerouted_to != rerouted_to:
                self._record_malformed("Codex emitted conflicting model reroute diagnostics.")
                self.model_identity_conflict = True
                self.actual_model_identity_verified = False
                self.unsupported_model_routing_observed = True
                return
            if self.resolved_model_identifier and self.resolved_model_identifier != rerouted_to:
                self._record_malformed("Codex emitted conflicting actual model evidence.")
                self.model_identity_conflict = True
                self.actual_model_identity_verified = False
                self.unsupported_model_routing_observed = True
                return
            self.rerouted_from = rerouted_from
            self.rerouted_to = rerouted_to
            self.resolved_model_identifier = rerouted_to
            self.actual_model_identity_verified = True
            self.model_identity_source = "validated_reroute_event"
        elif isinstance(event_type, str) and (
            "rerout" in event_type.casefold()
            or (
                "model" in event_type.casefold()
                and any(
                    marker in event_type.casefold()
                    for marker in ("change", "switch", "select", "fallback")
                )
            )
        ):
            # The installed Codex exec JSONL contract emits reroutes as a
            # specific item.completed error. Unknown routing event shapes must
            # never be interpreted as proof of the requested model identity.
            self.unsupported_model_routing_observed = True
            self._record_malformed("Codex emitted an unsupported model routing event shape.")

    def _record_malformed(self, summary: str) -> None:
        self.malformed = True
        self.malformed_line_count += 1
        if len(self.malformed_diagnostics) < 20:
            self.malformed_diagnostics.append(_bounded_event_text(summary, maximum=240))

    def _record_lifecycle_conflict(self, summary: str) -> None:
        self.lifecycle_conflict = True
        self.resolved_model_identifier = ""
        self.actual_model_identity_verified = False
        self.model_identity_source = ""
        self._record_malformed(summary)

    @staticmethod
    def _event_message(event: dict[str, object]) -> str:
        for candidate in (
            event.get("message"),
            event.get("error"),
            event.get("detail"),
        ):
            if isinstance(candidate, str):
                return candidate
            if isinstance(candidate, dict):
                for key in ("message", "detail", "reason"):
                    value = candidate.get(key)
                    if isinstance(value, str):
                        return value
        return ""

    def _record_failure(self, message: str, *, terminal: bool) -> None:
        safe_message = _bounded_event_text(message, maximum=500)
        if not safe_message:
            safe_message = "Codex turn failed without a public diagnostic."
        if terminal or not self.failure_summary:
            self.failure_summary = safe_message
            self.failure_classification = _failure_classification(safe_message)

    def _consume_trusted_model_metadata(self, event: dict[str, object]) -> None:
        candidate = ""
        for key in (
            "actual_resolved_model",
            "actual_model_identifier",
            "resolved_model",
        ):
            value = event.get(key)
            if isinstance(value, str) and value:
                candidate = value
                break
        if not candidate:
            return
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}", candidate):
            self._record_malformed("Trusted lifecycle metadata contained an unsafe model identifier.")
            return
        if self.resolved_model_identifier and self.resolved_model_identifier != candidate:
            self._record_malformed("Trusted lifecycle metadata contained conflicting model identities.")
            self.model_identity_conflict = True
            self.actual_model_identity_verified = False
            self.unsupported_model_routing_observed = True
            return
        self.resolved_model_identifier = candidate
        self.actual_model_identity_verified = True
        self.model_identity_source = "explicit_actual_model_metadata"

    def _consume_command_execution(self, item: dict[str, object]) -> None:
        self.command_execution_count += 1
        raw_command = item.get("command")
        if isinstance(raw_command, list):
            command = " ".join(str(part) for part in raw_command)
        else:
            command = str(raw_command or "")
        label = _test_command_label(command)
        if not label:
            return
        raw_exit = item.get("exit_code")
        exit_code = raw_exit if type(raw_exit) is int else None
        output = item.get("aggregated_output")
        if not isinstance(output, str):
            output = str(item.get("output") or "")
        self.test_executions.append(
            {
                "evidence_type": "test_execution",
                "command_label": label,
                "status": "passed" if exit_code == 0 else "failed" if exit_code is not None else "unknown",
                "exit_code": exit_code,
                "summary": _test_output_summary(output, exit_code),
            }
        )

    @property
    def actual_model_identifier(self) -> str:
        return self.resolved_model_identifier

    @property
    def jsonl_observed(self) -> bool:
        return self._valid_event_count > 0

    @property
    def structured_success(self) -> bool:
        return bool(
            not self.limit_exceeded
            and not self.collection_incomplete
            and not self.lifecycle_conflict
            and self.thread_started
            and self.turn_started
            and self.turn_completed
            and self.terminal_turn_status == "completed"
            and not self.fatal_adapter_error
            and self.thread_id_fingerprint
        )


@dataclass(frozen=True)
class CodexDetection:
    status: str
    found: bool
    executable: str | None
    version: str | None
    supported_command: str | None
    reason: str
    next_action: str

    def as_dict(self, include_path: bool = False) -> dict[str, object]:
        output = asdict(self)
        if not include_path:
            output.pop("executable", None)
        return output


@dataclass(frozen=True)
class CodexModelCatalogEntry:
    adapter_id: str
    provider_id: str
    canonical_model_id: str
    display_name: str
    aliases: tuple[str, ...]
    selectable: bool
    recommended: bool
    lifecycle_status: str
    compatibility_status: str
    compatibility_source: str
    catalog_version: str
    supported_capabilities: tuple[str, ...]
    purpose: str
    minimum_cli_version: str | None = None
    model_family: str | None = None
    performance_tier: str | None = None
    disabled_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "provider_id": self.provider_id,
            "canonical_model_id": self.canonical_model_id,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "selectable": self.selectable,
            "recommended": self.recommended,
            "lifecycle_status": self.lifecycle_status,
            "compatibility_status": self.compatibility_status,
            "compatibility_source": self.compatibility_source,
            "catalog_version": self.catalog_version,
            "minimum_cli_version": self.minimum_cli_version,
            "supported_capabilities": list(self.supported_capabilities),
            "model_family": self.model_family,
            "performance_tier": self.performance_tier,
            "purpose": self.purpose,
            "disabled_reason": self.disabled_reason,
        }


@dataclass(frozen=True)
class CodexModelCatalog:
    status: str
    source: str
    version: str
    installed_cli_version: str | None
    warnings: tuple[str, ...]
    models: tuple[CodexModelCatalogEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_status": self.status,
            "catalog_source": self.source,
            "catalog_version": self.version,
            "installed_cli_version": self.installed_cli_version,
            "warnings": list(self.warnings),
            "models": [model.as_dict() for model in self.models],
        }


class CodexAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model_catalog_lock = threading.Lock()
        self._model_catalog_cached_at = 0.0
        self._model_catalog_cache: CodexModelCatalog | None = None

    @staticmethod
    def _catalog_text(value: object, *, maximum: int) -> str:
        if not isinstance(value, str):
            return ""
        return _bounded_event_text(value[: maximum * 4], maximum=maximum)

    @staticmethod
    def _cli_version_tuple(version: str | None) -> tuple[int, int, int] | None:
        match = re.search(r"(?:^|\s)(\d+)\.(\d+)\.(\d+)(?:\D|$)", version or "")
        if not match:
            return None
        return tuple(int(part) for part in match.groups())

    def _parse_cli_model_catalog(
        self,
        raw_output: str,
        *,
        source: str,
        installed_cli_version: str | None,
    ) -> CodexModelCatalog:
        if len(raw_output.encode("utf-8", errors="replace")) > CODEX_MODEL_CATALOG_MAX_BYTES:
            raise ValueError("catalog output exceeded the bounded parser limit")
        payload = json.loads(raw_output)
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("catalog response did not contain a models list")
        safe_rows: list[tuple[int, str, str, tuple[str, ...], str]] = []
        for raw_model in payload["models"][:CODEX_MODEL_CATALOG_MAX_ENTRIES]:
            if not isinstance(raw_model, dict) or raw_model.get("visibility") != "list":
                continue
            canonical_id = raw_model.get("slug")
            if not isinstance(canonical_id, str) or not _SAFE_MODEL_IDENTIFIER.fullmatch(canonical_id):
                continue
            display_name = self._catalog_text(raw_model.get("display_name"), maximum=120) or canonical_id
            purpose = self._catalog_text(raw_model.get("description"), maximum=240)
            aliases: list[str] = []
            raw_aliases = raw_model.get("aliases")
            if isinstance(raw_aliases, list):
                for alias in raw_aliases[:20]:
                    if (
                        isinstance(alias, str)
                        and alias != canonical_id
                        and _SAFE_MODEL_IDENTIFIER.fullmatch(alias)
                        and alias not in aliases
                    ):
                        aliases.append(alias)
            priority = raw_model.get("priority")
            safe_priority = priority if type(priority) is int else 1_000_000
            safe_rows.append((safe_priority, canonical_id, display_name, tuple(aliases), purpose))
        if not safe_rows:
            raise ValueError("catalog contained no visible safe model entries")
        safe_rows.sort(key=lambda row: (row[0], row[1]))
        digest_payload = [
            {"id": row[1], "name": row[2], "aliases": row[3], "purpose": row[4]}
            for row in safe_rows
        ]
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        version_label = self._catalog_text(installed_cli_version, maximum=80) or "unknown-cli"
        catalog_version = f"{version_label}.catalog-{digest}"
        models = tuple(
            CodexModelCatalogEntry(
                adapter_id="codex_cli",
                provider_id="local_codex_cli",
                canonical_model_id=canonical_id,
                display_name=display_name,
                aliases=aliases,
                selectable=True,
                recommended=index == 0,
                lifecycle_status="current",
                compatibility_status="catalog_listed",
                compatibility_source=source,
                catalog_version=catalog_version,
                supported_capabilities=("coding", "verification"),
                purpose=purpose,
            )
            for index, (_, canonical_id, display_name, aliases, purpose) in enumerate(safe_rows)
        )
        return CodexModelCatalog(
            status="available" if source == "installed_codex_cli_machine_readable" else "bundled",
            source=source,
            version=catalog_version,
            installed_cli_version=self._catalog_text(installed_cli_version, maximum=80) or None,
            warnings=(),
            models=models,
        )

    def _parse_app_server_model_catalog(
        self,
        raw_models: list[object],
        *,
        installed_cli_version: str | None,
    ) -> CodexModelCatalog:
        safe_rows: list[tuple[str, str, tuple[str, ...], bool, str | None]] = []
        seen: set[str] = set()
        for raw_model in raw_models[:CODEX_MODEL_CATALOG_MAX_ENTRIES]:
            if not isinstance(raw_model, dict) or raw_model.get("hidden") is True:
                continue
            canonical_id = raw_model.get("model") or raw_model.get("id")
            if (
                not isinstance(canonical_id, str)
                or canonical_id in seen
                or not _SAFE_MODEL_IDENTIFIER.fullmatch(canonical_id)
            ):
                continue
            seen.add(canonical_id)
            display_name = self._catalog_text(raw_model.get("displayName"), maximum=120) or canonical_id
            aliases: list[str] = []
            entry_id = raw_model.get("id")
            if (
                isinstance(entry_id, str)
                and entry_id != canonical_id
                and _SAFE_MODEL_IDENTIFIER.fullmatch(entry_id)
            ):
                aliases.append(entry_id)
            default_effort = raw_model.get("defaultReasoningEffort")
            safe_effort = (
                default_effort
                if isinstance(default_effort, str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", default_effort)
                else None
            )
            safe_rows.append(
                (canonical_id, display_name, tuple(aliases), raw_model.get("isDefault") is True, safe_effort)
            )
        if not safe_rows:
            raise ValueError("app-server catalog contained no visible safe model entries")
        digest = hashlib.sha256(
            json.dumps(safe_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        version_label = self._catalog_text(installed_cli_version, maximum=80) or "unknown-cli"
        catalog_version = f"{version_label}.app-server-{digest}"
        models = tuple(
            CodexModelCatalogEntry(
                adapter_id="codex_cli",
                provider_id="local_codex_cli",
                canonical_model_id=canonical_id,
                display_name=display_name,
                aliases=aliases,
                selectable=True,
                recommended=recommended,
                lifecycle_status="current",
                compatibility_status="catalog_listed",
                compatibility_source="codex_app_server_model_list",
                catalog_version=catalog_version,
                supported_capabilities=("coding", "verification"),
                purpose=(
                    f"Default reasoning effort: {default_effort}." if default_effort else ""
                ),
                performance_tier=default_effort,
            )
            for canonical_id, display_name, aliases, recommended, default_effort in safe_rows
        )
        return CodexModelCatalog(
            status="available",
            source="codex_app_server_model_list",
            version=catalog_version,
            installed_cli_version=self._catalog_text(installed_cli_version, maximum=80) or None,
            warnings=(),
            models=models,
        )

    def _app_server_model_catalog(self, detection: CodexDetection) -> CodexModelCatalog:
        if not detection.executable:
            raise ValueError("Codex CLI executable is unavailable")
        process = subprocess.Popen(
            [detection.executable, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=tempfile.gettempdir(),
        )
        if process.stdin is None or process.stdout is None:
            process.terminate()
            raise ValueError("app-server stdio transport was unavailable")
        selector = selectors.DefaultSelector()
        stdout_fd = process.stdout.fileno()
        os.set_blocking(stdout_fd, False)
        selector.register(stdout_fd, selectors.EVENT_READ)
        deadline = time.monotonic() + CODEX_MODEL_CATALOG_APP_SERVER_TIMEOUT_SECONDS
        observed_bytes = 0
        frame_buffer = bytearray()

        def send(message: dict[str, object]) -> None:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def response_for(request_id: int) -> dict[str, object]:
            nonlocal observed_bytes
            while time.monotonic() < deadline:
                while b"\n" in frame_buffer:
                    raw_line, _, remainder = frame_buffer.partition(b"\n")
                    frame_buffer[:] = remainder
                    raw_line = raw_line.rstrip(b"\r")
                    if not raw_line.strip():
                        continue
                    message = json.loads(raw_line.decode("utf-8"))
                    if not isinstance(message, dict) or message.get("id") != request_id:
                        continue
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise ValueError("app-server catalog request failed")
                    return message["result"]
                ready = selector.select(max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                try:
                    chunk = os.read(
                        stdout_fd,
                        min(65_536, CODEX_MODEL_CATALOG_MAX_BYTES - observed_bytes + 1),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                observed_bytes += len(chunk)
                if observed_bytes > CODEX_MODEL_CATALOG_MAX_BYTES:
                    raise ValueError("app-server catalog response exceeded the bounded parser limit")
                frame_buffer.extend(chunk)
            raise TimeoutError("app-server catalog response timed out")

        raw_models: list[object] = []
        try:
            send(
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "twos",
                            "title": "TWOS",
                            "version": "0.17.0",
                        }
                    },
                }
            )
            response_for(1)
            send({"method": "initialized", "params": {}})
            cursor: str | None = None
            for page in range(4):
                request_id = 10 + page
                params: dict[str, object] = {"limit": 100, "includeHidden": False}
                if cursor:
                    params["cursor"] = cursor
                send({"method": "model/list", "id": request_id, "params": params})
                result = response_for(request_id)
                data = result.get("data")
                if not isinstance(data, list):
                    raise ValueError("app-server catalog response omitted model data")
                raw_models.extend(data[:CODEX_MODEL_CATALOG_MAX_ENTRIES - len(raw_models)])
                next_cursor = result.get("nextCursor")
                if next_cursor is None:
                    break
                if not isinstance(next_cursor, str) or len(next_cursor) > 500:
                    raise ValueError("app-server returned an invalid catalog cursor")
                cursor = next_cursor
            return self._parse_app_server_model_catalog(
                raw_models,
                installed_cli_version=detection.version,
            )
        finally:
            selector.close()
            try:
                process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)

    def _versioned_compatibility_catalog(
        self,
        installed_cli_version: str | None,
        warnings: list[str],
    ) -> CodexModelCatalog:
        parsed_version = self._cli_version_tuple(installed_cli_version)
        supported_version = bool(
            parsed_version and parsed_version >= CODEX_MODEL_CATALOG_FALLBACK_MINIMUM_CLI
        )
        disabled_reason = (
            ""
            if supported_version
            else "Installed CLI version could not be matched to the versioned compatibility contract."
        )
        models = tuple(
            CodexModelCatalogEntry(
                adapter_id="codex_cli",
                provider_id="local_codex_cli",
                canonical_model_id=canonical_id,
                display_name=display_name,
                aliases=(),
                selectable=supported_version,
                recommended=index == 0,
                lifecycle_status="compatible" if supported_version else "unavailable",
                compatibility_status=(
                    "versioned_compatibility" if supported_version else "unverified_cli_version"
                ),
                compatibility_source="twos_versioned_compatibility",
                catalog_version=CODEX_MODEL_CATALOG_FALLBACK_VERSION,
                minimum_cli_version="0.144.4",
                supported_capabilities=("coding", "verification"),
                purpose=purpose,
                disabled_reason=disabled_reason,
            )
            for index, (canonical_id, display_name, purpose) in enumerate(
                _CODEX_CLI_COMPATIBILITY_MODELS
            )
        )
        return CodexModelCatalog(
            status="fallback" if supported_version else "unavailable",
            source="twos_versioned_compatibility",
            version=CODEX_MODEL_CATALOG_FALLBACK_VERSION,
            installed_cli_version=self._catalog_text(installed_cli_version, maximum=80) or None,
            warnings=tuple(warnings[:4]),
            models=models,
        )

    def model_catalog(self, *, force_refresh: bool = False) -> CodexModelCatalog:
        now = time.monotonic()
        with self._model_catalog_lock:
            if (
                not force_refresh
                and self._model_catalog_cache is not None
                and now - self._model_catalog_cached_at < CODEX_MODEL_CATALOG_CACHE_SECONDS
            ):
                return self._model_catalog_cache

        detection = self.detect()
        warnings: list[str] = []
        catalog: CodexModelCatalog | None = None
        if detection.executable:
            try:
                catalog = self._app_server_model_catalog(detection)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
                warnings.append(
                    "codex_app_server_model_list unavailable "
                    f"({type(exc).__name__}); no raw protocol output was retained."
                )
            if catalog is None:
                source = "installed_codex_cli_bundled"
                try:
                    result = subprocess.run(
                        [detection.executable, "debug", "models", "--bundled"],
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    if result.returncode != 0:
                        raise ValueError("catalog command returned a non-zero status")
                    catalog = self._parse_cli_model_catalog(
                        result.stdout,
                        source=source,
                        installed_cli_version=detection.version,
                    )
                except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
                    warnings.append(
                        f"{source} unavailable ({type(exc).__name__}); no raw command output was retained."
                    )
        if catalog is None:
            catalog = self._versioned_compatibility_catalog(detection.version, warnings)
        elif warnings:
            catalog = CodexModelCatalog(
                status=catalog.status,
                source=catalog.source,
                version=catalog.version,
                installed_cli_version=catalog.installed_cli_version,
                warnings=tuple(warnings[:4]),
                models=catalog.models,
            )
        with self._model_catalog_lock:
            self._model_catalog_cache = catalog
            self._model_catalog_cached_at = time.monotonic()
        return catalog

    def catalog_model(self, model_identifier: str) -> CodexModelCatalogEntry | None:
        return next(
            (
                model
                for model in self.model_catalog().models
                if model.selectable and model.canonical_model_id == model_identifier
            ),
            None,
        )

    def detect(self) -> CodexDetection:
        executable = self.settings.codex_executable or shutil.which("codex")
        if not executable or not Path(executable).is_file():
            return CodexDetection(
                status="unconfigured",
                found=False,
                executable=None,
                version=None,
                supported_command=None,
                reason="Codex CLI was not found on PATH.",
                next_action="Install and authenticate the supported Codex CLI, then refresh Runtime Status.",
            )
        try:
            version_result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            help_result = subprocess.run(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=None,
                supported_command=None,
                reason=f"Codex entrypoint exists but could not run ({type(exc).__name__}).",
                next_action="Repair or reinstall the local Codex CLI binary and verify authentication.",
            )

        version_text = (version_result.stdout or version_result.stderr).strip().splitlines()
        version = version_text[0][:240] if version_result.returncode == 0 and version_text else None
        help_text = (help_result.stdout or help_result.stderr).strip()
        if version_result.returncode != 0 or help_result.returncode != 0:
            failed_checks = []
            if version_result.returncode != 0:
                failed_checks.append("version")
            if help_result.returncode != 0:
                failed_checks.append("non-interactive exec")
            reason = f"Codex CLI {' and '.join(failed_checks)} capability check failed."
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=version,
                supported_command=None,
                reason=reason[:1000],
                next_action="Repair Codex CLI setup or authentication, then run detection again.",
            )
        if "exec" not in help_text.lower() or "--model" not in help_text or "--json" not in help_text:
            return CodexDetection(
                status="needs_setup",
                found=True,
                executable=executable,
                version=version,
                supported_command=None,
                reason="Installed Codex CLI does not advertise the required exec, model, and JSON evidence options.",
                next_action="Upgrade to a Codex CLI version that supports codex exec --model and --json.",
            )
        return CodexDetection(
            status="configured",
            found=True,
            executable=executable,
            version=version,
            supported_command="exec",
            reason="Codex CLI and non-interactive exec command were detected.",
            next_action="Approve the current Codex Instruction Pack before running it.",
        )

    def source_state(self) -> dict[str, object]:
        return git_source_state(
            self.settings.source_repo,
            hardened_read_only=True,
        )

    def validate_source_identity(
        self,
        *,
        expected_repo: str,
        expected_branch: str,
        expected_commit: str,
    ) -> dict[str, object]:
        """Bind execution preparation to the exact admitted repository state."""

        state = self.source_state()
        try:
            repository_matches = (
                Path(str(state["repo"])).resolve()
                == Path(expected_repo).resolve()
            )
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                "Approved source repository identity could not be verified."
            ) from exc
        if not repository_matches:
            raise RuntimeError(
                "Source repository does not match the approved Run binding."
            )
        if str(state.get("branch") or "") != str(expected_branch or ""):
            raise RuntimeError(
                "Source branch does not match the approved Run binding."
            )
        if str(state.get("commit") or "") != str(expected_commit or ""):
            raise RuntimeError(
                "Source HEAD does not match the approved Run binding."
            )
        return state

    @staticmethod
    def authentication_ready(detection: CodexDetection) -> tuple[bool, str]:
        if detection.status != "configured" or not detection.executable:
            return False, "Codex CLI readiness must pass before authentication can be verified."
        diagnostic = inspect_authentication(
            detection.executable,
            environment=codex_child_environment(),
        )
        ready = bool(
            diagnostic.state
            in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"}
            and diagnostic.credential_store_accessible
        )
        return ready, diagnostic.safe_summary

    def create_worktree(self, run_id: int, source_commit: str) -> tuple[Path, str]:
        state = self.source_state()
        if state["commit"] != source_commit:
            raise RuntimeError("Source repository HEAD differs from the approved instruction-pack baseline.")
        token = uuid.uuid4().hex[:8]
        branch = f"twos/codex-run-{run_id}-{token}"
        root = self.settings.worktree_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        worktree = root / f"run-{run_id}-{token}"
        run_git(Path(state["repo"]), "worktree", "add", "-b", branch, str(worktree), source_commit, timeout=60)
        return worktree, branch

    def discard_unstarted_worktree(
        self,
        worktree: Path,
        branch: str,
    ) -> tuple[bool, str]:
        """Remove one manager-created worktree and verify the final state.

        The previous implementation ignored both Git exit statuses.  That made
        a failed cleanup indistinguishable from a successful pre-launch block.
        Return only stable diagnostic codes so callers can persist truthful
        evidence without leaking a host path or raw Git output.
        """

        source_repo = self.settings.source_repo.resolve()
        authorized_root = self.settings.worktree_root.resolve(strict=False)
        candidate = worktree.resolve(strict=False)
        if (
            not candidate.is_relative_to(authorized_root)
            or not re.fullmatch(r"twos/codex-run-[0-9]+-[0-9a-f]{8}", branch)
        ):
            return False, "UNSTARTED_WORKTREE_IDENTITY_INVALID"

        remove = run_git(
            source_repo,
            "worktree",
            "remove",
            "--force",
            str(candidate),
            check=False,
            timeout=60,
        )
        delete_branch = run_git(
            source_repo,
            "branch",
            "-D",
            branch,
            check=False,
            timeout=30,
        )
        worktree_list = run_git(
            source_repo,
            "worktree",
            "list",
            "--porcelain",
            check=False,
            timeout=30,
        )
        branch_ref = run_git(
            source_repo,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
            timeout=30,
        )
        path_state_verified = True
        try:
            candidate.lstat()
            path_present = True
        except FileNotFoundError:
            path_present = False
        except OSError:
            path_present = True
            path_state_verified = False
        registered = bool(
            worktree_list.returncode == 0
            and f"worktree {candidate}\n" in f"{worktree_list.stdout.rstrip()}\n"
        )
        branch_present = branch_ref.returncode == 0
        cleanup_verified = bool(
            worktree_list.returncode == 0
            and branch_ref.returncode in {0, 1}
            and path_state_verified
            and not path_present
            and not registered
            and not branch_present
        )
        if cleanup_verified:
            return True, "UNSTARTED_WORKTREE_CLEANUP_VERIFIED"

        blockers: list[str] = []
        if remove.returncode != 0:
            blockers.append("WORKTREE_REMOVE_FAILED")
        if delete_branch.returncode != 0 and branch_present:
            blockers.append("BRANCH_DELETE_FAILED")
        if worktree_list.returncode != 0:
            blockers.append("WORKTREE_REGISTRY_UNVERIFIED")
        elif registered:
            blockers.append("WORKTREE_STILL_REGISTERED")
        if branch_ref.returncode not in {0, 1}:
            blockers.append("BRANCH_STATE_UNVERIFIED")
        elif branch_present:
            blockers.append("BRANCH_STILL_PRESENT")
        if path_present:
            blockers.append("WORKTREE_PATH_STILL_PRESENT")
        if not path_state_verified:
            blockers.append("WORKTREE_PATH_STATE_UNVERIFIED")
        return False, ",".join(dict.fromkeys(blockers)) or "CLEANUP_UNVERIFIED"

    def command_for(
        self,
        detection: CodexDetection,
        pack_content: str,
        model_identifier: str,
        *,
        sandbox_mode: str = "workspace-write",
        output_last_message: Path | None = None,
    ) -> list[str]:
        if detection.status != "configured" or not detection.executable or not detection.supported_command:
            raise RuntimeError("Codex CLI is not configured for execution.")
        if not model_identifier or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}", model_identifier
        ):
            raise RuntimeError("The approved Codex model identifier is missing or unsafe.")
        if sandbox_mode not in {"workspace-write", "read-only"}:
            raise RuntimeError("The Codex sandbox mode is not supported.")
        # The approved pack is transported through stdin using Codex's documented
        # `-` prompt sentinel. Keeping it out of argv avoids ARG_MAX failures and
        # guarantees that shell metacharacters remain inert data.
        command = [
            detection.executable,
            detection.supported_command,
            "--model",
            model_identifier,
            "--json",
            "--sandbox",
            sandbox_mode,
            "--ephemeral",
            "--ignore-user-config",
            "--color",
            "never",
        ]
        if output_last_message is not None:
            if not output_last_message.is_absolute():
                raise RuntimeError("The Codex final-result sidecar path must be absolute.")
            command.extend(["--output-last-message", str(output_last_message)])
        command.append("-")
        return command


class CodexExecutionManager:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.adapter = CodexAdapter(settings)
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._workers: dict[int, threading.Thread] = {}
        self._cancel_requested: set[int] = set()
        self._stopping = False
        instance_identity = hashlib.sha256(
            (
                f"{settings.database_url}\0"
                f"{settings.source_repo.resolve(strict=False)}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        bridge_base = codex_exec_bridge.prepare_spool_root(
            settings.codex_spool_root.resolve(strict=False),
            forbidden_roots=(settings.source_repo,),
        )
        self._bridge_root = bridge_base / instance_identity
        self._bridge_handles: dict[tuple[int, str], codex_exec_bridge.ExecutionHandle] = {}

    @staticmethod
    def _invalidate_approved_model_assignments(
        session: Session,
        model_ids: set[int],
        *,
        reason: str,
    ) -> None:
        if not model_ids:
            return
        task_ids = set(
            session.scalars(
                select(AIModelAssignment.task_id).where(
                    or_(
                        AIModelAssignment.assigned_model_id.in_(model_ids),
                        AIModelAssignment.fallback_model_id.in_(model_ids),
                    )
                )
            ).all()
        )
        for task_id in task_ids:
            invalidated = invalidate_approved_packs(session, task_id)
            if invalidated:
                task = session.get(Task, task_id)
                if task is not None:
                    task.status = "planned"
                session.add(
                    AuditEvent(
                        action="codex_pack_approval_invalidated",
                        entity_type="task",
                        entity_id=task_id,
                        details=f"{reason}; invalidated_packs={invalidated}.",
                    )
                )

    def sync_local_model_registry(self) -> None:
        """Apply an explicit, secret-free local Codex model binding at startup."""
        model_identifier = str(self.settings.codex_model_identifier or "").strip()
        if not model_identifier:
            # Owner-created UI configuration is durable. An absent legacy
            # startup binding must not erase or downgrade it on restart.
            return
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}", model_identifier):
            raise ValueError("TWOS_CODEX_MODEL_ID must be a safe Codex model identifier.")
        requested_capabilities = tuple(dict.fromkeys(self.settings.codex_model_capabilities))
        if not requested_capabilities:
            raise ValueError("TWOS_CODEX_MODEL_CAPABILITIES must name at least one capability.")
        detection = self.adapter.detect()
        with self.factory() as session:
            supported_capabilities = {
                item.name
                for item in session.scalars(select(AICapability).where(AICapability.enabled == True)).all()  # noqa: E712
            }
            if any(
                not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", item)
                or item not in supported_capabilities
                for item in requested_capabilities
            ):
                raise ValueError(
                    "TWOS_CODEX_MODEL_CAPABILITIES contains an unsupported capability name."
                )
            provider = session.scalar(
                select(Provider).where(
                    Provider.name == "Local Codex CLI",
                    Provider.kind == "model",
                )
            )
            if provider is None:
                provider = Provider(
                    name="Local Codex CLI",
                    kind="model",
                    status="unconfigured",
                    enabled=False,
                    details="Explicit local Codex CLI adapter; no provider credentials are stored by TWOS.",
                )
                session.add(provider)
                session.flush()
            model = session.scalar(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.execution_adapter == "codex_cli",
                    AIModel.provider_model_id == model_identifier,
                )
            )
            if model is None:
                stable_id = f"codex-cli.{hashlib.sha256(model_identifier.encode('utf-8')).hexdigest()[:16]}"
                model = AIModel(
                    provider_id=provider.id,
                    model_name=model_identifier,
                    stable_id=stable_id,
                    display_name=model_identifier,
                    provider_model_id=model_identifier,
                    execution_adapter="codex_cli",
                    capability_tags=json.dumps(requested_capabilities, separators=(",", ":")),
                    context_limit=None,
                    cost_metadata="unknown",
                    latency_metadata="unknown",
                    routing_priority=5,
                )
                session.add(model)
            session.flush()
            tracked_models = list(session.scalars(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.execution_adapter == "codex_cli",
                )
            ).all())
            provider_before = (provider.enabled, provider.status)
            model_before = {
                item.id: (
                    item.status,
                    item.configuration_status,
                    item.availability_status,
                    item.invocation_mode,
                    item.evidence_status,
                    item.evidence_source,
                    item.provider_model_id,
                    item.execution_adapter,
                    item.capability_tags,
                )
                for item in tracked_models
            }
            authenticated, authentication_reason = self.adapter.authentication_ready(detection)
            prerequisites_ready = detection.status == "configured" and authenticated
            connectivity_verified = bool(
                model.evidence_source == "codex_connectivity_probe"
                and model.evidence_status == "verified"
                and model.availability_status == "available"
            )
            ready = prerequisites_ready and connectivity_verified
            provider.enabled = ready
            provider.status = "healthy" if ready else "unconfigured"
            provider.last_checked_at = utc_now()
            model.model_name = model_identifier
            model.display_name = model_identifier
            model.provider_model_id = model_identifier
            model.execution_adapter = "codex_cli"
            model.capability_tags = json.dumps(requested_capabilities, separators=(",", ":"))
            model.status = "healthy" if ready else "unconfigured"
            model.configuration_status = "configured"
            model.availability_status = "available" if ready else "unavailable"
            model.invocation_mode = "real"
            if model.evidence_status != "verified":
                model.evidence_status = "runtime_check" if ready else "unverified"
                model.evidence_source = "local_cli_readiness"
            model.safe_diagnostic = (
                "Codex CLI, authentication, Provider connectivity, and effective probe-model "
                "availability were verified by an explicit Owner connection probe."
                if ready
                else "Codex CLI and authentication prerequisites are available; Provider connectivity must be verified by the Owner."
                if prerequisites_ready
                else authentication_reason
                if detection.status == "configured"
                else detection.reason
            )
            session.flush()
            provider_changed = provider_before != (provider.enabled, provider.status)
            changed_model_ids = {
                item.id
                for item in tracked_models
                if model_before[item.id]
                != (
                    item.status,
                    item.configuration_status,
                    item.availability_status,
                    item.invocation_mode,
                    item.evidence_status,
                    item.evidence_source,
                    item.provider_model_id,
                    item.execution_adapter,
                    item.capability_tags,
                )
            }
            if provider_changed:
                changed_model_ids.update(item.id for item in tracked_models)
            self._invalidate_approved_model_assignments(
                session,
                changed_model_ids,
                reason="Local Codex readiness changed at runtime startup",
            )
            session.commit()

    def reconcile_observed_local_readiness(
        self,
        session: Session,
        detection: CodexDetection,
        *,
        authenticated: bool,
        authentication_reason: str,
    ) -> bool:
        """Persist an observed CLI/auth transition and invalidate bound approvals."""
        model_identifier = str(self.settings.codex_model_identifier or "").strip()
        ready = detection.status == "configured" and authenticated
        models = list(session.scalars(
            select(AIModel)
            .where(
                AIModel.execution_adapter == "codex_cli",
                AIModel.configuration_status != "disabled",
            )
            .order_by(AIModel.id)
        ).all())
        # A background CLI/authentication observation may downgrade a target,
        # but it must never promote one to Provider/model Ready. Promotion is
        # reserved for the explicit Owner-triggered connectivity probe.
        if ready:
            return False
        if not models:
            return False
        provider = models[0].provider
        provider_before = (provider.enabled, provider.status)
        model_before = {
            model.id: (
                model.status,
                model.configuration_status,
                model.availability_status,
                model.invocation_mode,
                model.evidence_status,
                model.evidence_source,
            )
            for model in models
        }
        provider.enabled = ready
        provider.status = "healthy" if ready else "unconfigured"
        provider.last_checked_at = utc_now()
        for model in models:
            model.status = "healthy" if ready else "unconfigured"
            model.configuration_status = "configured"
            model.availability_status = "available" if ready else "unavailable"
            model.invocation_mode = "real"
            if model.evidence_status != "verified":
                model.evidence_status = "runtime_check" if ready else "unverified"
                model.evidence_source = "local_cli_readiness"
            model.safe_diagnostic = (
                authentication_reason
                if detection.status == "configured"
                else detection.reason
            )
        model_after = {
            model.id: (
                model.status,
                model.configuration_status,
                model.availability_status,
                model.invocation_mode,
                model.evidence_status,
                model.evidence_source,
            )
            for model in models
        }
        provider_changed = provider_before != (provider.enabled, provider.status)
        state_changed = provider_changed or model_before != model_after
        if not state_changed:
            return False
        changed_model_ids = set(model_after)
        if provider_changed:
            changed_model_ids.update(item.id for item in provider.models)
        self._invalidate_approved_model_assignments(
            session,
            changed_model_ids,
            reason="Observed Local Codex CLI or authentication readiness changed",
        )
        session.add(
            AuditEvent(
                action="codex_runtime_readiness_reconciled",
                entity_type="provider",
                entity_id=provider.id,
                details=(
                    f"cli_status={detection.status}; authentication_ready={authenticated}; "
                    f"execution_state={'available' if ready else 'unavailable'}"
                ),
            )
        )
        return True

    @staticmethod
    def _sync_result_monitor(
        session: Session,
        run: CodexRun,
        *,
        actual_model_identifier: str | None = None,
        codex_session_identity: str | None = None,
    ) -> None:
        """Persist monitor progress without weakening ordinary Run finalization."""
        try:
            update_monitor_from_run(
                session,
                run,
                actual_model_identifier=actual_model_identifier,
                codex_session_identity=codex_session_identity,
            )
        except ResultIntakeError as exc:
            session.add(
                AuditEvent(
                    action="codex_run_monitor_update_blocked",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"code={exc.code}",
                )
            )

    def _bridge_phase_key(self, run_id: int, phase: str) -> str:
        return f"run-{run_id}-{phase}"

    def _existing_bridge_handle(
        self,
        run_id: int,
        phase: str,
    ) -> codex_exec_bridge.ExecutionHandle | None:
        key = (run_id, phase)
        cached = self._bridge_handles.get(key)
        if cached is not None:
            return cached
        ticket_path = (
            self._bridge_root
            / self._bridge_phase_key(run_id, phase)
            / "ticket.json"
        )
        if not ticket_path.exists() and not ticket_path.is_symlink():
            return None
        handle = codex_exec_bridge.handle_from_ticket_path(ticket_path)
        self._bridge_handles[key] = handle
        return handle

    def _bridge_preparation_status(self, run_id: int, phase: str) -> str:
        """Classify the local ticket/seal publication window without launching."""
        phase_directory = self._bridge_root / self._bridge_phase_key(run_id, phase)
        ticket_path = phase_directory / "ticket.json"
        seal_path = phase_directory / "ticket.seal.json"
        if not phase_directory.exists() and not phase_directory.is_symlink():
            return "absent"
        if ticket_path.exists() and seal_path.exists():
            # Full validation is intentionally delegated to the public bridge
            # loader; mere filenames are never a ready signal.
            codex_exec_bridge.handle_from_ticket_path(ticket_path)
            return "ready"
        try:
            newest_mtime = max(
                item.lstat().st_mtime
                for item in (phase_directory, ticket_path, seal_path)
                if item.exists() or item.is_symlink()
            )
        except (OSError, ValueError) as exc:
            raise codex_exec_bridge.CodexExecBridgeError(
                "BRIDGE_PREPARATION_STATE_INVALID",
                "The durable Codex preparation state could not be verified.",
            ) from exc
        if time.time() - newest_mtime <= BRIDGE_PREPARATION_GRACE_SECONDS:
            return "preparing"
        raise codex_exec_bridge.CodexExecBridgeError(
            "BRIDGE_PREPARATION_INCOMPLETE",
            "The durable Codex ticket preparation did not complete within its bounded window.",
        )

    def _bridge_phase_has_launch_evidence(self, run_id: int, phase: str) -> bool:
        try:
            if self._bridge_preparation_status(run_id, phase) != "ready":
                return False
            handle = self._existing_bridge_handle(run_id, phase)
            if handle is None:
                return False
            if codex_exec_bridge.load_terminal_receipt(handle) is not None:
                return True
            launch = codex_exec_bridge.load_launch_info(handle)
            # The validated immutable launch boundary is enough to prevent a
            # synthetic pre-launch failure. Recovery independently determines
            # whether that exact PID is live, terminal, or genuinely lost.
            return launch is not None
        except codex_exec_bridge.CodexExecBridgeError:
            # A malformed durable launch boundary must flow to recovery's
            # integrity blocker rather than being converted into exit=-1.
            return True

    def _validated_bridge_ticket(
        self,
        run: CodexRun,
        *,
        phase: str,
        worktree: Path,
    ) -> tuple[codex_exec_bridge.ExecutionHandle, dict[str, object]]:
        """Load an exact sealed phase ticket without recreating launch baselines."""
        handle = self._existing_bridge_handle(int(run.id), phase)
        if handle is None:
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_TICKET_UNAVAILABLE",
                "The durable Codex execution ticket is unavailable.",
            )
        ticket = codex_exec_bridge.load_ticket(handle)
        identity = ticket.get("identity")
        if (
            not isinstance(identity, dict)
            or run.pack is None
            or run.pack.approved_by_user_id is None
            or run.execution_assignment is None
            or run.verification_assignment is None
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_BINDING_INCOMPLETE",
                "The durable Codex recovery binding is incomplete.",
            )
        connectivity = (
            run.execution_connectivity_evidence
            if phase == "coding"
            else run.verification_connectivity_evidence
        )
        expected_connectivity = str(
            connectivity.evidence_digest if connectivity is not None else ""
        )
        requested_model = (
            run.requested_model_identifier
            if phase == "coding"
            else run.verification_model_identifier
        )
        expected_static: dict[str, object] = {
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
            "requested_model_identifier": requested_model,
        }
        if any(identity.get(key) != value for key, value in expected_static.items()):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_BINDING_MISMATCH",
                "The sealed Codex ticket does not match the persisted Run binding.",
            )
        try:
            ticket_worktree = Path(str(ticket.get("working_directory") or "")).resolve(
                strict=True
            )
            expected_worktree = worktree.resolve(strict=True)
        except OSError as exc:
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_WORKTREE_UNAVAILABLE",
                "The isolated recovery workspace is unavailable.",
            ) from exc
        boundary_keys = (
            "source_remote_fingerprint",
            "git_boundary_fingerprint",
            "workspace_snapshot_digest",
        )
        if (
            ticket.get("phase") != phase
            or ticket.get("phase_key") != self._bridge_phase_key(int(run.id), phase)
            or ticket_worktree != expected_worktree
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", str(identity.get(key) or ""))
                for key in boundary_keys
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
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_TICKET_INTEGRITY_BLOCKED",
                "The sealed Codex ticket failed its Run or boundary integrity check.",
            )
        return handle, ticket

    def _bridge_execution_identity(
        self,
        run: CodexRun,
        *,
        phase: str,
        worktree: Path,
        executable: str,
    ) -> codex_exec_bridge.ExecutionIdentity:
        if (
            run.pack is None
            or run.pack.approved_by_user_id is None
            or run.execution_assignment is None
            or run.verification_assignment is None
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RUN_BINDING_INCOMPLETE",
                "The exact Run binding is incomplete.",
            )
        connectivity = (
            run.execution_connectivity_evidence
            if phase == "coding"
            else run.verification_connectivity_evidence
        )
        connectivity_identity = str(
            connectivity.evidence_digest if connectivity is not None else ""
        )
        if not re.fullmatch(r"[0-9a-f]{64}", connectivity_identity):
            raise codex_exec_bridge.CodexExecBridgeError(
                "CONNECTIVITY_BINDING_INCOMPLETE",
                "The Owner-verified Codex connectivity binding is unavailable.",
            )
        requested_model = (
            run.requested_model_identifier
            if phase == "coding"
            else run.verification_model_identifier
        )
        execution_location_identity = hashlib.sha256(
            json.dumps(
                {
                    "run_id": run.id,
                    "phase": phase,
                    "worktree": str(worktree.resolve(strict=True)),
                    "source_commit": run.source_commit,
                    "source_snapshot": run.source_snapshot_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        source_remote_fingerprint, _, remote_complete = (
            self._remote_state_fingerprint(self.settings.source_repo)
        )
        git_boundary_fingerprint, git_boundary_complete = (
            self._git_boundary_fingerprint(self.settings.source_repo)
        )
        try:
            workspace_snapshot_digest = str(
                capture_source_snapshot(
                    worktree,
                    hardened_read_only=True,
                    approved_source_branch=run.source_branch,
                ).get("digest")
                or ""
            )
        except RuntimeError as exc:
            raise codex_exec_bridge.CodexExecBridgeError(
                "WORKSPACE_SNAPSHOT_UNAVAILABLE",
                "The pre-execution workspace snapshot could not be verified.",
            ) from exc
        if (
            not remote_complete
            or not git_boundary_complete
            or not re.fullmatch(r"[0-9a-f]{64}", source_remote_fingerprint)
            or not re.fullmatch(r"[0-9a-f]{64}", git_boundary_fingerprint)
            or not re.fullmatch(r"[0-9a-f]{64}", workspace_snapshot_digest)
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "EXECUTION_BOUNDARY_UNAVAILABLE",
                "The pre-execution Git or workspace boundary could not be verified.",
            )
        if phase == "coding" and workspace_snapshot_digest != run.source_snapshot_digest:
            raise codex_exec_bridge.CodexExecBridgeError(
                "CODING_WORKSPACE_BASELINE_MISMATCH",
                "The isolated Coding workspace does not match the approved source snapshot.",
            )
        return codex_exec_bridge.ExecutionIdentity(
            owner_id=int(run.pack.approved_by_user_id),
            run_id=int(run.id),
            task_id=int(run.task_id),
            task_version=int(run.task_version),
            pack_id=int(run.pack_id),
            pack_version=int(run.pack.version),
            coding_assignment_id=int(run.execution_assignment.id),
            coding_assignment_version=int(
                run.execution_assignment.assignment_version
            ),
            verification_assignment_id=int(run.verification_assignment.id),
            verification_assignment_version=int(
                run.verification_assignment.assignment_version
            ),
            routing_snapshot_identity=run.routing_snapshot_hash,
            source_snapshot_identity=run.source_snapshot_digest,
            connectivity_evidence_identity=connectivity_identity,
            requested_model_identifier=requested_model,
            executable_fingerprint=self._executable_identity_fingerprint(
                executable
            ),
            execution_location_identity=execution_location_identity,
            source_remote_fingerprint=source_remote_fingerprint,
            git_boundary_fingerprint=git_boundary_fingerprint,
            workspace_snapshot_digest=workspace_snapshot_digest,
            pre_verification_workspace_digest=(
                workspace_snapshot_digest if phase == "verification" else None
            ),
        )

    def _prepare_bridge_phase(
        self,
        run: CodexRun,
        *,
        phase: str,
        detection: CodexDetection,
        worktree: Path,
        prompt: str,
        model_identifier: str,
        sandbox_mode: str,
    ) -> codex_exec_bridge.ExecutionHandle:
        if not detection.executable:
            raise codex_exec_bridge.CodexExecBridgeError(
                "EXECUTABLE_UNAVAILABLE",
                "The exact Codex executable is unavailable.",
            )
        phase_key = self._bridge_phase_key(int(run.id), phase)
        # Bind Codex's sidecar to this exact immutable Run/phase attempt.  A
        # generic filename makes stale-artifact forensics needlessly
        # ambiguous even when the containing phase directory is unique.
        final_message_name = f"final-message-{phase_key}.txt"
        final_message_path = self._bridge_root / phase_key / final_message_name
        command = self.adapter.command_for(
            detection,
            prompt,
            model_identifier,
            sandbox_mode=sandbox_mode,
            output_last_message=final_message_path,
        )
        handle = codex_exec_bridge.prepare_execution(
            self._bridge_root,
            phase_key=phase_key,
            phase=phase,
            identity=self._bridge_execution_identity(
                run,
                phase=phase,
                worktree=worktree,
                executable=detection.executable,
            ),
            argv=command,
            stdin_payload=prompt.encode("utf-8"),
            working_directory=worktree,
            environment_keys=CHILD_ENV_ALLOWLIST,
            output_limit_bytes=max(0, int(self.settings.codex_output_limit)),
            timeout_seconds=max(1, int(self.settings.codex_timeout_seconds)),
            heartbeat_interval_seconds=min(
                1.0,
                max(0.05, float(self.settings.scheduler_poll_seconds)),
            ),
            final_message_relative_path=final_message_name,
            forbidden_spool_roots=(self.settings.source_repo,),
        )
        self._bridge_handles[(int(run.id), phase)] = handle
        return handle

    def _bind_bridge_child(
        self,
        run_id: int,
        *,
        phase: str,
        process_id: int,
        process_start_identity: str,
        executable: str,
        worktree: Path,
        terminal_receipt: dict[str, object] | None = None,
    ) -> None:
        if process_id <= 0 or not re.fullmatch(
            r"[0-9a-f]{64}", process_start_identity
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "PROCESS_IDENTITY_UNAVAILABLE",
                "The exact Codex child-process identity is unavailable.",
            )
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None:
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RUN_UNAVAILABLE",
                    "The persisted Codex Run is unavailable.",
                )
            monitor = ensure_run_monitor(
                session,
                int(run.pack.approved_by_user_id),
                run,
            )
            recorded_id = (
                monitor.process_id
                if phase == "coding"
                else monitor.verification_process_id
            )
            recorded_identity = (
                monitor.process_start_identity
                if phase == "coding"
                else monitor.verification_process_start_identity
            )
            if recorded_id is not None:
                if (
                    recorded_id != process_id
                    or recorded_identity != process_start_identity
                ):
                    raise codex_exec_bridge.CodexExecBridgeError(
                        "PROCESS_IDENTITY_MISMATCH",
                        "The durable Codex child-process identity conflicts with this Run.",
                    )
                return
            historical_receipt = terminal_receipt
            if (
                historical_receipt is None
                and monitor.monitor_state
                in {
                    "COMPLETED",
                    "FAILED",
                    "CANCELLED",
                    "TIMED_OUT",
                    "RESULT_PENDING",
                    "RESULT_AVAILABLE",
                    "RESULT_UNAVAILABLE",
                    "RESULT_INTEGRITY_BLOCKED",
                }
            ):
                # Close the receipt-publication TOCTOU window: the manager may
                # have read live state immediately before the watcher observed
                # and committed the newly sealed terminal receipt.
                late_handle = self._existing_bridge_handle(run_id, phase)
                if late_handle is not None:
                    historical_receipt = (
                        codex_exec_bridge.load_terminal_receipt(late_handle)
                    )
            if (
                historical_receipt is not None
                and self._bind_historical_phase_process(
                    session,
                    run,
                    monitor,
                    phase=phase,
                    process_id=process_id,
                    process_start_identity=process_start_identity,
                    worktree=worktree,
                    terminal_receipt=historical_receipt,
                )
            ):
                session.commit()
                return
            if phase == "coding":
                run.process_spawned = True
            else:
                run.verification_process_spawned = True
            record_monitor_process_start(
                session,
                run,
                process_id,
                executable,
                worktree,
                phase=phase,
                trusted_process_start_identity=process_start_identity,
            )
            session.add(
                AuditEvent(
                    action=(
                        "codex_exec_bridge_coding_started"
                        if phase == "coding"
                        else "codex_exec_bridge_verification_started"
                    ),
                    entity_type="codex_run",
                    entity_id=run_id,
                    details=(
                        "Exact shell-free codex exec child identity was bound to "
                        "the durable external spool."
                    ),
                )
            )
            session.commit()

    def _bind_historical_phase_process(
        self,
        session: Session,
        run: CodexRun,
        monitor: CodexRunMonitor,
        *,
        phase: str,
        process_id: int,
        process_start_identity: str,
        worktree: Path,
        terminal_receipt: dict[str, object],
    ) -> bool:
        """Bind an exact exited child without regressing terminal monitor state.

        A very fast phase can publish its sealed terminal receipt before the
        in-process manager commits ``record_monitor_process_start``.  The
        result watcher may then persist the exact execution attempt and move
        the monitor to RESULT_PENDING.  Replaying the ordinary RUNNING or
        VERIFYING transition at that point is invalid, but losing the already
        proven child identity is equally wrong.

        This path is intentionally unavailable unless the sealed ticket and
        receipt validate against this Run and a persisted attempt already
        binds the same phase, PID, start identity, ticket, and receipt.  It
        changes only the missing monitor identity fields; monitor lifecycle
        state and result evidence remain untouched.
        """

        handle, _ticket = self._validated_bridge_ticket(
            run,
            phase=phase,
            worktree=worktree,
        )
        sealed_receipt = codex_exec_bridge.load_terminal_receipt(handle)
        if sealed_receipt is None or sealed_receipt != terminal_receipt:
            raise ResultIntakeError(
                "SEALED_RECEIPT_IDENTITY_MISMATCH",
                "The terminal Codex receipt does not match this phase binding.",
            )
        receipt_digest = canonical_sha256(sealed_receipt)
        attempt = session.scalar(
            select(CodexExecutionAttempt).where(
                CodexExecutionAttempt.owner_id == monitor.owner_id,
                CodexExecutionAttempt.run_id == run.id,
                CodexExecutionAttempt.monitor_id == monitor.id,
                CodexExecutionAttempt.phase == phase.upper(),
                CodexExecutionAttempt.attempt_number == 1,
            )
        )
        if attempt is None:
            return False
        receipt_process_id = sealed_receipt.get("child_process_id")
        receipt_process_identity = sealed_receipt.get(
            "child_process_start_identity"
        )
        exact_attempt = bool(
            attempt.ticket_digest == handle.ticket_digest
            and re.fullmatch(r"[0-9a-f]{64}", attempt.ticket_digest or "")
            and attempt.receipt_digest == receipt_digest
            and re.fullmatch(r"[0-9a-f]{64}", attempt.receipt_digest or "")
            and attempt.process_id == process_id == receipt_process_id
            and attempt.process_start_identity
            == process_start_identity
            == receipt_process_identity
            and re.fullmatch(
                r"[0-9a-f]{64}", attempt.process_start_identity or ""
            )
            and attempt.process_exit_known
            and attempt.terminal_event_observed
            and attempt.attempt_state
            in {
                "SETTLING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "RESULT_UNAVAILABLE",
                "RESULT_INTEGRITY_BLOCKED",
                "VERIFICATION_ELIGIBLE",
            }
        )
        if not exact_attempt:
            raise ResultIntakeError(
                "SEALED_ATTEMPT_PROCESS_IDENTITY_MISMATCH",
                "The terminal Codex process does not match its sealed execution attempt.",
            )
        if phase == "coding":
            recorded_id = monitor.process_id
            recorded_identity = monitor.process_start_identity
        else:
            recorded_id = monitor.verification_process_id
            recorded_identity = monitor.verification_process_start_identity
        if recorded_id is not None or recorded_identity:
            if (
                recorded_id != process_id
                or recorded_identity != process_start_identity
            ):
                raise ResultIntakeError(
                    "PROCESS_IDENTITY_MISMATCH",
                    f"The {phase.title()} process does not match this Run monitor.",
                )
            return True
        if phase == "coding":
            monitor.process_id = process_id
            monitor.process_start_identity = process_start_identity
            run.process_spawned = True
        else:
            monitor.verification_process_id = process_id
            monitor.verification_process_start_identity = process_start_identity
            run.verification_process_spawned = True
        session.add(
            AuditEvent(
                actor_user_id=monitor.owner_id,
                action="codex_run_monitor_terminal_process_bound",
                entity_type="codex_run_monitor",
                entity_id=monitor.id,
                details=(
                    f"run={run.id}; phase={phase}; "
                    "sealed_attempt_identity_verified=true; state_preserved=true"
                ),
            )
        )
        return True

    def _run_bridge_phase(
        self,
        run_id: int,
        *,
        phase: str,
        detection: CodexDetection,
        worktree: Path,
        prompt: str,
        model_identifier: str,
        sandbox_mode: str,
    ) -> dict[str, object]:
        if not detection.executable:
            raise codex_exec_bridge.CodexExecBridgeError(
                "EXECUTABLE_UNAVAILABLE",
                "The exact Codex executable is unavailable.",
            )
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None or run.pack is None or run.pack.approved_by_user_id is None:
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RUN_UNAVAILABLE",
                    "The persisted Codex Run is unavailable.",
                )
            handle = self._existing_bridge_handle(run_id, phase)
            ticket: dict[str, object]
            if handle is None:
                handle = self._prepare_bridge_phase(
                    run,
                    phase=phase,
                    detection=detection,
                    worktree=worktree,
                    prompt=prompt,
                    model_identifier=model_identifier,
                    sandbox_mode=sandbox_mode,
                )
                ticket = codex_exec_bridge.load_ticket(handle)
            else:
                handle, ticket = self._validated_bridge_ticket(
                    run,
                    phase=phase,
                    worktree=worktree,
                )
            monitor = ensure_run_monitor(
                session,
                int(run.pack.approved_by_user_id),
                run,
            )
            if not monitor.protected_result_locator:
                observe_monitor(
                    session,
                    monitor,
                    result_path=str(self._bridge_root),
                    result_source="codex_exec_jsonl_spool",
                    safe_summary=(
                        "Coding is monitored by the durable Codex Exec Bridge."
                        if phase == "coding"
                        else "Independent Verification is monitored by the durable Codex Exec Bridge."
                    ),
                )
            elif monitor.protected_result_locator != str(self._bridge_root):
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RESULT_LOCATOR_MISMATCH",
                    "The durable Codex spool conflicts with this Run monitor.",
                )
            session.commit()

        with self._lock:
            if self._stopping:
                raise _BridgeRuntimeHandoff()
            if run_id in self._cancel_requested and codex_exec_bridge.load_terminal_receipt(
                handle
            ) is None:
                # An Owner cancellation before this phase crosses its detached
                # launch boundary must not create a process merely to cancel it.
                raise _BridgeRuntimeHandoff()
            launch = codex_exec_bridge.launch_sidecar(
                handle,
                python_executable=sys.executable,
                child_environment=self._child_environment(),
            )
        deadline = time.monotonic() + max(
            30.0,
            float(self.settings.codex_timeout_seconds) + 30.0,
        )
        bound_child: tuple[int, str] | None = None
        receipt: dict[str, object] | None = None
        while receipt is None:
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            state = codex_exec_bridge.load_execution_state(handle)
            if isinstance(state, dict):
                child_pid = state.get("child_process_id")
                child_identity = state.get("child_process_start_identity")
                if (
                    type(child_pid) is int
                    and child_pid > 0
                    and isinstance(child_identity, str)
                    and re.fullmatch(r"[0-9a-f]{64}", child_identity)
                    and bound_child != (child_pid, child_identity)
                ):
                    self._bind_bridge_child(
                        run_id,
                        phase=phase,
                        process_id=child_pid,
                        process_start_identity=child_identity,
                        executable=detection.executable,
                        worktree=worktree,
                        terminal_receipt=receipt,
                    )
                    bound_child = (child_pid, child_identity)
            if receipt is not None:
                break
            stop_reason = self._stop_reason(run_id)
            if stop_reason == "runtime_shutdown":
                # The detached sidecar owns the exact process and output
                # pipes. Application shutdown abandons only this waiter; it
                # must not publish an Owner cancellation or stop Codex.
                raise _BridgeRuntimeHandoff()
            if stop_reason == "owner_cancelled":
                codex_exec_bridge.request_cancel(handle)
            if not codex_exec_bridge.process_identity_matches(
                launch.process_id,
                launch.process_start_identity,
            ):
                receipt = codex_exec_bridge.load_terminal_receipt(handle)
                if receipt is None:
                    raise codex_exec_bridge.CodexExecBridgeError(
                        "SIDECAR_PROCESS_LOST",
                        "The durable Codex Exec Bridge process was lost before terminal evidence.",
                    )
                break
            if time.monotonic() >= deadline:
                raise codex_exec_bridge.CodexExecBridgeError(
                    "TERMINAL_RECEIPT_UNAVAILABLE",
                    "The Codex Exec Bridge did not publish terminal evidence after its bounded timeout.",
                )
            time.sleep(0.05)

        assert receipt is not None
        child_pid = receipt.get("child_process_id")
        child_identity = receipt.get("child_process_start_identity")
        if (
            type(child_pid) is int
            and child_pid > 0
            and isinstance(child_identity, str)
            and re.fullmatch(r"[0-9a-f]{64}", child_identity)
        ):
            self._bind_bridge_child(
                run_id,
                phase=phase,
                process_id=child_pid,
                process_start_identity=child_identity,
                executable=detection.executable,
                worktree=worktree,
                terminal_receipt=receipt,
            )
            bound_child = (child_pid, child_identity)

        collector = _CodexJsonlEvidenceCollector(model_identifier)
        ticket_identity = ticket.get("identity")
        collector.executable_identity_fingerprint = str(
            ticket_identity.get("executable_fingerprint")
            if isinstance(ticket_identity, dict)
            else ""
        )
        if bound_child is not None:
            collector.process_id_fingerprint = hashlib.sha256(
                (
                    f"{phase}:{run_id}:{bound_child[0]}:{bound_child[1]}"
                ).encode("utf-8")
            ).hexdigest()
        replay = codex_exec_bridge.replay_stdout_to_collector(handle, collector)
        stdout_bytes = codex_exec_bridge.load_stream_bytes(handle, stream="stdout")
        stderr_bytes = codex_exec_bridge.load_stream_bytes(handle, stream="stderr")
        stdout = self._sanitize_process_output(
            stdout_bytes.decode("utf-8", errors="replace")
        )
        stderr = self._sanitize_process_output(
            stderr_bytes.decode("utf-8", errors="replace")
        )
        stdout_binding = receipt.get("stdout")
        stderr_binding = receipt.get("stderr")
        retained_stdout_truncated = bool(
            isinstance(stdout_binding, dict)
            and stdout_binding.get("truncated") is True
        )
        retained_stderr_truncated = bool(
            isinstance(stderr_binding, dict)
            and stderr_binding.get("truncated") is True
        )
        stdout, stderr, presentation_truncated = self._rebudget_sanitized_outputs(
            stdout,
            stderr,
            already_truncated=(
                retained_stdout_truncated or retained_stderr_truncated
            ),
            marker_on_stdout=(
                retained_stdout_truncated or not retained_stderr_truncated
            ),
        )
        final_message = codex_exec_bridge.load_final_message(handle)
        jsonl_final_message_recovered = False
        if final_message is None:
            try:
                recovery_candidate = (
                    codex_exec_bridge.load_jsonl_final_message_candidate(handle)
                )
            except codex_exec_bridge.CodexExecBridgeError:
                recovery_candidate = None
            if isinstance(recovery_candidate, str) and recovery_candidate.strip():
                if phase == "verification":
                    try:
                        recovered_contract = json.loads(recovery_candidate)
                    except json.JSONDecodeError:
                        recovered_contract = None
                    if (
                        isinstance(recovered_contract, dict)
                        and recovered_contract.get("schema") == "twos.verification.v1"
                        and recovered_contract.get("verdict") in {"pass", "fail"}
                    ):
                        final_message = recovery_candidate
                        jsonl_final_message_recovered = True
                else:
                    # Transport identity proves the exact Run and turn; the
                    # content must independently satisfy the bounded Coding
                    # handoff schema before a missing sidecar can be recovered.
                    if _valid_coding_handoff_contract(recovery_candidate):
                        final_message = recovery_candidate
                        jsonl_final_message_recovered = True
        # The bridge proves transport identity and semantic agreement between
        # JSONL and the sidecar.  It deliberately supports both JSON and text,
        # so the phase adapter must still enforce the approved structured
        # Coding handoff contract before independent Verification can start.
        coding_contract_invalid = bool(
            phase == "coding"
            and final_message is not None
            and not _valid_coding_handoff_contract(final_message)
        )
        if final_message is not None:
            collector.final_agent_message = _bounded_event_text(
                final_message.strip(),
                maximum=2000,
            )
            if phase == "verification":
                try:
                    recovered_verdict = json.loads(final_message)
                except json.JSONDecodeError:
                    recovered_verdict = None
                if (
                    isinstance(recovered_verdict, dict)
                    and recovered_verdict.get("schema") == "twos.verification.v1"
                ):
                    collector.verification_result = recovered_verdict
        terminal_state = str(receipt.get("terminal_state") or "")
        outcome_facts = receipt.get("outcome_facts")
        outcome_facts = outcome_facts if isinstance(outcome_facts, dict) else {}
        final_message_mismatch = bool(
            (
                terminal_state == "RESULT_INTEGRITY_BLOCKED"
                and not jsonl_final_message_recovered
            )
            or coding_contract_invalid
        )
        if final_message_mismatch:
            collector.mark_incomplete()
        stdin_delivery = receipt.get("stdin_delivery")
        retention_truncated = bool(
            retained_stdout_truncated
            or retained_stderr_truncated
            or presentation_truncated
        )
        return {
            "handle": handle,
            "receipt": receipt,
            "collector": collector,
            "process_spawned": bound_child is not None,
            "process_id": bound_child[0] if bound_child else None,
            "process_start_identity": bound_child[1] if bound_child else "",
            "exit_code": receipt.get("process_exit_code"),
            "timed_out": bool(
                outcome_facts.get("timed_out") is True
                or terminal_state == "TIMED_OUT"
            ),
            "cancelled": bool(
                outcome_facts.get("cancelled") is True
                or terminal_state == "CANCELLED"
            ),
            "runtime_interrupted": False,
            "integrity_blocked": bool(
                (
                    terminal_state == "RESULT_INTEGRITY_BLOCKED"
                    and not jsonl_final_message_recovered
                )
                or coding_contract_invalid
            ),
            "stdout": stdout,
            "stderr": stderr,
            "delivery_complete": bool(
                isinstance(stdin_delivery, dict)
                and stdin_delivery.get("complete") is True
            ),
            "retention_truncated": retention_truncated,
            "terminal_event_replayed": replay.terminal_event_replayed,
            "final_message": final_message,
            "final_message_mismatch": final_message_mismatch,
            "final_message_contract_invalid": coding_contract_invalid,
            "jsonl_final_message_recovered": jsonl_final_message_recovered,
        }

    def _recovery_worktree(self, run: CodexRun) -> Path:
        if not run.worktree_path:
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_WORKTREE_UNAVAILABLE",
                "The persisted isolated Codex workspace is unavailable.",
            )
        try:
            worktree = Path(run.worktree_path).resolve(strict=True)
            authorized_root = self.settings.worktree_root.resolve(strict=True)
        except OSError as exc:
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_WORKTREE_UNAVAILABLE",
                "The persisted isolated Codex workspace is unavailable.",
            ) from exc
        if not worktree.is_dir() or not worktree.is_relative_to(authorized_root):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_WORKTREE_OUTSIDE_ROOT",
                "The persisted isolated workspace is outside the authorized root.",
            )
        return worktree

    @staticmethod
    def _detection_from_bridge_ticket(
        ticket: dict[str, object],
    ) -> CodexDetection:
        argv = ticket.get("argv")
        identity = ticket.get("identity")
        if (
            not isinstance(argv, list)
            or not argv
            or not isinstance(argv[0], str)
            or not argv[0]
            or not isinstance(identity, dict)
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(identity.get("executable_fingerprint") or ""),
            )
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_EXECUTABLE_BINDING_INVALID",
                "The sealed Codex executable binding is invalid.",
            )
        return CodexDetection(
            status="configured",
            found=True,
            executable=argv[0],
            version=None,
            supported_command="exec",
            reason="Recovered from the sealed Codex execution ticket.",
            next_action="Continue monitoring the exact detached execution.",
        )

    def _bridge_recovery_observation(
        self,
        run: CodexRun,
        worktree: Path,
    ) -> dict[str, object]:
        """Classify sealed recovery evidence without launching any process."""
        coding_preparation = self._bridge_preparation_status(int(run.id), "coding")
        if coding_preparation == "preparing":
            return {
                "status": "preparing",
                "phase": "coding",
                "code": "BRIDGE_PREPARATION_PENDING",
            }
        if coding_preparation != "ready":
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_TICKET_UNAVAILABLE",
                "The durable Codex execution ticket is unavailable.",
            )
        coding_handle, coding_ticket = self._validated_bridge_ticket(
            run,
            phase="coding",
            worktree=worktree,
        )
        coding_receipt = codex_exec_bridge.load_terminal_receipt(coding_handle)
        verification_preparation = self._bridge_preparation_status(
            int(run.id),
            "verification",
        )
        if verification_preparation == "preparing":
            return {
                "status": "preparing",
                "phase": "verification",
                "code": "BRIDGE_PREPARATION_PENDING",
            }
        verification_handle = (
            self._existing_bridge_handle(int(run.id), "verification")
            if verification_preparation == "ready"
            else None
        )
        if verification_handle is None and run.verification_process_spawned:
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_VERIFICATION_TICKET_UNAVAILABLE",
                "Verification was previously spawned but its sealed ticket is unavailable.",
            )
        phase = "coding"
        handle = coding_handle
        ticket = coding_ticket
        receipt = coding_receipt
        if verification_handle is not None:
            if (
                coding_receipt is None
                or coding_receipt.get("terminal_state") != "COMPLETED"
            ):
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RECOVERY_PHASE_ORDER_INVALID",
                    "Verification evidence exists without successful terminal Coding evidence.",
                )
            handle, ticket = self._validated_bridge_ticket(
                run,
                phase="verification",
                worktree=worktree,
            )
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            phase = "verification"
        if receipt is not None:
            terminal_state = str(receipt.get("terminal_state") or "")
            if terminal_state not in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "RESULT_INTEGRITY_BLOCKED",
            }:
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RECOVERY_TERMINAL_STATE_INVALID",
                    "The sealed Codex terminal state is invalid.",
                )
            return {
                "status": (
                    "terminal"
                ),
                "phase": phase,
                "handle": handle,
                "ticket": ticket,
                "receipt": receipt,
            }
        try:
            state = codex_exec_bridge.load_execution_state(handle)
        except codex_exec_bridge.CodexExecBridgeError:
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            if receipt is not None:
                return {
                    "status": "terminal",
                    "phase": phase,
                    "handle": handle,
                    "ticket": ticket,
                    "receipt": receipt,
                }
            raise
        if not isinstance(state, dict):
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            if receipt is not None:
                return {
                    "status": "terminal",
                    "phase": phase,
                    "handle": handle,
                    "ticket": ticket,
                    "receipt": receipt,
                }
            try:
                launch = codex_exec_bridge.load_launch_info(handle)
            except codex_exec_bridge.CodexExecBridgeError:
                receipt = codex_exec_bridge.load_terminal_receipt(handle)
                if receipt is not None:
                    return {
                        "status": "terminal",
                        "phase": phase,
                        "handle": handle,
                        "ticket": ticket,
                        "receipt": receipt,
                    }
                raise
            if (
                launch is not None
                and codex_exec_bridge.process_identity_matches(
                    launch.process_id,
                    launch.process_start_identity,
                )
            ):
                return {
                    "status": "starting",
                    "phase": phase,
                    "handle": handle,
                    "ticket": ticket,
                    "launch": launch,
                }
            # Close the launch-exit/terminal-publication race one final time.
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            if receipt is not None:
                return {
                    "status": "terminal",
                    "phase": phase,
                    "handle": handle,
                    "ticket": ticket,
                    "receipt": receipt,
                }
            return {
                "status": "process_lost",
                "phase": phase,
                "code": (
                    "BRIDGE_LAUNCH_IDENTITY_LOST"
                    if launch is not None
                    else "BRIDGE_LAUNCH_UNAVAILABLE"
                ),
            }
        sidecar_pid = state.get("sidecar_process_id")
        sidecar_identity = state.get("sidecar_process_start_identity")
        if not (
            type(sidecar_pid) is int
            and isinstance(sidecar_identity, str)
            and codex_exec_bridge.process_identity_matches(
                sidecar_pid,
                sidecar_identity,
            )
        ):
            # One last immutable receipt read closes the child-exit/receipt
            # publication race without trusting the now-absent PID.
            receipt = codex_exec_bridge.load_terminal_receipt(handle)
            if receipt is not None:
                return {
                    "status": (
                        "terminal"
                    ),
                    "phase": phase,
                    "handle": handle,
                    "ticket": ticket,
                    "receipt": receipt,
                }
            return {
                "status": "process_lost",
                "phase": phase,
                "code": "BRIDGE_PROCESS_IDENTITY_LOST",
            }
        child_pid = state.get("child_process_id")
        child_identity = state.get("child_process_start_identity")
        if type(child_pid) is int and child_pid > 0 and not (
            isinstance(child_identity, str)
            and re.fullmatch(r"[0-9a-f]{64}", child_identity)
        ):
            raise codex_exec_bridge.CodexExecBridgeError(
                "RECOVERY_CHILD_IDENTITY_INVALID",
                "The sealed Codex child-process identity is invalid.",
            )
        return {
            "status": "active",
            "phase": phase,
            "handle": handle,
            "ticket": ticket,
            "state": state,
        }

    def _mark_bridge_integrity_blocked(
        self,
        run_id: int,
        *,
        code: str,
        summary: str,
    ) -> None:
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None or run.status not in {
                "queued",
                "starting",
                "running",
                "verifying",
            }:
                return
            run.status = "blocked"
            run.finished_at = utc_now()
            run.owner_summary = summary
            run.task.status = "needs_review"
            monitor = ensure_run_monitor(
                session,
                int(run.pack.approved_by_user_id),
                run,
            )
            observe_monitor(
                session,
                monitor,
                state="RESULT_INTEGRITY_BLOCKED",
                recovery_state="INTEGRITY_BLOCKED",
                failure_code=code,
                safe_summary=summary,
            )
            session.add(
                AuditEvent(
                    action="codex_exec_bridge_integrity_blocked",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"code={code}; replacement_process_started=false",
                )
            )
            session.commit()

    def _preserve_bridge_worker_failure(
        self,
        run_id: int,
        *,
        recovery_worker: bool,
        failure_type: str,
    ) -> str:
        """Protect a detached execution from generic worker-failure handling.

        Returns ``retry`` only when a normal worker failed after an immutable
        terminal receipt became available.  Recovery workers never loop.
        """
        try:
            with self.factory() as session:
                run = session.get(CodexRun, run_id)
                if (
                    run is None
                    or run.status
                    not in {"queued", "starting", "running", "verifying", "settling"}
                    or self._existing_bridge_handle(run_id, "coding") is None
                ):
                    return "none"
                worktree = self._recovery_worktree(run)
                observation = self._bridge_recovery_observation(run, worktree)
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                status = str(observation.get("status") or "")
                if status in {"starting", "active"}:
                    clear_stale_monitor_terminal_state(
                        session,
                        monitor,
                        reason="exact_bridge_worker_handoff",
                    )
                    observe_monitor(
                        session,
                        monitor,
                        state=(
                            "VERIFYING"
                            if observation.get("phase") == "verification"
                            else (
                                "STARTING"
                                if status == "starting"
                                else "RUNNING"
                            )
                        ),
                        recovery_state="MONITORING_RESUMED",
                        failure_code="",
                        safe_summary=(
                            "The detached Codex execution remains live; TWOS will "
                            "recover its sealed evidence without replacing it."
                        ),
                    )
                elif status == "terminal":
                    observe_monitor(
                        session,
                        monitor,
                        recovery_state="RESULT_RECOVERED",
                        failure_code="",
                        safe_summary=(
                            "A sealed terminal Codex receipt remains available for "
                            "idempotent recovery."
                        ),
                    )
                elif status == "preparing":
                    clear_stale_monitor_terminal_state(
                        session,
                        monitor,
                        reason="sealed_bridge_worker_handoff_pending",
                    )
                    observe_monitor(
                        session,
                        monitor,
                        state=(
                            "VERIFYING"
                            if observation.get("phase") == "verification"
                            else "STARTING"
                        ),
                        recovery_state="NONE",
                        failure_code="",
                        safe_summary=(
                            "The sealed Codex execution boundary is still being "
                            "published; no replacement process was started."
                        ),
                    )
                else:
                    run.status = "failed"
                    run.finished_at = utc_now()
                    run.owner_summary = (
                        "The exact detached Codex process identity was lost; no "
                        "replacement process was launched."
                    )
                    run.task.status = "needs_review"
                    observe_monitor(
                        session,
                        monitor,
                        state="PROCESS_LOST",
                        recovery_state="PROCESS_LOST",
                        failure_code=str(
                            observation.get("code")
                            or "BRIDGE_PROCESS_IDENTITY_LOST"
                        ),
                        safe_summary=run.owner_summary,
                    )
                session.add(
                    AuditEvent(
                        action="codex_exec_bridge_worker_handoff",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details=(
                            f"failure_type={failure_type}; bridge_status={status}; "
                            "replacement_process_started=false"
                        ),
                    )
                )
                session.commit()
                if status == "terminal" and not recovery_worker:
                    return "retry"
                return "preserved"
        except Exception as exc:
            self._mark_bridge_integrity_blocked(
                run_id,
                code=(
                    exc.code
                    if isinstance(exc, codex_exec_bridge.CodexExecBridgeError)
                    else "BRIDGE_RECOVERY_READ_FAILED"
                ),
                summary="Durable Codex recovery evidence could not be verified safely.",
            )
            return "preserved"

    def _terminalize_legacy_interrupted_run(
        self,
        session: Session,
        run: CodexRun,
        monitor: CodexRunMonitor,
    ) -> None:
        """Preserve the Vol.17 restart boundary for Runs without bridge data."""
        spawned = bool(run.process_spawned or run.verification_process_spawned)
        run.status = "failed" if spawned else "blocked"
        run.owner_summary = (
            "Server restarted after the Codex process was spawned; its final outcome requires review."
            if spawned
            else (
                "Server restarted inside the durable Codex launch window; process start cannot be proven "
                "and no invocation is claimed."
                if run.launch_intent_at is not None
                else "Server restarted before the durable Codex launch boundary; no invocation is claimed."
            )
        )
        run.finished_at = utc_now()
        run.task.status = "needs_review"
        observe_monitor(
            session,
            monitor,
            state=("PROCESS_LOST" if spawned else "RESULT_UNAVAILABLE"),
            recovery_state=("PROCESS_LOST" if spawned else "RESULT_UNAVAILABLE"),
            failure_code=(
                "LEGACY_PROCESS_OUTCOME_UNAVAILABLE"
                if spawned
                else "PROCESS_NOT_STARTED"
            ),
            safe_summary=run.owner_summary,
        )
        if spawned:
            try:
                with session.begin_nested():
                    self._record_incomplete_spawn_evidence(
                        session,
                        run,
                        diagnostic_code="runtime_restart",
                        safe_summary=(
                            "Runtime restart interrupted final Codex evidence collection."
                        ),
                    )
            except Exception as exc:
                session.add(
                    AuditEvent(
                        action="model_invocation_evidence_persistence_failed",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details=(
                            f"failure_type={type(exc).__name__}; "
                            "context=runtime_restart"
                        ),
                    )
                )
        session.add(
            AuditEvent(
                action="codex_run_recovered",
                entity_type="codex_run",
                entity_id=run.id,
                details=(
                    f"Legacy interrupted process state terminalized as {run.status}; "
                    "replacement_process_started=false."
                ),
            )
        )

    def recover_interrupted_runs(self) -> None:
        """Resume exact bridge waiters or terminal finalizers without rerunning."""
        with self.factory() as session:
            run_ids = list(
                session.scalars(
                    select(CodexRun.id).where(
                        CodexRun.status.in_(["queued", "starting", "running", "verifying", "settling"])
                    )
                ).all()
            )
        recoverable: list[int] = []
        for run_id in run_ids:
            with self.factory() as session:
                run = session.get(CodexRun, run_id)
                if run is None or run.status not in {
                    "queued",
                    "starting",
                    "running",
                    "verifying",
                    "settling",
                }:
                    continue
                if run.pack is None or run.pack.approved_by_user_id is None:
                    continue
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                try:
                    if self._bridge_preparation_status(int(run.id), "coding") == "absent":
                        self._terminalize_legacy_interrupted_run(
                            session,
                            run,
                            monitor,
                        )
                        session.commit()
                        continue
                    worktree = self._recovery_worktree(run)
                    observation = self._bridge_recovery_observation(run, worktree)
                except codex_exec_bridge.CodexExecBridgeError as exc:
                    if (
                        exc.code == "RECOVERY_TICKET_UNAVAILABLE"
                        and not run.process_spawned
                        and not run.verification_process_spawned
                        and run.launch_intent_at is None
                    ):
                        run.status = "blocked"
                        run.finished_at = utc_now()
                        run.owner_summary = (
                            "Runtime restarted before a durable Codex process identity "
                            "was established; no invocation is claimed."
                        )
                        run.task.status = "blocked"
                        observe_monitor(
                            session,
                            monitor,
                            state="RESULT_UNAVAILABLE",
                            recovery_state="RESULT_UNAVAILABLE",
                            failure_code="PROCESS_NOT_STARTED",
                            safe_summary=run.owner_summary,
                        )
                    else:
                        run.status = "blocked"
                        run.finished_at = utc_now()
                        run.owner_summary = (
                            "Durable Codex recovery evidence failed its integrity checks."
                        )
                        run.task.status = "needs_review"
                        observe_monitor(
                            session,
                            monitor,
                            state="RESULT_INTEGRITY_BLOCKED",
                            recovery_state="INTEGRITY_BLOCKED",
                            failure_code=exc.code,
                            safe_summary=exc.safe_message,
                        )
                    session.add(
                        AuditEvent(
                            action="codex_run_recovery_blocked",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=f"code={exc.code}; replacement_process_started=false",
                        )
                    )
                    session.commit()
                    continue

                recovery_status = str(observation.get("status") or "")
                if recovery_status == "preparing":
                    clear_stale_monitor_terminal_state(
                        session,
                        monitor,
                        reason="sealed_bridge_preparation_pending",
                    )
                    observe_monitor(
                        session,
                        monitor,
                        state=(
                            "VERIFYING"
                            if observation.get("phase") == "verification"
                            else "STARTING"
                        ),
                        recovery_state="NONE",
                        failure_code="",
                        safe_summary=(
                            "The durable Codex launch boundary is still being prepared; "
                            "no replacement process was started."
                        ),
                    )
                    session.add(
                        AuditEvent(
                            action="codex_run_bridge_preparation_pending",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=(
                                f"phase={observation.get('phase')}; "
                                "replacement_process_started=false"
                            ),
                        )
                    )
                    session.commit()
                    continue
                if recovery_status in {"starting", "active", "terminal"}:
                    if recovery_status in {"starting", "active"}:
                        clear_stale_monitor_terminal_state(
                            session,
                            monitor,
                            reason="exact_bridge_process_resumed",
                        )
                    observe_monitor(
                        session,
                        monitor,
                        state=(
                            "RESULT_PENDING"
                            if recovery_status == "terminal"
                            else (
                                "VERIFYING"
                                if observation.get("phase") == "verification"
                                else "STARTING"
                            )
                            if recovery_status == "starting"
                            else {
                                "queued": "QUEUED",
                                "starting": "STARTING",
                                "running": "RUNNING",
                                "verifying": "VERIFYING",
                            }.get(run.status, monitor.monitor_state)
                        ),
                        recovery_state=(
                            "MONITORING_RESUMED"
                            if recovery_status in {"starting", "active"}
                            else "RESULT_RECOVERED"
                        ),
                        failure_code="",
                        safe_summary=(
                            "Monitoring resumed from the exact sealed detached-process identity."
                            if recovery_status in {"starting", "active"}
                            else "A sealed terminal Codex receipt was recovered for durable finalization."
                        ),
                    )
                    session.add(
                        AuditEvent(
                            action=(
                                "codex_run_monitoring_resumed"
                                if recovery_status in {"starting", "active"}
                                else "codex_run_terminal_receipt_recovered"
                            ),
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=(
                                f"phase={observation.get('phase')}; "
                                "replacement_process_started=false"
                            ),
                        )
                    )
                    session.commit()
                    recoverable.append(int(run.id))
                    continue
                run.status = "failed"
                run.owner_summary = (
                    "The exact detached Codex process identity was lost before "
                    "terminal evidence became available. No replacement process was launched."
                )
                observe_monitor(
                    session,
                    monitor,
                    state="PROCESS_LOST",
                    recovery_state="PROCESS_LOST",
                    failure_code=str(
                        observation.get("code")
                        or "BRIDGE_PROCESS_IDENTITY_LOST"
                    ),
                    safe_summary=run.owner_summary,
                )
                run.finished_at = utc_now()
                monitor.terminal_at = monitor.terminal_at or run.finished_at
                monitor.last_observed_at = utc_now()
                run.task.status = "needs_review"
                if run.process_spawned or run.verification_process_spawned:
                    try:
                        with session.begin_nested():
                            self._record_incomplete_spawn_evidence(
                                session,
                                run,
                                diagnostic_code="process_lost",
                                safe_summary=(
                                    "Runtime recovery could not safely finalize the exact "
                                    "persisted Codex execution evidence."
                                ),
                            )
                    except Exception as exc:
                        session.add(
                            AuditEvent(
                                action="model_invocation_evidence_persistence_failed",
                                entity_type="codex_run",
                                entity_id=run.id,
                                details=(
                                    f"failure_type={type(exc).__name__}; "
                                    "context=runtime_restart"
                                ),
                            )
                        )
                session.add(
                    AuditEvent(
                        action="codex_run_recovered",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details=(
                            f"Interrupted state reconciled as {monitor.monitor_state}; "
                            "replacement_process_started=false."
                        ),
                    )
                )
                session.commit()
        for run_id in recoverable:
            self._start_worker(run_id, recover_bridge=True)
        try:
            reconcile_run_monitors(self.factory)
        except (ResultIntakeError, OSError):
            # Startup remains available with the persisted truthful monitor
            # blocker; reconciliation is retried by the bounded watcher.
            pass

    @staticmethod
    def _attach_verification_result(
        result: dict[str, object],
        verification: dict[str, object] | None,
    ) -> None:
        if verification is None:
            result["verification"] = {
                "status": "not_started",
                "summary": (
                    "Verification was not started because Coding did not reach "
                    "the verification boundary."
                ),
                "process_spawned": False,
            }
            result["verification_process"] = {
                "status": "not_started",
                "process_started": False,
                "failure": "Coding did not reach the Verification boundary.",
            }
            result["verification_invocation"] = {
                "process_execution_verified": False,
                "codex_turn_verified": False,
                "requested_model": "",
                "actual_resolved_model": None,
                "actual_model_identity_verified": False,
                "failure": "Verification was not started.",
            }
            result["verification_verdict"] = {
                "status": "not_reached",
                "passed_checks": [],
                "failed_checks": [],
            }
            return
        result["verification"] = {
            key: value
            for key, value in verification.items()
            if key
            not in {
                "collector",
                "prompt",
                "delivery_complete",
                "_started_at",
                "_completed_at",
            }
        }
        result["verification_process"] = dict(verification.get("process", {}))
        result["verification_invocation"] = dict(
            verification.get("invocation", {})
        )
        result["verification_verdict"] = dict(verification.get("verdict", {}))

    @staticmethod
    def _reconcile_recovered_task_acceptance(
        result: dict[str, object],
    ) -> None:
        task_acceptance = result.get("task_acceptance")
        if not (
            isinstance(task_acceptance, dict)
            and task_acceptance.get("status") == "needs_owner_review"
        ):
            return
        verification_verdict = result.get("verification_verdict")
        verdict_status = (
            verification_verdict.get("status")
            if isinstance(verification_verdict, dict)
            else "not_reached"
        )
        if verdict_status == "passed":
            task_acceptance["status"] = "passed"
            task_acceptance["reason"] = (
                "Independent Verification passed the frozen task checks."
            )
        elif verdict_status == "failed":
            failed_checks = verification_verdict.get("failed_checks", [])
            task_acceptance["status"] = "failed"
            task_acceptance["reason"] = (
                "Independent Verification rejected the output"
                + (
                    f": {', '.join(str(item) for item in failed_checks)}"
                    if failed_checks
                    else "."
                )
            )
        else:
            task_acceptance["reason"] = (
                "Independent Verification did not reach a structured task verdict."
            )

    def _finalize_recovered_bridge_run(
        self,
        run_id: int,
        *,
        result: dict[str, object],
        coding_bridge: dict[str, object],
        coding_collector: _CodexJsonlEvidenceCollector | None,
        pack_content: str,
        verification: dict[str, object] | None,
        coding_integrity_blocked: bool = False,
    ) -> None:
        stdout = str(coding_bridge.get("stdout") or "")
        stderr = str(coding_bridge.get("stderr") or "")
        exit_code = coding_bridge.get("exit_code")
        timed_out = bool(coding_bridge.get("timed_out"))
        cancelled = bool(coding_bridge.get("cancelled"))
        output_truncated = bool(coding_bridge.get("retention_truncated"))
        pack_delivery_complete = bool(coding_bridge.get("delivery_complete"))
        coding_receipt = coding_bridge.get("receipt")
        coding_duration = (
            int(coding_receipt.get("duration_ms") or 0)
            if isinstance(coding_receipt, dict)
            else 0
        )
        verification_duration = (
            int(verification.get("duration_ms") or 0)
            if isinstance(verification, dict)
            else 0
        )
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None:
                return
            run.stdout = stdout
            run.stderr = stderr
            run.output_truncated = output_truncated
            run.exit_code = exit_code if type(exit_code) is int else None
            run.duration_ms = max(
                int(run.duration_ms or 0),
                coding_duration + verification_duration,
            )
            run.timed_out = timed_out
            run.cancelled = cancelled
            run.structured_result = json.dumps(result, separators=(",", ":"))
            run.finished_at = utc_now()
            if verification is not None:
                run.verification_status = str(verification["status"])
                run.verification_summary = str(verification["summary"])
                run.verification_process_spawned = bool(
                    verification["process_spawned"]
                )
                run.verification_stdout = str(verification["stdout"])
                run.verification_stderr = str(verification["stderr"])
                verification_exit = verification.get("exit_code")
                run.verification_exit_code = (
                    verification_exit if type(verification_exit) is int else None
                )
                run.verification_duration_ms = int(
                    verification.get("duration_ms") or 0
                )
                run.verification_timed_out = bool(verification["timed_out"])
                run.verification_cancelled = bool(verification["cancelled"])
                run.verification_output_truncated = bool(
                    verification["output_truncated"]
                )
            else:
                run.verification_status = "not_started"
                run.verification_summary = str(
                    result["verification"]["summary"]  # type: ignore[index]
                )
            coding_process = result.get("coding_process")
            git_evidence = result.get("git_evidence")
            task_acceptance = result.get("task_acceptance")
            verification_verdict = result.get("verification_verdict")
            if cancelled:
                run.status = "cancelled"
                run.owner_summary = "Codex execution was cancelled by the Owner."
                run.task.status = "cancelled"
            elif timed_out:
                run.status = "timed_out"
                run.owner_summary = "Codex execution exceeded the configured timeout."
                run.task.status = "needs_review"
            elif coding_integrity_blocked:
                run.status = "blocked"
                run.owner_summary = (
                    "The detached Coding result failed its sealed result integrity checks."
                )
                run.task.status = "needs_review"
            elif type(exit_code) is not int or exit_code != 0:
                run.status = "failed"
                run.owner_summary = str(
                    coding_process.get("failure")
                    if isinstance(coding_process, dict)
                    else "Codex process failed; review is required."
                )
                run.task.status = "needs_review"
            elif not isinstance(git_evidence, dict) or git_evidence.get("status") != "passed":
                run.status = "failed"
                run.owner_summary = (
                    "Git evidence collection or validation failed; inspect Advanced diagnostics."
                )
                run.task.status = "needs_review"
            elif not self._boundary_evidence_passes(result):
                run.status = "failed"
                run.owner_summary = (
                    "Codex exited successfully, but isolation or no-commit/no-push evidence failed."
                )
                run.task.status = "needs_review"
            elif verification is None:
                run.status = "failed"
                run.owner_summary = (
                    "Coding finished, but independent Verification did not start."
                )
                run.task.status = "needs_review"
            elif verification.get("integrity_blocked"):
                run.status = "blocked"
                run.owner_summary = (
                    "Independent Verification failed its sealed result integrity checks."
                )
                run.task.status = "needs_review"
            elif verification.get("cancelled"):
                run.status = "cancelled"
                run.owner_summary = (
                    "Independent Verification was cancelled by the Owner."
                )
                run.task.status = "cancelled"
            elif verification.get("timed_out"):
                run.status = "timed_out"
                run.owner_summary = (
                    "Independent Verification exceeded the configured timeout."
                )
                run.task.status = "needs_review"
            elif verification.get("status") != "completed":
                run.status = "failed"
                run.owner_summary = str(
                    verification.get("failure")
                    or "Independent Verification process failed; review is required."
                )
                run.task.status = "needs_review"
            elif (
                not isinstance(verification_verdict, dict)
                or verification_verdict.get("status") != "passed"
            ):
                run.status = "failed"
                failed_checks = (
                    verification_verdict.get("failed_checks", [])
                    if isinstance(verification_verdict, dict)
                    else []
                )
                run.owner_summary = "Independent Verification verdict failed" + (
                    f": {', '.join(str(item) for item in failed_checks)}."
                    if failed_checks
                    else "."
                )
                run.task.status = "needs_review"
            elif not isinstance(task_acceptance, dict) or task_acceptance.get("status") != "passed":
                run.status = "failed"
                run.owner_summary = str(
                    task_acceptance.get("reason")
                    if isinstance(task_acceptance, dict)
                    else "The frozen Development task acceptance result requires review."
                )
                run.task.status = "needs_review"
            else:
                run.status = "completed"
                run.owner_summary = (
                    "Coding and independent Verification completed in an isolated worktree."
                )
                run.task.status = "result_ready"

            invocation_verified: bool | None = None
            if run.process_spawned:
                try:
                    with session.begin_nested():
                        invocation_verified = self._record_codex_invocation_evidence(
                            session,
                            run,
                            coding_collector,
                            result,
                            pack_content,
                            False,
                            pack_delivery_complete,
                        )
                except Exception as exc:
                    invocation_verified = False
                    session.add(
                        AuditEvent(
                            action="model_invocation_evidence_persistence_failed",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=(
                                f"failure_type={type(exc).__name__}; "
                                "context=bridge_recovery_finalization"
                            ),
                        )
                    )
            verification_verified: bool | None = None
            if verification is not None and run.verification_process_spawned:
                try:
                    with session.begin_nested():
                        verification_verified = (
                            self._record_verification_invocation_evidence(
                                session,
                                run,
                                verification,
                            )
                        )
                except Exception as exc:
                    verification_verified = False
                    session.add(
                        AuditEvent(
                            action="verification_invocation_evidence_persistence_failed",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=(
                                f"failure_type={type(exc).__name__}; "
                                "context=bridge_recovery_finalization"
                            ),
                        )
                    )
            if run.status == "completed" and (
                invocation_verified is False or verification_verified is False
            ):
                run.status = "failed"
                run.owner_summary = (
                    "Recovered process evidence could not be persisted as a verified invocation."
                )
                run.task.status = "needs_review"
            create_owner_acceptance(session, run.task, run)
            if run.status != "completed":
                run.task.status = (
                    "needs_review"
                    if run.status in {"failed", "timed_out"}
                    else run.status
                )
            session.add(
                AuditEvent(
                    action="codex_run_recovery_finalized",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=(
                        f"status={run.status}; exit_code={run.exit_code}; "
                        f"changed_files={len(result.get('changed_files', []))}; "
                        "replacement_process_started=false"
                    ),
                )
            )
            self._sync_result_monitor(
                session,
                run,
                actual_model_identifier=(
                    coding_collector.actual_model_identifier
                    if coding_collector
                    and coding_collector.actual_model_identity_verified
                    else None
                ),
                codex_session_identity=(
                    coding_collector.thread_id_fingerprint
                    if coding_collector
                    and coding_collector.thread_id_fingerprint
                    else None
                ),
            )
            if coding_integrity_blocked or (
                verification is not None and verification.get("integrity_blocked")
            ):
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_INTEGRITY_BLOCKED",
                    recovery_state="INTEGRITY_BLOCKED",
                    failure_code="BRIDGE_RESULT_INTEGRITY_BLOCKED",
                    safe_summary=run.owner_summary,
                )
            session.commit()
            if coding_integrity_blocked or (
                verification is not None and verification.get("integrity_blocked")
            ):
                # The Run finalization transaction is committed before taking
                # the per-Run reconciliation lock, avoiding a SQLite
                # writer/lock inversion with the independent monitor thread.
                # The following transaction atomically projects attempt,
                # snapshot, notification and Verification eligibility.
                from .run_lifecycle import reconcile_execution_attempt

                reconcile_execution_attempt(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                    monitor,
                )
                session.commit()

    def _recover_bridge_run(self, run_id: int) -> None:
        """Replay one sealed Coding receipt and continue its normal finalizer."""
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None or not self._bridge_recovery_allowed(run):
                return
            worktree = self._recovery_worktree(run)
            _, coding_ticket = self._validated_bridge_ticket(
                run,
                phase="coding",
                worktree=worktree,
            )
            coding_identity = coding_ticket.get("identity")
            if not isinstance(coding_identity, dict):
                raise codex_exec_bridge.CodexExecBridgeError(
                    "RECOVERY_TICKET_INTEGRITY_BLOCKED",
                    "The sealed Coding identity is unavailable.",
                )
            detection = self._detection_from_bridge_ticket(coding_ticket)
            pack_content = run.pack.content
            coding_model = run.requested_model_identifier

        coding_bridge = self._run_bridge_phase(
            run_id,
            phase="coding",
            detection=detection,
            worktree=worktree,
            prompt=pack_content,
            model_identifier=coding_model,
            sandbox_mode="workspace-write",
        )
        coding_integrity_blocked = bool(coding_bridge.get("integrity_blocked"))
        coding_collector = coding_bridge.get("collector")
        if not isinstance(coding_collector, _CodexJsonlEvidenceCollector):
            coding_collector = None
        exit_code = coding_bridge.get("exit_code")
        timed_out = bool(coding_bridge.get("timed_out"))
        cancelled = bool(coding_bridge.get("cancelled"))
        output_truncated = bool(coding_bridge.get("retention_truncated"))
        delivery_complete = bool(coding_bridge.get("delivery_complete"))
        if (
            coding_collector is not None
            and coding_collector.structured_success
            and exit_code == 0
            and not timed_out
            and not cancelled
            and not output_truncated
            and delivery_complete
            and not coding_integrity_blocked
        ):
            self._bind_owner_verified_model_identity(
                run_id,
                coding_collector,
                capability="coding",
            )
        elif coding_collector is not None:
            coding_collector.clear_verified_model_identity()
        result = self._derive_result(
            worktree,
            run_id,
            str(coding_bridge.get("stdout") or ""),
            str(coding_bridge.get("stderr") or ""),
            exit_code if type(exit_code) is int else None,
            timed_out,
            cancelled,
            False,
            (
                str(coding_identity.get("source_remote_fingerprint") or ""),
                0,
                True,
            ),
            coding_collector,
            delivery_complete,
        )
        result["exec_bridge"] = {
            "transport": "codex exec --json",
            "presentation_evidence_truncated": output_truncated,
            "transport_consumption_completed": bool(
                coding_collector and not coding_collector.collection_incomplete
            ),
            "recovered_from_sealed_receipt": True,
            "integrity_state": (
                "blocked" if coding_integrity_blocked else "verified"
            ),
            "integrity_blocker": (
                "FINAL_RESULT_SCHEMA_INVALID"
                if coding_bridge.get("final_message_contract_invalid") is True
                else "BRIDGE_RESULT_INTEGRITY_BLOCKED"
                if coding_integrity_blocked
                else ""
            ),
        }
        if self._stop_reason(run_id) == "runtime_shutdown":
            raise _BridgeRuntimeHandoff()
        with self.factory() as transition_session:
            transition_run = transition_session.get(CodexRun, run_id)
            owner_cancelled = bool(
                self._stop_reason(run_id) == "owner_cancelled"
                or (
                    transition_run is not None
                    and (
                        transition_run.cancelled
                        or transition_run.status == "cancelled"
                    )
                )
            )
        coding_process = result.get("coding_process")
        git_evidence = result.get("git_evidence")
        coding_ready = bool(
            coding_bridge.get("process_spawned")
            and exit_code == 0
            and coding_collector is not None
            and coding_collector.structured_success
            and delivery_complete
            and isinstance(coding_process, dict)
            and coding_process.get("status") == "completed"
            and isinstance(git_evidence, dict)
            and git_evidence.get("status") == "passed"
            and self._boundary_evidence_passes(result)
            and not owner_cancelled
            and not timed_out
            and not coding_integrity_blocked
        )
        verification: dict[str, object] | None = None
        if coding_ready:
            with self.factory() as transition_session:
                transition_run = transition_session.get(CodexRun, run_id)
                if transition_run is None:
                    return
                transition_run.stdout = str(coding_bridge.get("stdout") or "")
                transition_run.stderr = str(coding_bridge.get("stderr") or "")
                transition_run.output_truncated = output_truncated
                transition_run.exit_code = (
                    exit_code if type(exit_code) is int else None
                )
                transition_run.structured_result = json.dumps(
                    result,
                    separators=(",", ":"),
                )
                transition_run.status = "verifying"
                transition_run.owner_summary = (
                    "Recovered terminal Coding evidence; independent Verification is continuing."
                )
                transition_run.verification_status = "starting"
                transition_run.verification_summary = (
                    "Independent Verification is preparing."
                )
                transition_run.task.status = "verifying"
                self._sync_result_monitor(transition_session, transition_run)
                transition_session.commit()
            if self._existing_bridge_handle(run_id, "verification") is not None:
                with self.factory() as verification_session:
                    verification_run = verification_session.get(CodexRun, run_id)
                    if verification_run is None:
                        return
                    _, verification_ticket = self._validated_bridge_ticket(
                        verification_run,
                        phase="verification",
                        worktree=worktree,
                    )
                verification_detection = self._detection_from_bridge_ticket(
                    verification_ticket
                )
            else:
                verification_detection = self.adapter.detect()
            verification = self._execute_verification(
                run_id,
                worktree,
                verification_detection,
                pack_content,
                result,
            )
        self._attach_verification_result(result, verification)
        self._reconcile_recovered_task_acceptance(result)
        self._finalize_recovered_bridge_run(
            run_id,
            result=result,
            coding_bridge=coding_bridge,
            coding_collector=coding_collector,
            pack_content=pack_content,
            verification=verification,
            coding_integrity_blocked=coding_integrity_blocked,
        )

    def start(self, run_id: int) -> bool:
        return self._start_worker(run_id, recover_bridge=False)

    def resume_persisted_execution(self, run_id: int) -> bool:
        """Attach one finalizer to an existing sealed bridge attempt.

        This callback is used by the durable result watcher after it commits
        its observation.  It never creates a replacement Coding process: the
        recovery worker validates the existing ticket, PID/start identity and
        receipt before it can continue settlement.
        """

        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if (
                run is None
                or not self._bridge_recovery_allowed(run)
                or self._existing_bridge_handle(run_id, "coding") is None
            ):
                return False
        return self._start_worker(run_id, recover_bridge=True)

    def _bridge_recovery_allowed(self, run: CodexRun) -> bool:
        if run.status in {"queued", "starting", "running", "verifying"}:
            return True
        if run.status not in {"settling", "blocked"} or run.stdout or run.stderr:
            return False
        try:
            handle = self._existing_bridge_handle(int(run.id), "coding")
            receipt = (
                codex_exec_bridge.load_terminal_receipt(handle)
                if handle is not None
                else None
            )
        except codex_exec_bridge.CodexExecBridgeError:
            return False
        return bool(
            isinstance(receipt, dict)
            and receipt.get("terminal_state")
            in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                "RESULT_INTEGRITY_BLOCKED",
            }
        )

    def _start_worker(self, run_id: int, *, recover_bridge: bool) -> bool:
        thread = threading.Thread(
            target=self._run_worker,
            args=(run_id, recover_bridge),
            daemon=True,
            name=(
                f"twos-codex-recovery-{run_id}"
                if recover_bridge
                else f"twos-codex-{run_id}"
            ),
        )
        with self._lock:
            if self._stopping or run_id in self._workers:
                return False
            self._workers[run_id] = thread
        thread.start()
        return True

    def _run_worker(self, run_id: int, recover_bridge: bool = False) -> None:
        retry_recovery = False
        try:
            if recover_bridge:
                self._recover_bridge_run(run_id)
            else:
                self._execute(run_id)
        except _BridgeRuntimeHandoff:
            # Durable ticket/state/receipt evidence remains owned by the
            # detached sidecar and will be reconciled by the next runtime.
            pass
        except Exception as exc:
            bridge_action = self._preserve_bridge_worker_failure(
                run_id,
                recovery_worker=recover_bridge,
                failure_type=type(exc).__name__,
            )
            if bridge_action == "none":
                self._mark_worker_failure(run_id, type(exc).__name__)
            elif bridge_action == "retry":
                retry_recovery = True
        finally:
            with self._lock:
                self._workers.pop(run_id, None)
                self._processes.pop(run_id, None)
                self._cancel_requested.discard(run_id)
        if retry_recovery:
            self._start_worker(run_id, recover_bridge=True)

    def cancel(self, run_id: int) -> bool:
        with self._lock:
            process = self._processes.get(run_id)
            if process is not None:
                if process.poll() is not None:
                    return False
                self._cancel_requested.add(run_id)
            else:
                self._cancel_requested.add(run_id)
        for phase in ("verification", "coding"):
            try:
                handle = self._existing_bridge_handle(run_id, phase)
                if (
                    handle is not None
                    and codex_exec_bridge.load_terminal_receipt(handle) is None
                ):
                    codex_exec_bridge.request_cancel(handle)
                    return True
            except codex_exec_bridge.CodexExecBridgeError:
                # Preserve the exact persisted blocker for the worker; never
                # fall back to signalling an unverified PID.
                return False
        if process is not None:
            self._stop_process_tree(process, force=False)
            return True
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run or run.status not in {"queued", "starting", "running", "verifying"}:
                with self._lock:
                    self._cancel_requested.discard(run_id)
                return False
            if run.process_spawned:
                verification_handle = self._existing_bridge_handle(
                    run_id,
                    "verification",
                )
                coding_handle = self._existing_bridge_handle(run_id, "coding")
                coding_receipt = (
                    codex_exec_bridge.load_terminal_receipt(coding_handle)
                    if coding_handle is not None
                    else None
                )
                if (
                    not run.verification_process_spawned
                    and verification_handle is None
                    and isinstance(coding_receipt, dict)
                    and coding_receipt.get("terminal_state") == "COMPLETED"
                ):
                    # Coding is terminal but the separate Verification process
                    # has not crossed its launch boundary. Persist this narrow
                    # Owner cancellation window and let the worker retain the
                    # completed Coding evidence without starting Verification.
                    run.status = "cancelled"
                    run.cancelled = True
                    run.finished_at = utc_now()
                    run.task.status = "cancelled"
                    session.add(
                        AuditEvent(
                            action="codex_run_cancelled_before_verification",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=(
                                "Owner cancelled after Coding terminal evidence and "
                                "before independent Verification launch."
                            ),
                        )
                    )
                    session.commit()
                    return True
                # A terminal phase is already owned by the finalizer. A late
                # cancel must not overwrite captured process evidence.
                with self._lock:
                    self._cancel_requested.discard(run_id)
                return False
            run.status = "cancelled"
            run.cancelled = True
            run.finished_at = utc_now()
            run.task.status = "cancelled"
            session.add(
                AuditEvent(
                    action="codex_run_cancelled",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Owner cancelled Codex execution.",
                )
            )
            session.commit()
        return True

    def _record_launch_intent(self, run_id: int) -> bool:
        """Persist the last pre-spawn checkpoint before any child can exist."""
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if (
                run is None
                or run.status != "running"
                or run.process_spawned
                or self._is_cancel_requested(run_id)
            ):
                return False
            run.launch_intent_at = utc_now()
            session.add(
                AuditEvent(
                    action="codex_run_launch_intent_recorded",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Durable launch intent recorded before the shell-free Codex spawn boundary.",
                )
            )
            session.commit()
        return True

    def shutdown(self) -> None:
        """Stop legacy children; detached bridge executions survive restart."""
        with self._lock:
            self._stopping = True
            processes = list(self._processes.values())
            workers = list(self._workers.values())
        for process in processes:
            if process.poll() is None:
                self._stop_process_tree(process, force=False)
        deadline = time.monotonic() + 2.0
        for process in processes:
            if process.poll() is not None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                self._stop_process_tree(process, force=True)
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))

    def _discard_snapshot_blocked_worktree(
        self,
        worktree: Path,
        branch: str,
    ) -> tuple[bool, str]:
        """Best-effort cleanup with a safe, persistable verification result."""

        try:
            return self.adapter.discard_unstarted_worktree(worktree, branch)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return False, f"CLEANUP_OPERATION_{type(exc).__name__.upper()}"

    def _execute(self, run_id: int) -> None:
        started_monotonic = time.monotonic()
        detection = self.adapter.detect()
        worktree: Path | None = None
        branch = ""
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            if run.status == "cancelled" or self._is_cancel_requested(run_id):
                self._finish_cancelled(session, run)
                return
            run.status = "starting"
            run.owner_summary = "The approved source snapshot is being prepared."
            run.task.status = "starting"
            session.add(
                AuditEvent(
                    action="codex_run_starting",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Accepted Run is preparing its approved isolated source snapshot.",
                )
            )
            self._sync_result_monitor(session, run)
            session.commit()
            run.executable_status = detection.status
            if detection.status != "configured":
                self.reconcile_observed_local_readiness(
                    session,
                    detection,
                    authenticated=False,
                    authentication_reason=(
                        "Codex authentication could not be checked because CLI readiness failed."
                    ),
                )
                self._finish_pack_blocked(session, run, reason=detection.reason)
                return
            authenticated, authentication_reason = self.adapter.authentication_ready(detection)
            if not authenticated:
                run.executable_status = "needs_setup"
                self.reconcile_observed_local_readiness(
                    session,
                    detection,
                    authenticated=False,
                    authentication_reason=authentication_reason,
                )
                self._finish_pack_blocked(session, run, reason=authentication_reason)
                return
            try:
                codex_run_execution_target(
                    session,
                    run,
                    self.settings.source_repo,
                    codex_executable=detection.executable,
                    child_environment=self._child_environment(),
                )
            except ValueError as exc:
                self._finish_pack_blocked(session, run, reason=str(exc))
                return
            try:
                self.adapter.validate_source_identity(
                    expected_repo=run.source_repo,
                    expected_branch=run.source_branch,
                    expected_commit=run.source_commit,
                )
                if (
                    run.pack.source_snapshot_digest
                    != run.source_snapshot_digest
                ):
                    raise RuntimeError(
                        "Source snapshot does not match the approved Pack and Run binding."
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                self._finish_source_snapshot_unavailable(
                    session,
                    run,
                    diagnostic=str(exc),
                )
                return
            try:
                worktree, branch = self.adapter.create_worktree(run.id, run.source_commit)
            except Exception as exc:
                run.status = "blocked"
                run.owner_summary = (
                    "The isolated Codex worktree could not be created. "
                    "Inspect Advanced for diagnostics."
                )
                run.stderr = self._sanitize_process_output(str(exc)[:2000])
                run.finished_at = utc_now()
                run.verification_status = "not_started"
                run.verification_summary = "Verification was not started because workspace creation was blocked."
                run.task.status = "blocked"
                session.add(
                    AuditEvent(
                        action="codex_run_blocked",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details="Isolated Codex worktree creation failed.",
                    )
                )
                session.commit()
                return
            assert worktree is not None
            try:
                source_snapshot = json.loads(run.pack.source_snapshot_json or "{}")
                hydrate_source_snapshot(
                    worktree,
                    source_snapshot,
                    approved_digest=run.source_snapshot_digest,
                    approved_source_branch=run.source_branch,
                )
            except Exception as exc:
                cleanup_verified, cleanup_code = (
                    self._discard_snapshot_blocked_worktree(worktree, branch)
                )
                worktree = None
                branch = ""
                self._finish_source_snapshot_unavailable(
                    session,
                    run,
                    diagnostic=str(exc),
                    cleanup_verified=cleanup_verified,
                    cleanup_code=cleanup_code,
                )
                return
            session.refresh(run)
            if run.status == "cancelled" or self._is_cancel_requested(run_id):
                self.adapter.discard_unstarted_worktree(worktree, branch)
                self._finish_cancelled(session, run)
                return
            session.refresh(run.pack)
            try:
                self.adapter.validate_source_identity(
                    expected_repo=run.source_repo,
                    expected_branch=run.source_branch,
                    expected_commit=run.source_commit,
                )
                if (
                    run.pack.source_snapshot_digest
                    != run.source_snapshot_digest
                ):
                    raise RuntimeError(
                        "Source snapshot does not match the approved Pack and Run binding."
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                cleanup_verified, cleanup_code = (
                    self._discard_snapshot_blocked_worktree(worktree, branch)
                )
                self._finish_source_snapshot_unavailable(
                    session,
                    run,
                    diagnostic=str(exc),
                    cleanup_verified=cleanup_verified,
                    cleanup_code=cleanup_code,
                )
                return
            try:
                codex_run_execution_target(
                    session,
                    run,
                    self.settings.source_repo,
                    codex_executable=detection.executable,
                    child_environment=self._child_environment(),
                )
            except ValueError as exc:
                self.adapter.discard_unstarted_worktree(worktree, branch)
                self._finish_pack_blocked(session, run, reason=str(exc))
                return
            run.worktree_path = str(worktree)
            run.worktree_branch = branch
            run.status = "running"
            run.owner_summary = "Coding invocation is running in the isolated workspace."
            run.started_at = utc_now()
            run.task.status = "running"
            session.add(
                AuditEvent(
                    action="codex_run_started",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"Isolated branch {branch} started.",
                )
            )
            self._sync_result_monitor(session, run)
            session.commit()

        if not self._record_launch_intent(run_id):
            self.adapter.discard_unstarted_worktree(worktree, branch)
            with self.factory() as stopped_session:
                stopped_run = stopped_session.get(CodexRun, run_id)
                if stopped_run is not None and stopped_run.status in {"queued", "starting", "running"}:
                    self._finish_cancelled(stopped_session, stopped_run)
            return

        stdout = ""
        stderr = ""
        exit_code: int | None = None
        timed_out = False
        cancelled = False
        runtime_interrupted = False
        integrity_blocked = False
        output_truncated = False
        process_spawned = False
        presentation_output_truncated = False
        evidence_collector: _CodexJsonlEvidenceCollector | None = None
        pack_content = ""
        remote_state_before: tuple[str, int, bool] | None = None
        try:
            # Serialize the final approval check with SQLite writers so a task
            # edit cannot invalidate the pack between this check and spawn.
            with self.factory() as launch_session:
                if launch_session.get_bind().dialect.name == "sqlite":
                    launch_session.execute(text("BEGIN IMMEDIATE"))
                launch_run = launch_session.get(CodexRun, run_id)
                if not launch_run:
                    return
                launch_session.refresh(launch_run.pack)
                try:
                    execution_target = codex_run_execution_target(
                        launch_session,
                        launch_run,
                        self.settings.source_repo,
                        codex_executable=detection.executable,
                        child_environment=self._child_environment(),
                    )
                except ValueError as exc:
                    self.adapter.discard_unstarted_worktree(worktree, branch)
                    launch_run.worktree_path = ""
                    launch_run.worktree_branch = ""
                    self._finish_pack_blocked(launch_session, launch_run, reason=str(exc))
                    return
                authenticated, authentication_reason = self.adapter.authentication_ready(detection)
                if not authenticated:
                    self.reconcile_observed_local_readiness(
                        launch_session,
                        detection,
                        authenticated=False,
                        authentication_reason=authentication_reason,
                    )
                    self.adapter.discard_unstarted_worktree(worktree, branch)
                    launch_run.worktree_path = ""
                    launch_run.worktree_branch = ""
                    self._finish_pack_blocked(
                        launch_session,
                        launch_run,
                        reason=authentication_reason,
                    )
                    return
                pack_content = launch_run.pack.content
                remote_state_before = self._remote_state_fingerprint(self.settings.source_repo)
                if not remote_state_before[2]:
                    self.adapter.discard_unstarted_worktree(worktree, branch)
                    launch_run.worktree_path = ""
                    launch_run.worktree_branch = ""
                    self._finish_pack_blocked(
                        launch_session,
                        launch_run,
                        reason="Git remote boundary state could not be verified before process launch.",
                    )
                    return
                with self._lock:
                    if self._stopping or run_id in self._cancel_requested or launch_run.status == "cancelled":
                        self.adapter.discard_unstarted_worktree(worktree, branch)
                        launch_run.worktree_path = ""
                        launch_run.worktree_branch = ""
                        self._finish_cancelled(launch_session, launch_run)
                        return
                launch_session.commit()
            bridge_result = self._run_bridge_phase(
                run_id,
                phase="coding",
                detection=detection,
                worktree=worktree,
                prompt=pack_content,
                model_identifier=execution_target.requested_model_identifier,
                sandbox_mode="workspace-write",
            )
            evidence_collector = bridge_result["collector"]  # type: ignore[assignment]
            process_spawned = bool(bridge_result["process_spawned"])
            exit_code = bridge_result["exit_code"]  # type: ignore[assignment]
            timed_out = bool(bridge_result["timed_out"])
            cancelled = bool(bridge_result["cancelled"])
            runtime_interrupted = bool(bridge_result["runtime_interrupted"])
            integrity_blocked = bool(bridge_result.get("integrity_blocked"))
            stdout = str(bridge_result["stdout"])
            stderr = str(bridge_result["stderr"])
            pack_delivery_complete = bool(bridge_result["delivery_complete"])
            presentation_output_truncated = bool(
                bridge_result["retention_truncated"]
            )
            # Retained stdout/stderr truncation is the legacy process-output
            # boundary persisted on the Run. Collector event-count summaries
            # remain separate and do not by themselves set this flag.
            output_truncated = presentation_output_truncated
        except (OSError, codex_exec_bridge.CodexExecBridgeError) as exc:
            if self._bridge_phase_has_launch_evidence(run_id, "coding"):
                # A known live sidecar or immutable terminal receipt owns the
                # real exit/output truth. Let worker recovery re-read it;
                # never replace it with a synthetic -1 exit.
                raise
            # The bridge ticket may be sealed before sidecar Popen. Without a
            # validated launch record or receipt this is still the pre-spawn
            # boundary: discard the isolated worktree, invalidate approval,
            # and make no process/exit/model-invocation claim.
            self.adapter.discard_unstarted_worktree(worktree, branch)
            with self.factory() as blocked_session:
                blocked_run = blocked_session.get(CodexRun, run_id)
                if blocked_run is not None and not blocked_run.process_spawned:
                    blocked_run.worktree_path = ""
                    blocked_run.worktree_branch = ""
                    self._finish_pack_blocked(
                        blocked_session,
                        blocked_run,
                        reason=str(exc),
                    )
            return
        if (
            evidence_collector is not None
            and evidence_collector.structured_success
            and exit_code == 0
            and not timed_out
            and not cancelled
            and not runtime_interrupted
            and not output_truncated
            and pack_delivery_complete
        ):
            self._bind_owner_verified_model_identity(
                run_id,
                evidence_collector,
                capability="coding",
            )
        elif evidence_collector is not None:
            evidence_collector.clear_verified_model_identity()
        result = self._derive_result(
            worktree,
            run_id,
            stdout,
            stderr,
            exit_code,
            timed_out,
            cancelled,
            runtime_interrupted,
            remote_state_before,
            evidence_collector,
            pack_delivery_complete,
        )
        verification: dict[str, object] | None = None
        result["exec_bridge"] = {
            "transport": "codex exec --json",
            "presentation_evidence_truncated": presentation_output_truncated,
            "transport_consumption_completed": bool(
                evidence_collector and not evidence_collector.collection_incomplete
            ),
            "integrity_state": "blocked" if integrity_blocked else "verified",
            "integrity_blocker": (
                "FINAL_RESULT_SCHEMA_INVALID"
                if bridge_result.get("final_message_contract_invalid") is True
                else "BRIDGE_RESULT_INTEGRITY_BLOCKED"
                if integrity_blocked
                else ""
            ),
        }
        if self._stop_reason(run_id) == "runtime_shutdown":
            raise _BridgeRuntimeHandoff()
        with self.factory() as transition_session:
            transition_run = transition_session.get(CodexRun, run_id)
            owner_cancelled_before_verification = bool(
                self._stop_reason(run_id) == "owner_cancelled"
                or (
                    transition_run is not None
                    and (
                        transition_run.cancelled
                        or transition_run.status == "cancelled"
                    )
                )
            )
        if owner_cancelled_before_verification:
            cancelled = True
        coding_process_for_gate = result.get("coding_process")
        git_evidence_for_gate = result.get("git_evidence")
        coding_ready_for_verification = bool(
            process_spawned
            and exit_code == 0
            and evidence_collector is not None
            and evidence_collector.structured_success
            and not evidence_collector.unsupported_model_routing_observed
            and pack_delivery_complete
            and isinstance(coding_process_for_gate, dict)
            and coding_process_for_gate.get("status") == "completed"
            and isinstance(git_evidence_for_gate, dict)
            and git_evidence_for_gate.get("status") == "passed"
            and self._boundary_evidence_passes(result)
            and not cancelled
            and not timed_out
            and not runtime_interrupted
        )
        if coding_ready_for_verification:
            with self.factory() as verification_session:
                verification_run = verification_session.get(CodexRun, run_id)
                if verification_run is not None:
                    verification_run.stdout = stdout
                    verification_run.stderr = stderr
                    verification_run.output_truncated = output_truncated
                    verification_run.exit_code = exit_code
                    verification_run.duration_ms = int((time.monotonic() - started_monotonic) * 1000)
                    verification_run.structured_result = json.dumps(result, separators=(",", ":"))
                    verification_run.status = "verifying"
                    verification_run.owner_summary = (
                        "Coding has reached a terminal process state; independent Verification is running."
                    )
                    verification_run.verification_status = "starting"
                    verification_run.verification_summary = "Independent Verification is preparing."
                    verification_run.task.status = "verifying"
                    verification_session.add(
                        AuditEvent(
                            action="codex_verification_starting",
                            entity_type="codex_run",
                            entity_id=run_id,
                            details="Coding process finished; independent Verification is preparing.",
                        )
                    )
                    self._sync_result_monitor(
                        verification_session,
                        verification_run,
                    )
                    verification_session.commit()
            verification = self._execute_verification(
                run_id,
                worktree,
                detection,
                pack_content,
                result,
            )
            result["verification"] = {
                key: value
                for key, value in verification.items()
                if key not in {
                    "collector",
                    "prompt",
                    "delivery_complete",
                    "_started_at",
                    "_completed_at",
                }
            }
            result["verification_process"] = dict(verification.get("process", {}))
            result["verification_invocation"] = dict(verification.get("invocation", {}))
            result["verification_verdict"] = dict(verification.get("verdict", {}))
        else:
            result["verification"] = {
                "status": "not_started",
                "summary": "Verification was not started because Coding did not reach the verification boundary.",
                "process_spawned": False,
            }
            result["verification_process"] = {
                "status": "not_started",
                "process_started": False,
                "failure": "Coding did not reach the Verification boundary.",
            }
            result["verification_invocation"] = {
                "process_execution_verified": False,
                "codex_turn_verified": False,
                "requested_model": "",
                "actual_resolved_model": None,
                "actual_model_identity_verified": False,
                "failure": "Verification was not started.",
            }
            result["verification_verdict"] = {
                "status": "not_reached",
                "passed_checks": [],
                "failed_checks": [],
            }

        task_acceptance = result.get("task_acceptance")
        if isinstance(task_acceptance, dict) and task_acceptance.get("status") == "needs_owner_review":
            verification_verdict = result.get("verification_verdict")
            verdict_status = (
                verification_verdict.get("status")
                if isinstance(verification_verdict, dict)
                else "not_reached"
            )
            if verdict_status == "passed":
                task_acceptance["status"] = "passed"
                task_acceptance["reason"] = "Independent Verification passed the frozen task checks."
            elif verdict_status == "failed":
                failed_checks = verification_verdict.get("failed_checks", [])
                task_acceptance["status"] = "failed"
                task_acceptance["reason"] = (
                    "Independent Verification rejected the output"
                    + (f": {', '.join(str(item) for item in failed_checks)}" if failed_checks else ".")
                )
            else:
                task_acceptance["reason"] = (
                    "Independent Verification did not reach a structured task verdict."
                )
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if not run:
                return
            run.stdout = stdout
            run.stderr = stderr
            run.output_truncated = output_truncated
            run.exit_code = exit_code
            run.duration_ms = duration_ms
            run.timed_out = timed_out
            run.cancelled = cancelled
            run.structured_result = json.dumps(result, separators=(",", ":"))
            run.finished_at = utc_now()
            if verification is not None:
                run.verification_status = str(verification["status"])
                run.verification_summary = str(verification["summary"])
                run.verification_process_spawned = bool(verification["process_spawned"])
                run.verification_stdout = str(verification["stdout"])
                run.verification_stderr = str(verification["stderr"])
                run.verification_exit_code = verification["exit_code"]  # type: ignore[assignment]
                run.verification_duration_ms = int(verification["duration_ms"])
                run.verification_timed_out = bool(verification["timed_out"])
                run.verification_cancelled = bool(verification["cancelled"])
                run.verification_output_truncated = bool(verification["output_truncated"])
            else:
                run.verification_status = "not_started"
                run.verification_summary = str(result["verification"]["summary"])
            coding_process = result.get("coding_process")
            git_evidence = result.get("git_evidence")
            task_acceptance = result.get("task_acceptance")
            verification_verdict = result.get("verification_verdict")
            if runtime_interrupted:
                run.status = "failed"
                run.owner_summary = "Runtime shutdown interrupted Codex execution; the failure is persisted."
                run.task.status = "needs_review"
            elif cancelled:
                run.status = "cancelled"
                run.owner_summary = "Codex execution was cancelled by the Owner."
                run.task.status = "cancelled"
            elif timed_out:
                run.status = "timed_out"
                run.owner_summary = "Codex execution exceeded the configured timeout."
                run.task.status = "needs_review"
            elif integrity_blocked:
                run.status = "blocked"
                run.owner_summary = (
                    "The detached Coding result failed its sealed integrity checks."
                )
                run.task.status = "needs_review"
            elif exit_code != 0:
                run.status = "failed"
                run.owner_summary = str(
                    coding_process.get("failure")
                    if isinstance(coding_process, dict)
                    else "Codex process failed; inspect Result and Advanced raw output."
                )
                run.task.status = "needs_review"
            elif not isinstance(git_evidence, dict) or git_evidence.get("status") != "passed":
                run.status = "failed"
                run.owner_summary = "Git evidence collection or validation failed; inspect Advanced diagnostics."
                run.task.status = "needs_review"
            elif not self._boundary_evidence_passes(result):
                run.status = "failed"
                run.owner_summary = "Codex exited successfully, but isolation or no-commit/no-push evidence failed."
                run.task.status = "needs_review"
            elif verification is None:
                run.status = "failed"
                run.owner_summary = "Coding finished, but independent Verification did not start."
                run.task.status = "needs_review"
            elif verification.get("integrity_blocked"):
                run.status = "blocked"
                run.owner_summary = (
                    "Independent Verification failed its sealed result integrity checks."
                )
                run.task.status = "needs_review"
            elif verification["runtime_interrupted"]:
                run.status = "failed"
                run.owner_summary = "Runtime shutdown interrupted independent Verification."
                run.task.status = "needs_review"
            elif verification["cancelled"]:
                run.status = "cancelled"
                run.owner_summary = "Independent Verification was cancelled by the Owner."
                run.task.status = "cancelled"
            elif verification["timed_out"]:
                run.status = "timed_out"
                run.owner_summary = "Independent Verification exceeded the configured timeout."
                run.task.status = "needs_review"
            elif verification.get("status") != "completed":
                run.status = "failed"
                run.owner_summary = str(
                    verification.get("failure")
                    or "Independent Verification process failed; inspect its separate evidence."
                )
                run.task.status = "needs_review"
            elif (
                not isinstance(verification_verdict, dict)
                or verification_verdict.get("status") != "passed"
            ):
                run.status = "failed"
                failed_checks = verification_verdict.get("failed_checks", []) if isinstance(
                    verification_verdict, dict
                ) else []
                run.owner_summary = "Independent Verification verdict failed" + (
                    f": {', '.join(str(item) for item in failed_checks)}."
                    if failed_checks
                    else "."
                )
                run.task.status = "needs_review"
            elif not isinstance(task_acceptance, dict) or task_acceptance.get("status") != "passed":
                run.status = "failed"
                run.owner_summary = str(
                    task_acceptance.get("reason")
                    if isinstance(task_acceptance, dict)
                    else "The frozen Development task acceptance result requires review."
                )
                run.task.status = "needs_review"
            else:
                run.status = "completed"
                run.owner_summary = "Coding and independent Verification completed in an isolated worktree."
                run.task.status = "result_ready"
            invocation_verified: bool | None = None
            if run.process_spawned:
                try:
                    with session.begin_nested():
                        invocation_verified = self._record_codex_invocation_evidence(
                            session,
                            run,
                            evidence_collector,
                            result,
                            pack_content,
                            runtime_interrupted,
                            pack_delivery_complete,
                        )
                except Exception as exc:
                    invocation_verified = False
                    session.add(
                        AuditEvent(
                            action="model_invocation_evidence_persistence_failed",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=f"failure_type={type(exc).__name__}; context=run_finalization",
                        )
                    )
                    try:
                        with session.begin_nested():
                            self._record_incomplete_spawn_evidence(
                                session,
                                run,
                                diagnostic_code="evidence_persistence_failure",
                                safe_summary=(
                                    "Model evidence persistence failed during finalization; "
                                    "the captured run requires review."
                                ),
                            )
                    except Exception as fallback_exc:
                        session.add(
                            AuditEvent(
                                action="model_invocation_fallback_evidence_failed",
                                entity_type="codex_run",
                                entity_id=run.id,
                                details=(
                                    f"failure_type={type(fallback_exc).__name__}; "
                                    "context=run_finalization"
                                ),
                            )
                        )
            verification_verified: bool | None = None
            if verification is not None and run.verification_process_spawned:
                try:
                    with session.begin_nested():
                        verification_verified = self._record_verification_invocation_evidence(
                            session,
                            run,
                            verification,
                        )
                except Exception as exc:
                    verification_verified = False
                    session.add(
                        AuditEvent(
                            action="verification_invocation_evidence_persistence_failed",
                            entity_type="codex_run",
                            entity_id=run.id,
                            details=f"failure_type={type(exc).__name__}; context=run_finalization",
                        )
                    )
            if invocation_verified is False and run.status == "completed":
                run.status = "failed"
                run.owner_summary = (
                    "Coding process finished, but its real invocation evidence could not be verified."
                )
                run.task.status = "needs_review"
            if verification_verified is False and run.status == "completed":
                run.status = "failed"
                run.owner_summary = (
                    "Verification process finished, but its separate invocation evidence could not be verified."
                )
                run.task.status = "needs_review"
            create_owner_acceptance(session, run.task, run)
            if run.status != "completed":
                run.task.status = "needs_review" if run.status in {"failed", "timed_out"} else run.status
            session.add(
                AuditEvent(
                    action="codex_run_completed",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=f"status={run.status}; exit_code={run.exit_code}; changed_files={len(result['changed_files'])}",
                )
            )
            self._sync_result_monitor(
                session,
                run,
                actual_model_identifier=(
                    evidence_collector.actual_model_identifier
                    if evidence_collector
                    and evidence_collector.actual_model_identity_verified
                    else None
                ),
                codex_session_identity=(
                    evidence_collector.thread_id_fingerprint
                    if evidence_collector
                    and evidence_collector.thread_id_fingerprint
                    else None
                ),
            )
            if verification is not None and verification.get("integrity_blocked"):
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_INTEGRITY_BLOCKED",
                    recovery_state="INTEGRITY_BLOCKED",
                    failure_code="BRIDGE_RESULT_INTEGRITY_BLOCKED",
                    safe_summary=run.owner_summary,
                )
            elif integrity_blocked:
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_INTEGRITY_BLOCKED",
                    recovery_state="INTEGRITY_BLOCKED",
                    failure_code="BRIDGE_RESULT_INTEGRITY_BLOCKED",
                    safe_summary=run.owner_summary,
                )
            session.commit()
            if (
                integrity_blocked
                or verification is not None
                and verification.get("integrity_blocked")
            ):
                from .run_lifecycle import reconcile_execution_attempt

                reconcile_execution_attempt(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                    monitor,
                )
                session.commit()

    def _execute_verification(
        self,
        run_id: int,
        worktree: Path,
        detection: CodexDetection,
        pack_content: str,
        coding_result: dict[str, object],
    ) -> dict[str, object]:
        """Run a second, read-only Codex process for independent Verification."""
        started_at = utc_now()
        started_monotonic = time.monotonic()
        expected_changed_files = sorted(
            str(item)
            for item in coding_result.get("changed_files", [])
            if isinstance(item, str)
        )
        sealed_verification_identity: dict[str, object] | None = None
        recovering_verification = (
            self._existing_bridge_handle(run_id, "verification") is not None
        )
        if recovering_verification:
            with self.factory() as recovery_session:
                recovery_run = recovery_session.get(CodexRun, run_id)
                if recovery_run is None:
                    raise codex_exec_bridge.CodexExecBridgeError(
                        "RUN_UNAVAILABLE",
                        "The persisted Codex Run is unavailable.",
                    )
                _, sealed_ticket = self._validated_bridge_ticket(
                    recovery_run,
                    phase="verification",
                    worktree=worktree,
                )
                raw_identity = sealed_ticket.get("identity")
                if isinstance(raw_identity, dict):
                    sealed_verification_identity = raw_identity
        if sealed_verification_identity is not None:
            # These are immutable prelaunch values.  Recomputing them after a
            # restart would turn the post-execution workspace into a false
            # baseline and could conceal Verification-side mutation.
            verification_snapshot_before_digest = str(
                sealed_verification_identity.get(
                    "pre_verification_workspace_digest"
                )
                or ""
            )
            git_boundary_before = (
                str(
                    sealed_verification_identity.get(
                        "git_boundary_fingerprint"
                    )
                    or ""
                ),
                True,
            )
            remote_boundary_before = (
                str(
                    sealed_verification_identity.get(
                        "source_remote_fingerprint"
                    )
                    or ""
                ),
                0,
                True,
            )
        else:
            try:
                verification_snapshot_before = capture_source_snapshot(worktree)
                verification_snapshot_before_digest = str(
                    verification_snapshot_before.get("digest", "")
                )
            except RuntimeError:
                verification_snapshot_before_digest = ""
            git_boundary_before = self._git_boundary_fingerprint(
                self.settings.source_repo
            )
            remote_boundary_before = self._remote_state_fingerprint(
                self.settings.source_repo
            )
        verification_context = {
            "changed_files": expected_changed_files,
            "changed_file_evidence": coding_result.get("changed_file_evidence", []),
            "tests_reported": coding_result.get("tests_reported", []),
            "validation": coding_result.get("validation", {}),
            "boundary_confirmation": coding_result.get("boundary_confirmation", {}),
            "source_snapshot_digest": coding_result.get("source_snapshot_digest", ""),
        }
        prompt = "\n".join(
            [
                "# TWOS Independent Verification",
                "You are the Verification capability in a separate invocation from Coding.",
                "Inspect the isolated workspace without modifying any file.",
                "Verify required and unexpected changed files, exact requested content, test evidence,",
                "the Git boundary, and the no-commit/no-merge/no-push/no-tag/no-remote boundary.",
                "Return exactly one JSON object as an agent message, with no code fence, using:",
                '{"schema":"twos.verification.v1","verdict":"pass|fail",'
                '"changed_files_checked":["relative/path"],"unexpected_files":[],'
                '"exact_content":"pass|fail","tests":"pass|fail|not_applicable",'
                '"git_boundary":"pass|fail","remote_boundary":"pass|fail"}',
                "changed_files_checked must exactly list every Coding-produced changed file supplied below.",
                "Do not claim actions or checks you did not actually perform.",
                "",
                "## Owner-approved Codex Pack",
                pack_content,
                "",
                "## Coding evidence supplied by TWOS",
                json.dumps(verification_context, sort_keys=True, separators=(",", ":")),
            ]
        )
        collector: _CodexJsonlEvidenceCollector | None = None
        process_spawned = False
        presentation_output_truncated = False
        exit_code: int | None = None
        timed_out = False
        cancelled = False
        runtime_interrupted = False
        integrity_blocked = False
        output_truncated = False
        stdout = ""
        stderr = ""
        model_identifier = ""
        launch_failure_classification = ""
        launch_failure_summary = ""
        try:
            with self.factory() as session:
                run = session.get(CodexRun, run_id)
                if run is None:
                    raise RuntimeError("The persisted Run no longer exists.")
                if not recovering_verification:
                    codex_run_execution_target(
                        session,
                        run,
                        self.settings.source_repo,
                        codex_executable=detection.executable,
                        child_environment=self._child_environment(),
                        allow_equivalent_connectivity_supersession=True,
                    )
                model_identifier = run.verification_model_identifier
                if not recovering_verification:
                    authenticated, reason = self.adapter.authentication_ready(detection)
                    if not authenticated:
                        raise RuntimeError(reason)
                run.status = "verifying"
                run.owner_summary = (
                    "Coding has reached a terminal process state; independent Verification is running."
                )
                run.verification_status = "running"
                run.verification_summary = "Independent Verification is running in read-only mode."
                run.task.status = "verifying"
                self._sync_result_monitor(session, run)
                session.commit()
            bridge_result = self._run_bridge_phase(
                run_id,
                phase="verification",
                detection=detection,
                worktree=worktree,
                prompt=prompt,
                model_identifier=model_identifier,
                sandbox_mode="read-only",
            )
            collector = bridge_result["collector"]  # type: ignore[assignment]
            process_spawned = bool(bridge_result["process_spawned"])
            exit_code = bridge_result["exit_code"]  # type: ignore[assignment]
            timed_out = bool(bridge_result["timed_out"])
            cancelled = bool(bridge_result["cancelled"])
            runtime_interrupted = bool(bridge_result["runtime_interrupted"])
            integrity_blocked = bool(bridge_result.get("integrity_blocked"))
            stdout = str(bridge_result["stdout"])
            stderr = str(bridge_result["stderr"])
            delivery_complete = bool(bridge_result["delivery_complete"])
            presentation_output_truncated = bool(
                bridge_result["retention_truncated"]
            )
            output_truncated = presentation_output_truncated
        except (
            OSError,
            RuntimeError,
            ValueError,
            codex_exec_bridge.CodexExecBridgeError,
        ) as exc:
            if self._bridge_phase_has_launch_evidence(run_id, "verification"):
                raise
            launch_failure_summary = _bounded_event_text(str(exc), maximum=500)
            if isinstance(exc, OSError):
                launch_failure_classification = "process_launch_failure"
            elif "auth" in launch_failure_summary.casefold() or "login" in launch_failure_summary.casefold():
                launch_failure_classification = "cli_authentication_failure"
            elif "model" in launch_failure_summary.casefold():
                launch_failure_classification = "invalid_model_identifier"
            else:
                launch_failure_classification = "runtime_configuration_failure"
            stderr = self._sanitize_process_output(str(exc)[:2000])
            exit_code = -1
            delivery_complete = False
        if (
            collector is not None
            and collector.structured_success
            and exit_code == 0
            and not timed_out
            and not cancelled
            and not runtime_interrupted
            and not output_truncated
            and delivery_complete
        ):
            self._bind_owner_verified_model_identity(
                run_id,
                collector,
                capability="verification",
            )
        elif collector is not None:
            collector.clear_verified_model_identity()
        try:
            verification_snapshot_after = capture_source_snapshot(worktree)
            verification_snapshot_after_digest = str(
                verification_snapshot_after.get("digest", "")
            )
        except RuntimeError:
            verification_snapshot_after_digest = ""
        git_boundary_after = self._git_boundary_fingerprint(self.settings.source_repo)
        remote_boundary_after = self._remote_state_fingerprint(self.settings.source_repo)
        workspace_unchanged = bool(
            verification_snapshot_before_digest
            and verification_snapshot_after_digest == verification_snapshot_before_digest
        )
        git_boundary_unchanged = bool(
            git_boundary_before[1]
            and git_boundary_after[1]
            and git_boundary_before[0] == git_boundary_after[0]
        )
        remote_boundary_unchanged = bool(
            remote_boundary_before[2]
            and remote_boundary_after[2]
            and remote_boundary_before[0] == remote_boundary_after[0]
        )
        contract = collector.verification_result if collector is not None else None
        contract_keys = {
            "schema",
            "verdict",
            "changed_files_checked",
            "unexpected_files",
            "exact_content",
            "tests",
            "git_boundary",
            "remote_boundary",
        }
        contract_shape_valid = bool(
            isinstance(contract, dict)
            and set(contract) == contract_keys
            and contract.get("schema") == "twos.verification.v1"
            and contract.get("verdict") in {"pass", "fail"}
            and isinstance(contract.get("changed_files_checked"), list)
            and all(isinstance(item, str) for item in contract.get("changed_files_checked", []))
            and isinstance(contract.get("unexpected_files"), list)
            and all(isinstance(item, str) for item in contract.get("unexpected_files", []))
            and contract.get("exact_content") in {"pass", "fail"}
            and contract.get("tests") in {"pass", "fail", "not_applicable"}
            and contract.get("git_boundary") in {"pass", "fail"}
            and contract.get("remote_boundary") in {"pass", "fail"}
        )
        claimed_changed_files = sorted(
            str(item) for item in (contract or {}).get("changed_files_checked", [])
        ) if contract_shape_valid else []
        unexpected_files = list((contract or {}).get("unexpected_files", [])) if contract_shape_valid else []
        checks = {
            "verification_verdict_observed": contract_shape_valid,
            "workspace_unchanged_after_verification": workspace_unchanged,
            "changed_files_checked": contract_shape_valid
            and claimed_changed_files == expected_changed_files,
            "unexpected_files_checked": contract_shape_valid and not unexpected_files,
            "exact_content_checked": contract_shape_valid and contract.get("exact_content") == "pass",
            "test_evidence_checked": contract_shape_valid
            and contract.get("tests") in {"pass", "not_applicable"},
            "git_boundary_checked": contract_shape_valid
            and contract.get("git_boundary") == "pass"
            and git_boundary_unchanged,
            "remote_boundary_checked": contract_shape_valid
            and contract.get("remote_boundary") == "pass"
            and remote_boundary_unchanged,
        }
        semantic_verification_passed = bool(
            contract_shape_valid
            and contract.get("verdict") == "pass"
            and all(checks.values())
        )
        failed_checks = [key for key, passed in checks.items() if not passed]
        passed_checks = [key for key, passed in checks.items() if passed]
        completed_at = utc_now()
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        if integrity_blocked:
            process_status = "integrity_blocked"
            failure_classification = "result_integrity_blocked"
            failure = "Independent Verification failed its sealed result integrity checks."
        elif runtime_interrupted:
            process_status = "failed"
            failure_classification = "runtime_interrupted"
            failure = "Runtime shutdown interrupted independent Verification."
        elif cancelled:
            process_status = "cancelled"
            failure_classification = "owner_cancelled"
            failure = "Independent Verification was cancelled by the Owner."
        elif timed_out:
            process_status = "timed_out"
            failure_classification = "process_timeout"
            failure = "Independent Verification timed out."
        elif launch_failure_classification:
            process_status = "failed"
            failure_classification = launch_failure_classification
            failure = launch_failure_summary or "Independent Verification could not launch."
        elif exit_code != 0:
            process_status = "failed"
            failure_classification = (
                collector.failure_classification
                if collector and collector.failure_classification
                else "process_nonzero_exit"
            )
            failure = (
                collector.failure_summary
                if collector and collector.failure_summary
                else f"Independent Verification exited with code {exit_code}."
            )
        elif collector and (
            collector.terminal_turn_status == "failed" or collector.fatal_adapter_error
        ):
            process_status = "failed"
            failure_classification = collector.failure_classification or "codex_turn_failed"
            failure = collector.failure_summary or "Independent Verification turn failed."
        elif collector is None or not collector.structured_success:
            process_status = "failed"
            failure_classification = "output_parser_failure"
            failure = "Independent Verification did not expose a complete terminal Codex turn."
        else:
            process_status = "completed"
            failure_classification = ""
            failure = ""

        if failure_classification == "invalid_model_identifier":
            failure = f'Configured model identifier “{model_identifier}” was rejected by Codex.'
        if process_status != "completed" or not contract_shape_valid:
            verdict_status = "not_reached"
        elif semantic_verification_passed:
            verdict_status = "passed"
        else:
            verdict_status = "failed"
        if process_status == "completed" and verdict_status == "passed":
            summary = "Independent Verification process completed and its structured verdict passed."
        elif process_status == "completed":
            summary = "Independent Verification process completed, but its structured verdict failed."
        else:
            summary = failure
        return {
            "status": process_status,
            "summary": summary,
            "process_spawned": process_spawned,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "runtime_interrupted": runtime_interrupted,
            "integrity_blocked": integrity_blocked,
            "output_truncated": output_truncated,
            "presentation_evidence_truncated": presentation_output_truncated,
            "started_at": started_at.isoformat() + "Z",
            "completed_at": completed_at.isoformat() + "Z",
            "collector": collector,
            "prompt": prompt,
            "delivery_complete": delivery_complete,
            "checks": checks,
            "semantic_verification_passed": semantic_verification_passed,
            "failure_classification": failure_classification,
            "failure": failure,
            "process": {
                "status": process_status,
                "assigned_model": model_identifier,
                "requested_model": model_identifier,
                "actual_resolved_model": (
                    collector.actual_model_identifier
                    if collector and collector.actual_model_identity_verified
                    else None
                ),
                "actual_model_identity_verified": bool(
                    collector and collector.actual_model_identity_verified
                ),
                "model_identity_source": (
                    collector.model_identity_source if collector else ""
                ),
                "connectivity_evidence_identity": (
                    collector.connectivity_evidence_identity if collector else ""
                ),
                "process_started": process_spawned,
                "turn_started": bool(collector and collector.turn_started),
                "process_exit": exit_code,
                "turn_terminal_state": collector.terminal_turn_status if collector else "not_observed",
                "failure_classification": failure_classification,
                "failure": failure,
            },
            "invocation": {
                "process_execution_verified": bool(
                    process_spawned
                    and type(exit_code) is int
                    and not runtime_interrupted
                    and not timed_out
                    and not cancelled
                ),
                "codex_turn_verified": bool(
                    collector
                    and collector.thread_started
                    and collector.turn_started
                    and collector.terminal_turn_status in {"completed", "failed"}
                ),
                "requested_model": model_identifier,
                "actual_resolved_model": (
                    collector.actual_model_identifier
                    if collector and collector.actual_model_identity_verified
                    else None
                ),
                "actual_model_identity_verified": bool(
                    collector and collector.actual_model_identity_verified
                ),
                "model_identity_source": (
                    collector.model_identity_source if collector else ""
                ),
                "connectivity_evidence_identity": (
                    collector.connectivity_evidence_identity if collector else ""
                ),
                "failure": failure,
            },
            "verdict": {
                "status": verdict_status,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
            },
            "expected_changed_files": expected_changed_files,
            "unexpected_files": unexpected_files if contract_shape_valid else [],
            "verification_snapshot_before_digest": verification_snapshot_before_digest,
            "verification_snapshot_after_digest": verification_snapshot_after_digest,
            "_started_at": started_at,
            "_completed_at": completed_at,
        }

    def _derive_result(
        self,
        worktree: Path,
        run_id: int,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
        cancelled: bool,
        runtime_interrupted: bool,
        remote_state_before: tuple[str, int, bool] | None,
        collector: _CodexJsonlEvidenceCollector | None,
        pack_delivery_complete: bool,
    ) -> dict[str, object]:
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            source_commit = run.source_commit if run else ""
            source_branch = run.source_branch if run else ""
            source_repo = Path(run.source_repo) if run else worktree
            frozen_development_task = (
                str(getattr(run, "development_task", "") or "")
                if run
                else ""
            )
            frozen_development_task_digest = (
                str(getattr(run, "development_task_digest", "") or "")
                if run
                else ""
            )
            requested_model_identifier = run.requested_model_identifier if run else ""
            pack_version = run.pack.version if run and run.pack else None
            process_spawned = bool(run and run.process_spawned)
            approved_snapshot = (
                json.loads(run.pack.source_snapshot_json or "{}") if run and run.pack else {}
            )
            approved_digest = run.source_snapshot_digest if run else ""
        post_commit = run_git(worktree, "rev-parse", "HEAD", check=False).stdout.strip()
        branch = run_git(worktree, "branch", "--show-current", check=False).stdout.strip()
        status_text = run_git(worktree, "status", "--porcelain", "--untracked-files=all", check=False).stdout.strip()
        untracked_files = [line[3:] for line in status_text.splitlines() if line.startswith("?? ")]
        post_snapshot = capture_source_snapshot(worktree)

        def snapshot_state(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
            output: dict[str, dict[str, object]] = {}
            rows = snapshot.get("included_manifest", [])
            if not isinstance(rows, list):
                return output
            for raw in rows:
                if not isinstance(raw, dict) or not raw.get("path"):
                    continue
                # Compare exact effective file state, not Git's classification
                # relative to whichever HEAD happens to exist after Coding. A
                # Run-created commit can change `tracked_change` to `tracked`
                # without changing bytes; conversely its file edits must still
                # be detected even after they become committed.
                row = {
                    "sha256": raw.get("sha256"),
                    "size": raw.get("size"),
                    "mode": raw.get("mode"),
                    "deleted": bool(raw.get("deleted", False)),
                }
                output[str(raw["path"])] = row
            return output

        approved_state = snapshot_state(approved_snapshot)
        post_state = snapshot_state(post_snapshot)
        changed_files = sorted(
            path
            for path in set(approved_state) | set(post_state)
            if approved_state.get(path) != post_state.get(path)
        )
        changed_file_evidence = [
            {
                "path": path,
                "before_sha256": approved_state.get(path, {}).get("sha256"),
                "after_sha256": post_state.get(path, {}).get("sha256"),
                "before_size": approved_state.get(path, {}).get("size"),
                "after_size": post_state.get(path, {}).get("size"),
                "before_mode": approved_state.get(path, {}).get("mode"),
                "after_mode": post_state.get(path, {}).get("mode"),
                "before_deleted": approved_state.get(path, {}).get("deleted", False),
                "after_deleted": post_state.get(path, {}).get("deleted", False),
            }
            for path in changed_files
        ]

        def verified_payload(
            root: Path,
            relative_path: str,
            state: dict[str, object] | None,
        ) -> bytes | None:
            if not state or state.get("deleted") or not state.get("sha256"):
                return b""
            size = state.get("size")
            if not isinstance(size, int) or size < 0 or size > SANITIZED_DIFF_MAX_FILE_BYTES:
                return None
            candidate = (root / relative_path).resolve()
            if (
                not candidate.is_relative_to(root.resolve())
                or not candidate.is_file()
                or candidate.is_symlink()
            ):
                return None
            payload = candidate.read_bytes()
            if len(payload) != size or hashlib.sha256(payload).hexdigest() != state.get("sha256"):
                return None
            return payload

        def text_lines(payload: bytes | None) -> list[str] | None:
            if payload is None or b"\0" in payload:
                return None
            try:
                return payload.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                return None

        sanitized_diff_records: list[dict[str, object]] = []
        for path in changed_files[:SANITIZED_DIFF_MAX_FILES]:
            before = approved_state.get(path)
            after = post_state.get(path)
            before_payload = verified_payload(source_repo, path, before)
            after_payload = verified_payload(worktree, path, after)
            before_lines = text_lines(before_payload)
            after_lines = text_lines(after_payload)
            added_lines: int | None = None
            removed_lines: int | None = None
            changed_hunks: int | None = None
            if before_lines is not None and after_lines is not None:
                added_lines = 0
                removed_lines = 0
                changed_hunks = 0
                for tag, before_start, before_end, after_start, after_end in difflib.SequenceMatcher(
                    None,
                    before_lines,
                    after_lines,
                    autojunk=False,
                ).get_opcodes():
                    if tag == "equal":
                        continue
                    changed_hunks += 1
                    if tag in {"replace", "delete"}:
                        removed_lines += before_end - before_start
                    if tag in {"replace", "insert"}:
                        added_lines += after_end - after_start
            before_present = bool(before and not before.get("deleted") and before.get("sha256"))
            after_present = bool(after and not after.get("deleted") and after.get("sha256"))
            if not before_present and after_present:
                change_type = "created"
            elif before_present and not after_present:
                change_type = "deleted"
            elif before and after and before.get("sha256") == after.get("sha256"):
                change_type = "mode_changed"
            else:
                change_type = "modified"
            sanitized_diff_records.append(
                {
                    "path": path,
                    "change_type": change_type,
                    "before_sha256": before.get("sha256") if before else None,
                    "after_sha256": after.get("sha256") if after else None,
                    "before_mode": before.get("mode") if before else None,
                    "after_mode": after.get("mode") if after else None,
                    "before_size": before.get("size") if before else None,
                    "after_size": after.get("size") if after else None,
                    "content_kind": (
                        "text"
                        if before_lines is not None and after_lines is not None
                        else "binary_or_oversized"
                    ),
                    "added_lines": added_lines,
                    "removed_lines": removed_lines,
                    "changed_hunks": changed_hunks,
                    "content_included": False,
                }
            )
        sanitized_diff_evidence = {
            "schema": "twos.sanitized_diff.v1",
            "content_included": False,
            "records": sanitized_diff_records,
            "record_count": len(changed_files),
            "truncated": len(changed_files) > SANITIZED_DIFF_MAX_FILES,
        }

        unexpected_excluded_artifacts: list[dict[str, str]] = []
        for item in post_snapshot.get("excluded_manifest", []):
            if not isinstance(item, dict):
                continue
            relative_path = str(item.get("path", ""))
            reason = str(item.get("reason", "excluded"))
            candidate = (worktree / relative_path).resolve()
            if not candidate.is_relative_to(worktree.resolve()) or not (
                candidate.exists() or candidate.is_symlink()
            ):
                continue
            unexpected_excluded_artifacts.append(
                {
                    "path": (
                        "[credential-shaped path withheld]"
                        if reason == "credential_or_secret"
                        else relative_path
                    ),
                    "reason": reason,
                }
            )
        untracked_files = [path for path in untracked_files if path in changed_files]
        committed_stat = run_git(worktree, "diff", "--stat", f"{source_commit}..HEAD", check=False).stdout.strip()
        working_stat = run_git(worktree, "diff", "--stat", check=False).stdout.strip()
        cached_stat = run_git(worktree, "diff", "--cached", "--stat", check=False).stdout.strip()
        untracked_stats: list[str] = []
        untracked_checks_ok = True
        worktree_root = worktree.resolve()
        for relative_path in untracked_files:
            candidate = (worktree / relative_path).resolve()
            if not candidate.is_relative_to(worktree_root) or not candidate.is_file():
                untracked_checks_ok = False
                continue
            check_result = run_git(
                worktree,
                "diff",
                "--no-index",
                "--check",
                "--",
                os.devnull,
                relative_path,
                check=False,
            )
            if check_result.returncode not in {0, 1} or check_result.stdout.strip() or check_result.stderr.strip():
                untracked_checks_ok = False
            stat_result = run_git(
                worktree,
                "diff",
                "--no-index",
                "--stat",
                "--",
                os.devnull,
                relative_path,
                check=False,
            )
            if stat_result.stdout.strip():
                untracked_stats.append(stat_result.stdout.strip())
        commit_lines = run_git(
            worktree,
            "log",
            "--format=%H%x09%s",
            f"{source_commit}..HEAD",
            check=False,
        ).stdout.splitlines()
        # Commit identity is boundary evidence; free-form commit subjects are
        # not required and could echo sensitive task or source text.
        commits = [line.split("\t", 1)[0] for line in commit_lines if line.split("\t", 1)[0]]
        merge_commits = run_git(
            worktree,
            "rev-list",
            "--merges",
            f"{source_commit}..HEAD",
            check=False,
        ).stdout.splitlines()
        source_post_commit = run_git(
            source_repo,
            "rev-parse",
            "HEAD",
            check=False,
            hardened_read_only=True,
        ).stdout.strip()
        source_status = run_git(
            source_repo,
            "status",
            "--porcelain",
            "--untracked-files=all",
            check=False,
            hardened_read_only=True,
        ).stdout.strip()
        remote_state_after = self._remote_state_fingerprint(source_repo)
        remote_state_unchanged = bool(
            remote_state_before
            and remote_state_before[2]
            and remote_state_after[2]
            and remote_state_before[0] == remote_state_after[0]
        )
        worktree_common_raw = run_git(worktree, "rev-parse", "--git-common-dir", check=False).stdout.strip()
        source_common_raw = run_git(source_repo, "rev-parse", "--git-common-dir", check=False).stdout.strip()
        worktree_common = self._resolved_git_path(worktree, worktree_common_raw)
        source_common = self._resolved_git_path(source_repo, source_common_raw)
        isolated_worktree = (
            worktree.resolve() != source_repo.resolve()
            and worktree_common is not None
            and worktree_common == source_common
        )
        try:
            source_post_snapshot = capture_source_snapshot(
                source_repo,
                hardened_read_only=True,
            )
            source_unchanged = (
                source_post_commit == source_commit
                and source_post_snapshot.get("digest") == approved_digest
            )
        except RuntimeError:
            source_unchanged = False
        checks = [
            run_git(worktree, "diff", "--check", f"{source_commit}..HEAD", check=False),
            run_git(worktree, "diff", "--check", check=False),
            run_git(worktree, "diff", "--cached", "--check", check=False),
        ]
        diff_check = (
            all(item.returncode == 0 for item in checks)
            and untracked_checks_ok
            and not unexpected_excluded_artifacts
        )
        def sanitized_status(
            raw_status: str,
            snapshot: dict[str, object],
        ) -> str:
            sanitized = raw_status
            rows = snapshot.get("excluded_manifest", [])
            if not isinstance(rows, list):
                return sanitized
            for item in rows:
                if not isinstance(item, dict) or item.get("reason") != "credential_or_secret":
                    continue
                path = str(item.get("path", ""))
                if path:
                    sanitized = sanitized.replace(path, "[credential-shaped path withheld]")
            return sanitized

        public_worktree_status = sanitized_status(status_text, post_snapshot)
        public_source_status = sanitized_status(source_status, approved_snapshot)
        process_execution_verified = bool(
            process_spawned
            and type(exit_code) is int
            and not runtime_interrupted
            and not timed_out
            and not cancelled
        )
        if runtime_interrupted:
            coding_process_status = "failed"
            coding_process_failure = "Runtime shutdown interrupted Coding process evidence collection."
        elif cancelled:
            coding_process_status = "cancelled"
            coding_process_failure = "Coding was cancelled by the Owner."
        elif timed_out:
            coding_process_status = "timed_out"
            coding_process_failure = "Coding exceeded the configured timeout."
        elif type(exit_code) is not int:
            coding_process_status = "failed"
            coding_process_failure = "Coding process terminal status was not available."
        elif exit_code != 0:
            coding_process_status = "failed"
            coding_process_failure = (
                collector.failure_summary
                if collector and collector.failure_summary
                else f"Coding process exited with code {exit_code}."
            )
        else:
            coding_process_status = "completed"
            coding_process_failure = ""

        codex_turn_verified = bool(
            collector
            and collector.thread_started
            and collector.turn_started
            and collector.terminal_turn_status in {"completed", "failed"}
            and not collector.limit_exceeded
            and not collector.collection_incomplete
        )
        successful_turn = bool(
            codex_turn_verified
            and collector
            and collector.terminal_turn_status == "completed"
            and not collector.fatal_adapter_error
        )
        invocation_failure = ""
        if collector is None:
            invocation_failure = "Codex JSONL lifecycle evidence was not available."
        elif collector.limit_exceeded:
            invocation_failure = "Codex JSONL exceeded the bounded evidence limit."
        elif collector.collection_incomplete:
            invocation_failure = "Codex JSONL collection did not finish cleanly."
        elif collector.unsupported_model_routing_observed:
            invocation_failure = (
                "Codex exposed an unsupported model-routing event, so the approved target "
                "could not be verified."
            )
        elif collector.terminal_turn_status == "failed" or collector.fatal_adapter_error:
            invocation_failure = collector.failure_summary or "Codex reported a failed terminal turn."
        elif not collector.thread_started or not collector.turn_started:
            invocation_failure = "Codex did not expose a complete thread and turn start lifecycle."
        elif collector.terminal_turn_status != "completed":
            invocation_failure = "Codex did not expose a terminal turn event."
        elif not pack_delivery_complete:
            invocation_failure = "The exact approved Pack was not fully delivered to Codex stdin."

        tests = list(collector.test_executions) if collector else []
        git_evidence_status = "passed" if diff_check else "failed"
        git_evidence_failure = "" if diff_check else "Git inspection or diff validation failed."
        no_change_explicitly_allowed = bool(
            re.search(
                r"\b(?:do not modify any file|no (?:repository |source |file )?changes?|"
                r"analysis only|review only|read[- ]only review)\b",
                frozen_development_task,
                re.IGNORECASE,
            )
        )
        if coding_process_status != "completed":
            task_acceptance_status = "failed"
            task_acceptance_reason = coding_process_failure or "Coding did not complete."
        elif git_evidence_status != "passed":
            task_acceptance_status = "failed"
            task_acceptance_reason = git_evidence_failure
        elif not changed_files and not no_change_explicitly_allowed:
            task_acceptance_status = "failed"
            task_acceptance_reason = "No requested implementation output was produced."
        elif not changed_files:
            task_acceptance_status = "passed"
            task_acceptance_reason = "The frozen task explicitly permitted a no-change result."
        else:
            task_acceptance_status = "needs_owner_review"
            task_acceptance_reason = "Run-produced changes require the independent Verification verdict."

        coding_invocation = {
            "process_execution_verified": process_execution_verified,
            "codex_turn_verified": codex_turn_verified,
            "turn_started": bool(collector and collector.turn_started),
            "turn_terminal_state": collector.terminal_turn_status if collector else "not_observed",
            "requested_model": requested_model_identifier,
            "actual_resolved_model": (
                collector.actual_model_identifier
                if collector and collector.actual_model_identity_verified
                else None
            ),
            "actual_model_identity_verified": bool(
                collector and collector.actual_model_identity_verified
            ),
            "model_identity_source": (
                collector.model_identity_source if collector else ""
            ),
            "connectivity_evidence_identity": (
                collector.connectivity_evidence_identity if collector else ""
            ),
            "approved_prompt_delivery_complete": pack_delivery_complete,
            "failure": invocation_failure,
        }
        return {
            "task_id": run_id and (run.task_id if run else None),
            "task_version": run.task_version if run else None,
            "development_task": frozen_development_task,
            "development_task_digest": frozen_development_task_digest,
            "pack_version": pack_version,
            "coding_prompt_digest": hashlib.sha256(
                (run.pack.content if run and run.pack else "").encode("utf-8")
            ).hexdigest(),
            "pre_run_commit": source_commit,
            "post_run_commit": post_commit,
            "source_branch": source_branch,
            "worktree_branch": branch,
            "working_tree_status": public_worktree_status or "clean",
            "changed_files": changed_files,
            "changed_file_evidence": changed_file_evidence,
            "sanitized_diff_evidence": sanitized_diff_evidence,
            "unexpected_excluded_artifacts": unexpected_excluded_artifacts,
            "source_snapshot_digest": approved_digest,
            "post_run_snapshot_digest": post_snapshot.get("digest"),
            "diff_summary": "\n".join(
                f"{item['path']}: {item['before_sha256'] or 'absent'} -> {item['after_sha256'] or 'absent'}"
                for item in changed_file_evidence
            ),
            "commits": commits,
            "process": {
                "exit_code": exit_code,
                "timed_out": timed_out,
                "cancelled": cancelled,
                "runtime_interrupted": runtime_interrupted,
                "stderr_present": bool(stderr),
            },
            "coding_process": {
                "status": coding_process_status,
                "process_started": process_spawned,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "cancelled": cancelled,
                "failure": coding_process_failure,
            },
            "coding_invocation": coding_invocation,
            "run_produced_changes": {
                "status": "changes" if changed_files else "none",
                "changed_files": changed_files,
                "unexpected_files": [
                    item.get("path")
                    for item in unexpected_excluded_artifacts
                    if isinstance(item, dict) and item.get("path")
                ],
            },
            "git_evidence": {
                "status": git_evidence_status,
                "failure": git_evidence_failure,
            },
            "task_acceptance": {
                "status": task_acceptance_status,
                "reason": task_acceptance_reason,
            },
            "validation": {
                "diff_check": diff_check,
                "no_excluded_artifacts": not unexpected_excluded_artifacts,
            },
            "tests": tests,
            "tests_reported": [str(item.get("summary", "")) for item in tests],
            "advanced_diagnostics": {
                "coding_final_agent_message": collector.final_agent_message if collector else "",
                "malformed_jsonl_lines": collector.malformed_line_count if collector else 0,
                "malformed_jsonl_diagnostics": list(collector.malformed_diagnostics) if collector else [],
                "command_execution_count": collector.command_execution_count if collector else 0,
                "file_change_event_count": collector.file_change_count if collector else 0,
            },
            "boundary_confirmation": {
                "isolated_worktree": isolated_worktree,
                "source_main_unchanged": source_unchanged,
                "source_post_run_commit": source_post_commit,
                "source_post_run_status": public_source_status or "clean",
                "merge_commits_created": bool(merge_commits),
                "source_remote_count": remote_state_after[1],
                "push_target_configured": remote_state_after[1] > 0,
                "remote_state_observed": remote_state_after[2],
                "remote_state_unchanged": remote_state_unchanged,
                "git_transport_protocols_allowed": False,
                "codex_tool_network_access_allowed": False,
                "automatic_merge": False,
                "automatic_push": False,
            },
        }

    def _truncate(self, value: str) -> tuple[str, bool]:
        limit = max(0, self.settings.codex_output_limit)
        raw = value.encode("utf-8")
        if len(raw) <= limit:
            return value, False
        suffix = OUTPUT_TRUNCATION_SUFFIX.encode("utf-8")
        if limit <= len(suffix):
            return suffix[:limit].decode("utf-8", errors="ignore"), True
        retained = raw[: limit - len(suffix)] + suffix
        return retained.decode("utf-8", errors="ignore"), True

    def _bounded_outputs(
        self,
        stdout_capture: _StreamCapture,
        stderr_capture: _StreamCapture,
    ) -> tuple[str, str, bool]:
        stdout_data = stdout_capture.data()
        stderr_data = stderr_capture.data()
        truncated = stdout_capture.truncated or stderr_capture.truncated
        if not truncated:
            return (
                stdout_data.decode("utf-8", errors="ignore"),
                stderr_data.decode("utf-8", errors="ignore"),
                False,
            )
        limit = max(0, self.settings.codex_output_limit)
        suffix = OUTPUT_TRUNCATION_SUFFIX.encode("utf-8")
        if limit <= len(suffix):
            marker = suffix[:limit].decode("utf-8", errors="ignore")
            return (marker, "", True) if stdout_capture.truncated else ("", marker, True)
        content_limit = limit - len(suffix)
        stdout_data = stdout_data[:content_limit]
        stderr_data = stderr_data[: max(0, content_limit - len(stdout_data))]
        if stdout_capture.truncated:
            stdout_data += suffix
        else:
            stderr_data += suffix
        return (
            stdout_data.decode("utf-8", errors="ignore"),
            stderr_data.decode("utf-8", errors="ignore"),
            True,
        )

    def _rebudget_sanitized_outputs(
        self,
        stdout: str,
        stderr: str,
        *,
        already_truncated: bool = False,
        marker_on_stdout: bool = True,
    ) -> tuple[str, str, bool]:
        """Keep safe presentation evidence inside one truthful combined cap.

        The durable Exec Bridge may already have consumed the complete byte
        budget before this presentation layer reads its retained streams.  In
        that case the retained payload itself is not over budget, but the
        receipt still proves that bytes were omitted.  Reserve space for the
        truncation marker deterministically instead of depending on which
        drain thread won the shared budget race.
        """
        limit = max(0, self.settings.codex_output_limit)
        stdout_data = stdout.encode("utf-8")
        stderr_data = stderr.encode("utf-8")
        if not already_truncated and len(stdout_data) + len(stderr_data) <= limit:
            return stdout, stderr, False
        suffix = OUTPUT_TRUNCATION_SUFFIX.encode("utf-8")
        if limit <= len(suffix):
            marker = suffix[:limit].decode("utf-8", errors="ignore")
            return (
                (marker, "", True)
                if marker_on_stdout
                else ("", marker, True)
            )
        content_limit = limit - len(suffix)
        retained_stdout = stdout_data[:content_limit]
        retained_stderr = stderr_data[: max(0, content_limit - len(retained_stdout))]
        if marker_on_stdout:
            retained_stdout += suffix
        else:
            retained_stderr += suffix
        return (
            retained_stdout.decode("utf-8", errors="ignore"),
            retained_stderr.decode("utf-8", errors="ignore"),
            True,
        )

    @classmethod
    def _sanitize_process_output(cls, value: str) -> str:
        """Persist only credential-safe, reasoning-safe process evidence.

        Codex JSONL can contain transport events for private reasoning items.
        Those events are useful as lifecycle evidence, but their text is not
        Owner-visible output and must never be stored on ``CodexRun``.  Keep a
        minimal event envelope so event ordering/counting remains auditable.
        """
        sanitized_lines: list[str] = []
        for line in value.splitlines(keepends=True):
            ending = "\n" if line.endswith("\n") else ""
            payload = line[:-1] if ending else line
            try:
                decoded = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                sanitized_lines.append(cls._redact_sensitive_text(payload) + ending)
                continue
            if cls._is_private_reasoning_event(decoded):
                decoded = cls._reasoning_event_envelope(decoded)
            sanitized = cls._sanitize_json_value(decoded)
            sanitized_lines.append(
                json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + ending
            )
        return "".join(sanitized_lines)

    @staticmethod
    def _is_private_reasoning_event(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        event_type = str(value.get("type") or "").lower()
        if "reasoning" in event_type or event_type.startswith("analysis."):
            return True
        item = value.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type") or "").lower()
            if item_type in {
                "reasoning",
                "analysis",
                "reasoning_summary",
                "reasoning_summary_text",
            }:
                return True
        return False

    @staticmethod
    def _reasoning_event_envelope(value: dict[str, object]) -> dict[str, object]:
        safe: dict[str, object] = {
            "type": str(value.get("type") or "reasoning.activity")[:120],
            "summary": "Codex is reasoning",
        }
        for key in ("timestamp", "created_at", "thread_id", "turn_id"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float)) and not isinstance(
                candidate, bool
            ):
                safe[key] = candidate
        item = value.get("item")
        if isinstance(item, dict):
            safe_item: dict[str, object] = {"type": "reasoning"}
            for key in ("id", "status"):
                candidate = item.get(key)
                if isinstance(candidate, str):
                    safe_item[key] = candidate[:240]
            safe["item"] = safe_item
        return safe

    @classmethod
    def _sanitize_json_value(cls, value, *, key: str = "", depth: int = 0):
        if depth > 20:
            return "[redacted: nesting limit]"
        if key == "thread_id" and isinstance(value, str):
            return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
        if key and _SENSITIVE_OUTPUT_KEY.search(key):
            return "[redacted]"
        if isinstance(value, dict):
            return {
                str(item_key): cls._sanitize_json_value(
                    item_value,
                    key=str(item_key),
                    depth=depth + 1,
                )
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [cls._sanitize_json_value(item, depth=depth + 1) for item in value]
        if isinstance(value, str):
            return cls._redact_sensitive_text(value)
        return value

    @staticmethod
    def _redact_sensitive_text(value: str) -> str:
        redacted = _PRIVATE_KEY_BLOCK.sub("[redacted private key]", value)
        redacted = _THREAD_ID_TEXT.sub(
            lambda match: (
                f'{match.group(1)}sha256:'
                f'{hashlib.sha256(match.group(2).encode("utf-8")).hexdigest()}{match.group(3)}'
            ),
            redacted,
        )
        redacted = _BEARER_TOKEN.sub("Bearer [redacted]", redacted)
        redacted = _PROVIDER_TOKEN.sub("[redacted provider token]", redacted)
        redacted = _COMMON_PROVIDER_TOKEN.sub("[redacted provider token]", redacted)
        redacted = _ENV_CREDENTIAL_TEXT.sub(lambda match: f"[redacted]{match.group(1)}", redacted)
        return _SENSITIVE_OUTPUT_TEXT.sub(lambda match: f"[redacted]{match.group(1)}", redacted)

    def _child_environment(self) -> dict[str, str]:
        return codex_child_environment()

    def _bind_owner_verified_model_identity(
        self,
        run_id: int,
        collector: _CodexJsonlEvidenceCollector | None,
        *,
        capability: str,
    ) -> None:
        """Bind admission evidence without inventing this Run's model identity.

        A prior Owner connectivity turn can authorize the exact executable and
        requested-model context, but it cannot attest which physical model a
        later `codex exec` process used.  Only this Run's own structured output
        may set the collector's actual-model fields.
        """
        if collector is None or not collector.structured_success:
            return
        with self.factory() as session:
            run = session.get(CodexRun, run_id)
            if run is None or run.pack is None or run.pack.approved_by_user_id is None:
                return
            if capability == "coding":
                evidence = run.execution_connectivity_evidence
                expected_evidence_id = run.execution_connectivity_evidence_id
                expected_model_id = run.execution_model_id
                requested_model = run.requested_model_identifier
            elif capability == "verification":
                evidence = run.verification_connectivity_evidence
                expected_evidence_id = run.verification_connectivity_evidence_id
                expected_model_id = run.verification_model_id
                requested_model = run.verification_model_identifier
            else:
                return
            if not (
                evidence is not None
                and evidence.id == expected_evidence_id
                and evidence.owner_id == run.pack.approved_by_user_id
                and evidence.model_id == expected_model_id
                and evidence.requested_model_identifier == requested_model
                and evidence.readiness_state == "READY_FOR_REAL_RUN"
                and evidence.provider_reachable
                and evidence.model_available
                and evidence.credential_store_accessible
                and not evidence.interactive_prompt_detected
                and not evidence.timed_out
                and evidence.exit_code == 0
                and re.fullmatch(r"[0-9a-f]{64}", evidence.evidence_digest or "")
            ):
                return
            collector.connectivity_evidence_identity = evidence.evidence_digest

    @staticmethod
    def _executable_identity_fingerprint(executable: str | None) -> str:
        return executable_identity(executable)

    @staticmethod
    def _remote_state_fingerprint(repo: Path) -> tuple[str, int, bool]:
        """Hash local remote config/tracking refs without persisting URLs or credentials."""
        remotes = run_git(repo, "remote", check=False, hardened_read_only=True)
        refs = run_git(
            repo,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            "refs/remotes",
            check=False,
            hardened_read_only=True,
        )
        config = run_git(
            repo,
            "config",
            "--local",
            "--null",
            "--get-regexp",
            r"^remote\..*\.(url|pushurl)$",
            check=False,
            hardened_read_only=True,
        )
        complete = (
            remotes.returncode == 0
            and refs.returncode == 0
            and config.returncode in {0, 1}
        )
        remote_names = sorted(item for item in remotes.stdout.splitlines() if item)
        if not complete:
            return "", len(remote_names), False
        payload = "\0".join(remote_names) + "\0" + refs.stdout + "\0" + config.stdout
        return hashlib.sha256(payload.encode("utf-8")).hexdigest(), len(remote_names), True

    @staticmethod
    def _git_boundary_fingerprint(repo: Path) -> tuple[str, bool]:
        """Hash refs and remote configuration without persisting sensitive values."""
        refs = run_git(
            repo,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            "refs/heads",
            "refs/tags",
            "refs/remotes",
            check=False,
            hardened_read_only=True,
        )
        config = run_git(
            repo,
            "config",
            "--local",
            "--null",
            "--get-regexp",
            r"^remote\..*\.(url|pushurl)$",
            check=False,
            hardened_read_only=True,
        )
        complete = refs.returncode == 0 and config.returncode in {0, 1}
        if not complete:
            return "", False
        payload = refs.stdout + "\0" + config.stdout
        return hashlib.sha256(payload.encode("utf-8")).hexdigest(), True

    @staticmethod
    def _write_pack(
        process: subprocess.Popen[bytes],
        pack_content: str,
        delivery: _StdinDelivery,
    ) -> None:
        if not process.stdin:
            delivery.finish(0, failed=True)
            return
        encoded = pack_content.encode("utf-8")
        try:
            written = process.stdin.write(encoded)
            process.stdin.flush()
            process.stdin.close()
            delivery.finish(int(written or 0), failed=written != len(encoded))
        except (BrokenPipeError, OSError, ValueError):
            # Exit status and bounded stderr remain the authoritative evidence.
            delivery.finish(0, failed=True)
            return

    def _wait_for_process(
        self,
        run_id: int,
        process: subprocess.Popen[bytes],
    ) -> tuple[int | None, bool, bool, bool]:
        deadline = time.monotonic() + self.settings.codex_timeout_seconds
        while process.poll() is None:
            stop_reason = self._stop_reason(run_id)
            if stop_reason is not None:
                self._stop_process_tree(process, force=False)
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._stop_process_tree(process, force=True)
                    process.wait(timeout=2.0)
                return (
                    process.returncode,
                    False,
                    stop_reason == "owner_cancelled",
                    stop_reason == "runtime_shutdown",
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_process_tree(process, force=True)
                process.wait(timeout=2.0)
                return process.returncode, True, False, False
            try:
                process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
        stop_reason = self._stop_reason(run_id)
        return (
            process.returncode,
            False,
            stop_reason == "owner_cancelled",
            stop_reason == "runtime_shutdown",
        )

    @staticmethod
    def _stop_process_tree(process: subprocess.Popen[bytes], force: bool) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            return

    @staticmethod
    def _resolved_git_path(repo: Path, value: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return (path if path.is_absolute() else repo / path).resolve()

    @staticmethod
    def _boundary_evidence_passes(result: dict[str, object]) -> bool:
        boundary = result.get("boundary_confirmation")
        commits = result.get("commits")
        if not isinstance(boundary, dict) or not isinstance(commits, list):
            return False
        return bool(
            boundary.get("isolated_worktree")
            and boundary.get("source_main_unchanged")
            and not boundary.get("merge_commits_created")
            and boundary.get("remote_state_observed") is True
            and boundary.get("remote_state_unchanged") is True
            and boundary.get("git_transport_protocols_allowed") is False
            and boundary.get("codex_tool_network_access_allowed") is False
            and boundary.get("automatic_merge") is False
            and boundary.get("automatic_push") is False
            and not commits
        )

    def _record_codex_invocation_evidence(
        self,
        session: Session,
        run: CodexRun,
        collector: _CodexJsonlEvidenceCollector | None,
        result: dict[str, object],
        pack_content: str,
        runtime_interrupted: bool,
        pack_delivery_complete: bool,
    ) -> bool:
        """Persist one bounded evidence row for an actually spawned Codex process."""
        invocation_ref = f"codex-run-{run.id}-coding"
        existing = session.scalar(
            select(AIModelInvocationEvidence).where(
                AIModelInvocationEvidence.invocation_ref == invocation_ref
            )
        )
        if existing is not None:
            return is_verified_real_invocation(existing)

        assignment = run.execution_assignment
        requested_model = run.execution_model
        if assignment is None or requested_model is None:
            session.add(
                AuditEvent(
                    action="model_invocation_evidence_blocked",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Persisted Codex execution target is incomplete.",
                )
            )
            return False

        model = requested_model
        actual_identifier = ""
        authorized_actual = False
        reroute_observed = bool(collector and collector.rerouted_to)
        requested_identifier_match = (
            requested_model.provider_model_id == run.requested_model_identifier
        )
        collector_identity_usable = bool(
            collector
            and collector.actual_model_identity_verified
            and not collector.limit_exceeded
            and not collector.collection_incomplete
            and not collector.lifecycle_conflict
            and not collector.unsupported_model_routing_observed
            and collector.structured_success
            and pack_delivery_complete
            and not runtime_interrupted
            and not run.timed_out
            and not run.cancelled
            and not run.output_truncated
            and run.exit_code == 0
        )
        if collector_identity_usable and collector is not None:
            candidate = collector.actual_model_identifier
            if candidate == run.requested_model_identifier:
                actual_identifier = candidate
                authorized_actual = requested_model.provider_model_id == candidate
            elif (
                collector.rerouted_from == run.requested_model_identifier
                and assignment.fallback_allowed
                and assignment.fallback_model is not None
                and assignment.fallback_model.provider_model_id == candidate
            ):
                model = assignment.fallback_model
                actual_identifier = candidate
                authorized_actual = True
            else:
                actual_identifier = candidate

        structured_success = bool(collector and collector.structured_success)
        if runtime_interrupted:
            outcome = "failed"
            error_category = "interrupted"
            diagnostic_code = "runtime_shutdown"
            safe_summary = "Runtime shutdown interrupted the spawned Codex process; no Owner cancellation is claimed."
        elif run.cancelled:
            outcome = "cancelled"
            error_category = "cancelled"
            diagnostic_code = "owner_cancelled"
            safe_summary = "The spawned Codex process was cancelled; no verified model claim was recorded."
        elif run.timed_out:
            outcome = "timed_out"
            error_category = "timeout"
            diagnostic_code = "process_timeout"
            safe_summary = "The spawned Codex process timed out; no verified model claim was recorded."
        elif run.exit_code != 0:
            outcome = "failed"
            error_category = (
                collector.failure_classification
                if collector and collector.failure_classification
                else "process_failure"
            )
            diagnostic_code = (
                "turn_failed"
                if collector and collector.terminal_turn_status == "failed"
                else "nonzero_exit"
            )
            safe_summary = (
                collector.failure_summary
                if collector and collector.failure_summary
                else "The spawned Codex process exited unsuccessfully."
            )
        elif collector_identity_usable and actual_identifier and not authorized_actual:
            outcome = "failed"
            error_category = "routing_mismatch"
            diagnostic_code = "unapproved_model_reroute"
            safe_summary = "Codex reported a model reroute outside the approved fallback policy."
        elif run.output_truncated:
            outcome = "failed"
            error_category = "evidence_incomplete"
            diagnostic_code = "output_truncated"
            safe_summary = "Output was capped, so the real model invocation claim remains unverified."
        elif collector is None or collector.limit_exceeded:
            outcome = "failed"
            error_category = "evidence_incomplete"
            diagnostic_code = "jsonl_limit_exceeded" if collector else "jsonl_missing"
            safe_summary = "Bounded Codex JSONL evidence was unavailable or exceeded its safety limit."
        elif not pack_delivery_complete:
            outcome = "failed"
            error_category = "evidence_incomplete"
            diagnostic_code = "approved_pack_delivery_incomplete"
            safe_summary = "The exact approved Pack was not fully delivered to Codex stdin."
        elif collector.collection_incomplete:
            outcome = "failed"
            error_category = "evidence_incomplete"
            diagnostic_code = "jsonl_collection_incomplete"
            safe_summary = "Codex output collection did not finish cleanly; no verified model claim was recorded."
        elif collector.lifecycle_conflict:
            outcome = "failed"
            error_category = "evidence_integrity"
            diagnostic_code = "jsonl_lifecycle_conflict"
            safe_summary = (
                "Codex JSONL did not preserve one ordered thread and turn identity."
            )
        elif collector.unsupported_model_routing_observed:
            outcome = "failed"
            error_category = "routing_mismatch"
            diagnostic_code = "unsupported_model_routing_event"
            safe_summary = (
                "Codex exposed an unsupported model-routing event, so the approved target "
                "could not be verified."
            )
        elif not structured_success or not requested_identifier_match:
            outcome = "failed"
            error_category = (
                collector.failure_classification
                if collector and collector.failure_classification
                else "evidence_incomplete"
            )
            diagnostic_code = (
                "turn_failed"
                if collector and collector.terminal_turn_status == "failed"
                else "jsonl_incomplete"
            )
            safe_summary = (
                collector.failure_summary
                if collector and collector.failure_summary
                else "Codex JSONL lifecycle evidence was incomplete."
            )
        else:
            outcome = "succeeded"
            error_category = ""
            diagnostic_code = "codex_structured_evidence_verified"
            safe_summary = (
                "Structured Codex process and terminal-turn evidence verified a real CLI invocation; "
                + (
                    "actual resolved model identity was independently exposed by this Run."
                    if authorized_actual
                    else "actual resolved model identity was not independently exposed."
                )
            )

        process_evidence: dict[str, object] = {
            "process_observed": True,
            "process_execution_verified": bool(
                type(run.exit_code) is int
                and not runtime_interrupted
                and not run.timed_out
                and not run.cancelled
            ),
            "duration_ms": max(0, int(run.duration_ms or 0)),
            "isolated_worktree": bool(
                isinstance(result.get("boundary_confirmation"), dict)
                and result["boundary_confirmation"].get("isolated_worktree")
            ),
            "stdout_present": bool(run.stdout),
            "stderr_present": bool(run.stderr),
            "codex_jsonl_observed": bool(collector and collector.jsonl_observed),
            "codex_thread_started": bool(collector and collector.thread_started),
            "codex_turn_started": bool(collector and collector.turn_started),
            "codex_turn_completed": bool(collector and collector.turn_completed),
            "codex_turn_failed": bool(
                collector and collector.terminal_turn_status == "failed"
            ),
            "codex_lifecycle_conflict": bool(
                collector and collector.lifecycle_conflict
            ),
            "codex_turn_verified": bool(
                collector
                and collector.thread_started
                and collector.turn_started
                and collector.terminal_turn_status in {"completed", "failed"}
                and not collector.lifecycle_conflict
                and not collector.limit_exceeded
                and not collector.collection_incomplete
            ),
            "model_argument_observed": True,
            "model_identity_observed": bool(collector_identity_usable and authorized_actual),
            "actual_model_identity_verified": bool(
                collector_identity_usable and authorized_actual
            ),
            "model_identity_source": (
                collector.model_identity_source
                if collector_identity_usable and authorized_actual and collector
                else ""
            ),
            "model_reroute_observed": reroute_observed,
            "unsupported_model_routing_observed": bool(
                collector and collector.unsupported_model_routing_observed
            ),
            "final_agent_message_observed": bool(collector and collector.final_agent_message),
            "approved_pack_stdin_complete": pack_delivery_complete,
            "runtime_interrupted": runtime_interrupted,
            "jsonl_malformed_lines": collector.malformed_line_count if collector else 0,
            "jsonl_event_count": collector._valid_event_count if collector else 0,
            "command_execution_count": collector.command_execution_count if collector else 0,
            "file_change_count": collector.file_change_count if collector else 0,
            "command_shape": (
                "codex exec --model <requested-model> --json --sandbox workspace-write "
                "--ephemeral --ignore-user-config --color never -"
            ),
        }
        if type(run.exit_code) is int:
            process_evidence["exit_code"] = run.exit_code
        if collector and collector.thread_id_fingerprint:
            process_evidence["thread_id_fingerprint"] = collector.thread_id_fingerprint
        if collector and collector.turn_id_fingerprint:
            process_evidence["turn_id_fingerprint"] = collector.turn_id_fingerprint
        if collector and collector.executable_identity_fingerprint:
            process_evidence["executable_identity_fingerprint"] = (
                collector.executable_identity_fingerprint
            )
        if collector and collector.process_id_fingerprint:
            process_evidence["process_id_fingerprint"] = collector.process_id_fingerprint
        if collector and collector.connectivity_evidence_identity:
            process_evidence["connectivity_evidence_identity"] = (
                collector.connectivity_evidence_identity
            )

        provider_evidence = {
            "provider_response_observed": False,
            "model_identifier_match": bool(actual_identifier and authorized_actual),
            "requested_model_identifier_match": requested_identifier_match,
        }
        usage_metadata = dict(collector.usage) if collector else {}
        if "input_tokens" in usage_metadata and "output_tokens" in usage_metadata:
            usage_metadata["total_tokens"] = min(
                10**12,
                usage_metadata["input_tokens"] + usage_metadata["output_tokens"],
            )
        request_fingerprint = hashlib.sha256(pack_content.encode("utf-8")).hexdigest()
        response_fingerprint = hashlib.sha256(
            (run.stdout + "\0" + run.stderr).encode("utf-8")
        ).hexdigest()

        record_kwargs = {
            "model": model,
            "assignment": assignment,
            "task_id": run.task_id,
            "codex_run_id": run.id,
            "capability": "coding",
            "assignment_version": run.assignment_version,
            "invocation_ref": invocation_ref,
            "invocation_mode": "real",
            "outcome": outcome,
            "actual_invoked_model_identifier": actual_identifier,
            "process_evidence": process_evidence,
            "provider_evidence": provider_evidence,
            "usage_metadata": usage_metadata,
            "request_fingerprint": request_fingerprint,
            "response_fingerprint": response_fingerprint,
            "duration_ms": run.duration_ms,
            "timed_out": run.timed_out,
            "cancelled": run.cancelled,
            "output_truncated": run.output_truncated,
            "error_category": error_category,
            "diagnostic_code": diagnostic_code,
            "safe_summary": safe_summary,
            "started_at": run.started_at,
            "completed_at": run.finished_at,
        }
        try:
            evidence = record_model_invocation_evidence(session, **record_kwargs)
        except ValueError:
            if outcome != "succeeded":
                raise
            record_kwargs.update(
                outcome="failed",
                error_category="evidence_incomplete",
                diagnostic_code="evidence_validation_failed",
                safe_summary="Stored runtime state could not verify the real model invocation.",
            )
            evidence = record_model_invocation_evidence(session, **record_kwargs)
        return is_verified_real_invocation(evidence)

    def _record_verification_invocation_evidence(
        self,
        session: Session,
        run: CodexRun,
        verification: dict[str, object],
    ) -> bool:
        """Persist separate evidence for the read-only Verification process."""
        invocation_ref = f"codex-run-{run.id}-verification"
        existing = session.scalar(
            select(AIModelInvocationEvidence).where(
                AIModelInvocationEvidence.invocation_ref == invocation_ref
            )
        )
        if existing is not None:
            return is_verified_real_invocation(existing)
        assignment = run.verification_assignment
        requested_model = run.verification_model
        collector = verification.get("collector")
        if not isinstance(collector, _CodexJsonlEvidenceCollector):
            collector = None
        if assignment is None or requested_model is None:
            return False

        model = requested_model
        actual_identifier = ""
        authorized_actual = False
        reroute_observed = bool(collector and collector.rerouted_to)
        requested_identifier_match = (
            requested_model.provider_model_id == run.verification_model_identifier
        )
        exit_code = verification.get("exit_code")
        timed_out = bool(verification.get("timed_out"))
        cancelled = bool(verification.get("cancelled"))
        interrupted = bool(verification.get("runtime_interrupted"))
        output_truncated = bool(verification.get("output_truncated"))
        delivery_complete = bool(verification.get("delivery_complete"))
        structured_success = bool(collector and collector.structured_success)
        identity_usable = bool(
            collector
            and collector.actual_model_identity_verified
            and not collector.limit_exceeded
            and not collector.collection_incomplete
            and not collector.lifecycle_conflict
            and not collector.unsupported_model_routing_observed
            and structured_success
            and delivery_complete
            and not interrupted
            and not timed_out
            and not cancelled
            and not output_truncated
            and exit_code == 0
        )
        if identity_usable and collector is not None:
            candidate = collector.actual_model_identifier
            if candidate == run.verification_model_identifier:
                actual_identifier = candidate
                authorized_actual = requested_model.provider_model_id == candidate
            elif (
                collector.rerouted_from == run.verification_model_identifier
                and assignment.fallback_allowed
                and assignment.fallback_model is not None
                and assignment.fallback_model.provider_model_id == candidate
            ):
                model = assignment.fallback_model
                actual_identifier = candidate
                authorized_actual = True
            else:
                actual_identifier = candidate

        if interrupted:
            outcome, category, code, summary = (
                "failed",
                "interrupted",
                "runtime_shutdown",
                "Runtime shutdown interrupted the Verification process.",
            )
        elif cancelled:
            outcome, category, code, summary = (
                "cancelled",
                "cancelled",
                "owner_cancelled",
                "The Verification process was cancelled by the Owner.",
            )
        elif timed_out:
            outcome, category, code, summary = (
                "timed_out",
                "timeout",
                "process_timeout",
                "The Verification process timed out.",
            )
        elif exit_code != 0:
            outcome, category, code, summary = (
                "failed",
                (
                    collector.failure_classification
                    if collector and collector.failure_classification
                    else "process_failure"
                ),
                (
                    "turn_failed"
                    if collector and collector.terminal_turn_status == "failed"
                    else "nonzero_exit"
                ),
                (
                    collector.failure_summary
                    if collector and collector.failure_summary
                    else "The Verification process exited unsuccessfully."
                ),
            )
        elif identity_usable and actual_identifier and not authorized_actual:
            outcome, category, code, summary = (
                "failed",
                "routing_mismatch",
                "unapproved_model_reroute",
                "Verification reported a model reroute outside the approved fallback policy.",
            )
        elif output_truncated:
            outcome, category, code, summary = (
                "failed",
                "evidence_incomplete",
                "output_truncated",
                "Verification output was capped, so invocation proof is incomplete.",
            )
        elif not delivery_complete:
            outcome, category, code, summary = (
                "failed",
                "evidence_incomplete",
                "verification_prompt_delivery_incomplete",
                "The approved Verification request was not fully delivered.",
            )
        elif collector is None or collector.limit_exceeded:
            outcome, category, code, summary = (
                "failed",
                "evidence_incomplete",
                "verification_jsonl_limit_exceeded" if collector else "verification_jsonl_missing",
                "Bounded Verification JSONL evidence was unavailable or exceeded its safety limit.",
            )
        elif collector.collection_incomplete:
            outcome, category, code, summary = (
                "failed",
                "evidence_incomplete",
                "verification_jsonl_collection_incomplete",
                "Verification output collection did not finish cleanly.",
            )
        elif collector.lifecycle_conflict:
            outcome, category, code, summary = (
                "failed",
                "evidence_integrity",
                "verification_jsonl_lifecycle_conflict",
                "Verification JSONL did not preserve one ordered thread and turn identity.",
            )
        elif collector.unsupported_model_routing_observed:
            outcome, category, code, summary = (
                "failed",
                "routing_mismatch",
                "unsupported_model_routing_event",
                (
                    "Verification exposed an unsupported model-routing event, so the approved "
                    "target could not be verified."
                ),
            )
        elif not structured_success or not requested_identifier_match:
            outcome, category, code, summary = (
                "failed",
                (
                    collector.failure_classification
                    if collector and collector.failure_classification
                    else "evidence_incomplete"
                ),
                (
                    "turn_failed"
                    if collector and collector.terminal_turn_status == "failed"
                    else "verification_jsonl_incomplete"
                ),
                (
                    collector.failure_summary
                    if collector and collector.failure_summary
                    else "Verification JSONL lifecycle evidence was incomplete."
                ),
            )
        else:
            outcome, category, code, summary = (
                "succeeded",
                "",
                "verification_structured_evidence_verified",
                "Structured evidence verified the separate Verification invocation; "
                + (
                    "actual resolved model identity was independently exposed by this Run."
                    if authorized_actual
                    else "actual resolved model identity was not independently exposed."
                ),
            )

        stdout = str(verification.get("stdout", ""))
        stderr = str(verification.get("stderr", ""))
        prompt = str(verification.get("prompt", ""))
        process_evidence: dict[str, object] = {
            "process_observed": bool(verification.get("process_spawned")),
            "process_execution_verified": bool(
                verification.get("process_spawned")
                and type(exit_code) is int
                and not interrupted
                and not timed_out
                and not cancelled
            ),
            "duration_ms": max(0, int(verification.get("duration_ms") or 0)),
            "isolated_worktree": bool(run.worktree_path),
            "read_only_sandbox": True,
            "stdout_present": bool(stdout),
            "stderr_present": bool(stderr),
            "codex_jsonl_observed": bool(collector and collector.jsonl_observed),
            "codex_thread_started": bool(collector and collector.thread_started),
            "codex_turn_started": bool(collector and collector.turn_started),
            "codex_turn_completed": bool(collector and collector.turn_completed),
            "codex_turn_failed": bool(
                collector and collector.terminal_turn_status == "failed"
            ),
            "codex_lifecycle_conflict": bool(
                collector and collector.lifecycle_conflict
            ),
            "codex_turn_verified": bool(
                collector
                and collector.thread_started
                and collector.turn_started
                and collector.terminal_turn_status in {"completed", "failed"}
                and not collector.lifecycle_conflict
                and not collector.limit_exceeded
                and not collector.collection_incomplete
            ),
            "model_argument_observed": True,
            "model_identity_observed": bool(identity_usable and authorized_actual),
            "actual_model_identity_verified": bool(identity_usable and authorized_actual),
            "model_identity_source": (
                collector.model_identity_source
                if identity_usable and authorized_actual and collector
                else ""
            ),
            "model_reroute_observed": reroute_observed,
            "unsupported_model_routing_observed": bool(
                collector and collector.unsupported_model_routing_observed
            ),
            "final_agent_message_observed": bool(collector and collector.final_agent_message),
            "approved_pack_stdin_complete": delivery_complete,
            "runtime_interrupted": interrupted,
            "jsonl_malformed_lines": collector.malformed_line_count if collector else 0,
            "jsonl_event_count": collector._valid_event_count if collector else 0,
            "command_execution_count": collector.command_execution_count if collector else 0,
            "file_change_count": collector.file_change_count if collector else 0,
            "command_shape": (
                "codex exec --model <requested-model> --json --sandbox read-only "
                "--ephemeral --ignore-user-config --color never -"
            ),
        }
        checks = verification.get("checks")
        if isinstance(checks, dict):
            for key in (
                "verification_verdict_observed",
                "workspace_unchanged_after_verification",
                "changed_files_checked",
                "unexpected_files_checked",
                "exact_content_checked",
                "test_evidence_checked",
                "git_boundary_checked",
                "remote_boundary_checked",
            ):
                if type(checks.get(key)) is bool:
                    process_evidence[key] = checks[key]
        if type(exit_code) is int:
            process_evidence["exit_code"] = exit_code
        if collector and collector.thread_id_fingerprint:
            process_evidence["thread_id_fingerprint"] = collector.thread_id_fingerprint
        if collector and collector.turn_id_fingerprint:
            process_evidence["turn_id_fingerprint"] = collector.turn_id_fingerprint
        if collector and collector.executable_identity_fingerprint:
            process_evidence["executable_identity_fingerprint"] = (
                collector.executable_identity_fingerprint
            )
        if collector and collector.process_id_fingerprint:
            process_evidence["process_id_fingerprint"] = collector.process_id_fingerprint
        if collector and collector.connectivity_evidence_identity:
            process_evidence["connectivity_evidence_identity"] = (
                collector.connectivity_evidence_identity
            )
        usage = dict(collector.usage) if collector else {}
        if "input_tokens" in usage and "output_tokens" in usage:
            usage["total_tokens"] = min(10**12, usage["input_tokens"] + usage["output_tokens"])
        evidence = record_model_invocation_evidence(
            session,
            model=model,
            assignment=assignment,
            task_id=run.task_id,
            codex_run_id=run.id,
            capability="verification",
            assignment_version=run.assignment_version,
            invocation_ref=invocation_ref,
            invocation_mode="real",
            outcome=outcome,
            actual_invoked_model_identifier=actual_identifier,
            process_evidence=process_evidence,
            provider_evidence={
                "provider_response_observed": False,
                "model_identifier_match": bool(actual_identifier and authorized_actual),
                "requested_model_identifier_match": requested_identifier_match,
            },
            usage_metadata=usage,
            request_fingerprint=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            response_fingerprint=hashlib.sha256((stdout + "\0" + stderr).encode("utf-8")).hexdigest(),
            duration_ms=int(verification.get("duration_ms") or 0),
            timed_out=timed_out,
            cancelled=cancelled,
            output_truncated=output_truncated,
            error_category=category,
            diagnostic_code=code,
            safe_summary=summary,
            started_at=verification.get("_started_at"),
            completed_at=verification.get("_completed_at"),
        )
        return is_verified_real_invocation(evidence)

    def _record_incomplete_spawn_evidence(
        self,
        session: Session,
        run: CodexRun,
        *,
        outcome: str = "failed",
        error_category: str = "interrupted",
        diagnostic_code: str,
        safe_summary: str,
    ) -> None:
        """Terminalize an observed spawn when structured output cannot be recovered."""
        invocation_ref = f"codex-run-{run.id}-coding"
        if session.scalar(
            select(AIModelInvocationEvidence).where(
                AIModelInvocationEvidence.invocation_ref == invocation_ref
            )
        ):
            return
        if run.execution_model is None or run.execution_assignment is None or run.pack is None:
            session.add(
                AuditEvent(
                    action="model_invocation_evidence_blocked",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Interrupted run is missing its persisted execution target.",
                )
            )
            return
        process_evidence: dict[str, object] = {
            "process_observed": True,
            "duration_ms": max(0, int(run.duration_ms or 0)),
            "isolated_worktree": bool(run.worktree_path),
            "stdout_present": bool(run.stdout),
            "stderr_present": bool(run.stderr),
            "codex_jsonl_observed": False,
            "codex_thread_started": False,
            "codex_turn_completed": False,
            "model_argument_observed": True,
            "model_identity_observed": False,
            "model_reroute_observed": False,
            "approved_pack_stdin_complete": False,
            "runtime_interrupted": diagnostic_code == "runtime_shutdown",
        }
        if type(run.exit_code) is int:
            process_evidence["exit_code"] = run.exit_code
        record_model_invocation_evidence(
            session,
            model=run.execution_model,
            assignment=run.execution_assignment,
            task_id=run.task_id,
            codex_run_id=run.id,
            capability="coding",
            assignment_version=run.assignment_version,
            invocation_ref=invocation_ref,
            invocation_mode="real",
            outcome=outcome,
            actual_invoked_model_identifier="",
            process_evidence=process_evidence,
            provider_evidence={
                "provider_response_observed": False,
                "model_identifier_match": False,
            },
            request_fingerprint=hashlib.sha256(run.pack.content.encode("utf-8")).hexdigest(),
            response_fingerprint=hashlib.sha256(
                (run.stdout + "\0" + run.stderr).encode("utf-8")
            ).hexdigest(),
            duration_ms=run.duration_ms,
            timed_out=run.timed_out,
            cancelled=run.cancelled,
            output_truncated=run.output_truncated,
            error_category=error_category,
            diagnostic_code=diagnostic_code,
            safe_summary=safe_summary,
            started_at=run.started_at,
            completed_at=run.finished_at,
        )

    def _is_cancel_requested(self, run_id: int) -> bool:
        return self._stop_reason(run_id) is not None

    def _stop_reason(self, run_id: int) -> str | None:
        with self._lock:
            if run_id in self._cancel_requested:
                return "owner_cancelled"
            if self._stopping:
                return "runtime_shutdown"
            return None

    def _finish_cancelled(self, session: Session, run: CodexRun) -> None:
        if self._stop_reason(run.id) == "runtime_shutdown":
            run.status = "failed" if run.process_spawned or run.verification_process_spawned else "blocked"
            run.cancelled = False
            run.finished_at = utc_now()
            run.owner_summary = "Runtime shutdown stopped the accepted Codex Run; the terminal state is persisted."
            run.task.status = "needs_review"
            session.add(
                AuditEvent(
                    action="codex_run_runtime_interrupted",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details="Runtime shutdown stopped Codex execution before process start.",
                )
            )
            session.commit()
            return
        run.status = "cancelled"
        run.cancelled = True
        run.finished_at = utc_now()
        run.task.status = "cancelled"
        session.add(
            AuditEvent(
                action="codex_run_cancelled",
                entity_type="codex_run",
                entity_id=run.id,
                details="Owner cancelled Codex execution before process start.",
            )
        )
        session.commit()

    def _finish_pack_blocked(self, session: Session, run: CodexRun, *, reason: str) -> None:
        run.status = "blocked"
        run.finished_at = utc_now()
        run.owner_summary = "Blocked before process start: approved execution conditions are no longer satisfied."
        run.stderr = self._sanitize_process_output(reason[:2000])
        run.verification_status = "not_started"
        run.verification_summary = "Verification was not started because Coding was blocked."
        run.task.status = "blocked"
        if run.pack is not None and run.pack.status == "approved":
            run.pack.status = "invalidated"
            run.pack.invalidated_at = utc_now()
        session.add(
            AuditEvent(
                action="codex_run_blocked",
                entity_type="codex_run",
                entity_id=run.id,
                details=f"Approved pack was no longer executable before process start: {reason[:500]}",
            )
        )
        session.commit()

    def _finish_source_snapshot_unavailable(
        self,
        session: Session,
        run: CodexRun,
        *,
        diagnostic: str,
        cleanup_verified: bool | None = None,
        cleanup_code: str = "",
    ) -> None:
        """Persist one truthful pre-launch blocker without result evidence."""

        run.status = "blocked"
        run.owner_summary = (
            "Source snapshot unavailable. Regenerate Codex Pack."
            if cleanup_verified is not False
            else (
                "Source snapshot unavailable. Isolated workspace cleanup could "
                "not be verified. Review blocker evidence, then Regenerate "
                "Codex Pack."
            )
        )
        safe_diagnostic = _bounded_event_text(diagnostic, maximum=400)
        run.stderr = (
            safe_diagnostic
            if cleanup_verified is not False
            else _bounded_event_text(
                f"{safe_diagnostic} cleanup={cleanup_code or 'CLEANUP_UNVERIFIED'}",
                maximum=500,
            )
        )
        run.finished_at = utc_now()
        run.verification_status = "not_started"
        run.verification_summary = (
            "Verification was not started because the approved source snapshot "
            "was unavailable."
        )
        run.task.status = "blocked"
        if run.pack is not None and run.pack.status == "approved":
            run.pack.status = "invalidated"
            run.pack.invalidated_at = utc_now()
            session.add(
                AuditEvent(
                    action="codex_pack_approval_invalidated",
                    entity_type="codex_instruction_pack",
                    entity_id=run.pack.id,
                    details=(
                        "code=SOURCE_SNAPSHOT_UNAVAILABLE; exact approved Pack "
                        "invalidated after pre-launch snapshot preparation failed."
                    ),
                )
            )
        if cleanup_verified is False:
            session.add(
                AuditEvent(
                    action="codex_unstarted_worktree_cleanup_unverified",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=(
                        "code=SOURCE_SNAPSHOT_UNAVAILABLE; "
                        f"cleanup={cleanup_code or 'CLEANUP_UNVERIFIED'}"
                    ),
                )
            )
        try:
            # Monitor state is a recoverable projection. Isolate it in a
            # savepoint so a projection persistence error cannot roll back the
            # authoritative Run, Pack invalidation, or blocker audit.
            with session.begin_nested():
                monitor = ensure_run_monitor(
                    session,
                    int(run.pack.approved_by_user_id),
                    run,
                )
                observe_monitor(
                    session,
                    monitor,
                    state="RESULT_UNAVAILABLE",
                    recovery_state="RESULT_UNAVAILABLE",
                    failure_code="SOURCE_SNAPSHOT_UNAVAILABLE",
                    safe_summary="Source snapshot unavailable. Regenerate Codex Pack.",
                )
        except (
            ResultIntakeError,
            OSError,
            RuntimeError,
            SQLAlchemyError,
            TypeError,
            ValueError,
        ) as monitor_exc:
            session.add(
                AuditEvent(
                    action="codex_run_monitor_update_blocked",
                    entity_type="codex_run",
                    entity_id=run.id,
                    details=(
                        "code=SOURCE_SNAPSHOT_UNAVAILABLE; "
                        f"monitor={type(monitor_exc).__name__}"
                    ),
                )
            )
        session.add(
            AuditEvent(
                action="codex_run_blocked",
                entity_type="codex_run",
                entity_id=run.id,
                details=(
                    "code=SOURCE_SNAPSHOT_UNAVAILABLE; "
                    "approved source snapshot preparation failed."
                ),
            )
        )
        session.commit()

    def _audit_evidence_persistence_failure(
        self,
        run_id: int,
        *,
        context: str,
        failure_type: str,
    ) -> None:
        try:
            with self.factory() as session:
                session.add(
                    AuditEvent(
                        action="model_invocation_evidence_persistence_failed",
                        entity_type="codex_run",
                        entity_id=run_id,
                        details=f"failure_type={failure_type}; context={context}",
                    )
                )
                session.commit()
        except Exception:
            return

    def _mark_worker_failure(self, run_id: int, failure_type: str) -> None:
        with self._lock:
            process = self._processes.pop(run_id, None)
        if process and process.poll() is None:
            self._stop_process_tree(process, force=True)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        spawned = False
        try:
            with self.factory() as session:
                run = session.get(CodexRun, run_id)
                if not run or run.status not in {"queued", "starting", "running", "verifying"}:
                    return
                if process is not None:
                    # A local Popen object is definitive spawn evidence even if
                    # committing the ordinary spawn marker failed.
                    run.process_spawned = True
                spawned = run.process_spawned
                run.status = "failed" if run.process_spawned or run.verification_process_spawned else "blocked"
                run.finished_at = utc_now()
                if process is not None and type(process.returncode) is int:
                    run.exit_code = process.returncode
                run.owner_summary = "TWOS stopped the Codex process after an internal execution error. Review is required."
                run.task.status = "needs_review"
                session.add(
                    AuditEvent(
                        action="codex_run_internal_failure",
                        entity_type="codex_run",
                        entity_id=run.id,
                        details=f"failure_type={failure_type}",
                    )
                )
                session.commit()
        except Exception:
            # Do not let secondary persistence failures resurrect a child process.
            return
        if spawned:
            try:
                with self.factory() as evidence_session:
                    run = evidence_session.get(CodexRun, run_id)
                    if run is None:
                        return
                    self._record_incomplete_spawn_evidence(
                        evidence_session,
                        run,
                        diagnostic_code="worker_internal_failure",
                        safe_summary="An internal worker failure interrupted Codex evidence finalization.",
                    )
                    evidence_session.commit()
            except Exception as exc:
                self._audit_evidence_persistence_failure(
                    run_id,
                    context="worker_internal_failure",
                    failure_type=type(exc).__name__,
                )
