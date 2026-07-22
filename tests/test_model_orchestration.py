from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from twos_runtime.ai_orchestration import (
    assignment_binding,
    assignment_snapshot,
    bind_assignment_snapshot,
    compose_team,
    is_verified_real_invocation,
    model_registry_snapshot,
    record_model_invocation_evidence,
    recompose_model_assignments,
    route_capability,
    provider_state_hash,
)
from twos_runtime.db import (
    VOL17_END_TO_END_SCHEMA_VERSION,
    VOL17_SCHEMA_VERSION,
    initialize_database,
    make_engine,
    make_session_factory,
)
from twos_runtime.models import (
    AICapability,
    AIModel,
    AIModelAssignment,
    AIModelInvocationEvidence,
    AITeamPlan,
    AuditEvent,
    CodexInstructionPack,
    CodexRun,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    Project,
    Provider,
    SchemaVersion,
    SessionToken,
    SyncEntry,
    Task,
    User,
)


TEST_MODEL_CAPABILITIES = [
    "planning",
    "coding",
    "verification",
    "risk_analysis",
]


def install_test_model_registry(factory) -> None:
    """Install generic model fixtures without implying production vendor configuration."""
    with factory() as session:
        provider = session.scalar(
            select(Provider).where(
                Provider.name == "Test Fixture Provider",
                Provider.kind == "model",
            )
        )
        if provider is None:
            provider = Provider(
                name="Test Fixture Provider",
                kind="model",
                status="unconfigured",
                enabled=False,
                details="Generic test-only model registry fixture.",
            )
            session.add(provider)
            session.flush()
        for ordinal in range(1, 5):
            model_name = f"Test Fixture Model {ordinal}"
            if session.scalar(
                select(AIModel).where(
                    AIModel.provider_id == provider.id,
                    AIModel.model_name == model_name,
                )
            ):
                continue
            session.add(
                AIModel(
                    provider_id=provider.id,
                    model_name=model_name,
                    stable_id=f"test-fixture.model-{ordinal}",
                    display_name=model_name,
                    capability_tags=json.dumps(TEST_MODEL_CAPABILITIES, separators=(",", ":")),
                    context_limit=None,
                    cost_metadata="unknown",
                    latency_metadata="unknown",
                    status="unconfigured",
                    configuration_status="needs_setup",
                    availability_status="unavailable",
                    invocation_mode="unavailable",
                    last_invocation_outcome="not_invoked",
                    evidence_status="unverified",
                    evidence_source="seeded_registry",
                    safe_diagnostic="",
                    routing_priority=ordinal * 10,
                )
            )
        session.commit()


def database(tmp_path: Path, *, seed_models: bool = True):
    engine = make_engine(f"sqlite:///{tmp_path / 'vol17.sqlite3'}")
    initialize_database(engine)
    factory = make_session_factory(engine)
    if seed_models:
        install_test_model_registry(factory)
    return engine, factory


def test_fresh_vol17_schema_starts_empty_and_fixture_sources_are_explicit(
    tmp_path: Path,
) -> None:
    engine, factory = database(tmp_path, seed_models=False)

    ai_model_columns = {
        item["name"]: item for item in inspect(engine).get_columns("ai_models")
    }
    assert "evidence_source" in ai_model_columns
    assert ai_model_columns["evidence_source"]["nullable"] is False

    with factory() as session:
        assert session.scalars(select(AIModel)).all() == []

    install_test_model_registry(factory)

    with factory() as session:
        models = session.scalars(select(AIModel).order_by(AIModel.id)).all()
        assert len(models) == 4
        assert {model.evidence_source for model in models} == {"seeded_registry"}
        assert {
            model_registry_snapshot(model)["evidence_source"] for model in models
        } == {"seeded_registry"}


def partial_model_registry_database(
    tmp_path: Path,
    existing_state_column: str,
    existing_state_value: str,
):
    assert existing_state_column in {"configuration_status", "availability_status"}
    engine = make_engine(f"sqlite:///{tmp_path / f'partial-{existing_state_column}.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE providers (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, "
                "kind VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL, enabled BOOLEAN NOT NULL, "
                "details TEXT NOT NULL, last_checked_at DATETIME, UNIQUE(name, kind))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ai_models (id INTEGER PRIMARY KEY, provider_id INTEGER NOT NULL, "
                "model_name VARCHAR(160) NOT NULL, capability_tags TEXT NOT NULL, context_limit INTEGER, "
                "cost_metadata VARCHAR(40) NOT NULL, latency_metadata VARCHAR(40) NOT NULL, "
                "status VARCHAR(40) NOT NULL, "
                f"{existing_state_column} VARCHAR(40) NOT NULL, "
                "routing_priority INTEGER NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, UNIQUE(provider_id, model_name))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO providers VALUES (71, 'Partial Provider', 'model', 'healthy', 1, "
                "'persisted provider readiness', '2026-07-16 01:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ai_models (id, provider_id, model_name, capability_tags, context_limit, "
                "cost_metadata, latency_metadata, status, "
                f"{existing_state_column}, routing_priority, created_at, updated_at) "
                "VALUES (72, 71, 'Partial model', '[\"planning\"]', 8192, 'medium', 'low', "
                f"'healthy', :state_value, 5, '2026-07-16 01:00:00', '2026-07-16 01:00:00')"
            ),
            {"state_value": existing_state_value},
        )
    return engine


