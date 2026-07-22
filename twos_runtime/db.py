from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    AICapability,
    AIModel,
    AIModelAvailabilityEvidence,
    Base,
    Project,
    Provider,
    SchemaVersion,
    Tool,
    stable_model_identifier,
)


VOL17_SCHEMA_VERSION = "vol17.001"
VOL17_MODEL_SETUP_SCHEMA_VERSION = "vol17.002"
VOL17_END_TO_END_SCHEMA_VERSION = "vol17.003"
VOL17_REAL_EVIDENCE_SCHEMA_VERSION = "vol17.004"


DEFAULT_PROJECTS = [
    ("ldd", "LDD"),
    ("wc", "2026WC"),
    ("twos", "TWOS Product Development"),
]

# Vol.17 does not invent vendor configuration. Model providers are created only
# from explicit runtime/persisted configuration; upgraded Vol.16 placeholders
# remain preserved in the database but are not treated as configured records.
DEFAULT_PROVIDERS: list[tuple[str, str, str, str]] = []

DEFAULT_AI_CAPABILITIES = [
    ("reasoning", "Frame decisions and resolve multi-step ambiguity.", "high", "medium", False, True),
    ("coding", "Design and implement product or software changes.", "high", "medium", True, True),
    ("research", "Gather and synthesize evidence for a task.", "high", "low", True, True),
    ("verification", "Check boundaries, evidence, and acceptance conditions.", "high", "medium", False, False),
    ("summarization", "Compress source material without losing decisions or boundaries.", "medium", "high", False, True),
    ("planning", "Turn goals into an ordered, reviewable execution plan.", "high", "medium", False, True),
    ("risk_analysis", "Identify downside, uncovered tails, and policy boundaries.", "high", "medium", False, True),
    ("data_analysis", "Interpret structured evidence and quantitative outputs.", "high", "medium", True, True),
]

DEFAULT_AI_MODELS: list[tuple[str, str, list[str], int]] = []

DEFAULT_TOOLS = [
    ("Calendar", "calendar", "unconfigured", "Required slot; no event creation configured."),
    ("Outlook / Email", "email", "unconfigured", "Required slot; no auto-send configured."),
    ("IM / Chat", "messaging", "unconfigured", "Required slot; no auto-post configured."),
    ("Task tracker", "task_tool", "unconfigured", "Required slot; no task write adapter configured."),
    ("File / document workspace", "workspace", "unconfigured", "Required slot; no document adapter configured."),
    ("Trading execution", "live_trade", "blocked", "Hard policy denial."),
    ("Betting execution", "live_bet", "blocked", "Hard policy denial."),
]

