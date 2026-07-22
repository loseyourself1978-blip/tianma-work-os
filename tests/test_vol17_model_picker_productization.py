from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import twos_runtime.codex_adapter as codex_adapter_module
from test_self_hosting import (
    OWNER_PASSWORD,
    approve_pack,
    create_development_task,
    generate_pack,
    init_and_login,
    make_client,
    make_fake_codex,
    make_source_repo,
)
from twos_runtime.ai_orchestration import latest_model_assignments
from twos_runtime.codex_adapter import (
    CodexAdapter,
    CodexDetection,
    CodexModelCatalog,
    CodexModelCatalogEntry,
)
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import (
    AIModel,
    AIModelAssignment,
    AIModelAvailabilityEvidence,
    AIModelInvocationEvidence,
    CodexInstructionPack,
    CodexRun,
    Provider,
    RoutingDecision,
)


CATALOG_MODEL_IDS = ("gpt-5.6-sol", "gpt-5.5", "gpt-5.6-terra")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'catalog-unit.sqlite3'}",
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=tmp_path,
        worktree_root=tmp_path / "worktrees",
        codex_executable=str(tmp_path / "controlled-codex"),
    )


def _detection() -> CodexDetection:
    return CodexDetection(
        status="configured",
        found=True,
        executable="/controlled/codex",
        version="codex-cli 0.144.4",
        supported_command="codex exec --json",
        reason="Controlled non-inference fixture.",
        next_action="No action required.",
    )


def _entry(
    model_id: str,
    *,
    aliases: tuple[str, ...] = (),
    selectable: bool = True,
    provider_id: str = "local_codex_cli",
    adapter_id: str = "codex_cli",
) -> CodexModelCatalogEntry:
    return CodexModelCatalogEntry(
        adapter_id=adapter_id,
        provider_id=provider_id,
        canonical_model_id=model_id,
        display_name=model_id,
        aliases=aliases,
        selectable=selectable,
        recommended=model_id == "gpt-5.6-sol",
        lifecycle_status="current" if selectable else "unavailable",
        compatibility_status="controlled_test_fixture",
        compatibility_source="controlled_test_fixture",
        catalog_version="controlled-picker.v1",
        supported_capabilities=("coding", "verification"),
        purpose="Controlled catalog-only fixture; no entitlement or invocation claim.",
        disabled_reason="" if selectable else "Not selectable in this controlled catalog.",
    )


def _catalog(*entries: CodexModelCatalogEntry, source: str = "controlled_test_fixture") -> CodexModelCatalog:
    return CodexModelCatalog(
        status="available",
        source=source,
        version="controlled-picker.v1",
        installed_cli_version="codex-cli 0.144.4",
        warnings=(),
        models=entries or tuple(_entry(model_id) for model_id in CATALOG_MODEL_IDS),
    )


def _install_catalog(client, catalog: CodexModelCatalog) -> None:
    adapter = client.app.state.codex_manager.adapter
    adapter._model_catalog_cache = catalog
    adapter._model_catalog_cached_at = time.monotonic()


