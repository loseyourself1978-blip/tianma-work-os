from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .models import (
    AIModel,
    AIModelAvailabilityEvidence,
    CodexConnectivityEvidence,
    utc_now,
)
from .codex_protocol_0144 import (
    EXPERIMENTAL_SERVER_REQUEST_METHODS,
    KNOWN_SERVER_REQUEST_METHODS,
    MessageKind,
    STABLE_JSON_SCHEMA_BUNDLE_SHA256,
    STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
    STABLE_SERVER_REQUEST_SCHEMA_SHA256,
    classify_jsonrpc_message,
    classify_notification_method,
    payload_shape_summary,
    schema_version_matches,
)
from .result_intake import canonical_sha256, sanitize_result_value


CONNECTIVITY_POLICY = "twos.codex_connectivity.vol18.005.codex_exec_jsonl.r2"
CONNECTIVITY_STATES = frozenset(
    {
        "CLI_NOT_INSTALLED",
        "AUTHENTICATION_REQUIRED",
        "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED",
        "PROVIDER_UNREACHABLE",
        "MODEL_UNAVAILABLE",
        "READY_FOR_REAL_RUN",
        "BLOCKED",
    }
)
AUTHENTICATION_STATES = frozenset(
    {
        "CHATGPT_LOGIN_AUTHENTICATED",
        "API_KEY_AUTHENTICATED",
        "AUTHENTICATION_REQUIRED",
        "CREDENTIAL_STORE_UNAVAILABLE",
        "AUTHENTICATION_UNKNOWN",
    }
)
CONNECTIVITY_PROBE_TIMEOUT_SECONDS = 180
CONNECTIVITY_PROBE_MAX_TIMEOUT_SECONDS = 600
CONNECTIVITY_OUTPUT_LIMIT = 128_000
CONNECTIVITY_FRAME_LIMIT = 64_000
CONNECTIVITY_MESSAGE_LIMIT = 1_000
CONNECTIVITY_PROMPT = (
    "TWOS connectivity verification only. Do not read or write files, invoke tools, "
    "or modify source. Reply with exactly this JSON object and no other fields: "
    '{"status":"TWOS_CODEX_CONNECTION_OK"}'
)
CONNECTIVITY_RESPONSE_MARKER = "TWOS_CODEX_CONNECTION_OK"
CONNECTIVITY_RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "const": CONNECTIVITY_RESPONSE_MARKER},
    },
    "required": ["status"],
}
CONNECTIVITY_MODEL_PROVIDER = "openai"
_SAFE_MODEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
_RUNTIME_ID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_CREDENTIAL_STORE_FAILURE = re.compile(
    r"(?:keychain|keyring|credential(?: store)?).{0,80}(?:unavailable|denied|locked|failed|error)|"
    r"(?:permission denied).{0,80}(?:credential|keychain|keyring)",
    re.IGNORECASE | re.DOTALL,
)
_AUTH_REQUIRED = re.compile(
    r"(?:not logged in|login required|authentication required|please (?:run )?login|unauthorized)",
    re.IGNORECASE,
)
_MODEL_UNAVAILABLE = re.compile(
    r"(?:model.{0,80}(?:not found|not available|unavailable|unsupported|unknown|denied)|"
    r"invalid.{0,40}model|does not have access to model)",
    re.IGNORECASE | re.DOTALL,
)
_PROVIDER_UNREACHABLE = re.compile(
    r"(?:connection (?:failed|refused|reset)|network (?:error|unreachable)|"
    r"timed? out|dns|name resolution|could not connect|failed to connect|proxy error|"
    r"service unavailable|temporarily unavailable)",
    re.IGNORECASE,
)
_INTERACTIVE_PROMPT = re.compile(
    r"(?:press enter|open (?:this )?url|visit .{0,80}(?:login|authorize)|"
    r"waiting for (?:browser|authentication|oauth)|enter (?:the )?(?:code|api key)|"
    r"select (?:an )?account)",
    re.IGNORECASE,
)
_SAFE_ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


@dataclass(frozen=True)
class AuthenticationDiagnostic:
    state: str
    method: str
    credential_store: str
    credential_store_accessible: bool
    safe_summary: str


def classify_direct_exec_gate_zero(
    normal: bool,
    detached: bool,
) -> dict[str, object]:
    """Classify the two bounded direct-exec controls without starting either one."""
    if type(normal) is not bool or type(detached) is not bool:
        raise TypeError("Gate Zero control results must be booleans.")
    if normal and detached:
        blocker_code: str | None = None
    elif normal:
        blocker_code = "DETACHED_ENVIRONMENT_MISMATCH"
    elif detached:
        blocker_code = "CONTROL_ENVIRONMENT_INVALID"
    else:
        blocker_code = "DIRECT_CODEX_PROVIDER_PATH_FAILED"
    return {
        "normal_passed": normal,
        "detached_passed": detached,
        "can_continue": blocker_code is None,
        "blocker_code": blocker_code,
    }


def safe_environment_shape_comparison(
    normal_keys: set[str] | frozenset[str] | list[str] | tuple[str, ...],
    detached_keys: set[str] | frozenset[str] | list[str] | tuple[str, ...],
) -> dict[str, object]:
    """Compare environment key presence only; values are neither accepted nor returned."""

    def normalize(value: object) -> frozenset[str]:
        if not isinstance(value, (set, frozenset, list, tuple)):
            raise TypeError("Environment shape comparison accepts key collections only.")
        if len(value) > 256:
            raise ValueError("Environment key collection is oversized.")
        keys = frozenset(value)
        if len(keys) != len(value) or any(
            not isinstance(key, str) or not _SAFE_ENVIRONMENT_KEY.fullmatch(key)
            for key in keys
        ):
            raise ValueError("Environment key collection is malformed.")
        return keys

    normal = normalize(normal_keys)
    detached = normalize(detached_keys)
    all_keys = sorted(normal | detached)
    presence = [
        {
            "key": key,
            "normal_present": key in normal,
            "detached_present": key in detached,
            "different": (key in normal) != (key in detached),
        }
        for key in all_keys
    ]
    return {
        "matches": normal == detached,
        "presence": presence,
        "normal_only": sorted(normal - detached),
        "detached_only": sorted(detached - normal),
    }


