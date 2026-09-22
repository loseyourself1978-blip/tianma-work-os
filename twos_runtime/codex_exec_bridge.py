from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Mapping, Protocol, Sequence


BRIDGE_POLICY = "twos.codex_exec_bridge.vol18.004.v1"
TICKET_SCHEMA = "twos.codex_exec_bridge.ticket.v1"
TICKET_SEAL_SCHEMA = "twos.codex_exec_bridge.ticket_seal.v1"
STATE_SCHEMA = "twos.codex_exec_bridge.state.v1"
TERMINAL_RECEIPT_SCHEMA = "twos.codex_exec_bridge.terminal_receipt.v1"
LAUNCH_SCHEMA = "twos.codex_exec_bridge.launch.v1"
CANCEL_SCHEMA = "twos.codex_exec_bridge.cancel.v1"
FINAL_MESSAGE_ABSENCE_SCHEMA = "twos.codex_exec_bridge.final_message_absence.v1"
FINAL_RESULT_SELECTION_RULE = "last-structurally-valid-before-terminal.v1"
FINAL_RESULT_CANONICALIZATION_RULE = "twos.final-result-canonicalization.v1"
JSONL_CLASSIFIER_RULE = "codex-jsonl-0.144.4.v2"

OWNER_DIRECTORY_MODE = 0o700
OWNER_FILE_MODE = 0o600
DEFAULT_OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_LIMIT_BYTES = 64 * 1024 * 1024
MAX_STDIN_BYTES = 16 * 1024 * 1024
MAX_PROTECTED_JSON_BYTES = 1024 * 1024
MAX_FINAL_MESSAGE_BYTES = 1024 * 1024
MAX_JSONL_LINE_BYTES = 256 * 1024
MAX_JSONL_EVENT_TYPES = 64
MAX_UNKNOWN_EVENT_SAMPLES = 20
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 1.0
PROCESS_STOP_GRACE_SECONDS = 2.0
SIDECAR_LAUNCH_RECORD_WAIT_SECONDS = 5.0
STREAM_SETTLEMENT_SECONDS = 3.0
STREAM_FORCED_STOP_SECONDS = 1.0
FINAL_MESSAGE_SETTLEMENT_SECONDS = 1.0
FINAL_MESSAGE_SETTLEMENT_POLL_SECONDS = 0.025
INTERNAL_PUBLICATION_SETTLEMENT_SECONDS = 0.25
INTERNAL_PUBLICATION_SETTLEMENT_POLL_SECONDS = 0.002
DEFAULT_ENVIRONMENT_KEYS = (
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
    "OPENAI_API_KEY",
    "CODEX_ACCESS_TOKEN",
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

_SAFE_PHASE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PHASE = frozenset({"coding", "verification"})
_SAFE_MODEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
_SAFE_ENVIRONMENT_KEY = frozenset(DEFAULT_ENVIRONMENT_KEYS)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_HISTOGRAM_KEYS = ("1-1024", "1025-4096", "4097-8192", "8193+")
_SENSITIVE_ENVIRONMENT_KEY = re.compile(
    r"(?:PASSWORD|PASSPHRASE|SECRET|CREDENTIAL|TOKEN|API_KEY|PRIVATE_KEY|"
    r"AUTHORIZATION|COOKIE)",
    re.IGNORECASE,
)
_PERSISTED_TOKEN_PATTERNS = (
    re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|"
        rb"github_pat_[A-Za-z0-9_]{20,}|"
        rb"xox[baprs]-[A-Za-z0-9-]{12,}|AKIA[A-Z0-9]{16})\b"
    ),
    re.compile(
        rb"(?i)\b(?:password|passphrase|client[_ -]?secret|"
        rb"session[_ -]?token|access[_ -]?token|refresh[_ -]?token|"
        rb"api[_ -]?key|authorization|cookie|OPENAI_API_KEY|"
        rb"CODEX_ACCESS_TOKEN|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|"
        rb"GH_TOKEN|GITHUB_TOKEN)\s*[:=]\s*"
        rb"[^\s,;\"\\}\]]+"
    ),
    re.compile(
        rb"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
        rb"-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
)
_PERSISTED_SENSITIVE_JSON_FIELD = re.compile(
    rb'(?i)("(?:password|passphrase|secret|credential|token|api[_-]?key|'
    rb'private[_-]?key|authorization|cookie|OPENAI_API_KEY|CODEX_ACCESS_TOKEN|'
    rb'AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|GH_TOKEN|GITHUB_TOKEN)"'
    rb'\s*:\s*")((?:\\.|[^"\\])*)(")'
)
_PERSISTED_CREDENTIAL_URL = re.compile(
    rb"(?i)([A-Za-z][A-Za-z0-9+.-]{0,31}://)([^/@\s:]+:[^/@\s]+)(@)"
)


def _masked_bytes(length: int) -> bytes:
    return b"x" * max(0, length)


def _environment_value_is_invalid(key: str, value: object) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return True
    if not _SENSITIVE_ENVIRONMENT_KEY.search(key):
        return False
    # Very short credential-shaped values cannot be safely replaced as raw
    # substrings without corrupting ordinary JSON/output bytes. Reject them
    # before spawn instead of allowing any value to escape durable redaction.
    return bool(
        "\r" in value
        or "\n" in value
        or (value and len(value.encode("utf-8")) < 8)
    )


def _persistent_secret_values(environment: Mapping[str, str]) -> tuple[bytes, ...]:
    values: set[bytes] = set()
    for key, value in environment.items():
        if _environment_value_is_invalid(key, value):
            raise CodexExecBridgeError(
                "ENVIRONMENT_VALUE_INVALID",
                "The detached environment contained an invalid value.",
            )
        if not (_SENSITIVE_ENVIRONMENT_KEY.search(key) and value):
            continue
        values.add(value.encode("utf-8"))
        # JSONL string escaping can change the byte spelling of a secret. Bind
        # both standard JSON variants so quotes, slashes, control characters,
        # and non-ASCII values are masked before any event reaches disk.
        values.add(json.dumps(value)[1:-1].encode("utf-8"))
        values.add(
            json.dumps(value, ensure_ascii=False)[1:-1].encode("utf-8")
        )
    return tuple(sorted(values, key=len, reverse=True))


def _redact_persisted_output(payload: bytes, secrets: Sequence[bytes] = ()) -> bytes:
    """Mask credentials without changing stream byte offsets or JSON shape."""
    redacted = payload
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, _masked_bytes(len(secret)))
    for pattern in _PERSISTED_TOKEN_PATTERNS:
        redacted = pattern.sub(
            lambda match: _masked_bytes(len(match.group(0))), redacted
        )
    redacted = _PERSISTED_SENSITIVE_JSON_FIELD.sub(
        lambda match: (
            match.group(1)
            + _masked_bytes(len(match.group(2)))
            + match.group(3)
        ),
        redacted,
    )
    redacted = _PERSISTED_CREDENTIAL_URL.sub(
        lambda match: (
            match.group(1)
            + _masked_bytes(len(match.group(2)))
            + match.group(3)
        ),
        redacted,
    )
    if len(redacted) != len(payload):
        raise CodexExecBridgeError(
            "OUTPUT_REDACTION_INVALID",
            "Credential redaction changed the durable stream boundary.",
        )
    return redacted


class _PersistentOutputRedactor:
    """Line-aware bounded redaction before any process output reaches disk."""

    def __init__(self, secrets: Sequence[bytes]) -> None:
        self.secrets = tuple(secrets)
        self.pending = bytearray()
        self.overlap = max(
            (MAX_JSONL_LINE_BYTES, *(len(secret) for secret in self.secrets)),
        )

    def feed(self, chunk: bytes) -> bytes:
        self.pending.extend(chunk)
        newline = self.pending.rfind(b"\n")
        if newline >= 0:
            boundary = newline + 1
        elif len(self.pending) > self.overlap * 2:
            boundary = len(self.pending) - self.overlap
        else:
            return b""
        value = bytes(self.pending[:boundary])
        del self.pending[:boundary]
        return _redact_persisted_output(value, self.secrets)

    def finish(self) -> bytes:
        value = bytes(self.pending)
        self.pending.clear()
        return _redact_persisted_output(value, self.secrets)


class CodexExecBridgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class CollectorProtocol(Protocol):
    def feed(self, chunk: bytes) -> None: ...

    def finish(self) -> None: ...

    def mark_incomplete(self) -> None: ...


@dataclass(frozen=True)
class ExecutionIdentity:
    owner_id: int
    run_id: int
    task_id: int
    task_version: int
    pack_id: int
    pack_version: int
    coding_assignment_id: int
    coding_assignment_version: int
    verification_assignment_id: int
    verification_assignment_version: int
    routing_snapshot_identity: str
    source_snapshot_identity: str
    connectivity_evidence_identity: str
    requested_model_identifier: str
    executable_fingerprint: str
    execution_location_identity: str
    source_remote_fingerprint: str
    git_boundary_fingerprint: str
    workspace_snapshot_digest: str
    pre_verification_workspace_digest: str | None = None

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        _validate_execution_identity(value)
        return value


@dataclass(frozen=True)
class ExecutionHandle:
    spool_root: Path
    phase_directory: Path
    ticket_path: Path
    ticket_digest: str
    phase_key: str


@dataclass(frozen=True)
class LaunchInfo:
    process_id: int
    process_start_identity: str
    ticket_digest: str
    launched_at: str


@dataclass(frozen=True)
class ReplayResult:
    bytes_replayed: int
    stdout_truncated: bool
    agent_message_event_replayed: bool
    terminal_event_replayed: bool
    collection_incomplete: bool
    omitted_stdout_bytes: int
    terminal_state: str
    ticket_digest: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _reject_json_constant(token: str) -> object:
    raise ValueError(f"unsupported JSON constant: {token}")


