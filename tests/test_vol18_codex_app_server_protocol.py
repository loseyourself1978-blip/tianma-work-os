from __future__ import annotations

import json

from twos_runtime.codex_protocol_0144 import (
    CODEX_CLI_VERSION,
    EXPERIMENTAL_SERVER_REQUEST_METHODS,
    INVALID_MESSAGE,
    KNOWN_SERVER_NOTIFICATION_METHODS,
    KNOWN_SERVER_REQUEST_METHODS,
    MessageKind,
    NotificationRisk,
    RESPONSE,
    SERVER_NOTIFICATION,
    SERVER_REQUEST,
    STABLE_JSON_SCHEMA_BUNDLE_SHA256,
    STABLE_SERVER_NOTIFICATION_METHODS,
    STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
    STABLE_SERVER_REQUEST_METHODS,
    STABLE_SERVER_REQUEST_SCHEMA_SHA256,
    TYPESCRIPT_COMPAT_SERVER_NOTIFICATION_METHODS,
    classify_jsonrpc_message,
    classify_notification_method,
    exact_protocol_schema_matches,
    is_known_server_notification,
    is_known_server_request,
    notification_is_critical,
    payload_shape_summary,
    schema_version_matches,
)


def test_exact_version_schema_constants_and_registries() -> None:
    assert CODEX_CLI_VERSION == "codex-cli 0.144.4"
    assert len(STABLE_JSON_SCHEMA_BUNDLE_SHA256) == 64
    assert len(STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256) == 64
    assert len(STABLE_SERVER_REQUEST_SCHEMA_SHA256) == 64
    assert len(STABLE_SERVER_NOTIFICATION_METHODS) == 68
    assert len(set(STABLE_SERVER_NOTIFICATION_METHODS)) == 68
    assert len(STABLE_SERVER_REQUEST_METHODS) == 10
    assert len(set(STABLE_SERVER_REQUEST_METHODS)) == 10


def test_complete_critical_generated_notification_variants_are_present() -> None:
    required = {
        "turn/started",
        "turn/completed",
        "item/started",
        "item/completed",
        "account/updated",
        "account/rateLimits/updated",
        "model/rerouted",
        "model/verification",
        "model/safetyBuffering/updated",
        "guardianWarning",
        "error",
    }
    assert required <= set(STABLE_SERVER_NOTIFICATION_METHODS)


def test_typescript_only_raw_response_compatibility_variant_is_explicit() -> None:
    assert TYPESCRIPT_COMPAT_SERVER_NOTIFICATION_METHODS == (
        "rawResponseItem/completed",
    )
    assert "rawResponseItem/completed" not in STABLE_SERVER_NOTIFICATION_METHODS
    assert "rawResponseItem/completed" in KNOWN_SERVER_NOTIFICATION_METHODS
    policy = classify_notification_method("rawResponseItem/completed")
    assert policy.known is True
    assert policy.registry == "stable_typescript_compat_0.144.4"


def test_stable_requests_exclude_experimental_current_time() -> None:
    assert "currentTime/read" in EXPERIMENTAL_SERVER_REQUEST_METHODS
    assert "currentTime/read" not in KNOWN_SERVER_REQUEST_METHODS
    assert "item/commandExecution/requestApproval" in KNOWN_SERVER_REQUEST_METHODS


def test_classifies_correlated_result_response() -> None:
    classification = classify_jsonrpc_message(
        {"id": 3, "result": {"turn": {"id": "turn-1"}}},
        outstanding_request_ids={3},
    )
    assert classification.kind is MessageKind.RESPONSE
    assert classification.kind.value == RESPONSE
    assert classification.request_id == 3


def test_classifies_correlated_error_response() -> None:
    classification = classify_jsonrpc_message(
        {"id": "thread-start", "error": {"code": -32000, "message": "blocked"}},
        outstanding_request_ids={"thread-start"},
    )
    assert classification.kind is MessageKind.RESPONSE
    assert classification.request_id == "thread-start"


def test_response_requires_exactly_one_result_or_error() -> None:
    both = classify_jsonrpc_message(
        {"id": 1, "result": {}, "error": {"code": -1, "message": "x"}},
        outstanding_request_ids={1},
    )
    neither = classify_jsonrpc_message({"id": 1}, outstanding_request_ids={1})
    assert both.kind.value == INVALID_MESSAGE
    assert both.reason == "ambiguous_response"
    assert neither.kind.value == INVALID_MESSAGE


def test_out_of_order_response_is_invalid() -> None:
    classification = classify_jsonrpc_message(
        {"id": 9, "result": {}}, outstanding_request_ids={1, 2, 3}
    )
    assert classification.kind is MessageKind.INVALID_MESSAGE
    assert classification.reason == "out_of_order_response"


def test_boolean_and_control_character_ids_are_not_safe() -> None:
    boolean_id = classify_jsonrpc_message(
        {"id": True, "result": {}}, outstanding_request_ids={True}
    )
    control_id = classify_jsonrpc_message(
        {"id": "bad\nidentity", "result": {}},
        outstanding_request_ids={"bad\nidentity"},
    )
    assert boolean_id.reason == "unsafe_response_id"
    assert control_id.reason == "unsafe_response_id"