def codex_child_environment() -> dict[str, str]:
    """Match the real Run's allowlisted detached child environment exactly."""
    allowlist = (
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
        # Authentication is inherited only by the real Codex child and is
        # never serialized into evidence, diagnostics, logs, or API output.
        "OPENAI_API_KEY",
        "CODEX_ACCESS_TOKEN",
        # Preserve the detached runtime's network and trust context.
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
    )
    environment = {key: os.environ[key] for key in allowlist if key in os.environ}
    environment["NO_COLOR"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_ALLOW_PROTOCOL"] = ""
    return environment


def _file_content_identity(path: Path) -> str:
    try:
        path = path.resolve(strict=True)
        if not path.is_file():
            return ""
        stat = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    payload = (
        f"{path}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}:"
        f"{stat.st_mtime_ns}:{stat.st_mode}:{digest.hexdigest()}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _native_codex_executable_identities(launcher: Path) -> tuple[str, ...]:
    """Hash npm-packaged native Codex children without persisting their paths."""
    if launcher.name != "codex.js" or launcher.parent.name != "bin":
        return ()
    package_root = launcher.parent.parent
    scopes = (
        package_root / "node_modules" / "@openai",
        package_root.parent,
    )
    identities: set[str] = set()
    for scope in scopes:
        if not scope.is_dir():
            continue
        for candidate in sorted(scope.glob("codex-*/vendor/*/bin/codex*"))[:16]:
            identity = _file_content_identity(candidate)
            if identity:
                identities.add(identity)
    return tuple(sorted(identities))


def _reported_cli_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            timeout=10,
            env=codex_child_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    lines = (result.stdout or result.stderr).decode(
        "utf-8", errors="replace"
    ).strip().splitlines()
    return lines[0][:240] if lines else ""


def executable_identity(
    executable: str | None,
    *,
    cli_version: str | None = None,
) -> str:
    if not executable:
        return ""
    try:
        launcher = Path(executable).resolve(strict=True)
    except OSError:
        return ""
    launcher_identity = _file_content_identity(launcher)
    if not launcher_identity:
        return ""
    reported_version = (
        str(cli_version).strip()[:240]
        if cli_version is not None
        else _reported_cli_version(launcher)
    )
    payload = {
        "launcher_identity": launcher_identity,
        "native_executable_identities": _native_codex_executable_identities(launcher),
        "cli_version_identity": hashlib.sha256(
            reported_version.encode("utf-8")
        ).hexdigest(),
    }
    return canonical_sha256(payload)


def execution_context_identity(environment: dict[str, str] | None = None) -> str:
    environment = environment or codex_child_environment()
    # Hash values that affect credential lookup; persist neither values nor raw paths.
    configured_home = environment.get("CODEX_HOME")
    default_home = environment.get("HOME")
    auth_file = (
        Path(configured_home) / "auth.json"
        if configured_home
        else Path(default_home) / ".codex" / "auth.json"
        if default_home
        else None
    )
    auth_store_identity = ""
    if auth_file is not None:
        try:
            stat = auth_file.stat()
            content_digest = hashlib.sha256()
            with auth_file.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    content_digest.update(chunk)
            auth_store_identity = hashlib.sha256(
                (
                    f"{auth_file}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}:"
                    f"{stat.st_mtime_ns}:{stat.st_mode}:{content_digest.hexdigest()}"
                ).encode()
            ).hexdigest()
        except OSError:
            pass
    identity = {
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "keys": sorted(environment),
        "home": hashlib.sha256(environment.get("HOME", "").encode()).hexdigest(),
        "codex_home": hashlib.sha256(environment.get("CODEX_HOME", "").encode()).hexdigest(),
        "path": hashlib.sha256(environment.get("PATH", "").encode()).hexdigest(),
        "credential_store_identity": auth_store_identity,
        "auth_variables_present": sorted(
            key for key in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN") if key in environment
        ),
        "auth_variable_fingerprints": {
            key: hashlib.sha256(environment[key].encode()).hexdigest()
            for key in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN")
            if key in environment
        },
        "network_variables": {
            key: hashlib.sha256(environment[key].encode()).hexdigest()
            for key in (
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
            )
            if key in environment
        },
    }
    return canonical_sha256(identity)


def _safe_output_summary(stdout: bytes, stderr: bytes) -> str:
    value = (stderr or stdout).decode("utf-8", errors="replace")[:4000]
    value = _RUNTIME_ID.sub("[runtime id redacted]", value)
    safe = sanitize_result_value(value)
    return str(safe or "").strip()[:1000]


def inspect_authentication(
    executable: str | None,
    *,
    environment: dict[str, str] | None = None,
    timeout_seconds: int = 10,
) -> AuthenticationDiagnostic:
    if not executable:
        return AuthenticationDiagnostic(
            "AUTHENTICATION_UNKNOWN", "unknown", "unknown", False,
            "Codex CLI is unavailable, so authentication could not be inspected.",
        )
    environment = environment or codex_child_environment()
    try:
        help_result = subprocess.run(
            [executable, "login", "--help"],
            capture_output=True,
            timeout=timeout_seconds,
            env=environment,
        )
        help_text = (help_result.stdout + help_result.stderr).decode("utf-8", errors="replace")
        if help_result.returncode != 0 or "status" not in help_text.casefold():
            return AuthenticationDiagnostic(
                "AUTHENTICATION_UNKNOWN", "unknown", "unknown", False,
                "The installed Codex CLI did not expose a supported read-only login status command.",
            )
        result = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return AuthenticationDiagnostic(
            "AUTHENTICATION_UNKNOWN", "unknown", "unknown", False,
            "Codex authentication status did not return within the bounded check.",
        )
    except OSError:
        return AuthenticationDiagnostic(
            "AUTHENTICATION_UNKNOWN", "unknown", "unknown", False,
            "Codex authentication status could not be executed in the detached runtime context.",
        )

    combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    lowered = combined.casefold()
    safe_summary = _safe_output_summary(result.stdout, result.stderr)
    if _CREDENTIAL_STORE_FAILURE.search(combined):
        return AuthenticationDiagnostic(
            "CREDENTIAL_STORE_UNAVAILABLE", "unknown", "unknown", False,
            safe_summary or "The Codex credential store is unavailable in the detached runtime context.",
        )
    if result.returncode != 0 or _AUTH_REQUIRED.search(combined):
        return AuthenticationDiagnostic(
            "AUTHENTICATION_REQUIRED", "none", "unknown", False,
            safe_summary or "Codex authentication is required.",
        )
    if "api key" in lowered:
        environment_sources = {
            key
            for key in ("OPENAI_API_KEY", "CODEX_ACCESS_TOKEN")
            if key in os.environ
        }
        source = "environment" if environment_sources else "unknown"
        accessible = source != "environment" or environment_sources.issubset(environment)
        return AuthenticationDiagnostic(
            "API_KEY_AUTHENTICATED",
            "API key",
            source,
            accessible,
            "Codex reports API-key authentication; the key value is withheld.",
        )
    if "logged in" in lowered or "chatgpt" in lowered or "authenticated" in lowered:
        configured_home = environment.get("CODEX_HOME")
        default_home = environment.get("HOME")
        auth_file = (
            Path(configured_home) / "auth.json"
            if configured_home
            else Path(default_home) / ".codex" / "auth.json"
            if default_home
            else None
        )
        store = (
            "keyring" if "keyring" in lowered
            else "keychain" if "keychain" in lowered
            else "file" if "file" in lowered
            else "file"
            if auth_file is not None and auth_file.is_file() and os.access(auth_file, os.R_OK)
            else "unknown"
        )
        return AuthenticationDiagnostic(
            "CHATGPT_LOGIN_AUTHENTICATED",
            "ChatGPT login",
            store,
            True,
            "Codex reports an authenticated ChatGPT login in the detached runtime context.",
        )
    return AuthenticationDiagnostic(
        "AUTHENTICATION_UNKNOWN", "unknown", "unknown", False,
        safe_summary or "Codex returned an unrecognized authentication status.",
    )


def latest_matching_connectivity(
    session: Session,
    *,
    owner_id: int,
    model: AIModel,
    executable: str | None,
    environment: dict[str, str] | None = None,
    cli_version: str | None = None,
) -> CodexConnectivityEvidence | None:
    return session.scalar(
        select(CodexConnectivityEvidence)
        .where(
            CodexConnectivityEvidence.owner_id == owner_id,
            CodexConnectivityEvidence.model_id == model.id,
            CodexConnectivityEvidence.configuration_identity == (model.stable_id or f"model-{model.id}"),
            CodexConnectivityEvidence.requested_model_identifier == model.provider_model_id,
            CodexConnectivityEvidence.executable_identity
            == executable_identity(executable, cli_version=cli_version),
            CodexConnectivityEvidence.execution_context_identity == execution_context_identity(environment),
        )
        .order_by(CodexConnectivityEvidence.id.desc())
    )


def connectivity_evidence_is_ready(evidence: CodexConnectivityEvidence | None) -> bool:
    diagnostics: dict[str, Any] = {}
    if evidence is not None:
        try:
            decoded = json.loads(evidence.diagnostic_json or "{}")
            diagnostics = decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            diagnostics = {}
    lifecycle = diagnostics.get("structured_lifecycle", {})
    return bool(
        evidence
        and evidence.readiness_state == "READY_FOR_REAL_RUN"
        and evidence.authentication_state
        in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"}
        and evidence.credential_store_accessible
        and evidence.provider_reachable
        and evidence.model_available
        and (
            not evidence.actual_model_identifier
            or evidence.actual_model_identifier == evidence.requested_model_identifier
        )
        and not evidence.interactive_prompt_detected
        and not evidence.timed_out
        and evidence.exit_code == 0
        and diagnostics.get("policy") == CONNECTIVITY_POLICY
        and diagnostics.get("transport") == "codex_exec_jsonl"
        and diagnostics.get("requested_model_argument_verified") is True
        and isinstance(lifecycle, dict)
        and lifecycle.get("thread_started") is True
        and lifecycle.get("turn_started") is True
        and lifecycle.get("turn_completed") is True
        and lifecycle.get("terminal_success") is True
        and lifecycle.get("response_ok") is True
        and lifecycle.get("malformed_jsonl") is False
        and lifecycle.get("lifecycle_conflict") is False
        and lifecycle.get("unexpected_action") is False
        and diagnostics.get("temporary_workspace_mutated") is False
    )


def connectivity_evidence_is_current(
    session: Session,
    *,
    owner_id: int,
    model: AIModel,
    evidence: CodexConnectivityEvidence | None,
) -> bool:
    """Reject saved probes superseded by a later registry/readiness downgrade."""
    if not connectivity_evidence_is_ready(evidence):
        return False
    provider = model.provider
    if not (
        model.configuration_status == "configured"
        and model.availability_status == "available"
        and model.invocation_mode == "real"
        and model.status in {"healthy", "degraded"}
        and provider.enabled
        and provider.status in {"healthy", "degraded"}
    ):
        return False
    latest_availability = session.scalar(
        select(AIModelAvailabilityEvidence)
        .where(
            AIModelAvailabilityEvidence.model_id == model.id,
            AIModelAvailabilityEvidence.checked_by_user_id == owner_id,
            AIModelAvailabilityEvidence.configuration_identity
            == (model.stable_id or f"model-{model.id}"),
        )
        .order_by(
            AIModelAvailabilityEvidence.checked_at.desc(),
            AIModelAvailabilityEvidence.id.desc(),
        )
    )
    return bool(
        latest_availability
        and latest_availability.result == "available"
        and latest_availability.adapter == "codex_cli"
        and latest_availability.invocation_mode == "real"
        and evidence is not None
        and evidence.requested_model_identifier == model.provider_model_id
        and (
            not evidence.actual_model_identifier
            or evidence.actual_model_identifier == model.provider_model_id
        )
    )


def connectivity_evidence_out(evidence: CodexConnectivityEvidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    diagnostics = json.loads(evidence.diagnostic_json or "{}")
    lifecycle = (
        diagnostics.get("structured_lifecycle", {})
        if isinstance(diagnostics, dict)
        else {}
    )
    model_identity_kind = (
        lifecycle.get("actual_model_source")
        if isinstance(lifecycle, dict)
        else None
    )
    protocol_blocker_codes = {
        "PROTOCOL_COMPATIBILITY_BLOCKED",
        "PROTOCOL_SCHEMA_VERSION_MISMATCH",
        "APP_SERVER_UNKNOWN_NOTIFICATION",
    }
    display_state = (
        "PROTOCOL_COMPATIBILITY_BLOCKED"
        if evidence.blocker_code in protocol_blocker_codes
        else evidence.readiness_state
    )
    next_action = (
        "Update or remediate the TWOS Codex protocol adapter, then explicitly verify the connection again."
        if display_state == "PROTOCOL_COMPATIBILITY_BLOCKED"
        else "Run native Codex login, then verify the connection again."
        if evidence.readiness_state == "AUTHENTICATION_REQUIRED"
        else "Select a supported model and explicitly verify the connection again."
        if evidence.readiness_state == "MODEL_UNAVAILABLE"
        else "Check local Provider access, then explicitly verify the connection again."
        if evidence.readiness_state == "PROVIDER_UNREACHABLE"
        else "Run Codex"
        if evidence.readiness_state == "READY_FOR_REAL_RUN"
        else "Review the blocker, then explicitly verify the connection again."
    )
    return {
        "evidence_id": evidence.evidence_id,
        "policy": CONNECTIVITY_POLICY,
        "readiness_state": display_state,
        "ready_for_real_run": connectivity_evidence_is_ready(evidence),
        "cli_installed": evidence.cli_installed,
        "cli_version": evidence.cli_version or None,
        "authentication": {
            "state": evidence.authentication_state,
            "authenticated": evidence.authentication_state
            in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"},
            "method": evidence.authentication_method,
            "credential_store": evidence.credential_store,
            "credential_store_accessible": evidence.credential_store_accessible,
            "next_action": (
                "Run native Codex login"
                if evidence.authentication_state == "AUTHENTICATION_REQUIRED"
                else "Restore Codex credential-store access"
                if evidence.authentication_state == "CREDENTIAL_STORE_UNAVAILABLE"
                else "No authentication action required"
            ),
            "native_login_command": (
                "codex login"
                if evidence.authentication_state == "AUTHENTICATION_REQUIRED"
                else None
            ),
        },
        "provider_reachable": evidence.provider_reachable,
        "requested_model": evidence.requested_model_identifier,
        "model_available": evidence.model_available,
        "resolved_model": evidence.actual_model_identifier or None,
        "model_identity_kind": model_identity_kind or None,
        # Compatibility alias for persisted Phase 18.5A evidence. The setup UI
        # presents this as Codex's same-turn effective model, not as independent
        # physical-provider attestation for a later Run.
        "actual_model": evidence.actual_model_identifier or None,
        "last_connectivity_check": evidence.checked_at.isoformat() + "Z",
        "duration_ms": evidence.duration_ms,
        "timed_out": evidence.timed_out,
        "interactive_prompt_detected": evidence.interactive_prompt_detected,
        "exit_code": evidence.exit_code,
        "blocker": evidence.safe_summary if evidence.blocker_code else None,
        "blocker_code": evidence.blocker_code or None,
        "safe_summary": evidence.safe_summary,
        "next_action": next_action,
        "advanced": {
            "sanitized_command": evidence.sanitized_command,
            "executable_identity": evidence.executable_identity,
            "execution_context_identity": evidence.execution_context_identity,
            "evidence_digest": evidence.evidence_digest,
            "diagnostics": diagnostics,
        },
    }


def connectivity_status(
    session: Session,
    *,
    owner_id: int,
    model: AIModel | None,
    detection: Any,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = environment or codex_child_environment()
    auth = inspect_authentication(detection.executable, environment=environment)
    latest = (
        latest_matching_connectivity(
            session,
            owner_id=owner_id,
            model=model,
            executable=detection.executable,
            environment=environment,
            cli_version=detection.version,
        )
        if model is not None
        else None
    )
    if not detection.found:
        state, blocker = "CLI_NOT_INSTALLED", detection.reason
    elif detection.status != "configured":
        state, blocker = "BLOCKED", detection.reason
    elif auth.state == "AUTHENTICATION_REQUIRED":
        state, blocker = "AUTHENTICATION_REQUIRED", auth.safe_summary
    elif auth.state == "CREDENTIAL_STORE_UNAVAILABLE":
        state, blocker = "BLOCKED", auth.safe_summary
    elif auth.state not in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"}:
        state, blocker = "BLOCKED", auth.safe_summary
    elif not auth.credential_store_accessible:
        state, blocker = "BLOCKED", "Detached TWOS cannot access the configured Codex credential source."
    elif connectivity_evidence_is_current(
        session,
        owner_id=owner_id,
        model=model,
        evidence=latest,
    ):
        return connectivity_evidence_out(latest) or {}
    elif latest is not None and latest.readiness_state != "READY_FOR_REAL_RUN":
        # A failed Owner-triggered probe is durable evidence too. Preserve its
        # exact provider/model blocker and timestamp across refreshes while the
        # live CLI/authentication prerequisites above still match. Only stale
        # READY evidence falls through to the explicit invalidation state.
        return connectivity_evidence_out(latest) or {}
    elif latest is not None:
        state, blocker = (
            "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED",
            "A later runtime readiness observation invalidated the saved connectivity result. Run Verify Codex Connection again.",
        )
    else:
        state, blocker = (
            "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED",
            "Authentication is confirmed, but an Owner must run Verify Codex Connection.",
        )
    return {
        "evidence_id": None,
        "policy": CONNECTIVITY_POLICY,
        "readiness_state": state,
        "ready_for_real_run": False,
        "cli_installed": bool(detection.found),
        "cli_version": detection.version,
        "authentication": {
            "state": auth.state,
            "authenticated": auth.state
            in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"},
            "method": auth.method,
            "credential_store": auth.credential_store,
            "credential_store_accessible": auth.credential_store_accessible,
            "next_action": (
                "Run native Codex login"
                if auth.state == "AUTHENTICATION_REQUIRED"
                else "Restore Codex credential-store access"
                if auth.state == "CREDENTIAL_STORE_UNAVAILABLE"
                else "No authentication action required"
            ),
            "native_login_command": (
                "codex login" if auth.state == "AUTHENTICATION_REQUIRED" else None
            ),
        },
        "provider_reachable": False,
        "requested_model": model.provider_model_id if model is not None else None,
        "model_available": False,
        "resolved_model": None,
        "model_identity_kind": None,
        "actual_model": None,
        "last_connectivity_check": None,
        "duration_ms": None,
        "timed_out": False,
        "interactive_prompt_detected": False,
        "exit_code": None,
        "blocker": blocker,
        "blocker_code": state,
        "safe_summary": blocker,
        "next_action": (
            "Run native Codex login, then explicitly verify the connection."
            if state == "AUTHENTICATION_REQUIRED"
            else "Select a supported model, then explicitly verify the connection."
        ),
        "advanced": {
            "sanitized_command": None,
            "executable_identity": executable_identity(
                detection.executable,
                cli_version=detection.version,
            ),
            "execution_context_identity": execution_context_identity(environment),
            "evidence_digest": None,
            "diagnostics": {"provider_probe_performed": False},
        },
    }


def _collect_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    prompt: str = CONNECTIVITY_PROMPT,
) -> tuple[int | None, bytes, bytes, bool, bool, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        start_new_session=os.name == "posix",
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    process.stdin.write(prompt.encode("utf-8"))
    process.stdin.close()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    oversized = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready = selector.select(min(0.25, remaining))
            if not ready and process.poll() is not None:
                # Drain EOF after the process exits.
                ready = selector.select(0)
                if not ready:
                    break
            for key, _ in ready:
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = buffers[key.data]
                room = CONNECTIVITY_OUTPUT_LIMIT + 1 - len(target)
                if room > 0:
                    target.extend(chunk[:room])
                if len(target) > CONNECTIVITY_OUTPUT_LIMIT:
                    oversized = True
                    break
            if oversized:
                break
        if timed_out or oversized:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except (OSError, ProcessLookupError):
                    pass
                process.wait(timeout=2)
        else:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except (OSError, ProcessLookupError):
                        pass
                    process.wait(timeout=2)
    finally:
        selector.close()
    stdout, stderr = bytes(buffers["stdout"]), bytes(buffers["stderr"])
    prompt_detected = bool(_INTERACTIVE_PROMPT.search((stdout + stderr).decode("utf-8", errors="replace")))
    return process.returncode, stdout, stderr, timed_out, oversized, prompt_detected


def _app_server_connectivity_probe(
    executable: str,
    requested_model: str,
    *,
    environment: dict[str, str],
    timeout_seconds: int,
    cli_version: str | None = None,
) -> dict[str, Any]:
    """Execute one bounded Provider turn on one exact app-server thread."""
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    source_mutated = False
    launch_failed = False
    timed_out = False
    oversized = False
    partial_frame = False
    stdout_size = 0
    stderr_bytes = bytearray()
    stdout_frame = bytearray()
    message_count = 0
    protocol_failure_code = ""
    protocol_failure_summary = ""
    reported_errors: list[str] = []
    warnings: list[str] = []
    responses_seen: set[str | int] = set()
    requested_ids: dict[str | int, str] = {}
    protocol_transcript: list[dict[str, Any]] = []
    protocol_started = time.monotonic()
    protocol_warnings: list[str] = []
    critical_protocol_method = ""
    pending_approval = False
    initialize_response = False
    mcp_inventory_response = False
    thread_response = False
    turn_response = False
    thread_notification_seen = False
    thread_id = ""
    turn_id = ""
    effective_model = ""
    observed_settings_model = ""
    model_provider = ""
    turn_started = False
    turn_completed = False
    terminal_status = ""
    final_messages: list[str] = []
    terminal_agent_messages: list[str] = []
    reroute_count = 0
    provider_reachable = False
    thread_request_sent = False
    mcp_request_sent = False
    turn_request_sent = False
    expected_cwd = ""
    expected_codex_home = ""
    user_config_isolated = False
    credential_file_linked = False
    observed_cli_version = str(
        cli_version or _reported_cli_version(Path(executable)) or ""
    )
    protocol_schema_matches = schema_version_matches(
        observed_cli_version,
        schema_bundle_sha256=STABLE_JSON_SCHEMA_BUNDLE_SHA256,
        server_notification_sha256=STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
        server_request_sha256=STABLE_SERVER_REQUEST_SCHEMA_SHA256,
    )

    def safe_text(value: object, *, limit: int = 1000) -> str:
        redacted = _RUNTIME_ID.sub("[runtime id redacted]", str(value or ""))
        return str(sanitize_result_value(redacted) or "")[:limit]

    def record_protocol_message(
        message: dict[str, Any],
        classification: Any,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "sequence": len(protocol_transcript) + 1,
            "offset_ms": max(0, int((time.monotonic() - protocol_started) * 1000)),
            "classification": classification.kind.value,
            "has_id": "id" in message,
            "id_type": (
                "integer"
                if isinstance(message.get("id"), int)
                and not isinstance(message.get("id"), bool)
                else "string"
                if isinstance(message.get("id"), str)
                else "none"
            ),
            "disposition": "pending",
        }
        if classification.method:
            entry["method"] = classification.method
        elif classification.request_id in requested_ids:
            entry["response_to"] = requested_ids[classification.request_id]
        payload_key = next(
            (key for key in ("params", "result", "error") if key in message),
            None,
        )
        if payload_key is not None:
            entry["payload_key"] = payload_key
            entry["payload_shape"] = payload_shape_summary(message[payload_key])
        if classification.reason:
            entry["classification_reason"] = classification.reason
        if len(protocol_transcript) < CONNECTIVITY_MESSAGE_LIMIT:
            protocol_transcript.append(entry)
        return entry

    def add_protocol_warning(code: str) -> None:
        if code not in protocol_warnings and len(protocol_warnings) < 20:
            protocol_warnings.append(code)

    def valid_timestamp(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def valid_optional_string(value: object, *, limit: int = 1000) -> bool:
        return value is None or (isinstance(value, str) and len(value) <= limit)

    def same_local_path(candidate: object, expected: str) -> bool:
        if not isinstance(candidate, str) or not candidate or not expected:
            return False
        try:
            return Path(candidate).resolve(strict=False) == Path(expected).resolve(
                strict=False
            )
        except OSError:
            return False

    def fail(code: str, summary: str) -> None:
        nonlocal protocol_failure_code, protocol_failure_summary
        if not protocol_failure_code:
            protocol_failure_code = code
            protocol_failure_summary = summary

    if not protocol_schema_matches:
        fail(
            "PROTOCOL_SCHEMA_VERSION_MISMATCH",
            "The installed Codex CLI does not match TWOS's generated app-server protocol schema.",
        )

    def bind_thread(candidate: object) -> bool:
        nonlocal thread_id
        if not isinstance(candidate, str) or not candidate or len(candidate) > 240:
            fail("APP_SERVER_THREAD_ID_INVALID", "Codex returned an invalid thread identity.")
            return False
        if thread_id and thread_id != candidate:
            fail("APP_SERVER_CROSS_THREAD", "Codex returned conflicting thread identity evidence.")
            return False
        thread_id = candidate
        return True

    def bind_turn(candidate: object) -> bool:
        nonlocal turn_id
        if not isinstance(candidate, str) or not candidate or len(candidate) > 240:
            fail("APP_SERVER_TURN_ID_INVALID", "Codex returned an invalid turn identity.")
            return False
        if turn_id and turn_id != candidate:
            fail("APP_SERVER_CROSS_TURN", "Codex returned conflicting turn identity evidence.")
            return False
        turn_id = candidate
        return True

    def validate_notification_ids(params: dict[str, Any], *, require_turn: bool) -> bool:
        if not bind_thread(params.get("threadId")):
            return False
        if require_turn and not bind_turn(params.get("turnId")):
            return False
        return True

    def record_error(value: object) -> None:
        text_value = safe_text(value)
        if text_value and len(reported_errors) < 20:
            reported_errors.append(text_value)

    def handle_response(request_id: str | int, message: dict[str, Any]) -> None:
        nonlocal initialize_response, mcp_inventory_response
        nonlocal thread_response, turn_response
        nonlocal effective_model, model_provider
        if request_id not in requested_ids:
            fail("APP_SERVER_UNKNOWN_RESPONSE", "Codex returned a response for an unknown request.")
            return
        if request_id in responses_seen:
            fail("APP_SERVER_DUPLICATE_RESPONSE", "Codex returned a duplicate response.")
            return
        responses_seen.add(request_id)
        if "error" in message:
            error = message.get("error")
            if isinstance(error, dict):
                record_error(error.get("message"))
            fail("APP_SERVER_REQUEST_ERROR", "Codex app-server rejected a connectivity request.")
            return
        result = message.get("result")
        if not isinstance(result, dict):
            fail("APP_SERVER_RESPONSE_INVALID", "Codex returned an invalid app-server response.")
            return
        if request_id == 1:
            if (
                not all(
                    isinstance(result.get(key), str)
                    for key in ("userAgent", "platformFamily", "platformOs")
                )
                or not same_local_path(result.get("codexHome"), expected_codex_home)
            ):
                fail("APP_SERVER_INITIALIZE_INVALID", "Codex returned incomplete initialization evidence.")
                return
            initialize_response = True
            return
        if request_id == 2:
            data = result.get("data")
            next_cursor = result.get("nextCursor")
            if data != [] or next_cursor is not None:
                fail(
                    "APP_SERVER_MCP_INVENTORY_NOT_EMPTY",
                    "Codex exposed an MCP integration during connectivity verification.",
                )
                return
            mcp_inventory_response = True
            return
        if request_id == 3:
            model_value = result.get("model")
            provider_value = result.get("modelProvider")
            thread = result.get("thread")
            sandbox = result.get("sandbox")
            if (
                not isinstance(model_value, str)
                or not _SAFE_MODEL_IDENTIFIER.fullmatch(model_value)
                or model_value != requested_model
                or not isinstance(provider_value, str)
                or provider_value != CONNECTIVITY_MODEL_PROVIDER
                or not same_local_path(result.get("cwd"), expected_cwd)
                or result.get("approvalPolicy") != "never"
                or result.get("instructionSources") != []
                or not isinstance(result.get("runtimeWorkspaceRoots"), list)
                or len(result["runtimeWorkspaceRoots"]) != 1
                or not same_local_path(
                    result["runtimeWorkspaceRoots"][0], expected_cwd
                )
                or not isinstance(sandbox, dict)
                or sandbox.get("type") != "readOnly"
                or sandbox.get("networkAccess") is not False
                or not isinstance(thread, dict)
                or thread.get("ephemeral") is not True
                or not bind_thread(thread.get("id"))
            ):
                fail("APP_SERVER_THREAD_START_INVALID", "Codex returned incomplete thread model evidence.")
                return
            effective_model = model_value
            if observed_settings_model and observed_settings_model != effective_model:
                fail("APP_SERVER_MODEL_CONFLICT", "Codex returned conflicting thread model settings.")
                return
            model_provider = safe_text(provider_value, limit=240)
            thread_response = True
            return
        if request_id == 4:
            turn = result.get("turn")
            if not isinstance(turn, dict) or not bind_turn(turn.get("id")):
                fail("APP_SERVER_TURN_START_INVALID", "Codex returned incomplete turn evidence.")
                return
            if turn.get("status") not in {"inProgress", "completed"}:
                fail("APP_SERVER_TURN_STATUS_INVALID", "Codex returned an invalid initial turn status.")
                return
            turn_response = True
            return
    def handle_notification(method: str, params: dict[str, Any]) -> None:
        nonlocal thread_notification_seen, turn_started, turn_completed
        nonlocal effective_model, observed_settings_model
        nonlocal reroute_count, terminal_status, provider_reachable
        nonlocal terminal_agent_messages
        nonlocal critical_protocol_method, pending_approval
        if method in {"warning", "deprecationNotice", "configWarning"}:
            warning = safe_text(params.get("message") or params.get("warning"))
            if warning and len(warnings) < 20:
                warnings.append(warning)
            return
        if method == "remoteControl/status/changed":
            status = params.get("status")
            if (
                status not in {"disabled", "connecting", "connected", "errored"}
                or not isinstance(params.get("installationId"), str)
                or not isinstance(params.get("serverName"), str)
                or not valid_optional_string(params.get("environmentId"), limit=240)
            ):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid remote-control status metadata.",
                )
                return
            # 0.144.4 emits `disabled` immediately after initialize. It is
            # known startup metadata, not Provider/model/readiness evidence.
            if status == "disabled":
                add_protocol_warning("REMOTE_CONTROL_DISABLED")
                return
            critical_protocol_method = method
            fail(
                "APP_SERVER_REMOTE_CONTROL_ACTIVE",
                "Codex remote control was not disabled for the isolated connection probe.",
            )
            return
        if method == "account/updated":
            auth_mode = params.get("authMode")
            plan_type = params.get("planType")
            if auth_mode not in {
                None,
                "apikey",
                "chatgpt",
                "chatgptAuthTokens",
                "headers",
                "agentIdentity",
                "personalAccessToken",
                "bedrockApiKey",
            } or plan_type not in {
                None,
                "free",
                "go",
                "plus",
                "pro",
                "prolite",
                "team",
                "self_serve_business_usage_based",
                "business",
                "enterprise_cbp_usage_based",
                "enterprise",
                "edu",
                "unknown",
            }:
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid account-state metadata.",
                )
                return
            add_protocol_warning("ACCOUNT_STATE_OBSERVED")
            return
        if method == "account/login/completed":
            if (
                type(params.get("success")) is not bool
                or not valid_optional_string(params.get("error"), limit=4000)
                or not valid_optional_string(params.get("loginId"), limit=240)
            ):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid account-login metadata.",
                )
                return
            if not params["success"]:
                fail(
                    "APP_SERVER_AUTHENTICATION_REQUIRED",
                    "Codex reported that authentication did not complete in the detached runtime context.",
                )
            return
        if method == "account/rateLimits/updated":
            if not isinstance(params.get("rateLimits"), dict):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid account rate-limit metadata.",
                )
                return
            add_protocol_warning("ACCOUNT_RATE_LIMITS_OBSERVED")
            return
        if method.startswith("mcpServer/") or method.startswith("item/mcp"):
            fail(
                "APP_SERVER_UNEXPECTED_ACTION",
                "Codex exposed an MCP action during connectivity verification.",
            )
            return
        if method == "thread/started":
            thread = params.get("thread")
            if (
                not thread_request_sent
                or thread_notification_seen
                or turn_started
                or turn_completed
                or not isinstance(thread, dict)
                or not bind_thread(thread.get("id"))
            ):
                fail("APP_SERVER_THREAD_LIFECYCLE_CONFLICT", "Codex returned conflicting thread lifecycle evidence.")
                return
            thread_notification_seen = True
            return
        if method == "thread/status/changed":
            if not thread_request_sent or not bind_thread(params.get("threadId")):
                return
            status = params.get("status")
            if not isinstance(status, dict):
                fail("APP_SERVER_THREAD_STATUS_INVALID", "Codex returned invalid thread status evidence.")
                return
            status_type = status.get("type")
            if status_type not in {"notLoaded", "idle", "systemError", "active"}:
                fail("APP_SERVER_THREAD_STATUS_INVALID", "Codex returned invalid thread status evidence.")
                return
            if status_type == "systemError":
                fail("APP_SERVER_THREAD_ERROR", "Codex reported a terminal thread-system error.")
                return
            if status_type == "active":
                flags = status.get("activeFlags")
                if (
                    not isinstance(flags, list)
                    or any(flag not in {"waitingOnApproval", "waitingOnUserInput"} for flag in flags)
                ):
                    fail("APP_SERVER_THREAD_STATUS_INVALID", "Codex returned invalid active-thread evidence.")
                    return
                if flags:
                    pending_approval = True
                    fail(
                        "APP_SERVER_HIDDEN_APPROVAL_PENDING",
                        "Codex connection verification is waiting for an approval or user input that TWOS will not auto-approve.",
                    )
            return
        if method == "thread/tokenUsage/updated":
            if not thread_request_sent or not bind_thread(params.get("threadId")):
                return
            candidate_turn = params.get("turnId")
            if candidate_turn is not None:
                if not turn_started or turn_completed:
                    fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order turn metadata.")
                    return
                if not bind_turn(candidate_turn):
                    return
            return
        if method == "thread/settings/updated":
            if not thread_request_sent or not bind_thread(params.get("threadId")):
                return
            settings = params.get("threadSettings")
            if not isinstance(settings, dict):
                fail("APP_SERVER_SETTINGS_INVALID", "Codex returned invalid thread settings evidence.")
                return
            settings_model = settings.get("model")
            if not isinstance(settings_model, str) or not _SAFE_MODEL_IDENTIFIER.fullmatch(settings_model):
                fail("APP_SERVER_SETTINGS_INVALID", "Codex returned invalid thread model settings.")
                return
            observed_settings_model = settings_model
            if effective_model and settings_model != effective_model:
                fail("APP_SERVER_MODEL_CONFLICT", "Codex changed the thread model outside an explicit reroute.")
            return
        if method == "turn/started":
            turn = params.get("turn")
            if (
                not turn_request_sent
                or turn_started
                or turn_completed
                or not bind_thread(params.get("threadId"))
                or not isinstance(turn, dict)
                or not bind_turn(turn.get("id"))
                or turn.get("status") != "inProgress"
            ):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned conflicting turn-start evidence.")
                return
            turn_started = True
            return
        if method == "model/rerouted":
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_REROUTE_CONFLICT", "Codex returned an out-of-order model reroute.")
                return
            from_model = params.get("fromModel")
            to_model = params.get("toModel")
            reroute_reason = params.get("reason")
            if (
                not isinstance(from_model, str)
                or not isinstance(to_model, str)
                or not _SAFE_MODEL_IDENTIFIER.fullmatch(from_model)
                or not _SAFE_MODEL_IDENTIFIER.fullmatch(to_model)
                or from_model != effective_model
                or from_model == to_model
                or reroute_reason != "highRiskCyberActivity"
                or reroute_count != 0
            ):
                fail("APP_SERVER_REROUTE_CONFLICT", "Codex returned conflicting model reroute evidence.")
                return
            effective_model = to_model
            reroute_count += 1
            provider_reachable = True
            return
        if method == "model/verification":
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order turn metadata.")
                return
            verifications = params.get("verifications")
            if (
                not isinstance(verifications, list)
                or any(value != "trustedAccessForCyber" for value in verifications)
            ):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid model-verification metadata.",
                )
                return
            # This is a trusted-access/safety signal in 0.144.4, not a model
            # identity or availability signal.
            add_protocol_warning("MODEL_TRUST_VERIFICATION_OBSERVED")
            return
        if method == "turn/moderationMetadata":
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order turn metadata.")
            return
        if method == "model/safetyBuffering/updated":
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order safety metadata.")
                return
            if (
                not isinstance(params.get("model"), str)
                or not isinstance(params.get("reasons"), list)
                or not isinstance(params.get("useCases"), list)
                or type(params.get("showBufferingUi")) is not bool
                or not valid_optional_string(params.get("fasterModel"), limit=240)
            ):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid safety-buffering metadata.",
                )
                return
            add_protocol_warning("MODEL_SAFETY_BUFFERING_OBSERVED")
            return
        if method == "guardianWarning":
            if (
                not thread_request_sent
                or not bind_thread(params.get("threadId"))
                or not isinstance(params.get("message"), str)
                or len(params["message"]) > 4000
            ):
                critical_protocol_method = method
                fail(
                    "PROTOCOL_COMPATIBILITY_BLOCKED",
                    "The local Codex app-server returned invalid guardian-warning metadata.",
                )
                return
            fail(
                "APP_SERVER_GUARDIAN_WARNING",
                "Codex reported a guardian safety warning during connection verification.",
            )
            return
        if method == "error":
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order error evidence.")
                return
            error = params.get("error")
            if isinstance(error, dict):
                record_error(error.get("message"))
                info = error.get("codexErrorInfo")
                if info is not None:
                    record_error(info)
                if type(params.get("willRetry")) is not bool:
                    fail("APP_SERVER_ERROR_INVALID", "Codex returned incomplete error retry evidence.")
                elif not params["willRetry"]:
                    fail("APP_SERVER_TURN_ERROR", "Codex reported a terminal Provider-turn error.")
            else:
                fail("APP_SERVER_ERROR_INVALID", "Codex returned invalid error evidence.")
            return
        if method == "turn/completed":
            turn = params.get("turn")
            if (
                not turn_request_sent
                or
                turn_completed
                or not turn_started
                or not bind_thread(params.get("threadId"))
                or not isinstance(turn, dict)
                or not bind_turn(turn.get("id"))
            ):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned conflicting turn-completion evidence.")
                return
            terminal_status = str(turn.get("status") or "")
            if terminal_status not in {"completed", "failed", "interrupted"}:
                fail("APP_SERVER_TURN_STATUS_INVALID", "Codex returned an invalid terminal turn status.")
                return
            error = turn.get("error")
            if isinstance(error, dict):
                record_error(error.get("message"))
                if error.get("codexErrorInfo") is not None:
                    record_error(error.get("codexErrorInfo"))
            items = turn.get("items")
            if not isinstance(items, list):
                fail("APP_SERVER_TURN_ITEMS_INVALID", "Codex returned invalid terminal item evidence.")
                return
            terminal_agent_messages = []
            for item in items:
                if not isinstance(item, dict):
                    fail("APP_SERVER_TURN_ITEMS_INVALID", "Codex returned invalid terminal item evidence.")
                    return
                if item.get("type") != "agentMessage":
                    continue
                text_value = item.get("text")
                if not isinstance(text_value, str) or len(text_value) > 500:
                    fail("APP_SERVER_TURN_ITEMS_INVALID", "Codex returned invalid terminal item evidence.")
                    return
                terminal_agent_messages.append(text_value)
            turn_completed = True
            provider_reachable = terminal_status == "completed"
            return
        if method in {
            "item/agentMessage/delta",
            "item/reasoning/summaryTextDelta",
            "item/reasoning/summaryPartAdded",
            "item/reasoning/textDelta",
        }:
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order item evidence.")
            return
        if method in {"item/started", "item/completed"}:
            if not turn_request_sent or turn_completed or not turn_started or not validate_notification_ids(params, require_turn=True):
                fail("APP_SERVER_TURN_LIFECYCLE_CONFLICT", "Codex returned out-of-order item evidence.")
                return
            item = params.get("item")
            timestamp_key = "startedAtMs" if method == "item/started" else "completedAtMs"
            if not isinstance(item, dict) or not valid_timestamp(params.get(timestamp_key)):
                fail("APP_SERVER_ITEM_INVALID", "Codex returned invalid item evidence.")
                return
            item_type = item.get("type")
            if item_type not in {"userMessage", "agentMessage", "reasoning"}:
                fail("APP_SERVER_UNEXPECTED_ACTION", "Codex attempted an action during connectivity verification.")
                return
            if method == "item/completed" and item_type == "agentMessage":
                text_value = item.get("text")
                if not isinstance(text_value, str) or len(text_value) > 500:
                    fail("APP_SERVER_FINAL_MESSAGE_INVALID", "Codex returned an invalid final response.")
                    return
                final_messages.append(text_value)
                provider_reachable = True
            return
        if method == "thread/closed" and turn_request_sent and turn_completed:
            bind_thread(params.get("threadId"))
            return
        action_methods = {
            "hook/started",
            "hook/completed",
            "item/autoApprovalReview/started",
            "item/autoApprovalReview/completed",
            "command/exec/outputDelta",
            "process/outputDelta",
            "process/exited",
            "item/commandExecution/outputDelta",
            "item/commandExecution/terminalInteraction",
            "item/fileChange/outputDelta",
            "item/fileChange/patchUpdated",
            "item/mcpToolCall/progress",
            "fs/changed",
        }
        method_policy = classify_notification_method(method)
        if method in action_methods:
            critical_protocol_method = method
            if "Approval" in method or "approval" in method:
                pending_approval = True
                fail(
                    "APP_SERVER_APPROVAL_REQUEST_BLOCKED",
                    "Codex requested an approval during the read-only connection probe; TWOS did not approve it.",
                )
            else:
                fail(
                    "APP_SERVER_UNEXPECTED_ACTION",
                    "Codex exposed an action or source mutation during connectivity verification.",
                )
            return
        if method in {
            "thread/realtime/error",
            "windows/worldWritableWarning",
            "windowsSandbox/setupCompleted",
        }:
            critical_protocol_method = method
            fail(
                "APP_SERVER_ENVIRONMENT_BLOCKED",
                "Codex reported a terminal or unsafe execution-environment condition during connection verification.",
            )
            return
        if method_policy.known:
            if method_policy.critical:
                # The method is in the exact-version registry but is not a
                # readiness signal. Preserve only its type-shape audit entry.
                add_protocol_warning("KNOWN_CRITICAL_METADATA_OBSERVED")
            else:
                add_protocol_warning("KNOWN_NONCRITICAL_NOTIFICATION_OBSERVED")
            return
        if method_policy.critical:
            critical_protocol_method = method
            fail(
                "PROTOCOL_COMPATIBILITY_BLOCKED",
                "The local Codex app-server returned a critical protocol message that this TWOS version cannot safely interpret.",
            )
            return
        add_protocol_warning("UNKNOWN_NONCRITICAL_NOTIFICATION")

    def handle_server_request(
        request_id: str | int,
        method: str,
        params: object,
    ) -> None:
        nonlocal critical_protocol_method, pending_approval
        if not isinstance(params, dict):
            send_server_response(
                request_id,
                error={"code": -32602, "message": "Invalid app-server request parameters."},
            )
            critical_protocol_method = method
            fail(
                "PROTOCOL_COMPATIBILITY_BLOCKED",
                "The local Codex app-server returned an invalid server request.",
            )
            return
        if method in EXPERIMENTAL_SERVER_REQUEST_METHODS:
            if (
                method == "currentTime/read"
                and thread_request_sent
                and params.get("threadId") == thread_id
            ):
                send_server_response(
                    request_id,
                    result={"currentTimeAt": int(time.time())},
                )
                add_protocol_warning("SAFE_CURRENT_TIME_REQUEST_HANDLED")
                return
        approval_methods = {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/tool/requestUserInput",
            "mcpServer/elicitation/request",
            "item/permissions/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }
        send_server_response(
            request_id,
            error={
                "code": -32601,
                "message": "Method is not supported by the read-only TWOS connection probe.",
            },
        )
        critical_protocol_method = method
        if method in approval_methods:
            pending_approval = True
            fail(
                "APP_SERVER_APPROVAL_REQUEST_BLOCKED",
                "Codex requested an approval or Owner input during the read-only connection probe; TWOS did not approve it.",
            )
        elif method in KNOWN_SERVER_REQUEST_METHODS:
            fail(
                "APP_SERVER_UNSUPPORTED_REQUEST",
                "Codex requested a tool, credential, or attestation action that the read-only connection probe does not support.",
            )
        else:
            fail(
                "PROTOCOL_COMPATIBILITY_BLOCKED",
                "The local Codex app-server returned a server request that this TWOS version cannot safely interpret.",
            )

    def handle_message(message: object) -> None:
        nonlocal critical_protocol_method
        outstanding = tuple(
            request_id
            for request_id in requested_ids
            if request_id not in responses_seen
        )
        classification = classify_jsonrpc_message(
            message,
            outstanding_request_ids=outstanding,
        )
        message_dict = message if isinstance(message, dict) else {}
        entry = record_protocol_message(message_dict, classification)
        if classification.kind is MessageKind.INVALID_MESSAGE:
            entry["disposition"] = "blocked"
            reason = classification.reason
            code = (
                "APP_SERVER_RESPONSE_OUT_OF_ORDER"
                if reason == "out_of_order_response"
                else "APP_SERVER_MESSAGE_INVALID"
            )
            fail(code, "Codex returned an invalid or out-of-order app-server message.")
            return
        if classification.kind is MessageKind.RESPONSE:
            handle_response(classification.request_id, message_dict)
            entry["disposition"] = "blocked" if protocol_failure_code else "handled"
            return
        method = str(classification.method or "")
        params = message_dict.get("params")
        if classification.kind is MessageKind.SERVER_REQUEST:
            entry["known_method"] = method in KNOWN_SERVER_REQUEST_METHODS
            handle_server_request(classification.request_id, method, params)
            entry["disposition"] = "blocked" if protocol_failure_code else "responded"
            return
        method_policy = classify_notification_method(method)
        entry["known_method"] = method_policy.known
        entry["criticality"] = method_policy.criticality.value
        entry["registry"] = method_policy.registry
        if not isinstance(params, dict):
            critical_protocol_method = method
            fail(
                "PROTOCOL_COMPATIBILITY_BLOCKED",
                "The local Codex app-server returned invalid notification parameters.",
            )
            entry["disposition"] = "blocked"
            return
        handle_notification(method, params)
        entry["disposition"] = (
            "blocked"
            if protocol_failure_code
            else "retained_warning"
            if not method_policy.known
            else "handled"
        )

    def send(message: dict[str, Any]) -> bool:
        if process is None or process.stdin is None or process.stdin.closed:
            fail("APP_SERVER_STDIN_UNAVAILABLE", "Codex app-server input became unavailable.")
            return False
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(payload) > CONNECTIVITY_FRAME_LIMIT:
            fail("APP_SERVER_REQUEST_OVERSIZED", "A connectivity request exceeded the bounded frame limit.")
            return False
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            fail("APP_SERVER_STDIN_UNAVAILABLE", "Codex app-server input became unavailable.")
            return False
        request_id = message.get("id")
        method = message.get("method")
        if (
            isinstance(request_id, (str, int))
            and not isinstance(request_id, bool)
            and isinstance(method, str)
        ):
            requested_ids[request_id] = method
        return True

    def send_server_response(
        request_id: str | int,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> bool:
        if (result is None) == (error is None):
            return False
        payload: dict[str, Any] = {"id": request_id}
        if result is not None:
            payload["result"] = result
        else:
            payload["error"] = error
        return send(payload)

    def pump_until(done: Any, deadline: float) -> bool:
        nonlocal timed_out, oversized, partial_frame
        nonlocal stdout_size, message_count
        assert selector is not None and process is not None
        while not done() and not protocol_failure_code:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                partial_frame = bool(stdout_frame)
                break
            ready = selector.select(min(0.25, remaining))
            if not ready:
                if process.poll() is not None:
                    partial_frame = bool(stdout_frame)
                    fail("APP_SERVER_PROCESS_EXITED", "Codex app-server exited before terminal evidence was available.")
                continue
            for key, _ in ready:
                try:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except KeyError:
                        pass
                    continue
                if stdout_size + len(stderr_bytes) + len(chunk) > CONNECTIVITY_OUTPUT_LIMIT:
                    oversized = True
                    fail("APP_SERVER_OUTPUT_LIMIT", "Codex app-server output exceeded the bounded evidence limit.")
                    break
                if key.data == "stderr":
                    stderr_bytes.extend(chunk)
                    continue
                stdout_size += len(chunk)
                stdout_frame.extend(chunk)
                if len(stdout_frame) > CONNECTIVITY_FRAME_LIMIT and b"\n" not in stdout_frame:
                    oversized = True
                    fail("APP_SERVER_FRAME_LIMIT", "Codex app-server emitted an oversized protocol frame.")
                    break
                while b"\n" in stdout_frame and not protocol_failure_code:
                    raw_frame, _, remainder = stdout_frame.partition(b"\n")
                    stdout_frame[:] = remainder
                    if not raw_frame:
                        fail("APP_SERVER_EMPTY_FRAME", "Codex app-server emitted an empty protocol frame.")
                        break
                    if len(raw_frame) > CONNECTIVITY_FRAME_LIMIT:
                        oversized = True
                        fail("APP_SERVER_FRAME_LIMIT", "Codex app-server emitted an oversized protocol frame.")
                        break
                    message_count += 1
                    if message_count > CONNECTIVITY_MESSAGE_LIMIT:
                        oversized = True
                        fail("APP_SERVER_MESSAGE_LIMIT", "Codex app-server emitted too many protocol messages.")
                        break
                    try:
                        decoded = raw_frame.decode("utf-8", errors="strict")
                        message = json.loads(decoded)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        fail("APP_SERVER_MALFORMED_FRAME", "Codex app-server emitted malformed structured output.")
                        break
                    handle_message(message)
        return bool(done() and not protocol_failure_code)

    def stop_process() -> None:
        if process is None:
            return
        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        try:
            # App-server is optional and must never hold the direct-exec
            # workflow behind a long graceful-shutdown wait after its bounded
            # probe deadline. Closing stdin gets a short cooperative window;
            # the exact process group is then terminated deterministically.
            process.wait(timeout=0.25)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=1)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    try:
        with (
            tempfile.TemporaryDirectory(
                prefix="twos-codex-connectivity-"
            ) as raw_root,
            tempfile.TemporaryDirectory(
                prefix="twos-codex-isolated-home-"
            ) as raw_codex_home,
        ):
            root = Path(raw_root)
            expected_cwd = str(root)
            isolated_codex_home = Path(raw_codex_home)
            expected_codex_home = str(isolated_codex_home)
            isolated_codex_home.chmod(0o700)
            original_codex_home = environment.get("CODEX_HOME")
            original_home = environment.get("HOME")
            original_auth_file = (
                Path(original_codex_home) / "auth.json"
                if original_codex_home
                else Path(original_home) / ".codex" / "auth.json"
                if original_home
                else None
            )
            probe_environment = dict(environment)
            probe_environment["CODEX_HOME"] = str(isolated_codex_home)
            user_config_isolated = True
            if original_auth_file is not None and original_auth_file.is_file():
                try:
                    (isolated_codex_home / "auth.json").symlink_to(
                        original_auth_file.resolve(strict=True)
                    )
                    credential_file_linked = True
                except OSError:
                    fail(
                        "APP_SERVER_CREDENTIAL_ISOLATION_FAILED",
                        "Codex credentials could not be exposed safely to the isolated probe context.",
                    )
            initialized = subprocess.run(
                ["git", "init", "--quiet"],
                cwd=root,
                capture_output=True,
                timeout=10,
                env=environment,
            )
            if initialized.returncode != 0:
                fail("APP_SERVER_FIXTURE_UNAVAILABLE", "The temporary read-only fixture could not be initialized.")
            before = _temporary_source_entries(root)
            if not protocol_failure_code:
                try:
                    process = subprocess.Popen(
                        [
                            executable,
                            "app-server",
                            "-c",
                            "mcp_servers={}",
                            "--strict-config",
                            "--listen",
                            "stdio://",
                        ],
                        cwd=root,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0,
                        env=probe_environment,
                        start_new_session=os.name == "posix",
                    )
                except OSError:
                    launch_failed = True
                    fail("APP_SERVER_LAUNCH_FAILED", "Codex app-server could not be launched in the detached runtime context.")
            if process is not None:
                assert process.stdout is not None and process.stderr is not None
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stderr.fileno(), False)
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                deadline = time.monotonic() + max(1, min(int(timeout_seconds), 120))
                send(
                    {
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {
                                "name": "twos",
                                "title": "TWOS",
                                "version": __version__,
                            },
                            "capabilities": {
                                "experimentalApi": False,
                                "mcpServerOpenaiFormElicitation": False,
                                "optOutNotificationMethods": [],
                                "requestAttestation": False,
                            },
                        },
                    }
                )
                if pump_until(lambda: initialize_response, deadline):
                    send({"method": "initialized"})
                    mcp_request_sent = send(
                        {
                            "id": 2,
                            "method": "mcpServerStatus/list",
                            "params": {
                                "cursor": None,
                                "detail": "toolsAndAuthOnly",
                                "limit": 1,
                                "threadId": None,
                            },
                        }
                    )
                if mcp_request_sent and pump_until(
                    lambda: mcp_inventory_response,
                    deadline,
                ):
                    thread_request_sent = send(
                        {
                            "id": 3,
                            "method": "thread/start",
                            "params": {
                                "model": requested_model,
                                "modelProvider": CONNECTIVITY_MODEL_PROVIDER,
                                "cwd": str(root),
                                "approvalPolicy": "never",
                                "sandbox": "read-only",
                                "ephemeral": True,
                                "allowProviderModelFallback": False,
                                "personality": "none",
                                "baseInstructions": CONNECTIVITY_PROMPT,
                                "developerInstructions": CONNECTIVITY_PROMPT,
                                "config": {
                                    "mcp_servers": {},
                                    "web_search": "disabled",
                                },
                                "dynamicTools": [],
                                "environments": [],
                                "runtimeWorkspaceRoots": [str(root)],
                                "selectedCapabilityRoots": [],
                            },
                        }
                    )
                if thread_request_sent and pump_until(
                    lambda: thread_response,
                    deadline,
                ):
                    turn_request_sent = send(
                        {
                            "id": 4,
                            "method": "turn/start",
                            "params": {
                                "threadId": thread_id,
                                "input": [
                                    {
                                        "type": "text",
                                        "text": CONNECTIVITY_PROMPT,
                                        "text_elements": [],
                                    }
                                ],
                                "approvalPolicy": "never",
                                "model": requested_model,
                                "environments": [],
                            },
                        }
                    )
                if turn_request_sent and pump_until(
                    lambda: turn_response and turn_completed,
                    deadline,
                ):
                    # The ephemeral app-server process is closed directly.
                    # Cleanup acknowledgements are deliberately outside the
                    # Provider-turn readiness decision.
                    pass
                if stdout_frame and not protocol_failure_code:
                    partial_frame = True
                    fail("APP_SERVER_PARTIAL_FRAME", "Codex app-server left a partial protocol frame.")
                stop_process()
                after = _temporary_source_entries(root)
                source_mutated = before != after
    except (OSError, ValueError, subprocess.SubprocessError):
        launch_failed = True
        fail("APP_SERVER_LAUNCH_FAILED", "Codex connectivity verification could not start in the detached runtime context.")
    finally:
        if selector is not None:
            selector.close()
        stop_process()

    response_ok = bool(
        len(final_messages) == 1
        and final_messages[0].strip() == "TWOS_CODEX_CONNECTION_OK"
        and terminal_agent_messages == final_messages
    )
    if turn_completed and terminal_status != "completed" and not protocol_failure_code:
        fail("APP_SERVER_TURN_FAILED", "Codex connectivity verification did not complete successfully.")
    if turn_completed and not response_ok and not protocol_failure_code:
        fail("APP_SERVER_FINAL_MESSAGE_MISMATCH", "Codex did not return the exact bounded connectivity response.")
    if partial_frame and not protocol_failure_code:
        fail("APP_SERVER_PARTIAL_FRAME", "Codex app-server left a partial protocol frame.")
    if timed_out and not protocol_failure_code:
        fail("APP_SERVER_TIMEOUT", "Codex connectivity verification timed out.")

    stderr = bytes(stderr_bytes)
    prompt_detected = bool(
        _INTERACTIVE_PROMPT.search(stderr.decode("utf-8", errors="replace"))
    )
    probe_success = bool(
        not protocol_failure_code
        and protocol_schema_matches
        and initialize_response
        and mcp_inventory_response
        and thread_response
        and turn_response
        and turn_started
        and turn_completed
        and terminal_status == "completed"
        and response_ok
        and not pending_approval
    )
    actual_model_source = (
        "app_server_same_turn_reroute"
        if reroute_count
        else "app_server_effective_turn_model"
        if effective_model and probe_success
        else ""
    )
    logical_exit_code = (
        0
        if probe_success
        else process.returncode
        if process is not None and process.returncode is not None
        else 1
    )
    return {
        "exit_code": logical_exit_code,
        "stderr": stderr,
        "stdout_size": stdout_size,
        "timed_out": timed_out,
        "oversized": oversized,
        "partial_frame": partial_frame,
        "prompt_detected": prompt_detected,
        "source_mutated": source_mutated,
        "launch_failed": launch_failed,
        "user_config_isolated": user_config_isolated,
        "credential_file_linked": credential_file_linked,
        "protocol_failure_code": protocol_failure_code,
        "protocol_failure_summary": protocol_failure_summary,
        "parsed": {
            "thread_started": thread_response,
            "turn_started": turn_started,
            "turn_completed": turn_completed,
            "actual_model": effective_model if probe_success else "",
            "actual_model_source": actual_model_source,
            "actual_model_conflict": protocol_failure_code
            in {"APP_SERVER_MODEL_CONFLICT", "APP_SERVER_REROUTE_CONFLICT"},
            "lifecycle_conflict": protocol_failure_code
            in {
                "APP_SERVER_THREAD_LIFECYCLE_CONFLICT",
                "APP_SERVER_TURN_LIFECYCLE_CONFLICT",
                "APP_SERVER_CROSS_THREAD",
                "APP_SERVER_CROSS_TURN",
            },
            "reported_errors": reported_errors,
            "warnings": warnings,
            "response_ok": response_ok,
            "malformed_jsonl": protocol_failure_code
            in {
                "APP_SERVER_MALFORMED_FRAME",
                "APP_SERVER_PARTIAL_FRAME",
                "APP_SERVER_EMPTY_FRAME",
                "APP_SERVER_MESSAGE_INVALID",
                "APP_SERVER_NOTIFICATION_INVALID",
            },
            "provider_reachable": provider_reachable,
            "provider_probe_performed": turn_request_sent,
            "model_provider": model_provider,
            "model_rerouted": reroute_count > 0,
            "message_count": message_count,
            "protocol_schema": {
                "cli_version": observed_cli_version,
                "schema_digest": STABLE_JSON_SCHEMA_BUNDLE_SHA256,
                "notification_registry_digest": STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
                "request_registry_digest": STABLE_SERVER_REQUEST_SCHEMA_SHA256,
                "version_match": protocol_schema_matches,
            },
            "protocol_transcript": protocol_transcript,
            "protocol_warnings": protocol_warnings,
            "critical_protocol_method": critical_protocol_method,
            "pending_approval": pending_approval,
        },
    }


