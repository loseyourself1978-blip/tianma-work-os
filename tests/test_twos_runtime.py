from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from twos_runtime.app import create_app
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings


OWNER_PASSWORD = "owner-password-123"


def make_client(tmp_path: Path, start_scheduler: bool = False) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'twos-test.sqlite3'}",
        scheduler_poll_seconds=0.05,
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
    )
    app = create_app(settings=settings, start_scheduler=start_scheduler)
    return TestClient(app)


def init_and_login(client: TestClient) -> dict[str, str]:
    init = client.post("/api/auth/init", json={"username": "owner", "password": OWNER_PASSWORD})
    assert init.status_code in (200, 409)
    login = client.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD})
    assert login.status_code == 200
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def create_runtime_task(client: TestClient, headers: dict[str, str]) -> int:
    projects = client.get("/api/projects", headers=headers)
    assert projects.status_code == 200
    twos = next(item for item in projects.json() if item["key"] == "twos")
    task = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "project_id": twos["id"],
            "title": "Runtime foundation compact sync",
            "action": "Compact Sync",
            "source_sync_summary": "Pasted TWOS compact sync for owner verification.",
            "required_output": "Persisted compact sync with audit trail.",
            "boundary_risk": "External providers unconfigured; live trading and live betting blocked.",
        },
    )
    assert task.status_code == 200
    return task.json()["id"]


def test_auth_health_and_protected_routes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"
        protected = client.get("/api/projects")
        assert protected.status_code == 401
        headers = init_and_login(client)
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["owner"]["username"] == "owner"


def test_task_persists_run_now_compact_sync_and_auto_accept(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        task_id = create_runtime_task(client, headers)
        run = client.post(f"/api/tasks/{task_id}/run", headers=headers, json={"action": "compact_sync"})
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "accepted"
        assert "Vol.15 MVP-14 Sync" in body["result"]
        tasks = client.get("/api/tasks", headers=headers).json()
        task = next(item for item in tasks if item["id"] == task_id)
        assert task["action"] == "Compact Sync"
        assert task["source_sync_summary"] == "Pasted TWOS compact sync for owner verification."
        assert task["status"] == "accepted"
        assert task["acceptance_state"] == "accepted"
        assert "Vol.15 MVP-14 Sync" in task["compact_sync_result"]
        audit = client.get("/api/audit", headers=headers)
        assert audit.status_code == 200
        assert any(item["action"] == "task_run_completed" for item in audit.json())
        acceptance = client.get(f"/api/tasks/{task_id}/acceptance", headers=headers)
        assert acceptance.status_code == 200
        evidence = acceptance.json()
        assert evidence["display_decision"] == "Accepted automatically"
        assert evidence["reason"] == "All deterministic checks passed."
        assert evidence["audit_created"] is True
        assert evidence["engine"] == "deterministic_compact_sync_v1"
        assert {item["id"] for item in evidence["checks"]} == {
            "required_output_generated",
            "boundary_check_passed",
            "result_persisted",
        }
        assert all(item["passed"] for item in evidence["checks"])

    with make_client(tmp_path) as restarted:
        headers = init_and_login(restarted)
        tasks = restarted.get("/api/tasks", headers=headers)
        assert tasks.status_code == 200
        persisted = next(item for item in tasks.json() if item["id"] == task_id)
        assert persisted["compact_sync_result"]
        assert persisted["source_sync_summary"] == "Pasted TWOS compact sync for owner verification."
        assert restarted.get(f"/api/tasks/{task_id}/acceptance", headers=headers).json()["record_count"] == 1


def wait_for_run_count(
    client: TestClient,
    headers: dict[str, str],
    task_id: int,
    expected: int,
    timeout: float = 5.0,
) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = [item for item in client.get("/api/runs", headers=headers).json() if item["task_id"] == task_id]
        if len(runs) >= expected:
            return runs
        time.sleep(0.1)
    raise AssertionError(f"Expected {expected} runs before timeout")


def test_recurring_schedule_runs_pauses_resumes_and_persists(tmp_path: Path) -> None:
    with make_client(tmp_path, start_scheduler=True) as client:
        headers = init_and_login(client)
        task_id = create_runtime_task(client, headers)
        created = client.post(
            "/api/schedules",
            headers=headers,
            json={"task_id": task_id, "name": "Compact sync heartbeat", "interval_seconds": 1},
        )
        assert created.status_code == 200
        schedule_id = created.json()["id"]
        first_runs = wait_for_run_count(client, headers, task_id, 3)
        assert all(item["status"] == "accepted" for item in first_runs)

        paused = client.patch(f"/api/schedules/{schedule_id}", headers=headers, json={"paused": True})
        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        assert paused.json()["next_run_at"] is None
        paused_count = len([item for item in client.get("/api/runs", headers=headers).json() if item["task_id"] == task_id])
        time.sleep(1.3)
        assert len([item for item in client.get("/api/runs", headers=headers).json() if item["task_id"] == task_id]) == paused_count

        resumed = client.patch(f"/api/schedules/{schedule_id}", headers=headers, json={"paused": False})
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
        assert resumed.json()["next_run_at"]
        runs = wait_for_run_count(client, headers, task_id, paused_count + 1)
        acceptance = client.get(f"/api/tasks/{task_id}/acceptance", headers=headers).json()
        assert acceptance["record_count"] == len(runs)
        schedules = client.get("/api/schedules", headers=headers).json()
        assert next(item for item in schedules if item["id"] == schedule_id)["run_count"] == len(runs)
        audit = client.get("/api/audit", headers=headers).json()
        assert len([item for item in audit if item["action"] == "schedule_run_completed" and item["entity_id"] == schedule_id]) == len(runs)

    with make_client(tmp_path) as restarted:
        headers = init_and_login(restarted)
        schedules = restarted.get("/api/schedules", headers=headers).json()
        persisted_schedule = next(item for item in schedules if item["id"] == schedule_id)
        assert persisted_schedule["last_run_at"]
        persisted_runs = [item for item in restarted.get("/api/runs", headers=headers).json() if item["task_id"] == task_id]
        assert len(persisted_runs) >= 4
        assert persisted_schedule["run_count"] == len(persisted_runs)
        assert restarted.get(f"/api/tasks/{task_id}/acceptance", headers=headers).json()["record_count"] == len(persisted_runs)


def test_live_trade_and_live_bet_are_policy_denied(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        task_id = create_runtime_task(client, headers)
        for action in ("live_trade", "live_bet"):
            denied = client.post(f"/api/tasks/{task_id}/run", headers=headers, json={"action": action})
            assert denied.status_code == 403
            assert action in denied.json()["error"]["message"]


def test_provider_and_tool_statuses_are_honest(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        providers = client.get("/api/providers", headers=headers)
        tools = client.get("/api/tools", headers=headers)
        assert providers.status_code == 200
        assert tools.status_code == 200
        provider_statuses = {item["status"] for item in providers.json()}
        tool_statuses = {item["status"] for item in tools.json()}
        assert "unconfigured" in provider_statuses
        assert "unconfigured" in tool_statuses
        assert any(item["kind"] == "live_trade" and item["status"] == "blocked" for item in tools.json())
        assert any(item["kind"] == "live_bet" and item["status"] == "blocked" for item in tools.json())
