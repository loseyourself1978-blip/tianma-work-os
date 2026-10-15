"""Additive R2 tables. Never rewrite legacy Task/Run/approval records.

The extension has its own version row; vol20.001 storage stays compatible with
101.10. Older applications cannot operate these records, but do not delete them.
"""
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base


class ProjectSpace(Base):
    __tablename__ = "r2_project_spaces"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    goal: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    team_json: Mapped[str] = mapped_column(Text, default="{}")
    target_json: Mapped[str] = mapped_column(Text, default="{}")


class ProjectSource(Base):
    __tablename__ = "r2_project_sources"
    __table_args__ = (UniqueConstraint("project_id", "name", "sha256"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("r2_project_spaces.project_id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))
    receipt_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class ImportPreview(Base):
    __tablename__ = "r2_import_previews"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("r2_project_spaces.project_id"), index=True)
    archive_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    receipt_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40))
    confirmed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class WorkItem(Base):
    __tablename__ = "r2_work_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("r2_project_spaces.project_id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="document")
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    output_locale: Mapped[str] = mapped_column(String(16))
    sources_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(40), default="DRAFT")
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    plan_hash: Mapped[str] = mapped_column(String(64), default="")
    approval_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40))


class WorkExecution(Base):
    __tablename__ = "r2_work_executions"
    __table_args__ = (UniqueConstraint("work_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("r2_work_items.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    plan_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(40))
    input_json: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    output: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str] = mapped_column(String(80), default="")
    started_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ProjectActivity(Base):
    __tablename__ = "r2_project_activity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("r2_project_spaces.project_id"), index=True)
    work_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40))
    event: Mapped[str] = mapped_column(String(80))
    content_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class ProductPreference(Base):
    __tablename__ = "r2_product_preferences"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
