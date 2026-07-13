from __future__ import annotations

import sqlite3
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from twos_runtime.app import create_app
from twos_runtime.codex_adapter import CodexAdapter
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings


OWNER_PASSWORD = "owner-password-123"


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
import pathlib
import subprocess
import sys
import time

if sys.argv[1:] == ["--version"]:
    print("codex-cli 1.0-test")
    raise SystemExit(0)
if sys.argv[1:] == ["exec", "--help"]:
    print("Usage: codex exec [PROMPT]")
    raise SystemExit(0)
if len(sys.argv) < 3 or sys.argv[1] != "exec":
    raise SystemExit(64)

prompt = sys.argv[2]
if "FAKE_TIMEOUT" in prompt or "FAKE_CANCEL" in prompt:
    time.sleep(10)
if "FAKE_FAIL" in prompt:
    print("fake execution failed", file=sys.stderr)
    raise SystemExit(3)

pathlib.Path("codex-result.txt").write_text("isolated result\\n")
if "FAKE_COMMIT" in prompt:
    subprocess.run(["git", "add", "codex-result.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "fake codex result"], check=True)
print("1 passed in fake validation")
"""
    )
    executable.chmod(0o755)
    return executable


def make_client(
    tmp_path: Path,
    source_repo: Path,
    codex_executable: Path,
    timeout: int = 5,
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
        codex_output_limit=20_000,
    )
    return TestClient(create_app(settings=settings, start_scheduler=False))


def init_and_login(client: TestClient) -> dict[str, str]:
    initialized = client.post("/api/auth/init", json={"username": "owner", "password": OWNER_PASSWORD})
    assert initialized.status_code in {200, 409}
    login = client.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_twos_short_url_uses_canonical_static_asset_base(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        page = client.get("/twos")
        assert page.status_code == 200
        assert page.url.path == "/static_cockpit/vol12_static_mvp/twos_command_center.html"
        assert '<link rel="stylesheet" href="./styles.css"' in page.text
        stylesheet = client.get("/static_cockpit/vol12_static_mvp/styles.css")
        assert stylesheet.status_code == 200
        assert ".global-owner-header" in stylesheet.text


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
        approved = approve_pack(client, headers, task_id, first["id"])
        assert approved["approved"] is True

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


def test_codex_success_git_result_acceptance_and_compact_sync(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    baseline = run_command(source_repo, "git", "rev-parse", "HEAD").stdout.strip()
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        headers = init_and_login(client)
        task_id = create_development_task(client, headers, marker="FAKE_COMMIT")
        pack = generate_pack(client, headers, task_id)
        approve_pack(client, headers, task_id, pack["id"])
        started = client.post(f"/api/tasks/{task_id}/codex-runs", headers=headers)
        assert started.status_code == 200, started.text
        run = wait_for_run(client, headers, started.json()["id"], {"completed", "needs_review"})
        assert run["status"] == "completed"
        assert run["source_commit"] == baseline
        assert run["worktree_branch"].startswith("twos/codex-run-")
        assert run["result"]["changed_files"] == ["codex-result.txt"]
        assert run["result"]["commits"]
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
        cancelled = client.post(f"/api/codex-runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        run = wait_for_run(client, headers, run_id, {"cancelled"}, timeout=5)
        assert run["cancelled"] is True


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