def _check_model(client, model_id: str, capability: str = "coding") -> int:
    response = client.post(
        "/api/codex/setup/check",
        json={"model_identifier": model_id, "capability": capability},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert payload["configuration"]["provider_model_id"] == model_id
    assert payload["configuration"]["last_invocation_outcome"] == "not_invoked"
    assert payload["availability_evidence"]["evidence_type"] == "non_inference_cli_health"
    return payload["configuration"]["id"]


def _assign_model(client, task_id: int, model_id: int, capability: str):
    response = client.post(
        f"/api/tasks/{task_id}/codex/setup/assign",
        json={"model_id": model_id, "capability": capability},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assignment(payload: dict, capability: str) -> dict:
    return next(item for item in payload["assignments"] if item["capability"] == capability)


def _side_effect_counts(client) -> dict[str, int]:
    factory = client.app.state.session_factory
    with factory() as session:
        return {
            "providers": session.query(Provider).count(),
            "models": session.query(AIModel).count(),
            "assignments": session.query(AIModelAssignment).count(),
            "packs": session.query(CodexInstructionPack).count(),
            "approved_packs": session.query(CodexInstructionPack)
            .filter(CodexInstructionPack.approved_at.is_not(None))
            .count(),
            "runs": session.query(CodexRun).count(),
            "availability_evidence": session.query(AIModelAvailabilityEvidence).count(),
            "invocation_evidence": session.query(AIModelInvocationEvidence).count(),
        }


def test_catalog_discovery_precedence_cache_and_non_inference_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = CodexAdapter(_settings(tmp_path))
    primary_calls: list[str] = []
    monkeypatch.setattr(primary, "detect", _detection)

    def app_server_catalog(_detection: CodexDetection) -> CodexModelCatalog:
        primary_calls.append("app-server")
        return _catalog(_entry("gpt-5.6-sol"), source="codex_app_server_model_list")

    monkeypatch.setattr(primary, "_app_server_model_catalog", app_server_catalog)

    def unexpected_bundled(*_args, **_kwargs):
        raise AssertionError("bundled catalog must not run when app-server model/list succeeds")

    monkeypatch.setattr(codex_adapter_module.subprocess, "run", unexpected_bundled)
    discovered = primary.model_catalog(force_refresh=True)
    assert discovered.source == "codex_app_server_model_list"
    assert discovered.version == "controlled-picker.v1"
    assert [item.canonical_model_id for item in discovered.models] == ["gpt-5.6-sol"]
    assert primary.model_catalog() is discovered
    assert primary_calls == ["app-server"]

    bundled = CodexAdapter(_settings(tmp_path))
    monkeypatch.setattr(bundled, "detect", _detection)
    monkeypatch.setattr(
        bundled,
        "_app_server_model_catalog",
        lambda _value: (_ for _ in ()).throw(ValueError("app-server unavailable")),
    )
    observed_commands: list[list[str]] = []
    raw_catalog = json.dumps(
        {
            "models": [
                {
                    "slug": "gpt-5.6-sol",
                    "display_name": "GPT-5.6-Sol",
                    "description": "Controlled bundled metadata.",
                    "aliases": ["sol", "gpt-5.6-sol"],
                    "priority": 1,
                    "visibility": "list",
                    "authorization": "Bearer fixture-must-not-survive",
                },
                {
                    "slug": "vendor model with spaces",
                    "display_name": "Unsupported provider candidate",
                    "visibility": "list",
                },
                {"slug": "hidden-model", "display_name": "Hidden", "visibility": "hide"},
            ],
            "raw_config": "fixture-raw-config-must-not-survive",
        }
    )

    def bundled_run(argv, **_kwargs):
        observed_commands.append([str(item) for item in argv])
        return SimpleNamespace(returncode=0, stdout=raw_catalog, stderr="")

    monkeypatch.setattr(codex_adapter_module.subprocess, "run", bundled_run)
    discovered = bundled.model_catalog(force_refresh=True)
    assert discovered.source == "installed_codex_cli_bundled"
    assert discovered.version.startswith("codex-cli 0.144.4.catalog-")
    assert observed_commands == [["/controlled/codex", "debug", "models", "--bundled"]]
    assert [item.canonical_model_id for item in discovered.models] == ["gpt-5.6-sol"]
    assert discovered.models[0].aliases == ("sol",)
    serialized = json.dumps(discovered.as_dict())
    assert "fixture-must-not-survive" not in serialized
    assert "fixture-raw-config-must-not-survive" not in serialized
    assert "exec" not in " ".join(observed_commands[0])

    fallback = CodexAdapter(_settings(tmp_path))
    monkeypatch.setattr(fallback, "detect", _detection)
    monkeypatch.setattr(
        fallback,
        "_app_server_model_catalog",
        lambda _value: (_ for _ in ()).throw(ValueError("app-server unavailable")),
    )
    monkeypatch.setattr(
        codex_adapter_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=64, stdout="", stderr="ignored"),
    )
    discovered = fallback.model_catalog(force_refresh=True)
    assert discovered.status == "fallback"
    assert discovered.source == "twos_versioned_compatibility"
    assert discovered.version == "twos.codex_cli.compatibility.2026-07-21.v1"
    assert {"gpt-5.6-sol", "gpt-5.5"}.issubset(
        {item.canonical_model_id for item in discovered.models if item.selectable}
    )
    assert all(item.compatibility_status == "versioned_compatibility" for item in discovered.models)
    assert all(item.supported_capabilities == ("coding", "verification") for item in discovered.models)


def test_authenticated_catalog_is_allowlisted_scoped_and_side_effect_free(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        assert client.get("/api/model-catalog?adapter=codex_cli").status_code == 401
        init_and_login(client)
        _install_catalog(
            client,
            _catalog(
                _entry("gpt-5.6-sol", aliases=("sol",)),
                _entry("gpt-5.5"),
                _entry("retired-codex-model", selectable=False),
            ),
        )
        before = _side_effect_counts(client)
        response = client.get("/api/model-catalog?adapter=codex_cli&capability=coding")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert set(payload) == {
            "adapter",
            "provider",
            "catalog_status",
            "catalog_source",
            "catalog_version",
            "installed_cli_version",
            "warnings",
            "models",
            "currently_assigned_model",
        }
        assert payload["adapter"] == {
            "id": "codex_cli",
            "display_name": "Local Codex CLI",
            "invocation_mode": "real",
        }
        assert payload["provider"] == {
            "id": "local_codex_cli",
            "display_name": "Local Codex CLI",
        }
        assert payload["catalog_source"] == "controlled_test_fixture"
        assert payload["catalog_version"] == "controlled-picker.v1"
        assert payload["currently_assigned_model"] is None
        assert [item["canonical_model_id"] for item in payload["models"]] == [
            "gpt-5.6-sol",
            "gpt-5.5",
            "retired-codex-model",
        ]
        assert payload["models"][0]["aliases"] == ["sol"]
        assert payload["models"][2]["selectable"] is False
        assert payload["models"][2]["disabled_reason"]
        assert all(item["adapter_id"] == "codex_cli" for item in payload["models"])
        assert all(item["provider_id"] == "local_codex_cli" for item in payload["models"])
        allowed_entry_fields = {
            "adapter_id",
            "provider_id",
            "canonical_model_id",
            "display_name",
            "aliases",
            "selectable",
            "recommended",
            "lifecycle_status",
            "compatibility_status",
            "compatibility_source",
            "catalog_version",
            "minimum_cli_version",
            "supported_capabilities",
            "model_family",
            "performance_tier",
            "purpose",
            "disabled_reason",
        }
        assert all(set(item) == allowed_entry_fields for item in payload["models"])
        serialized = json.dumps(payload).casefold()
        for forbidden in (
            "authorization:",
            "bearer fixture",
            "api_key",
            "access_token",
            "cookie",
            "raw_config",
            "development task",
            "codex pack",
            str(source_repo).casefold(),
        ):
            assert forbidden not in serialized
        assert _side_effect_counts(client) == before
        assert client.get("/api/model-catalog?adapter=anthropic").status_code == 422


def test_catalog_exact_id_enforcement_rejects_malformed_and_alias_before_registry_write(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        init_and_login(client)
        _install_catalog(client, _catalog(_entry("gpt-5.6-sol", aliases=("sol", "gpt56sol"))))
        assert _side_effect_counts(client)["models"] == 0

        for candidate in ("5.6sol", "gpt5.6sol", "gpt-5.6-so1", "sol", "gpt56sol"):
            rejected = client.post(
                "/api/codex/setup/check",
                json={"model_identifier": candidate, "capability": "coding"},
            )
            assert rejected.status_code == 422, (candidate, rejected.text)
            assert rejected.json()["error"]["message"] == "No matching supported model."
        assert _side_effect_counts(client) == {
            "providers": 0,
            "models": 0,
            "assignments": 0,
            "packs": 0,
            "approved_packs": 0,
            "runs": 0,
            "availability_evidence": 0,
            "invocation_evidence": 0,
        }

        model_id = _check_model(client, "gpt-5.6-sol")
        factory = client.app.state.session_factory
        with factory() as session:
            persisted = session.get(AIModel, model_id)
            assert persisted is not None
            assert persisted.provider_model_id == "gpt-5.6-sol"
            assert persisted.model_name == "gpt-5.6-sol"
            assert persisted.last_invocation_outcome == "not_invoked"
            assert session.query(AIModelInvocationEvidence).count() == 0
            assert session.query(CodexRun).count() == 0


def test_catalog_context_preserves_current_and_absent_legacy_assignments_without_mutation(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        init_and_login(client)
        task_id = create_development_task(client, {}, marker="picker legacy preservation")
        current_model_id = _check_model(client, "gpt-5.6-sol")
        assigned = _assign_model(client, task_id, current_model_id, "coding")
        current = _assignment(assigned, "coding")
        before = {
            "version": current["assignment_version"],
            "snapshot": current["routing_snapshot_hash"],
            "counts": _side_effect_counts(client),
        }

        catalog = client.get(
            f"/api/model-catalog?adapter=codex_cli&capability=coding&task_id={task_id}"
        ).json()
        assert catalog["currently_assigned_model"] == {
            "canonical_model_id": "gpt-5.6-sol",
            "display_name": "gpt-5.6-sol",
            "catalog_listed": True,
            "lifecycle_status": "current",
            "assignment_version": before["version"],
            "routing_snapshot_hash": before["snapshot"],
        }
        assert _side_effect_counts(client) == before["counts"]

        factory = client.app.state.session_factory
        with factory() as session:
            provider = session.scalar(
                select(Provider).where(Provider.name == "Local Codex CLI", Provider.kind == "model")
            )
            assert provider is not None
            legacy = AIModel(
                provider_id=provider.id,
                model_name="owner-preserved-custom-model",
                display_name="Owner preserved custom model",
                provider_model_id="owner-preserved-custom-model",
                execution_adapter="codex_cli",
                capability_tags='["coding"]',
                status="healthy",
                configuration_status="configured",
                availability_status="available",
                invocation_mode="real",
                last_invocation_outcome="not_invoked",
                evidence_status="runtime_check",
                evidence_source="local_cli_readiness",
            )
            session.add(legacy)
            session.flush()
            coding = next(
                item for item in latest_model_assignments(session, task_id) if item.capability == "coding"
            )
            coding.assigned_model_id = legacy.id
            session.commit()

        before_legacy = _side_effect_counts(client)
        response = client.get(
            f"/api/model-catalog?adapter=codex_cli&capability=coding&task_id={task_id}"
        )
        assert response.status_code == 200, response.text
        legacy_context = response.json()["currently_assigned_model"]
        assert legacy_context["canonical_model_id"] == "owner-preserved-custom-model"
        assert legacy_context["display_name"] == "Owner preserved custom model"
        assert legacy_context["catalog_listed"] is False
        assert legacy_context["lifecycle_status"] == "legacy"
        assert legacy_context["assignment_version"] == before["version"]
        assert legacy_context["routing_snapshot_hash"] == before["snapshot"]
        assert _side_effect_counts(client) == before_legacy


def test_coding_and_verification_allow_same_then_different_catalog_models_without_run(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        init_and_login(client)
        task_id = create_development_task(client, {}, marker="independent picker bindings")
        sol_id = _check_model(client, "gpt-5.6-sol", "coding")
        gpt55_id = _check_model(client, "gpt-5.5", "verification")

        coding_saved = _assign_model(client, task_id, sol_id, "coding")
        coding_version = _assignment(coding_saved, "coding")["assignment_version"]
        same_saved = _assign_model(client, task_id, sol_id, "verification")
        coding_same = _assignment(same_saved, "coding")
        verification_same = _assignment(same_saved, "verification")
        planning_same = _assignment(same_saved, "planning")
        assert coding_same["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert verification_same["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert verification_same["independence_status"] == "separate_invocation"
        assert verification_same["assignment_version"] > coding_version
        assert planning_same["assigned_model"] is None
        assert planning_same["availability_at_composition"] == "unavailable"

        different_saved = _assign_model(client, task_id, gpt55_id, "verification")
        coding_different = _assignment(different_saved, "coding")
        verification_different = _assignment(different_saved, "verification")
        assert coding_different["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert verification_different["assigned_model"]["provider_model_id"] == "gpt-5.5"
        assert coding_different["assignment_version"] == verification_different["assignment_version"]
        assert coding_different["assignment_version"] > verification_same["assignment_version"]
        assert client.get(f"/api/tasks/{task_id}/codex-runs").json() == []
        assert client.get(f"/api/tasks/{task_id}/codex-packs").json() == []
        factory = client.app.state.session_factory
        with factory() as session:
            assert session.query(AIModelInvocationEvidence).count() == 0


def test_open_and_unchanged_save_preserve_assignment_snapshot_and_approval(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        init_and_login(client)
        task_id = create_development_task(client, {}, marker="unchanged picker save")
        sol_id = _check_model(client, "gpt-5.6-sol")
        _assign_model(client, task_id, sol_id, "coding")
        assigned = _assign_model(client, task_id, sol_id, "verification")
        binding = _assignment(assigned, "coding")
        pack = generate_pack(client, {}, task_id)
        approved = approve_pack(client, {}, task_id, pack["id"])
        assert approved["approved"] is True

        factory = client.app.state.session_factory
        with factory() as session:
            assignment_rows_before = session.query(AIModelAssignment).count()
            routes_before = session.query(RoutingDecision).count()
            evidence_before = session.query(AIModelAvailabilityEvidence).count()
        counts_before_open = _side_effect_counts(client)

        setup = client.get(f"/api/codex/setup?capability=coding&task_id={task_id}")
        catalog = client.get(
            f"/api/model-catalog?adapter=codex_cli&capability=coding&task_id={task_id}"
        )
        assert setup.status_code == 200
        assert catalog.status_code == 200
        assert catalog.json()["currently_assigned_model"]["canonical_model_id"] == "gpt-5.6-sol"
        assert _side_effect_counts(client) == counts_before_open

        unchanged = _assign_model(client, task_id, sol_id, "coding")
        assert unchanged["changed"] is False
        assert unchanged["invalidated_packs"] == 0
        current = _assignment(unchanged, "coding")
        assert current["assignment_version"] == binding["assignment_version"]
        assert current["routing_snapshot_hash"] == binding["routing_snapshot_hash"]

        with factory() as session:
            assert session.query(AIModelAssignment).count() == assignment_rows_before
            assert session.query(RoutingDecision).count() == routes_before
            assert session.query(AIModelAvailabilityEvidence).count() == evidence_before
            persisted_pack = session.get(CodexInstructionPack, pack["id"])
            assert persisted_pack is not None
            assert persisted_pack.status == "approved"
            assert persisted_pack.approved_at is not None
            assert persisted_pack.invalidated_at is None
            assert session.query(CodexRun).count() == 0
            assert session.query(AIModelInvocationEvidence).count() == 0


def test_material_model_change_versions_snapshot_invalidates_approval_without_automation(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        init_and_login(client)
        task_id = create_development_task(client, {}, marker="material picker change")
        sol_id = _check_model(client, "gpt-5.6-sol")
        gpt55_id = _check_model(client, "gpt-5.5")
        _assign_model(client, task_id, sol_id, "coding")
        initial = _assign_model(client, task_id, sol_id, "verification")
        binding_before = _assignment(initial, "coding")
        pack = generate_pack(client, {}, task_id)
        approve_pack(client, {}, task_id, pack["id"])

        changed = _assign_model(client, task_id, gpt55_id, "coding")
        assert changed["changed"] is True
        assert changed["invalidated_packs"] == 1
        coding_after = _assignment(changed, "coding")
        verification_after = _assignment(changed, "verification")
        assert coding_after["assigned_model"]["provider_model_id"] == "gpt-5.5"
        assert verification_after["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert coding_after["assignment_version"] == binding_before["assignment_version"] + 1
        assert coding_after["routing_snapshot_hash"] != binding_before["routing_snapshot_hash"]

        eligibility = client.get(f"/api/tasks/{task_id}/run-eligibility")
        assert eligibility.status_code == 200
        assert eligibility.json()["eligible"] is False
        assert any(item["code"] == "PACK_STALE" for item in eligibility.json()["blockers"])
        assert len(client.get(f"/api/tasks/{task_id}/codex-packs").json()) == 1
        assert client.get(f"/api/tasks/{task_id}/codex-runs").json() == []

        factory = client.app.state.session_factory
        with factory() as session:
            invalidated = session.get(CodexInstructionPack, pack["id"])
            assert invalidated is not None
            assert invalidated.status == "invalidated"
            # The historical approval timestamp remains evidence that approval once
            # occurred; status + invalidated_at make it non-current and unusable.
            assert invalidated.approved_at is not None
            assert invalidated.invalidated_at is not None
            assert session.query(CodexInstructionPack).count() == 1
            assert session.query(CodexRun).count() == 0
            assert session.query(AIModelInvocationEvidence).count() == 0


def test_separate_assignments_survive_logout_login_and_runtime_restart(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    database_path = tmp_path / "picker-persistence.sqlite3"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as initial:
        init_and_login(initial)
        task_id = create_development_task(initial, {}, marker="picker persistence")
        sol_id = _check_model(initial, "gpt-5.6-sol", "coding")
        gpt55_id = _check_model(initial, "gpt-5.5", "verification")
        _assign_model(initial, task_id, sol_id, "coding")
        assigned = _assign_model(initial, task_id, gpt55_id, "verification")
        original_version = _assignment(assigned, "coding")["assignment_version"]
        original_snapshot = _assignment(assigned, "coding")["routing_snapshot_hash"]

        assert initial.post("/api/auth/logout").status_code == 200
        assert initial.get(
            f"/api/model-catalog?adapter=codex_cli&capability=coding&task_id={task_id}"
        ).status_code == 401
        login = initial.post(
            "/api/auth/login",
            json={"username": "owner", "password": OWNER_PASSWORD},
        )
        assert login.status_code == 200
        refreshed = initial.get(f"/api/tasks/{task_id}/ai-plan").json()
        assert _assignment(refreshed, "coding")["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert _assignment(refreshed, "verification")["assigned_model"]["provider_model_id"] == "gpt-5.5"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
    ) as restarted:
        init_and_login(restarted)
        persisted = restarted.get(f"/api/tasks/{task_id}/ai-plan")
        assert persisted.status_code == 200, persisted.text
        coding = _assignment(persisted.json(), "coding")
        verification = _assignment(persisted.json(), "verification")
        assert coding["assigned_model"]["provider_model_id"] == "gpt-5.6-sol"
        assert verification["assigned_model"]["provider_model_id"] == "gpt-5.5"
        assert coding["assignment_version"] == original_version
        assert verification["assignment_version"] == original_version
        assert coding["routing_snapshot_hash"] == original_snapshot
        assert verification["routing_snapshot_hash"] == original_snapshot
        coding_catalog = restarted.get(
            f"/api/model-catalog?adapter=codex_cli&capability=coding&task_id={task_id}"
        ).json()
        verification_catalog = restarted.get(
            f"/api/model-catalog?adapter=codex_cli&capability=verification&task_id={task_id}"
        ).json()
        assert coding_catalog["currently_assigned_model"]["canonical_model_id"] == "gpt-5.6-sol"
        assert verification_catalog["currently_assigned_model"]["canonical_model_id"] == "gpt-5.5"
        assert restarted.get(f"/api/tasks/{task_id}/codex-runs").json() == []


def test_production_ui_contract_uses_accessible_scoped_picker_without_default_free_text(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    with make_client(tmp_path, source_repo, fake_codex) as client:
        page = client.get("/twos")
        script = client.get("/static_cockpit/vol12_static_mvp/twos_command_center.js")
        stylesheet = client.get("/static_cockpit/vol12_static_mvp/styles.css")
        assert page.status_code == 200
        assert script.status_code == 200
        assert stylesheet.status_code == 200
        assert '<label for="setup-model-search">Model</label>' in page.text
        assert 'id="setup-model-search" type="search" role="combobox"' in page.text
        assert 'aria-autocomplete="list"' in page.text
        assert 'aria-controls="setup-model-options"' in page.text
        assert 'id="setup-model-options"' in page.text and 'role="listbox"' in page.text
        assert "Codex model identifier" not in page.text
        assert "Same model, separate verification invocation" in page.text
        assert "Check availability" in page.text
        assert "Save and assign" in page.text
        assert "Advanced" in page.text
        assert "<details id=\"setup-catalog-details\"" in page.text
        assert "open>" not in page.text.split('id="setup-catalog-details"', 1)[1].split("</details>", 1)[0][:120]

        assert 'api("/api/model-catalog?adapter=codex_cli&capability="' in script.text
        assert "No matching supported model" in script.text
        assert "canonicalModelIdentifier" in script.text
        assert "entry.selectable !== true" in script.text
        assert 'elements.checkCodexAvailability.disabled = !selectable' in script.text
        assert 'elements.saveAssignCodex.disabled = !verified' in script.text
        assert "Same model, separate verification invocation" in script.text
        assert "Ran with" not in page.text
        assert "Account entitled" not in page.text
        assert "@media (max-width: 760px)" in stylesheet.text
        assert "max-height: min(18rem, 38dvh)" in stylesheet.text
        assert "overflow-wrap: anywhere" in stylesheet.text
