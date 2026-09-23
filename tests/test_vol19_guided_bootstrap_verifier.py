from __future__ import annotations

import json
import os
import secrets
import socket
import sqlite3
import subprocess

import httpx
import pytest

from scripts import twos_bootstrap
from tests.test_vol19_fresh_install_bootstrap import (
    ROOT,
    available_local_port,
    clean_source_copy,
    source_snapshot,
    terminate_owned_process,
)
from tests.test_vol19_guided_first_delivery import CHOICE, local_runner
from tests.test_vol19_verification_truth_remediation import make_local_verifier


VERIFIER_SETTING = "TWOS_LOCAL_VERIFICATION_COMMAND_JSON"
DELIVERY_TABLES = (
    "task_runs", "codex_instruction_packs", "codex_runs",
    "ai_model_invocation_evidence", "apply_sessions",
    "local_commit_executions", "push_executions",
)


def test_verifier_environment_is_runtime_only_and_allowlisted(tmp_path, monkeypatch):
    raw = json.dumps(["/trusted/python", "/trusted/verifier with spaces.py"])
    monkeypatch.setenv(VERIFIER_SETTING, raw)
    monkeypatch.setenv("TWOS_UNSUPPORTED_SETTING", "must-not-survive")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-survive")
    monkeypatch.setenv("PYTHONPATH", "/must/not/survive")
    installation = {"installation_id": "install_" + "a" * 32, "port": 18080}
    child = twos_bootstrap.child_environment(
        ROOT, tmp_path / "data", tmp_path / "runtime", tmp_path / "logs", installation,
    )
    assert child[VERIFIER_SETTING] == raw
    for name in ("TWOS_UNSUPPORTED_SETTING", "OPENAI_API_KEY", "PYTHONPATH"):
        assert name not in child
    assert VERIFIER_SETTING not in twos_bootstrap.bootstrap_environment()
    assert VERIFIER_SETTING not in twos_bootstrap.bootstrap_environment(package_install=True)
    monkeypatch.delenv(VERIFIER_SETTING)
    assert VERIFIER_SETTING not in twos_bootstrap.child_environment(
        ROOT, tmp_path / "data", tmp_path / "runtime", tmp_path / "logs", installation,
    )


