from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import twos_runtime.codex_adapter as codex_adapter_module
from twos_runtime.app import codex_run_out, create_app
from twos_runtime.codex_adapter import (
    CodexAdapter,
    CodexDetection,
    CodexModelCatalog,
    CodexModelCatalogEntry,
)
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import (
    AIModel,
    AIModelAvailabilityEvidence,
    AIModelAssignment,
    AuditEvent,
    CodexInstructionPack,
    CodexRun,
    Provider,
    Task,
    utc_now,
)
from twos_runtime.self_hosting import codex_execution_target


OWNER_PASSWORD = "owner-password-123"
FAKE_THREAD_ID = "fixture-codex-thread-001"
FAKE_GH_TOKEN = "ghp_" + "0123456789ABCDEFGHIJKLMN"
FAKE_GITHUB_TOKEN = "github_pat_" + "0123456789_ABCDEFGHIJKLMN"
FAKE_GH_SHAPED_TOKEN = "ghp_" + "9876543210ZYXWVUTSRQPONM"
FAKE_GITHUB_SHAPED_TOKEN = "github_pat_" + "9876543210_ZYXWVUTSRQPONM"
FAKE_SLACK_SHAPED_TOKEN = "xoxb-" + "123456789012-abcdefghijkl"
FAKE_AWS_ACCESS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
CONTROLLED_CATALOG_MODELS = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.5",
    "fixture-provider-model-owner-setup",
    "fixture-unassigned-draft-model",
    "fixture-provider-model-ready",
    "fixture-runtime-readiness-model",
    "fixture-worker-detect-model",
    "fixture-worker-authenticate-model",
    "fixture-worker-popen-model",
    "fixture-worktree-failure-model",
    "fixture-startup-codex-model",
    "fixture-coding-structured",
    "fixture-coding-no-change",
    "fixture-verification-structured",
    "fixture-verification-reject-no-change",
    "fixture-verification-invalid-5.6sol",
    "fixture-verification-invalid-persisted",
    "fixture-verification-reject-output",
)


class FixturePrimaryEvidenceWriteError(RuntimeError):
    pass


class FixtureFallbackEvidenceWriteError(RuntimeError):
    pass


def codex_exec_args(model_identifier: str) -> list[str]:
    return [
        "exec",
        "--model",
        model_identifier,
        "--json",
        "--sandbox",
        "workspace-write",
        "--ephemeral",
        "--ignore-user-config",
        "--color",
        "never",
        "-",
    ]


def run_command(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def make_source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source-repo"
    repo.mkdir()
    run_command(repo, "git", "init", "-b", "main")
    run_command(repo, "git", "config", "user.email", "twos-test@example.invalid")
    run_command(repo, "git", "config", "user.name", "TWOS Test")
    (repo / "README.md").write_text("# Test source\n")
    run_command(repo, "git", "add", "README.md")
    run_command(repo, "git", "commit", "-m", "test baseline")
    return repo


def make_fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

if sys.argv[1:] == ["--version"]:
    delay_marker = pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + ".delay-second-detection")
    if delay_marker.exists():
        count_file = pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + ".detection-count")
        count = int(count_file.read_text() or "0") + 1 if count_file.exists() else 1
        count_file.write_text(str(count))
        if count >= 2:
            time.sleep(0.75)
    print("codex-cli 1.0-test")
    raise SystemExit(0)
if sys.argv[1:] == ["exec", "--help"]:
    print("Usage: codex exec --model MODEL --json [PROMPT]")
    raise SystemExit(0)
if sys.argv[1:] == ["login", "status"]:
    print("Logged in")
    raise SystemExit(0)

args = sys.argv[1:]
model_identifier = args[2] if len(args) > 2 and args[:2] == ["exec", "--model"] else ""
expected_args = [
    "exec",
    "--model",
    model_identifier,
    "--json",
    "--sandbox",
    args[5] if len(args) > 5 else "",
    "--ephemeral",
    "--ignore-user-config",
    "--color",
    "never",
    "-",
]
if (
    args != expected_args
    or args[5] not in {"workspace-write", "read-only"}
    or not model_identifier.startswith("fixture-provider-model-")
):
    print("unexpected fixed argv", file=sys.stderr)
    raise SystemExit(64)

def emit(event):
    print(json.dumps(event, separators=(",", ":")), flush=True)

prompt = sys.stdin.read()
pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + ".executed").write_text("executed\\n")
emit({"type": "thread.started", "thread_id": "fixture-codex-thread-001"})
emit({"type": "turn.started", "turn_id": "fixture-codex-turn-001"})
reroute_file = pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + ".reroute-to")
if reroute_file.exists():
    reroute_target = reroute_file.read_text().strip()
    emit({
        "type": "item.completed",
        "item": {
            "type": "error",
            "message": f"model rerouted: {model_identifier} -> {reroute_target} (fixture)",
        },
    })
if "FAKE_UNKNOWN_REROUTE" in prompt:
    emit({
        "type": "model.rerouted",
        "detail": {"from": model_identifier, "to": "fixture-unapproved-model"},
    })
if "FAKE_TRANSPORT" in prompt:
    forbidden = [
        key
        for key in ("TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET")
        if key in os.environ
    ]
    if forbidden:
        print("forbidden environment reached Codex", file=sys.stderr)
        raise SystemExit(78)
    emit({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": json.dumps({
                "argv": sys.argv[1:],
                "stdin_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "env_keys": sorted(os.environ),
                "NO_COLOR": os.environ.get("NO_COLOR", ""),
                "GIT_TERMINAL_PROMPT": os.environ.get("GIT_TERMINAL_PROMPT", ""),
                "GIT_ALLOW_PROTOCOL": os.environ.get("GIT_ALLOW_PROTOCOL", "missing"),
            }, separators=(",", ":")),
        },
    })
if "FAKE_PUSH_ATTEMPT" in prompt:
    push = subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/forbidden-by-twos"],
        capture_output=True,
        text=True,
    )
    emit({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": json.dumps({"push_returncode": push.returncode}, separators=(",", ":")),
        },
    })
    if push.returncode == 0:
        raise SystemExit(79)
if "FAKE_SECRET_OUTPUT" in prompt:
    emit({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": (
                "password=fixture-plain-secret "
                "Authorization: Bearer fixturebearertoken12345 "
                "sk-" + "fixtureprovidertoken12345 "
                "AWS_SECRET_ACCESS_KEY=fixture-aws-secret-value "
                "AWS_SESSION_TOKEN=fixture-aws-session-token "
                "GH_TOKEN=" + "ghp_" + "0123456789ABCDEFGHIJKLMN "
                "GITHUB_TOKEN=" + "github_pat_" + "0123456789_ABCDEFGHIJKLMN "
                "ghp_" + "9876543210ZYXWVUTSRQPONM "
                "github_pat_" + "9876543210_ZYXWVUTSRQPONM "
                "xoxb-" + "123456789012-abcdefghijkl "
                "AKIA" + "ABCDEFGHIJKLMNOP "
                "-----BEGIN " + "PRIVATE KEY-----fixture-private-----END " + "PRIVATE KEY-----"
            ),
            "api_key": "fixture-api-key-value",
        },
    })
if "FAKE_OUTPUT_CAP_UTF8" in prompt:
    sys.stdout.buffer.write(("界" * 10_000).encode("utf-8"))
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(b"\\xff" * 10_000)
    sys.stderr.buffer.flush()
elif "FAKE_OUTPUT_CAP" in prompt:
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "O" * 10_000}})
    sys.stderr.write("E" * 10_000 + "\\n")
    sys.stderr.flush()
if "FAKE_TIMEOUT" in prompt or "FAKE_CANCEL" in prompt or "FAKE_RUNTIME_SHUTDOWN" in prompt:
    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib,time;time.sleep(1.5);pathlib.Path('child-survived.txt').write_text('survived\\n')",
        ]
    )
    time.sleep(10)
if "FAKE_FAIL" in prompt:
    emit({
        "type": "turn.failed",
        "turn_id": "fixture-codex-turn-001",
        "error": {"message": "bounded fixture failure"},
    })
    print("fake execution failed", file=sys.stderr)
    raise SystemExit(3)

if args[5] == "read-only":
    if "FAKE_VERIFICATION_MUTATION" in prompt:
        pathlib.Path("verification-mutated.txt").write_text("forbidden verification mutation\\n")
    verification_result = {
        "schema": "twos.verification.v1",
        "verdict": "pass",
        "changed_files_checked": ["codex-result.txt"],
        "unexpected_files": [],
        "exact_content": "pass",
        "tests": "pass",
        "git_boundary": "pass",
        "remote_boundary": "pass",
    }
    emit({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": json.dumps(verification_result, separators=(",", ":")),
        },
    })

if args[5] == "workspace-write":
    pathlib.Path("codex-result.txt").write_text(
        "trailing whitespace   \\n" if "FAKE_BAD_WHITESPACE" in prompt else "isolated result\\n"
    )
    if "FAKE_EXCLUDED_ARTIFACT" in prompt:
        pathlib.Path(".env.codex-produced").write_text(
            "PASSWORD=fixture-result-secret-must-stay-redacted\\n"
        )