def _decode_probe_response(value: str) -> dict[str, str] | None:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    expected = {"status": CONNECTIVITY_RESPONSE_MARKER}
    return expected if decoded == expected else None


def _parse_probe_jsonl(stdout: bytes, requested_model: str) -> dict[str, Any]:
    """Parse only the bounded, ordered `codex exec --json` readiness evidence."""
    thread_started = False
    turn_started = False
    turn_completed = False
    turn_failed = False
    thread_identity = ""
    turn_identity = ""
    actual_models: set[str] = set()
    actual_model_sources: set[str] = set()
    agent_messages: list[str] = []
    reported_errors: list[str] = []
    raw_lines = [line for line in stdout.splitlines() if line.strip()]
    message_limit_exceeded = len(raw_lines) > CONNECTIVITY_MESSAGE_LIMIT
    malformed = message_limit_exceeded
    lifecycle_conflict = False
    unexpected_action = False
    terminal_success = False
    message_count = 0
    action_item_types = {
        "command_execution",
        "file_change",
        "mcp_tool_call",
        "web_search",
        "tool_call",
    }
    for raw_line in raw_lines[:CONNECTIVITY_MESSAGE_LIMIT]:
        message_count += 1
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            malformed = True
            continue
        if not isinstance(event, dict):
            malformed = True
            continue
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            malformed = True
            continue
        if turn_completed or turn_failed:
            lifecycle_conflict = True
        if event_type == "thread.started":
            candidate_thread = event.get("thread_id")
            valid_thread = (
                isinstance(candidate_thread, str)
                and 0 < len(candidate_thread) <= 240
            )
            if (
                not valid_thread
                or thread_started
                or turn_started
                or turn_completed
                or turn_failed
            ):
                lifecycle_conflict = True
            else:
                thread_started = True
                thread_identity = candidate_thread
        elif event_type == "turn.started":
            candidate_turn = event.get("turn_id") or event.get("id")
            valid_turn = candidate_turn is None or (
                isinstance(candidate_turn, str) and 0 < len(candidate_turn) <= 240
            )
            if (
                not thread_started
                or not valid_turn
                or turn_started
                or turn_completed
                or turn_failed
            ):
                lifecycle_conflict = True
            else:
                turn_started = True
                turn_identity = candidate_turn if isinstance(candidate_turn, str) else ""
        elif event_type == "turn.completed":
            candidate_turn = event.get("turn_id") or event.get("id")
            valid_turn = candidate_turn is None or (
                isinstance(candidate_turn, str) and 0 < len(candidate_turn) <= 240
            )
            if (
                not thread_started
                or not turn_started
                or turn_completed
                or turn_failed
                or not valid_turn
                or bool(candidate_turn) != bool(turn_identity)
                or (bool(candidate_turn) and candidate_turn != turn_identity)
            ):
                lifecycle_conflict = True
            else:
                turn_completed = True
                terminal_success = True
        elif event_type in {"turn.failed", "turn.cancelled", "turn.interrupted"}:
            if not thread_started or not turn_started or turn_completed or turn_failed:
                lifecycle_conflict = True
            turn_failed = True
            terminal_success = False

        if event_type in {"thread.started", "turn.started", "turn.completed"}:
            # Generic `model` fields can merely echo the requested argument.
            # Only explicitly resolved/actual fields establish physical model
            # identity; readiness itself is based on the exact requested argv
            # plus a successful Provider lifecycle.
            for key in (
                "actual_resolved_model",
                "actual_model_identifier",
                "resolved_model",
            ):
                candidate = event.get(key)
                if (
                    isinstance(candidate, str)
                    and _SAFE_MODEL_IDENTIFIER.fullmatch(candidate)
                ):
                    actual_models.add(candidate)
                    actual_model_sources.add(key)

        if event_type == "item.completed":
            item = event.get("item")
            if not thread_started or not turn_started or turn_completed or turn_failed:
                lifecycle_conflict = True
            if not isinstance(item, dict):
                malformed = True
                continue
            item_type = str(item.get("type") or "")
            if item_type == "agent_message" and isinstance(item.get("text"), str):
                agent_messages.append(item["text"][:2000])
            elif item_type == "error" and isinstance(item.get("message"), str):
                reported_errors.append(item["message"][:1000])
                match = re.fullmatch(
                    r"model rerouted: ([A-Za-z0-9][A-Za-z0-9._:/-]{0,239}) -> ([A-Za-z0-9][A-Za-z0-9._:/-]{0,239})(?: \([^\r\n]{0,500}\))?",
                    item["message"],
                )
                if match and match.group(1) == requested_model:
                    actual_models.add(match.group(2))
                    actual_model_sources.add("validated_reroute_event")
            elif item_type in action_item_types:
                unexpected_action = True
        elif event_type == "error" and isinstance(event.get("message"), str):
            reported_errors.append(event["message"][:1000])

    actual_model = next(iter(actual_models)) if len(actual_models) == 1 else ""
    final_message = agent_messages[0] if len(agent_messages) == 1 else ""
    return {
        "thread_started": thread_started,
        "turn_started": turn_started,
        "turn_completed": turn_completed,
        "turn_failed": turn_failed,
        "terminal_success": terminal_success,
        "thread_identity": thread_identity,
        "turn_identity": turn_identity,
        "actual_model": actual_model,
        "actual_model_source": (
            next(iter(actual_model_sources))
            if len(actual_model_sources) == 1
            else ""
        ),
        "actual_model_conflict": len(actual_models) > 1,
        "lifecycle_conflict": lifecycle_conflict,
        "unexpected_action": unexpected_action,
        "reported_errors": reported_errors[:20],
        "response_ok": _decode_probe_response(final_message) is not None,
        "response_document": _decode_probe_response(final_message),
        "final_message": final_message,
        "malformed_jsonl": malformed,
        "message_limit_exceeded": message_limit_exceeded,
        "message_count": message_count,
        "provider_probe_performed": turn_started,
        "provider_reachable": bool(
            turn_completed
            and terminal_success
            and not turn_failed
            and not malformed
            and not lifecycle_conflict
        ),
    }


