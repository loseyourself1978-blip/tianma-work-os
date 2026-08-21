from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from twos_runtime.codex_exec_bridge import (
    CodexExecBridgeError,
    ExecutionHandle,
    ExecutionIdentity,
    load_final_message,
    load_jsonl_final_message_candidate,
    prepare_execution,
    run_execution,
)


def _identity(run_id: int = 1) -> ExecutionIdentity:
    return ExecutionIdentity(
        owner_id=1,
        run_id=run_id,
        task_id=2,
        task_version=1,
        pack_id=3,
        pack_version=1,
        coding_assignment_id=4,
        coding_assignment_version=1,
        verification_assignment_id=5,
        verification_assignment_version=1,
        routing_snapshot_identity="canonical-routing",
        source_snapshot_identity="canonical-source",
        connectivity_evidence_identity="canonical-connectivity",
        requested_model_identifier="fixture-model",
        executable_fingerprint="canonical-executable",
        execution_location_identity="canonical-location",
        source_remote_fingerprint=hashlib.sha256(b"remote").hexdigest(),
        git_boundary_fingerprint=hashlib.sha256(b"git").hexdigest(),
        workspace_snapshot_digest=hashlib.sha256(b"workspace").hexdigest(),
    )


def _prepare(
    tmp_path: Path,
    source: str,
    *,
    phase_key: str = "coding-canonical",
    run_id: int = 1,
) -> ExecutionHandle:
    root = tmp_path / phase_key
    root.mkdir(mode=0o700, parents=True)
    working = root / "working"
    working.mkdir(mode=0o700)
    executable = root / "fixture.py"
    executable.write_text(source, encoding="utf-8")
    executable.chmod(0o700)
    final_message = root / "spool" / phase_key / "final-message.txt"
    return prepare_execution(
        root / "spool",
        phase_key=phase_key,
        phase="coding",
        identity=_identity(run_id),
        argv=(
            str(Path(sys.executable).resolve(strict=True)),
            str(executable),
            str(final_message),
        ),
        stdin_payload=b"approved\n",
        working_directory=working,
        timeout_seconds=3.0,
        heartbeat_interval_seconds=0.02,
    )


def _coding_contract(summary: str) -> dict[str, str]:
    return {
        "schema": "twos.coding_handoff.v1",
        "status": "completed",
        "summary": summary,
    }


def test_last_structurally_valid_message_before_terminal_is_canonical(
    tmp_path: Path,
) -> None:
    first = _coding_contract("first complete handoff")
    final = _coding_contract("canonical final handoff")
    sidecar = {
        "summary": final["summary"],
        "status": "completed",
        "schema": "twos.coding_handoff.v1",
    }
    source = f'''
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(
    json.dumps({sidecar!r}, ensure_ascii=False, indent=2), encoding="utf-8"
)
events = [
    {{"type":"thread.started","thread_id":"thread-canonical"}},
    {{"type":"turn.started","turn_id":"turn-canonical"}},
    {{"type":"item.completed","turn_id":"turn-canonical","item":{{"id":"progress","type":"agent_message","text":"progress update"}}}},
    {{"type":"error","message":"recoverable observation without fatal flag"}},
    {{"type":"item.completed","turn_id":"turn-canonical","item":{{"id":"first","type":"agent_message","text":json.dumps({first!r}, separators=(",", ":"))}}}},
    {{"type":"item.completed","turn_id":"turn-canonical","item":{{"id":"continuation","type":"agent_message","text":"presentation-only continuation"}}}},
    {{"type":"item.completed","turn_id":"turn-canonical","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}},
    {{"type":"turn.completed","turn_id":"turn-canonical"}},
]
for event in events:
    print(json.dumps(event, separators=(",", ":")), flush=True)
'''
    handle = _prepare(tmp_path, source)

    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "COMPLETED"
    jsonl = receipt["stdout_jsonl"]
    assert jsonl["agent_message_count"] == 4
    assert jsonl["fatal_error_count"] == 0
    assert jsonl["last_agent_message_event_sequence"] == 7
    assert jsonl["last_agent_message_selection"] == (
        "LAST_STRUCTURALLY_VALID_BEFORE_TERMINAL"
    )
    assert jsonl["last_agent_message_schema_status"] == "VALID"
    assert receipt["final_message"]["canonicalization"] == "JSON"
    assert receipt["final_message"]["schema_status"] == "VALID"
    assert receipt["final_message"]["matches_last_agent_message"] is True
    assert receipt["final_message"]["representation_warning"] == (
        "RESULT_REPRESENTATION_NORMALIZED"
    )
    assert receipt["outcome_facts"]["warnings"] == [
        "RESULT_REPRESENTATION_NORMALIZED"
    ]
    assert (
        receipt["final_message"]["normalized_sha256"]
        != jsonl["last_agent_message_raw_sha256"]
    )
    assert json.loads(load_final_message(handle) or "{}") == final


