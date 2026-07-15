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

from twos_runtime.app import create_app
from twos_runtime.codex_adapter import CodexAdapter
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings


OWNER_PASSWORD = "owner-password-123"
CODEX_EXEC_ARGS = [
    "exec",
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
    print("Usage: codex exec [PROMPT]")
    raise SystemExit(0)

expected_args = [
    "exec",
    "--sandbox",
    "workspace-write",
    "--ephemeral",
    "--ignore-user-config",
    "--color",
    "never",
    "-",
]
if sys.argv[1:] != expected_args:
    print("unexpected fixed argv", file=sys.stderr)
    raise SystemExit(64)

prompt = sys.stdin.read()
pathlib.Path(__file__).with_name(pathlib.Path(__file__).name + ".executed").write_text("executed\\n")
if "FAKE_TRANSPORT" in prompt:
    forbidden = [
        key
        for key in ("TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET")
        if key in os.environ
    ]
    if forbidden:
        print("forbidden environment reached Codex", file=sys.stderr)
        raise SystemExit(78)
    print("argv=" + json.dumps(sys.argv[1:], separators=(",", ":")))
    print("stdin_sha256=" + hashlib.sha256(prompt.encode("utf-8")).hexdigest())
    print("env_keys=" + json.dumps(sorted(os.environ), separators=(",", ":")))
    print("NO_COLOR=" + os.environ.get("NO_COLOR", ""))
    print("GIT_TERMINAL_PROMPT=" + os.environ.get("GIT_TERMINAL_PROMPT", ""))
if "FAKE_OUTPUT_CAP_UTF8" in prompt:
    sys.stdout.buffer.write(("界" * 10_000).encode("utf-8"))
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(b"\\xff" * 10_000)
    sys.stderr.buffer.flush()
elif "FAKE_OUTPUT_CAP" in prompt:
    sys.stdout.write("O" * 10_000 + "\\n")
    sys.stdout.flush()
    sys.stderr.write("E" * 10_000 + "\\n")
    sys.stderr.flush()
if "FAKE_TIMEOUT" in prompt or "FAKE_CANCEL" in prompt:
    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib,time;time.sleep(1.5);pathlib.Path('child-survived.txt').write_text('survived\\n')",
        ]
    )
    time.sleep(10)
if "FAKE_FAIL" in prompt:
    print("fake execution failed", file=sys.stderr)
    raise SystemExit(3)

pathlib.Path("codex-result.txt").write_text(
    "trailing whitespace   \\n" if "FAKE_BAD_WHITESPACE" in prompt else "isolated result\\n"
)
if "FAKE_COMMIT" in prompt:
    subprocess.run(["git", "add", "codex-result.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "fake codex result"], check=True)
print("1 passed in fake validation")
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
    help_text: str = "Usage: codex exec [PROMPT]",
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
        "    print('Usage: codex exec [PROMPT]')\n"
        "    raise SystemExit(0)\n"
        f"if sys.argv[1:] != {CODEX_EXEC_ARGS!r}:\n"
        "    raise SystemExit(64)\n"
        "time.sleep(10)\n"
    )
    executable.chmod(0o755)
    return executable


def make_client(
    tmp_path: Path,
    source_repo: Path,
    codex_executable: Path,
    timeout: int = 5,
    output_limit: int = 20_000,
) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'twos-self-hosting.sqlite3'}",
        scheduler_poll_seconds=0.05,
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "worktrees",
        codex_executable=str(codex_executable),
        codex_timeout_seconds=timeout,
        codex_output_limit=output_limit,
    )
    return TestClient(create_app(settings=settings, start_scheduler=False))


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