def _normalize_result_text(value: str) -> str:
    """Normalize only transport line endings and one CLI terminal newline."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:-1] if normalized.endswith("\n") else normalized


def _canonical_result_text(
    value: str,
    *,
    phase: str,
) -> tuple[bytes, str, str]:
    """Return deterministic comparison bytes and phase-contract status.

    The JSONL result and ``--output-last-message`` sidecar may serialize the
    same JSON object differently. Plain text preserves all meaningful
    whitespace and Unicode bytes; only line endings and one optional CLI
    terminal newline are normalized. Schema status is evidence only; the
    higher layer remains authoritative for full contract validation and Run
    identity.
    """

    normalized_text = _normalize_result_text(value)
    json_text = normalized_text[1:] if normalized_text.startswith("\ufeff") else normalized_text
    try:
        decoded = json.loads(json_text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        schema_status = (
            "INVALID_JSON"
            if json_text.lstrip().startswith(("{", "["))
            else "NOT_JSON"
        )
        return normalized_text.encode("utf-8"), "TEXT", schema_status

    canonical = json.dumps(
        decoded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if not isinstance(decoded, dict):
        return canonical, "JSON", "UNRECOGNIZED_SCHEMA"
    if phase == "coding":
        if decoded.get("schema") != "twos.coding_handoff.v1":
            schema_status = "UNRECOGNIZED_SCHEMA"
        elif decoded.get("status") != "completed":
            schema_status = "INVALID_STATUS"
        elif not isinstance(decoded.get("summary"), str) or not str(
            decoded.get("summary")
        ).strip():
            schema_status = "INVALID_SHAPE"
        else:
            schema_status = "VALID"
    elif phase == "verification":
        if decoded.get("schema") != "twos.verification.v1":
            schema_status = "UNRECOGNIZED_SCHEMA"
        elif decoded.get("verdict") not in {"pass", "fail"}:
            schema_status = "INVALID_STATUS"
        else:
            schema_status = "VALID"
    else:
        schema_status = "UNRECOGNIZED_SCHEMA"
    return canonical, "JSON", schema_status


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_plain_text(value: object, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CodexExecBridgeError("IDENTITY_INVALID", f"{field} is missing or invalid.")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise CodexExecBridgeError("IDENTITY_INVALID", f"{field} contains unsafe text.")
    return value


def _validate_execution_identity(value: Mapping[str, object]) -> None:
    integer_fields = (
        "owner_id",
        "run_id",
        "task_id",
        "task_version",
        "pack_id",
        "pack_version",
        "coding_assignment_id",
        "coding_assignment_version",
        "verification_assignment_id",
        "verification_assignment_version",
    )
    for field in integer_fields:
        candidate = value.get(field)
        if type(candidate) is not int or candidate <= 0:
            raise CodexExecBridgeError("IDENTITY_INVALID", f"{field} must be a positive integer.")
    for field in (
        "routing_snapshot_identity",
        "source_snapshot_identity",
        "connectivity_evidence_identity",
        "executable_fingerprint",
        "execution_location_identity",
    ):
        _validate_plain_text(value.get(field), field)
    requested_model = _validate_plain_text(
        value.get("requested_model_identifier"),
        "requested_model_identifier",
        maximum=240,
    )
    if not _SAFE_MODEL_IDENTIFIER.fullmatch(requested_model):
        raise CodexExecBridgeError(
            "IDENTITY_INVALID",
            "requested_model_identifier is malformed.",
        )
    for field in (
        "source_remote_fingerprint",
        "git_boundary_fingerprint",
        "workspace_snapshot_digest",
    ):
        candidate = value.get(field)
        if not isinstance(candidate, str) or not _SHA256.fullmatch(candidate):
            raise CodexExecBridgeError(
                "PREFLIGHT_EVIDENCE_INVALID",
                f"{field} must be a safe SHA-256 fingerprint.",
            )
    pre_verification = value.get("pre_verification_workspace_digest")
    if pre_verification is not None and (
        not isinstance(pre_verification, str)
        or not _SHA256.fullmatch(pre_verification)
    ):
        raise CodexExecBridgeError(
            "PREFLIGHT_EVIDENCE_INVALID",
            "pre_verification_workspace_digest must be a safe SHA-256 fingerprint when present.",
        )


def _path_contains_traversal(path: Path) -> bool:
    return any(part in {"", ".", ".."} for part in path.parts[1:])


def _assert_no_symlink_components(path: Path, *, include_leaf: bool = True) -> None:
    if not path.is_absolute() or _path_contains_traversal(path):
        raise CodexExecBridgeError("PATH_INVALID", "The protected path must be absolute and normalized.")
    parts = path.parts if include_leaf else path.parts[:-1]
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            observed = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(observed.st_mode):
            raise CodexExecBridgeError("SYMLINK_REJECTED", "A protected path contains a symbolic link.")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_owner_directory(path: Path) -> os.stat_result:
    _assert_no_symlink_components(path)
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise CodexExecBridgeError("DIRECTORY_UNAVAILABLE", "The protected directory is unavailable.") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise CodexExecBridgeError("DIRECTORY_INVALID", "The protected location is not a directory.")
    if observed.st_uid != os.getuid():
        raise CodexExecBridgeError("DIRECTORY_OWNER_MISMATCH", "The protected directory has the wrong owner.")
    if stat.S_IMODE(observed.st_mode) != OWNER_DIRECTORY_MODE:
        raise CodexExecBridgeError("DIRECTORY_MODE_INVALID", "The protected directory must use owner-only permissions.")
    return observed


def prepare_spool_root(
    spool_root: str | os.PathLike[str],
    *,
    forbidden_roots: Sequence[str | os.PathLike[str]] = (),
) -> Path:
    root = Path(spool_root)
    if not root.is_absolute() or _path_contains_traversal(root):
        raise CodexExecBridgeError("SPOOL_PATH_INVALID", "The spool root must be an absolute normalized path.")
    _assert_no_symlink_components(root.parent)
    for forbidden in forbidden_roots:
        forbidden_path = Path(forbidden)
        if not forbidden_path.is_absolute():
            raise CodexExecBridgeError("SPOOL_PATH_INVALID", "A forbidden root was not absolute.")
        forbidden_resolved = forbidden_path.resolve(strict=True)
        if _is_within(root.resolve(strict=False), forbidden_resolved):
            raise CodexExecBridgeError("SPOOL_INSIDE_REPOSITORY", "The execution spool must be outside the repository.")
    try:
        os.mkdir(root, OWNER_DIRECTORY_MODE)
        os.chmod(root, OWNER_DIRECTORY_MODE, follow_symlinks=False)
        parent_fd = os.open(root.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise CodexExecBridgeError("SPOOL_CREATE_FAILED", "The protected spool root could not be created.") from exc
    _validate_owner_directory(root)
    return root


def _validate_phase_directory(root: Path, phase_directory: Path) -> os.stat_result:
    _validate_owner_directory(root)
    if phase_directory.parent != root or not _SAFE_PHASE_KEY.fullmatch(phase_directory.name):
        raise CodexExecBridgeError("PHASE_PATH_INVALID", "The phase directory is outside the protected spool.")
    return _validate_owner_directory(phase_directory)


def _internal_publication_alias_matches(
    path: Path,
    observed: os.stat_result,
) -> bool:
    """Recognize only this bridge's transient link-then-unlink publication.

    Immutable records are published by linking one owner-only temporary file
    to the final leaf and immediately unlinking the temporary name.  During
    those two syscalls the one inode has exactly two names.  A protected
    reader may settle that bounded internal window, but arbitrary aliases,
    extra links, foreign owners/modes, and other directories remain blocked.
    """

    if observed.st_nlink != 2:
        return False
    expression = re.compile(
        rf"^\.{re.escape(path.name)}\.[0-9a-f]{{32}}\.publish$"
    )
    matches = 0
    try:
        with os.scandir(path.parent) as entries:
            for entry in entries:
                if not expression.fullmatch(entry.name):
                    continue
                try:
                    candidate = os.lstat(path.parent / entry.name)
                except FileNotFoundError:
                    # A losing concurrent publisher may remove its own
                    # different inode while this directory scan is active.
                    continue
                if (
                    candidate.st_dev != observed.st_dev
                    or candidate.st_ino != observed.st_ino
                ):
                    continue
                if (
                    not stat.S_ISREG(candidate.st_mode)
                    or candidate.st_uid != observed.st_uid
                    or stat.S_IMODE(candidate.st_mode)
                    != stat.S_IMODE(observed.st_mode)
                    or candidate.st_nlink != 2
                ):
                    return False
                matches += 1
    except OSError:
        return False
    return matches == 1


def _safe_regular_file_stat(path: Path, *, expected_mode: int = OWNER_FILE_MODE) -> os.stat_result:
    _assert_no_symlink_components(path)
    deadline: float | None = None
    settled_identity: tuple[int, int] | None = None
    while True:
        try:
            observed = os.lstat(path)
        except OSError as exc:
            raise CodexExecBridgeError("PROTECTED_FILE_UNAVAILABLE", "A protected execution file is unavailable.") from exc
        if not stat.S_ISREG(observed.st_mode):
            raise CodexExecBridgeError("PROTECTED_FILE_INVALID", "A protected execution file is not regular.")
        if observed.st_uid != os.getuid():
            raise CodexExecBridgeError("PROTECTED_FILE_OWNER_MISMATCH", "A protected execution file has the wrong owner.")
        if stat.S_IMODE(observed.st_mode) != expected_mode:
            raise CodexExecBridgeError("PROTECTED_FILE_MODE_INVALID", "A protected execution file has unsafe permissions.")
        identity = (observed.st_dev, observed.st_ino)
        if settled_identity is not None and identity != settled_identity:
            raise CodexExecBridgeError(
                "PROTECTED_FILE_REPLACED",
                "A protected execution file changed during publication settlement.",
            )
        if observed.st_nlink == 1:
            return observed
        if observed.st_nlink == 0:
            # APFS can finish lstat on the old inode while an atomic rename
            # unlinks it. Never open/accept that observation. Only the mutable
            # state reader may retry this replacement, with all checks anew;
            # immutable records still fail closed.
            raise CodexExecBridgeError(
                "PROTECTED_FILE_REPLACED",
                "A protected execution file was unlinked during observation.",
            )
        if observed.st_nlink != 2:
            raise CodexExecBridgeError("HARDLINK_REJECTED", "A hard-linked protected execution file is not allowed.")
        if not _internal_publication_alias_matches(path, observed):
            # The publisher may have unlinked its sibling between lstat and
            # directory enumeration. Re-read once before treating the stale
            # two-link observation as an external alias.
            try:
                refreshed = os.lstat(path)
            except OSError as exc:
                raise CodexExecBridgeError(
                    "PROTECTED_FILE_UNAVAILABLE",
                    "A protected execution file is unavailable.",
                ) from exc
            if (
                refreshed.st_dev == observed.st_dev
                and refreshed.st_ino == observed.st_ino
                and refreshed.st_nlink == 1
            ):
                return refreshed
            raise CodexExecBridgeError("HARDLINK_REJECTED", "A hard-linked protected execution file is not allowed.")
        now = time.monotonic()
        if deadline is None:
            deadline = now + INTERNAL_PUBLICATION_SETTLEMENT_SECONDS
            settled_identity = identity
        if now >= deadline:
            raise CodexExecBridgeError("HARDLINK_REJECTED", "A hard-linked protected execution file is not allowed.")
        time.sleep(
            min(
                INTERNAL_PUBLICATION_SETTLEMENT_POLL_SECONDS,
                max(0.0, deadline - now),
            )
        )


def _open_protected_file(path: Path) -> tuple[int, os.stat_result]:
    before = _safe_regular_file_stat(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CodexExecBridgeError("PROTECTED_FILE_OPEN_FAILED", "A protected execution file could not be opened.") from exc
    after = os.fstat(fd)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or after.st_nlink != 1
        or not stat.S_ISREG(after.st_mode)
    ):
        os.close(fd)
        raise CodexExecBridgeError("PROTECTED_FILE_REPLACED", "A protected execution file changed while opening.")
    return fd, after


def _read_protected_bytes(path: Path, *, maximum: int) -> tuple[bytes, os.stat_result]:
    fd, observed = _open_protected_file(path)
    try:
        if observed.st_size > maximum:
            raise CodexExecBridgeError("PROTECTED_FILE_OVERSIZED", "A protected execution file exceeded its size limit.")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise CodexExecBridgeError("PROTECTED_FILE_OVERSIZED", "A protected execution file exceeded its size limit.")
        return b"".join(chunks), observed
    finally:
        os.close(fd)


def _read_protected_json(path: Path, *, maximum: int = MAX_PROTECTED_JSON_BYTES) -> tuple[dict[str, object], os.stat_result]:
    payload, observed = _read_protected_bytes(path, maximum=maximum)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexExecBridgeError("PROTECTED_JSON_INVALID", "A protected execution record is malformed.") from exc
    if not isinstance(value, dict):
        raise CodexExecBridgeError("PROTECTED_JSON_INVALID", "A protected execution record must be an object.")
    return value, observed


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short protected file write")
        offset += written


def _fsync_parent(path: Path) -> None:
    fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_immutable_file(path: Path, payload: bytes) -> os.stat_result:
    _assert_no_symlink_components(path, include_leaf=False)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.publish"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(temporary, flags, OWNER_FILE_MODE)
    except OSError as exc:
        raise CodexExecBridgeError("IMMUTABLE_FILE_CREATE_FAILED", "An immutable execution record could not be created.") from exc
    try:
        os.fchmod(fd, OWNER_FILE_MODE)
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise CodexExecBridgeError("IMMUTABLE_FILE_EXISTS", "An immutable execution record already exists.") from exc
        os.unlink(temporary)
        _fsync_parent(path)
        return _safe_regular_file_stat(path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _create_immutable_json(path: Path, value: Mapping[str, object]) -> os.stat_result:
    return _create_immutable_file(path, (_canonical_json(value) + "\n").encode("utf-8"))


def _atomic_replace_json(path: Path, value: Mapping[str, object]) -> None:
    _assert_no_symlink_components(path, include_leaf=False)
    if path.exists() or path.is_symlink():
        _safe_regular_file_stat(path)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        _create_immutable_json(temporary, value)
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _hash_file(path: Path, *, maximum: int | None = None) -> tuple[str, int, os.stat_result]:
    fd, observed = _open_protected_file(path)
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if maximum is not None and size > maximum:
                raise CodexExecBridgeError("PROTECTED_FILE_OVERSIZED", "A protected execution file exceeded its size limit.")
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest(), size, observed


def _unprotected_file_identity(path: Path, *, require_executable: bool = False) -> dict[str, object]:
    if not path.is_absolute() or _path_contains_traversal(path):
        raise CodexExecBridgeError("EXECUTION_PATH_INVALID", "An execution path must be absolute and normalized.")
    _assert_no_symlink_components(path)
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise CodexExecBridgeError("EXECUTION_PATH_UNAVAILABLE", "An execution path is unavailable.") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise CodexExecBridgeError("EXECUTABLE_INVALID", "The configured executable is not a regular file.")
    if require_executable and not os.access(path, os.X_OK):
        raise CodexExecBridgeError("EXECUTABLE_INVALID", "The configured executable is not executable.")
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        after = os.fstat(fd)
        if (
            observed.st_dev != after.st_dev
            or observed.st_ino != after.st_ino
            or not stat.S_ISREG(after.st_mode)
        ):
            os.close(fd)
            raise CodexExecBridgeError("EXECUTABLE_REPLACED", "The configured executable changed while opening.")
        with os.fdopen(fd, "rb") as stream:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise CodexExecBridgeError("EXECUTABLE_UNREADABLE", "The configured executable could not be fingerprinted.") from exc
    return {
        "path": str(path),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "size": observed.st_size,
        "mtime_ns": observed.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def _working_directory_identity(path: Path) -> dict[str, int]:
    if not path.is_absolute() or _path_contains_traversal(path):
        raise CodexExecBridgeError("WORKING_DIRECTORY_INVALID", "The working directory must be absolute and normalized.")
    _assert_no_symlink_components(path)
    try:
        observed = os.lstat(path)
    except OSError as exc:
        raise CodexExecBridgeError("WORKING_DIRECTORY_UNAVAILABLE", "The working directory is unavailable.") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise CodexExecBridgeError("WORKING_DIRECTORY_INVALID", "The working directory is invalid.")
    return {"device": observed.st_dev, "inode": observed.st_ino}


def _validate_argv(argv: Sequence[str]) -> list[str]:
    if not argv or len(argv) > 256:
        raise CodexExecBridgeError("ARGV_INVALID", "The exact execution argv is missing or too large.")
    output: list[str] = []
    for argument in argv:
        if not isinstance(argument, str) or "\x00" in argument or len(argument) > 32_768:
            raise CodexExecBridgeError("ARGV_INVALID", "The exact execution argv contains an invalid argument.")
        output.append(argument)
    executable = Path(output[0])
    if not executable.is_absolute():
        raise CodexExecBridgeError("ARGV_INVALID", "The exact executable path must be absolute.")
    try:
        # Resolve an approved launcher symlink once, then bind and execute the
        # canonical regular file. The immutable ticket therefore cannot drift
        # when a package-manager launcher link is replaced after preparation.
        canonical_executable = executable.resolve(strict=True)
    except OSError as exc:
        raise CodexExecBridgeError("ARGV_INVALID", "The exact executable path is unavailable.") from exc
    _assert_no_symlink_components(canonical_executable)
    output[0] = str(canonical_executable)
    return output


def _validate_environment_keys(keys: Sequence[str]) -> list[str]:
    output: list[str] = []
    for key in keys:
        if key not in _SAFE_ENVIRONMENT_KEY:
            raise CodexExecBridgeError("ENVIRONMENT_KEY_REJECTED", "An unapproved child environment key was requested.")
        if key not in output:
            output.append(key)
    return output


def _phase_preflight_from_identity(
    identity: Mapping[str, object],
    *,
    phase: str,
) -> dict[str, object]:
    pre_verification = identity.get("pre_verification_workspace_digest")
    if phase == "verification":
        if not isinstance(pre_verification, str) or not _SHA256.fullmatch(
            pre_verification
        ):
            raise CodexExecBridgeError(
                "PREFLIGHT_EVIDENCE_MISSING",
                "Verification requires a pre-verification workspace SHA-256 fingerprint.",
            )
    elif pre_verification is not None:
        raise CodexExecBridgeError(
            "PREFLIGHT_EVIDENCE_PHASE_MISMATCH",
            "Coding preflight cannot contain verification-only workspace evidence.",
        )
    return {
        "source_remote_fingerprint": identity["source_remote_fingerprint"],
        "git_boundary_fingerprint": identity["git_boundary_fingerprint"],
        "workspace_snapshot_digest": identity["workspace_snapshot_digest"],
        "pre_verification_workspace_digest": pre_verification,
    }


def _validate_phase_preflight(
    ticket: Mapping[str, object], identity: Mapping[str, object]
) -> None:
    phase = ticket.get("phase")
    if phase not in _SAFE_PHASE:
        raise CodexExecBridgeError(
            "TICKET_PHASE_INVALID", "The execution ticket phase is invalid."
        )
    expected = _phase_preflight_from_identity(identity, phase=str(phase))
    if ticket.get("phase_preflight") != expected:
        raise CodexExecBridgeError(
            "PREFLIGHT_EVIDENCE_INVALID",
            "The immutable phase preflight evidence failed its ticket binding.",
        )


def _ticket_without_digest(ticket: Mapping[str, object]) -> dict[str, object]:
    payload = dict(ticket)
    payload.pop("ticket_digest", None)
    return payload


def _validate_ticket_value(ticket: Mapping[str, object]) -> str:
    if ticket.get("schema") != TICKET_SCHEMA or ticket.get("policy") != BRIDGE_POLICY:
        raise CodexExecBridgeError("TICKET_SCHEMA_INVALID", "The execution ticket schema is unsupported.")
    digest = ticket.get("ticket_digest")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise CodexExecBridgeError("TICKET_DIGEST_INVALID", "The execution ticket digest is invalid.")
    if _canonical_sha256(_ticket_without_digest(ticket)) != digest:
        raise CodexExecBridgeError("TICKET_DIGEST_MISMATCH", "The execution ticket failed its integrity check.")
    identity = ticket.get("identity")
    if not isinstance(identity, dict):
        raise CodexExecBridgeError("TICKET_IDENTITY_INVALID", "The execution ticket identity is missing.")
    _validate_execution_identity(identity)
    phase_key = ticket.get("phase_key")
    if not isinstance(phase_key, str) or not _SAFE_PHASE_KEY.fullmatch(phase_key):
        raise CodexExecBridgeError("TICKET_PHASE_INVALID", "The execution ticket phase key is invalid.")
    if ticket.get("phase") not in _SAFE_PHASE:
        raise CodexExecBridgeError("TICKET_PHASE_INVALID", "The execution ticket phase is invalid.")
    _validate_phase_preflight(ticket, identity)
    argv = ticket.get("argv")
    if not isinstance(argv, list):
        raise CodexExecBridgeError("TICKET_ARGV_INVALID", "The execution ticket argv is invalid.")
    _validate_argv(argv)
    environment_keys = ticket.get("environment_keys")
    if not isinstance(environment_keys, list):
        raise CodexExecBridgeError("TICKET_ENVIRONMENT_INVALID", "The execution ticket environment policy is invalid.")
    _validate_environment_keys(environment_keys)
    final_message = ticket.get("final_message")
    if not isinstance(final_message, dict):
        raise CodexExecBridgeError("TICKET_FINAL_MESSAGE_INVALID", "The final-message binding is invalid.")
    relative_path = final_message.get("relative_path")
    maximum_bytes = final_message.get("maximum_bytes")
    capture_mode = final_message.get("capture_mode", "sidecar_required")
    if (
        not isinstance(relative_path, str)
        or not _SAFE_PHASE_KEY.fullmatch(relative_path)
        or "/" in relative_path
        or type(maximum_bytes) is not int
        or not 1 <= maximum_bytes <= MAX_FINAL_MESSAGE_BYTES
        or capture_mode not in {"sidecar_required", "jsonl_only"}
    ):
        raise CodexExecBridgeError("TICKET_FINAL_MESSAGE_INVALID", "The final-message binding is invalid.")
    return digest


def _load_ticket_and_seal(handle: ExecutionHandle) -> dict[str, object]:
    _validate_phase_directory(handle.spool_root, handle.phase_directory)
    ticket, ticket_stat = _read_protected_json(handle.ticket_path)
    digest = _validate_ticket_value(ticket)
    if digest != handle.ticket_digest or ticket.get("phase_key") != handle.phase_key:
        raise CodexExecBridgeError("TICKET_BINDING_MISMATCH", "The execution ticket does not match its phase binding.")
    seal, _ = _read_protected_json(handle.phase_directory / "ticket.seal.json")
    if seal.get("schema") != TICKET_SEAL_SCHEMA or seal.get("ticket_digest") != digest:
        raise CodexExecBridgeError("TICKET_SEAL_INVALID", "The execution ticket seal is invalid.")
    expected_ticket = seal.get("ticket_file")
    if not isinstance(expected_ticket, dict) or (
        expected_ticket.get("device") != ticket_stat.st_dev
        or expected_ticket.get("inode") != ticket_stat.st_ino
    ):
        raise CodexExecBridgeError("TICKET_REPLACED", "The immutable execution ticket was replaced.")
    stdin_digest, stdin_size, stdin_stat = _hash_file(handle.phase_directory / "stdin.bin", maximum=MAX_STDIN_BYTES)
    expected_stdin = seal.get("stdin_file")
    ticket_stdin = ticket.get("stdin")
    if not isinstance(expected_stdin, dict) or not isinstance(ticket_stdin, dict):
        raise CodexExecBridgeError("STDIN_BINDING_INVALID", "The approved input binding is invalid.")
    if (
        expected_stdin.get("device") != stdin_stat.st_dev
        or expected_stdin.get("inode") != stdin_stat.st_ino
        or expected_stdin.get("sha256") != stdin_digest
        or expected_stdin.get("size") != stdin_size
        or ticket_stdin.get("sha256") != stdin_digest
        or ticket_stdin.get("size") != stdin_size
    ):
        raise CodexExecBridgeError("STDIN_BINDING_MISMATCH", "The approved input failed its integrity check.")
    return ticket


def prepare_execution(
    spool_root: str | os.PathLike[str],
    *,
    phase_key: str,
    phase: str,
    identity: ExecutionIdentity,
    argv: Sequence[str],
    stdin_payload: bytes,
    working_directory: str | os.PathLike[str],
    environment_keys: Sequence[str] = DEFAULT_ENVIRONMENT_KEYS,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    final_message_relative_path: str = "final-message.txt",
    final_message_maximum_bytes: int = MAX_FINAL_MESSAGE_BYTES,
    final_message_capture_mode: str = "sidecar_required",
    forbidden_spool_roots: Sequence[str | os.PathLike[str]] = (),
) -> ExecutionHandle:
    if not isinstance(phase_key, str) or not _SAFE_PHASE_KEY.fullmatch(phase_key):
        raise CodexExecBridgeError("PHASE_KEY_INVALID", "The phase key is malformed.")
    if phase not in _SAFE_PHASE:
        raise CodexExecBridgeError("PHASE_INVALID", "The execution phase is unsupported.")
    if not isinstance(stdin_payload, bytes) or len(stdin_payload) > MAX_STDIN_BYTES:
        raise CodexExecBridgeError("STDIN_INVALID", "The approved input is invalid or oversized.")
    if type(output_limit_bytes) is not int or not 0 <= output_limit_bytes <= MAX_OUTPUT_LIMIT_BYTES:
        raise CodexExecBridgeError("OUTPUT_LIMIT_INVALID", "The output retention limit is invalid.")
    if not isinstance(timeout_seconds, (int, float)) or not 0.05 <= float(timeout_seconds) <= 86_400:
        raise CodexExecBridgeError("TIMEOUT_INVALID", "The execution timeout is invalid.")
    if not isinstance(heartbeat_interval_seconds, (int, float)) or not 0.02 <= float(heartbeat_interval_seconds) <= 30:
        raise CodexExecBridgeError("HEARTBEAT_INVALID", "The heartbeat interval is invalid.")
    if (
        not isinstance(final_message_relative_path, str)
        or not _SAFE_PHASE_KEY.fullmatch(final_message_relative_path)
        or "/" in final_message_relative_path
        or type(final_message_maximum_bytes) is not int
        or not 1 <= final_message_maximum_bytes <= MAX_FINAL_MESSAGE_BYTES
        or final_message_capture_mode not in {"sidecar_required", "jsonl_only"}
    ):
        raise CodexExecBridgeError("FINAL_MESSAGE_BINDING_INVALID", "The final-message binding is invalid.")

    identity_value = identity.as_dict()
    phase_preflight = _phase_preflight_from_identity(identity_value, phase=phase)
    exact_argv = _validate_argv(argv)
    environment_key_list = _validate_environment_keys(environment_keys)
    working_path = Path(working_directory)
    working_identity = _working_directory_identity(working_path)
    executable_identity = _unprotected_file_identity(Path(exact_argv[0]), require_executable=True)
    root = prepare_spool_root(
        spool_root,
        forbidden_roots=tuple(forbidden_spool_roots) + (working_path,),
    )
    root_stat = _validate_owner_directory(root)
    stdin_digest = hashlib.sha256(stdin_payload).hexdigest()
    payload: dict[str, object] = {
        "schema": TICKET_SCHEMA,
        "policy": BRIDGE_POLICY,
        "phase_key": phase_key,
        "phase": phase,
        "identity": identity_value,
        "phase_preflight": phase_preflight,
        "argv": exact_argv,
        "working_directory": str(working_path),
        "working_directory_identity": working_identity,
        "executable_identity": executable_identity,
        "stdin": {
            "relative_path": "stdin.bin",
            "size": len(stdin_payload),
            "sha256": stdin_digest,
        },
        "environment_keys": environment_key_list,
        "limits": {
            "combined_output_bytes": output_limit_bytes,
            "timeout_seconds": float(timeout_seconds),
            "heartbeat_interval_seconds": float(heartbeat_interval_seconds),
        },
        "final_message": {
            "relative_path": final_message_relative_path,
            "maximum_bytes": final_message_maximum_bytes,
            "capture_mode": final_message_capture_mode,
        },
        "spool_root_identity": {"device": root_stat.st_dev, "inode": root_stat.st_ino},
    }
    ticket_digest = _canonical_sha256(payload)
    ticket = {**payload, "ticket_digest": ticket_digest}
    phase_directory = root / phase_key
    handle = ExecutionHandle(
        spool_root=root,
        phase_directory=phase_directory,
        ticket_path=phase_directory / "ticket.json",
        ticket_digest=ticket_digest,
        phase_key=phase_key,
    )
    try:
        os.mkdir(phase_directory, OWNER_DIRECTORY_MODE)
        os.chmod(phase_directory, OWNER_DIRECTORY_MODE, follow_symlinks=False)
        _fsync_parent(phase_directory)
    except FileExistsError:
        _validate_phase_directory(root, phase_directory)
        try:
            existing = _load_ticket_and_seal(handle)
        except CodexExecBridgeError as exc:
            raise CodexExecBridgeError("PHASE_INCOMPLETE_OR_CONFLICTING", "The phase directory is incomplete or conflicting.") from exc
        if existing != ticket:
            raise CodexExecBridgeError("PHASE_IDENTITY_CONFLICT", "The phase key is already bound to a different execution.")
        return handle
    except OSError as exc:
        raise CodexExecBridgeError("PHASE_CREATE_FAILED", "The phase directory could not be created.") from exc

    stdin_stat = _create_immutable_file(phase_directory / "stdin.bin", stdin_payload)
    ticket_stat = _create_immutable_json(handle.ticket_path, ticket)
    seal = {
        "schema": TICKET_SEAL_SCHEMA,
        "policy": BRIDGE_POLICY,
        "ticket_digest": ticket_digest,
        "ticket_file": {"device": ticket_stat.st_dev, "inode": ticket_stat.st_ino},
        "stdin_file": {
            "device": stdin_stat.st_dev,
            "inode": stdin_stat.st_ino,
            "size": len(stdin_payload),
            "sha256": stdin_digest,
        },
    }
    _create_immutable_json(phase_directory / "ticket.seal.json", seal)
    _load_ticket_and_seal(handle)
    return handle


def handle_from_ticket_path(ticket_path: str | os.PathLike[str]) -> ExecutionHandle:
    path = Path(ticket_path)
    if not path.is_absolute() or path.name != "ticket.json":
        raise CodexExecBridgeError("TICKET_PATH_INVALID", "The ticket path is invalid.")
    phase_directory = path.parent
    root = phase_directory.parent
    if not _SAFE_PHASE_KEY.fullmatch(phase_directory.name):
        raise CodexExecBridgeError("TICKET_PATH_INVALID", "The ticket phase path is invalid.")
    ticket, _ = _read_protected_json(path)
    digest = _validate_ticket_value(ticket)
    handle = ExecutionHandle(root, phase_directory, path, digest, phase_directory.name)
    _load_ticket_and_seal(handle)
    return handle


def load_ticket(handle: ExecutionHandle) -> dict[str, object]:
    return dict(_load_ticket_and_seal(handle))


def capture_process_start_identity(process_id: int) -> str:
    if type(process_id) is not int or process_id <= 0:
        return ""
    evidence = ""
    proc_stat = Path(f"/proc/{process_id}/stat")
    try:
        if proc_stat.is_file():
            fields = proc_stat.read_text(encoding="utf-8", errors="strict").split()
            if len(fields) > 21:
                evidence = f"proc:{fields[21]}"
    except (OSError, UnicodeError):
        evidence = ""
    if not evidence and sys.platform == "darwin":
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
                3,
                0,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if observed_size == ctypes.sizeof(info) and info.pbi_pid == process_id:
                evidence = f"libproc:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}:{info.pbi_ppid}"
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
    return _canonical_sha256(
        {"policy": BRIDGE_POLICY, "process_id": process_id, "start_evidence": evidence}
    )


def process_identity_matches(process_id: int, expected_identity: str) -> bool:
    return bool(
        expected_identity
        and _SHA256.fullmatch(expected_identity)
        and capture_process_start_identity(process_id) == expected_identity
    )


class _RetentionBudget:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum
        self.remaining = maximum
        self._lock = threading.Lock()

    def retain(self, chunk: bytes) -> bytes:
        with self._lock:
            retained = chunk[: self.remaining]
            self.remaining -= len(retained)
        return retained


def _empty_histogram() -> dict[str, int]:
    return {key: 0 for key in _CHUNK_HISTOGRAM_KEYS}


def _histogram_key(size: int) -> str:
    if size <= 1024:
        return "1-1024"
    if size <= 4096:
        return "1025-4096"
    if size <= 8192:
        return "4097-8192"
    return "8193+"


_KNOWN_CODEX_JSONL_EVENTS = frozenset(
    {
        "thread.started",
        "turn.started",
        "turn.completed",
        "turn.failed",
        "error",
        "warning",
        "item.started",
        "item.updated",
        "item.completed",
    }
)
_TERMINAL_CODEX_JSONL_EVENTS = frozenset({"turn.completed", "turn.failed"})
_SAFE_EVENT_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


class _JsonlStreamClassifier:
    """Classify the complete stdout stream while retaining only bounded evidence."""

    def __init__(self, phase: str = "coding") -> None:
        self.phase = phase
        self.buffer = bytearray()
        self.stream_offset = 0
        self.event_count = 0
        self.complete_line_count = 0
        self.valid_event_count = 0
        self.malformed_count = 0
        self.oversized_line_count = 0
        self.type_histogram: dict[str, int] = {}
        self.overflow_event_type_count = 0
        self.unknown_samples: list[dict[str, object]] = []
        self.last_terminal_event = b""
        self.last_terminal_event_type = ""
        self.last_terminal_event_start = 0
        self.last_terminal_event_end = 0
        self.terminal_event_count = 0
        self.last_terminal_event_sequence = 0
        self.last_terminal_event_observed_at = ""
        self.last_terminal_event_reported_at = ""
        self.last_terminal_turn_identity = ""
        self.thread_started_count = 0
        self.turn_started_count = 0
        self.turn_completed_count = 0
        self.turn_failed_count = 0
        self.error_count = 0
        self.fatal_error_count = 0
        self.last_started_turn_identity = ""
        self.last_started_thread_identity = ""
        self.lifecycle_conflict_count = 0
        self.lifecycle_conflict_codes: set[str] = set()
        self.agent_message_count = 0
        self.valid_agent_message_count = 0
        self.last_agent_message_bytes = 0
        self.last_agent_message_sha256 = ""
        self.last_agent_message_raw_bytes = 0
        self.last_agent_message_raw_sha256 = ""
        self.last_agent_message_source_bytes = 0
        self.last_agent_message_source_sha256 = ""
        self.last_agent_message_event = b""
        self.last_agent_message_event_start = 0
        self.last_agent_message_event_end = 0
        self.last_agent_message_event_sequence = 0
        self.last_agent_message_turn_identity = ""
        self.last_agent_message_canonicalization = ""
        self.last_agent_message_schema_status = "UNAVAILABLE"
        self.last_agent_message_selection = "UNAVAILABLE"
        self._completed_agent_message_item_ids: set[str] = set()
        self._line_start_offset = 0
        self._discard_oversized_line = False
        self._discarded_line_bytes = 0
        self.eof_received = False
        self.trailing_partial_line_present = False
        self.trailing_partial_line_resolved = True

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.buffer.extend(chunk)
        while True:
            newline = self.buffer.find(b"\n")
            if newline < 0:
                if len(self.buffer) > MAX_JSONL_LINE_BYTES:
                    self._discard_oversized_line = True
                    self._discarded_line_bytes += len(self.buffer)
                    self.buffer.clear()
                return
            line = bytes(self.buffer[:newline])
            consumed = newline + 1
            del self.buffer[:consumed]
            line_start = self._line_start_offset
            line_end = line_start + self._discarded_line_bytes + consumed
            self._line_start_offset = line_end
            self.stream_offset = line_end
            self.complete_line_count += 1
            if self._discard_oversized_line or len(line) > MAX_JSONL_LINE_BYTES:
                self.event_count += 1
                self.malformed_count += 1
                self.oversized_line_count += 1
                self._discard_oversized_line = False
                self._discarded_line_bytes = 0
                continue
            self._discarded_line_bytes = 0
            self._consume_line(line, line_start=line_start, line_end=line_end)

    def finish(self, *, eof: bool = True) -> None:
        self.eof_received = eof
        if self.buffer or self._discard_oversized_line:
            self.trailing_partial_line_present = True
            line = bytes(self.buffer)
            line_start = self._line_start_offset
            line_end = line_start + self._discarded_line_bytes + len(line)
            self.stream_offset = line_end
            if self._discard_oversized_line or len(line) > MAX_JSONL_LINE_BYTES:
                self.event_count += 1
                self.malformed_count += 1
                self.oversized_line_count += 1
                self.trailing_partial_line_resolved = False
            else:
                self.trailing_partial_line_resolved = self._consume_line(
                    line, line_start=line_start, line_end=line_end
                )
            if not eof:
                self.trailing_partial_line_resolved = False
        self.buffer.clear()
        self._discard_oversized_line = False
        self._discarded_line_bytes = 0

    def _record_lifecycle_conflict(self, code: str) -> None:
        self.lifecycle_conflict_count += 1
        if len(self.lifecycle_conflict_codes) < 20:
            self.lifecycle_conflict_codes.add(code)

    def _select_agent_message(
        self,
        *,
        line: bytes,
        line_start: int,
        line_end: int,
        text: str,
        turn_identity: str,
    ) -> None:
        raw_normalized = _normalize_result_text(text).encode("utf-8")
        source_payload = text.encode("utf-8")
        canonical, canonicalization, schema_status = _canonical_result_text(
            text,
            phase=self.phase,
        )
        if not canonical:
            return
        self.valid_agent_message_count += 1
        self.last_agent_message_bytes = len(canonical)
        self.last_agent_message_sha256 = hashlib.sha256(canonical).hexdigest()
        self.last_agent_message_raw_bytes = len(raw_normalized)
        self.last_agent_message_raw_sha256 = hashlib.sha256(
            raw_normalized
        ).hexdigest()
        self.last_agent_message_source_bytes = len(source_payload)
        self.last_agent_message_source_sha256 = hashlib.sha256(
            source_payload
        ).hexdigest()
        self.last_agent_message_event = line + b"\n"
        self.last_agent_message_event_start = line_start
        self.last_agent_message_event_end = line_end
        self.last_agent_message_event_sequence = self.event_count
        self.last_agent_message_turn_identity = turn_identity
        self.last_agent_message_canonicalization = canonicalization
        self.last_agent_message_schema_status = schema_status
        self.last_agent_message_selection = (
            "LAST_STRUCTURALLY_VALID_BEFORE_TERMINAL"
        )

    def _consume_line(self, line: bytes, *, line_start: int, line_end: int) -> bool:
        if not line.strip():
            return True
        self.event_count += 1
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.malformed_count += 1
            return False
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            self.malformed_count += 1
            return False
        event_type = str(value["type"])
        if not event_type or len(event_type) > 120 or any(ord(character) < 32 for character in event_type):
            self.malformed_count += 1
            return False
        safe_event_type = event_type if _SAFE_EVENT_TYPE.fullmatch(event_type) else "__unsafe_type__"
        self.valid_event_count += 1
        if safe_event_type in self.type_histogram:
            self.type_histogram[safe_event_type] += 1
        elif len(self.type_histogram) < MAX_JSONL_EVENT_TYPES:
            self.type_histogram[safe_event_type] = 1
        else:
            self.overflow_event_type_count += 1
        if event_type not in _KNOWN_CODEX_JSONL_EVENTS and len(self.unknown_samples) < MAX_UNKNOWN_EVENT_SAMPLES:
            self.unknown_samples.append(
                {
                    "event_type": safe_event_type,
                    "line_bytes": len(line),
                    "line_sha256": hashlib.sha256(line).hexdigest(),
                }
            )
        raw_turn_identity = value.get("turn_id")
        if raw_turn_identity is not None and (
            not isinstance(raw_turn_identity, str)
            or not raw_turn_identity
            or len(raw_turn_identity) > 240
        ):
            self._record_lifecycle_conflict("TURN_IDENTITY_INVALID")
            event_turn_identity = ""
        else:
            event_turn_identity = str(raw_turn_identity or "")
        if event_type == "thread.started":
            self.thread_started_count += 1
            if (
                self.thread_started_count != 1
                or self.turn_started_count
                or self.terminal_event_count
            ):
                self._record_lifecycle_conflict("THREAD_STARTED_OUT_OF_ORDER")
            thread_identity = value.get("thread_id")
            if thread_identity is not None and (
                not isinstance(thread_identity, str)
                or not thread_identity
                or len(thread_identity) > 240
            ):
                self._record_lifecycle_conflict("THREAD_IDENTITY_INVALID")
                thread_identity = None
            self.last_started_thread_identity = (
                str(thread_identity)
                if isinstance(thread_identity, str)
                else f"synthetic-thread:{self.event_count}"
            )
        elif event_type == "turn.started":
            self.turn_started_count += 1
            if (
                self.thread_started_count != 1
                or self.turn_started_count != 1
                or self.terminal_event_count
            ):
                self._record_lifecycle_conflict("TURN_STARTED_OUT_OF_ORDER")
            self.last_started_turn_identity = (
                event_turn_identity
                or f"synthetic-turn:{self.event_count}"
            )
        elif event_type == "turn.completed":
            self.turn_completed_count += 1
            if self.turn_started_count != 1 or self.terminal_event_count:
                self._record_lifecycle_conflict("TURN_COMPLETED_OUT_OF_ORDER")
            if (
                event_turn_identity
                and self.last_started_turn_identity
                and event_turn_identity != self.last_started_turn_identity
            ):
                self._record_lifecycle_conflict("TERMINAL_TURN_IDENTITY_MISMATCH")
        elif event_type == "turn.failed":
            self.turn_failed_count += 1
            if self.turn_started_count != 1 or self.terminal_event_count:
                self._record_lifecycle_conflict("TURN_FAILED_OUT_OF_ORDER")
            if (
                event_turn_identity
                and self.last_started_turn_identity
                and event_turn_identity != self.last_started_turn_identity
            ):
                self._record_lifecycle_conflict("TERMINAL_TURN_IDENTITY_MISMATCH")
        elif event_type == "error":
            self.error_count += 1
            # Codex CLI 0.144.4 emits recoverable error observations without a
            # ``fatal`` member. Only explicit fatal truth is terminal evidence.
            if value.get("fatal") is True:
                self.fatal_error_count += 1
        if event_type == "item.completed":
            item = value.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                self.agent_message_count += 1
                raw_item_identity = item.get("id")
                duplicate_item_identity = False
                if raw_item_identity is not None:
                    if (
                        not isinstance(raw_item_identity, str)
                        or not raw_item_identity
                        or len(raw_item_identity) > 240
                    ):
                        self._record_lifecycle_conflict(
                            "AGENT_MESSAGE_ITEM_IDENTITY_INVALID"
                        )
                        duplicate_item_identity = True
                    elif raw_item_identity in self._completed_agent_message_item_ids:
                        self._record_lifecycle_conflict(
                            "DUPLICATE_AGENT_MESSAGE_ITEM_ID"
                        )
                        duplicate_item_identity = True
                    else:
                        self._completed_agent_message_item_ids.add(
                            raw_item_identity
                        )
                candidate_turn_identity = (
                    event_turn_identity or self.last_started_turn_identity
                )
                if duplicate_item_identity:
                    pass
                elif self.terminal_event_count:
                    self._record_lifecycle_conflict(
                        "AGENT_MESSAGE_AFTER_TERMINAL"
                    )
                elif self.turn_started_count != 1 or not candidate_turn_identity:
                    self._record_lifecycle_conflict(
                        "AGENT_MESSAGE_OUTSIDE_TURN"
                    )
                elif (
                    event_turn_identity
                    and self.last_started_turn_identity
                    and event_turn_identity != self.last_started_turn_identity
                ):
                    self._record_lifecycle_conflict(
                        "AGENT_MESSAGE_TURN_IDENTITY_MISMATCH"
                    )
                else:
                    self._select_agent_message(
                        line=line,
                        line_start=line_start,
                        line_end=line_end,
                        text=item["text"],
                        turn_identity=candidate_turn_identity,
                    )
        # Nonterminal error events are deliberately not terminal evidence.
        if event_type in _TERMINAL_CODEX_JSONL_EVENTS:
            self.terminal_event_count += 1
            self.last_terminal_event = line + b"\n"
            self.last_terminal_event_type = event_type
            self.last_terminal_event_start = line_start
            self.last_terminal_event_end = line_end
            self.last_terminal_event_sequence = self.event_count
            self.last_terminal_event_observed_at = _utc_now()
            reported_at = value.get("timestamp")
            if (
                isinstance(reported_at, str)
                and 0 < len(reported_at) <= 80
                and "\x00" not in reported_at
                and "\r" not in reported_at
                and "\n" not in reported_at
            ):
                self.last_terminal_event_reported_at = reported_at
            self.last_terminal_turn_identity = (
                event_turn_identity or self.last_started_turn_identity
            )
        return True

    def terminal_truth(self) -> dict[str, object]:
        completed = self.turn_completed_count
        failed = self.turn_failed_count
        fatal_errors = self.fatal_error_count
        ordered_single_turn = bool(
            self.thread_started_count == 1
            and self.turn_started_count == 1
            and self.terminal_event_count == 1
            and self.lifecycle_conflict_count == 0
        )
        success = bool(
            ordered_single_turn
            and completed == 1
            and failed == 0
            and fatal_errors == 0
        )
        failure = bool(
            ordered_single_turn and completed == 0 and failed == 1
        )
        contradiction = bool(
            completed > 1
            or failed > 1
            or (completed > 0 and (failed > 0 or fatal_errors > 0))
            or self.lifecycle_conflict_count > 0
        )
        same_turn = bool(
            success
            and self.last_agent_message_event_sequence
            < self.last_terminal_event_sequence
            and (
                not self.last_agent_message_turn_identity
                or not self.last_terminal_turn_identity
                or self.last_agent_message_turn_identity
                == self.last_terminal_turn_identity
            )
        )
        return {
            "success": success,
            "failure": failure,
            "contradiction": contradiction,
            "same_turn_final_agent_message": same_turn,
            "ordered_single_turn": ordered_single_turn,
        }

    def summary(self, *, retained_stdout_bytes: int) -> dict[str, object]:
        return {
            "classifier_rule": JSONL_CLASSIFIER_RULE,
            "final_result_selection_rule": FINAL_RESULT_SELECTION_RULE,
            "canonicalization_rule": FINAL_RESULT_CANONICALIZATION_RULE,
            "event_count": self.event_count,
            "complete_line_count": self.complete_line_count,
            "valid_event_count": self.valid_event_count,
            "malformed_count": self.malformed_count,
            "oversized_line_count": self.oversized_line_count,
            "type_histogram": dict(sorted(self.type_histogram.items())),
            "overflow_event_type_count": self.overflow_event_type_count,
            "unknown_samples": list(self.unknown_samples),
            "terminal_event_count": self.terminal_event_count,
            "thread_started_count": self.thread_started_count,
            "turn_started_count": self.turn_started_count,
            "turn_completed_count": self.turn_completed_count,
            "turn_failed_count": self.turn_failed_count,
            "error_count": self.error_count,
            "fatal_error_count": self.fatal_error_count,
            "lifecycle_conflict_count": self.lifecycle_conflict_count,
            "lifecycle_conflict_codes": sorted(self.lifecycle_conflict_codes),
            "terminal_truth": self.terminal_truth(),
            "agent_message_count": self.agent_message_count,
            "valid_agent_message_count": self.valid_agent_message_count,
            "last_agent_message_bytes": self.last_agent_message_bytes,
            "last_agent_message_sha256": self.last_agent_message_sha256,
            "last_agent_message_raw_bytes": self.last_agent_message_raw_bytes,
            "last_agent_message_raw_sha256": self.last_agent_message_raw_sha256,
            "last_agent_message_source_bytes": self.last_agent_message_source_bytes,
            "last_agent_message_source_sha256": self.last_agent_message_source_sha256,
            "last_agent_message_event_start_offset": self.last_agent_message_event_start,
            "last_agent_message_event_end_offset": self.last_agent_message_event_end,
            "last_agent_message_event_sequence": self.last_agent_message_event_sequence,
            "last_agent_message_turn_identity": self.last_agent_message_turn_identity,
            "last_agent_message_canonicalization": self.last_agent_message_canonicalization,
            "last_agent_message_schema_status": self.last_agent_message_schema_status,
            "last_agent_message_selection": self.last_agent_message_selection,
            "agent_message_event_within_retained_prefix": bool(
                self.last_agent_message_event
                and self.last_agent_message_event_end <= retained_stdout_bytes
            ),
            "last_terminal_event_type": self.last_terminal_event_type,
            "last_terminal_event_start_offset": self.last_terminal_event_start,
            "last_terminal_event_end_offset": self.last_terminal_event_end,
            "last_terminal_event_sequence": self.last_terminal_event_sequence,
            "last_terminal_event_observed_at": self.last_terminal_event_observed_at,
            "last_terminal_event_reported_at": self.last_terminal_event_reported_at,
            "last_terminal_turn_identity": self.last_terminal_turn_identity,
            "eof_received": self.eof_received,
            "trailing_partial_line_present": self.trailing_partial_line_present,
            "trailing_partial_line_resolved": self.trailing_partial_line_resolved,
            "terminal_event_within_retained_prefix": bool(
                self.last_terminal_event
                and self.last_terminal_event_end <= retained_stdout_bytes
            ),
        }


class _DrainCapture:
    def __init__(
        self,
        name: str,
        stream,
        output_fd: int,
        budget: _RetentionBudget,
        *,
        jsonl_classifier: _JsonlStreamClassifier | None = None,
        persistent_secrets: Sequence[bytes] = (),
    ) -> None:
        self.name = name
        self.stream = stream
        self.output_fd = output_fd
        self.budget = budget
        self.observed_bytes = 0
        self.retained_bytes = 0
        self.observed_digest = hashlib.sha256()
        self.retained_digest = hashlib.sha256()
        self.histogram = _empty_histogram()
        self.jsonl_classifier = jsonl_classifier
        self.redactor = _PersistentOutputRedactor(persistent_secrets)
        self.completed = False
        self.eof = False
        self.incomplete = False
        self.failed = False
        self.completed_at = ""
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def request_stop(self) -> None:
        self._stop_event.set()

    def drain(self) -> None:
        write_available = True

        def retain_sanitized(sanitized: bytes) -> None:
            nonlocal write_available
            if not sanitized:
                return
            with self._lock:
                self.observed_digest.update(sanitized)
            if self.jsonl_classifier is not None:
                self.jsonl_classifier.feed(sanitized)
            retained = self.budget.retain(sanitized)
            if retained and write_available:
                try:
                    _write_all(self.output_fd, retained)
                except OSError:
                    with self._lock:
                        self.failed = True
                    write_available = False
                else:
                    with self._lock:
                        self.retained_bytes += len(retained)
                        self.retained_digest.update(retained)

        try:
            stream_fd = self.stream.fileno()
            while True:
                readable, _, _ = select.select([stream_fd], [], [], 0.05)
                if not readable:
                    if self._stop_event.is_set():
                        with self._lock:
                            self.incomplete = True
                        break
                    continue
                chunk = os.read(stream_fd, 8192)
                if not chunk:
                    with self._lock:
                        self.eof = True
                    break
                with self._lock:
                    self.observed_bytes += len(chunk)
                    self.histogram[_histogram_key(len(chunk))] += 1
                retain_sanitized(self.redactor.feed(chunk))
        except Exception:
            with self._lock:
                self.failed = True
                self.incomplete = True
        finally:
            try:
                retain_sanitized(self.redactor.finish())
            except Exception:
                with self._lock:
                    self.failed = True
                    self.incomplete = True
            if self.jsonl_classifier is not None:
                self.jsonl_classifier.finish(eof=self.eof)
            try:
                self.stream.close()
            except Exception:
                with self._lock:
                    self.failed = True
            try:
                os.fsync(self.output_fd)
            except OSError:
                with self._lock:
                    self.failed = True
            finally:
                os.close(self.output_fd)
            with self._lock:
                self.completed = True
                self.completed_at = _utc_now()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "observed_bytes": self.observed_bytes,
                "retained_bytes": self.retained_bytes,
                "observed_sha256": self.observed_digest.hexdigest(),
                "retained_sha256": self.retained_digest.hexdigest(),
                "truncated": self.observed_bytes > self.retained_bytes,
                "completed": self.completed,
                "eof": self.eof,
                "incomplete": self.incomplete,
                "completed_at": self.completed_at,
                "failed": self.failed,
                "chunk_histogram": dict(self.histogram),
            }


class _StdinDelivery:
    def __init__(self, expected_size: int, expected_digest: str) -> None:
        self.expected_size = expected_size
        self.expected_digest = expected_digest
        self.written_bytes = 0
        self.completed = False
        self.failed = False
        self._lock = threading.Lock()

    def deliver(self, stream, stdin_path: Path) -> None:
        digest = hashlib.sha256()
        try:
            fd, _ = _open_protected_file(stdin_path)
            try:
                while True:
                    chunk = os.read(fd, 64 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = stream.write(view)
                        if written is None:
                            written = len(view)
                        if written <= 0:
                            raise BrokenPipeError
                        with self._lock:
                            self.written_bytes += written
                        view = view[written:]
                stream.flush()
            finally:
                os.close(fd)
            with self._lock:
                self.completed = (
                    self.written_bytes == self.expected_size
                    and digest.hexdigest() == self.expected_digest
                )
                self.failed = not self.completed
        except Exception:
            with self._lock:
                self.failed = True
        finally:
            try:
                stream.close()
            except Exception:
                with self._lock:
                    self.failed = True

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "expected_bytes": self.expected_size,
                "written_bytes": self.written_bytes,
                "expected_sha256": self.expected_digest,
                "complete": self.completed and not self.failed,
                "failed": self.failed,
            }


def _create_capture_file(path: Path) -> tuple[int, os.stat_result]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, OWNER_FILE_MODE)
    except FileExistsError as exc:
        raise CodexExecBridgeError("PARTIAL_CAPTURE_EXISTS", "A prior partial capture prevents duplicate execution.") from exc
    except OSError as exc:
        raise CodexExecBridgeError("CAPTURE_CREATE_FAILED", "A protected output capture could not be created.") from exc
    os.fchmod(fd, OWNER_FILE_MODE)
    return fd, os.fstat(fd)


def _open_lease(path: Path) -> int:
    common_flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, common_flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        created = True
    except FileExistsError:
        before = _safe_regular_file_stat(path)
        try:
            fd = os.open(path, common_flags)
        except OSError as exc:
            raise CodexExecBridgeError("LEASE_UNAVAILABLE", "The execution lease could not be opened.") from exc
        after = os.fstat(fd)
        if before.st_dev != after.st_dev or before.st_ino != after.st_ino:
            os.close(fd)
            raise CodexExecBridgeError("LEASE_REPLACED", "The execution lease changed while opening.")
        created = False
    except OSError as exc:
        raise CodexExecBridgeError("LEASE_UNAVAILABLE", "The execution lease could not be opened.") from exc
    try:
        if created:
            os.fchmod(fd, OWNER_FILE_MODE)
        observed = os.fstat(fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != os.getuid()
            or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != OWNER_FILE_MODE
        ):
            raise CodexExecBridgeError("LEASE_INVALID", "The execution lease is unsafe.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CodexExecBridgeError("PHASE_ALREADY_RUNNING", "The execution phase already has a live writer.") from exc
        os.ftruncate(fd, 0)
        _write_all(fd, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
        return fd
    except Exception:
        os.close(fd)
        raise


def _cancel_requested(handle: ExecutionHandle) -> bool:
    path = handle.phase_directory / "cancel.request.json"
    try:
        value, _ = _read_protected_json(path)
    except CodexExecBridgeError as exc:
        if exc.code == "PROTECTED_FILE_UNAVAILABLE" and not path.exists() and not path.is_symlink():
            return False
        raise
    return bool(
        value.get("schema") == CANCEL_SCHEMA
        and value.get("policy") == BRIDGE_POLICY
        and value.get("ticket_digest") == handle.ticket_digest
    ) or (_raise_cancel_integrity())


def _raise_cancel_integrity() -> bool:
    raise CodexExecBridgeError("CANCEL_REQUEST_INVALID", "The durable cancellation request is invalid.")


def request_cancel(
    handle: ExecutionHandle,
) -> Literal["requested", "replayed", "terminal"]:
    _load_ticket_and_seal(handle)
    if (handle.phase_directory / "terminal.json").exists():
        return "terminal"
    value = {
        "schema": CANCEL_SCHEMA,
        "policy": BRIDGE_POLICY,
        "ticket_digest": handle.ticket_digest,
        "requested_at": _utc_now(),
    }
    try:
        _create_immutable_json(handle.phase_directory / "cancel.request.json", value)
        return "requested"
    except CodexExecBridgeError as exc:
        if exc.code != "IMMUTABLE_FILE_EXISTS":
            raise
        if not _cancel_requested(handle):
            raise CodexExecBridgeError("CANCEL_REQUEST_INVALID", "The durable cancellation request conflicts.")
        return "replayed"


def _validate_runtime_bindings(ticket: Mapping[str, object]) -> None:
    executable = ticket.get("executable_identity")
    working = ticket.get("working_directory_identity")
    if not isinstance(executable, dict) or not isinstance(working, dict):
        raise CodexExecBridgeError("RUNTIME_BINDING_INVALID", "The runtime binding is invalid.")
    current_executable = _unprotected_file_identity(Path(str(executable.get("path") or "")), require_executable=True)
    if current_executable != executable:
        raise CodexExecBridgeError("EXECUTABLE_REPLACED", "The configured executable changed after approval.")
    current_working = _working_directory_identity(Path(str(ticket.get("working_directory") or "")))
    if current_working != working:
        raise CodexExecBridgeError("WORKING_DIRECTORY_REPLACED", "The working directory changed identity after approval.")


def _child_environment(ticket: Mapping[str, object]) -> dict[str, str]:
    keys = ticket.get("environment_keys")
    if not isinstance(keys, list):
        raise CodexExecBridgeError("TICKET_ENVIRONMENT_INVALID", "The child environment policy is invalid.")
    approved = _validate_environment_keys(keys)
    # A detached sidecar receives these approved values from its launcher and
    # passes only the ticket-bound subset to Codex. No value is serialized.
    output: dict[str, str] = {}
    for key in approved:
        if key not in os.environ:
            continue
        value = os.environ[key]
        if _environment_value_is_invalid(key, value):
            raise CodexExecBridgeError(
                "ENVIRONMENT_VALUE_INVALID",
                "The detached environment contained an invalid value.",
            )
        output[key] = value
    return output


def _validated_detached_environment(
    ticket: Mapping[str, object],
    supplied: Mapping[str, str] | None,
) -> dict[str, str]:
    keys = ticket.get("environment_keys")
    if not isinstance(keys, list):
        raise CodexExecBridgeError(
            "TICKET_ENVIRONMENT_INVALID",
            "The child environment policy is invalid.",
        )
    approved = frozenset(_validate_environment_keys(keys))
    available: Mapping[str, str] = (
        supplied if supplied is not None else os.environ
    )
    output: dict[str, str] = {}
    for key, value in available.items():
        if key not in approved:
            if supplied is not None:
                raise CodexExecBridgeError(
                    "ENVIRONMENT_KEY_REJECTED",
                    "The detached environment contained a key outside its ticket allowlist.",
                )
            continue
        if _environment_value_is_invalid(key, value):
            raise CodexExecBridgeError(
                "ENVIRONMENT_VALUE_INVALID",
                "The detached environment contained an invalid value.",
            )
        output[key] = value
    return output


def _snapshot_state(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    *,
    state: str,
    sequence: int,
    sidecar_identity: str,
    child_process_id: int,
    child_start_identity: str,
    stdout: _DrainCapture | None,
    stderr: _DrainCapture | None,
    stdin: _StdinDelivery | None,
    started_at: str,
) -> dict[str, object]:
    stdout_value = stdout.snapshot() if stdout is not None else _empty_stream_snapshot()
    stderr_value = stderr.snapshot() if stderr is not None else _empty_stream_snapshot()
    return {
        "schema": STATE_SCHEMA,
        "policy": BRIDGE_POLICY,
        "ticket_digest": handle.ticket_digest,
        "phase": ticket.get("phase"),
        "state": state,
        "heartbeat_sequence": sequence,
        "heartbeat_at": _utc_now(),
        "started_at": started_at,
        "sidecar_process_id": os.getpid(),
        "sidecar_process_start_identity": sidecar_identity,
        "child_process_id": child_process_id,
        "child_process_start_identity": child_start_identity,
        "stream_offsets": {
            "stdout_observed": stdout_value["observed_bytes"],
            "stdout_retained": stdout_value["retained_bytes"],
            "stderr_observed": stderr_value["observed_bytes"],
            "stderr_retained": stderr_value["retained_bytes"],
        },
        "chunk_histogram": {
            "stdout": stdout_value["chunk_histogram"],
            "stderr": stderr_value["chunk_histogram"],
        },
        "stdout_jsonl": (
            stdout.jsonl_classifier.summary(
                retained_stdout_bytes=int(stdout_value["retained_bytes"])
            )
            if stdout is not None and stdout.jsonl_classifier is not None
            else None
        ),
        "stdin_delivery": stdin.snapshot() if stdin is not None else None,
    }


def _empty_stream_snapshot() -> dict[str, object]:
    return {
        "observed_bytes": 0,
        "retained_bytes": 0,
        "observed_sha256": hashlib.sha256(b"").hexdigest(),
        "retained_sha256": hashlib.sha256(b"").hexdigest(),
        "truncated": False,
        "completed": False,
        "eof": False,
        "incomplete": False,
        "completed_at": "",
        "failed": False,
        "chunk_histogram": _empty_histogram(),
    }


def _terminate_exact_process(process: subprocess.Popen[bytes], start_identity: str) -> bool:
    if process.poll() is not None:
        return True
    if not process_identity_matches(process.pid, start_identity):
        return False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + PROCESS_STOP_GRACE_SECONDS
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    if process.poll() is None:
        if not process_identity_matches(process.pid, start_identity):
            return False
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return process.poll() is not None


def _terminate_unbound_sidecar(process: subprocess.Popen[bytes]) -> bool:
    """Reap the exact, not-yet-published Popen child and its process group."""
    if process.poll() is not None:
        return True
    try:
        if os.getpgid(process.pid) != process.pid:
            return False
    except ProcessLookupError:
        try:
            process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return False
        return process.poll() is not None
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            if os.getpgid(process.pid) != process.pid:
                return False
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=PROCESS_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return False
    return process.poll() is not None


def _terminal_state(
    *,
    exit_code: int | None,
    timed_out: bool,
    cancelled: bool,
    integrity_blocked: bool,
    terminal_success: bool,
    terminal_failure: bool,
    stdin: _StdinDelivery,
    stdout: _DrainCapture,
    stderr: _DrainCapture,
) -> str:
    if timed_out:
        return "TIMED_OUT"
    if cancelled:
        return "CANCELLED"
    if integrity_blocked or stdout.snapshot()["failed"] or stderr.snapshot()["failed"]:
        return "RESULT_INTEGRITY_BLOCKED"
    if terminal_failure:
        return "FAILED"
    if exit_code == 0 and stdin.snapshot()["complete"] and terminal_success:
        return "COMPLETED"
    return "FAILED"


def _publish_terminal_event(
    handle: ExecutionHandle,
    classifier: _JsonlStreamClassifier,
    *,
    retained_stdout_bytes: int,
) -> dict[str, object]:
    summary = classifier.summary(retained_stdout_bytes=retained_stdout_bytes)
    agent_message_binding: dict[str, object] | None = None
    if classifier.last_agent_message_event:
        agent_path = handle.phase_directory / "stdout-agent-message-event.jsonl"
        agent_observed = _create_immutable_file(
            agent_path, classifier.last_agent_message_event
        )
        agent_message_binding = {
            "relative_path": agent_path.name,
            "size": len(classifier.last_agent_message_event),
            "sha256": hashlib.sha256(
                classifier.last_agent_message_event
            ).hexdigest(),
            "device": agent_observed.st_dev,
            "inode": agent_observed.st_ino,
            "stream_sequence": classifier.last_agent_message_event_sequence,
            "turn_identity": classifier.last_agent_message_turn_identity,
            "selection": classifier.last_agent_message_selection,
            "canonicalization": classifier.last_agent_message_canonicalization,
            "schema_status": classifier.last_agent_message_schema_status,
            "canonical_size": classifier.last_agent_message_bytes,
            "canonical_sha256": classifier.last_agent_message_sha256,
            "source_text_size": classifier.last_agent_message_source_bytes,
            "source_text_sha256": classifier.last_agent_message_source_sha256,
        }
    terminal_binding: dict[str, object] | None = None
    if classifier.last_terminal_event:
        event_path = handle.phase_directory / "stdout-terminal-event.jsonl"
        observed = _create_immutable_file(event_path, classifier.last_terminal_event)
        terminal_binding = {
            "relative_path": event_path.name,
            "size": len(classifier.last_terminal_event),
            "sha256": hashlib.sha256(classifier.last_terminal_event).hexdigest(),
            "device": observed.st_dev,
            "inode": observed.st_ino,
            "event_type": classifier.last_terminal_event_type,
            "stream_sequence": classifier.last_terminal_event_sequence,
            "observed_at": classifier.last_terminal_event_observed_at,
            "reported_at": classifier.last_terminal_event_reported_at,
            "turn_identity": classifier.last_terminal_turn_identity,
        }
    return {
        **summary,
        "agent_message_event": agent_message_binding,
        "terminal_event": terminal_binding,
    }


def _final_message_binding_identity(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
) -> str:
    binding = ticket.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_BINDING_INVALID",
            "The final-message binding is invalid.",
        )
    return _canonical_sha256(
        {
            "ticket_digest": handle.ticket_digest,
            "phase_key": handle.phase_key,
            "phase": ticket.get("phase"),
            "relative_path": binding.get("relative_path"),
            "maximum_bytes": binding.get("maximum_bytes"),
            "capture_mode": binding.get("capture_mode", "sidecar_required"),
        }
    )


def _publish_final_message_absence(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
) -> dict[str, object]:
    binding = ticket.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_BINDING_INVALID",
            "The final-message binding is invalid.",
        )
    final_path = handle.phase_directory / str(binding.get("relative_path") or "")
    if final_path.exists() or final_path.is_symlink():
        raise CodexExecBridgeError(
            "PARTIAL_FINAL_MESSAGE_EXISTS",
            "A prior final-message artifact prevents duplicate execution.",
        )
    parent = _validate_phase_directory(handle.spool_root, handle.phase_directory)
    checked_at = _utc_now()
    payload: dict[str, object] = {
        "schema": FINAL_MESSAGE_ABSENCE_SCHEMA,
        "policy": BRIDGE_POLICY,
        "ticket_digest": handle.ticket_digest,
        "phase_key": handle.phase_key,
        "phase": ticket.get("phase"),
        "final_message_relative_path": binding.get("relative_path"),
        "final_message_binding_identity": _final_message_binding_identity(
            handle, ticket
        ),
        "checked_at": checked_at,
        "parent_directory_identity": {
            "device": parent.st_dev,
            "inode": parent.st_ino,
        },
    }
    path = handle.phase_directory / "final-message-absence.json"
    try:
        observed = _create_immutable_json(path, payload)
    except CodexExecBridgeError as exc:
        if exc.code == "IMMUTABLE_FILE_EXISTS":
            raise CodexExecBridgeError(
                "FINAL_MESSAGE_ABSENCE_PROOF_EXISTS",
                "A prior launch-attempt proof prevents duplicate execution.",
            ) from exc
        raise
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    return {
        "relative_path": path.name,
        "size": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "checked_at": checked_at,
        "final_message_binding_identity": payload[
            "final_message_binding_identity"
        ],
    }


def _validate_final_message_absence(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    receipt: Mapping[str, object],
) -> None:
    proof_path = handle.phase_directory / "final-message-absence.json"
    receipt_binding = receipt.get("final_message_absence")
    proof_exists = proof_path.exists() or proof_path.is_symlink()
    if receipt_binding is None and not proof_exists:
        # Compatibility for sealed receipts created before absence proofs were
        # introduced. Every new attempt publishes and binds the proof.
        return
    if not isinstance(receipt_binding, dict) or not proof_exists:
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_ABSENCE_BINDING_INVALID",
            "The launch-time final-message absence proof is unavailable.",
        )
    payload, observed = _read_protected_json(proof_path)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    if (
        receipt_binding.get("relative_path") != proof_path.name
        or receipt_binding.get("size") != len(encoded)
        or receipt_binding.get("sha256") != hashlib.sha256(encoded).hexdigest()
        or receipt_binding.get("device") != observed.st_dev
        or receipt_binding.get("inode") != observed.st_ino
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_ABSENCE_BINDING_INVALID",
            "The launch-time final-message absence proof failed integrity validation.",
        )
    final_binding = ticket.get("final_message")
    parent = _validate_phase_directory(handle.spool_root, handle.phase_directory)
    parent_identity = payload.get("parent_directory_identity")
    if (
        payload.get("schema") != FINAL_MESSAGE_ABSENCE_SCHEMA
        or payload.get("policy") != BRIDGE_POLICY
        or payload.get("ticket_digest") != handle.ticket_digest
        or payload.get("phase_key") != handle.phase_key
        or payload.get("phase") != ticket.get("phase")
        or not isinstance(final_binding, dict)
        or payload.get("final_message_relative_path")
        != final_binding.get("relative_path")
        or payload.get("final_message_binding_identity")
        != _final_message_binding_identity(handle, ticket)
        or receipt_binding.get("final_message_binding_identity")
        != payload.get("final_message_binding_identity")
        or receipt_binding.get("checked_at") != payload.get("checked_at")
        or not isinstance(parent_identity, dict)
        or parent_identity.get("device") != parent.st_dev
        or parent_identity.get("inode") != parent.st_ino
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_ABSENCE_BINDING_INVALID",
            "The launch-time final-message absence proof changed identity.",
        )


def _sanitize_final_message_file(
    path: Path,
    *,
    maximum: int,
    persistent_secrets: Sequence[bytes],
) -> None:
    payload, observed = _read_protected_bytes(path, maximum=maximum)
    redacted = _redact_persisted_output(payload, persistent_secrets)
    if redacted == payload:
        return
    flags = os.O_WRONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        current = os.fstat(fd)
        if (
            current.st_dev != observed.st_dev
            or current.st_ino != observed.st_ino
            or not stat.S_ISREG(current.st_mode)
            or current.st_uid != os.getuid()
            or stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE
        ):
            raise CodexExecBridgeError(
                "FINAL_MESSAGE_REPLACED",
                "The final message changed before credential-safe retention.",
            )
        os.ftruncate(fd, 0)
        _write_all(fd, redacted)
        os.fsync(fd)
    finally:
        os.close(fd)


def _bind_final_message(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    *,
    persistent_secrets: Sequence[bytes] = (),
) -> dict[str, object]:
    binding = ticket.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError("FINAL_MESSAGE_BINDING_INVALID", "The final-message binding is invalid.")
    relative_path = str(binding.get("relative_path") or "")
    maximum = int(binding.get("maximum_bytes") or 0)
    binding_identity = _final_message_binding_identity(handle, ticket)
    path = handle.phase_directory / relative_path
    if not path.exists() and not path.is_symlink():
        return {
            "present": False,
            "relative_path": relative_path,
            "maximum_bytes": maximum,
            "ticket_binding_identity": binding_identity,
        }
    _sanitize_final_message_file(
        path,
        maximum=maximum,
        persistent_secrets=persistent_secrets,
    )
    digest, size, observed = _hash_file(path, maximum=maximum)
    payload, payload_stat = _read_protected_bytes(path, maximum=maximum)
    if (
        payload_stat.st_dev != observed.st_dev
        or payload_stat.st_ino != observed.st_ino
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_REPLACED",
            "The final message changed while its receipt was created.",
        )
    try:
        decoded = payload.decode("utf-8")
        normalized = _normalize_result_text(decoded).encode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_INVALID",
            "The final message is not UTF-8 text.",
        ) from exc
    if b"\x00" in normalized:
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_INVALID",
            "The final message contains invalid text.",
        )
    canonical, canonicalization, schema_status = _canonical_result_text(
        decoded,
        phase=str(ticket.get("phase") or ""),
    )
    return {
        "present": True,
        "valid": True,
        "relative_path": relative_path,
        "maximum_bytes": maximum,
        "size": size,
        "sha256": digest,
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "normalized_size": len(normalized),
        "normalized_sha256": hashlib.sha256(normalized).hexdigest(),
        "canonical_size": len(canonical),
        "canonical_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonicalization": canonicalization,
        "schema_status": schema_status,
        "ticket_binding_identity": binding_identity,
    }


def _settle_final_message(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    *,
    process_exited_monotonic: float,
    persistent_secrets: Sequence[bytes] = (),
) -> dict[str, object]:
    """Wait for a stable final sidecar without confusing process exit with durability."""
    binding = ticket.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_BINDING_INVALID", "The final-message binding is invalid."
        )
    relative_path = str(binding.get("relative_path") or "")
    maximum = int(binding.get("maximum_bytes") or 0)
    binding_identity = _final_message_binding_identity(handle, ticket)
    deadline = time.monotonic() + FINAL_MESSAGE_SETTLEMENT_SECONDS
    previous_signature: tuple[object, ...] | None = None
    last_error_code = ""
    observed_once = False
    while True:
        try:
            candidate = _bind_final_message(
                handle,
                ticket,
                persistent_secrets=persistent_secrets,
            )
        except CodexExecBridgeError as exc:
            candidate = None
            last_error_code = exc.code
            observed_once = True
        if candidate is not None and candidate.get("present") is True:
            observed_once = True
            signature = (
                candidate.get("device"),
                candidate.get("inode"),
                candidate.get("size"),
                candidate.get("sha256"),
                candidate.get("normalized_size"),
                candidate.get("normalized_sha256"),
            )
            if signature == previous_signature:
                settled_at = _utc_now()
                return {
                    **candidate,
                    "settlement": {
                        "status": "VALID",
                        "window_seconds": FINAL_MESSAGE_SETTLEMENT_SECONDS,
                        "waited_ms": max(
                            0,
                            int(
                                (time.monotonic() - process_exited_monotonic)
                                * 1000
                            ),
                        ),
                        "settled_at": settled_at,
                        "validation_error_code": "",
                        "blocker_code": "",
                    },
                }
            previous_signature = signature
        else:
            previous_signature = None
        if time.monotonic() >= deadline:
            status = "INVALID" if observed_once else "MISSING"
            validation_error_code = (
                last_error_code
                if last_error_code
                else "FINAL_MESSAGE_UNSTABLE"
                if observed_once
                else ""
            )
            return {
                "present": False,
                "valid": False,
                "relative_path": relative_path,
                "maximum_bytes": maximum,
                "ticket_binding_identity": binding_identity,
                "settlement": {
                    "status": status,
                    "window_seconds": FINAL_MESSAGE_SETTLEMENT_SECONDS,
                    "waited_ms": max(
                        0,
                        int(
                            (time.monotonic() - process_exited_monotonic) * 1000
                        ),
                    ),
                    "settled_at": _utc_now(),
                    "validation_error_code": validation_error_code,
                    "blocker_code": (
                        "SIDECAR_ATTEMPT_IDENTITY_MISMATCH"
                        if status == "INVALID"
                        else "FINAL_AGENT_MESSAGE_UNAVAILABLE"
                    ),
                },
            }
        time.sleep(FINAL_MESSAGE_SETTLEMENT_POLL_SECONDS)


def _observe_final_message_once(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    *,
    persistent_secrets: Sequence[bytes] = (),
) -> dict[str, object]:
    binding = ticket.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_BINDING_INVALID", "The final-message binding is invalid."
        )
    try:
        candidate = _bind_final_message(
            handle,
            ticket,
            persistent_secrets=persistent_secrets,
        )
    except CodexExecBridgeError as exc:
        return {
            "present": False,
            "valid": False,
            "relative_path": str(binding.get("relative_path") or ""),
            "maximum_bytes": int(binding.get("maximum_bytes") or 0),
            "ticket_binding_identity": _final_message_binding_identity(
                handle, ticket
            ),
            "settlement": {
                "status": "INVALID",
                "window_seconds": 0.0,
                "waited_ms": 0,
                "settled_at": _utc_now(),
                "validation_error_code": exc.code,
                "blocker_code": "SIDECAR_ATTEMPT_IDENTITY_MISMATCH",
            },
        }
    return {
        **candidate,
        "valid": candidate.get("present") is True,
        "settlement": {
            "status": "VALID" if candidate.get("present") is True else "MISSING",
            "window_seconds": 0.0,
            "waited_ms": 0,
            "settled_at": _utc_now(),
            "validation_error_code": "",
            "blocker_code": (
                "" if candidate.get("present") is True else "FINAL_AGENT_MESSAGE_UNAVAILABLE"
            ),
        },
    }


def _jsonl_final_message_recovery(
    stdout_jsonl: Mapping[str, object],
    *,
    stdout: Mapping[str, object],
    stderr: Mapping[str, object],
    final_message: Mapping[str, object],
) -> dict[str, object]:
    terminal_truth = stdout_jsonl.get("terminal_truth")
    same_turn_success = bool(
        isinstance(terminal_truth, dict)
        and terminal_truth.get("success") is True
        and terminal_truth.get("same_turn_final_agent_message") is True
    )
    streams_settled = bool(
        stdout.get("completed") is True
        and stdout.get("eof") is True
        and stdout.get("failed") is not True
        and stdout.get("incomplete") is not True
        and stderr.get("completed") is True
        and stderr.get("eof") is True
        and stderr.get("failed") is not True
        and stderr.get("incomplete") is not True
        and stdout_jsonl.get("eof_received") is True
        and stdout_jsonl.get("trailing_partial_line_resolved") is True
    )
    unambiguous = bool(
        int(
            stdout_jsonl.get("valid_agent_message_count")
            or stdout_jsonl.get("agent_message_count")
            or 0
        )
        >= 1
        and stdout_jsonl.get("malformed_count") == 0
        and int(stdout_jsonl.get("lifecycle_conflict_count") or 0) == 0
        and isinstance(stdout_jsonl.get("agent_message_event"), dict)
    )
    settlement = final_message.get("settlement")
    settlement = settlement if isinstance(settlement, Mapping) else {}
    genuine_missing = bool(
        final_message.get("present") is not True
        and settlement.get("status") == "MISSING"
        and not settlement.get("validation_error_code")
        and settlement.get("blocker_code") == "FINAL_AGENT_MESSAGE_UNAVAILABLE"
    )
    independently_proven_write_failure = bool(
        final_message.get("present") is not True
        and settlement.get("status") == "WRITE_FAILED"
        and settlement.get("validation_error_code")
        == "FINAL_MESSAGE_WRITE_FAILED_PROVEN"
    )
    selected_schema_status = str(
        stdout_jsonl.get("last_agent_message_schema_status") or "UNAVAILABLE"
    )
    eligible = bool(
        (genuine_missing or independently_proven_write_failure)
        and same_turn_success
        and streams_settled
        and unambiguous
        and selected_schema_status == "VALID"
    )
    return {
        "eligible_candidate": eligible,
        "source": "FINAL_AGENT_MESSAGE_JSONL" if eligible else "",
        "message_size": (
            int(stdout_jsonl.get("last_agent_message_bytes") or 0)
            if eligible
            else 0
        ),
        "message_sha256": (
            str(stdout_jsonl.get("last_agent_message_sha256") or "")
            if eligible
            else ""
        ),
        "same_turn_terminal_success": same_turn_success,
        "streams_settled": streams_settled,
        "unambiguous": unambiguous,
        "selected_schema_status": selected_schema_status,
        "sidecar_settlement_status": str(settlement.get("status") or ""),
        "sidecar_blocker_code": str(settlement.get("blocker_code") or ""),
        "genuine_missing": genuine_missing,
        "independently_proven_write_failure": independently_proven_write_failure,
        "schema_validation": (
            "PHASE_SCHEMA_VALID"
            if eligible and selected_schema_status == "VALID"
            else "REQUIRED_BY_HIGHER_LAYER"
            if eligible
            else "NOT_ELIGIBLE"
        ),
        "identity_validation": "REQUIRED_BY_HIGHER_LAYER" if eligible else "NOT_ELIGIBLE",
    }


def _terminal_receipt(
    handle: ExecutionHandle,
    ticket: Mapping[str, object],
    *,
    state: str,
    exit_code: int | None,
    terminal_reason: str,
    sidecar_identity: str,
    child_process_id: int,
    child_start_identity: str,
    stdin: _StdinDelivery,
    stdout: _DrainCapture,
    stderr: _DrainCapture,
    stdout_stat: os.stat_result,
    stderr_stat: os.stat_result,
    started_at: str,
    started_monotonic: float,
    process_exited_at: str,
    process_exit_elapsed_ms: int,
    heartbeat_sequence: int,
    stdout_jsonl: Mapping[str, object],
    final_message: Mapping[str, object],
    final_message_absence: Mapping[str, object],
    outcome_facts: Mapping[str, object],
) -> dict[str, object]:
    stdout_value = stdout.snapshot()
    stderr_value = stderr.snapshot()
    terminal_at = _utc_now()
    return {
        "schema": TERMINAL_RECEIPT_SCHEMA,
        "policy": BRIDGE_POLICY,
        "classifier_rule": JSONL_CLASSIFIER_RULE,
        "final_result_selection_rule": FINAL_RESULT_SELECTION_RULE,
        "canonicalization_rule": FINAL_RESULT_CANONICALIZATION_RULE,
        "ticket_digest": handle.ticket_digest,
        "phase": ticket.get("phase"),
        "terminal_state": state,
        "terminal_reason": terminal_reason,
        "terminal_blocker_code": str(
            outcome_facts.get("result_blocker_code") or ""
        ),
        "process_exit_code": exit_code,
        "process_exit_signal": -exit_code if isinstance(exit_code, int) and exit_code < 0 else None,
        "process_exited_at": process_exited_at,
        "process_exit_elapsed_ms": process_exit_elapsed_ms,
        "started_at": started_at,
        "terminal_at": terminal_at,
        "duration_ms": max(0, int((time.monotonic() - started_monotonic) * 1000)),
        "sidecar_process_id": os.getpid(),
        "sidecar_process_start_identity": sidecar_identity,
        "child_process_id": child_process_id,
        "child_process_start_identity": child_start_identity,
        "heartbeat_sequence": heartbeat_sequence,
        "outcome_facts": dict(outcome_facts),
        "stream_settlement": {
            "stdout_eof": stdout_value["eof"],
            "stdout_completed": stdout_value["completed"],
            "stdout_completed_at": stdout_value["completed_at"],
            "stdout_incomplete": stdout_value["incomplete"],
            "stderr_eof": stderr_value["eof"],
            "stderr_completed": stderr_value["completed"],
            "stderr_completed_at": stderr_value["completed_at"],
            "stderr_incomplete": stderr_value["incomplete"],
            "trailing_partial_line_present": stdout_jsonl.get(
                "trailing_partial_line_present"
            ),
            "trailing_partial_line_resolved": stdout_jsonl.get(
                "trailing_partial_line_resolved"
            ),
        },
        "stdin_delivery": stdin.snapshot(),
        "combined_output": {
            "limit_bytes": ticket["limits"]["combined_output_bytes"],
            "observed_bytes": stdout_value["observed_bytes"] + stderr_value["observed_bytes"],
            "retained_bytes": stdout_value["retained_bytes"] + stderr_value["retained_bytes"],
        },
        "stream_offsets": {
            "stdout_observed": stdout_value["observed_bytes"],
            "stdout_retained": stdout_value["retained_bytes"],
            "stderr_observed": stderr_value["observed_bytes"],
            "stderr_retained": stderr_value["retained_bytes"],
        },
        "chunk_histogram": {
            "stdout": stdout_value["chunk_histogram"],
            "stderr": stderr_value["chunk_histogram"],
        },
        "stdout_jsonl": dict(stdout_jsonl),
        "final_message": dict(final_message),
        "final_message_absence": dict(final_message_absence),
        "stdout": {
            **stdout_value,
            "relative_path": "stdout.bin",
            "device": stdout_stat.st_dev,
            "inode": stdout_stat.st_ino,
        },
        "stderr": {
            **stderr_value,
            "relative_path": "stderr.bin",
            "device": stderr_stat.st_dev,
            "inode": stderr_stat.st_ino,
        },
    }


def load_terminal_receipt(handle: ExecutionHandle) -> dict[str, object] | None:
    ticket = _load_ticket_and_seal(handle)
    path = handle.phase_directory / "terminal.json"
    if not path.exists() and not path.is_symlink():
        return None
    value, _ = _read_protected_json(path)
    if (
        value.get("schema") != TERMINAL_RECEIPT_SCHEMA
        or value.get("policy") != BRIDGE_POLICY
        or value.get("ticket_digest") != handle.ticket_digest
    ):
        raise CodexExecBridgeError("TERMINAL_RECEIPT_INVALID", "The terminal receipt failed its identity check.")
    rule_values = (
        value.get("classifier_rule"),
        value.get("final_result_selection_rule"),
        value.get("canonicalization_rule"),
    )
    if any(item is not None for item in rule_values):
        stdout_jsonl = value.get("stdout_jsonl")
        if (
            rule_values
            != (
                JSONL_CLASSIFIER_RULE,
                FINAL_RESULT_SELECTION_RULE,
                FINAL_RESULT_CANONICALIZATION_RULE,
            )
            or not isinstance(stdout_jsonl, dict)
            or stdout_jsonl.get("classifier_rule") != JSONL_CLASSIFIER_RULE
            or stdout_jsonl.get("final_result_selection_rule")
            != FINAL_RESULT_SELECTION_RULE
            or stdout_jsonl.get("canonicalization_rule")
            != FINAL_RESULT_CANONICALIZATION_RULE
        ):
            raise CodexExecBridgeError(
                "TERMINAL_RECEIPT_RULE_INVALID",
                "The terminal receipt changed its classifier or canonicalization rule.",
            )
    _validate_final_message_absence(handle, ticket, value)
    return value


def load_execution_state(handle: ExecutionHandle) -> dict[str, object] | None:
    _load_ticket_and_seal(handle)
    path = handle.phase_directory / "state.json"
    value: dict[str, object] | None = None
    for attempt in range(3):
        if not path.exists() and not path.is_symlink():
            return None
        try:
            value, _ = _read_protected_json(path)
            break
        except CodexExecBridgeError as exc:
            if exc.code != "PROTECTED_FILE_REPLACED" or attempt == 2:
                raise
            # state.json is the one deliberately replaceable heartbeat file.
            # Retry only this exact, fully revalidated atomic-publication race;
            # immutable tickets, launches and receipts never get this path.
            time.sleep(0.001)
    if value is None:
        raise CodexExecBridgeError(
            "STATE_UNAVAILABLE",
            "The durable execution state could not be read safely.",
        )
    if (
        value.get("schema") != STATE_SCHEMA
        or value.get("policy") != BRIDGE_POLICY
        or value.get("ticket_digest") != handle.ticket_digest
    ):
        raise CodexExecBridgeError("STATE_INVALID", "The durable execution state failed its identity check.")
    return value


def run_execution(
    handle: ExecutionHandle,
    *,
    shutdown_event: threading.Event | None = None,
) -> dict[str, object]:
    ticket = _load_ticket_and_seal(handle)
    existing_terminal = load_terminal_receipt(handle)
    if existing_terminal is not None:
        return existing_terminal
    lease_fd = _open_lease(handle.phase_directory / "lease.lock")
    try:
        existing_terminal = load_terminal_receipt(handle)
        if existing_terminal is not None:
            return existing_terminal
        _validate_runtime_bindings(ticket)
        started_at = _utc_now()
        started_monotonic = time.monotonic()
        sidecar_identity = capture_process_start_identity(os.getpid())
        if not sidecar_identity:
            raise CodexExecBridgeError("SIDECAR_IDENTITY_UNAVAILABLE", "The sidecar process identity could not be verified.")
        sequence = 0
        initial_state = _snapshot_state(
            handle,
            ticket,
            state="STARTING",
            sequence=sequence,
            sidecar_identity=sidecar_identity,
            child_process_id=0,
            child_start_identity="",
            stdout=None,
            stderr=None,
            stdin=None,
            started_at=started_at,
        )
        _atomic_replace_json(handle.phase_directory / "state.json", initial_state)
        final_message_binding = ticket.get("final_message")
        if not isinstance(final_message_binding, dict):
            raise CodexExecBridgeError("FINAL_MESSAGE_BINDING_INVALID", "The final-message binding is invalid.")
        final_message_absence = _publish_final_message_absence(handle, ticket)
        stdout_fd, stdout_stat = _create_capture_file(handle.phase_directory / "stdout.bin")
        try:
            stderr_fd, stderr_stat = _create_capture_file(handle.phase_directory / "stderr.bin")
        except Exception:
            os.close(stdout_fd)
            raise
        argv = ticket.get("argv")
        limits = ticket.get("limits")
        stdin_binding = ticket.get("stdin")
        if not isinstance(argv, list) or not isinstance(limits, dict) or not isinstance(stdin_binding, dict):
            os.close(stdout_fd)
            os.close(stderr_fd)
            raise CodexExecBridgeError("TICKET_INVALID", "The execution ticket is incomplete.")
        process: subprocess.Popen[bytes] | None = None
        child_environment = _child_environment(ticket)
        persistent_secrets = _persistent_secret_values(child_environment)
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(ticket["working_directory"]),
                env=child_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
                close_fds=True,
                umask=0o077,
            )
        except (OSError, ValueError):
            os.close(stdout_fd)
            os.close(stderr_fd)
            raise CodexExecBridgeError("PROCESS_SPAWN_FAILED", "The exact Codex process could not be started.")
        if process.stdin is None or process.stdout is None or process.stderr is None:
            cleaned = _terminate_unbound_sidecar(process)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            os.close(stdout_fd)
            os.close(stderr_fd)
            if not cleaned:
                raise CodexExecBridgeError("PROCESS_CLEANUP_FAILED", "The unpublished Codex process could not be reaped.")
            raise CodexExecBridgeError("PROCESS_PIPE_FAILED", "The exact Codex process pipes are unavailable.")
        child_start_identity = capture_process_start_identity(process.pid)
        if not child_start_identity:
            cleaned = _terminate_unbound_sidecar(process)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            os.close(stdout_fd)
            os.close(stderr_fd)
            if not cleaned:
                raise CodexExecBridgeError("PROCESS_CLEANUP_FAILED", "The unpublished Codex process could not be reaped.")
            raise CodexExecBridgeError("PROCESS_IDENTITY_UNAVAILABLE", "The exact Codex process identity could not be verified.")

        budget = _RetentionBudget(int(limits["combined_output_bytes"]))
        jsonl_classifier = _JsonlStreamClassifier(phase=str(ticket["phase"]))
        stdout = _DrainCapture(
            "stdout",
            process.stdout,
            stdout_fd,
            budget,
            jsonl_classifier=jsonl_classifier,
            persistent_secrets=persistent_secrets,
        )
        stderr = _DrainCapture(
            "stderr",
            process.stderr,
            stderr_fd,
            budget,
            persistent_secrets=persistent_secrets,
        )
        stdin = _StdinDelivery(int(stdin_binding["size"]), str(stdin_binding["sha256"]))
        stdout_thread = threading.Thread(target=stdout.drain, name=f"twos-{handle.phase_key}-stdout", daemon=True)
        stderr_thread = threading.Thread(target=stderr.drain, name=f"twos-{handle.phase_key}-stderr", daemon=True)
        stdin_thread = threading.Thread(
            target=stdin.deliver,
            args=(process.stdin, handle.phase_directory / "stdin.bin"),
            name=f"twos-{handle.phase_key}-stdin",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        stdin_thread.start()

        timeout_seconds = float(limits["timeout_seconds"])
        heartbeat_seconds = float(limits["heartbeat_interval_seconds"])
        next_heartbeat = time.monotonic()
        timed_out = False
        cancelled = False
        integrity_blocked = False
        integrity_reasons: list[str] = []
        terminal_reason = "process_exited"
        while process.poll() is None:
            now = time.monotonic()
            if not process_identity_matches(process.pid, child_start_identity):
                # A short-lived child can exit between poll() and the identity
                # observation. Reap that normal exit before classifying reuse.
                if process.poll() is None:
                    integrity_blocked = True
                    integrity_reasons.append("process_identity_changed")
                    terminal_reason = "process_identity_changed"
                break
            if shutdown_event is not None and shutdown_event.is_set():
                cancelled = True
                terminal_reason = "sidecar_shutdown_requested"
                break
            if _cancel_requested(handle):
                cancelled = True
                terminal_reason = "owner_cancel_requested"
                break
            if now - started_monotonic >= timeout_seconds:
                timed_out = True
                terminal_reason = "timeout"
                break
            if now >= next_heartbeat:
                sequence += 1
                _atomic_replace_json(
                    handle.phase_directory / "state.json",
                    _snapshot_state(
                        handle,
                        ticket,
                        state="RUNNING",
                        sequence=sequence,
                        sidecar_identity=sidecar_identity,
                        child_process_id=process.pid,
                        child_start_identity=child_start_identity,
                        stdout=stdout,
                        stderr=stderr,
                        stdin=stdin,
                        started_at=started_at,
                    ),
                )
                next_heartbeat = now + heartbeat_seconds
            time.sleep(min(0.02, heartbeat_seconds))

        if process.poll() is None:
            if not _terminate_exact_process(process, child_start_identity):
                integrity_blocked = True
                integrity_reasons.append("process_identity_changed")
                terminal_reason = "process_identity_changed"
        try:
            exit_code = process.wait(timeout=PROCESS_STOP_GRACE_SECONDS + 1)
        except subprocess.TimeoutExpired:
            exit_code = None
            integrity_blocked = True
            integrity_reasons.append("process_did_not_terminate")
            terminal_reason = "process_did_not_terminate"
        process_exited_at = _utc_now() if exit_code is not None else ""
        process_exited_monotonic = time.monotonic()
        process_exit_elapsed_ms = max(
            0, int((process_exited_monotonic - started_monotonic) * 1000)
        )

        drain_deadline = time.monotonic() + STREAM_SETTLEMENT_SECONDS
        for drain_thread in (stdin_thread, stdout_thread, stderr_thread):
            drain_thread.join(max(0.0, drain_deadline - time.monotonic()))
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            stdout.request_stop()
            stderr.request_stop()
            stdout_thread.join(STREAM_FORCED_STOP_SECONDS)
            stderr_thread.join(STREAM_FORCED_STOP_SECONDS)
        if stdin_thread.is_alive():
            try:
                process.stdin.close()
            except Exception:
                pass
            stdin_thread.join(STREAM_FORCED_STOP_SECONDS)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            # The classifier is owned by the stdout drain thread. Publishing
            # while that thread can still mutate it would create a receipt
            # race, so fail closed without publishing conflicting evidence.
            raise CodexExecBridgeError(
                "STREAM_DRAIN_DID_NOT_STOP",
                "The execution streams could not be settled without a receipt race.",
            )
        if stdin_thread.is_alive():
            integrity_blocked = True
            integrity_reasons.append("stdin_collection_incomplete")
            if not timed_out and not cancelled:
                terminal_reason = "stdin_collection_incomplete"
        stdout_snapshot = stdout.snapshot()
        stderr_snapshot = stderr.snapshot()
        if (
            stdout_snapshot.get("completed") is not True
            or stdout_snapshot.get("eof") is not True
            or stdout_snapshot.get("incomplete") is True
            or stderr_snapshot.get("completed") is not True
            or stderr_snapshot.get("eof") is not True
            or stderr_snapshot.get("incomplete") is True
        ):
            integrity_blocked = True
            integrity_reasons.append("stream_collection_incomplete")
            if not timed_out and not cancelled:
                terminal_reason = "stream_collection_incomplete"
        stdout_jsonl = _publish_terminal_event(
            handle,
            jsonl_classifier,
            retained_stdout_bytes=int(stdout_snapshot["retained_bytes"]),
        )
        terminal_truth = stdout_jsonl.get("terminal_truth")
        terminal_success = bool(
            isinstance(terminal_truth, dict)
            and terminal_truth.get("success") is True
        )
        terminal_failure = bool(
            isinstance(terminal_truth, dict)
            and terminal_truth.get("failure") is True
        )
        terminal_contradiction = bool(
            isinstance(terminal_truth, dict)
            and terminal_truth.get("contradiction") is True
        )
        if stdout_jsonl.get("eof_received") is not True:
            integrity_blocked = True
            integrity_reasons.append("stdout_eof_missing")
            if not timed_out and not cancelled:
                terminal_reason = "stdout_eof_missing"
        if stdout_jsonl.get("trailing_partial_line_resolved") is not True:
            integrity_blocked = True
            integrity_reasons.append("stdout_trailing_partial_unresolved")
            if not timed_out and not cancelled:
                terminal_reason = "stdout_trailing_partial_unresolved"
        if int(stdout_jsonl.get("malformed_count") or 0) > 0:
            integrity_blocked = True
            integrity_reasons.append("stdout_jsonl_malformed")
            if not timed_out and not cancelled and terminal_reason == "process_exited":
                terminal_reason = "stdout_jsonl_malformed"
        if terminal_contradiction:
            integrity_blocked = True
            integrity_reasons.append("terminal_event_contradiction")
            if not timed_out and not cancelled and terminal_reason == "process_exited":
                terminal_reason = "terminal_event_contradiction"
        elif not terminal_success and not terminal_failure:
            integrity_blocked = True
            integrity_reasons.append("terminal_event_unresolved")
            if not timed_out and not cancelled and terminal_reason == "process_exited":
                terminal_reason = "terminal_event_unresolved"
        elif (
            terminal_failure
            and not timed_out
            and not cancelled
            and terminal_reason == "process_exited"
        ):
            terminal_reason = "turn_failed"

        streams_settled = bool(
            stdout_snapshot.get("completed") is True
            and stdout_snapshot.get("eof") is True
            and stdout_snapshot.get("incomplete") is not True
            and stderr_snapshot.get("completed") is True
            and stderr_snapshot.get("eof") is True
            and stderr_snapshot.get("incomplete") is not True
            and stdout_jsonl.get("eof_received") is True
            and stdout_jsonl.get("trailing_partial_line_resolved") is True
        )
        jsonl_only_result = bool(
            isinstance(final_message_binding, Mapping)
            and final_message_binding.get("capture_mode") == "jsonl_only"
        )
        if jsonl_only_result:
            final_message = _observe_final_message_once(
                handle,
                ticket,
                persistent_secrets=persistent_secrets,
            )
        elif exit_code == 0 and terminal_success and streams_settled:
            final_message = _settle_final_message(
                handle,
                ticket,
                process_exited_monotonic=process_exited_monotonic,
                persistent_secrets=persistent_secrets,
            )
        else:
            final_message = _observe_final_message_once(
                handle,
                ticket,
                persistent_secrets=persistent_secrets,
            )
        final_message_matches_jsonl = False
        result_representation_normalized = False
        if exit_code == 0 and terminal_success:
            if jsonl_only_result:
                if int(stdout_jsonl.get("agent_message_count") or 0) < 1:
                    integrity_blocked = True
                    integrity_reasons.append("agent_message_missing")
                    if not timed_out and not cancelled and terminal_reason == "process_exited":
                        terminal_reason = "agent_message_missing"
                else:
                    # In JSONL-only mode the final agent-message event is the
                    # transport-bound result representation.  Its presence and
                    # same-turn binding are transport facts; the higher layer
                    # separately decides whether its body is a valid TWOS
                    # structured handoff.  Plain text or an unrelated schema
                    # therefore remains honest, settled result evidence rather
                    # than masquerading as transport corruption.
                    final_message_matches_jsonl = True
            elif final_message.get("present") is not True:
                integrity_blocked = True
                settlement = final_message.get("settlement")
                settlement = settlement if isinstance(settlement, Mapping) else {}
                if (
                    settlement.get("blocker_code")
                    == "SIDECAR_ATTEMPT_IDENTITY_MISMATCH"
                ):
                    integrity_reasons.append(
                        "sidecar_attempt_identity_mismatch"
                    )
                    if (
                        not timed_out
                        and not cancelled
                        and terminal_reason == "process_exited"
                    ):
                        terminal_reason = "sidecar_attempt_identity_mismatch"
                else:
                    integrity_reasons.append("final_message_missing")
                    if (
                        not timed_out
                        and not cancelled
                        and terminal_reason == "process_exited"
                    ):
                        terminal_reason = "final_message_missing"
            elif int(stdout_jsonl.get("agent_message_count") or 0) < 1:
                integrity_blocked = True
                integrity_reasons.append("agent_message_missing")
                if not timed_out and not cancelled and terminal_reason == "process_exited":
                    terminal_reason = "agent_message_missing"
            else:
                final_message_matches_jsonl = bool(
                    final_message.get("canonical_size")
                    == stdout_jsonl.get("last_agent_message_bytes")
                    and final_message.get("canonical_sha256")
                    == stdout_jsonl.get("last_agent_message_sha256")
                )
                result_representation_normalized = bool(
                    final_message_matches_jsonl
                    and (
                        final_message.get("size")
                        != stdout_jsonl.get("last_agent_message_source_bytes")
                        or final_message.get("sha256")
                        != stdout_jsonl.get(
                            "last_agent_message_source_sha256"
                        )
                    )
                )
                if not final_message_matches_jsonl:
                    integrity_blocked = True
                    integrity_reasons.append("final_message_jsonl_mismatch")
                    if not timed_out and not cancelled and terminal_reason == "process_exited":
                        terminal_reason = "final_message_jsonl_mismatch"
                elif stdout_jsonl.get("last_agent_message_schema_status") in {
                    "INVALID_JSON",
                    "INVALID_STATUS",
                    "INVALID_SHAPE",
                }:
                    integrity_blocked = True
                    integrity_reasons.append("final_result_schema_invalid")
                    if (
                        not timed_out
                        and not cancelled
                        and terminal_reason == "process_exited"
                    ):
                        terminal_reason = "final_result_schema_invalid"
        elif (
            exit_code not in (0, None)
            and not timed_out
            and not cancelled
            and terminal_reason == "process_exited"
        ):
            terminal_reason = "process_exit_failed"
        recovery = _jsonl_final_message_recovery(
            stdout_jsonl,
            stdout=stdout_snapshot,
            stderr=stderr_snapshot,
            final_message=final_message,
        )
        final_message = {
            **final_message,
            "capture_mode": (
                "jsonl_only" if jsonl_only_result else "sidecar_required"
            ),
            "matches_last_agent_message": final_message_matches_jsonl,
            "representation_warning": (
                "RESULT_REPRESENTATION_NORMALIZED"
                if result_representation_normalized
                else ""
            ),
            "jsonl_recovery": recovery,
        }
        settlement = final_message.get("settlement")
        settlement = settlement if isinstance(settlement, Mapping) else {}
        result_blocker_code = ""
        if settlement.get("blocker_code") == "SIDECAR_ATTEMPT_IDENTITY_MISMATCH":
            result_blocker_code = "SIDECAR_ATTEMPT_IDENTITY_MISMATCH"
        elif "final_result_schema_invalid" in integrity_reasons:
            result_blocker_code = "FINAL_RESULT_SCHEMA_INVALID"
        elif final_message.get("present") is not True and not (
            jsonl_only_result and final_message_matches_jsonl
        ):
            result_blocker_code = "FINAL_AGENT_MESSAGE_UNAVAILABLE"
        elif not final_message_matches_jsonl and exit_code == 0 and terminal_success:
            result_blocker_code = "FINAL_RESULT_SEMANTIC_MISMATCH"
        state = _terminal_state(
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            integrity_blocked=integrity_blocked,
            terminal_success=terminal_success,
            terminal_failure=terminal_failure,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
        sequence += 1
        final_state = _snapshot_state(
            handle,
            ticket,
            state=state,
            sequence=sequence,
            sidecar_identity=sidecar_identity,
            child_process_id=process.pid,
            child_start_identity=child_start_identity,
            stdout=stdout,
            stderr=stderr,
            stdin=stdin,
            started_at=started_at,
        )
        _atomic_replace_json(handle.phase_directory / "state.json", final_state)
        receipt = _terminal_receipt(
            handle,
            ticket,
            state=state,
            exit_code=exit_code,
            terminal_reason=terminal_reason,
            sidecar_identity=sidecar_identity,
            child_process_id=process.pid,
            child_start_identity=child_start_identity,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            stdout_stat=stdout_stat,
            stderr_stat=stderr_stat,
            started_at=started_at,
            started_monotonic=started_monotonic,
            process_exited_at=process_exited_at,
            process_exit_elapsed_ms=process_exit_elapsed_ms,
            heartbeat_sequence=sequence,
            stdout_jsonl=stdout_jsonl,
            final_message=final_message,
            final_message_absence=final_message_absence,
            outcome_facts={
                "process_exit_known": exit_code is not None,
                "timed_out": timed_out,
                "cancelled": cancelled,
                "integrity_blocked": integrity_blocked,
                "integrity_reasons": sorted(set(integrity_reasons)),
                "terminal_success": terminal_success,
                "terminal_failure": terminal_failure,
                "terminal_contradiction": terminal_contradiction,
                "streams_settled": streams_settled,
                "final_result_capture_mode": (
                    "jsonl_only" if jsonl_only_result else "sidecar_required"
                ),
                "final_sidecar_valid": final_message.get("present") is True,
                "final_sidecar_matches_jsonl": bool(
                    not jsonl_only_result and final_message_matches_jsonl
                ),
                "final_jsonl_result_valid": bool(
                    jsonl_only_result
                    and final_message_matches_jsonl
                    and recovery.get("eligible_candidate") is True
                ),
                "final_jsonl_message_observed": bool(
                    jsonl_only_result and final_message_matches_jsonl
                ),
                "jsonl_recovery_candidate": recovery.get("eligible_candidate")
                is True,
                "result_representation_normalized": result_representation_normalized,
                "warnings": (
                    ["RESULT_REPRESENTATION_NORMALIZED"]
                    if result_representation_normalized
                    else []
                ),
                "result_blocker_code": result_blocker_code,
            },
        )
        try:
            _create_immutable_json(handle.phase_directory / "terminal.json", receipt)
        except CodexExecBridgeError as exc:
            if exc.code != "IMMUTABLE_FILE_EXISTS":
                raise
            existing = load_terminal_receipt(handle)
            if existing != receipt:
                raise CodexExecBridgeError("TERMINAL_RECEIPT_CONFLICT", "A conflicting terminal receipt already exists.")
            return existing
        return receipt
    finally:
        try:
            fcntl.flock(lease_fd, fcntl.LOCK_UN)
        finally:
            os.close(lease_fd)


def _load_launch(handle: ExecutionHandle) -> LaunchInfo | None:
    path = handle.phase_directory / "launch.json"
    if not path.exists() and not path.is_symlink():
        return None
    value, _ = _read_protected_json(path)
    if (
        value.get("schema") != LAUNCH_SCHEMA
        or value.get("policy") != BRIDGE_POLICY
        or value.get("ticket_digest") != handle.ticket_digest
        or type(value.get("process_id")) is not int
        or int(value.get("process_id") or 0) <= 0
        or not isinstance(value.get("process_start_identity"), str)
        or not _SHA256.fullmatch(str(value.get("process_start_identity") or ""))
        or not isinstance(value.get("launched_at"), str)
        or not str(value.get("launched_at") or "")
        or len(str(value.get("launched_at") or "")) > 80
    ):
        raise CodexExecBridgeError("LAUNCH_RECORD_INVALID", "The detached launch record is invalid.")
    return LaunchInfo(
        process_id=int(value["process_id"]),
        process_start_identity=str(value["process_start_identity"]),
        ticket_digest=handle.ticket_digest,
        launched_at=str(value["launched_at"]),
    )


def load_launch_info(handle: ExecutionHandle) -> LaunchInfo | None:
    """Load one sealed launch binding without inferring current liveness."""
    _load_ticket_and_seal(handle)
    return _load_launch(handle)


def launch_sidecar(
    handle: ExecutionHandle,
    *,
    python_executable: str | os.PathLike[str] = sys.executable,
    child_environment: Mapping[str, str] | None = None,
) -> LaunchInfo:
    _load_ticket_and_seal(handle)
    existing_terminal = load_terminal_receipt(handle)
    existing_launch = _load_launch(handle)
    if existing_terminal is not None:
        if existing_launch is None:
            raise CodexExecBridgeError("LAUNCH_RECORD_MISSING", "A terminal phase has no detached launch record.")
        return existing_launch
    if existing_launch is not None:
        if process_identity_matches(existing_launch.process_id, existing_launch.process_start_identity):
            return existing_launch
        raise CodexExecBridgeError("SIDECAR_PROCESS_LOST", "The prior detached sidecar is no longer alive.")

    python_path = Path(python_executable).resolve(strict=True)
    if not python_path.is_absolute() or not python_path.is_file():
        raise CodexExecBridgeError("SIDECAR_EXECUTABLE_INVALID", "The sidecar Python executable is invalid.")
    module_root = Path(__file__).resolve().parent.parent
    ticket = _load_ticket_and_seal(handle)
    environment = _validated_detached_environment(ticket, child_environment)
    environment["PYTHONPATH"] = str(module_root)
    process = subprocess.Popen(
        [str(python_path), "-m", "twos_runtime.codex_exec_bridge", "--ticket", str(handle.ticket_path)],
        cwd=str(handle.spool_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        start_new_session=True,
        close_fds=True,
    )
    start_identity = capture_process_start_identity(process.pid)
    if not start_identity:
        if not _terminate_unbound_sidecar(process):
            raise CodexExecBridgeError(
                "SIDECAR_CLEANUP_FAILED",
                "The unpublished detached sidecar could not be stopped safely.",
            )
        raise CodexExecBridgeError("SIDECAR_IDENTITY_UNAVAILABLE", "The detached sidecar identity could not be verified.")
    value = {
        "schema": LAUNCH_SCHEMA,
        "policy": BRIDGE_POLICY,
        "ticket_digest": handle.ticket_digest,
        "process_id": process.pid,
        "process_start_identity": start_identity,
        "launched_at": _utc_now(),
    }
    try:
        _create_immutable_json(handle.phase_directory / "launch.json", value)
    except (CodexExecBridgeError, OSError) as exc:
        if not _terminate_exact_process(process, start_identity):
            raise CodexExecBridgeError(
                "SIDECAR_CLEANUP_FAILED",
                "The unpublished detached sidecar could not be stopped safely.",
            ) from exc
        if isinstance(exc, CodexExecBridgeError) and exc.code == "IMMUTABLE_FILE_EXISTS":
            existing_launch = load_launch_info(handle)
            if existing_launch is None:
                raise CodexExecBridgeError(
                    "LAUNCH_RECORD_PUBLISH_FAILED",
                    "The detached launch record could not be published safely.",
                ) from exc
            return existing_launch
        raise CodexExecBridgeError(
            "LAUNCH_RECORD_PUBLISH_FAILED",
            "The detached launch record could not be published safely.",
        ) from exc
    return LaunchInfo(process.pid, start_identity, handle.ticket_digest, str(value["launched_at"]))


def _await_own_launch_record(
    handle: ExecutionHandle,
    shutdown_event: threading.Event,
) -> LaunchInfo:
    process_id = os.getpid()
    start_identity = capture_process_start_identity(process_id)
    if not start_identity:
        raise CodexExecBridgeError(
            "SIDECAR_IDENTITY_UNAVAILABLE",
            "The detached sidecar identity could not be verified.",
        )
    deadline = time.monotonic() + SIDECAR_LAUNCH_RECORD_WAIT_SECONDS
    while time.monotonic() < deadline:
        if shutdown_event.is_set():
            raise CodexExecBridgeError(
                "SIDECAR_LAUNCH_ABORTED",
                "The detached sidecar launch was aborted before publication.",
            )
        launch = load_launch_info(handle)
        if launch is None:
            time.sleep(0.01)
            continue
        if (
            launch.process_id != process_id
            or launch.process_start_identity != start_identity
        ):
            raise CodexExecBridgeError(
                "SIDECAR_LAUNCH_BINDING_MISMATCH",
                "The detached launch record belongs to a different process.",
            )
        return launch
    raise CodexExecBridgeError(
        "SIDECAR_LAUNCH_RECORD_UNAVAILABLE",
        "The detached launch record was not published in time.",
    )


def load_stream_bytes(
    handle: ExecutionHandle,
    *,
    stream: str = "stdout",
) -> bytes:
    if stream not in {"stdout", "stderr"}:
        raise CodexExecBridgeError("STREAM_INVALID", "Only stdout or stderr may be loaded.")
    receipt = load_terminal_receipt(handle)
    if receipt is None:
        raise CodexExecBridgeError("RESULT_NOT_TERMINAL", "The execution has no terminal receipt.")
    binding = receipt.get(stream)
    if not isinstance(binding, dict) or binding.get("relative_path") != f"{stream}.bin":
        raise CodexExecBridgeError("STREAM_BINDING_INVALID", "The protected stream binding is invalid.")
    payload, observed = _read_protected_bytes(
        handle.phase_directory / f"{stream}.bin",
        maximum=MAX_OUTPUT_LIMIT_BYTES,
    )
    if (
        binding.get("device") != observed.st_dev
        or binding.get("inode") != observed.st_ino
        or binding.get("retained_bytes") != len(payload)
        or binding.get("retained_sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise CodexExecBridgeError("STREAM_REPLACED", "The protected stream failed its receipt integrity check.")
    return payload


def load_final_message(handle: ExecutionHandle) -> str | None:
    receipt = load_terminal_receipt(handle)
    if receipt is None:
        raise CodexExecBridgeError("RESULT_NOT_TERMINAL", "The execution has no terminal receipt.")
    binding = receipt.get("final_message")
    if not isinstance(binding, dict):
        raise CodexExecBridgeError("FINAL_MESSAGE_BINDING_INVALID", "The final-message receipt binding is invalid.")
    if binding.get("present") is not True:
        return None
    ticket = _load_ticket_and_seal(handle)
    ticket_binding = ticket.get("final_message")
    if not isinstance(ticket_binding, dict) or (
        binding.get("relative_path") != ticket_binding.get("relative_path")
        or binding.get("maximum_bytes") != ticket_binding.get("maximum_bytes")
    ):
        raise CodexExecBridgeError("FINAL_MESSAGE_BINDING_INVALID", "The final-message receipt changed its ticket binding.")
    expected_binding_identity = _final_message_binding_identity(handle, ticket)
    if (
        binding.get("ticket_binding_identity") is not None
        and binding.get("ticket_binding_identity") != expected_binding_identity
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_BINDING_INVALID",
            "The final-message receipt changed its ticket identity.",
        )
    maximum = int(binding["maximum_bytes"])
    payload, observed = _read_protected_bytes(
        handle.phase_directory / str(binding["relative_path"]),
        maximum=maximum,
    )
    if (
        binding.get("device") != observed.st_dev
        or binding.get("inode") != observed.st_ino
        or binding.get("size") != len(payload)
        or binding.get("sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise CodexExecBridgeError("FINAL_MESSAGE_REPLACED", "The final message failed its receipt integrity check.")
    try:
        message = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodexExecBridgeError("FINAL_MESSAGE_INVALID", "The final message is not UTF-8 text.") from exc
    if "\x00" in message:
        raise CodexExecBridgeError("FINAL_MESSAGE_INVALID", "The final message contains invalid text.")
    normalized = (
        _normalize_result_text(message).encode("utf-8")
        if binding.get("canonical_size") is not None
        else message.strip().encode("utf-8")
    )
    if (
        binding.get("normalized_size") != len(normalized)
        or binding.get("normalized_sha256")
        != hashlib.sha256(normalized).hexdigest()
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_REPLACED",
            "The final message failed its normalized receipt binding.",
        )
    canonical, canonicalization, schema_status = _canonical_result_text(
        message,
        phase=str(ticket.get("phase") or ""),
    )
    if (
        binding.get("canonical_size") is not None
        and (
            binding.get("canonical_size") != len(canonical)
            or binding.get("canonical_sha256")
            != hashlib.sha256(canonical).hexdigest()
            or binding.get("canonicalization") != canonicalization
            or binding.get("schema_status") != schema_status
        )
    ):
        raise CodexExecBridgeError(
            "FINAL_MESSAGE_REPLACED",
            "The final message failed its canonical receipt binding.",
        )
    return message


def _load_terminal_event(
    handle: ExecutionHandle,
    stdout_jsonl: Mapping[str, object],
) -> bytes | None:
    binding = stdout_jsonl.get("terminal_event")
    if binding is None:
        return None
    if not isinstance(binding, dict) or binding.get("relative_path") != "stdout-terminal-event.jsonl":
        raise CodexExecBridgeError("TERMINAL_EVENT_BINDING_INVALID", "The terminal JSONL event binding is invalid.")
    payload, observed = _read_protected_bytes(
        handle.phase_directory / "stdout-terminal-event.jsonl",
        maximum=MAX_JSONL_LINE_BYTES + 1,
    )
    if (
        binding.get("device") != observed.st_dev
        or binding.get("inode") != observed.st_ino
        or binding.get("size") != len(payload)
        or binding.get("sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise CodexExecBridgeError("TERMINAL_EVENT_REPLACED", "The terminal JSONL event failed its receipt integrity check.")
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexExecBridgeError("TERMINAL_EVENT_INVALID", "The terminal JSONL event is malformed.") from exc
    event_type = event.get("type") if isinstance(event, dict) else None
    if (
        event_type not in _TERMINAL_CODEX_JSONL_EVENTS
        or event_type != stdout_jsonl.get("last_terminal_event_type")
    ):
        raise CodexExecBridgeError("TERMINAL_EVENT_INVALID", "The saved JSONL event is not terminal evidence.")
    return payload


def _load_agent_message_event(
    handle: ExecutionHandle,
    stdout_jsonl: Mapping[str, object],
) -> bytes | None:
    binding = stdout_jsonl.get("agent_message_event")
    if binding is None:
        return None
    if (
        not isinstance(binding, dict)
        or binding.get("relative_path") != "stdout-agent-message-event.jsonl"
    ):
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_BINDING_INVALID",
            "The final agent-message JSONL binding is invalid.",
        )
    payload, observed = _read_protected_bytes(
        handle.phase_directory / "stdout-agent-message-event.jsonl",
        maximum=MAX_JSONL_LINE_BYTES + 1,
    )
    if (
        binding.get("device") != observed.st_dev
        or binding.get("inode") != observed.st_ino
        or binding.get("size") != len(payload)
        or binding.get("sha256") != hashlib.sha256(payload).hexdigest()
    ):
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_REPLACED",
            "The final agent-message JSONL event failed its receipt integrity check.",
        )
    for binding_key, summary_key in (
        ("stream_sequence", "last_agent_message_event_sequence"),
        ("turn_identity", "last_agent_message_turn_identity"),
        ("selection", "last_agent_message_selection"),
        ("canonicalization", "last_agent_message_canonicalization"),
        ("schema_status", "last_agent_message_schema_status"),
        ("canonical_size", "last_agent_message_bytes"),
        ("canonical_sha256", "last_agent_message_sha256"),
        ("source_text_size", "last_agent_message_source_bytes"),
        ("source_text_sha256", "last_agent_message_source_sha256"),
    ):
        if (
            binding.get(binding_key) is not None
            and binding.get(binding_key) != stdout_jsonl.get(summary_key)
        ):
            raise CodexExecBridgeError(
                "AGENT_MESSAGE_EVENT_BINDING_INVALID",
                "The selected final agent-message binding is inconsistent.",
            )
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_INVALID",
            "The saved final agent-message JSONL event is malformed.",
        ) from exc
    if not isinstance(event, dict):
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_INVALID",
            "The saved final agent-message JSONL event must be an object.",
        )
    item = event.get("item")
    text = item.get("text") if isinstance(item, dict) else None
    if (
        event.get("type") != "item.completed"
        or not isinstance(item, dict)
        or item.get("type") != "agent_message"
        or not isinstance(text, str)
    ):
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_INVALID",
            "The saved JSONL event is not final agent-message evidence.",
        )
    ticket = _load_ticket_and_seal(handle)
    normalized, canonicalization, schema_status = _canonical_result_text(
        text,
        phase=str(ticket.get("phase") or ""),
    )
    if (
        stdout_jsonl.get("last_agent_message_bytes") != len(normalized)
        or stdout_jsonl.get("last_agent_message_sha256")
        != hashlib.sha256(normalized).hexdigest()
        or (
            stdout_jsonl.get("last_agent_message_canonicalization") is not None
            and stdout_jsonl.get("last_agent_message_canonicalization")
            != canonicalization
        )
        or (
            stdout_jsonl.get("last_agent_message_schema_status") is not None
            and stdout_jsonl.get("last_agent_message_schema_status")
            != schema_status
        )
    ):
        raise CodexExecBridgeError(
            "AGENT_MESSAGE_EVENT_INVALID",
            "The saved final agent-message does not match its stream evidence.",
        )
    return payload


def load_jsonl_final_message_candidate(handle: ExecutionHandle) -> str | None:
    """Load a transport-bound recovery candidate for higher-layer validation.

    The bridge deliberately does not declare this content a successful result:
    its structured schema and Run identity still must be validated by the
    result-intake layer.
    """
    receipt = load_terminal_receipt(handle)
    if receipt is None:
        raise CodexExecBridgeError(
            "RESULT_NOT_TERMINAL", "The execution has no terminal receipt."
        )
    final_message = receipt.get("final_message")
    stdout_jsonl = receipt.get("stdout_jsonl")
    outcome_facts = receipt.get("outcome_facts")
    if (
        not isinstance(final_message, dict)
        or not isinstance(stdout_jsonl, dict)
        or not isinstance(outcome_facts, dict)
    ):
        raise CodexExecBridgeError(
            "JSONL_RECOVERY_BINDING_INVALID",
            "The JSONL recovery receipt binding is invalid.",
        )
    recovery = final_message.get("jsonl_recovery")
    if not isinstance(recovery, dict) or recovery.get("eligible_candidate") is not True:
        return None
    if (
        outcome_facts.get("process_exit_known") is not True
        or outcome_facts.get("terminal_success") is not True
        or outcome_facts.get("streams_settled") is not True
    ):
        raise CodexExecBridgeError(
            "JSONL_RECOVERY_BINDING_INVALID",
            "The JSONL recovery candidate lacks settled terminal evidence.",
        )
    payload = _load_agent_message_event(handle, stdout_jsonl)
    if payload is None:
        raise CodexExecBridgeError(
            "JSONL_RECOVERY_BINDING_INVALID",
            "The JSONL recovery candidate is unavailable.",
        )
    event = json.loads(payload.decode("utf-8"))
    item = event.get("item") if isinstance(event, dict) else None
    message = item.get("text") if isinstance(item, dict) else None
    if not isinstance(message, str):
        raise CodexExecBridgeError(
            "JSONL_RECOVERY_BINDING_INVALID",
            "The JSONL recovery candidate is invalid.",
        )
    ticket = _load_ticket_and_seal(handle)
    normalized, _, schema_status = _canonical_result_text(
        message,
        phase=str(ticket.get("phase") or ""),
    )
    if (
        recovery.get("message_size") != len(normalized)
        or recovery.get("message_sha256")
        != hashlib.sha256(normalized).hexdigest()
        or recovery.get("selected_schema_status") != schema_status
        or schema_status != "VALID"
    ):
        raise CodexExecBridgeError(
            "JSONL_RECOVERY_BINDING_INVALID",
            "The JSONL recovery candidate failed its receipt digest.",
        )
    return message


def replay_stdout_to_collector(
    handle: ExecutionHandle,
    collector: CollectorProtocol,
    *,
    chunk_size: int = 8192,
) -> ReplayResult:
    if type(chunk_size) is not int or not 1 <= chunk_size <= 64 * 1024:
        raise CodexExecBridgeError("REPLAY_CHUNK_INVALID", "The replay chunk size is invalid.")
    receipt = load_terminal_receipt(handle)
    if receipt is None:
        raise CodexExecBridgeError("RESULT_NOT_TERMINAL", "The execution has no terminal receipt.")
    stdout_binding = receipt.get("stdout")
    stdout_jsonl = receipt.get("stdout_jsonl")
    if not isinstance(stdout_binding, dict) or stdout_binding.get("relative_path") != "stdout.bin":
        raise CodexExecBridgeError("STDOUT_BINDING_INVALID", "The stdout capture binding is invalid.")
    if not isinstance(stdout_jsonl, dict):
        raise CodexExecBridgeError("STDOUT_JSONL_BINDING_INVALID", "The stdout JSONL evidence binding is invalid.")
    retained_payload = load_stream_bytes(handle, stream="stdout")
    truncated = stdout_binding.get("truncated") is True
    terminal_within_prefix = stdout_jsonl.get("terminal_event_within_retained_prefix") is True
    agent_message_within_prefix = (
        stdout_jsonl.get("agent_message_event_within_retained_prefix") is True
    )
    terminal_event = _load_terminal_event(handle, stdout_jsonl)
    agent_message_event = _load_agent_message_event(handle, stdout_jsonl)
    replay_payload = retained_payload
    dropped_partial_bytes = 0
    if truncated:
        final_newline = replay_payload.rfind(b"\n")
        complete_length = final_newline + 1 if final_newline >= 0 else 0
        dropped_partial_bytes = len(replay_payload) - complete_length
        replay_payload = replay_payload[:complete_length]
    replayed = 0
    agent_message_event_replayed = False
    terminal_event_replayed = False
    collection_incomplete = False
    try:
        for offset in range(0, len(replay_payload), chunk_size):
            chunk = replay_payload[offset : offset + chunk_size]
            collector.feed(chunk)
            replayed += len(chunk)
        agent_message_event_replayed = bool(
            truncated
            and not agent_message_within_prefix
            and agent_message_event is not None
        )
        if agent_message_event_replayed and agent_message_event is not None:
            collector.feed(agent_message_event)
            replayed += len(agent_message_event)
        terminal_event_replayed = bool(
            truncated and not terminal_within_prefix and terminal_event is not None
        )
        if terminal_event_replayed and terminal_event is not None:
            collector.feed(terminal_event)
            replayed += len(terminal_event)
        successful_process = receipt.get("process_exit_code") == 0
        terminal_truth = stdout_jsonl.get("terminal_truth")
        terminal_truth_resolved = bool(
            isinstance(terminal_truth, dict)
            and terminal_truth.get("contradiction") is not True
            and (
                terminal_truth.get("success") is True
                or terminal_truth.get("failure") is True
            )
        )
        classifier_complete = bool(
            stdout_jsonl.get("malformed_count") == 0
            and stdout_jsonl.get("eof_received") is True
            and stdout_jsonl.get("trailing_partial_line_resolved") is True
            and (
                not successful_process
                or (
                    stdout_jsonl.get("agent_message_count", 0) >= 1
                    and agent_message_event is not None
                )
            )
            and stdout_jsonl.get("terminal_event_count") == 1
            and terminal_event is not None
            and terminal_truth_resolved
        )
        if stdout_binding.get("failed") is True or not classifier_complete:
            collector.mark_incomplete()
            collection_incomplete = True
        collector.finish()
    except Exception:
        collection_incomplete = True
        try:
            collector.mark_incomplete()
            collector.finish()
        except Exception:
            pass
    observed_bytes = int(stdout_binding.get("observed_bytes") or 0)
    return ReplayResult(
        bytes_replayed=replayed,
        stdout_truncated=truncated,
        agent_message_event_replayed=agent_message_event_replayed,
        terminal_event_replayed=terminal_event_replayed,
        collection_incomplete=collection_incomplete,
        omitted_stdout_bytes=max(0, observed_bytes - len(retained_payload)) + dropped_partial_bytes,
        terminal_state=str(receipt.get("terminal_state") or ""),
        ticket_digest=handle.ticket_digest,
    )


def _command_line(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="twos-codex-exec-bridge")
    parser.add_argument("--ticket", required=True)
    options = parser.parse_args(argv)
    handle = handle_from_ticket_path(options.ticket)
    shutdown_event = threading.Event()

    def request_shutdown(_signum, _frame) -> None:
        shutdown_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    _await_own_launch_record(handle, shutdown_event)
    receipt = run_execution(handle, shutdown_event=shutdown_event)
    return 0 if receipt.get("terminal_state") == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(_command_line())
