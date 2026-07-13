from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from twos_runtime.app import create_app
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import AIModel, Provider, RoutingDecision
from twos_runtime.provider_gateway import ProviderExecutionUnavailable, ProviderGateway


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


def create_project_task(
    client: TestClient,
    headers: dict[str, str],
    project_key: str,
    title: str,
    required_output: str,
) -> int:
    projects = client.get("/api/projects", headers=headers).json()
    project = next(item for item in projects if item["key"] == project_key)
    response = client.post(
        "/api/tasks",
        headers=headers,
        json={
            "project_id": project["id"],
            "title": title,
            "action": "Analyze",
            "source_sync_summary": "Owner-provided source sync.",
            "required_output": required_output,
            "boundary_risk": "No live trading or live betting execution.",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


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


def test_ai_capability_provider_and_model_registries_are_honest(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        capabilities = client.get("/api/ai/capabilities", headers=headers)
        providers = client.get("/api/providers", headers=headers)
        models = client.get("/api/models", headers=headers)

        assert capabilities.status_code == 200
        assert {item["name"] for item in capabilities.json()} == {
            "reasoning",
            "coding",
            "research",
            "verification",
            "summarization",
            "planning",
            "risk_analysis",
            "data_analysis",
        }
        assert providers.status_code == 200
        assert {item["name"] for item in providers.json()} == {
            "OpenAI",
            "Gemini",
            "Claude",
            "DeepSeek",
            "GLM",
        }
        assert all(item["status"] == "unconfigured" and item["available"] is False for item in providers.json())

        assert models.status_code == 200
        assert len(models.json()) == 10
        assert all(item["status"] == "unconfigured" and item["available"] is False for item in models.json())
        models_per_provider = {
            provider: len([item for item in models.json() if item["provider"] == provider])
            for provider in {item["provider"] for item in models.json()}
        }
        assert all(count >= 2 for count in models_per_provider.values())

        factory = client.app.state.session_factory
        with factory() as session:
            gateway = ProviderGateway.from_session(session)
            adapter = gateway.get("OpenAI")
            assert adapter is not None
            assert len(adapter.list_models()) == 2
            assert adapter.health_check().available is False
            with pytest.raises(ProviderExecutionUnavailable):
                adapter.execute({"prompt": "must not leave the local runtime"})


def test_ai_team_composition_and_unavailable_routing_persist(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        twos_task_id = create_project_task(
            client,
            headers,
            "twos",
            "TWOS Product Build",
            "Implement the owner-visible AI Team and routing decision surface.",
        )
        product_response = client.post(
            "/api/ai/team-compose",
            headers=headers,
            json={"task_id": twos_task_id, "risk_level": "medium", "urgency": "normal"},
        )
        assert product_response.status_code == 200
        product_plan = product_response.json()
        assert product_plan["required_capabilities"] == ["planning", "coding", "verification"]
        assert product_plan["minimum_role_count"] == 3
        assert "ordered build plan" in product_plan["explanation"]
        product_reasons = {item["capability"]: item["selection_reason"] for item in product_plan["team"]}
        assert "implementation path" in product_reasons["planning"]
        assert "implementation artifact" in product_reasons["coding"]
        assert "acceptance conditions" in product_reasons["verification"]
        assert {item["capability"] for item in product_plan["omitted_capabilities"]} == {
            "reasoning",
            "research",
            "summarization",
            "risk_analysis",
            "data_analysis",
        }
        assert "Not added" in product_plan["omission_explanation"]

        product_routes = product_plan["routes"]
        assert len(product_routes) == 3
        for decision in product_routes:
            assert decision["status"] == "unavailable"
            assert decision["selected"] is None
            assert decision["fallback"] is None
            assert decision["requested_capabilities"] == ["planning", "coding", "verification"]
            assert decision["reason"] == (
                "No configured and healthy provider is available for the requested capabilities."
            )
            assert decision["fallback_status"] == "unavailable"
            assert decision["fallback_reason"] == (
                "No fallback is available because all compatible providers are unconfigured."
            )
            assert decision["next_action"] == (
                "Configure and verify at least one compatible provider, then recompose the AI Team."
            )
        assert product_plan["routing_summary"]["status"] == "unavailable"
        assert product_plan["routing_summary"]["evaluation_completed"] is True

        ldd_task_id = create_project_task(
            client,
            headers,
            "ldd",
            "LDD Risk Review",
            "Review SPCX downside and admission gates with owner-readable acceptance evidence.",
        )
        composed = client.post(
            "/api/ai/team-compose",
            headers=headers,
            json={"task_id": ldd_task_id, "risk_level": "medium", "urgency": "normal"},
        )
        assert composed.status_code == 200
        ldd_plan = composed.json()
        assert ldd_plan["required_capabilities"] == ["reasoning", "risk_analysis", "verification"]
        assert ldd_plan["required_capabilities"] != product_plan["required_capabilities"]
        assert ldd_plan["minimum_role_count"] == 3
        assert "downside and admission-gate review" in ldd_plan["explanation"]
        ldd_reasons = {item["capability"]: item["selection_reason"] for item in ldd_plan["team"]}
        assert "supplied LDD evidence" in ldd_reasons["reasoning"]
        assert "downside, admission gates" in ldd_reasons["risk_analysis"]
        assert "no live trading action" in ldd_reasons["verification"]
        assert "bounded risk review" in ldd_plan["omission_explanation"]
        assert len(ldd_plan["routes"]) == 3
        assert all(item["status"] == "unavailable" for item in ldd_plan["routes"])
        assert ldd_plan["routing_summary"]["status"] == "unavailable"
        assert all("provider" not in item and "model" not in item for item in ldd_plan["team"])

        persisted = client.get(f"/api/tasks/{ldd_task_id}/ai-plan", headers=headers)
        assert persisted.status_code == 200
        assert persisted.json()["plan"]["id"] == ldd_plan["id"]
        assert len(persisted.json()["routes"]) == 3
        assert persisted.json()["routing_summary"]["evaluation_completed"] is True

    with make_client(tmp_path) as restarted:
        headers = init_and_login(restarted)
        persisted_ldd = restarted.get(f"/api/tasks/{ldd_task_id}/ai-plan", headers=headers)
        persisted_product = restarted.get(f"/api/tasks/{twos_task_id}/ai-plan", headers=headers)
        assert persisted_ldd.status_code == 200
        assert persisted_product.status_code == 200
        assert persisted_ldd.json()["plan"]["required_capabilities"] == [
            "reasoning",
            "risk_analysis",
            "verification",
        ]
        assert persisted_product.json()["plan"]["required_capabilities"] == [
            "planning",
            "coding",
            "verification",
        ]
        assert len(persisted_ldd.json()["routes"]) == 3
        assert len(persisted_product.json()["routes"]) == 3
        assert persisted_ldd.json()["routing_summary"]["evaluation_completed"] is True
        assert persisted_product.json()["routing_summary"]["evaluation_completed"] is True


def test_saved_task_context_updates_and_recomposes_in_place(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        task_id = create_project_task(
            client,
            headers,
            "twos",
            "TWOS Product Build",
            "Implement an owner-visible workbench surface.",
        )
        first_plan = client.post(
            "/api/ai/team-compose",
            headers=headers,
            json={"task_id": task_id},
        ).json()
        assert first_plan["required_capabilities"] == ["planning", "coding", "verification"]

        projects = client.get("/api/projects", headers=headers).json()
        ldd = next(item for item in projects if item["key"] == "ldd")
        updated = client.patch(
            f"/api/tasks/{task_id}",
            headers=headers,
            json={
                "project_id": ldd["id"],
                "title": "LDD Risk Review",
                "action": "Analyze",
                "source_sync_summary": "SPCX and admission-gate evidence.",
                "required_output": "Review downside and admission gates.",
                "boundary_risk": "No live trading execution.",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["project"]["key"] == "ldd"
        second_plan = client.post(
            "/api/ai/team-compose",
            headers=headers,
            json={"task_id": task_id},
        ).json()
        assert second_plan["required_capabilities"] == ["reasoning", "risk_analysis", "verification"]
        assert second_plan["id"] != first_plan["id"]
        assert len(client.get("/api/tasks", headers=headers).json()) == 1
        latest = client.get(f"/api/tasks/{task_id}/ai-plan", headers=headers).json()
        assert latest["plan"]["id"] == second_plan["id"]
        assert latest["routing_summary"]["evaluation_completed"] is True


def test_routing_selects_healthy_models_and_falls_back_from_failed_provider(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        task_id = create_project_task(
            client,
            headers,
            "ldd",
            "Analyze LDD risk",
            "Reasoning and verification output.",
        )
        factory = client.app.state.session_factory
        with factory() as session:
            providers = {
                item.name: item
                for item in session.scalars(select(Provider).where(Provider.kind == "model")).all()
            }
            for provider_name in ("OpenAI", "Claude", "Gemini"):
                providers[provider_name].status = "healthy"
                providers[provider_name].enabled = True
            providers["DeepSeek"].status = "blocked"
            providers["DeepSeek"].enabled = True

            for model in session.scalars(select(AIModel)).all():
                if "reasoning" in model.capability_tags and model.provider.name in {
                    "OpenAI",
                    "Claude",
                    "Gemini",
                    "DeepSeek",
                }:
                    model.status = "healthy"
                    model.cost_metadata = "medium"
                    model.latency_metadata = "medium"
            session.commit()

        first = client.post(
            "/api/ai/route",
            headers=headers,
            json={"task_id": task_id, "capability": "reasoning"},
        )
        assert first.status_code == 200
        assert first.json()["status"] == "selected"
        assert first.json()["selected"]["provider"] == "OpenAI"
        assert first.json()["fallback"]["provider"] == "Claude"

        with factory() as session:
            openai = session.scalar(select(Provider).where(Provider.name == "OpenAI"))
            openai.status = "failed"
            session.commit()

        second = client.post(
            "/api/ai/route",
            headers=headers,
            json={"task_id": task_id, "capability": "reasoning"},
        )
        assert second.status_code == 200
        assert second.json()["selected"]["provider"] == "Claude"
        assert second.json()["fallback"]["provider"] == "Gemini"
        assert second.json()["selected"]["provider"] != "DeepSeek"

        with factory() as session:
            decisions = session.scalars(
                select(RoutingDecision).where(RoutingDecision.task_id == task_id).order_by(RoutingDecision.id)
            ).all()
            assert len(decisions) == 2
            assert decisions[0].fallback_model_id is not None