def test_vol17_migration_is_versioned_additive_idempotent_and_preserves_vol16_rows(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'legacy-vol16.sqlite3'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_versions ("
                "id INTEGER PRIMARY KEY, version VARCHAR(40) NOT NULL UNIQUE, applied_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80) NOT NULL UNIQUE, "
                "password_hash VARCHAR(160) NOT NULL, password_salt VARCHAR(80) NOT NULL, "
                "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE session_tokens (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
                "token_hash VARCHAR(160) NOT NULL UNIQUE, created_at DATETIME NOT NULL, "
                "expires_at DATETIME NOT NULL, revoked_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, key VARCHAR(80) NOT NULL UNIQUE, "
                "name VARCHAR(160) NOT NULL, status VARCHAR(80) NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
                "title VARCHAR(240) NOT NULL, task_type VARCHAR(80) NOT NULL, source_sync_summary TEXT NOT NULL, "
                "required_output TEXT NOT NULL, boundary_risk TEXT NOT NULL, workflow_type VARCHAR(80) NOT NULL, "
                "objective TEXT NOT NULL, implementation_scope TEXT NOT NULL, forbidden_scope TEXT NOT NULL, "
                "acceptance_target TEXT NOT NULL, repository_identity VARCHAR(240) NOT NULL, "
                "source_baseline_commit VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL, "
                "acceptance_state VARCHAR(40) NOT NULL, compact_sync_result TEXT, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE sync_entries (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, "
                "summary TEXT NOT NULL, result TEXT, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE providers (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, "
                "kind VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL, enabled BOOLEAN NOT NULL, "
                "details TEXT NOT NULL, last_checked_at DATETIME, UNIQUE(name, kind))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ai_models (id INTEGER PRIMARY KEY, provider_id INTEGER NOT NULL, "
                "model_name VARCHAR(160) NOT NULL, capability_tags TEXT NOT NULL, context_limit INTEGER, "
                "cost_metadata VARCHAR(40) NOT NULL, latency_metadata VARCHAR(40) NOT NULL, "
                "status VARCHAR(40) NOT NULL, routing_priority INTEGER NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, UNIQUE(provider_id, model_name))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ai_team_plans (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
                "risk_level VARCHAR(40) NOT NULL, urgency VARCHAR(40) NOT NULL, "
                "required_capabilities TEXT NOT NULL, omitted_capabilities TEXT NOT NULL, "
                "minimum_role_count INTEGER NOT NULL, status VARCHAR(40) NOT NULL, explanation TEXT NOT NULL, "
                "omission_explanation TEXT NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE codex_instruction_packs (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
                "version INTEGER NOT NULL, status VARCHAR(40) NOT NULL, content TEXT NOT NULL, "
                "stage_summary TEXT NOT NULL, key_boundaries TEXT NOT NULL, acceptance_target TEXT NOT NULL, "
                "source_baseline_commit VARCHAR(80) NOT NULL, ai_team_plan_id INTEGER, "
                "routing_decision_ids TEXT NOT NULL, generation_metadata TEXT NOT NULL, "
                "approved_by_user_id INTEGER, approved_at DATETIME, invalidated_at DATETIME, "
                "created_at DATETIME NOT NULL, UNIQUE(task_id, version))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE codex_runs (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, pack_id INTEGER NOT NULL, "
                "status VARCHAR(40) NOT NULL, executable_status VARCHAR(40) NOT NULL, source_repo TEXT NOT NULL, "
                "source_branch VARCHAR(240) NOT NULL, source_commit VARCHAR(80) NOT NULL, worktree_path TEXT NOT NULL, "
                "worktree_branch VARCHAR(240) NOT NULL, stdout TEXT NOT NULL, stderr TEXT NOT NULL, "
                "output_truncated BOOLEAN NOT NULL, structured_result TEXT NOT NULL, owner_summary TEXT NOT NULL, "
                "exit_code INTEGER, duration_ms INTEGER, timed_out BOOLEAN NOT NULL, cancelled BOOLEAN NOT NULL, "
                "created_at DATETIME NOT NULL, started_at DATETIME, finished_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE owner_acceptance_sessions (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
                "codex_run_id INTEGER NOT NULL UNIQUE, status VARCHAR(40) NOT NULL, owner_note TEXT NOT NULL, "
                "compact_sync_result TEXT NOT NULL, decided_by_user_id INTEGER, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, decided_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE owner_acceptance_items (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, "
                "key VARCHAR(120) NOT NULL, label VARCHAR(240) NOT NULL, inspect_target TEXT NOT NULL, "
                "ui_path TEXT NOT NULL, pass_standard TEXT NOT NULL, required BOOLEAN NOT NULL, "
                "status VARCHAR(40) NOT NULL, note TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                "UNIQUE(session_id, key))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE audit_events (id INTEGER PRIMARY KEY, actor_user_id INTEGER, "
                "action VARCHAR(120) NOT NULL, entity_type VARCHAR(80) NOT NULL, entity_id INTEGER, "
                "request_id VARCHAR(80), details TEXT NOT NULL, created_at DATETIME NOT NULL)"
            )
        )
        now = "2026-07-15 01:00:00"
        connection.execute(
            text("INSERT INTO schema_versions VALUES (1, 'vol16.001', :now)"), {"now": now}
        )
        connection.execute(
            text(
                "INSERT INTO users VALUES (3, 'preserved-owner', 'fixture-hash', 'fixture-salt', 1, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO session_tokens VALUES (4, 3, 'fixture-token-fingerprint', :now, :now, NULL)"
            ),
            {"now": now},
        )
        connection.execute(
            text("INSERT INTO projects VALUES (1, 'twos', 'TWOS', 'active', :now, :now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO sync_entries VALUES (21, 1, 'preserved compact sync source', "
                "'preserved compact sync result', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO tasks VALUES (42, 1, 'Preserved Vol16 task', 'Analyze', 'source', 'output', "
                "'boundary', 'product_development', 'objective', 'scope', 'forbidden', 'acceptance', "
                "'repo', 'baseline', 'planned', 'needs_review', 'preserved sync', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO providers VALUES (1, 'OpenAI', 'model', 'healthy', 1, "
                "'legacy provider evidence', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO ai_models VALUES (7, 1, 'Legacy configured model', '[\"planning\"]', "
                "8192, 'medium', 'low', 'healthy', 5, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO ai_team_plans VALUES (5, 42, 'medium', 'normal', '[\"planning\"]', '[]', "
                "2, 'composed', 'preserved plan', 'preserved omission', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO codex_instruction_packs VALUES (9, 42, 1, 'approved', 'preserved pack', "
                "'stage', 'boundary', 'acceptance', 'baseline', 5, '[]', '{}', NULL, NULL, NULL, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO codex_runs VALUES (11, 42, 9, 'completed', 'configured', '/source', 'main', "
                "'baseline', '/worktree', 'run-11', 'preserved stdout', '', 0, '{}', 'preserved result', "
                "0, 10, 0, 0, :now, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO owner_acceptance_sessions VALUES (12, 42, 11, 'accepted', "
                "'preserved owner decision', 'preserved accepted compact sync', 3, :now, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO owner_acceptance_items VALUES (13, 12, 'required_output', 'Required output', "
                "'result', 'Result', 'Evidence passes', 1, 'pass', 'preserved acceptance item', 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO audit_events VALUES (14, 3, 'owner_acceptance_accepted', "
                "'owner_acceptance_session', 12, 'fixture-request', 'preserved non-secret audit', :now)"
            ),
            {"now": now},
        )

    initialize_database(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        task = session.get(Task, 42)
        model = session.get(AIModel, 7)
        assert task is not None
        assert task.title == "Preserved Vol16 task"
        assert task.compact_sync_result == "preserved sync"
        assert task.task_version == 1
        assert task.development_task == ""
        assert task.objective == "objective"
        assert task.implementation_scope == "scope"
        assert task.acceptance_target == "acceptance"
        assert (
            task.objective_provenance,
            task.source_context_provenance,
            task.required_output_provenance,
            task.acceptance_target_provenance,
            task.implementation_scope_provenance,
        ) == ("derived", "derived", "derived", "derived", "derived")
        assert model is not None
        assert model.model_name == "Legacy configured model"
        assert model.stable_id
        assert model.display_name == model.model_name
        assert model.configuration_status == "configured"
        assert model.availability_status == "available"
        assert model.invocation_mode == "unavailable"
        assert model.evidence_source == "none"
        assert model.execution_adapter == ""
        legacy_plan = session.get(AITeamPlan, 5)
        legacy_pack = session.get(CodexInstructionPack, 9)
        legacy_run = session.get(CodexRun, 11)
        legacy_owner = session.get(User, 3)
        legacy_session = session.get(SessionToken, 4)
        legacy_acceptance = session.get(OwnerAcceptanceSession, 12)
        legacy_item = session.get(OwnerAcceptanceItem, 13)
        legacy_audit = session.get(AuditEvent, 14)
        legacy_sync = session.get(SyncEntry, 21)
        assert legacy_plan is not None and legacy_plan.explanation == "preserved plan"
        assert legacy_plan.assignment_version == 0
        assert legacy_pack is not None and legacy_pack.content == "preserved pack"
        assert legacy_pack.assignment_version == 0
        assert legacy_pack.source_snapshot_digest == ""
        assert legacy_pack.source_snapshot_json == "{}"
        assert legacy_run is not None and legacy_run.owner_summary == "preserved result"
        assert legacy_run.status == "completed"
        assert legacy_run.exit_code == 0
        assert legacy_run.output_truncated is False
        assert legacy_run.timed_out is False
        assert legacy_run.cancelled is False
        assert legacy_run.assignment_version == 0
        assert legacy_run.task_version == 1
        assert legacy_run.routing_snapshot_hash == ""
        assert legacy_run.execution_assignment_id is None
        assert legacy_run.execution_model_id is None
        assert legacy_run.execution_provider_id is None
        assert legacy_run.requested_model_identifier == ""
        assert legacy_run.fallback_selected is False
        assert legacy_run.process_spawned is False
        assert legacy_run.launch_intent_at is None
        assert legacy_run.source_snapshot_digest == ""
        assert legacy_run.verification_assignment_id is None
        assert legacy_run.verification_model_id is None
        assert legacy_run.verification_provider_id is None
        assert legacy_run.verification_model_identifier == ""
        assert legacy_run.verification_status == "not_started"
        assert legacy_run.verification_summary == ""
        assert legacy_run.verification_process_spawned is False
        assert legacy_run.verification_stdout == ""
        assert legacy_run.verification_stderr == ""
        assert legacy_run.verification_exit_code is None
        assert legacy_run.verification_duration_ms is None
        assert legacy_run.verification_timed_out is False
        assert legacy_run.verification_cancelled is False
        assert legacy_run.verification_output_truncated is False
        assert legacy_owner is not None and legacy_owner.username == "preserved-owner"
        assert legacy_session is not None and legacy_session.user_id == legacy_owner.id
        assert legacy_acceptance is not None and legacy_acceptance.status == "accepted"
        assert legacy_acceptance.compact_sync_result == "preserved accepted compact sync"
        assert legacy_item is not None and legacy_item.status == "pass"
        assert legacy_audit is not None and legacy_audit.details == "preserved non-secret audit"
        assert legacy_sync is not None
        assert legacy_sync.summary == "preserved compact sync source"
        assert legacy_sync.result == "preserved compact sync result"
        vol17_version = session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)
        )
        assert vol17_version is not None
        first_vol17_applied_at = vol17_version.applied_at
        vol17_end_to_end_versions = session.scalars(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL17_END_TO_END_SCHEMA_VERSION
            )
        ).all()
        assert len(vol17_end_to_end_versions) == 1
        first_vol17_end_to_end_applied_at = vol17_end_to_end_versions[0].applied_at
        first_stable_id = model.stable_id
        assert session.scalar(select(SchemaVersion).where(SchemaVersion.version == "vol16.001"))

    inspector = inspect(engine)
    assert {"ai_model_assignments", "ai_model_invocation_evidence"}.issubset(
        inspector.get_table_names()
    )
    assert {"assignment_version", "task_version", "routing_snapshot_hash"}.issubset(
        {item["name"] for item in inspector.get_columns("ai_team_plans")}
    )
    assert {"assignment_version", "task_version", "routing_snapshot_hash"}.issubset(
        {item["name"] for item in inspector.get_columns("codex_instruction_packs")}
    )
    assert {
        "development_task",
        "objective_provenance",
        "source_context_provenance",
        "required_output_provenance",
        "acceptance_target_provenance",
        "implementation_scope_provenance",
    }.issubset({item["name"] for item in inspector.get_columns("tasks")})
    assert {"source_snapshot_digest", "source_snapshot_json"}.issubset(
        {item["name"] for item in inspector.get_columns("codex_instruction_packs")}
    )
    ai_model_columns = {
        item["name"]: item for item in inspector.get_columns("ai_models")
    }
    assert "execution_adapter" in ai_model_columns
    assert "evidence_source" in ai_model_columns
    assert ai_model_columns["evidence_source"]["nullable"] is False
    assert str(ai_model_columns["evidence_source"].get("default")).strip("'\"") == "none"
    codex_run_bridge_columns = {
        "assignment_version",
        "task_version",
        "routing_snapshot_hash",
        "execution_assignment_id",
        "execution_model_id",
        "execution_provider_id",
        "requested_model_identifier",
        "fallback_selected",
        "process_spawned",
        "launch_intent_at",
        "source_snapshot_digest",
        "verification_assignment_id",
        "verification_model_id",
        "verification_provider_id",
        "verification_model_identifier",
        "verification_status",
        "verification_summary",
        "verification_process_spawned",
        "verification_stdout",
        "verification_stderr",
        "verification_exit_code",
        "verification_duration_ms",
        "verification_timed_out",
        "verification_cancelled",
        "verification_output_truncated",
    }
    codex_run_columns = {
        item["name"]: item for item in inspector.get_columns("codex_runs")
    }
    assert codex_run_bridge_columns.issubset(codex_run_columns)
    assert codex_run_columns["launch_intent_at"]["nullable"] is True
    assert codex_run_columns["launch_intent_at"].get("default") is None
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("ai_models")
    }
    assert {
        ("configuration_status",),
        ("availability_status",),
        ("invocation_mode",),
        ("last_invocation_outcome",),
        ("evidence_status",),
    }.issubset(indexed_columns)
    codex_run_indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_runs")
    }
    assert {
        ("execution_assignment_id",),
        ("execution_model_id",),
        ("execution_provider_id",),
        ("source_snapshot_digest",),
        ("verification_assignment_id",),
        ("verification_model_id",),
        ("verification_provider_id",),
        ("verification_status",),
    }.issubset(codex_run_indexed_columns)
    codex_pack_indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_instruction_packs")
    }
    assert ("source_snapshot_digest",) in codex_pack_indexed_columns

    with factory() as session:
        model = session.get(AIModel, 7)
        assert model is not None
        model.configuration_status = "needs_setup"
        model.availability_status = "unavailable"
        model.evidence_source = "manual_record"
        session.commit()

    initialize_database(engine)
    with factory() as session:
        task = session.scalar(select(Task).where(Task.id == 42))
        assert task.title == "Preserved Vol16 task"
        assert task.development_task == ""
        assert (
            task.objective_provenance,
            task.source_context_provenance,
            task.required_output_provenance,
            task.acceptance_target_provenance,
            task.implementation_scope_provenance,
        ) == ("derived", "derived", "derived", "derived", "derived")
        assert session.get(User, 3).username == "preserved-owner"
        assert session.get(OwnerAcceptanceSession, 12).compact_sync_result == (
            "preserved accepted compact sync"
        )
        assert session.get(AuditEvent, 14).action == "owner_acceptance_accepted"
        assert session.get(SyncEntry, 21).result == "preserved compact sync result"
        models = session.scalars(select(AIModel).where(AIModel.id == 7)).all()
        assert len(models) == 1
        assert models[0].configuration_status == "needs_setup"
        assert models[0].availability_status == "unavailable"
        assert models[0].evidence_source == "manual_record"
        assert models[0].stable_id == first_stable_id
        legacy_pack = session.get(CodexInstructionPack, 9)
        assert legacy_pack is not None
        assert legacy_pack.content == "preserved pack"
        assert legacy_pack.source_snapshot_digest == ""
        assert legacy_pack.source_snapshot_json == "{}"
        legacy_run = session.get(CodexRun, 11)
        assert legacy_run is not None
        assert (
            legacy_run.status,
            legacy_run.exit_code,
            legacy_run.assignment_version,
            legacy_run.task_version,
            legacy_run.routing_snapshot_hash,
            legacy_run.execution_assignment_id,
            legacy_run.execution_model_id,
            legacy_run.execution_provider_id,
            legacy_run.requested_model_identifier,
            legacy_run.fallback_selected,
            legacy_run.process_spawned,
            legacy_run.launch_intent_at,
            legacy_run.source_snapshot_digest,
            legacy_run.verification_assignment_id,
            legacy_run.verification_model_id,
            legacy_run.verification_provider_id,
            legacy_run.verification_model_identifier,
            legacy_run.verification_status,
            legacy_run.verification_summary,
            legacy_run.verification_process_spawned,
            legacy_run.verification_stdout,
            legacy_run.verification_stderr,
            legacy_run.verification_exit_code,
            legacy_run.verification_duration_ms,
            legacy_run.verification_timed_out,
            legacy_run.verification_cancelled,
            legacy_run.verification_output_truncated,
        ) == (
            "completed",
            0,
            0,
            1,
            "",
            None,
            None,
            None,
            "",
            False,
            False,
            None,
            "",
            None,
            None,
            None,
            "",
            "not_started",
            "",
            False,
            "",
            "",
            None,
            None,
            False,
            False,
            False,
        )
        versions = session.scalars(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)
        ).all()
        assert len(versions) == 1
        assert versions[0].applied_at == first_vol17_applied_at
        vol17_end_to_end_versions = session.scalars(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL17_END_TO_END_SCHEMA_VERSION
            )
        ).all()
        assert len(vol17_end_to_end_versions) == 1
        assert (
            vol17_end_to_end_versions[0].applied_at
            == first_vol17_end_to_end_applied_at
        )

    repeated_codex_run_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspect(engine).get_indexes("codex_runs")
    }
    first_codex_run_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspector.get_indexes("codex_runs")
    }
    assert repeated_codex_run_indexes == first_codex_run_indexes
    repeated_codex_pack_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspect(engine).get_indexes("codex_instruction_packs")
    }
    first_codex_pack_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspector.get_indexes("codex_instruction_packs")
    }
    assert repeated_codex_pack_indexes == first_codex_pack_indexes


