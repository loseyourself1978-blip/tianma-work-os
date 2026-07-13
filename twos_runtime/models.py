from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(160))
    password_salt: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sessions: Mapped[list["SessionToken"]] = relationship(back_populates="user")


class SessionToken(Base):
    __tablename__ = "session_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(80), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    tasks: Mapped[list["Task"]] = relationship(back_populates="project")
    sync_entries: Mapped[list["SyncEntry"]] = relationship(back_populates="project")


class SyncEntry(Base):
    __tablename__ = "sync_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    project: Mapped[Project] = relationship(back_populates="sync_entries")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    task_type: Mapped[str] = mapped_column(String(80), default="Sync Intake")
    source_sync_summary: Mapped[str] = mapped_column(Text, default="")
    required_output: Mapped[str] = mapped_column(Text, default="")
    boundary_risk: Mapped[str] = mapped_column(Text, default="")
    workflow_type: Mapped[str] = mapped_column(String(80), default="general", index=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    implementation_scope: Mapped[str] = mapped_column(Text, default="")
    forbidden_scope: Mapped[str] = mapped_column(Text, default="")
    acceptance_target: Mapped[str] = mapped_column(Text, default="")
    repository_identity: Mapped[str] = mapped_column(String(240), default="")
    source_baseline_commit: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    acceptance_state: Mapped[str] = mapped_column(String(40), default="needs_review")
    compact_sync_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    project: Mapped[Project] = relationship(back_populates="tasks")
    runs: Mapped[list["TaskRun"]] = relationship(back_populates="task")
    acceptance_checks: Mapped[list["AcceptanceCheck"]] = relationship(back_populates="task")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="task")
    ai_team_plans: Mapped[list["AITeamPlan"]] = relationship(back_populates="task")
    routing_decisions: Mapped[list["RoutingDecision"]] = relationship(back_populates="task")
    codex_packs: Mapped[list["CodexInstructionPack"]] = relationship(back_populates="task")
    codex_runs: Mapped[list["CodexRun"]] = relationship(back_populates="task")
    owner_acceptance_sessions: Mapped[list["OwnerAcceptanceSession"]] = relationship(back_populates="task")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), default="compact_sync")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="runs")


class AcceptanceCheck(Base):
    __tablename__ = "acceptance_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("task_runs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="acceptance_checks")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    task: Mapped[Task] = relationship(back_populates="schedules")


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (UniqueConstraint("name", "kind", name="uq_provider_name_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="unconfigured")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    models: Mapped[list["AIModel"]] = relationship(back_populates="provider")


class AICapability(Base):
    __tablename__ = "ai_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    quality_requirement: Mapped[str] = mapped_column(String(40))
    latency_sensitivity: Mapped[str] = mapped_column(String(40))
    requires_tool_capability: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AIModel(Base):
    __tablename__ = "ai_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_name", name="uq_ai_model_provider_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(160))
    capability_tags: Mapped[str] = mapped_column(Text, default="[]")
    context_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_metadata: Mapped[str] = mapped_column(String(40), default="unknown")
    latency_metadata: Mapped[str] = mapped_column(String(40), default="unknown")
    status: Mapped[str] = mapped_column(String(40), default="unconfigured", index=True)
    routing_priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    provider: Mapped[Provider] = relationship(back_populates="models")


class AITeamPlan(Base):
    __tablename__ = "ai_team_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    risk_level: Mapped[str] = mapped_column(String(40), default="medium")
    urgency: Mapped[str] = mapped_column(String(40), default="normal")
    required_capabilities: Mapped[str] = mapped_column(Text, default="[]")
    omitted_capabilities: Mapped[str] = mapped_column(Text, default="[]")
    minimum_role_count: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(40), default="composed")
    explanation: Mapped[str] = mapped_column(Text)
    omission_explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="ai_team_plans")
    items: Mapped[list["AITeamPlanItem"]] = relationship(back_populates="plan")