def test_classifies_known_server_request() -> None:
    classification = classify_jsonrpc_message(
        {
            "id": "approval-1",
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": "thread-1"},
        }
    )
    assert classification.kind.value == SERVER_REQUEST
    assert is_known_server_request(classification.method)


def test_unknown_server_request_remains_a_request() -> None:
    classification = classify_jsonrpc_message(
        {"id": 17, "method": "future/request", "params": {}},
    )
    assert classification.kind is MessageKind.SERVER_REQUEST
    assert is_known_server_request(classification.method) is False


def test_classifies_known_and_unknown_server_notifications() -> None:
    known = classify_jsonrpc_message(
        {"method": "model/verification", "params": {"verifications": []}}
    )
    unknown = classify_jsonrpc_message(
        {"method": "telemetry/progress", "params": {"stage": "running"}}
    )
    assert known.kind.value == SERVER_NOTIFICATION
    assert is_known_server_notification(known.method)
    assert unknown.kind is MessageKind.SERVER_NOTIFICATION
    assert is_known_server_notification(unknown.method) is False


def test_unsafe_method_scalar_params_and_oversized_messages_are_invalid() -> None:
    unsafe_method = classify_jsonrpc_message(
        {"method": "bad method", "params": {}}
    )
    scalar_params = classify_jsonrpc_message(
        {"method": "future/event", "params": "raw secret"}
    )
    oversized = classify_jsonrpc_message(
        {"method": "future/event", "params": {"value": "x" * 65_000}}
    )
    assert unsafe_method.kind.value == INVALID_MESSAGE
    assert scalar_params.reason == "malformed_params"
    assert oversized.reason == "malformed_or_oversized"


def test_remote_control_status_is_explicitly_noncritical() -> None:
    policy = classify_notification_method("remoteControl/status/changed")
    assert policy.known is True
    assert policy.criticality is NotificationRisk.NON_CRITICAL
    assert notification_is_critical("remoteControl/status/changed") is False


def test_model_guardian_auth_and_terminal_notifications_are_critical() -> None:
    methods = (
        "model/verification",
        "guardianWarning",
        "account/updated",
        "turn/completed",
        "error",
    )
    assert all(notification_is_critical(method) for method in methods)


def test_unknown_notification_risk_is_fail_closed_only_for_critical_categories() -> None:
    optional = classify_notification_method("telemetry/progress")
    critical = classify_notification_method("future/modelVerification")
    assert optional.known is False
    assert optional.criticality is NotificationRisk.NON_CRITICAL
    assert critical.known is False
    assert critical.criticality is NotificationRisk.CRITICAL


def test_payload_shape_contains_only_field_names_and_types() -> None:
    secret = "super-secret-bearer-value"
    payload = {
        "threadId": "thread-123",
        "auth": {"bearer": secret, "valid": True},
        "verifications": ["trustedAccessForCyber"],
    }
    summary = payload_shape_summary(payload)
    encoded = json.dumps(summary, sort_keys=True)
    assert secret not in encoded
    assert "thread-123" not in encoded
    assert "trustedAccessForCyber" not in encoded
    assert "threadId" in encoded
    assert "bearer" in encoded
    assert '"type": "string"' in encoded
    assert '"type": "boolean"' in encoded


def test_payload_shape_is_bounded_and_sanitizes_unsafe_field_names() -> None:
    payload = {"secret\nvalue": "hidden"}
    payload.update({f"field-{index}": index for index in range(10)})
    summary = payload_shape_summary(payload, max_fields=3)
    encoded = json.dumps(summary, sort_keys=True)
    assert summary["truncated"] is True
    assert len(summary["fields"]) == 3
    assert "[unsafe-field-1]" in encoded
    assert "secret\\nvalue" not in encoded
    assert "hidden" not in encoded


def test_payload_shape_handles_depth_arrays_binary_and_cycles_without_values() -> None:
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    summary = payload_shape_summary(
        {"cycle": cycle, "items": [b"binary-secret", 3.5, None]},
        max_depth=4,
    )
    encoded = json.dumps(summary, sort_keys=True)
    assert "binary-secret" not in encoded
    assert '"type": "binary"' in encoded
    assert '"cycle": true' in encoded


def test_schema_version_match_requires_all_exact_identities() -> None:
    assert schema_version_matches(
        CODEX_CLI_VERSION,
        schema_bundle_sha256=STABLE_JSON_SCHEMA_BUNDLE_SHA256,
    )
    assert exact_protocol_schema_matches(
        CODEX_CLI_VERSION,
        STABLE_JSON_SCHEMA_BUNDLE_SHA256,
        STABLE_SERVER_NOTIFICATION_SCHEMA_SHA256,
        STABLE_SERVER_REQUEST_SCHEMA_SHA256,
    )
    assert not schema_version_matches(
        "codex-cli 0.144.5",
        schema_bundle_sha256=STABLE_JSON_SCHEMA_BUNDLE_SHA256,
    )
    assert not schema_version_matches(
        CODEX_CLI_VERSION,
        schema_bundle_sha256="0" * 64,
    )
    assert not schema_version_matches(
        CODEX_CLI_VERSION,
        schema_bundle_sha256=STABLE_JSON_SCHEMA_BUNDLE_SHA256,
        server_notification_sha256="f" * 64,
    )