@pytest.mark.parametrize(
    (
        "existing_state_column",
        "existing_state_value",
        "expected_configuration_status",
        "expected_availability_status",
    ),
    [
        ("configuration_status", "needs_setup", "needs_setup", "available"),
        ("availability_status", "unavailable", "configured", "unavailable"),
    ],
)
def test_partial_model_registry_migration_preserves_existing_state_and_is_idempotent(
    tmp_path: Path,
    existing_state_column: str,
    existing_state_value: str,
    expected_configuration_status: str,
    expected_availability_status: str,
) -> None:
    engine = partial_model_registry_database(
        tmp_path,
        existing_state_column,
        existing_state_value,
    )
    initialize_database(engine)
    factory = make_session_factory(engine)

    with factory() as session:
        model = session.get(AIModel, 72)
        assert model is not None
        assert model.configuration_status == expected_configuration_status
        assert model.availability_status == expected_availability_status
        assert model.invocation_mode == "unavailable"
        assert model.last_invocation_outcome == "not_invoked"
        assert model.evidence_status == "unverified"
        assert model.evidence_source == "none"
        assert model.last_verified_at is None
        first_registry_state = (
            model.stable_id,
            model.display_name,
            model.configuration_status,
            model.availability_status,
            model.evidence_source,
        )
        first_model_count = len(session.scalars(select(AIModel)).all())
        version = session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)
        )
        assert version is not None
        first_applied_at = version.applied_at

    first_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspect(engine).get_indexes("ai_models")
    }
    initialize_database(engine)

    with factory() as session:
        model = session.get(AIModel, 72)
        assert model is not None
        assert (
            model.stable_id,
            model.display_name,
            model.configuration_status,
            model.availability_status,
            model.evidence_source,
        ) == first_registry_state
        assert len(session.scalars(select(AIModel)).all()) == first_model_count
        versions = session.scalars(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)
        ).all()
        assert len(versions) == 1
        assert versions[0].applied_at == first_applied_at

    repeated_indexes = {
        (
            item.get("name"),
            tuple(item.get("column_names") or []),
            bool(item.get("unique")),
        )
        for item in inspect(engine).get_indexes("ai_models")
    }
    assert repeated_indexes == first_indexes