def test_twos_short_url_uses_canonical_static_asset_base(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        page = client.get("/twos")
        assert page.status_code == 200
        assert page.url.path == "/static_cockpit/vol12_static_mvp/twos_command_center.html"
        assert 'href="./styles.css' in page.text
        assert 'src="./twos_command_center.js' in page.text
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


def generate_pack(client: TestClient, headers: dict[str, str], task_id: int) -> dict:
    response = client.post(f"/api/tasks/{task_id}/codex-packs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def approve_pack(client: TestClient, headers: dict[str, str], task_id: int, pack_id: int) -> dict:
    response = client.post(f"/api/tasks/{task_id}/codex-packs/{pack_id}/approve", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


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


def test_codex_detection_requires_both_capability_commands_to_succeed(tmp_path: Path) -> None:
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


def test_codex_detection_and_approval_required(tmp_path: Path) -> None:
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
        status = client.get("/api/codex/status", headers=headers).json()
        assert status["status"] == "configured"
        assert status["source"]["clean"] is True
        task_id = create_development_task(client, headers)
        generate_pack(client, headers, task_id)
        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409
        assert "Approve" in blocked.json()["error"]["message"]


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
        task_id = create_development_task(client, headers, marker=marker)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "failed"})

    assert run["status"] == "completed", run
    expected_argv = json.dumps(CODEX_EXEC_ARGS, separators=(",", ":"))
    expected_hash = hashlib.sha256(pack["content"].encode("utf-8")).hexdigest()
    assert f"argv={expected_argv}" in run["stdout"]
    assert f"stdin_sha256={expected_hash}" in run["stdout"]
    assert "forbidden environment reached Codex" not in run["stderr"]
    env_line = next(line for line in run["stdout"].splitlines() if line.startswith("env_keys="))
    reported_env_keys = set(json.loads(env_line.removeprefix("env_keys=")))
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
    }
    assert all(key in fixed_allowed_keys or key.startswith("LC_") for key in manager_env)
    assert {"PATH", "HOME", "NO_COLOR", "GIT_TERMINAL_PROMPT"}.issubset(manager_env)
    assert manager_env["NO_COLOR"] == "1"
    assert manager_env["GIT_TERMINAL_PROMPT"] == "0"
    assert {"TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET"}.isdisjoint(manager_env)
    assert {"TWOS_OA005_SENTINEL", "OPENAI_API_KEY", "SESSION_SECRET"}.isdisjoint(reported_env_keys)
    assert "NO_COLOR=1" in run["stdout"].splitlines()
    assert "GIT_TERMINAL_PROMPT=0" in run["stdout"].splitlines()
    worktree = Path(run["worktree_path"])
    for root in (source_repo, worktree):
        assert not (root / "shell-injection").exists()
        assert not (root / "shell-injection-2").exists()


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
        task_id = create_development_task(client, headers, marker="FAKE_OUTPUT_CAP")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "failed"})

    assert run["status"] == "completed", run
    persisted_output = run["stdout"].encode("utf-8") + run["stderr"].encode("utf-8")
    assert len(persisted_output) <= output_limit
    assert run["output_truncated"] is True
    if output_limit >= len("\n[output truncated by TWOS]"):
        assert "[output truncated by TWOS]" in run["stdout"] + run["stderr"]


def test_codex_output_cap_is_byte_safe_for_multibyte_and_invalid_utf8(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, output_limit=128) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers, marker="FAKE_OUTPUT_CAP_UTF8")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "failed"})

    assert run["status"] == "completed", run
    persisted = run["stdout"].encode("utf-8") + run["stderr"].encode("utf-8")
    assert len(persisted) <= 128
    assert run["output_truncated"] is True


def test_large_pack_cannot_block_timeout_while_cli_ignores_stdin(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_nonreading_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=1) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers)
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


def test_codex_run_rejects_dirty_source_without_queuing(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers)
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        (source_repo / "owner-unstaged-change.txt").write_text("preserve me\n")

        blocked = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["message"] == "Source repository must be clean before Codex execution."
        assert client.get(f"/api/tasks/{task_id}/codex-runs", headers=headers).json() == []
        assert not fake_codex.with_name(fake_codex.name + ".executed").exists()


