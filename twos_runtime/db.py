from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from .models import AICapability, AIModel, Base, Project, Provider, SchemaVersion, Tool


DEFAULT_PROJECTS = [
    ("ldd", "LDD"),
    ("wc", "2026WC"),
    ("twos", "TWOS Product Development"),
]

DEFAULT_PROVIDERS = [
    ("OpenAI", "model", "unconfigured", "Gateway slot only; no credentials or external adapter configured."),
    ("Gemini", "model", "unconfigured", "Gateway slot only; no credentials or external adapter configured."),
    ("Claude", "model", "unconfigured", "Gateway slot only; no credentials or external adapter configured."),
    ("DeepSeek", "model", "unconfigured", "Gateway slot only; no credentials or external adapter configured."),
    ("GLM", "model", "unconfigured", "Gateway slot only; no credentials or external adapter configured."),
]

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

DEFAULT_AI_MODELS = [
    ("OpenAI", "GPT family reasoning profile", ["reasoning", "planning", "summarization"], 10),
    ("OpenAI", "GPT family coding profile", ["coding", "verification"], 20),
    ("Gemini", "Gemini family research profile", ["research", "data_analysis", "summarization"], 30),
    ("Gemini", "Gemini family reasoning profile", ["reasoning", "planning"], 40),
    ("Claude", "Claude family analysis profile", ["reasoning", "verification", "risk_analysis"], 30),
    ("Claude", "Claude family coding profile", ["coding", "planning", "verification"], 40),
    ("DeepSeek", "DeepSeek family reasoning profile", ["reasoning", "risk_analysis", "data_analysis"], 40),
    ("DeepSeek", "DeepSeek family coding profile", ["coding", "verification"], 50),
    ("GLM", "GLM family planning profile", ["planning", "summarization", "research"], 50),
    ("GLM", "GLM family analysis profile", ["reasoning", "data_analysis", "verification"], 60),
]

DEFAULT_TOOLS = [
    ("Codex", "developer_tool", "unconfigured", "Manual handoff exists; automatic adapter is not configured."),
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
        ("workflow_type", "VARCHAR(80) NOT NULL DEFAULT 'general'"),
        ("objective", "TEXT NOT NULL DEFAULT ''"),
        ("implementation_scope", "TEXT NOT NULL DEFAULT ''"),
        ("forbidden_scope", "TEXT NOT NULL DEFAULT ''"),
        ("acceptance_target", "TEXT NOT NULL DEFAULT ''"),
        ("repository_identity", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("source_baseline_commit", "VARCHAR(80) NOT NULL DEFAULT ''"),
    ],
    "ai_team_plans": [
        ("omitted_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("omission_explanation", "TEXT NOT NULL DEFAULT ''"),
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
        seed_projects(session)
        seed_registry(session)
        session.flush()
        seed_ai_registry(session)
        session.commit()


def ensure_runtime_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table_name, definitions in COLUMN_MIGRATIONS.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in definitions:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))


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
                    capability_tags=json.dumps(capability_tags, separators=(",", ":")),
                    context_limit=None,
                    cost_metadata="unknown",
                    latency_metadata="unknown",
                    status="unconfigured",
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