def test_registry_and_invocation_evidence_are_explicit_and_secret_free(tmp_path: Path) -> None:
    engine, factory = database(tmp_path)
    with factory() as session:
        model = session.scalar(select(AIModel).order_by(AIModel.id))
        assert model is not None
        snapshot = model_registry_snapshot(model)
        assert snapshot["stable_id"]
        assert snapshot["display_name"]
        assert snapshot["provider"]["name"]
        assert isinstance(snapshot["capabilities"], list)
        assert snapshot["configuration_status"] == "needs_setup"
        assert snapshot["availability_status"] == "unavailable"
        assert snapshot["invocation_mode"] == "unavailable"
        assert snapshot["evidence_source"] == "seeded_registry"
        assert snapshot["last_verified_at"] is None

        original_provider_name = model.provider.name
        original_display_name = model.display_name
        model.provider.name = "Password material is not a provider label"
        model.display_name = "Password material is not a model label"
        model.provider_model_id = "password-material-is-not-a-model-id"
        masked_snapshot = model_registry_snapshot(model)
        assert masked_snapshot["provider"]["name"] == "Configured provider"
        assert masked_snapshot["display_name"] == "Configured model"
        assert masked_snapshot["provider_model_id"] == ""
        model.evidence_source = "untrusted-evidence-source"
        assert model_registry_snapshot(model)["evidence_source"] == "none"
        model.provider.name = original_provider_name
        model.display_name = original_display_name
        model.provider_model_id = ""
        model.evidence_source = "seeded_registry"

        evidence = record_model_invocation_evidence(
            session,
            model=model,
            capability="planning",
            assignment_version=1,
            invocation_ref="vol17-simulated-001",
            invocation_mode="simulated",
            outcome="succeeded",
            actual_invoked_model_identifier=model.stable_id or "legacy-model",
            process_evidence={
                "process_observed": True,
                "exit_code": 0,
                "isolated_worktree": True,
                "stdout_present": True,
                "stderr_present": False,
            },
            provider_evidence={
                "provider_response_observed": False,
                "model_identifier_match": True,
            },
            usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            request_fingerprint="a" * 64,
            response_fingerprint="b" * 64,
            duration_ms=12,
            diagnostic_code="simulated.ok",
            safe_summary="Local simulated verification completed.",
        )
        assert evidence.configured_model_id == model.id
        assert evidence.configured_provider_id == model.provider_id
        assert evidence.invocation_mode == "simulated"
        assert evidence.outcome == "succeeded"
        assert evidence.actual_invoked_model_identifier == model.stable_id
        assert json.loads(evidence.usage_metadata) == {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        }
        assert model.configuration_status == "needs_setup"
        assert model.availability_status == "unavailable"
        assert model.last_invocation_outcome == "succeeded"
        assert model.evidence_status == "simulated"
        assert model.evidence_source == "simulation_record"
        assert model_registry_snapshot(model)["evidence_source"] == "simulation_record"
        assert model.last_verified_at is None

        manual_evidence = record_model_invocation_evidence(
            session,
            model=model,
            capability="verification",
            assignment_version=1,
            invocation_ref="vol17-manual-001",
            invocation_mode="manual",
            outcome="succeeded",
            actual_invoked_model_identifier=model.stable_id or "legacy-model",
            diagnostic_code="manual.recorded",
            safe_summary="Owner-recorded manual verification evidence.",
        )
        assert manual_evidence.invocation_mode == "manual"
        assert model.evidence_status == "manual"
        assert model.evidence_source == "manual_record"
        assert model_registry_snapshot(model)["evidence_source"] == "manual_record"
        assert model.last_verified_at is None

        with pytest.raises(ValueError, match="unsafe diagnostic material"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-unsafe-001",
                invocation_mode="simulated",
                outcome="failed",
                actual_invoked_model_identifier=model.stable_id or "legacy-model",
                safe_summary="Password material must not be stored.",
            )
        with pytest.raises(ValueError, match="unsupported fields"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-unsafe-002",
                invocation_mode="simulated",
                outcome="failed",
                actual_invoked_model_identifier=model.stable_id or "legacy-model",
                provider_evidence={"raw_response": "forbidden"},
            )
        with pytest.raises(ValueError, match="stdout_present must be a boolean"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-untyped-metadata-001",
                invocation_mode="simulated",
                outcome="failed",
                actual_invoked_model_identifier=model.stable_id or "legacy-model",
                process_evidence={"stdout_present": "raw output is not bounded metadata"},
            )
        model.provider.enabled = True
        model.provider.status = "healthy"
        model.provider_model_id = "provider-model-v1"
        with pytest.raises(ValueError, match="observed process evidence"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-unproved-real-001",
                invocation_mode="real",
                outcome="succeeded",
                actual_invoked_model_identifier=model.provider_model_id,
            )
        with pytest.raises(ValueError, match="zero process exit evidence"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-nonzero-real-001",
                invocation_mode="real",
                outcome="succeeded",
                actual_invoked_model_identifier=model.provider_model_id,
                process_evidence={"process_observed": True, "exit_code": -9},
                provider_evidence={
                    "provider_response_observed": True,
                    "model_identifier_match": True,
                    "status_code": 200,
                },
            )
        with pytest.raises(ValueError, match="successful provider status code"):
            record_model_invocation_evidence(
                session,
                model=model,
                capability="planning",
                assignment_version=1,
                invocation_ref="vol17-provider-failed-real-001",
                invocation_mode="real",
                outcome="succeeded",
                actual_invoked_model_identifier=model.provider_model_id,
                process_evidence={"process_observed": True, "exit_code": 0},
                provider_evidence={
                    "provider_response_observed": True,
                    "model_identifier_match": True,
                    "status_code": 500,
                },
            )
        verified_real = record_model_invocation_evidence(
            session,
            model=model,
            capability="planning",
            assignment_version=1,
            invocation_ref="vol17-proved-real-001",
            invocation_mode="real",
            outcome="succeeded",
            actual_invoked_model_identifier=model.provider_model_id,
            process_evidence={"process_observed": True, "exit_code": 0},
            provider_evidence={
                "provider_response_observed": True,
                "model_identifier_match": True,
                "status_code": 200,
                "request_id_fingerprint": "c" * 64,
            },
            safe_summary="Verified real invocation evidence recorded.",
        )
        assert verified_real.invocation_mode == "real"
        assert model.configuration_status == "configured"
        assert model.availability_status == "available"
        assert model.evidence_status == "verified"
        assert model.evidence_source == "invocation_evidence"
        assert model_registry_snapshot(model)["evidence_source"] == "invocation_evidence"
        assert model.last_verified_at is not None
        assert is_verified_real_invocation(verified_real) is True
        model.provider.enabled = False
        model.provider.status = "disabled"
        model.provider_model_id = "later-registry-target"
        assert is_verified_real_invocation(verified_real) is True
        session.commit()

    columns = {item["name"] for item in inspect(engine).get_columns("ai_model_invocation_evidence")}
    assert {
        "capability",
        "assignment_version",
        "configured_model_id",
        "configured_provider_id",
        "codex_run_id",
        "actual_invoked_model_identifier",
        "started_at",
        "completed_at",
        "outcome",
        "process_evidence",
        "provider_evidence",
        "timed_out",
        "cancelled",
        "output_truncated",
        "usage_metadata",
        "error_category",
        "invocation_mode",
    }.issubset(columns)
    assert not {
        "prompt",
        "response",
        "request_body",
        "response_body",
        "api_key",
        "credential",
        "stdout",
        "stderr",
    }.intersection(columns)
    with factory() as session:
        persisted_evidence = session.scalars(
            select(AIModelInvocationEvidence).order_by(AIModelInvocationEvidence.id)
        ).all()
        assert [
            (item.invocation_ref, item.invocation_mode) for item in persisted_evidence
        ] == [
            ("vol17-simulated-001", "simulated"),
            ("vol17-manual-001", "manual"),
            ("vol17-proved-real-001", "real"),
        ]