def test_untracked_file_whitespace_failure_cannot_complete(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers, marker="FAKE_BAD_WHITESPACE")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200
        run = wait_for_run(client, headers, started.json()["id"], {"needs_review"})

    assert run["result"]["validation"]["diff_check"] is False
    assert run["result"]["changed_files"] == ["codex-result.txt"]


def test_codex_commit_cannot_satisfy_uncommitted_execution_boundary(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    baseline = run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip()
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers, marker="FAKE_COMMIT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200
        run = wait_for_run(client, headers, started.json()["id"], {"needs_review"})

    assert run["result"]["commits"]
    assert run["result"]["boundary_confirmation"]["source_main_unchanged"] is True
    assert run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip() == baseline


def test_concurrent_run_requests_queue_exactly_one_process(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers, marker="FAKE_CANCEL")
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
        wait_for_run(client, headers, runs[0]["id"], {"running"}, timeout=3)
        cancelled = client.post(f"/api/codex-runs/{runs[0]['id']}/cancel", headers=headers)
        assert cancelled.status_code == 200
        wait_for_run(client, headers, runs[0]["id"], {"cancelled"}, timeout=5)


def test_codex_rechecks_exact_pack_approval_before_process_spawn(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    fake_codex.with_name(fake_codex.name + ".delay-second-detection").write_text("delay\n")
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers)
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
            {"failed", "cancelled", "needs_review"},
            timeout=5,
        )

    assert run["pack_id"] == pack["id"]
    assert run["worktree_path"] == ""
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
        task_id = create_development_task(client, headers, marker="FAKE_SUCCESS")
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
        assert "1 passed" in run["result"]["tests_reported"][0]
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
        acceptance = restarted.get(f"/api/tasks/{task_id}/owner-acceptance", headers=headers).json()["acceptance"]
        assert acceptance["status"] == "accepted"
        assert acceptance["compact_sync_result"]


def test_codex_failure_timeout_and_cancel(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex, timeout=1) as client:
        headers = init_and_login(client)
        for marker, expected in [("FAKE_FAIL", "failed"), ("FAKE_TIMEOUT", "timed_out")]:
            task_id = create_development_task(client, headers, marker=marker)
            pack = generate_pack(client, headers, task_id)
            approve_pack(client, headers, task_id, pack["id"])
            started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
            assert started.status_code == 200
            run = wait_for_run(client, headers, started.json()["id"], {expected}, timeout=8)
            assert run["status"] == expected
            if marker == "FAKE_TIMEOUT":
                assert run["timed_out"] is True
                assert run["result"]["process"]["timed_out"] is True
                assert run["result"]["process"]["cancelled"] is False
                time.sleep(1.7)
                assert not (Path(run["worktree_path"]) / "child-survived.txt").exists()
                assert "child-survived.txt" not in run["result"]["changed_files"]
            if marker == "FAKE_FAIL":
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

        cancel_task_id = create_development_task(client, headers, marker="FAKE_CANCEL")
        pack = generate_pack(client, headers, cancel_task_id)
        approve_pack(client, headers, cancel_task_id, pack["id"])
        started = client.post(f"/api/tasks/{cancel_task_id}/codex-runs", headers=headers)
        run_id = started.json()["id"]
        wait_for_run(client, headers, run_id, {"running"}, timeout=3)
        duplicate = client.post(f"/api/tasks/{cancel_task_id}/codex-runs", headers=headers)
        assert duplicate.status_code == 409
        assert "already queued or running" in duplicate.json()["error"]["message"]
        cancelled = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        run = wait_for_run(client, headers, run_id, {"cancelled"}, timeout=5)
        assert run["cancelled"] is True
        assert run["timed_out"] is False
        assert run["result"]["process"]["cancelled"] is True
        assert run["result"]["process"]["timed_out"] is False
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