def test_historical_track_b_sequence_selects_message_20_before_terminal_21(
    tmp_path: Path,
) -> None:
    """Lock the observed failed-acceptance topology without rewriting it."""

    final = _coding_contract("Phase 18.5A automatic intake passed.")
    source = f'''
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(
    json.dumps({final!r}, indent=2, sort_keys=True), encoding="utf-8"
)
events = [
    {{"type":"thread.started","thread_id":"historical-thread"}},
    {{"type":"turn.started"}},
    {{"type":"error","message":"reconnect retry 2/5"}},
    {{"type":"error","message":"reconnect retry 3/5"}},
    {{"type":"error","message":"reconnect retry 4/5"}},
    {{"type":"error","message":"reconnect retry 5/5"}},
    {{"type":"item.completed","item":{{"id":"plan","type":"plan","text":"safe plan status"}}}},
    {{"type":"item.completed","item":{{"id":"item_1","type":"agent_message","text":"progress message one"}}}},
    {{"type":"item.started","item":{{"id":"command-1","type":"command_execution"}}}},
    {{"type":"item.completed","item":{{"id":"command-1","type":"command_execution","exit_code":0}}}},
    {{"type":"item.started","item":{{"id":"command-2","type":"command_execution"}}}},
    {{"type":"item.completed","item":{{"id":"command-2","type":"command_execution","exit_code":0}}}},
    {{"type":"item.started","item":{{"id":"command-3","type":"command_execution"}}}},
    {{"type":"item.completed","item":{{"id":"command-3","type":"command_execution","exit_code":0}}}},
    {{"type":"item.completed","item":{{"id":"item_5","type":"agent_message","text":"progress message two"}}}},
    {{"type":"item.started","item":{{"id":"file-1","type":"file_change"}}}},
    {{"type":"item.completed","item":{{"id":"file-1","type":"file_change"}}}},
    {{"type":"item.started","item":{{"id":"validation-1","type":"command_execution"}}}},
    {{"type":"item.completed","item":{{"id":"validation-1","type":"command_execution","exit_code":0}}}},
    {{"type":"item.completed","item":{{"id":"item_8","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}},
    {{"type":"turn.completed"}},
]
for event in events:
    print(json.dumps(event, separators=(",", ":")), flush=True)
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    jsonl = receipt["stdout_jsonl"]
    assert jsonl["event_count"] == 21
    assert jsonl["agent_message_count"] == 3
    assert jsonl["fatal_error_count"] == 0
    assert jsonl["last_agent_message_event_sequence"] == 20
    assert jsonl["last_terminal_event_sequence"] == 21
    assert jsonl["last_agent_message_schema_status"] == "VALID"
    assert receipt["final_message"]["matches_last_agent_message"] is True
    assert receipt["terminal_blocker_code"] == ""


def test_later_completed_continuation_displaces_earlier_schema_result(
    tmp_path: Path,
) -> None:
    final = _coding_contract("earlier schema result")
    source = f'''