def test_registry_state_matrix_never_conflates_readiness_selection_and_invocation(
    tmp_path: Path,
) -> None:
    _engine, factory = database(tmp_path)
    with factory() as session:
        models = session.scalars(select(AIModel).order_by(AIModel.id).limit(3)).all()
        assert len(models) == 3
        provider = models[0].provider
        provider.enabled = True
        provider.status = "healthy"

        configured_unavailable, available_simulated, disabled = models
        configured_unavailable.configuration_status = "configured"
        configured_unavailable.availability_status = "unavailable"
        configured_unavailable.invocation_mode = "real"
        configured_unavailable.status = "healthy"

        available_simulated.configuration_status = "configured"
        available_simulated.availability_status = "available"
        available_simulated.invocation_mode = "simulated"
        available_simulated.status = "healthy"

        disabled.configuration_status = "disabled"
        disabled.availability_status = "disabled"
        disabled.invocation_mode = "unavailable"
        disabled.status = "disabled"

        first = model_registry_snapshot(configured_unavailable)
        second = model_registry_snapshot(available_simulated)
        third = model_registry_snapshot(disabled)
        assert (first["configuration_status"], first["availability_status"]) == (
            "configured",
            "unavailable",
        )
        assert first["last_invocation_outcome"] == "not_invoked"
        assert first["evidence_status"] == "unverified"
        assert second["availability_status"] == "available"
        assert second["invocation_mode"] == "simulated"
        assert second["last_invocation_outcome"] == "not_invoked"
        assert third["configuration_status"] == "disabled"
        assert third["availability_status"] == "disabled"
        assert third["invocation_mode"] == "unavailable"


