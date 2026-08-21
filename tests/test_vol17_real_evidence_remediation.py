from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_self_hosting import (
    approve_pack,
    init_and_login,
    make_client,
    make_source_repo,
    wait_for_run,
)
from twos_runtime.config import STATIC_COCKPIT_DIR


SMOKE_FILE = "OA04_E2E_SMOKE_20260720.md"
SMOKE_LINE = "TWOS Vol.17 end-to-end Coding and Verification verified."
SMOKE_TASK = f"""Create a new repository-root file named {SMOKE_FILE}
containing exactly one line:

{SMOKE_LINE}

Do not modify any other file.
Do not commit, merge, push, create a tag, or change any Git remote."""


def make_structured_codex(tmp_path: Path) -> Path:
    """Create a controlled, non-networked Codex JSONL executable for this module."""
    executable = tmp_path / "vol17-real-evidence-codex"
    executable.write_text(
        f'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys

SMOKE_FILE = {SMOKE_FILE!r}
SMOKE_LINE = {SMOKE_LINE!r}

if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.144.4")
    raise SystemExit(0)
if sys.argv[1:] == ["exec", "--help"]:
    print(
        "Usage: codex exec --model MODEL --json "
        "--output-schema FILE --output-last-message FILE [PROMPT]"
    )
    raise SystemExit(0)
if sys.argv[1:] == ["login", "--help"]:
    print("Usage: codex login [status]")
    raise SystemExit(0)
if sys.argv[1:] == ["login", "status"]:
    print("Logged in (controlled test only)")
    raise SystemExit(0)
if sys.argv[1:] == [
    "app-server", "-c", "mcp_servers={{}}", "--strict-config", "--listen", "stdio://"
]:
    thread_id = "controlled-connectivity-thread"
    turn_id = "controlled-connectivity-turn"
    thread_model = ""
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        if method == "initialize":
            print(json.dumps({{
                "id": message["id"],
                "result": {{
                    "userAgent": "controlled-fixture",
                    "platformFamily": "unix",
                    "platformOs": "test",
                    "codexHome": os.environ.get("CODEX_HOME"),
                }},
            }}), flush=True)
        elif method == "mcpServerStatus/list":
            print(json.dumps({{
                "id": message["id"],
                "result": {{"data": [], "nextCursor": None}},
            }}), flush=True)
        elif method == "thread/start":
            params = message.get("params", {{}})
            thread_model = str(params.get("model") or "")
            assert params.get("allowProviderModelFallback") is False
            assert params.get("sandbox") == "read-only"
            assert params.get("ephemeral") is True
            assert params.get("modelProvider") == "openai"
            assert params.get("config") == {{
                "mcp_servers": {{}}, "web_search": "disabled"
            }}
            assert params.get("dynamicTools") == []
            assert params.get("runtimeWorkspaceRoots") == [params.get("cwd")]
            assert params.get("selectedCapabilityRoots") == []
            print(json.dumps({{
                "id": message["id"],
                "result": {{
                    "model": thread_model,
                    "modelProvider": "openai",
                    "cwd": params.get("cwd"),
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                    "sandbox": {{"type": "readOnly", "networkAccess": False}},
                    "instructionSources": [],
                    "runtimeWorkspaceRoots": params.get("runtimeWorkspaceRoots"),
                    "thread": {{"id": thread_id, "ephemeral": True}},
                }},
            }}), flush=True)
        elif method == "turn/start":
            params = message.get("params", {{}})
            assert params.get("threadId") == thread_id
            assert params.get("model") == thread_model
            started = {{"id": turn_id, "items": [], "status": "inProgress"}}
            item = {{
                "id": "controlled-connectivity-message",
                "type": "agentMessage",
                "text": "TWOS_CODEX_CONNECTION_OK",
            }}
            print(json.dumps({{
                "id": message["id"], "result": {{"turn": started}}
            }}), flush=True)
            print(json.dumps({{
                "method": "turn/started",
                "params": {{"threadId": thread_id, "turn": started}},
            }}), flush=True)
            print(json.dumps({{
                "method": "item/completed",
                "params": {{"threadId": thread_id, "turnId": turn_id, "completedAtMs": 1, "item": item}},
            }}), flush=True)
            print(json.dumps({{
                "method": "turn/completed",
                "params": {{
                    "threadId": thread_id,
                    "turn": {{
                        "id": turn_id,
                        "items": [item],
                        "status": "completed",
                        "error": None,
                    }},
                }},
            }}), flush=True)
        elif method == "thread/unsubscribe":
            print(json.dumps({{
                "id": message["id"], "result": {{"status": "unsubscribed"}}
            }}), flush=True)
    raise SystemExit(0)

args = sys.argv[1:]
def option(name):
    return args[args.index(name) + 1] if name in args else ""

schema_path = option("--output-schema")
last_message_path = option("--output-last-message")
base_args = list(args)
for sidecar_option in ("--output-schema", "--output-last-message"):
    if sidecar_option in base_args:
        sidecar_index = base_args.index(sidecar_option)
        del base_args[sidecar_index:sidecar_index + 2]
if len(base_args) != 11 or base_args[:2] != ["exec", "--model"] or base_args[3:5] != ["--json", "--sandbox"]:
    print("unexpected controlled argv shape", file=sys.stderr)
    raise SystemExit(64)
model_identifier = base_args[2]
sandbox_mode = base_args[5]
if base_args[6:] != ["--ephemeral", "--ignore-user-config", "--color", "never", "-"]:
    print("unexpected controlled argv tail", file=sys.stderr)
    raise SystemExit(64)
if schema_path:
    schema = json.loads(pathlib.Path(schema_path).read_text())
    assert schema["required"] == ["status"]
    assert schema["properties"]["status"]["const"] == "TWOS_CODEX_CONNECTION_OK"

prompt = sys.stdin.read()
prompt_suffix = ".coding-prompt" if sandbox_mode == "workspace-write" else ".verification-prompt"
pathlib.Path(__file__).with_suffix(prompt_suffix).write_text(prompt)

def emit(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)

def write_last_message(value):
    if last_message_path:
        pathlib.Path(last_message_path).write_text(value)

if "TWOS connectivity verification only" in prompt:
    response_text = json.dumps(
        dict(status="TWOS_CODEX_CONNECTION_OK"), separators=(",", ":")
    )
    write_last_message(response_text)
    emit({{
        "type": "thread.started",
        "thread_id": "controlled-connectivity-thread",
        "actual_model_identifier": model_identifier,
    }})
    emit({{"type": "turn.started", "turn_id": "controlled-connectivity-turn"}})
    emit({{
        "type": "item.completed",
        "item": {{
            "id": "connectivity-message-1",
            "type": "agent_message",
            "text": response_text,
        }},
    }})
    emit({{
        "type": "turn.completed",
        "turn_id": "controlled-connectivity-turn",
        "actual_model_identifier": model_identifier,
    }})
    raise SystemExit(0)

thread_started = {{
    "type": "thread.started",
    "thread_id": "controlled-thread-" + sandbox_mode,
}}
if "invalid" not in model_identifier:
    thread_started["actual_model_identifier"] = model_identifier
emit(thread_started)
emit({{"type": "turn.started", "turn_id": "controlled-turn-" + sandbox_mode}})

if sandbox_mode == "workspace-write":
    command_item = {{
        "id": "coding-command-1",
        "type": "command_execution",
        "command": ["python", "-c", "write the approved smoke artifact"],
        "aggregated_output": "repository inspection completed; this is not a test execution",
        "exit_code": 0,
        "status": "completed",
    }}
    emit({{"type": "item.started", "item": {{**command_item, "status": "in_progress"}}}})
    emit({{"type": "item.updated", "item": {{**command_item, "aggregated_output": "working"}}}})
    if "no-change" not in model_identifier:
        pathlib.Path(SMOKE_FILE).write_text(SMOKE_LINE + "\\n")
        emit({{
            "type": "item.completed",
            "item": {{
                "id": "coding-file-1",
                "type": "file_change",
                "changes": [{{"path": SMOKE_FILE, "kind": "add"}}],
                "status": "completed",
            }},
        }})
    emit({{"type": "item.completed", "item": command_item}})
    # A forward-compatible additive event is consumed without displacing the
    # later terminal event. Its payload remains outside the default result UI.
    emit({{
        "type": "future.progress.v2",
        "detail": {{"presentation": "controlled additive diagnostic"}},
    }})
    coding_message = json.dumps(
        {{
            "schema": "twos.coding_handoff.v1",
            "status": "completed",
            "summary": (
                "Implemented the exact approved artifact. "
                "No test command was executed."
            ),
        }},
        separators=(",", ":"),
    )
    write_last_message(coding_message)
    emit({{
        "type": "item.completed",
        "item": {{
            "id": "coding-message-1",
            "type": "agent_message",
            "text": coding_message,
        }},
    }})
    emit({{
        "type": "turn.completed",
        "turn_id": "controlled-turn-workspace-write",
        "usage": {{"input_tokens": 20, "cached_input_tokens": 2, "output_tokens": 8}},
    }})
    raise SystemExit(0)

if sandbox_mode != "read-only":
    raise SystemExit(64)

if "invalid" in model_identifier:
    failure = f'Configured model identifier "{{model_identifier}}" was rejected by Codex.'
    write_last_message(failure)
    emit({{
        "type": "item.completed",
        "item": {{"id": "verification-error-1", "type": "error", "message": failure}},
    }})
    emit({{
        "type": "turn.failed",
        "turn_id": "controlled-turn-read-only",
        "error": {{"message": failure, "kind": "model_not_found"}},
    }})
    print(failure, file=sys.stderr)
    raise SystemExit(2)

changed_files = [SMOKE_FILE] if pathlib.Path(SMOKE_FILE).is_file() else []
reject = "reject" in model_identifier or not changed_files
contract = {{
    "schema": "twos.verification.v1",
    "verdict": "fail" if reject else "pass",
    "changed_files_checked": changed_files,
    "unexpected_files": [],
    "exact_content": "fail" if reject else "pass",
    "tests": "not_applicable",
    "git_boundary": "pass",
    "remote_boundary": "pass",
}}
contract_text = json.dumps(contract, separators=(",", ":"))
write_last_message(contract_text)
emit({{
    "type": "item.completed",
    "item": {{
        "id": "verification-command-1",
        "type": "command_execution",
        "command": ["read", SMOKE_FILE],
        "aggregated_output": "checked requested artifact without modifying the workspace",
        "exit_code": 0,
        "status": "completed",
    }},
}})
emit({{
    "type": "item.completed",
    "item": {{
        "id": "verification-message-1",
        "type": "agent_message",
        "text": contract_text,
    }},
}})
emit({{
    "type": "turn.completed",
    "turn_id": "controlled-turn-read-only",
    "usage": {{"input_tokens": 12, "output_tokens": 5}},
}})
raise SystemExit(0)
'''
    )
    executable.chmod(0o755)
    return executable


def create_exact_task(client: TestClient) -> dict:
    project = next(item for item in client.get("/api/projects").json() if item["key"] == "twos")
    response = client.post(
        "/api/tasks",
        json={"project_id": project["id"], "development_task": SMOKE_TASK},
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["development_task"] == SMOKE_TASK
    assert task["title"] != "develop task"
    composed = client.post("/api/ai/team-compose", json={"task_id": task["id"]})
    assert composed.status_code == 200, composed.text
    return task


def check_and_assign(client: TestClient, task_id: int, capability: str, identifier: str) -> dict:
    checked = client.post(
        "/api/codex/setup/check",
        json={"model_identifier": identifier, "capability": capability},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["execution_prerequisites_available"] is True
    assert checked.json()["provider_probe_performed"] is False
    assert checked.json()["available"] is False
    verified = client.post(
        "/api/codex/setup/verify-connection",
        json={"model_identifier": identifier, "capability": capability},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["readiness_state"] == "READY_FOR_REAL_RUN"
    assert verified.json()["actual_model"] == identifier
    model_id = verified.json()["configuration"]["id"]
    assigned = client.post(
        f"/api/tasks/{task_id}/codex/setup/assign",
        json={"model_id": model_id, "capability": capability},
    )
    assert assigned.status_code == 200, assigned.text
    return next(
        item for item in assigned.json()["assignments"] if item["capability"] == capability
    )


def prepare_approved_pack(
    client: TestClient,
    *,
    coding_model: str = "fixture-coding-structured",
    verification_model: str = "fixture-verification-structured",
) -> tuple[dict, dict]:
    task = create_exact_task(client)
    coding = check_and_assign(client, task["id"], "coding", coding_model)
    verification = check_and_assign(client, task["id"], "verification", verification_model)
    assert coding["assigned_model"]["provider_model_id"] == coding_model
    assert verification["assigned_model"]["provider_model_id"] == verification_model
    generated = client.post(f"/api/tasks/{task['id']}/codex-packs")
    assert generated.status_code == 200, generated.text
    pack = generated.json()
    approved = approve_pack(client, {}, task["id"], pack["id"])
    assert approved["approved"] is True
    return task, approved


def start_and_wait(client: TestClient, task_id: int) -> dict:
    started = client.post(f"/api/tasks/{task_id}/codex-runs")
    assert started.status_code == 200, started.text
    run = wait_for_run(
        client,
        {},
        started.json()["id"],
        {"completed", "failed", "cancelled", "timed_out", "blocked"},
        timeout=15,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        activity = client.get("/api/run-activity")
        assert activity.status_code == 200, activity.text
        record = next(
            item
            for item in activity.json()["runs"]
            if item["run_id"] == run["id"]
        )
        if record["result_available"]:
            refreshed = client.get(f"/api/codex-runs/{run['id']}")
            assert refreshed.status_code == 200, refreshed.text
            payload = refreshed.json()
            verification_process = payload["result"]["verification_process"]
            verification_invocation = payload["result"]["verification_invocation"]
            terminal_turn_observed = (
                verification_process.get("turn_terminal_state")
                in {"completed", "failed"}
            )
            if (
                not terminal_turn_observed
                or verification_invocation.get("codex_turn_verified") is True
            ):
                return payload
        time.sleep(0.05)
    raise AssertionError("The terminal Run Result was not ingested within 15 seconds.")


def invocation_for(run: dict, capability: str) -> dict:
    return next(item for item in run["model_invocations"] if item["capability"] == capability)


def test_exact_multiline_development_task_and_digest_survive_pack_run_and_result(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)
    expected_digest = hashlib.sha256(SMOKE_TASK.encode("utf-8")).hexdigest()

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, pack = prepare_approved_pack(client)

        assert task["development_task"] == SMOKE_TASK
        assert pack["task_id"] == task["id"]
        assert pack["task_version"] == task["task_version"]
        assert pack["development_task"] == SMOKE_TASK
        assert pack["development_task_digest"] == expected_digest
        assert SMOKE_TASK in pack["content"]

        run = start_and_wait(client, task["id"])
        assert run["task_id"] == task["id"]
        assert run["task_version"] == task["task_version"]
        assert run["pack_id"] == pack["id"]
        assert run["pack_version"] == pack["version"]
        assert run["development_task"] == SMOKE_TASK
        assert run["development_task_digest"] == expected_digest
        assert run["result"]["development_task"] == SMOKE_TASK
        assert run["result"]["development_task_digest"] == expected_digest
        assert "develop task" not in json.dumps(run, sort_keys=True)

        delivered_prompt = executable.with_suffix(".coding-prompt").read_text()
        assert delivered_prompt == pack["content"]
        coding_evidence = invocation_for(run, "coding")
        assert coding_evidence["request_fingerprint"] == hashlib.sha256(
            pack["content"].encode("utf-8")
        ).hexdigest()


def test_successful_jsonl_turn_records_one_change_and_separates_default_evidence(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)
    coding_model = "fixture-coding-structured"
    verification_model = "fixture-verification-structured"

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, _ = prepare_approved_pack(
            client,
            coding_model=coding_model,
            verification_model=verification_model,
        )
        run = start_and_wait(client, task["id"])

        assert run["status"] == "completed"
        result = run["result"]
        assert result["coding_process"]["status"] == "completed"
        assert result["coding_process"]["process_started"] is True
        assert result["coding_process"]["exit_code"] == 0
        assert not result["coding_process"]["failure"]
        assert result["run_produced_changes"]["changed_files"] == [SMOKE_FILE]
        assert result["run_produced_changes"]["unexpected_files"] == []
        assert result["git_evidence"]["status"] == "passed"
        assert result["task_acceptance"]["status"] == "passed"
        assert result["verification_process"]["status"] == "completed"
        assert result["verification_verdict"]["status"] == "passed"
        assert result["tests"] == []

        coding = result["coding_invocation"]
        assert coding["process_execution_verified"] is True
        assert coding["codex_turn_verified"] is True
        assert coding["requested_model"] == coding_model
        assert coding["actual_resolved_model"] == coding_model
        assert coding["actual_model_identity_verified"] is True
        verification = result["verification_invocation"]
        assert verification["process_execution_verified"] is True
        assert verification["codex_turn_verified"] is True
        assert verification["requested_model"] == verification_model
        assert verification["actual_resolved_model"] == verification_model
        assert verification["actual_model_identity_verified"] is True

        default_payload = json.dumps(result, sort_keys=True)
        assert '"type": "command_execution"' not in default_payload
        assert '"aggregated_output"' not in default_payload
        assert "controlled additive diagnostic" not in default_payload
        display_claims = {
            item["capability"]: item["display_claim"]
            for item in run["model_invocations"]
        }
        assert display_claims == {
            "coding": f"Ran with {coding_model}",
            "verification": f"Ran with {verification_model}",
        }
        assert run["result"]["exec_bridge"]["transport_consumption_completed"] is True
        assert '"type":"future.progress.v2"' in run["coding_jsonl_diagnostics"]
        assert len(run["coding_jsonl_diagnostics"].encode("utf-8")) <= 200_000
        assert len(run["coding_jsonl_diagnostics"].encode("utf-8")) <= 200_000


def test_successful_process_with_no_changes_keeps_git_pass_separate_from_acceptance(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, _ = prepare_approved_pack(
            client,
            coding_model="fixture-coding-no-change",
            verification_model="fixture-verification-reject-no-change",
        )
        run = start_and_wait(client, task["id"])
        result = run["result"]

        assert run["status"] == "failed"
        assert result["coding_process"]["status"] == "completed"
        assert result["coding_process"]["exit_code"] == 0
        assert result["git_evidence"]["status"] == "passed"
        assert result["run_produced_changes"]["changed_files"] == []
        assert result["task_acceptance"]["status"] == "failed"
        assert "no requested implementation output" in result["task_acceptance"]["reason"].lower()
        assert "Required Git evidence did not pass" not in run["owner_summary"]


def test_invalid_verification_model_exposes_process_failure_and_verdict_not_reached(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)
    invalid_model = "fixture-verification-invalid-5.6sol"

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, _ = prepare_approved_pack(
            client,
            verification_model=invalid_model,
        )
        run = start_and_wait(client, task["id"])
        result = run["result"]

        assert run["status"] == "failed"
        assert result["verification_process"]["status"] == "failed"
        assert result["verification_process"]["process_exit"] == 2
        assert invalid_model in result["verification_process"]["failure"]
        assert "rejected by Codex" in result["verification_process"]["failure"]
        assert result["verification_invocation"]["requested_model"] == invalid_model
        assert result["verification_invocation"]["process_execution_verified"] is True
        assert result["verification_invocation"]["codex_turn_verified"] is True
        assert result["verification_process"]["turn_terminal_state"] == "failed"
        assert result["verification_invocation"]["actual_resolved_model"] is None
        assert result["verification_verdict"]["status"] == "not_reached"
        assert "Independent Verification process failed." != run["owner_summary"]


def test_completed_verification_can_reject_output_without_becoming_process_failure(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, _ = prepare_approved_pack(
            client,
            verification_model="fixture-verification-reject-output",
        )
        run = start_and_wait(client, task["id"])
        result = run["result"]

        assert run["status"] == "failed"
        assert result["verification_process"]["status"] == "completed"
        assert result["verification_process"]["process_exit"] == 0
        assert not result["verification_process"]["failure"]
        assert result["verification_invocation"]["codex_turn_verified"] is True
        assert result["verification_verdict"]["status"] == "failed"
        assert result["verification_verdict"]["failed_checks"]
        assert result["verification_verdict"]["passed_checks"]


def test_result_layout_keeps_jsonl_advanced_and_state_summaries_current() -> None:
    html = (STATIC_COCKPIT_DIR / "vol12_static_mvp" / "twos_command_center.html").read_text()
    javascript = (STATIC_COCKPIT_DIR / "vol12_static_mvp" / "twos_command_center.js").read_text()

    for control_id in (
        "pack-frozen-task",
        "pack-development-task",
        "pack-task-digest",
        "result-coding-process",
        "result-coding-process-proof",
        "result-coding-turn-proof",
        "result-coding-requested-model",
        "result-coding-actual-model",
        "result-git-evidence",
        "result-task-acceptance",
        "result-verification-status",
        "result-verification-process-proof",
        "result-verification-turn-proof",
        "result-verification-verdict",
        "result-boundary",
        "result-tests",
    ):
        assert f'id="{control_id}"' in html

    advanced = html.split('<details id="advanced-panel"', 1)[1]
    default_result = html.split('<section id="result-card"', 1)[1].split(
        '<section id="acceptance-card"', 1
    )[0]
    assert 'id="coding-jsonl"' in advanced
    assert 'id="verification-jsonl"' in advanced
    assert 'id="coding-jsonl"' not in default_result
    assert 'id="verification-jsonl"' not in default_result
    assert "Development task approved for execution" in html

    assert "Coding invocation is running in the isolated workspace." in javascript
    assert "Coding has reached a terminal process state; independent Verification is running." in javascript
    assert "The Run failed. Review the failed process or acceptance checks below." in javascript
    assert "Run accepted and queued for isolated execution." in javascript
    assert "tests_reported" not in javascript
    assert "aggregated_output" not in default_result


def test_planning_is_capability_not_executable_model_assignment(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)

    with make_client(tmp_path, source_repo, executable, output_limit=200_000) as client:
        init_and_login(client)
        task, pack = prepare_approved_pack(client)
        snapshot = pack["model_routing_snapshot"]
        assignments = snapshot["assignments"]
        planning = next(item for item in assignments if item["capability"] == "planning")

        assert len(assignments) == 3
        assert sum(item["assigned_model"] is not None for item in assignments) == 2
        assert planning["assigned_model"] is None
        assert snapshot["capability_count"] == 3
        assert snapshot["executable_assignment_count"] == 2
        assert snapshot["non_executing_capabilities"] == ["planning"]
        assert task["id"] == pack["task_id"]

    javascript = (STATIC_COCKPIT_DIR / "vol12_static_mvp" / "twos_command_center.js").read_text()
    assert "Executable model assignments" in javascript
    assert "Unassigned/non-executing capabilities" in javascript
    assert "Deterministic / No model invocation" in javascript
    assert 'snapshotAssignments.length + " model assignment"' not in javascript


def test_failed_result_survives_refresh_relogin_and_runtime_restart(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_structured_codex(tmp_path)
    database_path = tmp_path / "vol17-real-evidence.sqlite3"
    task_id = 0
    run_id = 0

    with make_client(
        tmp_path,
        source_repo,
        executable,
        output_limit=200_000,
        database_path=database_path,
    ) as client:
        init_and_login(client)
        task, _ = prepare_approved_pack(
            client,
            verification_model="fixture-verification-invalid-persisted",
        )
        task_id = task["id"]
        failed = start_and_wait(client, task_id)
        run_id = failed["id"]
        expected = {
            "status": failed["status"],
            "development_task": failed["development_task"],
            "development_task_digest": failed["development_task_digest"],
            "result": failed["result"],
        }

        refreshed = client.get(f"/api/codex-runs/{run_id}").json()
        assert {key: refreshed[key] for key in expected} == expected
        assert client.post("/api/auth/logout").status_code == 200
        relogin = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert relogin.status_code == 200, relogin.text
        after_login = client.get(f"/api/codex-runs/{run_id}").json()
        assert {key: after_login[key] for key in expected} == expected

    with make_client(
        tmp_path,
        source_repo,
        executable,
        output_limit=200_000,
        database_path=database_path,
    ) as restarted:
        init_and_login(restarted)
        persisted = restarted.get(f"/api/codex-runs/{run_id}")
        assert persisted.status_code == 200, persisted.text
        assert {key: persisted.json()[key] for key in expected} == expected
        listed = restarted.get(f"/api/tasks/{task_id}/codex-runs").json()
        assert listed[0]["id"] == run_id
        assert listed[0]["status"] == "failed"