import json
import pathlib
import sys
message = json.dumps({final!r}, separators=(",", ":"))
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-later"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-later"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-later","item":{{"id":"schema","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-later","item":{{"id":"continuation","type":"agent_message","text":"later continuation"}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-later"}}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_message_jsonl_mismatch"
    assert receipt["terminal_blocker_code"] == "FINAL_RESULT_SEMANTIC_MISMATCH"
    assert receipt["stdout_jsonl"]["last_agent_message_schema_status"] == (
        "NOT_JSON"
    )
    assert receipt["stdout_jsonl"]["last_agent_message_event_sequence"] == 4


def test_missing_sidecar_recovers_selected_schema_result_with_synthetic_turn_binding(
    tmp_path: Path,
) -> None:
    final = _coding_contract("synthetic identity recovery")
    source = f'''
import json
print(json.dumps({{"type":"thread.started"}}))
print(json.dumps({{"type":"turn.started"}}))
print(json.dumps({{"type":"item.completed","item":{{"id":"progress","type":"agent_message","text":"progress"}}}}))
print(json.dumps({{"type":"item.completed","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}))
print(json.dumps({{"type":"turn.completed"}}))
'''
    handle = _prepare(tmp_path, source)

    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_message_missing"
    assert receipt["terminal_blocker_code"] == "FINAL_AGENT_MESSAGE_UNAVAILABLE"
    assert receipt["outcome_facts"]["terminal_success"] is True
    assert receipt["outcome_facts"]["jsonl_recovery_candidate"] is True
    jsonl = receipt["stdout_jsonl"]
    assert jsonl["last_agent_message_turn_identity"].startswith("synthetic-turn:")
    assert jsonl["last_terminal_turn_identity"] == jsonl[
        "last_agent_message_turn_identity"
    ]
    assert json.loads(load_jsonl_final_message_candidate(handle) or "{}") == final
    assert receipt["final_message"]["jsonl_recovery"]["schema_validation"] == (
        "PHASE_SCHEMA_VALID"
    )
    binding_identity = receipt["final_message"]["ticket_binding_identity"]
    assert re.fullmatch(r"[0-9a-f]{64}", binding_identity)


