from __future__ import annotations

import json
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
    signup = client.post("/api/auth/signup", json={"username": "owner", "password": OWNER_PASSWORD})
    assert signup.status_code in (201, 409)
    if signup.status_code == 409:
        login = client.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD})
        assert login.status_code == 200
        assert "token" not in login.json()
    else:
        assert signup.json() == {"authenticated": True, "user": {"username": "owner"}}
    return {}


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


def add_test_model(
    session,
    *,
    provider_name: str,
    model_name: str,
    capabilities: tuple[str, ...],
    priority: int,
    provider_status: str = "healthy",
    provider_enabled: bool = True,
    model_status: str = "healthy",
    configuration_status: str = "configured",
    availability_status: str = "available",
    invocation_mode: str = "real",
) -> AIModel:
    """Create explicit, metadata-only registry state for a local test."""
    provider = session.scalar(
        select(Provider).where(Provider.name == provider_name, Provider.kind == "model")
    )
    if provider is None:
        provider = Provider(
            name=provider_name,
            kind="model",
            status=provider_status,
            enabled=provider_enabled,
            details="Explicit test fixture; no external execution adapter is configured.",
        )
        session.add(provider)
        session.flush()
    else:
        provider.status = provider_status
        provider.enabled = provider_enabled

    model = AIModel(
        provider_id=provider.id,
        model_name=model_name,
        display_name=model_name,
        provider_model_id=f"fixture/{model_name}",
        execution_adapter="metadata_only_test_fixture",
        capability_tags=json.dumps(list(capabilities), separators=(",", ":")),
        context_limit=8192,
        cost_metadata="medium",
        latency_metadata="medium",
        status=model_status,
        configuration_status=configuration_status,
        availability_status=availability_status,
        invocation_mode=invocation_mode,
        last_invocation_outcome="not_invoked",
        evidence_status="unverified",
        evidence_source="manual_record",
        safe_diagnostic="Explicit test fixture; no provider request was sent.",
        routing_priority=priority,
    )
    session.add(model)
    session.flush()
    return model


def add_reasoning_routing_fixtures(session) -> dict[str, AIModel]:
    return {
        provider_name: add_test_model(
            session,
            provider_name=provider_name,
            model_name=f"fixture-{provider_name.casefold()}-reasoning",
            capabilities=("reasoning", "verification"),
            priority=priority,
            provider_status="blocked" if provider_name == "DeepSeek" else "healthy",
        )
        for priority, provider_name in enumerate(
            ("OpenAI", "Claude", "Gemini", "DeepSeek"),
            start=10,
        )
    }


def test_auth_health_and_protected_routes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"
        protected = client.get("/api/projects")
        assert protected.status_code == 401
        headers = init_and_login(client)
        session = client.get("/api/auth/session", headers=headers)
        assert session.status_code == 200
        assert session.json() == {"authenticated": True, "user": {"username": "owner"}}


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
        assert providers.json() == []
        tool_statuses = {item["status"] for item in tools.json()}
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
        assert providers.json() == []

        assert models.status_code == 200
        assert models.json() == []

        factory = client.app.state.session_factory
        with factory() as session:
            assert session.scalars(select(Provider).where(Provider.kind == "model")).all() == []
            assert session.scalars(select(AIModel)).all() == []
            assert ProviderGateway.from_session(session).adapters() == []

            explicit_model = add_test_model(
                session,
                provider_name="OpenAI",
                model_name="fixture-openai-metadata-only",
                capabilities=("reasoning", "planning"),
                priority=10,
            )
            session.commit()
            gateway = ProviderGateway.from_session(session)
            adapter = gateway.get("OpenAI")
            assert adapter is not None
            assert adapter.list_models() == [
                {
                    "model_name": explicit_model.model_name,
                    "capability_tags": ["reasoning", "planning"],
                    "status": "healthy",
                }
            ]
            assert adapter.health_check().available is True
            with pytest.raises(ProviderExecutionUnavailable):
                adapter.execute({"prompt": "must not leave the local runtime"})


def test_frontend_model_readiness_requires_verified_invocation_evidence() -> None:
    javascript = (TWOS_UI_PATH.parent / "twos_command_center.js").read_text(encoding="utf-8")
    configured_branch_start = javascript.index(
        'if (modelRecord.configuration_status === "configured" '
        '&& modelRecord.availability_status === "available")'
    )
    configured_branch_end = javascript.index("\n    if (route && route.status)", configured_branch_start)
    configured_branch = javascript[configured_branch_start:configured_branch_end]

    assert 'modelRecord.evidence_status === "verified" && modelRecord.last_verified_at' in configured_branch
    assert '? "ready"\n        : "runtime_available_model_configured_not_invoked";' in configured_branch
    assert 'return "Runtime available / Model configured / Not yet invoked";' in javascript


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
                f"No registered model declares support for the requested {decision['capability']} capability."
            )
            assert decision["fallback_status"] == "unavailable"
            assert decision["fallback_reason"] == (
                "No fallback is available because the model registry has no compatible candidate."
            )
            assert decision["next_action"] == (
                "Register a compatible model profile, then recompose the AI Team."
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
            fixtures = add_reasoning_routing_fixtures(session)
            assert set(fixtures) == {"OpenAI", "Claude", "Gemini", "DeepSeek"}
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


def test_routing_rejects_registry_unavailable_model_despite_healthy_legacy_status(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        headers = init_and_login(client)
        task_id = create_project_task(
            client,
            headers,
            "ldd",
            "Reject unavailable reasoning model",
            "No unavailable registry model may be selected.",
        )
        factory = client.app.state.session_factory
        with factory() as session:
            openai_reasoning = add_test_model(
                session,
                provider_name="OpenAI",
                model_name="fixture-openai-unavailable-reasoning",
                capabilities=("reasoning",),
                priority=10,
                availability_status="unavailable",
            )
            assert openai_reasoning.provider.status == "healthy"
            session.commit()

        response = client.post(
            "/api/ai/route",
            headers=headers,
            json={"task_id": task_id, "capability": "reasoning"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["selected"] is None
        assert payload["fallback"] is None