def test_verification_chooses_first_independent_eligible_model_after_two_producers(
    tmp_path: Path,
) -> None:
    _engine, factory = database(tmp_path)
    with factory() as session:
        project = session.scalar(select(Project).where(Project.key == "twos"))
        assert project is not None
        task = Task(
            project_id=project.id,
            title="Build with three independently assigned models",
            task_type="Build",
            workflow_type="product_development",
            required_output="Planning, coding, and independent verification.",
            boundary_risk="No provider execution.",
            task_version=1,
        )
        session.add(task)
        session.flush()
        plan = compose_team(session, task)

        models = session.scalars(select(AIModel).order_by(AIModel.id)).all()
        assert len(models) >= 3
        for provider in session.scalars(select(Provider).where(Provider.kind == "model")).all():
            provider.enabled = False
            provider.status = "unconfigured"
        for model in models:
            model.status = "disabled"
            model.configuration_status = "disabled"
            model.availability_status = "disabled"
            model.invocation_mode = "unavailable"

        planning_model, coding_model, verification_model = models[:3]
        model_contracts = (
            (planning_model, ["planning", "verification"], 10),
            (coding_model, ["coding", "verification"], 20),
            (verification_model, ["verification"], 30),
        )
        for model, capabilities, priority in model_contracts:
            model.provider.enabled = True
            model.provider.status = "healthy"
            model.status = "healthy"
            model.configuration_status = "configured"
            model.availability_status = "available"
            model.invocation_mode = "real"
            model.capability_tags = json.dumps(capabilities, separators=(",", ":"))
            model.cost_metadata = "medium"
            model.latency_metadata = "medium"
            model.routing_priority = priority
        session.flush()

        capabilities = {
            item.name: item
            for item in session.scalars(
                select(AICapability).where(
                    AICapability.name.in_(["planning", "coding", "verification"])
                )
            ).all()
        }
        routes = {
            name: route_capability(
                session,
                task,
                capabilities[name],
                team_plan_id=plan.id,
                requested_capabilities=[name],
            )
            for name in ("planning", "coding", "verification")
        }
        assert routes["planning"].selected_model_id == planning_model.id
        assert routes["coding"].selected_model_id == coding_model.id
        assert routes["verification"].selected_model_id == planning_model.id
        assert routes["verification"].fallback_model_id == coding_model.id

        assignments = recompose_model_assignments(
            session,
            task,
            routes.values(),
            team_plan=plan,
        )
        assigned = {item.capability: item for item in assignments}
        assert assigned["planning"].assigned_model_id == planning_model.id
        assert assigned["coding"].assigned_model_id == coding_model.id
        assert assigned["verification"].assigned_model_id == verification_model.id
        assert assigned["verification"].availability_at_composition == "available"
        assert assigned["verification"].independence_status == "independent_fallback"
        assert assigned["verification"].fallback_allowed is False