COLUMN_MIGRATIONS = {
    "tasks": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("workflow_type", "VARCHAR(80) NOT NULL DEFAULT 'general'"),
        ("objective", "TEXT NOT NULL DEFAULT ''"),
        ("implementation_scope", "TEXT NOT NULL DEFAULT ''"),
        ("forbidden_scope", "TEXT NOT NULL DEFAULT ''"),
        ("acceptance_target", "TEXT NOT NULL DEFAULT ''"),
        ("repository_identity", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("source_baseline_commit", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("objective_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("source_context_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("required_output_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("acceptance_target_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("implementation_scope_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
    ],
    "ai_models": [
        ("stable_id", "VARCHAR(160)"),
        ("display_name", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("provider_model_id", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("execution_adapter", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("configuration_status", "VARCHAR(40) NOT NULL DEFAULT 'needs_setup'"),
        ("availability_status", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("invocation_mode", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("last_invocation_outcome", "VARCHAR(40) NOT NULL DEFAULT 'not_invoked'"),
        ("evidence_status", "VARCHAR(40) NOT NULL DEFAULT 'unverified'"),
        ("evidence_source", "VARCHAR(80) NOT NULL DEFAULT 'none'"),
        ("last_verified_at", "DATETIME"),
        ("safe_diagnostic", "TEXT NOT NULL DEFAULT ''"),
    ],
    "ai_team_plans": [
        ("omitted_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("omission_explanation", "TEXT NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "ai_team_plan_items": [
        ("selection_reason", "TEXT NOT NULL DEFAULT ''"),
    ],
    "routing_decisions": [
        ("requested_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("fallback_status", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("fallback_reason", "TEXT NOT NULL DEFAULT ''"),
        ("next_action", "TEXT NOT NULL DEFAULT ''"),
    ],
    "codex_instruction_packs": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("development_task_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
    ],
    "codex_runs": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("development_task_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("execution_assignment_id", "INTEGER"),
        ("execution_model_id", "INTEGER"),
        ("execution_provider_id", "INTEGER"),
        ("requested_model_identifier", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("fallback_selected", "BOOLEAN NOT NULL DEFAULT 0"),
        ("launch_intent_at", "DATETIME"),
        ("process_spawned", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_assignment_id", "INTEGER"),
        ("verification_model_id", "INTEGER"),
        ("verification_provider_id", "INTEGER"),
        ("verification_model_identifier", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("verification_status", "VARCHAR(40) NOT NULL DEFAULT 'not_started'"),
        ("verification_summary", "TEXT NOT NULL DEFAULT ''"),
        ("verification_process_spawned", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_stdout", "TEXT NOT NULL DEFAULT ''"),
        ("verification_stderr", "TEXT NOT NULL DEFAULT ''"),
        ("verification_exit_code", "INTEGER"),
        ("verification_duration_ms", "INTEGER"),
        ("verification_timed_out", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_cancelled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_output_truncated", "BOOLEAN NOT NULL DEFAULT 0"),
    ],
}


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    ensure_runtime_columns(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp14.001")):
            session.add(SchemaVersion(version="mvp14.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp15.001")):
            session.add(SchemaVersion(version="mvp15.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp15.002")):
            session.add(SchemaVersion(version="mvp15.002"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "vol16.001")):
            session.add(SchemaVersion(version="vol16.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)):
            session.add(SchemaVersion(version=VOL17_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_MODEL_SETUP_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_MODEL_SETUP_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_END_TO_END_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_END_TO_END_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_REAL_EVIDENCE_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_REAL_EVIDENCE_SCHEMA_VERSION))
        seed_projects(session)
        seed_registry(session)
        session.flush()
        seed_ai_registry(session)
        session.commit()


def ensure_runtime_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added_columns: dict[str, set[str]] = {}
    with engine.begin() as connection:
        for table_name, definitions in COLUMN_MIGRATIONS.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in definitions:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
                    added_columns.setdefault(table_name, set()).add(column_name)
        if "ai_models" in tables:
            added_model_columns = added_columns.get("ai_models", set())
            _backfill_ai_model_registry(
                connection,
                promote_configuration_state="configuration_status" in added_model_columns,
                promote_availability_state="availability_status" in added_model_columns,
            )
    if "ai_models" in tables:
        _ensure_ai_model_stable_id_index(engine)
        _ensure_vol17_ai_model_indexes(engine)
    if "codex_runs" in tables:
        _ensure_vol17_codex_run_indexes(engine)
    if "codex_instruction_packs" in tables:
        _ensure_vol17_pack_indexes(engine)


def _backfill_ai_model_registry(
    connection: Connection,
    *,
    promote_configuration_state: bool,
    promote_availability_state: bool,
) -> None:
    """Populate additive registry fields and translate legacy state exactly once."""
    rows = list(
        connection.execute(
            text(
                "SELECT m.id, m.provider_id, m.model_name, m.stable_id, m.display_name, m.status, "
                "m.configuration_status, m.availability_status, p.enabled AS provider_enabled, "
                "p.status AS provider_status FROM ai_models AS m "
                "LEFT JOIN providers AS p ON p.id = m.provider_id ORDER BY m.id"
            )
        ).mappings()
    )
    reserved_ids = {
        str(row["stable_id"])
        for row in rows
        if row["stable_id"]
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", str(row["stable_id"]))
    }
    used_ids: set[str] = set()
    for row in rows:
        stable_id = str(row["stable_id"] or "")
        stable_id_is_safe = bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", stable_id)
        )
        if not stable_id_is_safe or stable_id in used_ids:
            base = stable_model_identifier(int(row["provider_id"]), str(row["model_name"]))
            candidate = base
            suffix = 0
            while candidate in reserved_ids or candidate in used_ids:
                suffix += 1
                available = max(1, 158 - len(str(row["id"])) - len(str(suffix)))
                candidate = f"{base[:available]}.{int(row['id'])}.{suffix}"
            stable_id = candidate
        used_ids.add(stable_id)
        legacy_status = str(row["status"] or "unconfigured")
        provider_status = str(row["provider_status"] or "unconfigured")
        provider_eligible = bool(row["provider_enabled"]) and provider_status in {"healthy", "degraded"}
        configuration_status = str(row["configuration_status"] or "needs_setup")
        if configuration_status not in {"configured", "needs_setup", "disabled"}:
            configuration_status = "needs_setup"
        if (
            promote_configuration_state
            and configuration_status == "needs_setup"
            and legacy_status in {"healthy", "degraded"}
            and provider_eligible
        ):
            configuration_status = "configured"
        if promote_configuration_state and (
            legacy_status in {"blocked", "disabled"}
            or provider_status in {"blocked", "disabled"}
        ):
            configuration_status = "disabled"
        availability_status = str(row["availability_status"] or "unavailable")
        if availability_status not in {"available", "unavailable", "disabled"}:
            availability_status = "unavailable"
        if promote_availability_state and legacy_status in {"healthy", "degraded"} and provider_eligible:
            availability_status = "available"
        elif promote_availability_state and (
            legacy_status in {"blocked", "disabled"}
            or provider_status in {"blocked", "disabled"}
        ):
            availability_status = "disabled"
        connection.execute(
            text(
                "UPDATE ai_models SET stable_id = :stable_id, display_name = :display_name, "
                "configuration_status = :configuration_status, availability_status = :availability_status "
                "WHERE id = :model_id"
            ),
            {
                "stable_id": stable_id,
                "display_name": str(row["display_name"] or row["model_name"]),
                "configuration_status": configuration_status,
                "availability_status": availability_status,
                "model_id": int(row["id"]),
            },
        )


def _ensure_ai_model_stable_id_index(engine: Engine) -> None:
    inspector = inspect(engine)
    unique_indexes = [
        item
        for item in inspector.get_indexes("ai_models")
        if item.get("unique") and item.get("column_names") == ["stable_id"]
    ]
    unique_constraints = [
        item
        for item in inspector.get_unique_constraints("ai_models")
        if item.get("column_names") == ["stable_id"]
    ]
    if unique_indexes or unique_constraints:
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX ux_ai_models_stable_id ON ai_models (stable_id)"))


def _ensure_vol17_ai_model_indexes(engine: Engine) -> None:
    """Give upgraded databases the indexes that fresh mapped tables receive."""
    required = {
        "ix_ai_models_configuration_status": "configuration_status",
        "ix_ai_models_availability_status": "availability_status",
        "ix_ai_models_invocation_mode": "invocation_mode",
        "ix_ai_models_last_invocation_outcome": "last_invocation_outcome",
        "ix_ai_models_evidence_status": "evidence_status",
    }
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("ai_models")
    }
    missing = [
        (index_name, column_name)
        for index_name, column_name in required.items()
        if (column_name,) not in indexed_columns
    ]
    if not missing:
        return
    with engine.begin() as connection:
        for index_name, column_name in missing:
            connection.execute(text(f"CREATE INDEX {index_name} ON ai_models ({column_name})"))


def _ensure_vol17_codex_run_indexes(engine: Engine) -> None:
    """Align additive-upgrade execution-target lookup indexes with fresh databases."""
    required = {
        "ix_codex_runs_execution_assignment_id": "execution_assignment_id",
        "ix_codex_runs_execution_model_id": "execution_model_id",
        "ix_codex_runs_execution_provider_id": "execution_provider_id",
        "ix_codex_runs_verification_assignment_id": "verification_assignment_id",
        "ix_codex_runs_verification_model_id": "verification_model_id",
        "ix_codex_runs_verification_provider_id": "verification_provider_id",
        "ix_codex_runs_source_snapshot_digest": "source_snapshot_digest",
        "ix_codex_runs_verification_status": "verification_status",
    }
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_runs")
    }
    missing = [
        (index_name, column_name)
        for index_name, column_name in required.items()
        if (column_name,) not in indexed_columns
    ]
    if not missing:
        return
    with engine.begin() as connection:
        for index_name, column_name in missing:
            connection.execute(text(f"CREATE INDEX {index_name} ON codex_runs ({column_name})"))


def _ensure_vol17_pack_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_instruction_packs")
    }
    if ("source_snapshot_digest",) in indexed_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE INDEX ix_codex_instruction_packs_source_snapshot_digest "
                "ON codex_instruction_packs (source_snapshot_digest)"
            )
        )


def seed_projects(session: Session) -> None:
    for key, name in DEFAULT_PROJECTS:
        if not session.scalar(select(Project).where(Project.key == key)):
            session.add(Project(key=key, name=name, status="active"))


def seed_registry(session: Session) -> None:
    for name, kind, status, details in DEFAULT_PROVIDERS:
        existing = session.scalar(select(Provider).where(Provider.name == name, Provider.kind == kind))
        if not existing:
            session.add(Provider(name=name, kind=kind, status=status, enabled=False, details=details))
    for name, kind, status, details in DEFAULT_TOOLS:
        existing = session.scalar(select(Tool).where(Tool.name == name, Tool.kind == kind))
        if not existing:
            session.add(Tool(name=name, kind=kind, status=status, enabled=False, details=details))


def seed_ai_registry(session: Session) -> None:
    for name, description, quality, latency, requires_tool, requires_verification in DEFAULT_AI_CAPABILITIES:
        if not session.scalar(select(AICapability).where(AICapability.name == name)):
            session.add(
                AICapability(
                    name=name,
                    description=description,
                    quality_requirement=quality,
                    latency_sensitivity=latency,
                    requires_tool_capability=requires_tool,
                    requires_verification=requires_verification,
                    enabled=True,
                )
            )

    providers = {item.name: item for item in session.scalars(select(Provider).where(Provider.kind == "model")).all()}
    for provider_name, model_name, capability_tags, priority in DEFAULT_AI_MODELS:
        provider = providers.get(provider_name)
        if not provider:
            continue
        existing = session.scalar(
            select(AIModel).where(AIModel.provider_id == provider.id, AIModel.model_name == model_name)
        )
        if not existing:
            session.add(
                AIModel(
                    provider_id=provider.id,
                    model_name=model_name,
                    stable_id=stable_model_identifier(provider.id, model_name),
                    display_name=model_name,
                    provider_model_id="",
                    execution_adapter="",
                    capability_tags=json.dumps(capability_tags, separators=(",", ":")),
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
                    routing_priority=priority,
                )
            )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