def _temporary_source_entries(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if ".git" not in path.relative_to(root).parts
        )
    )


def _temporary_source_snapshot(root: Path) -> tuple[tuple[str, str, int, str], ...]:
    """Return a content-sensitive snapshot without following repository symlinks."""
    snapshot: list[tuple[str, str, int, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        try:
            stat = path.lstat()
            if path.is_symlink():
                kind = "symlink"
                identity = hashlib.sha256(os.readlink(path).encode()).hexdigest()
            elif path.is_file():
                kind = "file"
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                identity = digest.hexdigest()
            elif path.is_dir():
                kind = "directory"
                identity = ""
            else:
                kind = "other"
                identity = ""
            snapshot.append(
                (relative.as_posix(), kind, stat.st_mode & 0o7777, identity)
            )
        except OSError:
            snapshot.append((relative.as_posix(), "unreadable", 0, ""))
    return tuple(snapshot)


def _codex_exec_options(
    executable: str,
    *,
    environment: dict[str, str],
) -> frozenset[str]:
    """Inspect only local help text; this never starts a Provider request."""
    try:
        result = subprocess.run(
            [executable, "exec", "--help"],
            capture_output=True,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    help_text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return frozenset(
        option
        for option in ("--output-schema", "--output-last-message")
        if option in help_text
    )


def _command_option_value(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
    except ValueError:
        return None
    return command[index + 1] if index + 1 < len(command) else None


def _build_exec_probe_command(
    *,
    command_for: Any,
    detection: Any,
    requested_model: str,
    schema_path: Path,
    last_message_path: Path,
    exec_options: frozenset[str],
) -> tuple[list[str], bool, bool]:
    command_value = command_for(
        detection,
        CONNECTIVITY_PROMPT,
        requested_model,
        sandbox_mode="read-only",
    )
    if not isinstance(command_value, (list, tuple)) or not all(
        isinstance(value, str) and value for value in command_value
    ):
        raise ValueError("Codex adapter returned an invalid exec command.")
    command = list(command_value)
    try:
        command_executable = Path(command[0]).resolve(strict=True)
        detected_executable = Path(str(detection.executable)).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Codex executable identity could not be verified.") from exc
    if command_executable != detected_executable:
        raise ValueError("Codex adapter returned a different executable.")
    if (
        len(command) < 3
        or command[1] != "exec"
        or command[-1] != "-"
        or "--json" not in command
        or "--ephemeral" not in command
        or "--ignore-user-config" not in command
        or _command_option_value(command, "--model") != requested_model
        or _command_option_value(command, "--sandbox") != "read-only"
        or "--dangerously-bypass-approvals-and-sandbox" in command
    ):
        raise ValueError("Codex adapter did not return the required safe exec command.")

    schema_enabled = "--output-schema" in exec_options
    last_message_enabled = "--output-last-message" in exec_options
    sidecar_arguments: list[str] = []
    if schema_enabled:
        sidecar_arguments.extend(("--output-schema", str(schema_path)))
    if last_message_enabled:
        sidecar_arguments.extend(("--output-last-message", str(last_message_path)))
    command[-1:-1] = sidecar_arguments
    return command, schema_enabled, last_message_enabled


def _run_exec_connectivity_probe(
    detection: Any,
    requested_model: str,
    *,
    command_for: Any,
    environment: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run one isolated `codex exec --json` turn without touching product source."""
    result: dict[str, Any] = {
        "exit_code": None,
        "stderr": b"",
        "stdout_size": 0,
        "timed_out": False,
        "oversized": False,
        "prompt_detected": False,
        "source_mutated": False,
        "launch_failed": False,
        "command_invalid": False,
        "sidecar_supported": False,
        "schema_enabled": False,
        "last_message_enabled": False,
        "schema_unchanged": False,
        "last_message_present": False,
        "last_message_match": False,
        "parsed": {},
    }
    try:
        with tempfile.TemporaryDirectory(prefix="twos-codex-connectivity-") as value:
            temporary_root = Path(value)
            repository = temporary_root / "repository"
            repository.mkdir(mode=0o700)
            initialized = subprocess.run(
                ["git", "init", "--quiet"],
                cwd=repository,
                capture_output=True,
                timeout=10,
                env=environment,
            )
            if initialized.returncode != 0:
                result["launch_failed"] = True
                return result

            schema_path = temporary_root / "connectivity-response.schema.json"
            last_message_path = temporary_root / "connectivity-last-message.json"
            schema_bytes = json.dumps(
                CONNECTIVITY_RESPONSE_SCHEMA,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            schema_path.write_bytes(schema_bytes)
            schema_path.chmod(0o600)
            before = _temporary_source_snapshot(repository)
            exec_options = _codex_exec_options(
                str(detection.executable),
                environment=environment,
            )
            try:
                command, schema_enabled, last_message_enabled = (
                    _build_exec_probe_command(
                        command_for=command_for,
                        detection=detection,
                        requested_model=requested_model,
                        schema_path=schema_path,
                        last_message_path=last_message_path,
                        exec_options=exec_options,
                    )
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                result["command_invalid"] = True
                return result
            result["schema_enabled"] = schema_enabled
            result["last_message_enabled"] = last_message_enabled
            result["sidecar_supported"] = schema_enabled and last_message_enabled
            if not result["sidecar_supported"]:
                return result

            (
                exit_code,
                stdout,
                stderr,
                timed_out,
                oversized,
                prompt_detected,
            ) = _collect_process(
                command,
                cwd=repository,
                environment=environment,
                timeout_seconds=max(
                    1,
                    min(
                        int(timeout_seconds),
                        CONNECTIVITY_PROBE_MAX_TIMEOUT_SECONDS,
                    ),
                ),
                prompt=CONNECTIVITY_PROMPT,
            )
            after = _temporary_source_snapshot(repository)
            parsed = _parse_probe_jsonl(stdout, requested_model)
            result.update(
                {
                    "exit_code": exit_code,
                    "stderr": stderr,
                    "stdout_size": len(stdout),
                    "timed_out": timed_out,
                    "oversized": oversized,
                    "prompt_detected": prompt_detected,
                    "source_mutated": before != after,
                    "parsed": parsed,
                }
            )
            try:
                result["schema_unchanged"] = (
                    not schema_path.is_symlink()
                    and schema_path.read_bytes() == schema_bytes
                )
            except OSError:
                result["schema_unchanged"] = False
            try:
                if (
                    not last_message_path.is_symlink()
                    and last_message_path.is_file()
                    and last_message_path.stat().st_size <= 4096
                ):
                    last_message = last_message_path.read_text(encoding="utf-8")
                    result["last_message_present"] = True
                    result["last_message_match"] = bool(
                        _decode_probe_response(last_message.strip())
                        and _decode_probe_response(
                            str(parsed.get("final_message") or "").strip()
                        )
                        and json.loads(last_message)
                        == json.loads(str(parsed.get("final_message") or ""))
                    )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                result["last_message_match"] = False
    except (OSError, subprocess.SubprocessError):
        result["launch_failed"] = True
    return result


def verify_codex_connection(
    session: Session,
    *,
    owner_id: int,
    model: AIModel,
    detection: Any,
    command_for: Any,
    timeout_seconds: int = CONNECTIVITY_PROBE_TIMEOUT_SECONDS,
) -> CodexConnectivityEvidence:
    """Run one explicit, bounded, non-mutating real probe and persist safe evidence."""
    environment = codex_child_environment()
    executable_hash = executable_identity(
        detection.executable,
        cli_version=detection.version,
    )
    context_hash = execution_context_identity(environment)
    auth = inspect_authentication(detection.executable, environment=environment)
    requested_model = str(model.provider_model_id or "")
    checked_at = utc_now()
    started = time.monotonic()
    state = "BLOCKED"
    blocker_code = ""
    summary = "Codex connection verification is blocked."
    exit_code: int | None = None
    stderr = b""
    stdout_size = 0
    timed_out = False
    oversized = False
    prompt_detected = False
    parsed: dict[str, Any] = {}
    source_mutated = False
    launch_failed = False
    command_invalid = False
    sidecar_supported = False
    schema_enabled = False
    last_message_enabled = False
    schema_unchanged = False
    last_message_present = False
    last_message_match = False
    sanitized_command = (
        "codex exec --model <requested-model> --json --sandbox read-only "
        "--ephemeral --ignore-user-config --output-schema <temporary-sidecar> "
        "--output-last-message <temporary-sidecar> -"
    )

    if not detection.found:
        state, blocker_code, summary = "CLI_NOT_INSTALLED", "CLI_NOT_INSTALLED", detection.reason
    elif detection.status != "configured" or not detection.executable:
        state, blocker_code, summary = "BLOCKED", "CLI_UNSUPPORTED", detection.reason
    elif auth.state == "AUTHENTICATION_REQUIRED":
        state, blocker_code, summary = "AUTHENTICATION_REQUIRED", auth.state, auth.safe_summary
    elif auth.state == "CREDENTIAL_STORE_UNAVAILABLE":
        state, blocker_code, summary = "BLOCKED", auth.state, auth.safe_summary
    elif auth.state not in {"CHATGPT_LOGIN_AUTHENTICATED", "API_KEY_AUTHENTICATED"}:
        state, blocker_code, summary = "BLOCKED", "AUTHENTICATION_UNKNOWN", auth.safe_summary
    elif not auth.credential_store_accessible:
        state, blocker_code, summary = (
            "BLOCKED",
            "DETACHED_CREDENTIALS_UNAVAILABLE",
            "Detached TWOS cannot access the configured Codex credential source.",
        )
    elif not _SAFE_MODEL_IDENTIFIER.fullmatch(requested_model):
        state, blocker_code, summary = "MODEL_UNAVAILABLE", "MODEL_IDENTIFIER_INVALID", "The configured Codex model identifier is unavailable."
    else:
        probe = _run_exec_connectivity_probe(
            detection,
            requested_model,
            command_for=command_for,
            environment=environment,
            timeout_seconds=max(
                1,
                min(
                    int(timeout_seconds),
                    CONNECTIVITY_PROBE_MAX_TIMEOUT_SECONDS,
                ),
            ),
        )
        exit_code = probe.get("exit_code")
        stderr = bytes(probe.get("stderr") or b"")
        stdout_size = int(probe.get("stdout_size") or 0)
        timed_out = bool(probe.get("timed_out"))
        oversized = bool(probe.get("oversized"))
        prompt_detected = bool(probe.get("prompt_detected"))
        source_mutated = bool(probe.get("source_mutated"))
        launch_failed = bool(probe.get("launch_failed"))
        command_invalid = bool(probe.get("command_invalid"))
        sidecar_supported = bool(probe.get("sidecar_supported"))
        schema_enabled = bool(probe.get("schema_enabled"))
        last_message_enabled = bool(probe.get("last_message_enabled"))
        schema_unchanged = bool(probe.get("schema_unchanged"))
        last_message_present = bool(probe.get("last_message_present"))
        last_message_match = bool(probe.get("last_message_match"))
        parsed = dict(probe.get("parsed") or {})
        diagnostic_errors = stderr.decode("utf-8", errors="replace") + "\n" + "\n".join(
            str(item) for item in parsed.get("reported_errors", [])
        )
        terminal_contract_complete = bool(
            exit_code == 0
            and parsed.get("thread_started")
            and parsed.get("turn_started")
            and parsed.get("turn_completed")
            and parsed.get("terminal_success")
            and not parsed.get("turn_failed")
            and parsed.get("response_ok")
            and not parsed.get("malformed_jsonl")
            and not parsed.get("lifecycle_conflict")
            and not parsed.get("unexpected_action")
            and schema_unchanged
            and last_message_present
            and last_message_match
        )
        if launch_failed:
            state, blocker_code, summary = "BLOCKED", "PROBE_LAUNCH_FAILED", "Codex connectivity verification could not start in the detached runtime context."
        elif command_invalid:
            state, blocker_code, summary = "BLOCKED", "EXEC_COMMAND_UNSAFE", "The Local Codex adapter did not provide the required safe exec command."
        elif not sidecar_supported:
            state, blocker_code, summary = "BLOCKED", "EXEC_SIDECAR_UNSUPPORTED", "The installed Local Codex exec command does not support the required structured response sidecars."
        elif prompt_detected:
            state, blocker_code, summary = "AUTHENTICATION_REQUIRED", "INTERACTIVE_PROMPT_DETECTED", "Codex waited for an interactive login prompt that detached TWOS cannot complete."
        elif oversized:
            state, blocker_code, summary = "BLOCKED", "PROBE_OUTPUT_LIMIT", "Codex connectivity output exceeded the bounded evidence limit."
        elif source_mutated:
            state, blocker_code, summary = "BLOCKED", "PROBE_MUTATED_WORKSPACE", "Codex connectivity verification changed the isolated probe source."
        elif not terminal_contract_complete and _MODEL_UNAVAILABLE.search(diagnostic_errors):
            state, blocker_code, summary = "MODEL_UNAVAILABLE", "MODEL_UNAVAILABLE", "The requested Codex model was rejected or unavailable."
        elif not terminal_contract_complete and _AUTH_REQUIRED.search(diagnostic_errors):
            state, blocker_code, summary = "AUTHENTICATION_REQUIRED", "AUTHENTICATION_REQUIRED", "Codex authentication is required in the detached runtime context."
        elif not terminal_contract_complete and _PROVIDER_UNREACHABLE.search(diagnostic_errors):
            state, blocker_code, summary = "PROVIDER_UNREACHABLE", "PROVIDER_UNREACHABLE", "The Codex Provider could not be reached from detached TWOS."
        elif timed_out:
            state, blocker_code, summary = "PROVIDER_UNREACHABLE", "PROBE_TIMED_OUT", "Codex exec connectivity verification timed out before a complete terminal result was available."
        elif exit_code != 0:
            state, blocker_code, summary = "BLOCKED", "PROBE_FAILED", "Codex connectivity verification exited unsuccessfully."
        elif parsed.get("malformed_jsonl"):
            state, blocker_code, summary = "BLOCKED", "PROBE_MALFORMED_JSONL", "Codex exec returned malformed structured lifecycle evidence."
        elif parsed.get("lifecycle_conflict"):
            state, blocker_code, summary = "BLOCKED", "PROBE_LIFECYCLE_CONFLICT", "Codex exec returned conflicting lifecycle identity evidence."
        elif parsed.get("unexpected_action"):
            state, blocker_code, summary = "BLOCKED", "PROBE_UNEXPECTED_ACTION", "Codex attempted an action during the read-only connectivity probe."
        elif not (
            parsed.get("thread_started")
            and parsed.get("turn_started")
            and parsed.get("turn_completed")
            and parsed.get("terminal_success")
            and not parsed.get("turn_failed")
            and parsed.get("response_ok")
        ):
            state, blocker_code, summary = "BLOCKED", "PROBE_EVIDENCE_INCOMPLETE", "Codex did not return complete bounded terminal evidence."
        elif not schema_unchanged:
            state, blocker_code, summary = "BLOCKED", "PROBE_SCHEMA_CHANGED", "The structured response schema changed during connectivity verification."
        elif not last_message_present or not last_message_match:
            state, blocker_code, summary = "BLOCKED", "PROBE_SIDECAR_MISMATCH", "Codex's structured JSONL response and final-message sidecar did not match the exact connectivity marker."
        elif parsed.get("actual_model_conflict"):
            state, blocker_code, summary = "BLOCKED", "ACTUAL_MODEL_CONFLICT", "Codex returned conflicting effective-model identities."
        elif parsed.get("actual_model") and parsed.get("actual_model") != requested_model:
            supported_resolution = session.scalar(
                select(AIModel.id).where(
                    AIModel.execution_adapter == "codex_cli",
                    AIModel.provider_id == model.provider_id,
                    AIModel.provider_model_id == parsed.get("actual_model"),
                    AIModel.configuration_status != "disabled",
                )
            )
            state = "MODEL_UNAVAILABLE"
            if supported_resolution is None:
                blocker_code = "ACTUAL_MODEL_UNSUPPORTED"
                summary = "Codex resolved to a model that is not in the supported Local Codex catalog."
            else:
                blocker_code = "REQUESTED_MODEL_REROUTED"
                summary = (
                    "Codex resolved this probe to a different supported model. "
                    "Select that model explicitly and verify its connection before a real Run."
                )
        else:
            state = "READY_FOR_REAL_RUN"
            summary = (
                "Authentication and Provider connectivity were verified through a bounded "
                "Codex exec turn using the exact requested model argument."
            )

    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    actual_model = str(parsed.get("actual_model") or "")
    provider_reachable = bool(
        not timed_out
        and not prompt_detected
        and parsed.get("provider_reachable")
    )
    model_available = state == "READY_FOR_REAL_RUN"
    diagnostic = sanitize_result_value(
        {
            "policy": CONNECTIVITY_POLICY,
            "transport": "codex_exec_jsonl",
            "provider_probe_performed": bool(parsed.get("provider_probe_performed")),
            "requested_model_argument_verified": bool(
                sidecar_supported and not command_invalid
            ),
            "stdout_present": stdout_size > 0,
            "stderr_present": bool(stderr),
            "stdout_size": stdout_size,
            "stderr_size": len(stderr),
            "output_summary": _safe_output_summary(b"", stderr),
            "structured_lifecycle": {
                "thread_started": bool(parsed.get("thread_started")),
                "turn_started": bool(parsed.get("turn_started")),
                "turn_completed": bool(parsed.get("turn_completed")),
                "terminal_success": bool(parsed.get("terminal_success")),
                "response_ok": bool(parsed.get("response_ok")),
                "malformed_jsonl": bool(parsed.get("malformed_jsonl")),
                "lifecycle_conflict": bool(parsed.get("lifecycle_conflict")),
                "unexpected_action": bool(parsed.get("unexpected_action")),
                "actual_model_conflict": bool(parsed.get("actual_model_conflict")),
                "actual_model_source": str(parsed.get("actual_model_source") or ""),
                "same_thread_model_resolution": bool(
                    parsed.get("actual_model_source")
                ),
                "model_rerouted": bool(parsed.get("model_rerouted")),
                "message_count": int(parsed.get("message_count") or 0),
                "pending_approval": bool(parsed.get("pending_approval")),
            },
            "structured_response": {
                "schema_enabled": schema_enabled,
                "last_message_enabled": last_message_enabled,
                "sidecar_supported": sidecar_supported,
                "schema_unchanged": schema_unchanged,
                "last_message_present": last_message_present,
                "last_message_match": last_message_match,
                "schema_identity": canonical_sha256(
                    CONNECTIVITY_RESPONSE_SCHEMA
                ),
            },
            "user_config_isolated": True,
            "temporary_workspace_mutated": source_mutated,
            "app_server_probe_performed": False,
        }
    )
    digest_payload = {
        "policy": CONNECTIVITY_POLICY,
        "owner_id": owner_id,
        "model_id": model.id,
        "configuration_identity": model.stable_id or f"model-{model.id}",
        "requested_model": requested_model,
        "actual_model": actual_model,
        "readiness_state": state,
        "cli_version": detection.version or "",
        "executable_identity": executable_hash,
        "execution_context_identity": context_hash,
        "authentication_state": auth.state,
        "provider_reachable": provider_reachable,
        "model_available": model_available,
        "interactive_prompt_detected": prompt_detected,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "blocker_code": blocker_code,
        "diagnostic": diagnostic,
        "checked_at": checked_at.isoformat(),
        "nonce": uuid.uuid4().hex,
    }
    evidence = CodexConnectivityEvidence(
        evidence_id=f"cce-{uuid.uuid4().hex}",
        owner_id=owner_id,
        model_id=model.id,
        configuration_identity=model.stable_id or f"model-{model.id}",
        requested_model_identifier=requested_model,
        actual_model_identifier=actual_model,
        readiness_state=state,
        cli_installed=bool(detection.found),
        cli_version=str(detection.version or "")[:120],
        executable_identity=executable_hash,
        execution_context_identity=context_hash,
        authentication_state=auth.state,
        authentication_method=auth.method,
        credential_store=auth.credential_store,
        credential_store_accessible=auth.credential_store_accessible,
        provider_reachable=provider_reachable,
        model_available=model_available,
        interactive_prompt_detected=prompt_detected,
        timed_out=timed_out,
        exit_code=exit_code,
        duration_ms=duration_ms,
        blocker_code=blocker_code,
        safe_summary=summary,
        sanitized_command=sanitized_command,
        diagnostic_json=json.dumps(diagnostic, sort_keys=True, separators=(",", ":")),
        evidence_digest=canonical_sha256(digest_payload),
        checked_at=checked_at,
    )
    session.add(evidence)
    session.flush()
    return evidence