class AITeamPlanItem(Base):
    __tablename__ = "ai_team_plan_items"
    __table_args__ = (UniqueConstraint("plan_id", "capability_id", name="uq_ai_team_plan_capability"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("ai_team_plans.id"), index=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("ai_capabilities.id"), index=True)
    role_label: Mapped[str] = mapped_column(String(120))
    selection_reason: Mapped[str] = mapped_column(Text, default="")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped[AITeamPlan] = relationship(back_populates="items")
    capability: Mapped[AICapability] = relationship()


class RoutingDecision(Base):
    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    team_plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_team_plans.id"), nullable=True, index=True)
    capability_id: Mapped[int] = mapped_column(ForeignKey("ai_capabilities.id"), index=True)
    urgency: Mapped[str] = mapped_column(String(40), default="normal")
    cost_sensitivity: Mapped[str] = mapped_column(String(40), default="balanced")
    latency_sensitivity: Mapped[str] = mapped_column(String(40), default="balanced")
    requested_capabilities: Mapped[str] = mapped_column(Text, default="[]")
    selected_model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_models.id"), nullable=True)
    fallback_model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_models.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="unavailable")
    reason: Mapped[str] = mapped_column(Text)
    fallback_status: Mapped[str] = mapped_column(String(40), default="unavailable")
    fallback_reason: Mapped[str] = mapped_column(Text, default="")
    next_action: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="routing_decisions")
    team_plan: Mapped[Optional[AITeamPlan]] = relationship()
    capability: Mapped[AICapability] = relationship()
    selected_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[selected_model_id])
    fallback_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[fallback_model_id])


class CodexInstructionPack(Base):
    __tablename__ = "codex_instruction_packs"
    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_codex_pack_task_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="approval_required", index=True)
    content: Mapped[str] = mapped_column(Text)
    stage_summary: Mapped[str] = mapped_column(Text)
    key_boundaries: Mapped[str] = mapped_column(Text)
    acceptance_target: Mapped[str] = mapped_column(Text)
    source_baseline_commit: Mapped[str] = mapped_column(String(80))
    ai_team_plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_team_plans.id"), nullable=True)
    routing_decision_ids: Mapped[str] = mapped_column(Text, default="[]")
    generation_metadata: Mapped[str] = mapped_column(Text, default="{}")
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[Task] = relationship(back_populates="codex_packs")
    ai_team_plan: Mapped[Optional[AITeamPlan]] = relationship()
    runs: Mapped[list["CodexRun"]] = relationship(back_populates="pack")


class CodexRun(Base):
    __tablename__ = "codex_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("codex_instruction_packs.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="approval_required", index=True)
    executable_status: Mapped[str] = mapped_column(String(40), default="unconfigured")
    source_repo: Mapped[str] = mapped_column(Text, default="")
    source_branch: Mapped[str] = mapped_column(String(240), default="")
    source_commit: Mapped[str] = mapped_column(String(80), default="")
    worktree_path: Mapped[str] = mapped_column(Text, default="")
    worktree_branch: Mapped[str] = mapped_column(String(240), default="")
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    structured_result: Mapped[str] = mapped_column(Text, default="{}")
    owner_summary: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="codex_runs")
    pack: Mapped[CodexInstructionPack] = relationship(back_populates="runs")
    acceptance_session: Mapped[Optional["OwnerAcceptanceSession"]] = relationship(back_populates="codex_run")


class OwnerAcceptanceSession(Base):
    __tablename__ = "owner_acceptance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    codex_run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="owner_review", index=True)
    owner_note: Mapped[str] = mapped_column(Text, default="")
    compact_sync_result: Mapped[str] = mapped_column(Text, default="")
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="owner_acceptance_sessions")
    codex_run: Mapped[CodexRun] = relationship(back_populates="acceptance_session")
    items: Mapped[list["OwnerAcceptanceItem"]] = relationship(back_populates="session")


class OwnerAcceptanceItem(Base):
    __tablename__ = "owner_acceptance_items"
    __table_args__ = (UniqueConstraint("session_id", "key", name="uq_owner_acceptance_item_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("owner_acceptance_sessions.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(240))
    inspect_target: Mapped[str] = mapped_column(Text)
    ui_path: Mapped[str] = mapped_column(Text)
    pass_standard: Mapped[str] = mapped_column(Text)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    note: Mapped[str] = mapped_column(Text, default="")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[OwnerAcceptanceSession] = relationship(back_populates="items")


class Tool(Base):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("name", "kind", name="uq_tool_name_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="unconfigured")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
