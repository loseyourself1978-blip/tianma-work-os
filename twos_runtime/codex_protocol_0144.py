"""Version-bound Codex app-server protocol facts for ``codex-cli 0.144.4``.

The registries and digests in this module were generated locally from the
configured Codex executable.  They are intentionally data-only: importing the
module never starts Codex and never performs a Provider request.

There is one generator inconsistency worth preserving explicitly.  The
standalone stable ``ServerNotification.json`` union contains 68 methods, while
the stable TypeScript ``ServerNotification`` union additionally contains
``rawResponseItem/completed``.  The compatibility method is accepted as a
known notification, but it is not counted as part of the JSON registry digest.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Collection, Iterable, Mapping


CODEX_CLI_VERSION = "codex-cli 0.144.4"
CODEX_CLI_SEMVER = "0.144.4"

# SHA-256 of the files emitted by the exact configured executable.  The bundle
# digest is for codex_app_server_protocol.schemas.json, not an archive whose
# metadata could make the digest non-deterministic.
STABLE_JSON_SCHEMA_BUNDLE_SHA256 = (
    "000f4e8b3331fce471cfa5d81c7676b7033c780dbf1198f0958933eb09f6d84a"
)
STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256 = (
    "67669e13a8af9449da30acdbd83a6108fd54ed92b79849dee381aece1521937f"
)
STABLE_SERVER_REQUEST_SCHEMA_SHA256 = (
    "7c8a2c6fe03d6afdf8a83f91fa5eb55e7ae630fe2e43a167691ab917dccc9556"
)


# Generated order is retained so audits can compare the local schema without
# first normalizing it to a set.
STABLE_SERVER_NOTIFICATION_METHODS = (
    "error",
    "thread/started",
    "thread/status/changed",
    "thread/archived",
    "thread/deleted",
    "thread/unarchived",
    "thread/closed",
    "skills/changed",
    "thread/name/updated",
    "thread/goal/updated",
    "thread/goal/cleared",
    "thread/settings/updated",
    "thread/tokenUsage/updated",
    "turn/started",
    "hook/started",
    "turn/completed",
    "hook/completed",
    "turn/diff/updated",
    "turn/plan/updated",
    "item/started",
    "item/autoApprovalReview/started",
    "item/autoApprovalReview/completed",
    "item/completed",
    "item/agentMessage/delta",
    "item/plan/delta",
    "command/exec/outputDelta",
    "process/outputDelta",
    "process/exited",
    "item/commandExecution/outputDelta",
    "item/commandExecution/terminalInteraction",
    "item/fileChange/outputDelta",
    "item/fileChange/patchUpdated",
    "serverRequest/resolved",
    "item/mcpToolCall/progress",
    "mcpServer/oauthLogin/completed",
    "mcpServer/startupStatus/updated",
    "account/updated",
    "account/rateLimits/updated",
    "app/list/updated",
    "remoteControl/status/changed",
    "externalAgentConfig/import/progress",
    "externalAgentConfig/import/completed",
    "fs/changed",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/summaryPartAdded",
    "item/reasoning/textDelta",
    "thread/compacted",
    "model/rerouted",
    "model/verification",
    "turn/moderationMetadata",
    "model/safetyBuffering/updated",
    "warning",
    "guardianWarning",
    "deprecationNotice",
    "configWarning",
    "fuzzyFileSearch/sessionUpdated",
    "fuzzyFileSearch/sessionCompleted",
    "thread/realtime/started",
    "thread/realtime/itemAdded",
    "thread/realtime/transcript/delta",
    "thread/realtime/transcript/done",
    "thread/realtime/outputAudio/delta",
    "thread/realtime/sdp",
    "thread/realtime/error",
    "thread/realtime/closed",
    "windows/worldWritableWarning",
    "windowsSandbox/setupCompleted",
    "account/login/completed",
)

# Present in generated stable TypeScript and in bundle definitions, but absent
# from the standalone stable ServerNotification.json oneOf registry.
TYPESCRIPT_COMPAT_SERVER_NOTIFICATION_METHODS = (
    "rawResponseItem/completed",
)

KNOWN_SERVER_NOTIFICATION_METHODS = frozenset(
    STABLE_SERVER_NOTIFICATION_METHODS
    + TYPESCRIPT_COMPAT_SERVER_NOTIFICATION_METHODS
)

STABLE_SERVER_REQUEST_METHODS = (
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
    "item/permissions/requestApproval",
    "item/tool/call",
    "account/chatgptAuthTokens/refresh",
    "attestation/generate",
    "applyPatchApproval",
    "execCommandApproval",
)
KNOWN_SERVER_REQUEST_METHODS = frozenset(STABLE_SERVER_REQUEST_METHODS)

# ``currentTime/read`` exists only in the --experimental ServerRequest schema.
# The read-only TWOS probe does not opt into experimentalApi and therefore does
# not advertise support for this request.
EXPERIMENTAL_SERVER_REQUEST_METHODS = frozenset({"currentTime/read"})


class MessageKind(str, Enum):
    RESPONSE = "RESPONSE"
    SERVER_REQUEST = "SERVER_REQUEST"
    SERVER_NOTIFICATION = "SERVER_NOTIFICATION"
    INVALID_MESSAGE = "INVALID_MESSAGE"


RESPONSE = MessageKind.RESPONSE.value
SERVER_REQUEST = MessageKind.SERVER_REQUEST.value
SERVER_NOTIFICATION = MessageKind.SERVER_NOTIFICATION.value
INVALID_MESSAGE = MessageKind.INVALID_MESSAGE.value


@dataclass(frozen=True)
class MessageClassification:
    kind: MessageKind
    method: str | None = None
    request_id: str | int | None = None
    reason: str = ""

    @property
    def is_valid(self) -> bool:
        return self.kind is not MessageKind.INVALID_MESSAGE


class NotificationRisk(str, Enum):
    CRITICAL = "CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


@dataclass(frozen=True)
class NotificationMethodClassification:
    method: str
    known: bool
    criticality: NotificationRisk
    registry: str

    @property
    def critical(self) -> bool:
        return self.criticality is NotificationRisk.CRITICAL


MAX_JSON_RPC_MESSAGE_BYTES = 64_000
MAX_JSON_RPC_ID_LENGTH = 240
MAX_JSON_RPC_METHOD_LENGTH = 240
MAX_PAYLOAD_SHAPE_DEPTH = 4
MAX_PAYLOAD_SHAPE_FIELDS = 64
MAX_PAYLOAD_SHAPE_ARRAY_ITEMS = 8
MAX_PAYLOAD_FIELD_NAME_LENGTH = 80

_SAFE_METHOD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


def is_safe_request_id(value: object) -> bool:
    """Return whether a JSON-RPC id can be compared and audited safely."""

    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return -(2**63) <= value <= 2**63 - 1
    if not isinstance(value, str):
        return False
    return (
        0 < len(value) <= MAX_JSON_RPC_ID_LENGTH
        and _CONTROL_CHARACTER.search(value) is None
    )


def is_safe_method_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_JSON_RPC_METHOD_LENGTH
        and _SAFE_METHOD.fullmatch(value) is not None
    )


def _request_id_key(value: object) -> tuple[str, str | int] | None:
    if not is_safe_request_id(value):
        return None
    if isinstance(value, int):
        return ("integer", value)
    return ("string", value)


def _bounded_json_message(message: object) -> bool:
    try:
        serialized = json.dumps(
            message,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return False
    return len(serialized) <= MAX_JSON_RPC_MESSAGE_BYTES


def _valid_params(params: object) -> bool:
    # Codex-generated params are objects.  Arrays remain valid JSON-RPC params
    # for forward-compatible messages, but scalars are treated as malformed.
    return isinstance(params, (Mapping, list))


def _valid_error(error: object) -> bool:
    if not isinstance(error, Mapping):
        return False
    code = error.get("code")
    message = error.get("message")
    return (
        isinstance(code, int)
        and not isinstance(code, bool)
        and -(2**63) <= code <= 2**63 - 1
        and isinstance(message, str)
        and len(message) <= 4_096
    )


def classify_jsonrpc_message(
    message: object,
    *,
    outstanding_request_ids: Collection[str | int] | Iterable[str | int] = (),
) -> MessageClassification:
    """Classify one bounded app-server JSON-RPC message.

    Responses are valid only when they contain exactly one of ``result`` and
    ``error`` and correlate to a currently outstanding client request.  A
    method plus id is a server request; a method without id is a notification.
    Ambiguous or unsafe messages are classified as ``INVALID_MESSAGE``.
    """

    if not isinstance(message, Mapping):
        return MessageClassification(MessageKind.INVALID_MESSAGE, reason="not_object")
    if not _bounded_json_message(message):
        return MessageClassification(
            MessageKind.INVALID_MESSAGE, reason="malformed_or_oversized"
        )

    has_id = "id" in message
    has_method = "method" in message
    has_result = "result" in message
    has_error = "error" in message

    if has_result or has_error:
        if has_method or not has_id or has_result == has_error:
            return MessageClassification(
                MessageKind.INVALID_MESSAGE, reason="ambiguous_response"
            )
        request_id = message.get("id")
        request_key = _request_id_key(request_id)
        if request_key is None:
            return MessageClassification(
                MessageKind.INVALID_MESSAGE, reason="unsafe_response_id"
            )
        outstanding_keys = {
            key
            for key in (_request_id_key(value) for value in outstanding_request_ids)
            if key is not None
        }
        if request_key not in outstanding_keys:
            return MessageClassification(
                MessageKind.INVALID_MESSAGE,
                request_id=request_id,
                reason="out_of_order_response",
            )
        if has_error and not _valid_error(message.get("error")):
            return MessageClassification(
                MessageKind.INVALID_MESSAGE,
                request_id=request_id,
                reason="malformed_error",
            )
        return MessageClassification(MessageKind.RESPONSE, request_id=request_id)

    if not has_method:
        return MessageClassification(
            MessageKind.INVALID_MESSAGE, reason="missing_method_or_response"
        )
    method = message.get("method")
    if not is_safe_method_name(method):
        return MessageClassification(
            MessageKind.INVALID_MESSAGE, reason="unsafe_method"
        )
    if "params" not in message or not _valid_params(message.get("params")):
        return MessageClassification(
            MessageKind.INVALID_MESSAGE, method=method, reason="malformed_params"
        )

    if has_id:
        request_id = message.get("id")
        if _request_id_key(request_id) is None:
            return MessageClassification(
                MessageKind.INVALID_MESSAGE,
                method=method,
                reason="unsafe_server_request_id",
            )
        return MessageClassification(
            MessageKind.SERVER_REQUEST, method=method, request_id=request_id
        )
    return MessageClassification(MessageKind.SERVER_NOTIFICATION, method=method)


# A compatibility alias keeps the call site concise without hiding that this
# function classifies JSON-RPC, rather than arbitrary process output.
classify_message = classify_jsonrpc_message


def is_known_server_notification(method: object) -> bool:
    return isinstance(method, str) and method in KNOWN_SERVER_NOTIFICATION_METHODS


def is_known_server_request(method: object) -> bool:
    return isinstance(method, str) and method in KNOWN_SERVER_REQUEST_METHODS


# Events whose semantics may affect authentication, approvals, safety, source
# mutation, terminal truth, model resolution, or result integrity.
KNOWN_CRITICAL_NOTIFICATION_METHODS = frozenset(
    {
        "error",
        "thread/status/changed",
        "turn/started",
        "turn/completed",
        "hook/started",
        "hook/completed",
        "item/started",
        "item/autoApprovalReview/started",
        "item/autoApprovalReview/completed",
        "item/completed",
        "command/exec/outputDelta",
        "process/outputDelta",
        "process/exited",
        "item/commandExecution/outputDelta",
        "item/commandExecution/terminalInteraction",
        "item/fileChange/outputDelta",
        "item/fileChange/patchUpdated",
        "serverRequest/resolved",
        "item/mcpToolCall/progress",
        "mcpServer/oauthLogin/completed",
        "mcpServer/startupStatus/updated",
        "account/updated",
        "account/rateLimits/updated",
        "fs/changed",
        "model/rerouted",
        "model/verification",
        "turn/moderationMetadata",
        "model/safetyBuffering/updated",
        "guardianWarning",
        "thread/realtime/error",
        "windows/worldWritableWarning",
        "windowsSandbox/setupCompleted",
        "account/login/completed",
    }
)

KNOWN_NON_CRITICAL_NOTIFICATION_METHODS = (
    KNOWN_SERVER_NOTIFICATION_METHODS - KNOWN_CRITICAL_NOTIFICATION_METHODS
)

_UNKNOWN_CRITICAL_SEGMENTS = (
    "auth",
    "account",
    "login",
    "approval",
    "permission",
    "guardian",
    "safety",
    "model",
    "verification",
    "moderation",
    "terminal",
    "completed",
    "failed",
    "failure",
    "error",
    "turn/",
    "serverrequest",
    "commandexecution",
    "filechange",
    "mcpserver",
    "process/exited",
)


def classify_notification_method(method: str) -> NotificationMethodClassification:
    if method in STABLE_SERVER_NOTIFICATION_METHODS:
        return NotificationMethodClassification(
            method=method,
            known=True,
            criticality=(
                NotificationRisk.CRITICAL
                if method in KNOWN_CRITICAL_NOTIFICATION_METHODS
                else NotificationRisk.NON_CRITICAL
            ),
            registry="stable_json_0.144.4",
        )
    if method in TYPESCRIPT_COMPAT_SERVER_NOTIFICATION_METHODS:
        return NotificationMethodClassification(
            method=method,
            known=True,
            criticality=NotificationRisk.NON_CRITICAL,
            registry="stable_typescript_compat_0.144.4",
        )

    folded = method.casefold()
    critical = any(segment in folded for segment in _UNKNOWN_CRITICAL_SEGMENTS)
    return NotificationMethodClassification(
        method=method,
        known=False,
        criticality=(
            NotificationRisk.CRITICAL
            if critical
            else NotificationRisk.NON_CRITICAL
        ),
        registry="unknown",
    )


def notification_is_critical(method: str) -> bool:
    return classify_notification_method(method).critical


def _safe_field_name(value: object, index: int) -> str:
    if isinstance(value, str) and _SAFE_FIELD_NAME.fullmatch(value):
        return value
    return f"[unsafe-field-{index}]"


def payload_shape_summary(
    payload: object,
    *,
    max_depth: int = MAX_PAYLOAD_SHAPE_DEPTH,
    max_fields: int = MAX_PAYLOAD_SHAPE_FIELDS,
    max_array_items: int = MAX_PAYLOAD_SHAPE_ARRAY_ITEMS,
) -> dict[str, Any]:
    """Return a bounded field-name/type summary containing no scalar values."""

    depth_limit = max(0, min(int(max_depth), 12))
    field_limit = max(1, min(int(max_fields), 512))
    item_limit = max(1, min(int(max_array_items), 64))
    remaining_fields = [field_limit]
    seen: set[int] = set()

    def summarize(value: object, depth: int) -> dict[str, Any]:
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number" if math.isfinite(value) else "nonFiniteNumber"}
        if isinstance(value, str):
            return {"type": "string"}
        if isinstance(value, (bytes, bytearray, memoryview)):
            return {"type": "binary"}
        if depth >= depth_limit:
            return {"type": "container", "truncated": True}

        identity = id(value)
        if isinstance(value, Mapping):
            if identity in seen:
                return {"type": "object", "cycle": True}
            seen.add(identity)
            fields: list[dict[str, Any]] = []
            truncated = False
            try:
                for index, (key, child) in enumerate(value.items(), start=1):
                    if remaining_fields[0] <= 0:
                        truncated = True
                        break
                    remaining_fields[0] -= 1
                    fields.append(
                        {
                            "name": _safe_field_name(key, index),
                            "shape": summarize(child, depth + 1),
                        }
                    )
            finally:
                seen.remove(identity)
            result: dict[str, Any] = {"type": "object", "fields": fields}
            if truncated:
                result["truncated"] = True
            return result

        if isinstance(value, (list, tuple)):
            if identity in seen:
                return {"type": "array", "cycle": True}
            seen.add(identity)
            items: list[dict[str, Any]] = []
            truncated = False
            try:
                for index, child in enumerate(value):
                    if index >= item_limit or remaining_fields[0] <= 0:
                        truncated = True
                        break
                    remaining_fields[0] -= 1
                    items.append(summarize(child, depth + 1))
            finally:
                seen.remove(identity)
            result = {"type": "array", "items": items}
            if truncated:
                result["truncated"] = True
            return result

        return {"type": "unsupported"}

    return summarize(payload, 0)


# Explicit name used by callers that persist the sanitized shape in audit data.
sanitize_payload_shape = payload_shape_summary


def schema_version_matches(
    cli_version: str,
    *,
    schema_bundle_sha256: str,
    server_notification_sha256: str = STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
    server_request_sha256: str = STABLE_SERVER_REQUEST_SCHEMA_SHA256,
) -> bool:
    """Fail closed unless the CLI and all stable schema identities match."""

    return (
        cli_version.strip() == CODEX_CLI_VERSION
        and schema_bundle_sha256.casefold() == STABLE_JSON_SCHEMA_BUNDLE_SHA256
        and server_notification_sha256.casefold()
        == STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256
        and server_request_sha256.casefold() == STABLE_SERVER_REQUEST_SCHEMA_SHA256
    )


def exact_protocol_schema_matches(
    cli_version: str,
    schema_bundle_sha256: str,
    server_notification_sha256: str,
    server_request_sha256: str,
) -> bool:
    return schema_version_matches(
        cli_version,
        schema_bundle_sha256=schema_bundle_sha256,
        server_notification_sha256=server_notification_sha256,
        server_request_sha256=server_request_sha256,
    )