def test_text_canonicalization_normalizes_line_endings_without_collapsing_content(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_bytes(b"  line one\r\nline two  \r\n")
events = [
    {"type":"thread.started","thread_id":"thread-text"},
    {"type":"turn.started","turn_id":"turn-text"},
    {"type":"item.completed","turn_id":"turn-text","item":{"id":"text","type":"agent_message","text":"  line one\nline two  "}},
    {"type":"turn.completed","turn_id":"turn-text"},
]
for event in events:
    print(json.dumps(event), flush=True)
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["final_message"]["canonicalization"] == "TEXT"
    assert receipt["final_message"]["schema_status"] == "NOT_JSON"
    assert receipt["final_message"]["matches_last_agent_message"] is True
    assert receipt["final_message"]["representation_warning"] == (
        "RESULT_REPRESENTATION_NORMALIZED"
    )


def test_missing_sidecar_bom_pretty_json_recovery_uses_canonical_digest(
    tmp_path: Path,
) -> None:
    final = _coding_contract("pretty recovery")
    reordered = {
        "summary": final["summary"],
        "status": final["status"],
        "schema": final["schema"],
    }
    source = f'''
import json
message = "\\ufeff" + json.dumps({reordered!r}, indent=2)
print(json.dumps({{"type":"thread.started","thread_id":"thread-pretty"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-pretty"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-pretty","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-pretty"}}))
'''
    handle = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["outcome_facts"]["jsonl_recovery_candidate"] is True
    recovered = load_jsonl_final_message_candidate(handle)
    assert isinstance(recovered, str)
    assert json.loads(recovered.lstrip("\ufeff")) == final
    recovery = receipt["final_message"]["jsonl_recovery"]
    assert recovery["selected_schema_status"] == "VALID"
    assert recovery["sidecar_settlement_status"] == "MISSING"
    assert recovery["genuine_missing"] is True


def test_meaningful_plain_text_whitespace_mismatch_is_blocked(
    tmp_path: Path,
) -> None:
    source = r'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("result ", encoding="utf-8")
print(json.dumps({"type":"thread.started","thread_id":"thread-space"}))
print(json.dumps({"type":"turn.started","turn_id":"turn-space"}))
print(json.dumps({"type":"item.completed","turn_id":"turn-space","item":{"id":"text","type":"agent_message","text":"result"}}))
print(json.dumps({"type":"turn.completed","turn_id":"turn-space"}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_message_jsonl_mismatch"
    assert receipt["terminal_blocker_code"] == "FINAL_RESULT_SEMANTIC_MISMATCH"
    assert receipt["final_message"]["matches_last_agent_message"] is False


def test_json_canonicalization_accepts_one_leading_bom_and_insignificant_layout(
    tmp_path: Path,
) -> None:
    final = _coding_contract("BOM JSON handoff")
    sidecar = {
        "summary": final["summary"],
        "status": final["status"],
        "schema": final["schema"],
    }
    source = f'''
import json
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text(
    "\\ufeff" + json.dumps({sidecar!r}, indent=2), encoding="utf-8"
)
message = json.dumps({final!r}, separators=(",", ":"))
print(json.dumps({{"type":"thread.started","thread_id":"thread-bom"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-bom"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-bom","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-bom"}}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["final_message"]["canonicalization"] == "JSON"
    assert receipt["final_message"]["schema_status"] == "VALID"
    assert receipt["final_message"]["matches_last_agent_message"] is True
    assert receipt["final_message"]["representation_warning"] == (
        "RESULT_REPRESENTATION_NORMALIZED"
    )


def test_json_with_trailing_non_whitespace_is_rejected_without_repair(
    tmp_path: Path,
) -> None:
    final = json.dumps(_coding_contract("invalid trailing payload")) + " trailing"
    source = f'''
import json
import pathlib
import sys
message = {final!r}
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-trailing"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-trailing"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-trailing","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-trailing"}}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_result_schema_invalid"
    assert receipt["terminal_blocker_code"] == "FINAL_RESULT_SCHEMA_INVALID"
    assert receipt["stdout_jsonl"]["last_agent_message_schema_status"] == (
        "INVALID_JSON"
    )
    assert receipt["final_message"]["canonicalization"] == "TEXT"


def test_exact_raw_result_equality_has_no_representation_warning(
    tmp_path: Path,
) -> None:
    final = _coding_contract("exact raw equality")
    source = f'''
import json
import pathlib
import sys
message = json.dumps({final!r}, separators=(",", ":"))
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-exact"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-exact"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-exact","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-exact"}}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "COMPLETED"
    assert receipt["final_message"]["representation_warning"] == ""
    assert receipt["outcome_facts"]["warnings"] == []
    assert receipt["terminal_blocker_code"] == ""
    assert receipt["classifier_rule"] == "codex-jsonl-0.144.4.v2"
    assert receipt["final_result_selection_rule"] == (
        "last-structurally-valid-before-terminal.v1"
    )
    assert receipt["canonicalization_rule"] == (
        "twos.final-result-canonicalization.v1"
    )


@pytest.mark.parametrize(
    "case",
    ["duplicate", "duplicate_item", "wrong_turn", "after_terminal", "before_turn"],
)
def test_duplicate_wrong_and_out_of_order_lifecycle_is_rejected(
    tmp_path: Path,
    case: str,
) -> None:
    final = _coding_contract("must remain blocked")
    terminal = '{"type":"turn.completed","turn_id":"turn-one"}'
    if case == "duplicate":
        events = [
            '{"type":"thread.started","thread_id":"thread-one"}',
            '{"type":"turn.started","turn_id":"turn-one"}',
            f'{{"type":"item.completed","turn_id":"turn-one","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}',
            terminal,
            terminal,
        ]
    elif case == "duplicate_item":
        events = [
            '{"type":"thread.started","thread_id":"thread-one"}',
            '{"type":"turn.started","turn_id":"turn-one"}',
            f'{{"type":"item.completed","turn_id":"turn-one","item":{{"id":"same-item","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}',
            '{"type":"item.completed","turn_id":"turn-one","item":{"id":"same-item","type":"agent_message","text":"duplicate item continuation"}}',
            terminal,
        ]
    elif case == "wrong_turn":
        events = [
            '{"type":"thread.started","thread_id":"thread-one"}',
            '{"type":"turn.started","turn_id":"turn-one"}',
            f'{{"type":"item.completed","turn_id":"turn-one","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}',
            '{"type":"turn.completed","turn_id":"turn-two"}',
        ]
    elif case == "after_terminal":
        events = [
            '{"type":"thread.started","thread_id":"thread-one"}',
            '{"type":"turn.started","turn_id":"turn-one"}',
            f'{{"type":"item.completed","turn_id":"turn-one","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}',
            terminal,
            '{"type":"item.completed","turn_id":"turn-one","item":{"id":"late","type":"agent_message","text":"late continuation"}}',
        ]
    else:
        events = [
            '{"type":"thread.started","thread_id":"thread-one"}',
            '{"type":"item.completed","turn_id":"turn-one","item":{"id":"early","type":"agent_message","text":"too early"}}',
            '{"type":"turn.started","turn_id":"turn-one"}',
            f'{{"type":"item.completed","turn_id":"turn-one","item":{{"id":"final","type":"agent_message","text":json.dumps({final!r}, separators=(",", ":"))}}}}',
            terminal,
        ]
    source = f'''
import json
import pathlib
import sys
final = {final!r}
pathlib.Path(sys.argv[1]).write_text(json.dumps(final), encoding="utf-8")
events = [{", ".join(events)}]
for event in events:
    print(json.dumps(event), flush=True)
'''

    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "terminal_event_contradiction"
    assert receipt["outcome_facts"]["terminal_contradiction"] is True
    assert receipt["stdout_jsonl"]["lifecycle_conflict_count"] >= 1
    if case == "duplicate_item":
        assert "DUPLICATE_AGENT_MESSAGE_ITEM_ID" in receipt["stdout_jsonl"][
            "lifecycle_conflict_codes"
        ]


def test_recognized_contract_with_invalid_status_is_not_published_as_success(
    tmp_path: Path,
) -> None:
    invalid = {
        "schema": "twos.coding_handoff.v1",
        "status": "failed",
        "summary": "not a completed handoff",
    }
    source = f'''
import json
import pathlib
import sys
message = json.dumps({invalid!r}, separators=(",", ":"))
pathlib.Path(sys.argv[1]).write_text(message, encoding="utf-8")
print(json.dumps({{"type":"thread.started","thread_id":"thread-schema"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-schema"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-schema","item":{{"id":"invalid","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-schema"}}))
'''
    receipt = run_execution(_prepare(tmp_path, source))

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["terminal_reason"] == "final_result_schema_invalid"
    assert receipt["terminal_blocker_code"] == "FINAL_RESULT_SCHEMA_INVALID"
    assert receipt["stdout_jsonl"]["last_agent_message_schema_status"] == (
        "INVALID_STATUS"
    )
    assert "final_result_schema_invalid" in receipt["outcome_facts"][
        "integrity_reasons"
    ]


def test_ticket_bound_absence_receipts_are_unique_across_phase_directories(
    tmp_path: Path,
) -> None:
    final = _coding_contract("missing but ticket bound")
    source = f'''
import json
message = json.dumps({final!r}, separators=(",", ":"))
print(json.dumps({{"type":"thread.started","thread_id":"thread-bound"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-bound"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-bound","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-bound"}}))
'''
    first_handle = _prepare(tmp_path, source, phase_key="coding-one", run_id=10)
    second_handle = _prepare(tmp_path, source, phase_key="coding-two", run_id=11)

    first = run_execution(first_handle)
    second = run_execution(second_handle)

    assert first_handle.phase_directory != second_handle.phase_directory
    assert first["final_message"]["relative_path"] == "final-message.txt"
    assert second["final_message"]["relative_path"] == "final-message.txt"
    assert first["final_message"]["ticket_binding_identity"] != second[
        "final_message"
    ]["ticket_binding_identity"]
    for receipt, handle in (
        (first, first_handle),
        (second, second_handle),
    ):
        absence = receipt["final_message_absence"]
        assert absence["relative_path"] == "final-message-absence.json"
        assert absence["final_message_binding_identity"] == receipt[
            "final_message"
        ]["ticket_binding_identity"]
        assert (handle.phase_directory / absence["relative_path"]).is_file()


@pytest.mark.parametrize("mode", ["partial", "invalid", "replaced"])
def test_partial_replaced_or_invalid_sidecar_never_enables_jsonl_recovery(
    tmp_path: Path,
    mode: str,
) -> None:
    final = _coding_contract("sidecar must not recover")
    if mode == "partial":
        sidecar_setup = 'path.write_text("{\\\"schema\\\":", encoding="utf-8")'
    elif mode == "invalid":
        sidecar_setup = 'path.write_bytes(b"\\xff\\xfe")'
    else:
        sidecar_setup = (
            'target = path.with_name("replacement-target.txt")\n'
            'target.write_text("replacement", encoding="utf-8")\n'
            'path.symlink_to(target.name)'
        )
    source = f'''
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
{sidecar_setup}
message = json.dumps({final!r}, separators=(",", ":"))
print(json.dumps({{"type":"thread.started","thread_id":"thread-invalid-sidecar"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-invalid-sidecar"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-invalid-sidecar","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-invalid-sidecar"}}))
'''
    handle = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["terminal_state"] == "RESULT_INTEGRITY_BLOCKED"
    assert receipt["outcome_facts"]["jsonl_recovery_candidate"] is False
    assert load_jsonl_final_message_candidate(handle) is None
    recovery = receipt["final_message"]["jsonl_recovery"]
    assert recovery["eligible_candidate"] is False
    if mode == "partial":
        assert receipt["terminal_blocker_code"] == (
            "FINAL_RESULT_SEMANTIC_MISMATCH"
        )
    else:
        assert receipt["final_message"]["settlement"]["status"] == "INVALID"
        assert receipt["terminal_blocker_code"] == (
            "SIDECAR_ATTEMPT_IDENTITY_MISMATCH"
        )


def test_fatal_terminal_contradiction_never_enables_missing_sidecar_recovery(
    tmp_path: Path,
) -> None:
    final = _coding_contract("fatal contradiction")
    source = f'''
import json
message = json.dumps({final!r}, separators=(",", ":"))
print(json.dumps({{"type":"thread.started","thread_id":"thread-fatal"}}))
print(json.dumps({{"type":"turn.started","turn_id":"turn-fatal"}}))
print(json.dumps({{"type":"item.completed","turn_id":"turn-fatal","item":{{"id":"final","type":"agent_message","text":message}}}}))
print(json.dumps({{"type":"error","fatal":True,"message":"fatal provider error"}}))
print(json.dumps({{"type":"turn.completed","turn_id":"turn-fatal"}}))
'''
    handle = _prepare(tmp_path, source)
    receipt = run_execution(handle)

    assert receipt["terminal_reason"] == "terminal_event_contradiction"
    assert receipt["outcome_facts"]["terminal_contradiction"] is True
    assert receipt["outcome_facts"]["jsonl_recovery_candidate"] is False
    assert load_jsonl_final_message_candidate(handle) is None


@pytest.mark.parametrize(
    ("artifact", "expected_code"),
    [
        ("final-message.txt", "PARTIAL_FINAL_MESSAGE_EXISTS"),
        ("final-message-absence.json", "FINAL_MESSAGE_ABSENCE_PROOF_EXISTS"),
    ],
)
def test_stale_prelaunch_sidecar_or_absence_proof_blocks_process_start(
    tmp_path: Path,
    artifact: str,
    expected_code: str,
) -> None:
    source = r'''
import pathlib
pathlib.Path("process-started.txt").write_text("started", encoding="utf-8")
'''
    handle = _prepare(tmp_path, source)
    (handle.phase_directory / artifact).write_text("stale", encoding="utf-8")

    with pytest.raises(CodexExecBridgeError) as raised:
        run_execution(handle)

    assert raised.value.code == expected_code
    assert not (
        tmp_path / "coding-canonical" / "working" / "process-started.txt"
    ).exists()