if "FAKE_COMMIT" in prompt:
    subprocess.run(["git", "add", "codex-result.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "fake codex result"], check=True)
emit({"type": "item.completed", "item": {"type": "agent_message", "text": "1 passed in fake validation"}})
emit({
    "type": "turn.completed",
    "turn_id": "fixture-codex-turn-001",
    "usage": {"input_tokens": 11, "cached_input_tokens": 2, "output_tokens": 3},
})
"""
    )
    executable.chmod(0o755)
    return executable


def make_detection_codex(
    tmp_path: Path,
    name: str,
    *,
    version_exit: int,
    help_exit: int,
    help_text: str = "Usage: codex exec --model MODEL --json [PROMPT]",
) -> Path:
    executable = tmp_path / name
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli matrix-test')\n"
        f"    raise SystemExit({version_exit})\n"
        "if sys.argv[1:] == ['exec', '--help']:\n"
        f"    print({help_text!r})\n"
        f"    raise SystemExit({help_exit})\n"
        "raise SystemExit(64)\n"
    )
    executable.chmod(0o755)
    return executable


def make_nonreading_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "nonreading-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import sys,time\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli nonreading-test')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['exec', '--help']:\n"
        "    print('Usage: codex exec --model MODEL --json [PROMPT]')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['login', 'status']:\n"
        "    print('Logged in')\n"
        "    raise SystemExit(0)\n"
        "args = sys.argv[1:]\n"
        "model_identifier = args[2] if len(args) > 2 and args[:2] == ['exec', '--model'] else ''\n"
        "expected = ['exec', '--model', model_identifier, '--json', '--sandbox', 'workspace-write', "
        "'--ephemeral', '--ignore-user-config', '--color', 'never', '-']\n"
        "if args != expected or not model_identifier.startswith('fixture-provider-model-'):\n"
        "    raise SystemExit(64)\n"
        "time.sleep(10)\n"
    )
    executable.chmod(0o755)
    return executable


def make_partial_stdin_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "partial-stdin-codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json,pathlib,sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli partial-stdin-test')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['exec', '--help']:\n"
        "    print('Usage: codex exec --model MODEL --json [PROMPT]')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['login', 'status']:\n"
        "    print('Logged in')\n"
        "    raise SystemExit(0)\n"
        "args = sys.argv[1:]\n"
        "model_identifier = args[2] if len(args) > 2 and args[:2] == ['exec', '--model'] else ''\n"
        "expected = ['exec', '--model', model_identifier, '--json', '--sandbox', 'workspace-write', "
        "'--ephemeral', '--ignore-user-config', '--color', 'never', '-']\n"
        "if args != expected or not model_identifier.startswith('fixture-provider-model-'):\n"
        "    raise SystemExit(64)\n"
        "sys.stdin.buffer.read(1)\n"
        "pathlib.Path('codex-result.txt').write_text('partial stdin fixture result\\n')\n"
        "print(json.dumps({'type':'thread.started','thread_id':'fixture-partial-stdin-thread'}), flush=True)\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}), flush=True)\n"
    )
    executable.chmod(0o755)
    return executable


def make_client(
    tmp_path: Path,
    source_repo: Path,
    codex_executable: Path,
    timeout: int = 5,
    output_limit: int = 20_000,
    *,
    database_path: Path | None = None,
    codex_model_identifier: str | None = None,
    codex_model_capabilities: tuple[str, ...] = ("coding",),
) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{database_path or (tmp_path / 'twos-self-hosting.sqlite3')}",
        scheduler_poll_seconds=0.05,
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "worktrees",
        codex_executable=str(codex_executable),
        codex_model_identifier=codex_model_identifier,
        codex_model_capabilities=codex_model_capabilities,
        codex_timeout_seconds=timeout,
        codex_output_limit=output_limit,
    )
    app = create_app(settings=settings, start_scheduler=False)
    identifiers = list(CONTROLLED_CATALOG_MODELS)
    if codex_model_identifier and codex_model_identifier not in identifiers:
        identifiers.append(codex_model_identifier)
    catalog = CodexModelCatalog(
        status="available",
        source="controlled_test_fixture",
        version="controlled-test-catalog.v1",
        installed_cli_version="codex-cli controlled-test",
        warnings=(),
        models=tuple(
            CodexModelCatalogEntry(
                adapter_id="codex_cli",
                provider_id="local_codex_cli",
                canonical_model_id=identifier,
                display_name=identifier,
                aliases=(),
                selectable=True,
                recommended=index == 0,
                lifecycle_status="current",
                compatibility_status="controlled_test_fixture",
                compatibility_source="controlled_test_fixture",
                catalog_version="controlled-test-catalog.v1",
                supported_capabilities=("coding", "verification"),
                purpose="Controlled test-only catalog entry.",
            )
            for index, identifier in enumerate(identifiers)
        ),
    )
    app.state.codex_manager.adapter._model_catalog_cache = catalog
    app.state.codex_manager.adapter._model_catalog_cached_at = time.monotonic()
    return TestClient(app)


def init_and_login(client: TestClient) -> dict[str, str]:
    signup = client.post("/api/auth/signup", json={"username": "owner", "password": OWNER_PASSWORD})
    assert signup.status_code in {201, 409}
    if signup.status_code == 409:
        login = client.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD})
        assert login.status_code == 200
        assert "token" not in login.json()
    else:
        assert signup.json() == {"authenticated": True, "user": {"username": "owner"}}
    return {}


def test_owner_can_check_and_assign_local_codex_without_execution_side_effects(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, executable) as client:
        headers = init_and_login(client)
        page = client.get("/")
        assert "Set up Codex" in page.text
        assert "Check availability" in page.text
        assert "Save and assign" in page.text
        assert client.get("/api/codex/setup").status_code == 200
        task_id = create_development_task(client, headers, marker="owner setup")
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []

        invalid_identifier = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": "5.6 sol"},
        )
        assert invalid_identifier.status_code == 422
        factory = client.app.state.session_factory
        with factory() as session:
            assert session.query(Provider).count() == 0
            assert session.query(AIModel).count() == 0
            assert session.query(AIModelAvailabilityEvidence).count() == 0

        checked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": "fixture-provider-model-owner-setup"},
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        model_id = checked.json()["configuration"]["id"]
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []

        assigned = client.post(
            f"/api/tasks/{task_id}/codex/setup/assign",
            json={"model_id": model_id},
        )
        assert assigned.status_code == 200, assigned.text
        coding = next(item for item in assigned.json()["assignments"] if item["capability"] == "coding")
        verification_before = next(
            item for item in assigned.json()["assignments"] if item["capability"] == "verification"
        )
        assert coding["assigned_model"]["provider_model_id"] == "fixture-provider-model-owner-setup"
        assert verification_before["assigned_model"] is None
        verification_blocker = client.get(
            f"/api/tasks/{task_id}/run-eligibility"
        ).json()["primary_blocker"]
        assert verification_blocker == {
            "code": "VERIFICATION_SETUP_REQUIRED",
            "message": "Verification needs setup.",
            "next_action": "Set up Verification",
            "control": "Set up Verification",
        }
        coding_assignment_version = coding["assignment_version"]
        verification_assigned = client.post(
            f"/api/tasks/{task_id}/codex/setup/assign",
            json={"model_id": model_id, "capability": "verification"},
        )
        assert verification_assigned.status_code == 200, verification_assigned.text
        assignments = verification_assigned.json()["assignments"]
        coding_after = next(item for item in assignments if item["capability"] == "coding")
        verification_after = next(item for item in assignments if item["capability"] == "verification")
        assert (
            coding_after["assigned_model"]["provider_model_id"]
            == "fixture-provider-model-owner-setup"
        )
        assert (
            verification_after["assigned_model"]["provider_model_id"]
            == "fixture-provider-model-owner-setup"
        )
        assert verification_after["independence_status"] == "separate_invocation"
        assert verification_after["assignment_version"] > coding_assignment_version
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []
        assert client.get(f"/api/tasks/{task_id}/codex-packs").json() == []

        pack = generate_pack(client, headers, task_id)
        assert pack["approved"] is False
        approved = approve_pack(client, headers, task_id, pack["id"])
        assert approved["approved"] is True
        assert client.get("/api/codex/status").json()["execution_ready"] is True
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []

        unchanged_check = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": "fixture-provider-model-owner-setup"},
        )
        assert unchanged_check.status_code == 200, unchanged_check.text
        assert unchanged_check.json()["available"] is True
        assert unchanged_check.json()["invalidated_packs"] == 0
        current_pack = client.get(f"/api/tasks/{task_id}/codex-packs/current").json()["pack"]
        assert current_pack["status"] == "approved"
        assert current_pack["approved"] is True
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []

        draft_check = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": "fixture-unassigned-draft-model"},
        )
        assert draft_check.status_code == 200, draft_check.text
        assert draft_check.json()["available"] is True
        assert draft_check.json()["invalidated_packs"] == 0
        current_pack = client.get(f"/api/tasks/{task_id}/codex-packs/current").json()["pack"]
        assert current_pack["status"] == "approved"
        current_assignments = client.get(f"/api/tasks/{task_id}/ai-plan").json()["assignments"]
        assert {
            item["capability"]: (
                item["assigned_model"]["provider_model_id"]
                if item["assigned_model"] is not None
                else None
            )
            for item in current_assignments
        }["coding"] == "fixture-provider-model-owner-setup"
        assert client.get("/api/tasks/%s/codex-runs" % task_id).json() == []

        with factory() as session:
            assert session.query(AIModelAvailabilityEvidence).count() == 3
            assert session.query(CodexRun).count() == 0

        assert client.post("/api/auth/logout").status_code == 200
        relogin = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert relogin.status_code == 200, relogin.text
        persisted_setup = client.get(
            f"/api/codex/setup?capability=coding&task_id={task_id}"
        ).json()
        assert (
            persisted_setup["configuration"]["provider_model_id"]
            == "fixture-provider-model-owner-setup"
        )

    with make_client(tmp_path, source_repo, executable) as restarted:
        headers = init_and_login(restarted)
        persisted_setup = restarted.get(
            f"/api/codex/setup?capability=coding&task_id={task_id}",
            headers=headers,
        )
        assert persisted_setup.status_code == 200, persisted_setup.text
        assert (
            persisted_setup.json()["configuration"]["provider_model_id"]
            == "fixture-provider-model-owner-setup"
        )
        current_pack = restarted.get(
            f"/api/tasks/{task_id}/codex-packs/current",
            headers=headers,
        ).json()["pack"]
        assert current_pack["status"] == "approved"
        assert restarted.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []


def test_codex_setup_requires_authentication(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    executable = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, executable) as client:
        assert client.get("/api/codex/setup").status_code == 401
        assert client.post(
            "/api/codex/setup/check", json={"model_identifier": "fixture-provider-model-auth"}
        ).status_code == 401


def configure_test_model_registry(client: TestClient, *, invocation_mode: str = "real") -> None:
    factory = client.app.state.session_factory
    with factory() as session:
        if session.scalar(select(AIModel).limit(1)) is None:
            provider_specs = (
                ("Fixture Model Provider A", "Primary test-only model registry."),
                ("Fixture Model Provider B", "Secondary test-only model registry."),
            )
            providers: dict[str, Provider] = {}
            for name, details in provider_specs:
                provider = session.scalar(
                    select(Provider).where(Provider.name == name, Provider.kind == "model")
                )
                if provider is None:
                    provider = Provider(
                        name=name,
                        kind="model",
                        status="healthy",
                        enabled=True,
                        details=details,
                        last_checked_at=utc_now(),
                    )
                    session.add(provider)
                    session.flush()
                providers[name] = provider

            model_specs = (
                ("Fixture Model Provider A", "Fixture planning model", ("planning",), 10),
                (
                    "Fixture Model Provider A",
                    "Fixture coding model",
                    ("coding", "verification"),
                    20,
                ),
                (
                    "Fixture Model Provider B",
                    "Fixture verification model",
                    ("verification",),
                    10,
                ),
                (
                    "Fixture Model Provider B",
                    "Fixture coding fallback model",
                    ("coding", "verification"),
                    30,
                ),
            )
            for provider_name, model_name, capabilities, priority in model_specs:
                provider = providers[provider_name]
                if session.scalar(
                    select(AIModel).where(
                        AIModel.provider_id == provider.id,
                        AIModel.model_name == model_name,
                    )
                ) is None:
                    session.add(
                        AIModel(
                            provider_id=provider.id,
                            model_name=model_name,
                            display_name=model_name,
                            capability_tags=json.dumps(capabilities, separators=(",", ":")),
                            routing_priority=priority,
                            evidence_source="local_cli_readiness",
                        )
                    )
            session.flush()

        for provider in session.scalars(select(Provider).where(Provider.kind == "model")).all():
            provider.enabled = True
            provider.status = "healthy"
        for model in session.scalars(select(AIModel)).all():
            model.status = "healthy"
            model.configuration_status = "configured"
            model.availability_status = "available"
            model.invocation_mode = invocation_mode
            model.execution_adapter = "codex_cli"
            model.evidence_status = "runtime_check"
            model.provider_model_id = f"fixture-provider-model-{model.id}"
            session.flush()
            session.add(
                AIModelAvailabilityEvidence(
                    configuration_identity=model.stable_id,
                    model_id=model.id,
                    checked_by_user_id=1,
                    adapter="codex_cli",
                    invocation_mode="real",
                    result="available",
                    evidence_type="controlled_test_cli_health",
                    failure_classification="",
                    runtime_identity="codex-cli 1.0-test",
                )
            )
        session.commit()


def test_twos_short_url_uses_canonical_static_asset_base(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        page = client.get("/twos")
        assert page.status_code == 200
        assert page.url.path == "/twos"
        assert client.get("/").history[0].headers["location"] == "/twos"
        legacy = client.get(
            "/static_cockpit/vol12_static_mvp/twos_command_center.html",
            follow_redirects=False,
        )
        assert legacy.status_code == 307
        assert legacy.headers["location"] == "/twos"
        assert 'href="/static_cockpit/vol12_static_mvp/styles.css?v=0.17.0"' in page.text
        assert 'src="/static_cockpit/vol12_static_mvp/twos_command_center.js?v=0.17.0"' in page.text
        stylesheet = client.get("/static_cockpit/vol12_static_mvp/styles.css")
        javascript = client.get("/static_cockpit/vol12_static_mvp/twos_command_center.js")
        assert stylesheet.status_code == 200
        assert javascript.status_code == 200
        assert stylesheet.text.strip()
        assert javascript.text.strip()


def create_development_task(client: TestClient, headers: dict[str, str], marker: str = "") -> int:
    projects = client.get("/api/projects", headers=headers).json()
    twos = next(item for item in projects if item["key"] == "twos")
    response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "project_id": twos["id"],
            "title": f"Self-hosting workbench {marker}".strip(),
            "action": "Analyze",
            "workflow_type": "product_development",
            "objective": f"Implement the self-hosting loop. {marker}".strip(),
            "source_sync_summary": "Owner feedback requires one persistent development flow.",
            "required_output": "Owner-visible Codex execution and acceptance evidence.",
            "boundary_risk": "No automatic merge or push.",
            "implementation_scope": "TWOS runtime and the existing command-center UI.",
            "forbidden_scope": "No shell injection, automatic merge, push, live trade, or live bet.",
            "acceptance_target": "Owner can inspect Git-derived result and accept all required items.",
        },
    )
    assert response.status_code == 200, response.text
    task_id = response.json()["id"]
    composed = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
    assert composed.status_code == 200
    return task_id


def create_executable_task(client: TestClient, headers: dict[str, str], marker: str = "") -> int:
    configure_test_model_registry(client)
    return create_development_task(client, headers, marker=marker)


def generate_pack(client: TestClient, headers: dict[str, str], task_id: int) -> dict:
    response = client.post(f"/api/tasks/{task_id}/codex-packs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def approve_pack(client: TestClient, headers: dict[str, str], task_id: int, pack_id: int) -> dict:
    response = client.post(f"/api/tasks/{task_id}/codex-packs/{pack_id}/approve", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def seed_bound_codex_run(
    client: TestClient,
    source_repo: Path,
    task_id: int,
    pack: dict,
    *,
    status: str,
    launch_intent: bool,
    process_spawned: bool,
    worktree_path: Path | None = None,
) -> int:
    factory = client.app.state.session_factory
    with factory() as session:
        coding = session.scalar(
            select(AIModelAssignment).where(
                AIModelAssignment.task_id == task_id,
                AIModelAssignment.assignment_version == pack["assignment_version"],
                AIModelAssignment.capability == "coding",
            )
        )
        assert coding is not None and coding.assigned_model is not None
        run = CodexRun(
            task_id=task_id,
            pack_id=pack["id"],
            status=status,
            executable_status="configured",
            source_repo=str(source_repo),
            source_branch="main",
            source_commit=pack["source_baseline_commit"],
            task_version=pack["task_version"],
            assignment_version=pack["assignment_version"],
            routing_snapshot_hash=pack["routing_snapshot_hash"],
            execution_assignment_id=coding.id,
            execution_model_id=coding.assigned_model_id,
            execution_provider_id=coding.assigned_model.provider_id,
            requested_model_identifier=coding.assigned_model.provider_model_id,
            fallback_selected=False,
            launch_intent_at=utc_now() if launch_intent else None,
            process_spawned=process_spawned,
            worktree_path=str(worktree_path) if worktree_path else "",
            worktree_branch=f"twos/run-fixture-{task_id}" if worktree_path else "",
            started_at=utc_now() if status == "running" else None,
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
    return run_id


def wait_for_run(
    client: TestClient,
    headers: dict[str, str],
    run_id: int,
    statuses: set[str],
    timeout: float = 10,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/codex-runs/{run_id}", headers=headers)
        assert response.status_code == 200
        run = response.json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"Codex run {run_id} did not reach {statuses}")


def wait_for_spawned_run(
    client: TestClient,
    headers: dict[str, str],
    run_id: int,
    timeout: float = 5,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/codex-runs/{run_id}", headers=headers)
        assert response.status_code == 200
        run = response.json()
        if run["process_spawned"]:
            return run
        if run["status"] not in {"queued", "starting", "running", "verifying"}:
            raise AssertionError(f"Codex run {run_id} ended before process spawn: {run['status']}")
        time.sleep(0.05)
    raise AssertionError(f"Codex run {run_id} did not spawn a process")


def jsonl_events(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def test_pack_versioning_approval_and_invalidation(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers)
        first = generate_pack(client, headers, task_id)
        assert first["version"] == 1
        assert first["status"] == "approval_required"
        assert "## Ordered Stages" in first["content"]
        assert "## Stop Conditions" in first["content"]
        commit_policy = first["content"].split("## Commit Policy", 1)[1].split("## Final Response Format", 1)[0]
        assert "uncommitted" in commit_policy
        assert "Commit only when validation passes." not in first["content"]
        approved = approve_pack(client, headers, task_id, first["id"])
        assert approved["approved"] is True
        assert client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []

        second = generate_pack(client, headers, task_id)
        assert second["version"] == 2
        versions = client.get(f"/api/tasks/{task_id}/codex-packs", headers=headers).json()
        old = next(item for item in versions if item["id"] == first["id"])
        assert old["status"] == "invalidated"
        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409

        approve_pack(client, headers, task_id, second["id"])
        changed = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={"source_sync_summary": "Changed after approval."},
        )
        assert changed.status_code == 200
        current = client.get(f"/api/tasks/{task_id}/codex-packs/current", headers=headers).json()["pack"]
        assert current["status"] == "invalidated"

    with make_client(tmp_path, source_repo, fake_codex) as restarted:
        headers = init_and_login(restarted)
        versions = restarted.get(f"/api/tasks/{task_id}/codex-packs", headers=headers).json()
        assert [item["version"] for item in versions] == [2, 1]


def test_model_assignments_persist_and_version_only_when_routing_changes(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers)
        initial = client.get(f"/api/tasks/{task_id}/ai-plan", headers=headers).json()
        assert [item["capability"] for item in initial["assignments"]] == [
            "planning",
            "coding",
            "verification",
        ]
        assert {item["assignment_version"] for item in initial["assignments"]} == {1}
        assert all(item["assigned_model"] is None for item in initial["assignments"])
        readiness = {item["capability"]: item["readiness"] for item in initial["assignments"]}
        assert readiness == {
            "planning": "deterministic_no_model_invocation",
            "coding": "needs_setup",
            "verification": "needs_setup",
        }

        unchanged = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
        assert unchanged.status_code == 200
        assert {item["assignment_version"] for item in unchanged.json()["assignments"]} == {1}

        configure_test_model_registry(client)
        changed = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
        assert changed.status_code == 200
        assignments = changed.json()["assignments"]
        assert {item["assignment_version"] for item in assignments} == {2}
        assert all(item["assigned_model"] is not None for item in assignments)
        assert all(item["assigned_model"]["configuration_status"] == "configured" for item in assignments)
        assert all(item["assigned_model"]["availability_status"] == "available" for item in assignments)
        assert all(
            item["readiness"] == "runtime_available_model_configured_not_invoked"
            for item in assignments
        )
        verification = next(item for item in assignments if item["capability"] == "verification")
        assert verification["independence_required"] is True
        assert verification["independence_status"] in {"independent", "independent_fallback"}

    with make_client(tmp_path, source_repo, fake_codex) as restarted:
        headers = init_and_login(restarted)
        persisted = restarted.get(f"/api/tasks/{task_id}/ai-plan", headers=headers).json()
        assert {item["assignment_version"] for item in persisted["assignments"]} == {2}


@pytest.mark.parametrize("capability_focus", ["planning", "coding", "verification"])
def test_product_development_capability_focus_persists_required_triad_and_pack_coding_target(
    tmp_path: Path,
    capability_focus: str,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(client, headers, marker=f"focus-{capability_focus}")

        focused = client.post(
            "/api/ai/team-compose",
            headers=headers,
            json={"task_id": task_id, "capability_override": [capability_focus]},
        )
        assert focused.status_code == 200, focused.text
        assert set(focused.json()["required_capabilities"]) == {
            "planning",
            "coding",
            "verification",
        }

        persisted = client.get(f"/api/tasks/{task_id}/ai-plan", headers=headers)
        assert persisted.status_code == 200, persisted.text
        payload = persisted.json()
        assert set(payload["plan"]["required_capabilities"]) == {
            "planning",
            "coding",
            "verification",
        }
        assignments = payload["assignments"]
        assert {item["capability"] for item in assignments} == {
            "planning",
            "coding",
            "verification",
        }
        assert len(assignments) == 3

        pack = generate_pack(client, headers, task_id)
        snapshot_assignments = pack["model_routing_snapshot"]["assignments"]
        assert {item["capability"] for item in snapshot_assignments} == {
            "planning",
            "coding",
            "verification",
        }
        factory = client.app.state.session_factory
        with factory() as session:
            task = session.get(Task, task_id)
            pack_row = session.get(CodexInstructionPack, pack["id"])
            assert task is not None and pack_row is not None
            target = codex_execution_target(session, task, pack_row)
            assert target.assignment.capability == "coding"
            assert target.assignment.assignment_version == pack["assignment_version"]
            assert target.requested_model_identifier == target.model.provider_model_id


def test_assignment_and_provider_semantic_changes_invalidate_exact_pack_approval(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(client, headers)
        first_pack = generate_pack(client, headers, task_id)
        assert first_pack["assignment_version"] == 1
        assert len(first_pack["model_routing_snapshot"]["assignments"]) == 3
        approve_pack(client, headers, task_id, first_pack["id"])

        factory = client.app.state.session_factory
        with factory() as session:
            planning = session.scalar(
                select(AIModelAssignment).where(
                    AIModelAssignment.task_id == task_id,
                    AIModelAssignment.assignment_version == 1,
                    AIModelAssignment.capability == "planning",
                )
            )
            assert planning is not None and planning.assigned_model is not None
            planning.assigned_model.status = "failed"
            planning.assigned_model.availability_status = "unavailable"
            session.commit()

        recomposed = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
        assert recomposed.status_code == 200
        assert {item["assignment_version"] for item in recomposed.json()["assignments"]} == {2}
        stale = client.get(f"/api/tasks/{task_id}/codex-packs/current", headers=headers).json()["pack"]
        assert stale["status"] == "invalidated"

        second_pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, second_pack["id"])
        with factory() as session:
            current_assignment = session.scalar(
                select(AIModelAssignment).where(
                    AIModelAssignment.task_id == task_id,
                    AIModelAssignment.assignment_version == 2,
                    AIModelAssignment.assigned_model_id.is_not(None),
                )
            )
            assert current_assignment is not None
            current_assignment.assigned_model.provider.status = "failed"
            session.commit()

        observed = client.get(f"/api/tasks/{task_id}/run-eligibility", headers=headers)
        assert observed.status_code == 200
        assert any(item["code"] == "PACK_STALE" for item in observed.json()["blockers"])
        with factory() as session:
            read_only_pack = session.get(CodexInstructionPack, second_pack["id"])
            assert read_only_pack is not None
            assert read_only_pack.status == "approved"
            assert read_only_pack.invalidated_at is None

        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409
        assert "Provider readiness" in blocked.json()["error"]["message"]
        persisted = client.get(f"/api/tasks/{task_id}/codex-packs/current", headers=headers).json()["pack"]
        assert persisted["status"] == "invalidated"
        assert client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


def test_codex_run_automatically_records_exact_approved_model_and_jsonl_evidence(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        configure_test_model_registry(client)
        task_id = create_development_task(client, headers, marker="FAKE_SUCCESS")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        factory = client.app.state.session_factory
        with factory() as session:
            coding = session.scalar(
                select(AIModelAssignment).where(
                    AIModelAssignment.task_id == task_id,
                    AIModelAssignment.assignment_version == pack["assignment_version"],
                    AIModelAssignment.capability == "coding",
                )
            )
            assert coding is not None and coding.assigned_model is not None
            assert coding.assigned_model.execution_adapter == "codex_cli"
            configured_model_id = coding.assigned_model_id
            actual_model_identifier = coding.assigned_model.provider_model_id

        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed"})
        assert run["task_version"] == pack["task_version"]
        assert run["assignment_version"] == pack["assignment_version"]
        assert run["routing_snapshot_hash"] == pack["routing_snapshot_hash"]
        assert run["process_spawned"] is True
        assert run["execution_target"]["assignment_id"] == coding.id
        assert run["execution_target"]["model"]["provider_model_id"] == actual_model_identifier
        assert run["execution_target"]["fallback_selected"] is False
        assert len(run["model_invocations"]) == 2
        by_capability = {item["capability"]: item for item in run["model_invocations"]}
        assert set(by_capability) == {"coding", "verification"}
        real = by_capability["coding"]
        assert real["capability"] == "coding"
        assert real["verified_real_invocation"] is True
        assert real["requested_model_identifier"] == actual_model_identifier
        assert real["actual_invoked_model_identifier"] is None
        assert real["actual_resolved_model_identifier"] is None
        assert real["actual_model_identity_verified"] is False
        assert "Real Codex CLI invocation verified" in real["display_claim"]
        assert "not independently exposed" in real["display_claim"]
        assert "Ran with" not in real["display_claim"]
        assert real["provider_evidence"] == {
            "model_identifier_match": False,
            "provider_response_observed": False,
            "requested_model_identifier_match": True,
        }
        process_evidence = real["process_evidence"]
        assert process_evidence["process_observed"] is True
        assert process_evidence["exit_code"] == 0
        assert process_evidence["isolated_worktree"] is True
        assert process_evidence["codex_jsonl_observed"] is True
        assert process_evidence["codex_thread_started"] is True
        assert process_evidence["codex_turn_started"] is True
        assert process_evidence["codex_turn_completed"] is True
        assert process_evidence["codex_turn_verified"] is True
        assert process_evidence["model_argument_observed"] is True
        assert process_evidence["model_identity_observed"] is False
        assert process_evidence["actual_model_identity_verified"] is False
        assert process_evidence["model_reroute_observed"] is False
        assert process_evidence["thread_id_fingerprint"] == hashlib.sha256(
            FAKE_THREAD_ID.encode("utf-8")
        ).hexdigest()
        assert real["usage_metadata"] == {
            "cached_input_tokens": 2,
            "input_tokens": 11,
            "output_tokens": 3,
            "total_tokens": 14,
        }
        assert real["timed_out"] is False
        assert real["cancelled"] is False
        assert real["output_truncated"] is False
        verification = by_capability["verification"]
        assert verification["verified_real_invocation"] is True
        assert verification["requested_model_identifier"] == run["verification_target"]["model_identifier"]
        assert verification["actual_invoked_model_identifier"] is None
        assert verification["actual_resolved_model_identifier"] is None
        assert verification["actual_model_identity_verified"] is False
        assert "Ran with" not in verification["display_claim"]
        verification_process = verification["process_evidence"]
        assert verification_process["read_only_sandbox"] is True
        for check in (
            "verification_verdict_observed",
            "workspace_unchanged_after_verification",
            "changed_files_checked",
            "unexpected_files_checked",
            "exact_content_checked",
            "test_evidence_checked",
            "git_boundary_checked",
            "remote_boundary_checked",
        ):
            assert verification_process[check] is True
        assert run["verification_target"]["process_spawned"] is True
        assert run["verification_target"]["status"] == "completed"
        with factory() as session:
            invoked_model = session.get(AIModel, configured_model_id)
            assert invoked_model is not None
            assert invoked_model.evidence_status == "verified"
            assert invoked_model.last_verified_at is not None


def test_verification_workspace_mutation_is_detected_and_never_applied_to_source(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_VERIFICATION_MUTATION")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["verification_target"]["status"] == "completed"
    assert run["result"]["verification_process"]["status"] == "completed"
    assert run["result"]["verification_verdict"]["status"] == "failed"
    assert "workspace_unchanged_after_verification" in run["result"]["verification_verdict"]["failed_checks"]
    assert "verdict failed" in run["owner_summary"]
    verification = next(
        item for item in run["model_invocations"] if item["capability"] == "verification"
    )
    assert verification["verified_real_invocation"] is True
    assert verification["diagnostic_code"] == "verification_structured_evidence_verified"
    assert verification["process_evidence"]["read_only_sandbox"] is True
    assert verification["process_evidence"]["workspace_unchanged_after_verification"] is False
    assert not (source_repo / "verification-mutated.txt").exists()
    assert (Path(run["worktree_path"]) / "verification-mutated.txt").exists()


def test_codex_jsonl_reroute_uses_only_the_explicit_approved_fallback(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_APPROVED_REROUTE")
        pack = generate_pack(client, headers, task_id)
        factory = client.app.state.session_factory
        with factory() as session:
            coding = session.scalar(
                select(AIModelAssignment).where(
                    AIModelAssignment.task_id == task_id,
                    AIModelAssignment.assignment_version == pack["assignment_version"],
                    AIModelAssignment.capability == "coding",
                )
            )
            assert coding is not None and coding.assigned_model is not None
            assert coding.fallback_allowed is True
            assert coding.fallback_model is not None
            assert coding.fallback_model.execution_adapter == "codex_cli"
            requested_identifier = coding.assigned_model.provider_model_id
            fallback_identifier = coding.fallback_model.provider_model_id
            fallback_stable_id = coding.fallback_model.stable_id
        fake_codex.with_name(fake_codex.name + ".reroute-to").write_text(fallback_identifier)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "needs_review"})

    assert run["status"] == "completed", run
    assert run["process_spawned"] is True
    assert run["execution_target"]["model"]["provider_model_id"] == requested_identifier
    assert run["execution_target"]["fallback_selected"] is False
    assert len(run["model_invocations"]) == 2
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["verified_real_invocation"] is True
    assert evidence["configured_model"]["stable_id"] == fallback_stable_id
    assert evidence["actual_invoked_model_identifier"] == fallback_identifier
    assert evidence["display_claim"] == f"Ran with {fallback_identifier}"
    assert evidence["process_evidence"]["model_reroute_observed"] is True
    assert evidence["process_evidence"]["model_identity_observed"] is True
    assert evidence["provider_evidence"]["model_identifier_match"] is True


def test_interrupted_run_recovery_distinguishes_prelaunch_launch_window_and_spawned(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="RECOVERY_BOUNDARIES")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        prelaunch_id = seed_bound_codex_run(
            client,
            source_repo,
            task_id,
            pack,
            status="queued",
            launch_intent=False,
            process_spawned=False,
        )
        launch_window_id = seed_bound_codex_run(
            client,
            source_repo,
            task_id,
            pack,
            status="running",
            launch_intent=True,
            process_spawned=False,
        )
        spawned_id = seed_bound_codex_run(
            client,
            source_repo,
            task_id,
            pack,
            status="running",
            launch_intent=True,
            process_spawned=True,
            worktree_path=tmp_path / "interrupted-spawned-worktree",
        )

        client.app.state.codex_manager.recover_interrupted_runs()
        recovered = {
            run_id: client.get(f"/api/codex-runs/{run_id}", headers=headers).json()
            for run_id in (prelaunch_id, launch_window_id, spawned_id)
        }

    prelaunch = recovered[prelaunch_id]
    assert prelaunch["status"] == "blocked"
    assert prelaunch["launch_intent_recorded"] is False
    assert prelaunch["process_spawned"] is False
    assert "before the durable Codex launch boundary" in prelaunch["owner_summary"]
    assert prelaunch["model_invocations"] == []

    launch_window = recovered[launch_window_id]
    assert launch_window["status"] == "blocked"
    assert launch_window["launch_intent_recorded"] is True
    assert launch_window["process_spawned"] is False
    assert "inside the durable Codex launch window" in launch_window["owner_summary"]
    assert "cannot be proven" in launch_window["owner_summary"]
    assert launch_window["model_invocations"] == []

    spawned = recovered[spawned_id]
    assert spawned["status"] == "failed"
    assert spawned["launch_intent_recorded"] is True
    assert spawned["process_spawned"] is True
    assert "after the Codex process was spawned" in spawned["owner_summary"]
    assert len(spawned["model_invocations"]) == 1
    interrupted_evidence = spawned["model_invocations"][0]
    assert interrupted_evidence["outcome"] == "failed"
    assert interrupted_evidence["diagnostic_code"] == "runtime_restart"
    assert interrupted_evidence["verified_real_invocation"] is False
    assert interrupted_evidence["actual_invoked_model_identifier"] is None
    assert interrupted_evidence["process_evidence"]["process_observed"] is True
    assert interrupted_evidence["process_evidence"]["codex_jsonl_observed"] is False
    assert interrupted_evidence["process_evidence"]["approved_pack_stdin_complete"] is False
    assert "Ran with" not in json.dumps(recovered, sort_keys=True)


def test_late_cancel_cannot_overwrite_spawned_run_owned_by_finalizer(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="LATE_CANCEL_FINALIZER")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        run_id = seed_bound_codex_run(
            client,
            source_repo,
            task_id,
            pack,
            status="running",
            launch_intent=True,
            process_spawned=True,
            worktree_path=tmp_path / "finalizer-owned-worktree",
        )

        late_cancel = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        assert late_cancel.status_code == 409
        assert late_cancel.json()["error"]["message"] == "Codex run was no longer cancellable."
        persisted = client.get(f"/api/codex-runs/{run_id}", headers=headers).json()

    assert persisted["status"] == "running"
    assert persisted["process_spawned"] is True
    assert persisted["cancelled"] is False
    assert persisted["finished_at"] is None
    assert persisted["model_invocations"] == []


def test_unknown_reroute_never_verifies_invocation_or_owner_acceptance(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_UNKNOWN_REROUTE")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

        acceptance = client.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]
        model_item = next(item for item in acceptance["items"] if item["key"] == "model_evidence")
        assert model_item["status"] == "fail"
        for item in acceptance["items"]:
            updated = client.patch(
                f"/api/owner-acceptance/{acceptance['id']}/items/{item['id']}",
                headers=headers,
                json={"status": "pass", "note": "Fixture-only attempted override."},
            )
            assert updated.status_code == 200
        blocked = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "Must remain blocked without verified evidence."},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["message"] == (
            "Separately verified Coding and Verification invocation evidence is required "
            "before acceptance."
        )
        persisted_acceptance = client.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]

    assert run["status"] == "failed"
    assert run["process_spawned"] is True
    assert len(run["model_invocations"]) == 2
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["outcome"] == "failed"
    assert evidence["diagnostic_code"] == "unsupported_model_routing_event"
    assert evidence["verified_real_invocation"] is False
    assert evidence["actual_invoked_model_identifier"] is None
    assert evidence["process_evidence"]["model_identity_observed"] is False
    assert evidence["display_claim"].startswith("Assigned to ")
    assert "Ran with" not in json.dumps(run, sort_keys=True)
    assert persisted_acceptance["status"] == "owner_review"
    assert persisted_acceptance["compact_sync_result"] == ""


def test_incomplete_approved_pack_stdin_delivery_never_verifies_real_invocation(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    partial_codex = make_partial_stdin_codex(tmp_path)
    with make_client(tmp_path, source_repo, partial_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="PARTIAL_STDIN")
        expanded = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={"required_output": "bounded pack delivery fixture " + ("P" * 2_000_000)},
        )
        assert expanded.status_code == 200, expanded.text
        recomposed = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
        assert recomposed.status_code == 200, recomposed.text
        pack = generate_pack(client, headers, task_id)
        assert len(pack["content"].encode("utf-8")) > 1_000_000
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["exit_code"] == 0
    assert run["process_spawned"] is True
    assert run["result"]["changed_files"] == ["codex-result.txt"]
    assert len(run["model_invocations"]) == 2
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["outcome"] == "failed"
    assert evidence["diagnostic_code"] == "approved_pack_delivery_incomplete"
    assert evidence["verified_real_invocation"] is False
    assert evidence["actual_invoked_model_identifier"] is None
    assert evidence["process_evidence"]["codex_jsonl_observed"] is True
    assert evidence["process_evidence"]["codex_turn_completed"] is True
    assert evidence["process_evidence"]["approved_pack_stdin_complete"] is False
    assert "Ran with" not in json.dumps(run, sort_keys=True)


def test_incomplete_jsonl_stream_collection_never_verifies_real_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    def fail_observer(_collector, _chunk: bytes) -> None:
        raise RuntimeError("bounded fixture observer failure")

    monkeypatch.setattr(codex_adapter_module._CodexJsonlEvidenceCollector, "feed", fail_observer)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="INCOMPLETE_JSONL_STREAM")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["exit_code"] == 0
    assert run["process_spawned"] is True
    assert len(run["model_invocations"]) == 2
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["outcome"] == "failed"
    assert evidence["diagnostic_code"] == "jsonl_collection_incomplete"
    assert evidence["verified_real_invocation"] is False
    assert evidence["actual_invoked_model_identifier"] is None
    assert evidence["process_evidence"]["codex_jsonl_observed"] is False
    assert evidence["process_evidence"]["approved_pack_stdin_complete"] is True
    assert "Ran with" not in json.dumps(run, sort_keys=True)


@pytest.mark.parametrize("fallback_fails", [False, True], ids=["fallback-recorded", "fallback-fails"])
def test_evidence_persistence_failure_terminalizes_run_and_blocks_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fallback_fails: bool,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    primary_message = "DO_NOT_PERSIST_PRIMARY_EXCEPTION_MESSAGE"
    fallback_message = "DO_NOT_PERSIST_FALLBACK_EXCEPTION_MESSAGE"

    def fail_primary_evidence(*_args, **_kwargs) -> bool:
        raise FixturePrimaryEvidenceWriteError(primary_message)

    def fail_fallback_evidence(*_args, **_kwargs) -> None:
        raise FixtureFallbackEvidenceWriteError(fallback_message)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="EVIDENCE_PERSISTENCE_FAILURE")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        manager = client.app.state.codex_manager
        monkeypatch.setattr(manager, "_record_codex_invocation_evidence", fail_primary_evidence)
        if fallback_fails:
            monkeypatch.setattr(manager, "_record_incomplete_spawn_evidence", fail_fallback_evidence)

        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        run = wait_for_run(client, headers, run_id, {"failed"})
        assert run["status"] not in {"queued", "starting", "running", "verifying"}

        audit_rows = [
            item
            for item in client.get("/api/audit", headers=headers).json()
            if item["entity_type"] == "codex_run" and item["entity_id"] == run_id
        ]
        primary_audits = [
            item
            for item in audit_rows
            if item["action"] == "model_invocation_evidence_persistence_failed"
        ]
        fallback_audits = [
            item
            for item in audit_rows
            if item["action"] == "model_invocation_fallback_evidence_failed"
        ]
        assert [item["details"] for item in primary_audits] == [
            "failure_type=FixturePrimaryEvidenceWriteError; context=run_finalization"
        ]
        assert [item["details"] for item in fallback_audits] == (
            ["failure_type=FixtureFallbackEvidenceWriteError; context=run_finalization"]
            if fallback_fails
            else []
        )
        serialized_audit = json.dumps(audit_rows, sort_keys=True)
        assert primary_message not in serialized_audit
        assert fallback_message not in serialized_audit

        acceptance = client.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]
        model_item = next(item for item in acceptance["items"] if item["key"] == "model_evidence")
        assert model_item["status"] == "fail"
        for item in acceptance["items"]:
            updated = client.patch(
                f"/api/owner-acceptance/{acceptance['id']}/items/{item['id']}",
                headers=headers,
                json={"status": "pass", "note": "Attempted fixture override."},
            )
            assert updated.status_code == 200
        blocked = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "Must remain blocked without verified evidence."},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["message"] == (
            "Separately verified Coding and Verification invocation evidence is required "
            "before acceptance."
        )
        persisted_acceptance = client.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]

    assert run["status"] == "failed"
    assert run["process_spawned"] is True
    assert run["exit_code"] == 0
    assert run["finished_at"] is not None
    assert run["result"]["changed_files"] == ["codex-result.txt"]
    assert run["result"]["commits"] == []
    assert run["result"]["validation"]["diff_check"] is True
    assert run["result"]["boundary_confirmation"]["isolated_worktree"] is True
    assert run["result"]["boundary_confirmation"]["source_main_unchanged"] is True
    assert run["result"]["boundary_confirmation"]["automatic_merge"] is False
    assert run["result"]["boundary_confirmation"]["automatic_push"] is False
    assert len(run["model_invocations"]) == (1 if fallback_fails else 2)
    verification_evidence = next(
        item for item in run["model_invocations"] if item["capability"] == "verification"
    )
    assert verification_evidence["verified_real_invocation"] is True
    assert not any(
        item["capability"] == "coding" and item["verified_real_invocation"]
        for item in run["model_invocations"]
    )
    if not fallback_fails:
        fallback_evidence = next(
            item for item in run["model_invocations"] if item["capability"] == "coding"
        )
        assert fallback_evidence["diagnostic_code"] == "evidence_persistence_failure"
        assert fallback_evidence["outcome"] == "failed"
        assert fallback_evidence["verified_real_invocation"] is False
        assert fallback_evidence["actual_invoked_model_identifier"] is None
    assert primary_message not in json.dumps(run, sort_keys=True)
    assert fallback_message not in json.dumps(run, sort_keys=True)
    assert persisted_acceptance["status"] == "owner_review"
    assert persisted_acceptance["compact_sync_result"] == ""


def test_codex_detection_requires_version_exec_model_and_json_capabilities(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    for version_exit, help_exit, expected in [
        (0, 0, "configured"),
        (1, 0, "needs_setup"),
        (0, 1, "needs_setup"),
        (1, 1, "needs_setup"),
    ]:
        executable = make_detection_codex(
            tmp_path,
            f"matrix-{version_exit}-{help_exit}",
            version_exit=version_exit,
            help_exit=help_exit,
        )
        detection = CodexAdapter(
            Settings(
                database_url="sqlite://",
                source_repo=source_repo,
                worktree_root=tmp_path / f"matrix-worktrees-{version_exit}-{help_exit}",
                codex_executable=str(executable),
            )
        ).detect()
        assert detection.status == expected
        assert (detection.supported_command == "exec") is (expected == "configured")

    no_exec_help = make_detection_codex(
        tmp_path,
        "matrix-help-without-exec",
        version_exit=0,
        help_exit=0,
        help_text="Usage: codex run [PROMPT]",
    )
    detection = CodexAdapter(
        Settings(
            database_url="sqlite://",
            source_repo=source_repo,
            worktree_root=tmp_path / "matrix-worktrees-no-exec",
            codex_executable=str(no_exec_help),
        )
    ).detect()
    assert detection.status == "needs_setup"
    assert detection.supported_command is None

    for name, help_text in [
        ("matrix-help-without-model", "Usage: codex exec --json [PROMPT]"),
        ("matrix-help-without-json", "Usage: codex exec --model MODEL [PROMPT]"),
    ]:
        incomplete = make_detection_codex(
            tmp_path,
            name,
            version_exit=0,
            help_exit=0,
            help_text=help_text,
        )
        detection = CodexAdapter(
            Settings(
                database_url="sqlite://",
                source_repo=source_repo,
                worktree_root=tmp_path / f"{name}-worktrees",
                codex_executable=str(incomplete),
            )
        ).detect()
        assert detection.status == "needs_setup"
        assert detection.supported_command is None


def test_fresh_registry_apis_expose_no_invented_models_and_show_explicit_local_binding(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    invented_names = {"OpenAI", "Gemini", "Claude", "DeepSeek", "GLM"}

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "fresh-unconfigured-registry.sqlite3",
    ) as fresh:
        headers = init_and_login(fresh)
        providers = fresh.get("/api/providers", headers=headers)
        models = fresh.get("/api/models", headers=headers)
        assert providers.status_code == 200, providers.text
        assert models.status_code == 200, models.text
        assert providers.json() == []
        assert models.json() == []
        assert invented_names.isdisjoint(
            {item.get("name") for item in providers.json()}
            | {item.get("provider") for item in models.json()}
            | {item.get("display_name") for item in models.json()}
        )

    explicit_model_identifier = "fixture-explicit-local-model"
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "fresh-explicit-registry.sqlite3",
        codex_model_identifier=explicit_model_identifier,
        codex_model_capabilities=("planning", "coding", "verification"),
    ) as explicit:
        headers = init_and_login(explicit)
        providers = explicit.get("/api/providers", headers=headers)
        models = explicit.get("/api/models", headers=headers)
        assert providers.status_code == 200, providers.text
        assert models.status_code == 200, models.text
        assert [item["name"] for item in providers.json()] == ["Local Codex CLI"]
        assert len(models.json()) == 1
        assert models.json()[0]["provider"] == "Local Codex CLI"
        assert models.json()[0]["display_name"] == explicit_model_identifier
        assert models.json()[0]["provider_model_id"] == explicit_model_identifier
        assert invented_names.isdisjoint(
            {item.get("name") for item in providers.json()}
            | {item.get("provider") for item in models.json()}
            | {item.get("display_name") for item in models.json()}
        )


def test_codex_status_requires_explicit_ready_model_binding(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "codex-status-unbound.sqlite3",
        codex_model_identifier=None,
    ) as unbound:
        headers = init_and_login(unbound)
        status = unbound.get("/api/codex/status", headers=headers)
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "unconfigured"
        assert payload["found"] is False
        assert payload["authentication_ready"] is False
        assert payload["model_binding_ready"] is False
        assert payload["execution_ready"] is False
        assert payload["configuration_status"] == "needs_setup"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=tmp_path / "codex-status-bound.sqlite3",
        codex_model_identifier="fixture-provider-model-ready",
        codex_model_capabilities=("planning", "coding", "verification"),
    ) as bound:
        headers = init_and_login(bound)
        status = bound.get("/api/codex/status", headers=headers)
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "check_required"
        assert payload["found"] is False
        assert payload["authentication_ready"] is False
        assert payload["model_binding_ready"] is False
        assert payload["execution_ready"] is False

        checked = bound.post(
            "/api/codex/setup/check",
            json={"model_identifier": "fixture-provider-model-ready"},
            headers=headers,
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        payload = bound.get("/api/codex/status", headers=headers).json()
        assert payload["status"] == "configured"
        assert payload["authentication_ready"] is True
        assert payload["model_binding_ready"] is True
        assert payload["execution_ready"] is True


@pytest.mark.parametrize("readiness_probe", ["check", "run"])
def test_observed_codex_detection_loss_invalidates_approval_and_restore_cannot_reuse_it(
    tmp_path: Path,
    readiness_probe: str,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    model_identifier = "fixture-runtime-readiness-model"
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        codex_model_identifier=model_identifier,
        codex_model_capabilities=("planning", "coding", "verification"),
    ) as client:
        headers = init_and_login(client)
        checked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": model_identifier},
            headers=headers,
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        task_id = create_development_task(client, headers, marker=f"READINESS_{readiness_probe.upper()}")
        pack = generate_pack(client, headers, task_id)
        approved = approve_pack(client, headers, task_id, pack["id"])
        assert approved["approved"] is True

        unavailable_executable = fake_codex.with_name(fake_codex.name + ".temporarily-unavailable")
        fake_codex.rename(unavailable_executable)
        if readiness_probe == "check":
            persisted = client.get("/api/codex/status", headers=headers)
            assert persisted.status_code == 200, persisted.text
            assert persisted.json()["execution_ready"] is True
            assert persisted.json()["status"] == "configured"
            observed = client.post(
                "/api/codex/setup/check",
                json={"model_identifier": model_identifier},
                headers=headers,
            )
            assert observed.status_code == 200, observed.text
            assert observed.json()["available"] is False
            assert (
                observed.json()["availability_evidence"]["failure_classification"]
                == "runtime_unavailable"
            )
        else:
            observed = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
            assert observed.status_code == 409, observed.text

        factory = client.app.state.session_factory
        with factory() as session:
            invalidated = session.get(CodexInstructionPack, pack["id"])
            task = session.get(Task, task_id)
            model = session.scalar(
                select(AIModel).where(
                    AIModel.execution_adapter == "codex_cli",
                    AIModel.provider_model_id == model_identifier,
                )
            )
            assert invalidated is not None
            assert invalidated.status == "invalidated"
            assert invalidated.invalidated_at is not None
            assert task is not None and task.status == "planned"
            assert model is not None
            assert model.availability_status == "unavailable"
            assert model.provider.enabled is False

        unavailable_executable.rename(fake_codex)
        restored = client.get("/api/codex/status", headers=headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "check_required"
        assert restored.json()["execution_ready"] is False
        rechecked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": model_identifier},
            headers=headers,
        )
        assert rechecked.status_code == 200, rechecked.text
        assert rechecked.json()["available"] is True
        restored = client.get("/api/codex/status", headers=headers)
        assert restored.json()["status"] == "configured"
        assert restored.json()["execution_ready"] is True
        current = client.get(
            f"/api/tasks/{task_id}/codex-packs/current",
            headers=headers,
        ).json()["pack"]
        assert current["status"] == "invalidated"
        assert current["approved"] is False
        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409, blocked.text
        assert client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


@pytest.mark.parametrize("failure_stage", ["detect", "authenticate", "popen"])
def test_worker_pre_spawn_readiness_failure_invalidates_pack_without_run_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    model_identifier = f"fixture-worker-{failure_stage}-model"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        codex_model_identifier=model_identifier,
        codex_model_capabilities=("planning", "coding", "verification"),
    ) as client:
        headers = init_and_login(client)
        checked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": model_identifier},
            headers=headers,
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        task_id = create_development_task(client, headers, marker=f"WORKER_{failure_stage.upper()}")
        pack = generate_pack(client, headers, task_id)
        assert approve_pack(client, headers, task_id, pack["id"])["approved"] is True

        manager = client.app.state.codex_manager
        monkeypatch.setattr(manager, "start", lambda _run_id: True)
        queued = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert queued.status_code == 200, queued.text
        run_id = queued.json()["id"]

        real_popen = codex_adapter_module.subprocess.Popen
        codex_spawn_attempts: list[list[str]] = []

        def tracked_popen(args, *popen_args, **popen_kwargs):
            argv = [str(item) for item in args]
            is_model_execution = len(argv) > 2 and argv[0] == str(fake_codex) and argv[1:3] == [
                "exec",
                "--model",
            ]
            if is_model_execution:
                codex_spawn_attempts.append(argv)
                if failure_stage == "popen":
                    raise OSError("fixture Codex process readiness failure")
            return real_popen(args, *popen_args, **popen_kwargs)

        monkeypatch.setattr(codex_adapter_module.subprocess, "Popen", tracked_popen)
        if failure_stage == "detect":
            monkeypatch.setattr(
                manager.adapter,
                "detect",
                lambda: CodexDetection(
                    status="needs_setup",
                    found=True,
                    executable=str(fake_codex),
                    version=None,
                    supported_command=None,
                    reason="Codex CLI capability check failed.",
                    next_action="Repair the local Codex CLI.",
                ),
            )
        elif failure_stage == "authenticate":
            monkeypatch.setattr(
                manager.adapter,
                "authentication_ready",
                lambda _detection: (False, "Codex authentication needs setup."),
            )

        manager._execute(run_id)

        response = client.get(f"/api/codex-runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] == "blocked"
        assert run["process_spawned"] is False
        assert run["model_invocations"] == []
        assert run["result"]["task_id"] == task_id
        assert run["result"]["development_task"] == run["development_task"]
        assert run["result"]["development_task_digest"] == run["development_task_digest"]
        assert run["result"]["coding_invocation"]["process_execution_verified"] is False
        assert run["result"]["coding_invocation"]["codex_turn_verified"] is False
        assert run["result"]["verification_invocation"]["process_execution_verified"] is False
        assert run["result"]["verification_invocation"]["codex_turn_verified"] is False
        assert run["worktree_path"] == ""
        assert run["owner_summary"] == (
            "Blocked before process start: approved execution conditions are no longer satisfied."
        )
        assert "Ran with" not in json.dumps(run)
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()
        assert len(codex_spawn_attempts) == (1 if failure_stage == "popen" else 0)

        factory = client.app.state.session_factory
        with factory() as session:
            invalidated = session.get(CodexInstructionPack, pack["id"])
            persisted_run = session.get(CodexRun, run_id)
            assert invalidated is not None
            assert invalidated.status == "invalidated"
            assert invalidated.invalidated_at is not None
            assert persisted_run is not None
            assert persisted_run.process_spawned is False
            assert persisted_run.stdout == ""

    assert run_command(source_repo, "git", "status", "--porcelain").stdout.strip() == ""
    worktree_list = run_command(source_repo, "git", "worktree", "list", "--porcelain").stdout
    assert worktree_list.count("worktree ") == 1
    assert run_command(source_repo, "git", "branch", "--list", "twos/codex-run-*").stdout.strip() == ""


def test_worktree_creation_failure_keeps_machine_path_out_of_default_run_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    model_identifier = "fixture-worktree-failure-model"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        codex_model_identifier=model_identifier,
        codex_model_capabilities=("planning", "coding", "verification"),
    ) as client:
        headers = init_and_login(client)
        checked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": model_identifier},
            headers=headers,
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        task_id = create_development_task(client, headers, marker="WORKTREE_FAILURE")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])

        manager = client.app.state.codex_manager
        monkeypatch.setattr(manager, "start", lambda _run_id: True)
        queued = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert queued.status_code == 200, queued.text
        run_id = queued.json()["id"]

        diagnostic_path = tmp_path / "machine-specific" / "failed-worktree"

        def fail_worktree(_run_id: int, _source_commit: str) -> tuple[Path, str]:
            raise RuntimeError(f"git worktree failed at {diagnostic_path}")

        monkeypatch.setattr(manager.adapter, "create_worktree", fail_worktree)
        manager._execute(run_id)

        factory = client.app.state.session_factory
        with factory() as session:
            persisted_run = session.get(CodexRun, run_id)
            assert persisted_run is not None
            default_contract = codex_run_out(persisted_run, session=session)
            advanced_contract = codex_run_out(persisted_run, include_raw=True, session=session)

        encoded_default = json.dumps(default_contract, sort_keys=True)
        assert default_contract["status"] == "blocked"
        assert default_contract["owner_summary"] == (
            "The isolated Codex worktree could not be created. Inspect Advanced for diagnostics."
        )
        assert str(tmp_path) not in encoded_default
        assert "source_repo" not in default_contract
        assert "worktree_path" not in default_contract
        assert "stderr" not in default_contract
        assert advanced_contract["worktree_path"] == ""
        assert str(diagnostic_path) in advanced_contract["stderr"]
        assert len(advanced_contract["stderr"]) <= 2000
        assert advanced_contract["process_spawned"] is False
        assert advanced_contract["model_invocations"] == []
        assert "Ran with" not in json.dumps(advanced_contract)
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


def test_explicit_codex_model_settings_sync_only_after_local_cli_readiness(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as default_client:
        factory = default_client.app.state.session_factory
        with factory() as session:
            assert session.scalar(
                select(Provider).where(
                    Provider.name == "Local Codex CLI",
                    Provider.kind == "model",
                )
            ) is None
            assert session.scalar(
                select(AIModel).where(AIModel.execution_adapter == "codex_cli")
            ) is None

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'explicit-codex-model.sqlite3'}",
        scheduler_poll_seconds=0.05,
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "explicit-codex-worktrees",
        codex_executable=str(fake_codex),
        codex_model_identifier="fixture-codex-model",
        codex_model_capabilities=("planning", "coding", "verification"),
    )
    with TestClient(create_app(settings=settings, start_scheduler=False)) as explicit_client:
        factory = explicit_client.app.state.session_factory
        with factory() as session:
            provider = session.scalar(
                select(Provider).where(
                    Provider.name == "Local Codex CLI",
                    Provider.kind == "model",
                )
            )
            assert provider is not None
            assert provider.enabled is True
            assert provider.status == "healthy"
            model = session.scalar(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.execution_adapter == "codex_cli",
                )
            )
            assert model is not None
            assert model.provider_model_id == "fixture-codex-model"
            assert model.configuration_status == "configured"
            assert model.availability_status == "available"
            assert model.invocation_mode == "real"
            assert model.evidence_status == "runtime_check"
            assert model.evidence_source == "local_cli_readiness"
            assert model.last_verified_at is None
            assert "exact model is verified only by an explicit Owner-approved run" in (
                model.safe_diagnostic
            )
            assert json.loads(model.capability_tags) == ["planning", "coding", "verification"]


def test_startup_reconciles_removed_local_codex_binding_before_api_use(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database = tmp_path / "startup-reconciliation.sqlite3"
    model_identifier = "fixture-startup-codex-model"
    explicit_kwargs = {
        "database_path": database,
        "codex_model_identifier": model_identifier,
        "codex_model_capabilities": ("planning", "coding", "verification"),
    }

    with make_client(tmp_path, source_repo, fake_codex, **explicit_kwargs) as initial:
        headers = init_and_login(initial)
        checked = initial.post(
            "/api/codex/setup/check",
            json={"model_identifier": model_identifier},
            headers=headers,
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["available"] is True
        task_id = create_development_task(initial, headers, marker="STARTUP_RECONCILIATION")
        pack = generate_pack(initial, headers, task_id)
        approved = approve_pack(initial, headers, task_id, pack["id"])
        assert approved["status"] == "approved"
        factory = initial.app.state.session_factory
        with factory() as session:
            provider = session.scalar(
                select(Provider).where(
                    Provider.name == "Local Codex CLI",
                    Provider.kind == "model",
                )
            )
            assert provider is not None and provider.enabled is True
            model = session.scalar(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.provider_model_id == model_identifier,
                )
            )
            assert model is not None
            assert model.configuration_status == "configured"
            assert model.availability_status == "available"

    with make_client(tmp_path, source_repo, fake_codex, **explicit_kwargs) as unchanged:
        # Startup reconciliation runs synchronously in create_app, before any API request.
        factory = unchanged.app.state.session_factory
        with factory() as session:
            unchanged_pack = session.get(CodexInstructionPack, pack["id"])
            unchanged_task = session.get(Task, task_id)
            invalidations = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "codex_pack_approval_invalidated",
                        AuditEvent.entity_type == "task",
                        AuditEvent.entity_id == task_id,
                    )
                ).all()
            )
            assert unchanged_pack is not None
            assert unchanged_pack.status == "approved"
            assert unchanged_pack.invalidated_at is None
            assert unchanged_task is not None and unchanged_task.status == "pack_ready"
            assert invalidations == []
        headers = init_and_login(unchanged)
        current = unchanged.get(
            f"/api/tasks/{task_id}/codex-packs/current",
            headers=headers,
        ).json()["pack"]
        assert current["approved"] is True

    removed = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        codex_model_identifier=None,
    )
    with removed:
        # An absent legacy startup override must preserve Owner-created durable setup.
        factory = removed.app.state.session_factory
        with factory() as session:
            provider = session.scalar(
                select(Provider).where(
                    Provider.name == "Local Codex CLI",
                    Provider.kind == "model",
                )
            )
            assert provider is not None
            assert provider.enabled is True
            assert provider.status == "healthy"
            model = session.scalar(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.provider_model_id == model_identifier,
                )
            )
            assert model is not None
            assert model.status == "healthy"
            assert model.configuration_status == "configured"
            assert model.availability_status == "available"
            assert model.invocation_mode == "real"
            invalidated_pack = session.get(CodexInstructionPack, pack["id"])
            reconciled_task = session.get(Task, task_id)
            assert invalidated_pack is not None
            assert invalidated_pack.status == "approved"
            assert invalidated_pack.invalidated_at is None
            assert reconciled_task is not None and reconciled_task.status == "pack_ready"
            events = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action == "codex_pack_approval_invalidated",
                        AuditEvent.entity_type == "task",
                        AuditEvent.entity_id == task_id,
                    )
                ).all()
            )
            assert events == []

        headers = init_and_login(removed)
        current = removed.get(
            f"/api/tasks/{task_id}/codex-packs/current",
            headers=headers,
        ).json()["pack"]
        assert current["status"] == "approved"
        assert current["approved"] is True
        eligibility = removed.get(
            f"/api/tasks/{task_id}/run-eligibility",
            headers=headers,
        ).json()
        assert eligibility["eligible"] is True
        assert removed.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


def test_codex_detection_and_approval_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    configured = CodexAdapter(
        Settings(
            database_url="sqlite://",
            source_repo=source_repo,
            worktree_root=tmp_path / "worktrees",
            codex_executable=str(fake_codex),
        )
    ).detect()
    assert configured.status == "configured"
    assert configured.version == "codex-cli 1.0-test"
    missing = CodexAdapter(
        Settings(
            database_url="sqlite://",
            source_repo=source_repo,
            worktree_root=tmp_path / "worktrees-missing",
            codex_executable=str(tmp_path / "missing-codex"),
        )
    ).detect()
    assert missing.status == "unconfigured"

    broken = tmp_path / "broken-codex"
    broken.write_text("#!/bin/sh\necho 'SENSITIVE_NATIVE_PATH missing' >&2\nexit 1\n")
    broken.chmod(0o755)
    needs_setup = CodexAdapter(
        Settings(
            database_url="sqlite://",
            source_repo=source_repo,
            worktree_root=tmp_path / "worktrees-broken",
            codex_executable=str(broken),
        )
    ).detect()
    assert needs_setup.status == "needs_setup"
    assert needs_setup.version is None
    assert "SENSITIVE_NATIVE_PATH" not in needs_setup.reason

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        runtime_detect = client.app.state.codex_manager.adapter.detect
        monkeypatch.setattr(
            client.app.state.codex_manager.adapter,
            "detect",
            lambda: (_ for _ in ()).throw(AssertionError("status GET must not probe Codex")),
        )
        status = client.get("/api/codex/status", headers=headers).json()
        assert status["status"] == "unconfigured"
        assert status["execution_ready"] is False
        assert status["source"]["clean"] is True
        with client.app.state.session_factory() as session:
            assert session.query(AIModelAvailabilityEvidence).count() == 0
        monkeypatch.setattr(client.app.state.codex_manager.adapter, "detect", runtime_detect)
        configure_test_model_registry(client)
        task_id = create_development_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409
        assert "Approve" in blocked.json()["error"]["message"]
        approve_pack(client, headers, task_id, pack["id"])
        eligibility = client.get(f"/api/tasks/{task_id}/run-eligibility", headers=headers)
        assert eligibility.status_code == 200
        assert eligibility.json()["eligible"] is True
        assert client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


def test_codex_exec_uses_fixed_argv_exact_stdin_and_sanitized_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    monkeypatch.setenv("TWOS_OA005_SENTINEL", "must-not-reach-codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("SESSION_SECRET", "must-not-reach-codex")
    marker = "FAKE_TRANSPORT ; touch shell-injection $(touch shell-injection-2)"

    with make_client(tmp_path, source_repo, fake_codex) as client:
        manager_env = client.app.state.codex_manager._child_environment()
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker=marker)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "failed"})

    assert run["status"] == "completed", run
    model_identifier = run["execution_target"]["model"]["provider_model_id"]
    expected_argv = codex_exec_args(model_identifier)
    expected_hash = hashlib.sha256(pack["content"].encode("utf-8")).hexdigest()
    events = jsonl_events(run["stdout"])
    transport_event = next(
        event
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "agent_message"
        and event.get("item", {}).get("text", "").startswith("{")
    )
    transport = json.loads(transport_event["item"]["text"])
    assert transport["argv"] == expected_argv
    assert transport["stdin_sha256"] == expected_hash
    assert "forbidden environment reached Codex" not in run["stderr"]
    reported_env_keys = set(transport["env_keys"])
    fixed_allowed_keys = {
        "PATH",
        "HOME",
        "CODEX_HOME",
        "TMPDIR",
        "LANG",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "NO_COLOR",
        "GIT_TERMINAL_PROMPT",
        "GIT_ALLOW_PROTOCOL",
    }
    assert all(key in fixed_allowed_keys or key.startswith("LC_") for key in manager_env)
    assert {"PATH", "HOME", "NO_COLOR", "GIT_TERMINAL_PROMPT"}.issubset(manager_env)
    assert manager_env["NO_COLOR"] == "1"
    assert manager_env["GIT_TERMINAL_PROMPT"] == "0"
    assert manager_env["GIT_ALLOW_PROTOCOL"] == ""
    assert {"TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET"}.isdisjoint(manager_env)
    assert {"TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET"}.isdisjoint(reported_env_keys)
    assert transport["NO_COLOR"] == "1"
    assert transport["GIT_TERMINAL_PROMPT"] == "0"
    assert transport["GIT_ALLOW_PROTOCOL"] == ""
    worktree = Path(run["worktree_path"])
    for root in (source_repo, worktree):
        assert not (root / "shell-injection").exists()
        assert not (root / "shell-injection-2").exists()


def test_codex_run_with_origin_keeps_remote_state_and_blocks_push_transport(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    origin_repo = tmp_path / "origin.git"
    run_command(tmp_path, "git", "init", "--bare", str(origin_repo))
    run_command(source_repo, "git", "remote", "add", "origin", str(origin_repo))
    remote_refs_before = run_command(
        origin_repo,
        "git",
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
    ).stdout
    fake_codex = make_fake_codex(tmp_path)

    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_PUSH_ATTEMPT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"completed", "failed", "needs_review"},
        )
        assert client.app.state.codex_manager._boundary_evidence_passes(run["result"]) is True

    assert run["status"] == "completed", run
    boundary = run["result"]["boundary_confirmation"]
    assert boundary["push_target_configured"] is True
    assert boundary["source_remote_count"] == 1
    assert boundary["remote_state_observed"] is True
    assert boundary["remote_state_unchanged"] is True
    assert boundary["git_transport_protocols_allowed"] is False
    assert boundary["codex_tool_network_access_allowed"] is False
    push_event = next(
        event
        for event in jsonl_events(run["stdout"])
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "agent_message"
        and "push_returncode" in event.get("item", {}).get("text", "")
    )
    assert json.loads(push_event["item"]["text"])["push_returncode"] != 0
    remote_refs_after = run_command(
        origin_repo,
        "git",
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
    ).stdout
    assert remote_refs_after == remote_refs_before


def test_codex_persisted_output_redacts_secrets_and_raw_thread_identity(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_SECRET_OUTPUT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed"})

    persisted = run["stdout"] + run["stderr"]
    for forbidden in (
        "fixture-plain-secret",
        "fixturebearertoken12345",
        "fixtureprovidertoken12345",
        "fixture-aws-secret-value",
        "fixture-aws-session-token",
        FAKE_GH_TOKEN,
        FAKE_GITHUB_TOKEN,
        FAKE_GH_SHAPED_TOKEN,
        FAKE_GITHUB_SHAPED_TOKEN,
        FAKE_SLACK_SHAPED_TOKEN,
        FAKE_AWS_ACCESS_KEY,
        "fixture-private",
        "fixture-api-key-value",
        FAKE_THREAD_ID,
    ):
        assert forbidden not in persisted
    assert "[redacted]" in persisted
    assert "sha256:" in persisted
    assert run["model_invocations"][0]["verified_real_invocation"] is True


@pytest.mark.parametrize("output_limit", [8, 128])
def test_codex_combined_output_cap_including_tiny_limit(tmp_path: Path, output_limit: int) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        output_limit=output_limit,
    ) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_OUTPUT_CAP")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"needs_review", "failed"})

    assert run["status"] == "failed", run
    persisted_output = run["stdout"].encode("utf-8") + run["stderr"].encode("utf-8")
    assert len(persisted_output) <= output_limit
    assert run["output_truncated"] is True
    assert run["process_spawned"] is True
    assert len(run["model_invocations"]) == 2
    assert {item["capability"] for item in run["model_invocations"]} == {"coding", "verification"}
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["verified_real_invocation"] is False
    assert evidence["outcome"] == "failed"
    assert evidence["output_truncated"] is True
    assert evidence["diagnostic_code"] == "output_truncated"
    assert evidence["actual_invoked_model_identifier"] is None
    assert evidence["display_claim"].startswith("Assigned to ")
    if output_limit >= len("\n[output truncated by TWOS]"):
        assert "[output truncated by TWOS]" in run["stdout"] + run["stderr"]


def test_codex_output_cap_is_byte_safe_for_multibyte_and_invalid_utf8(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, output_limit=128) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_OUTPUT_CAP_UTF8")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"needs_review", "failed"})

    assert run["status"] == "failed", run
    persisted = run["stdout"].encode("utf-8") + run["stderr"].encode("utf-8")
    assert len(persisted) <= 128
    assert run["output_truncated"] is True
    assert run["process_spawned"] is True
    assert len(run["model_invocations"]) == 2
    assert {item["capability"] for item in run["model_invocations"]} == {"coding", "verification"}
    evidence = next(item for item in run["model_invocations"] if item["capability"] == "coding")
    assert evidence["verified_real_invocation"] is False
    assert evidence["outcome"] == "failed"
    assert evidence["output_truncated"] is True
    assert evidence["diagnostic_code"] == "output_truncated"
    assert evidence["actual_invoked_model_identifier"] is None


def test_large_pack_cannot_block_timeout_while_cli_ignores_stdin(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_nonreading_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=1) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        updated = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={"required_output": "X" * 1_000_000},
        )
        assert updated.status_code == 200
        recomposed = client.post("/api/ai/team-compose", headers=headers, json={"task_id": task_id})
        assert recomposed.status_code == 200
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started_at = time.monotonic()
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200
        run = wait_for_run(client, headers, started.json()["id"], {"timed_out"}, timeout=5)

    assert time.monotonic() - started_at < 5
    assert run["timed_out"] is True
    assert run["process_spawned"] is True
    assert len(run["model_invocations"]) == 1
    evidence = run["model_invocations"][0]
    assert evidence["outcome"] == "timed_out"
    assert evidence["timed_out"] is True
    assert evidence["cancelled"] is False
    assert evidence["verified_real_invocation"] is False
    assert evidence["actual_invoked_model_identifier"] is None


def test_codex_run_uses_approved_dirty_source_without_modifying_owner_workspace(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    (source_repo / "README.md").write_text("# Owner-approved dirty baseline\n")
    (source_repo / "owner-untracked-source.py").write_text("APPROVED = True\n")
    status_before = run_command(
        source_repo, "git", "status", "--porcelain", "--untracked-files=all"
    ).stdout
    files_before = {
        item.relative_to(source_repo).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in source_repo.rglob("*")
        if item.is_file() and ".git" not in item.relative_to(source_repo).parts
    }
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed"})

    assert run["result"]["changed_files"] == ["codex-result.txt"]
    sanitized_diff = run["result"]["sanitized_diff_evidence"]
    assert sanitized_diff["schema"] == "twos.sanitized_diff.v1"
    assert sanitized_diff["content_included"] is False
    assert sanitized_diff["record_count"] == 1
    assert sanitized_diff["truncated"] is False
    diff_record = sanitized_diff["records"][0]
    assert diff_record["path"] == "codex-result.txt"
    assert diff_record["change_type"] == "created"
    assert diff_record["before_sha256"] is None
    assert (
        diff_record["after_sha256"]
        == run["result"]["changed_file_evidence"][0]["after_sha256"]
    )
    assert diff_record["before_size"] is None
    assert diff_record["after_size"] == len("isolated result\n".encode())
    assert diff_record["content_kind"] == "text"
    assert diff_record["added_lines"] == 1
    assert diff_record["removed_lines"] == 0
    assert diff_record["changed_hunks"] == 1
    assert diff_record["content_included"] is False
    assert run["result"]["unexpected_excluded_artifacts"] == []
    assert run["result"]["validation"]["no_excluded_artifacts"] is True
    assert run["result"]["boundary_confirmation"]["source_main_unchanged"] is True
    assert run_command(
        source_repo, "git", "status", "--porcelain", "--untracked-files=all"
    ).stdout == status_before
    files_after = {
        item.relative_to(source_repo).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in source_repo.rglob("*")
        if item.is_file() and ".git" not in item.relative_to(source_repo).parts
    }
    assert files_after == files_before


def test_untracked_file_whitespace_failure_cannot_complete(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_BAD_WHITESPACE")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["status"] == "failed"
    assert run["result"]["validation"]["diff_check"] is False
    assert run["result"]["changed_files"] == ["codex-result.txt"]


def test_run_created_excluded_artifact_is_redacted_and_fails_git_evidence(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_EXCLUDED_ARTIFACT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["result"]["changed_files"] == ["codex-result.txt"]
    assert run["result"]["validation"]["diff_check"] is False
    assert run["result"]["validation"]["no_excluded_artifacts"] is False
    assert run["result"]["unexpected_excluded_artifacts"] == [
        {
            "path": "[credential-shaped path withheld]",
            "reason": "credential_or_secret",
        }
    ]
    serialized = json.dumps(run, sort_keys=True)
    assert ".env.codex-produced" not in serialized
    assert "fixture-result-secret-must-stay-redacted" not in serialized


def test_codex_commit_cannot_satisfy_uncommitted_execution_boundary(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    baseline = run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip()
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_COMMIT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200
        run = wait_for_run(client, headers, started.json()["id"], {"failed"})

    assert run["status"] == "failed"
    assert run["result"]["commits"]
    assert run["result"]["changed_files"] == ["codex-result.txt"]
    assert run["result"]["boundary_confirmation"]["source_main_unchanged"] is True
    assert run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip() == baseline


def test_concurrent_run_requests_queue_exactly_one_process(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        barrier = threading.Barrier(3)
        responses = []

        def request_run() -> None:
            barrier.wait()
            responses.append(client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers))

        workers = [threading.Thread(target=request_run) for _ in range(2)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join(timeout=5)

        assert sorted(response.status_code for response in responses) == [200, 409]
        runs = client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json()
        assert len(runs) == 1
        wait_for_spawned_run(client, headers, runs[0]["id"], timeout=3)
        cancelled = client.post(f"/api/codex-runs/{runs[0]['id']}/cancel", headers=headers)
        assert cancelled.status_code == 200
        run = wait_for_run(client, headers, runs[0]["id"], {"cancelled"}, timeout=5)
        assert run["process_spawned"] is True
        assert len(run["model_invocations"]) == 1
        assert run["model_invocations"][0]["outcome"] == "cancelled"
        assert run["model_invocations"][0]["verified_real_invocation"] is False


def test_codex_rechecks_exact_pack_approval_before_process_spawn(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    fake_codex.with_name(fake_codex.name + ".delay-second-detection").write_text("delay\n")
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        changed = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={"source_sync_summary": "Changed while the approved run was queued."},
        )
        assert changed.status_code == 200
        run = wait_for_run(
            client,
            headers,
            started.json()["id"],
            {"failed", "blocked", "cancelled"},
            timeout=5,
        )

    assert run["pack_id"] == pack["id"]
    assert run["status"] == "blocked"
    assert run["worktree_path"] == ""
    assert run["process_spawned"] is False
    assert run["model_invocations"] == []
    assert not fake_codex.with_name(fake_codex.name + ".executed").exists()
    assert run_command(source_repo, "git", "status", "--porcelain").stdout.strip() == ""
    worktree_list = run_command(source_repo, "git", "worktree", "list", "--porcelain").stdout
    assert worktree_list.count("worktree ") == 1
    branches = run_command(source_repo, "git", "branch", "--list", "twos/codex-run-*").stdout
    assert branches.strip() == ""


def test_codex_success_git_result_acceptance_and_compact_sync(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    baseline = run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip()
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_SUCCESS")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        assert started.json()["pack_id"] == pack["id"]
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "needs_review"})
        assert run["status"] == "completed"
        assert run["pack_id"] == pack["id"]
        assert run["source_commit"] == baseline
        assert run["worktree_branch"].startswith("twos/codex-run-")
        assert run["result"]["changed_files"] == ["codex-result.txt"]
        assert run["result"]["commits"] == []
        assert run["result"]["pre_run_commit"] == baseline
        assert run["result"]["post_run_commit"] == baseline
        assert run["result"]["working_tree_status"] == "?? codex-result.txt"
        assert run["result"]["validation"]["diff_check"] is True
        assert run["result"]["tests"] == []
        assert run["result"]["tests_reported"] == []
        assert "1 passed in fake validation" in run["result"]["advanced_diagnostics"]["coding_final_agent_message"]
        assert run["result"]["boundary_confirmation"]["automatic_merge"] is False
        assert run["result"]["boundary_confirmation"]["automatic_push"] is False
        assert run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip() == baseline
        assert run_command(source_repo, "git", "status", "--porcelain").stdout.strip() == ""

        acceptance = client.get(f"/api/tasks/{task_id}/owner-acceptance", headers=headers).json()["acceptance"]
        assert acceptance["status"] == "owner_review"
        blocked_acceptance = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "Must not accept before required checks pass."},
        )
        assert blocked_acceptance.status_code == 409
        for item in acceptance["items"]:
            updated = client.patch(
                f"/api/owner-acceptance/{acceptance['id']}/items/{item['id']}",
                headers=headers,
                json={"status": "pass", "note": "Verified in the named UI path."},
            )
            assert updated.status_code == 200
        accepted = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "Owner accepted Git-derived evidence."},
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["status"] == "accepted"
        assert "Accepted in TWOS does not mean merged or pushed." in body["compact_sync_result"]
        rejected_after_acceptance = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/reject",
            headers=headers,
            json={"note": "A final acceptance cannot be overwritten."},
        )
        assert rejected_after_acceptance.status_code == 409
        accepted_again = client.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "A final acceptance cannot be repeated."},
        )
        assert accepted_again.status_code == 409
        task = next(item for item in client.get("/api/tasks", headers=headers).json() if item["id"] == task_id)
        assert task["status"] == "accepted"
        assert task["compact_sync_result"] == body["compact_sync_result"]

    with make_client(tmp_path, source_repo, fake_codex) as restarted:
        headers = init_and_login(restarted)
        runs = restarted.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json()
        assert runs[0]["result"]["changed_files"] == ["codex-result.txt"]
        assert runs[0]["process_spawned"] is True
        assert len(runs[0]["model_invocations"]) == 2
        assert {item["capability"] for item in runs[0]["model_invocations"]} == {
            "coding",
            "verification",
        }
        assert all(item["verified_real_invocation"] is True for item in runs[0]["model_invocations"])
        acceptance = restarted.get(f"/api/tasks/{task_id}/owner-acceptance", headers=headers).json()["acceptance"]
        assert acceptance["status"] == "accepted"
        assert acceptance["compact_sync_result"]


def test_runtime_shutdown_is_interrupted_needs_review_and_not_owner_cancelled(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database = tmp_path / "runtime-shutdown.sqlite3"
    client = make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=20,
    )
    with client:
        headers = init_and_login(client)
        task_id = create_executable_task(client, headers, marker="FAKE_RUNTIME_SHUTDOWN")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]
        spawned = wait_for_spawned_run(client, headers, run_id, timeout=3)
        assert spawned["status"] == "running"
        assert spawned["process_spawned"] is True
        factory = client.app.state.session_factory

    deadline = time.monotonic() + 5
    persisted_status = ""
    while time.monotonic() < deadline:
        with factory() as session:
            run_row = session.get(CodexRun, run_id)
            assert run_row is not None
            persisted_status = run_row.status
        if persisted_status not in {"queued", "starting", "running", "verifying"}:
            break
        time.sleep(0.05)
    assert persisted_status == "failed"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database,
        timeout=20,
    ) as restarted:
        headers = init_and_login(restarted)
        run = restarted.get(f"/api/codex-runs/{run_id}", headers=headers).json()
        audits = [
            item
            for item in restarted.get("/api/audit", headers=headers).json()
            if item["entity_type"] == "codex_run" and item["entity_id"] == run_id
        ]
        acceptance = restarted.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]
        assert acceptance is not None
        assert next(item for item in acceptance["items"] if item["key"] == "model_evidence")[
            "status"
        ] == "fail"
        for item in acceptance["items"]:
            updated = restarted.patch(
                f"/api/owner-acceptance/{acceptance['id']}/items/{item['id']}",
                headers=headers,
                json={"status": "pass", "note": "Attempted shutdown-evidence override."},
            )
            assert updated.status_code == 200
        blocked = restarted.post(
            f"/api/owner-acceptance/{acceptance['id']}/accept",
            headers=headers,
            json={"note": "Runtime interruption cannot be accepted as verified execution."},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["message"] == (
            "Separately verified Coding and Verification invocation evidence is required "
            "before acceptance."
        )
        persisted_acceptance = restarted.get(
            f"/api/tasks/{task_id}/owner-acceptance",
            headers=headers,
        ).json()["acceptance"]

    assert run["status"] == "failed"
    assert run["process_spawned"] is True
    assert run["cancelled"] is False
    assert run["timed_out"] is False
    assert run["finished_at"] is not None
    assert run["result"]["process"]["runtime_interrupted"] is True
    assert run["result"]["process"]["cancelled"] is False
    assert "cancelled by the Owner" not in run["owner_summary"]
    assert len(run["model_invocations"]) == 1
    evidence = run["model_invocations"][0]
    assert evidence["outcome"] == "failed"
    assert evidence["error_category"] == "interrupted"
    assert evidence["diagnostic_code"] == "runtime_shutdown"
    assert evidence["cancelled"] is False
    assert evidence["verified_real_invocation"] is False
    assert evidence["actual_invoked_model_identifier"] is None
    assert evidence["process_evidence"]["runtime_interrupted"] is True
    assert "no Owner cancellation is claimed" in evidence["safe_summary"]
    assert all(item["action"] != "codex_run_cancelled" for item in audits)
    completed_audit = next(item for item in audits if item["action"] == "codex_run_completed")
    assert "status=failed" in completed_audit["details"]
    assert persisted_acceptance["status"] == "owner_review"
    assert persisted_acceptance["compact_sync_result"] == ""
    time.sleep(1.7)
    assert not (Path(run["worktree_path"]) / "child-survived.txt").exists()


def test_codex_failure_timeout_and_cancel(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=1) as client:
        headers = init_and_login(client)
        for marker, expected in [("FAKE_FAIL", "failed"), ("FAKE_TIMEOUT", "timed_out")]:
            task_id = create_executable_task(client, headers, marker=marker)
            pack = generate_pack(client, headers, task_id)
            approve_pack(client, headers, task_id, pack["id"])
            started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
            assert started.status_code == 200
            run = wait_for_run(client, headers, started.json()["id"], {expected}, timeout=8)
            assert run["status"] == expected
            assert run["process_spawned"] is True
            expected_capabilities = (
                {"coding"} if marker == "FAKE_TIMEOUT" else {"coding", "verification"}
            )
            assert {item["capability"] for item in run["model_invocations"]} == expected_capabilities
            evidence = next(
                item for item in run["model_invocations"] if item["capability"] == "coding"
            )
            assert evidence["outcome"] == expected
            assert evidence["verified_real_invocation"] is False
            assert evidence["actual_invoked_model_identifier"] is None
            if marker == "FAKE_TIMEOUT":
                assert run["timed_out"] is True
                assert evidence["timed_out"] is True
                assert evidence["cancelled"] is False
                assert run["result"]["process"]["timed_out"] is True
                assert run["result"]["process"]["cancelled"] is False
                time.sleep(1.7)
                assert not (Path(run["worktree_path"]) / "child-survived.txt").exists()
                assert "child-survived.txt" not in run["result"]["changed_files"]
            if marker == "FAKE_FAIL":
                assert evidence["timed_out"] is False
                assert evidence["cancelled"] is False
                acceptance = client.get(
                    f"/api/tasks/{task_id}/owner-acceptance",
                    headers=headers,
                ).json()["acceptance"]
                rejected = client.post(
                    f"/api/owner-acceptance/{acceptance['id']}/reject",
                    headers=headers,
                    json={"note": "Owner rejected the failed run."},
                )
                assert rejected.status_code == 200
                assert rejected.json()["status"] == "rejected"

        cancel_task_id = create_executable_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, cancel_task_id)
        approve_pack(client, headers, cancel_task_id, pack["id"])
        started = client.post(f"/api/tasks/{cancel_task_id}/codex-runs", headers=headers)
        run_id = started.json()["id"]
        wait_for_spawned_run(client, headers, run_id, timeout=3)
        duplicate = client.post(f"/api/tasks/{cancel_task_id}/codex-runs", headers=headers)
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["message"] == (
            "A Codex Run is already active for this task."
        )
        cancelled = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        run = wait_for_run(client, headers, run_id, {"cancelled"}, timeout=5)
        assert run["cancelled"] is True
        assert run["timed_out"] is False
        assert run["status"] == "cancelled"
        assert run["owner_summary"] == "Codex execution was cancelled by the Owner."
        assert run["result"]["process"]["cancelled"] is True
        assert run["result"]["process"]["timed_out"] is False
        assert run["result"]["process"]["runtime_interrupted"] is False
        assert run["process_spawned"] is True
        assert len(run["model_invocations"]) == 1
        evidence = run["model_invocations"][0]
        assert evidence["outcome"] == "cancelled"
        assert evidence["diagnostic_code"] == "owner_cancelled"
        assert evidence["cancelled"] is True
        assert evidence["timed_out"] is False
        assert evidence["process_evidence"]["runtime_interrupted"] is False
        assert evidence["verified_real_invocation"] is False
        assert evidence["actual_invoked_model_identifier"] is None
        time.sleep(1.7)
        assert not (Path(run["worktree_path"]) / "child-survived.txt").exists()
        assert "child-survived.txt" not in run["result"]["changed_files"]


def test_existing_database_migration_preserves_old_task(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                title VARCHAR(240) NOT NULL,
                task_type VARCHAR(80) NOT NULL,
                source_sync_summary TEXT NOT NULL DEFAULT '',
                required_output TEXT NOT NULL DEFAULT '',
                boundary_risk TEXT NOT NULL DEFAULT '',
                status VARCHAR(40) NOT NULL DEFAULT 'queued',
                acceptance_state VARCHAR(40) NOT NULL DEFAULT 'needs_review',
                compact_sync_result TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )"""
        )
        connection.execute(
            "INSERT INTO tasks (id, project_id, title, task_type, status, acceptance_state) "
            "VALUES (1, 1, 'Legacy task', 'Analyze', 'queued', 'needs_review')"
        )
        connection.commit()

    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{database}",
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "migration-worktrees",
        codex_executable=str(fake_codex),
    )
    with TestClient(create_app(settings=settings, start_scheduler=False)) as client:
        assert client.get("/api/health").status_code == 200

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert {
            "workflow_type",
            "objective",
            "implementation_scope",
            "forbidden_scope",
            "acceptance_target",
            "repository_identity",
            "source_baseline_commit",
        }.issubset(columns)
        assert connection.execute("SELECT title FROM tasks WHERE id = 1").fetchone()[0] == "Legacy task"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "codex_instruction_packs",
            "codex_runs",
            "owner_acceptance_sessions",
            "owner_acceptance_items",
        }.issubset(tables)