@pytest.mark.parametrize("configuration", [
    "valid", "missing", "malformed", "non-array", "invalid-argument",
    "relative-executable", "unavailable-executable",
])
def test_standard_startup_guided_verifier_boundary(tmp_path, configuration):
    """T1–T4: real shell/bootstrap/venv/runtime/HTTP, no post-bootstrap injection.

    Only the external Codex service is replaced by the existing local protocol
    fixture. No live provider credentials or network Git destination are used.
    """
    tmp_path = tmp_path.resolve()
    source = tmp_path / "source"
    clean_source_copy(source)
    source_before = source_snapshot(source)
    tool_bin = tmp_path / "tools"
    tool_bin.mkdir()
    runner = local_runner(tool_bin).rename(tool_bin / "codex")
    probe_marker = runner.with_name(runner.name + ".probe-executed")
    verifier = make_local_verifier(tmp_path, name="trusted verifier.py")
    data, runtime, logs = (tmp_path / name for name in ("data", "runtime", "logs"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir(mode=0o700)
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("TWOS_", "GIT_"))
        and not any(key.startswith(prefix) for prefix in twos_bootstrap.SENSITIVE_CHILD_PREFIXES)
        and key not in twos_bootstrap.PYTHON_INJECTION_VARIABLES
    }
    environment["HOME"] = str(empty_home)
    environment["PATH"] = str(tool_bin) + os.pathsep + environment.get("PATH", "")
    supplied = {
        "valid": json.dumps(verifier),
        "malformed": "[not-json",
        "non-array": json.dumps({"command": list(verifier)}),
        "invalid-argument": json.dumps([verifier[0], 7]),
        "relative-executable": json.dumps(["python3", verifier[1]]),
        "unavailable-executable": json.dumps([str(tmp_path / "missing-verifier")]),
    }
    if configuration in supplied:
        environment[VERIFIER_SETTING] = supplied[configuration]
    port = available_local_port()
    command = [
        str(source / "start-twos"), "--data-root", str(data),
        "--runtime-root", str(runtime), "--log-root", str(logs),
        "--port", str(port), "--detach", "--no-browser", "--health-timeout", "90",
    ]
    pid = None
    try:
        launched = subprocess.run(
            command, cwd=source, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=600, check=False,
        )
        parser_errors = {
            "malformed": "must be a JSON argument-vector array",
            "non-array": "must contain 1 to 32 arguments",
            "invalid-argument": "contains an invalid argument",
        }
        if configuration in parser_errors:
            assert launched.returncode == 2, launched.stderr
            assert "BLOCKED: TWOS exited during startup" in launched.stderr
            assert "See the private runtime log" in launched.stderr
            runtime_log = next(logs.rglob("runtime.log")).read_text()
            assert VERIFIER_SETTING + " " + parser_errors[configuration] in runtime_log
            assert "TWOS is ready" not in launched.stdout
            assert not (data / "twos.sqlite3").exists()
            assert not probe_marker.exists()
            return

        assert launched.returncode == 0, launched.stderr
        lines = launched.stdout.splitlines()
        pid = int(next(line.split(":", 1)[1] for line in lines if line.startswith("Runtime PID:")))
        code = next(line.split(":", 1)[1].strip() for line in lines
                    if line.startswith("Setup authorization code:"))
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
            assert client.get("/api/health").json()["schema"] == "vol20.001"
            assert client.post("/api/setup/start", json={"confirmation": "START_FIRST_RUN"}).status_code == 200
            assert client.post("/api/setup/start", json={"confirmation": "CONFIRM_INSTALLATION"}).status_code == 200
            password = "test-" + secrets.token_urlsafe(32)
            owner = client.post("/api/setup/owner", json={
                "username": "verifier-owner", "password": password,
                "password_confirmation": password, "setup_authorization": code,
                "request_id": "standard-startup-verifier-owner-0001",
            })
            assert owner.status_code == 201, owner.text
            assert client.post("/api/setup/workspace", json={
                "path": str(workspace), "create_if_missing": False,
            }).status_code == 200
            assert client.post("/api/setup/optional-tools", json={"decision": "skip"}).status_code == 200
            assert client.post("/api/setup/finish", json={"confirmation": "FINISH_FIRST_RUN"}).json()["state"] == "ready"
            setup = client.get("/api/guided-tool-setup").json()
            assert setup["discovery"]["executable"] == str(runner)
            assert setup["configuration"] is None
            assert setup["provider_request_performed"] is False
            assert not probe_marker.exists()
            checked = client.post("/api/guided-tool-setup/check", json=CHOICE)
            if configuration in {"valid", "missing"}:
                assert checked.status_code == 200, checked.text
                checked_config = checked.json()["configuration"]
                assert checked_config["ready"] is True, checked.text
                assert checked_config["confirmed"] is False
                assert probe_marker.is_file()  # Explicit local fixture readiness only.
                with sqlite3.connect(data / "twos.sqlite3") as connection:
                    snapshot = json.loads(connection.execute(
                        "SELECT snapshot_json FROM guided_tool_configurations WHERE id = ?",
                        (checked_config["id"],),
                    ).fetchone()[0])
                if configuration == "valid":
                    assert snapshot["verification"]["argv"] == list(verifier)
                else:
                    argv = snapshot["verification"]["argv"]
                    assert argv[1:] == ["-I", str(source / "twos_runtime" / "builtin_verifier.py")]
                    assert snapshot["verification"]["files"]
                assert snapshot["workspace"] == str(workspace)
            else:
                assert checked.status_code == 409, checked.text
                expected = ("Configure an independent local Verification command for First Delivery."
                            if configuration == "missing" else
                            "The independent verifier needs an absolute executable path.")
                assert checked.json()["error"]["message"] == expected
                assert not probe_marker.exists()
                assert client.get("/api/guided-tool-setup").json()["configuration"] is None
            with sqlite3.connect(data / "twos.sqlite3") as connection:
                for table in DELIVERY_TABLES:
                    assert connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
                if configuration not in {"valid", "missing"}:
                    assert connection.execute("SELECT COUNT(*) FROM codex_connectivity_evidence").fetchone()[0] == 0
                    assert connection.execute("SELECT COUNT(*) FROM guided_tool_configurations").fetchone()[0] == 0
    finally:
        if pid is None and (data / "runtime.pid").exists():
            # The private fresh directory belongs to this one bootstrap invocation.
            pid = int((data / "runtime.pid").read_text().strip())
        if pid is not None:
            terminate_owned_process(pid)
        assert twos_bootstrap.configured_live_pid(data / "runtime.pid") is None
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
        assert source_snapshot(source) == source_before
        assert list(workspace.iterdir()) == []