def test_assignment_recomposition_versions_only_semantic_routing_changes(tmp_path: Path) -> None:
    _engine, factory = database(tmp_path)
    with factory() as session:
        project = session.scalar(select(Project).where(Project.key == "twos"))
        assert project is not None
        task = Task(
            project_id=project.id,
            title="Build a verified model orchestration core",
            task_type="Build",
            workflow_type="product_development",
            required_output="planning, coding, and independent verification assignments",
            boundary_risk="No provider execution.",
            task_version=1,
        )
        session.add(task)
        session.flush()
        plan = compose_team(session, task)

        for provider in session.scalars(select(Provider).where(Provider.kind == "model")).all():
            provider.enabled = True
            provider.status = "healthy"
        for model in session.scalars(select(AIModel)).all():
            if set(json.loads(model.capability_tags)).intersection({"planning", "coding", "verification"}):
                model.status = "healthy"
                model.configuration_status = "configured"
                model.availability_status = "available"
                model.invocation_mode = "simulated"
                model.evidence_status = "verified"
        session.flush()

        capabilities = {
            item.name: item
            for item in session.scalars(
                select(AICapability).where(
                    AICapability.name.in_(["planning", "coding", "verification", "risk_analysis"])
                )
            ).all()
        }
        routes = [
            route_capability(
                session,
                task,
                capabilities[name],
                team_plan_id=plan.id,
                requested_capabilities=[name],
            )
            for name in ("planning", "coding", "verification")
        ]

        first = recompose_model_assignments(session, task, routes, team_plan=plan)
        assert len(first) == 3
        assert {item.role for item in first} == {"planning", "coding", "verification"}
        assert {item.assignment_version for item in first} == {1}
        assert {item.task_version for item in first} == {1}
        assert all(item.assignment_reason for item in first)
        assert all(item.routing_source == "routing_decision" for item in first)
        assert all(item.availability_at_composition in {"available", "unavailable"} for item in first)
        assert plan.assignment_version == 1
        assert plan.task_version == 1
        assert plan.routing_snapshot_hash == first[0].routing_snapshot_hash
        assert len(provider_state_hash(session.scalars(select(AIModel)).all())) == 64

        planning = next(item for item in first if item.role == "planning")
        coding = next(item for item in first if item.role == "coding")
        verification = next(item for item in first if item.role == "verification")
        assert verification.independence_required is True
        assert verification.independence_status in {"independent", "independent_fallback"}
        assert verification.assigned_model_id not in {planning.assigned_model_id, coding.assigned_model_id}
        verification_snapshot = assignment_snapshot(verification)
        assert verification_snapshot["capability"] == "verification"
        assert verification_snapshot["assigned_model"]["stable_id"]
        assert "safe_diagnostic" in verification_snapshot["assigned_model"]
        first_ids = [item.id for item in first]
        first_hash = first[0].routing_snapshot_hash

        models_for_hash = session.scalars(select(AIModel).order_by(AIModel.id)).all()
        provider_hash_before_provenance = provider_state_hash(models_for_hash)
        assert planning.assigned_model is not None
        planning.assigned_model.evidence_status = "simulated"
        planning.assigned_model.evidence_source = "simulation_record"
        provenance_snapshot = model_registry_snapshot(planning.assigned_model)
        assert provenance_snapshot["evidence_status"] == "simulated"
        assert provenance_snapshot["evidence_source"] == "simulation_record"
        assert provider_state_hash(models_for_hash) == provider_hash_before_provenance

        provenance_only = recompose_model_assignments(
            session,
            task,
            routes,
            team_plan=plan,
            task_version=1,
        )
        assert [item.id for item in provenance_only] == first_ids
        assert {item.assignment_version for item in provenance_only} == {1}
        assert provenance_only[0].routing_snapshot_hash == first_hash

        same_route_new_task_version = recompose_model_assignments(
            session,
            task,
            routes,
            team_plan=plan,
            task_version=2,
        )
        second_ids = [item.id for item in same_route_new_task_version]
        assert set(second_ids).isdisjoint(first_ids)
        assert {item.assignment_version for item in same_route_new_task_version} == {1}
        assert {item.task_version for item in same_route_new_task_version} == {2}
        assert same_route_new_task_version[0].routing_snapshot_hash == first_hash
        assert {item.task_version for item in first} == {1}
        assert len(session.scalars(select(AIModelAssignment)).all()) == 6

        equivalent_new_decisions = [
            route_capability(
                session,
                task,
                capabilities[name],
                team_plan_id=plan.id,
                requested_capabilities=[name],
            )
            for name in ("planning", "coding", "verification")
        ]
        same_semantics = recompose_model_assignments(
            session,
            task,
            equivalent_new_decisions,
            team_plan=plan,
            task_version=2,
        )
        assert [item.id for item in same_semantics] == second_ids
        assert {item.assignment_version for item in same_semantics} == {1}

        planning.assigned_model.status = "unavailable"
        planning.assigned_model.availability_status = "unavailable"
        changed = recompose_model_assignments(
            session,
            task,
            equivalent_new_decisions,
            team_plan=plan,
            task_version=2,
        )
        assert {item.assignment_version for item in changed} == {2}
        assert changed[0].routing_snapshot_hash != first_hash
        assert len(session.scalars(select(AIModelAssignment)).all()) == 9
        unchanged_again = recompose_model_assignments(
            session,
            task,
            equivalent_new_decisions,
            team_plan=plan,
            task_version=3,
        )
        assert {item.assignment_version for item in unchanged_again} == {2}
        assert {item.task_version for item in unchanged_again} == {3}
        assert len(session.scalars(select(AIModelAssignment)).all()) == 12
        assert {item.task_version for item in first} == {1}

        binding = assignment_binding(unchanged_again)
        assert binding == {
            "assignment_version": 2,
            "task_version": 3,
            "routing_snapshot_hash": unchanged_again[0].routing_snapshot_hash,
        }
        pack = CodexInstructionPack(
            task_id=task.id,
            version=1,
            content="bounded pack",
            stage_summary="stage",
            key_boundaries="boundary",
            acceptance_target="acceptance",
            source_baseline_commit="baseline",
        )
        bind_assignment_snapshot(pack, unchanged_again)
        assert pack.assignment_version == 2
        assert pack.task_version == 3
        assert pack.routing_snapshot_hash == unchanged_again[0].routing_snapshot_hash

        risk_route = route_capability(
            session,
            task,
            capabilities["risk_analysis"],
            team_plan_id=plan.id,
            requested_capabilities=["risk_analysis"],
        )
        expanded = recompose_model_assignments(
            session,
            task,
            [*equivalent_new_decisions, risk_route],
            team_plan=plan,
            task_version=4,
        )
        assert {item.role for item in expanded} == {
            "planning",
            "coding",
            "verification",
            "risk_analysis",
        }
        assert {item.assignment_version for item in expanded} == {3}
        assert {item.task_version for item in expanded} == {4}
        assert len(session.scalars(select(AIModelAssignment)).all()) == 16

        expanded_hash = expanded[0].routing_snapshot_hash
        expanded_planning = next(item for item in expanded if item.capability == "planning")
        assert expanded_planning.assigned_model is not None
        expanded_planning.assigned_model.provider_model_id = "retargeted-provider-model-v2"
        retargeted = recompose_model_assignments(
            session,
            task,
            [*equivalent_new_decisions, risk_route],
            team_plan=plan,
            task_version=4,
        )
        assert {item.assignment_version for item in retargeted} == {4}
        assert retargeted[0].routing_snapshot_hash != expanded_hash
        assert len(session.scalars(select(AIModelAssignment)).all()) == 20

        with pytest.raises(ValueError, match="cannot regress"):
            recompose_model_assignments(
                session,
                task,
                [*equivalent_new_decisions, risk_route],
                team_plan=plan,
                task_version=3,
            )
        with pytest.raises(ValueError, match="one routing decision per capability"):
            recompose_model_assignments(
                session,
                task,
                [equivalent_new_decisions[0], equivalent_new_decisions[0]],
                team_plan=plan,
                task_version=4,
            )

        other_task = Task(project_id=project.id, title="Unrelated task", task_version=1)
        session.add(other_task)
        session.flush()
        other_plan = compose_team(session, other_task)
        with pytest.raises(ValueError, match="plan must belong"):
            recompose_model_assignments(
                session,
                task,
                [*equivalent_new_decisions, risk_route],
                team_plan=other_plan,
                task_version=4,
            )

        other_pack = CodexInstructionPack(
            task_id=other_task.id,
            version=1,
            content="unrelated bounded pack",
            stage_summary="stage",
            key_boundaries="boundary",
            acceptance_target="acceptance",
            source_baseline_commit="baseline",
            assignment_version=4,
            task_version=4,
            routing_snapshot_hash=retargeted[0].routing_snapshot_hash,
        )
        session.add(other_pack)
        session.flush()
        unrelated_run = CodexRun(
            task_id=other_task.id,
            pack_id=other_pack.id,
            assignment_version=4,
            task_version=4,
            routing_snapshot_hash=retargeted[0].routing_snapshot_hash,
        )
        session.add(unrelated_run)
        session.flush()
        retargeted_planning = next(item for item in retargeted if item.capability == "planning")
        assert retargeted_planning.assigned_model is not None
        with pytest.raises(ValueError, match="Codex run does not match"):
            record_model_invocation_evidence(
                session,
                model=retargeted_planning.assigned_model,
                assignment=retargeted_planning,
                task_id=task.id,
                codex_run_id=unrelated_run.id,
                capability="planning",
                assignment_version=retargeted_planning.assignment_version,
                invocation_ref="vol17-cross-task-evidence-001",
                invocation_mode="real",
                outcome="succeeded",
                actual_invoked_model_identifier="retargeted-provider-model-v2",
                process_evidence={"process_observed": True, "exit_code": 0},
                provider_evidence={
                    "provider_response_observed": True,
                    "model_identifier_match": True,
                    "status_code": 200,
                },
            )
