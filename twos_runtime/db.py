from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Project, Provider, SchemaVersion, Tool


DEFAULT_PROJECTS = [
    ("ldd", "LDD"),
    ("wc", "2026WC"),
    ("twos", "TWOS Product Development"),
]

DEFAULT_PROVIDERS = [
    ("OpenAI", "model", "unconfigured", "Required for TWOS 1.0; no provider key configured yet."),
    ("Gemini", "model", "unconfigured", "Required future adapter slot; no fake integration claim."),
    ("Claude", "model", "unconfigured", "Required future adapter slot; no fake integration claim."),
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


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp14.001")):
            session.add(SchemaVersion(version="mvp14.001"))
        seed_projects(session)
        seed_registry(session)
        session.commit()


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
