from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect as sa_inspect,
    text,
)
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


class Installation(Base):
    """One persisted, data-root-scoped First Run installation."""

    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source_version: Mapped[str] = mapped_column(String(40))
    data_root: Mapped[str] = mapped_column(Text)
    database_path: Mapped[str] = mapped_column(Text)
    runtime_environment: Mapped[str] = mapped_column(Text, default="")
    log_directory: Mapped[str] = mapped_column(Text)
    bind_host: Mapped[str] = mapped_column(String(80), default="127.0.0.1")
    bind_port: Mapped[int] = mapped_column(Integer)
    first_run_state: Mapped[str] = mapped_column(
        String(80), default="uninitialized", index=True
    )
    setup_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    setup_token_issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    setup_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    setup_token_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    owner_setup_request_id: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True, unique=True
    )
    owner_setup_request_digest: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, unique=True
    )
    optional_tools_state: Mapped[str] = mapped_column(Text, default='{"codex":"not_checked"}')
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resume_state: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AuthorizedWorkspace(Base):
    """The exact local directory explicitly authorized by the first Owner."""

    __tablename__ = "authorized_workspaces"
    __table_args__ = (
        UniqueConstraint("installation_id", "canonical_path", name="uq_installation_workspace_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("installations.id"), unique=True, index=True
    )
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    canonical_path: Mapped[str] = mapped_column(Text)
    device_id: Mapped[int] = mapped_column(Integer)
    inode: Mapped[int] = mapped_column(Integer)
    identity_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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


class ProjectWorkspaceAuthorization(Base):
    """Additional project scopes; the First Run installation binding stays intact."""

    __tablename__ = "project_workspace_authorizations"
    __table_args__ = (
        UniqueConstraint("installation_id", "canonical_path", name="uq_project_workspace_path"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(ForeignKey("installations.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    canonical_path: Mapped[str] = mapped_column(Text)
    device_id: Mapped[int] = mapped_column(Integer)
    inode: Mapped[int] = mapped_column(Integer)
    identity_digest: Mapped[str] = mapped_column(String(64), unique=True)
    recovery_epoch: Mapped[str] = mapped_column(String(80), default="")
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TaskArtifactContract(Base):
    """Append-only, Owner-declared exact-file checks, never executable commands."""

    __tablename__ = "task_artifact_contracts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    specification_json: Mapped[str] = mapped_column(Text)
    specification_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    development_task: Mapped[str] = mapped_column(Text, default="")
    task_type: Mapped[str] = mapped_column(String(80), default="Sync Intake")
    source_sync_summary: Mapped[str] = mapped_column(Text, default="")
    required_output: Mapped[str] = mapped_column(Text, default="")
    boundary_risk: Mapped[str] = mapped_column(Text, default="")
    workflow_type: Mapped[str] = mapped_column(String(80), default="general", index=True)
    objective: Mapped[str] = mapped_column(Text, default="")
    implementation_scope: Mapped[str] = mapped_column(Text, default="")
    forbidden_scope: Mapped[str] = mapped_column(Text, default="")
    acceptance_target: Mapped[str] = mapped_column(Text, default="")
    objective_provenance: Mapped[str] = mapped_column(String(40), default="derived")
    source_context_provenance: Mapped[str] = mapped_column(String(40), default="derived")
    required_output_provenance: Mapped[str] = mapped_column(String(40), default="derived")
    acceptance_target_provenance: Mapped[str] = mapped_column(String(40), default="derived")
    implementation_scope_provenance: Mapped[str] = mapped_column(String(40), default="derived")
    repository_identity: Mapped[str] = mapped_column(String(240), default="")
    source_baseline_commit: Mapped[str] = mapped_column(String(80), default="")
    task_version: Mapped[int] = mapped_column(Integer, default=1)
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


class GuidedToolConfiguration(Base):
    """One Owner-confirmed configuration; credentials always remain with Codex."""

    __tablename__ = "guided_tool_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ai_models.id"))
    snapshot_json: Mapped[str] = mapped_column(Text)
    configuration_digest: Mapped[str] = mapped_column(String(64))
    connectivity_evidence_id: Mapped[Optional[int]] = mapped_column(ForeignKey("codex_connectivity_evidence.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    # Keep the fresh and additive-upgrade schemas equivalent. SQLite cannot add
    # CHECK constraints without rebuilding the legacy table, so Vol.17 validates
    # these states at the orchestration boundary instead.
    __table_args__ = (UniqueConstraint("provider_id", "model_name", name="uq_ai_model_provider_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(160))
    stable_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    provider_model_id: Mapped[str] = mapped_column(String(240), default="")
    execution_adapter: Mapped[str] = mapped_column(String(40), default="")
    capability_tags: Mapped[str] = mapped_column(Text, default="[]")
    context_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_metadata: Mapped[str] = mapped_column(String(40), default="unknown")
    latency_metadata: Mapped[str] = mapped_column(String(40), default="unknown")
    status: Mapped[str] = mapped_column(String(40), default="unconfigured", index=True)
    configuration_status: Mapped[str] = mapped_column(String(40), default="needs_setup", index=True)
    availability_status: Mapped[str] = mapped_column(String(40), default="unavailable", index=True)
    invocation_mode: Mapped[str] = mapped_column(String(40), default="unavailable", index=True)
    last_invocation_outcome: Mapped[str] = mapped_column(String(40), default="not_invoked", index=True)
    evidence_status: Mapped[str] = mapped_column(String(40), default="unverified", index=True)
    evidence_source: Mapped[str] = mapped_column(String(80), default="none")
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    safe_diagnostic: Mapped[str] = mapped_column(Text, default="")
    routing_priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    provider: Mapped[Provider] = relationship(back_populates="models")


class AIModelAvailabilityEvidence(Base):
    __tablename__ = "ai_model_availability_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    configuration_identity: Mapped[str] = mapped_column(String(160), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ai_models.id"), index=True)
    checked_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    adapter: Mapped[str] = mapped_column(String(40), index=True)
    invocation_mode: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(40), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80))
    failure_classification: Mapped[str] = mapped_column(String(80), default="")
    runtime_identity: Mapped[str] = mapped_column(String(240), default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    model: Mapped[AIModel] = relationship()


class CodexConnectivityEvidence(Base):
    """Append-only evidence for one explicit Owner-triggered real CLI probe."""

    __tablename__ = "codex_connectivity_evidence"
    __table_args__ = (
        CheckConstraint(
            "readiness_state IN ("
            "'CLI_NOT_INSTALLED','AUTHENTICATION_REQUIRED',"
            "'AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED','PROVIDER_UNREACHABLE',"
            "'MODEL_UNAVAILABLE','READY_FOR_REAL_RUN','BLOCKED'"
            ")",
            name="ck_codex_connectivity_readiness_state",
        ),
        CheckConstraint(
            "authentication_state IN ("
            "'CHATGPT_LOGIN_AUTHENTICATED','API_KEY_AUTHENTICATED',"
            "'AUTHENTICATION_REQUIRED','CREDENTIAL_STORE_UNAVAILABLE',"
            "'AUTHENTICATION_UNKNOWN'"
            ")",
            name="ck_codex_connectivity_authentication_state",
        ),
        CheckConstraint("duration_ms >= 0", name="ck_codex_connectivity_duration_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_models.id"), nullable=True, index=True
    )
    configuration_identity: Mapped[str] = mapped_column(String(160), default="", index=True)
    requested_model_identifier: Mapped[str] = mapped_column(String(240), default="", index=True)
    actual_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    readiness_state: Mapped[str] = mapped_column(String(64), index=True)
    cli_installed: Mapped[bool] = mapped_column(Boolean, default=False)
    cli_version: Mapped[str] = mapped_column(String(120), default="")
    executable_identity: Mapped[str] = mapped_column(String(64), default="", index=True)
    execution_context_identity: Mapped[str] = mapped_column(String(64), default="", index=True)
    authentication_state: Mapped[str] = mapped_column(String(64), index=True)
    authentication_method: Mapped[str] = mapped_column(String(40), default="unknown")
    credential_store: Mapped[str] = mapped_column(String(40), default="unknown")
    credential_store_accessible: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_reachable: Mapped[bool] = mapped_column(Boolean, default=False)
    model_available: Mapped[bool] = mapped_column(Boolean, default=False)
    interactive_prompt_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    blocker_code: Mapped[str] = mapped_column(String(80), default="")
    safe_summary: Mapped[str] = mapped_column(Text, default="")
    sanitized_command: Mapped[str] = mapped_column(Text, default="")
    diagnostic_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )

    model: Mapped[Optional[AIModel]] = relationship()


def stable_model_identifier(provider_id: int, model_name: str) -> str:
    """Return a deterministic, non-secret identity for a provider/model pair."""
    normalized = re.sub(r"[^a-z0-9]+", "-", model_name.casefold()).strip("-") or "model"
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:10]
    return f"provider-{provider_id}.{normalized[:96]}.{digest}"


@event.listens_for(AIModel, "before_insert")
def _populate_ai_model_identity(_mapper: object, _connection: object, model: AIModel) -> None:
    # Existing integrations only provide provider_id/model_name. Preserve that API
    # while ensuring every newly persisted model receives a stable registry identity.
    if not model.stable_id:
        model.stable_id = stable_model_identifier(model.provider_id, model.model_name)
    if not model.display_name:
        model.display_name = model.model_name


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
    assignment_version: Mapped[int] = mapped_column(Integer, default=0)
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    routing_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
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


class AIModelAssignment(Base):
    __tablename__ = "ai_model_assignments"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "assignment_version",
            "task_version",
            "role",
            name="uq_ai_model_assignment_task_assignment_task_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    team_plan_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_team_plans.id"), nullable=True, index=True)
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    assignment_version: Mapped[int] = mapped_column(Integer, default=1, index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    capability: Mapped[str] = mapped_column(String(80))
    routing_snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    assigned_model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_models.id"), nullable=True)
    fallback_model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_models.id"), nullable=True)
    assignment_reason: Mapped[str] = mapped_column(Text, default="")
    routing_source: Mapped[str] = mapped_column(String(120), default="routing_decision")
    availability_at_composition: Mapped[str] = mapped_column(String(40), default="unavailable", index=True)
    fallback_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str] = mapped_column(Text, default="")
    independence_required: Mapped[bool] = mapped_column(Boolean, default=False)
    independence_status: Mapped[str] = mapped_column(String(40), default="not_required")
    independent_from_roles: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    task: Mapped[Task] = relationship()
    team_plan: Mapped[Optional[AITeamPlan]] = relationship()
    assigned_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[assigned_model_id])
    fallback_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[fallback_model_id])


class AIModelInvocationEvidence(Base):
    __tablename__ = "ai_model_invocation_evidence"
    __table_args__ = (
        CheckConstraint(
            "invocation_mode IN ('real','simulated','manual','unavailable')",
            name="ck_ai_model_evidence_invocation_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invocation_ref: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    capability: Mapped[str] = mapped_column(String(80), index=True)
    assignment_version: Mapped[int] = mapped_column(Integer)
    configured_model_id: Mapped[int] = mapped_column(ForeignKey("ai_models.id"), index=True)
    configured_provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    codex_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("codex_runs.id"), nullable=True, index=True)
    actual_invoked_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    invocation_mode: Mapped[str] = mapped_column(String(40), index=True)
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    process_evidence: Mapped[str] = mapped_column(Text, default="{}")
    provider_evidence: Mapped[str] = mapped_column(Text, default="{}")
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_metadata: Mapped[str] = mapped_column(Text, default="{}")
    error_category: Mapped[str] = mapped_column(String(80), default="")
    request_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    response_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    diagnostic_code: Mapped[str] = mapped_column(String(80), default="")
    safe_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    configured_model: Mapped[AIModel] = relationship()
    configured_provider: Mapped[Provider] = relationship()
    assignment: Mapped[Optional[AIModelAssignment]] = relationship()
    task: Mapped[Optional[Task]] = relationship()
    codex_run: Mapped[Optional["CodexRun"]] = relationship()


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
    development_task: Mapped[str] = mapped_column(Text, default="")
    development_task_digest: Mapped[str] = mapped_column(String(64), default="")
    assignment_version: Mapped[int] = mapped_column(Integer, default=0)
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    routing_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    source_snapshot_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
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
    development_task: Mapped[str] = mapped_column(Text, default="")
    development_task_digest: Mapped[str] = mapped_column(String(64), default="")
    assignment_version: Mapped[int] = mapped_column(Integer, default=0)
    task_version: Mapped[int] = mapped_column(Integer, default=1)
    routing_snapshot_hash: Mapped[str] = mapped_column(String(64), default="")
    source_snapshot_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    approved_instruction_digest: Mapped[str] = mapped_column(String(64), default="")
    start_idempotency_digest: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    start_request_digest: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    owner_start_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    execution_model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_models.id"), nullable=True, index=True
    )
    execution_provider_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("providers.id"), nullable=True, index=True
    )
    execution_connectivity_evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_connectivity_evidence.id"), nullable=True, index=True
    )
    requested_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    fallback_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    verification_model_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_models.id"), nullable=True, index=True
    )
    verification_provider_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("providers.id"), nullable=True, index=True
    )
    verification_connectivity_evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_connectivity_evidence.id"), nullable=True, index=True
    )
    verification_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    verification_status: Mapped[str] = mapped_column(String(40), default="not_started", index=True)
    verification_summary: Mapped[str] = mapped_column(Text, default="")
    verification_process_spawned: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_stdout: Mapped[str] = mapped_column(Text, default="")
    verification_stderr: Mapped[str] = mapped_column(Text, default="")
    verification_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    verification_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    verification_timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    launch_intent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    process_spawned: Mapped[bool] = mapped_column(Boolean, default=False)
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
    execution_assignment: Mapped[Optional[AIModelAssignment]] = relationship(
        foreign_keys=[execution_assignment_id]
    )
    execution_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[execution_model_id])
    execution_provider: Mapped[Optional[Provider]] = relationship(foreign_keys=[execution_provider_id])
    execution_connectivity_evidence: Mapped[Optional[CodexConnectivityEvidence]] = relationship(
        foreign_keys=[execution_connectivity_evidence_id]
    )
    verification_assignment: Mapped[Optional[AIModelAssignment]] = relationship(
        foreign_keys=[verification_assignment_id]
    )
    verification_model: Mapped[Optional[AIModel]] = relationship(foreign_keys=[verification_model_id])
    verification_provider: Mapped[Optional[Provider]] = relationship(
        foreign_keys=[verification_provider_id]
    )
    verification_connectivity_evidence: Mapped[Optional[CodexConnectivityEvidence]] = relationship(
        foreign_keys=[verification_connectivity_evidence_id]
    )
    acceptance_session: Mapped[Optional["OwnerAcceptanceSession"]] = relationship(back_populates="codex_run")


class OwnerAcceptanceSession(Base):
    __tablename__ = "owner_acceptance_sessions"
    __table_args__ = (
        CheckConstraint(
            "candidate_version IS NULL OR candidate_version >= 1",
            name="ck_owner_acceptance_candidate_version_positive",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_owner_acceptance_decision_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    codex_run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), unique=True, index=True)
    owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    result_envelope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), nullable=True, unique=True, index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), default="")
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    result_task_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_pack_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), nullable=True, index=True
    )
    result_pack_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_instruction_digest: Mapped[str] = mapped_column(String(64), default="")
    delivery_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_candidates.id"), nullable=True, unique=True, index=True
    )
    candidate_public_id: Mapped[str] = mapped_column(String(80), default="")
    candidate_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidate_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    review_policy_version: Mapped[str] = mapped_column(
        String(80), default="twos.result_delivery_review.v1", index=True
    )
    decision_version: Mapped[int] = mapped_column(Integer, default=1)
    decision_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="owner_review", index=True)
    owner_note: Mapped[str] = mapped_column(Text, default="")
    compact_sync_result: Mapped[str] = mapped_column(Text, default="")
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="owner_acceptance_sessions")
    codex_run: Mapped[CodexRun] = relationship(back_populates="acceptance_session")
    owner: Mapped[Optional[User]] = relationship(foreign_keys=[owner_id])
    result_envelope: Mapped[Optional["CodexResultEnvelope"]] = relationship(
        foreign_keys=[result_envelope_id]
    )
    result_pack: Mapped[Optional[CodexInstructionPack]] = relationship(
        foreign_keys=[result_pack_id]
    )
    delivery_candidate: Mapped[Optional["DeliveryCandidate"]] = relationship(
        foreign_keys=[delivery_candidate_id]
    )
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


class DeliveryCandidate(Base):
    __tablename__ = "delivery_candidates"
    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_delivery_candidate_owner_run"),
        UniqueConstraint(
            "owner_id",
            "result_envelope_id",
            "candidate_version",
            name="uq_delivery_candidate_owner_result_version",
        ),
        CheckConstraint(
            "candidate_version >= 1",
            name="ck_delivery_candidate_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_id: Mapped[int] = mapped_column(ForeignKey("codex_instruction_packs.id"), index=True)
    pack_version: Mapped[int] = mapped_column(Integer)
    candidate_version: Mapped[int] = mapped_column(Integer, default=1)
    derivation_version: Mapped[str] = mapped_column(
        String(80), default="twos.delivery_candidate.v1", index=True
    )
    coding_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True
    )
    coding_assignment_version: Mapped[int] = mapped_column(Integer, default=0)
    verification_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True
    )
    verification_assignment_version: Mapped[int] = mapped_column(Integer, default=0)
    routing_snapshot_identity: Mapped[str] = mapped_column(String(64))
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    source_baseline_commit: Mapped[str] = mapped_column(String(80))
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), unique=True, index=True)
    result_envelope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), nullable=True, unique=True, index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), default="")
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    approved_instruction_digest: Mapped[str] = mapped_column(String(64), default="")
    coding_attempt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_execution_attempts.id"), nullable=True, index=True
    )
    coding_attempt_identity: Mapped[str] = mapped_column(String(96), default="")
    coding_outcome: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    coding_evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_invocation_evidence.id"), nullable=True
    )
    coding_evidence_identity: Mapped[str] = mapped_column(String(160), default="")
    coding_evidence_digest: Mapped[str] = mapped_column(String(64), default="")
    verification_policy: Mapped[str] = mapped_column(
        String(40), default="required", index=True
    )
    verification_attempt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_execution_attempts.id"), nullable=True, index=True
    )
    verification_attempt_identity: Mapped[str] = mapped_column(String(96), default="")
    verification_receipt_identity: Mapped[str] = mapped_column(String(64), default="")
    verification_evidence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_invocation_evidence.id"), nullable=True
    )
    verification_evidence_identity: Mapped[str] = mapped_column(String(160), default="")
    verification_evidence_digest: Mapped[str] = mapped_column(String(64), default="")
    verification_verdict: Mapped[str] = mapped_column(String(40), default="unavailable")
    result_integrity_state: Mapped[str] = mapped_column(
        String(24), default="unverified", index=True
    )
    source_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_baseline_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_post_state_identity: Mapped[str] = mapped_column(String(64), default="")
    acceptance_id: Mapped[int] = mapped_column(ForeignKey("owner_acceptance_sessions.id"))
    acceptance_status: Mapped[str] = mapped_column(String(40))
    file_manifest_json: Mapped[str] = mapped_column(Text)
    excluded_manifest_json: Mapped[str] = mapped_column(Text, default="[]")
    attribution_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    readiness_state: Mapped[str] = mapped_column(String(48), default="blocked", index=True)
    readiness_reason: Mapped[str] = mapped_column(Text, default="")
    readiness_blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    patch_identity: Mapped[str] = mapped_column(String(64))
    candidate_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    result_envelope: Mapped[Optional["CodexResultEnvelope"]] = relationship(
        foreign_keys=[result_envelope_id]
    )
    coding_attempt: Mapped[Optional["CodexExecutionAttempt"]] = relationship(
        foreign_keys=[coding_attempt_id]
    )
    verification_attempt: Mapped[Optional["CodexExecutionAttempt"]] = relationship(
        foreign_keys=[verification_attempt_id]
    )
    acceptance: Mapped[OwnerAcceptanceSession] = relationship(
        foreign_keys=[acceptance_id]
    )


class SourceDriftEvaluation(Base):
    __tablename__ = "source_drift_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_candidates.id"), nullable=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    status: Mapped[str] = mapped_column(String(48), index=True)
    blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    next_action: Mapped[str] = mapped_column(Text)
    baseline_source_digest: Mapped[str] = mapped_column(String(64), default="")
    current_source_digest: Mapped[str] = mapped_column(String(64), default="")
    current_head: Mapped[str] = mapped_column(String(80), default="")
    conflict_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ApplyPlan(Base):
    __tablename__ = "apply_plans"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "run_id",
            "plan_version",
            name="uq_apply_plan_owner_run_version",
        ),
        UniqueConstraint("supersedes_plan_id", name="uq_apply_plan_successor"),
        CheckConstraint("plan_version >= 1", name="ck_apply_plan_version_positive"),
        CheckConstraint(
            "candidate_entry_count >= 0 AND classified_entry_count >= 0",
            name="ck_apply_plan_entry_counts_nonnegative",
        ),
        CheckConstraint(
            "candidate_entry_count = classified_entry_count",
            name="ck_apply_plan_all_entries_classified",
        ),
        CheckConstraint(
            "candidate_version >= 1",
            name="ck_apply_plan_candidate_version_positive",
        ),
        CheckConstraint(
            "staged_path_count >= 0",
            name="ck_apply_plan_staged_path_count_nonnegative",
        ),
        CheckConstraint(
            "status_at_creation IN ("
            "'ready_for_owner_review',"
            "'review_with_source_changes',"
            "'blocked_by_conflict',"
            "'blocked_by_candidate',"
            "'blocked_by_repository'"
            ")",
            name="ck_apply_plan_creation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    delivery_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_candidates.id"), nullable=True, index=True
    )
    candidate_public_id: Mapped[str] = mapped_column(String(80), default="")
    candidate_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    candidate_version: Mapped[int] = mapped_column(Integer, default=1)
    result_envelope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), nullable=True, index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), default="")
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_acceptance_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("owner_acceptance_sessions.id"), nullable=True, index=True
    )
    result_review_decision_digest: Mapped[str] = mapped_column(
        String(64), default="", index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    pack_version: Mapped[int] = mapped_column(Integer)
    approved_instruction_digest: Mapped[str] = mapped_column(String(64), default="")
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), default="")
    source_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_baseline_identity: Mapped[str] = mapped_column(
        String(64), default=""
    )
    run_workspace_post_state_identity: Mapped[str] = mapped_column(
        String(64), default=""
    )
    verification_policy: Mapped[str] = mapped_column(
        String(40), default="required", index=True
    )
    verification_verdict: Mapped[str] = mapped_column(String(40), default="unavailable")
    verification_receipt_identity: Mapped[str] = mapped_column(String(64), default="")
    source_drift_evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("source_drift_evaluations.id"), index=True
    )
    source_drift_state: Mapped[str] = mapped_column(String(48))
    drift_semantic_fingerprint: Mapped[str] = mapped_column(String(64))
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240), default="")
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    repository_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    branch: Mapped[str] = mapped_column(String(240), default="")
    observed_head: Mapped[str] = mapped_column(String(80), default="")
    current_source_digest: Mapped[str] = mapped_column(String(64), default="")
    index_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    worktree_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    staged_path_count: Mapped[int] = mapped_column(Integer, default=0)
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    plan_version: Mapped[int] = mapped_column(Integer)
    status_at_creation: Mapped[str] = mapped_column(String(48), index=True)
    candidate_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    classified_entry_count: Mapped[int] = mapped_column(Integer, default=0)
    operation_order_json: Mapped[str] = mapped_column(Text, default="[]")
    scope_findings_json: Mapped[str] = mapped_column(Text, default="[]")
    included_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    excluded_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    unexpected_findings_json: Mapped[str] = mapped_column(Text, default="[]")
    conflict_findings_json: Mapped[str] = mapped_column(Text, default="[]")
    global_preconditions_json: Mapped[str] = mapped_column(Text, default="[]")
    reversibility_requirements_json: Mapped[str] = mapped_column(Text, default="{}")
    pre_apply_checks_json: Mapped[str] = mapped_column(Text, default="[]")
    post_apply_checks_json: Mapped[str] = mapped_column(Text, default="[]")
    explicit_boundaries_json: Mapped[str] = mapped_column(Text, default="[]")
    blocker_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    binding_digest: Mapped[str] = mapped_column(String(64), index=True)
    plan_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supersedes_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("apply_plans.id"), nullable=True, index=True
    )
    supersession_reason: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    entries: Mapped[list["ApplyPlanEntry"]] = relationship(
        back_populates="apply_plan",
        order_by="ApplyPlanEntry.manifest_ordinal",
    )
    approval: Mapped[Optional["ApplyPlanApproval"]] = relationship(
        back_populates="apply_plan",
        uselist=False,
    )
    result_envelope: Mapped[Optional["CodexResultEnvelope"]] = relationship(
        foreign_keys=[result_envelope_id]
    )
    owner_acceptance: Mapped[Optional[OwnerAcceptanceSession]] = relationship(
        foreign_keys=[owner_acceptance_id]
    )


class ApplyPlanEntry(Base):
    __tablename__ = "apply_plan_entries"
    __table_args__ = (
        UniqueConstraint(
            "apply_plan_id",
            "manifest_ordinal",
            name="uq_apply_plan_entry_manifest_ordinal",
        ),
        UniqueConstraint(
            "apply_plan_id",
            "operation_ordinal",
            name="uq_apply_plan_entry_operation_ordinal",
        ),
        CheckConstraint(
            "manifest_ordinal >= 1",
            name="ck_apply_plan_entry_manifest_ordinal_positive",
        ),
        CheckConstraint(
            "operation_ordinal IS NULL OR operation_ordinal >= 1",
            name="ck_apply_plan_entry_operation_ordinal_positive",
        ),
        CheckConstraint(
            "(disposition = 'INCLUDED' AND operation_ordinal IS NOT NULL) OR "
            "(disposition IN ('EXCLUDED','BLOCKED') AND operation_ordinal IS NULL)",
            name="ck_apply_plan_entry_disposition_ordinal",
        ),
        CheckConstraint(
            "operation IN ('CREATE','MODIFY','DELETE','UNKNOWN')",
            name="ck_apply_plan_entry_operation",
        ),
        CheckConstraint(
            "disposition IN ('INCLUDED','EXCLUDED','BLOCKED')",
            name="ck_apply_plan_entry_disposition",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    apply_plan_id: Mapped[int] = mapped_column(
        ForeignKey("apply_plans.id"), index=True
    )
    manifest_ordinal: Mapped[int] = mapped_column(Integer)
    operation_ordinal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repository_path: Mapped[str] = mapped_column(Text, default="")
    display_path: Mapped[str] = mapped_column(Text)
    path_identity: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(16))
    disposition: Mapped[str] = mapped_column(String(16), index=True)
    reason_code: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    unexpected: Mapped[bool] = mapped_column(Boolean, default=False)
    content_kind: Mapped[str] = mapped_column(String(40), default="unknown")
    before_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    evidence_identity: Mapped[str] = mapped_column(String(64), default="")
    conflicts_json: Mapped[str] = mapped_column(Text, default="[]")
    preconditions_json: Mapped[str] = mapped_column(Text, default="[]")
    reversibility_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="[]")

    apply_plan: Mapped[ApplyPlan] = relationship(back_populates="entries")


class ApplyPlanApproval(Base):
    """Immutable Owner approval for one exact Apply Plan and delivery lineage."""

    __tablename__ = "apply_plan_approvals"
    __table_args__ = (
        UniqueConstraint("apply_plan_id", name="uq_apply_plan_approval_plan"),
        CheckConstraint(
            "candidate_version >= 1",
            name="ck_apply_plan_approval_candidate_version_positive",
        ),
        CheckConstraint(
            "approval_state = 'APPROVED'",
            name="ck_apply_plan_approval_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apply_plan_id: Mapped[int] = mapped_column(ForeignKey("apply_plans.id"), index=True)
    plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    candidate_public_id: Mapped[str] = mapped_column(String(80), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer, default=1)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    result_envelope_id: Mapped[int] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), index=True)
    result_digest: Mapped[str] = mapped_column(String(64), index=True)
    owner_acceptance_id: Mapped[int] = mapped_column(
        ForeignKey("owner_acceptance_sessions.id"), index=True
    )
    result_review_decision_digest: Mapped[str] = mapped_column(String(64), index=True)
    source_workspace_identity: Mapped[str] = mapped_column(String(64))
    run_workspace_identity: Mapped[str] = mapped_column(String(64))
    run_workspace_baseline_identity: Mapped[str] = mapped_column(String(64))
    run_workspace_post_state_identity: Mapped[str] = mapped_column(String(64))
    approval_state: Mapped[str] = mapped_column(String(24), default="APPROVED", index=True)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approval_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    apply_plan: Mapped[ApplyPlan] = relationship(back_populates="approval")
    delivery_candidate: Mapped[DeliveryCandidate] = relationship(
        foreign_keys=[delivery_candidate_id]
    )
    result_envelope: Mapped["CodexResultEnvelope"] = relationship(
        foreign_keys=[result_envelope_id]
    )
    owner_acceptance: Mapped[OwnerAcceptanceSession] = relationship(
        foreign_keys=[owner_acceptance_id]
    )
    approved_by: Mapped[User] = relationship(foreign_keys=[approved_by_user_id])


class ApplySession(Base):
    __tablename__ = "apply_sessions"
    __table_args__ = (
        UniqueConstraint("apply_plan_id", name="uq_apply_session_apply_plan"),
        CheckConstraint(
            "state IN ("
            "'PREFLIGHT_BLOCKED',"
            "'APPLYING',"
            "'APPLIED',"
            "'APPLY_FAILED_RECOVERED',"
            "'APPLY_FAILED_PARTIAL',"
            "'REVERTING',"
            "'REVERTED',"
            "'REVERT_BLOCKED',"
            "'REVERT_FAILED_PARTIAL'"
            ")",
            name="ck_apply_session_state",
        ),
        CheckConstraint(
            "included_path_count >= 0 AND excluded_path_count >= 0 "
            "AND blocked_path_count >= 0",
            name="ck_apply_session_path_counts_nonnegative",
        ),
        CheckConstraint(
            "candidate_version >= 1",
            name="ck_apply_session_candidate_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apply_plan_id: Mapped[int] = mapped_column(ForeignKey("apply_plans.id"), index=True)
    apply_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    apply_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    candidate_public_id: Mapped[str] = mapped_column(String(80), index=True)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer, default=1)
    result_envelope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), nullable=True, index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), default="")
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_acceptance_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("owner_acceptance_sessions.id"), nullable=True, index=True
    )
    result_review_decision_digest: Mapped[str] = mapped_column(
        String(64), default="", index=True
    )
    apply_plan_approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("apply_plan_approvals.id"), nullable=True, unique=True, index=True
    )
    apply_plan_approval_public_id: Mapped[str] = mapped_column(String(80), default="")
    apply_plan_approval_digest: Mapped[str] = mapped_column(
        String(64), default="", index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    pack_version: Mapped[int] = mapped_column(Integer)
    source_snapshot_identity: Mapped[str] = mapped_column(String(64))
    source_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    run_workspace_baseline_identity: Mapped[str] = mapped_column(
        String(64), default=""
    )
    run_workspace_post_state_identity: Mapped[str] = mapped_column(
        String(64), default=""
    )
    source_drift_evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("source_drift_evaluations.id"), index=True
    )
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64))
    repository_fingerprint: Mapped[str] = mapped_column(String(64))
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str] = mapped_column(String(240))
    pre_apply_head: Mapped[str] = mapped_column(String(80))
    pre_apply_index_fingerprint: Mapped[str] = mapped_column(String(64))
    pre_apply_worktree_fingerprint: Mapped[str] = mapped_column(String(64))
    included_path_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_path_count: Mapped[int] = mapped_column(Integer, default=0)
    blocked_path_count: Mapped[int] = mapped_column(Integer, default=0)
    included_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    excluded_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    ordered_operations_json: Mapped[str] = mapped_column(Text, default="[]")
    apply_confirmation_digest: Mapped[str] = mapped_column(String(64))
    journal_digest: Mapped[str] = mapped_column(String(64), index=True)
    revert_confirmation_digest: Mapped[str] = mapped_column(String(64), default="")
    before_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    after_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    pre_revert_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    post_revert_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(40), index=True)
    integrity_check_result: Mapped[str] = mapped_column(
        String(40), default="NOT_RUN"
    )
    failure_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    compensation_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revert_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revert_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    entries: Mapped[list["ApplySessionEntry"]] = relationship(
        back_populates="apply_session",
        order_by="ApplySessionEntry.operation_ordinal",
    )
    result_envelope: Mapped[Optional["CodexResultEnvelope"]] = relationship(
        foreign_keys=[result_envelope_id]
    )
    owner_acceptance: Mapped[Optional[OwnerAcceptanceSession]] = relationship(
        foreign_keys=[owner_acceptance_id]
    )
    apply_plan_approval: Mapped[Optional[ApplyPlanApproval]] = relationship(
        foreign_keys=[apply_plan_approval_id]
    )


class ApplySessionEntry(Base):
    __tablename__ = "apply_session_entries"
    __table_args__ = (
        UniqueConstraint(
            "apply_session_id",
            "repository_path",
            name="uq_apply_session_entry_path",
        ),
        UniqueConstraint(
            "apply_session_id",
            "operation_ordinal",
            name="uq_apply_session_entry_operation_ordinal",
        ),
        CheckConstraint(
            "operation IN ('CREATE','MODIFY','DELETE')",
            name="ck_apply_session_entry_operation",
        ),
        CheckConstraint(
            "reverse_operation IN ('DELETE_EXACT','RESTORE_EXACT','RECREATE_EXACT')",
            name="ck_apply_session_entry_reverse_operation",
        ),
        CheckConstraint(
            "operation_ordinal >= 1",
            name="ck_apply_session_entry_operation_ordinal_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    apply_session_id: Mapped[int] = mapped_column(
        ForeignKey("apply_sessions.id"), index=True
    )
    apply_plan_entry_id: Mapped[int] = mapped_column(
        ForeignKey("apply_plan_entries.id"), index=True
    )
    operation_ordinal: Mapped[int] = mapped_column(Integer)
    repository_path: Mapped[str] = mapped_column(Text)
    path_identity: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(16))
    reverse_operation: Mapped[str] = mapped_column(String(24))
    before_present: Mapped[bool] = mapped_column(Boolean)
    before_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_file_type: Mapped[str] = mapped_column(String(40))
    before_atime_ns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_mtime_ns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_material: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    after_present: Mapped[bool] = mapped_column(Boolean)
    after_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    after_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_file_type: Mapped[str] = mapped_column(String(40))
    after_atime_ns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_mtime_ns: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_material: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    temporary_material_identity: Mapped[str] = mapped_column(String(64))
    parent_chain_json: Mapped[str] = mapped_column(Text, default="[]")
    created_parent_dirs_json: Mapped[str] = mapped_column(Text, default="[]")
    apply_result: Mapped[str] = mapped_column(String(40), default="PENDING")
    revert_result: Mapped[str] = mapped_column(String(40), default="NOT_STARTED")
    failure_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reverted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    apply_session: Mapped[ApplySession] = relationship(back_populates="entries")


class ApplySessionAudit(Base):
    __tablename__ = "apply_session_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    apply_session_id: Mapped[int] = mapped_column(
        ForeignKey("apply_sessions.id"), index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    phase: Mapped[str] = mapped_column(String(24), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("apply_session_entries.id"), nullable=True, index=True
    )
    path_identity: Mapped[str] = mapped_column(String(64), default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PostApplyVerification(Base):
    __tablename__ = "post_apply_verifications"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "apply_session_id",
            "observation_digest",
            name="uq_post_apply_verification_owner_session_observation",
        ),
        CheckConstraint(
            "status IN ('READY','VERIFYING','PASSED','BLOCKED','FAILED')",
            name="ck_post_apply_verification_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    apply_session_id: Mapped[int] = mapped_column(
        ForeignKey("apply_sessions.id"), index=True
    )
    apply_plan_id: Mapped[int] = mapped_column(
        ForeignKey("apply_plans.id"), index=True
    )
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    apply_session_public_id: Mapped[str] = mapped_column(String(80), index=True)
    apply_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    candidate_public_id: Mapped[str] = mapped_column(String(80), index=True)
    journal_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64))
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    expected_repository_fingerprint: Mapped[str] = mapped_column(String(64))
    observed_repository_fingerprint: Mapped[str] = mapped_column(String(64))
    expected_branch: Mapped[str] = mapped_column(String(240))
    observed_branch: Mapped[str] = mapped_column(String(240))
    expected_head: Mapped[str] = mapped_column(String(80))
    observed_head: Mapped[str] = mapped_column(String(80))
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    expected_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    observed_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    preserved_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    unexpected_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    test_results_json: Mapped[str] = mapped_column(Text, default="[]")
    blocker_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    boundary_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    diagnostics_json: Mapped[str] = mapped_column(Text, default="{}")
    observation_digest: Mapped[str] = mapped_column(String(64), index=True)
    verification_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="READY", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommitProposal(Base):
    """Immutable, Owner-scoped version of an exact local Commit proposal."""

    __tablename__ = "commit_proposals"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "post_apply_verification_id",
            "version",
            name="uq_commit_proposal_owner_verification_version",
        ),
        CheckConstraint("version >= 1", name="ck_commit_proposal_version"),
        CheckConstraint(
            "status_at_creation IN ('READY','BLOCKED','EXPIRED')",
            name="ck_commit_proposal_creation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    post_apply_verification_id: Mapped[int] = mapped_column(
        ForeignKey("post_apply_verifications.id"), index=True
    )
    apply_session_id: Mapped[int] = mapped_column(ForeignKey("apply_sessions.id"), index=True)
    apply_plan_id: Mapped[int] = mapped_column(ForeignKey("apply_plans.id"), index=True)
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    result_envelope_id: Mapped[int] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), index=True
    )
    owner_acceptance_id: Mapped[int] = mapped_column(
        ForeignKey("owner_acceptance_sessions.id"), index=True
    )
    apply_plan_approval_id: Mapped[int] = mapped_column(
        ForeignKey("apply_plan_approvals.id"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    supersedes_proposal_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("commit_proposals.id"), nullable=True, index=True
    )
    verification_public_id: Mapped[str] = mapped_column(String(80), index=True)
    verification_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_session_public_id: Mapped[str] = mapped_column(String(80), index=True)
    journal_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    apply_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_plan_approval_public_id: Mapped[str] = mapped_column(String(80), index=True)
    apply_plan_approval_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_public_id: Mapped[str] = mapped_column(String(80), index=True)
    candidate_version: Mapped[int] = mapped_column(Integer)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), index=True)
    result_digest: Mapped[str] = mapped_column(String(64), index=True)
    result_review_decision_digest: Mapped[str] = mapped_column(String(64), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_version: Mapped[int] = mapped_column(Integer)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    repository_fingerprint: Mapped[str] = mapped_column(String(64))
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str] = mapped_column(String(240))
    branch_ref: Mapped[str] = mapped_column(String(320))
    base_head: Mapped[str] = mapped_column(String(80), index=True)
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    source_workspace_identity: Mapped[str] = mapped_column(String(64), index=True)
    run_workspace_identity: Mapped[str] = mapped_column(String(64), index=True)
    planned_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    planned_paths_digest: Mapped[str] = mapped_column(String(64), index=True)
    excluded_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    subject_digest: Mapped[str] = mapped_column(String(64))
    body_digest: Mapped[str] = mapped_column(String(64))
    message_digest: Mapped[str] = mapped_column(String(64), index=True)
    author_identity_sanitized: Mapped[str] = mapped_column(String(240))
    author_identity_digest: Mapped[str] = mapped_column(String(64), index=True)
    validation_json: Mapped[str] = mapped_column(Text, default="[]")
    blocker_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    boundary_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    status_at_creation: Mapped[str] = mapped_column(String(24), index=True)
    binding_digest: Mapped[str] = mapped_column(String(64), index=True)
    proposal_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommitProposalApproval(Base):
    """Immutable approval of one exact CommitProposal version and digest."""

    __tablename__ = "commit_proposal_approvals"
    __table_args__ = (
        UniqueConstraint("commit_proposal_id", name="uq_commit_proposal_approval"),
        CheckConstraint("state = 'APPROVED'", name="ck_commit_proposal_approval_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    commit_proposal_id: Mapped[int] = mapped_column(
        ForeignKey("commit_proposals.id"), unique=True, index=True
    )
    proposal_public_id: Mapped[str] = mapped_column(String(80), index=True)
    proposal_version: Mapped[int] = mapped_column(Integer)
    proposal_digest: Mapped[str] = mapped_column(String(64), index=True)
    message_digest: Mapped[str] = mapped_column(String(64), index=True)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confirmation_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    approval_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(24), default="APPROVED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CommitPlan(Base):
    __tablename__ = "commit_plans"
    __table_args__ = (
        UniqueConstraint(
            "post_apply_verification_id",
            name="uq_commit_plan_post_apply_verification",
        ),
        CheckConstraint(
            "status_at_creation IN ('DRAFT','READY','EXPIRED','BLOCKED','COMMITTED')",
            name="ck_commit_plan_creation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    commit_plan_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    post_apply_verification_id: Mapped[int] = mapped_column(
        ForeignKey("post_apply_verifications.id"), index=True
    )
    apply_session_id: Mapped[int] = mapped_column(
        ForeignKey("apply_sessions.id"), index=True
    )
    apply_plan_id: Mapped[int] = mapped_column(
        ForeignKey("apply_plans.id"), index=True
    )
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    verification_public_id: Mapped[str] = mapped_column(String(80), index=True)
    verification_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_session_public_id: Mapped[str] = mapped_column(String(80), index=True)
    journal_digest: Mapped[str] = mapped_column(String(64), index=True)
    apply_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    apply_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_public_id: Mapped[str] = mapped_column(String(80), index=True)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    repository_fingerprint: Mapped[str] = mapped_column(String(64))
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str] = mapped_column(String(240))
    branch_ref: Mapped[str] = mapped_column(String(320))
    base_head: Mapped[str] = mapped_column(String(80), index=True)
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    verified_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    excluded_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    validation_json: Mapped[str] = mapped_column(Text, default="[]")
    blocker_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    boundary_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    status_at_creation: Mapped[str] = mapped_column(String(24), index=True)
    binding_digest: Mapped[str] = mapped_column(String(64), index=True)
    plan_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StageExecution(Base):
    __tablename__ = "stage_executions"
    __table_args__ = (
        UniqueConstraint("commit_plan_id", name="uq_stage_execution_commit_plan"),
        CheckConstraint(
            "state IN ('STAGING','STAGED','BLOCKED','FAILED','INTEGRITY_BLOCKED')",
            name="ck_stage_execution_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_execution_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    commit_plan_id: Mapped[int] = mapped_column(
        ForeignKey("commit_plans.id"), unique=True, index=True
    )
    commit_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    commit_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    verification_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    branch: Mapped[str] = mapped_column(String(240))
    branch_ref: Mapped[str] = mapped_column(String(320))
    base_head: Mapped[str] = mapped_column(String(80), index=True)
    planned_entries_json: Mapped[str] = mapped_column(Text)
    planned_entries_digest: Mapped[str] = mapped_column(String(64), index=True)
    pre_stage_evidence_json: Mapped[str] = mapped_column(Text)
    pre_stage_evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    post_stage_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    staged_entries_json: Mapped[str] = mapped_column(Text, default="[]")
    staged_entries_digest: Mapped[str] = mapped_column(String(64), default="")
    stage_digest: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(32), index=True)
    failure_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class LocalCommitExecution(Base):
    __tablename__ = "local_commit_executions"
    __table_args__ = (
        UniqueConstraint("stage_execution_id", name="uq_local_commit_stage_execution"),
        Index(
            "ux_local_commit_owner_confirmation",
            "owner_commit_confirmation_digest",
            unique=True,
            sqlite_where=text("owner_commit_confirmation_digest != ''"),
            postgresql_where=text("owner_commit_confirmation_digest != ''"),
        ),
        CheckConstraint(
            "state IN ('COMMITTING','COMMITTED','BLOCKED','FAILED','INTEGRITY_BLOCKED')",
            name="ck_local_commit_execution_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    commit_execution_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    commit_proposal_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("commit_proposals.id"), nullable=True, index=True
    )
    commit_proposal_approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("commit_proposal_approvals.id"), nullable=True, unique=True, index=True
    )
    commit_plan_id: Mapped[int] = mapped_column(
        ForeignKey("commit_plans.id"), index=True
    )
    stage_execution_id: Mapped[int] = mapped_column(
        ForeignKey("stage_executions.id"), unique=True, index=True
    )
    commit_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    commit_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    stage_execution_public_id: Mapped[str] = mapped_column(String(80), index=True)
    stage_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    branch: Mapped[str] = mapped_column(String(240))
    branch_ref: Mapped[str] = mapped_column(String(320))
    base_head: Mapped[str] = mapped_column(String(80), index=True)
    staged_entries_json: Mapped[str] = mapped_column(Text)
    staged_entries_digest: Mapped[str] = mapped_column(String(64), index=True)
    subject_digest: Mapped[str] = mapped_column(String(64))
    body_digest: Mapped[str] = mapped_column(String(64))
    message_digest: Mapped[str] = mapped_column(String(64), index=True)
    intent_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pre_commit_evidence_json: Mapped[str] = mapped_column(Text)
    pre_commit_evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    proposal_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    proposal_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    proposal_approval_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    proposal_approval_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_commit_confirmation_digest: Mapped[str] = mapped_column(
        String(64), default="", index=True
    )
    owner_commit_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_envelope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), nullable=True, index=True
    )
    result_envelope_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_acceptance_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("owner_acceptance_sessions.id"), nullable=True, index=True
    )
    result_review_decision_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    candidate_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    apply_plan_approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("apply_plan_approvals.id"), nullable=True, index=True
    )
    apply_plan_approval_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    apply_plan_approval_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_workspace_identity: Mapped[str] = mapped_column(String(64), default="", index=True)
    run_workspace_identity: Mapped[str] = mapped_column(String(64), default="", index=True)
    author_identity_sanitized: Mapped[str] = mapped_column(String(240), default="")
    author_identity_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    command_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    command_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    command_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    command_output_json: Mapped[str] = mapped_column(Text, default="{}")
    command_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    command_evidence_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    hooks_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    hooks_evidence_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    tree_oid: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    commit_oid: Mapped[Optional[str]] = mapped_column(
        String(80), unique=True, nullable=True, index=True
    )
    parent_oid: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    post_commit_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    receipt_digest: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(32), index=True)
    failure_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PushPlan(Base):
    """Immutable, versioned approval surface for one exact non-force Push."""

    __tablename__ = "push_plans"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "local_commit_execution_id", "version",
            name="uq_push_plan_owner_commit_version",
        ),
        CheckConstraint("version >= 1", name="ck_push_plan_version"),
        CheckConstraint(
            "status_at_creation IN ('READY','BLOCKED','EXPIRED','ALREADY_DELIVERED')",
            name="ck_push_plan_creation_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    push_plan_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    local_commit_execution_id: Mapped[int] = mapped_column(
        ForeignKey("local_commit_executions.id"), index=True
    )
    commit_proposal_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("commit_proposals.id"), nullable=True, index=True
    )
    commit_proposal_approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("commit_proposal_approvals.id"), nullable=True, index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    supersedes_push_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("push_plans.id"), nullable=True, index=True
    )
    local_commit_public_id: Mapped[str] = mapped_column(String(80), index=True)
    local_commit_receipt_digest: Mapped[str] = mapped_column(String(64), index=True)
    commit_proposal_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    commit_proposal_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    commit_proposal_approval_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    commit_proposal_approval_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str] = mapped_column(String(240), default="main")
    branch_ref: Mapped[str] = mapped_column(String(320), default="refs/heads/main")
    remote_name: Mapped[str] = mapped_column(String(80), default="origin")
    destination_ref: Mapped[str] = mapped_column(String(320), default="refs/heads/main")
    approved_commit_oid: Mapped[str] = mapped_column(String(80), index=True)
    expected_parent_oid: Mapped[str] = mapped_column(String(80), index=True)
    observed_remote_base_oid: Mapped[str] = mapped_column(String(80), default="")
    expected_remote_oid: Mapped[str] = mapped_column(String(80), default="")
    remote_exists: Mapped[bool] = mapped_column(Boolean, default=False)
    subject: Mapped[str] = mapped_column(Text)
    subject_digest: Mapped[str] = mapped_column(String(64))
    remote_fetch_url_digest: Mapped[str] = mapped_column(String(64))
    remote_push_url_digest: Mapped[str] = mapped_column(String(64))
    remote_config_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    refspec: Mapped[str] = mapped_column(Text)
    preflight_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    preflight_evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    blocker_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    binding_digest: Mapped[str] = mapped_column(String(64), index=True)
    plan_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    policy_version: Mapped[str] = mapped_column(String(80), index=True)
    status_at_creation: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PushPlanApproval(Base):
    """Immutable Owner approval for one exact PushPlan version and digest."""

    __tablename__ = "push_plan_approvals"
    __table_args__ = (
        UniqueConstraint("push_plan_id", name="uq_push_plan_approval"),
        CheckConstraint("state = 'APPROVED'", name="ck_push_plan_approval_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    push_plan_id: Mapped[int] = mapped_column(ForeignKey("push_plans.id"), unique=True, index=True)
    push_plan_public_id: Mapped[str] = mapped_column(String(80), index=True)
    push_plan_version: Mapped[int] = mapped_column(Integer)
    push_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    approved_commit_oid: Mapped[str] = mapped_column(String(80), index=True)
    expected_remote_oid: Mapped[str] = mapped_column(String(80), default="")
    remote_config_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    approved_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confirmation_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    approval_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(24), default="APPROVED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PushExecution(Base):
    __tablename__ = "push_executions"
    __table_args__ = (
        CheckConstraint(
            "state IN ("
            "'READY_TO_PUSH','PUSHING','PUSHED','PUSH_BLOCKED',"
            "'REMOTE_MOVED','PUSH_FAILED','RECONCILIATION_BLOCKED'"
            ")",
            name="ck_push_execution_state",
        ),
        CheckConstraint(
            "remote_name = 'origin' AND branch = 'main' "
            "AND branch_ref = 'refs/heads/main' "
            "AND destination_ref = 'refs/heads/main'",
            name="ck_push_execution_exact_destination",
        ),
        CheckConstraint(
            "command_attempt_count IN (0,1)",
            name="ck_push_execution_single_attempt",
        ),
        Index(
            "ux_push_execution_local_commit_active",
            "local_commit_execution_id",
            unique=True,
            sqlite_where=text(
                "state IN ('READY_TO_PUSH','PUSHING','RECONCILIATION_BLOCKED')"
            ),
            postgresql_where=text(
                "state IN ('READY_TO_PUSH','PUSHING','RECONCILIATION_BLOCKED')"
            ),
        ),
        Index(
            "ux_push_execution_local_commit_success",
            "local_commit_execution_id",
            unique=True,
            sqlite_where=text("state = 'PUSHED'"),
            postgresql_where=text("state = 'PUSHED'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    push_execution_id: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    push_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("push_plans.id"), nullable=True, index=True
    )
    push_plan_approval_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("push_plan_approvals.id"), nullable=True, index=True
    )
    local_commit_execution_id: Mapped[int] = mapped_column(
        ForeignKey("local_commit_executions.id"), index=True
    )
    stage_execution_id: Mapped[int] = mapped_column(
        ForeignKey("stage_executions.id"), index=True
    )
    commit_plan_id: Mapped[int] = mapped_column(
        ForeignKey("commit_plans.id"), index=True
    )
    post_apply_verification_id: Mapped[int] = mapped_column(
        ForeignKey("post_apply_verifications.id"), index=True
    )
    apply_session_id: Mapped[int] = mapped_column(
        ForeignKey("apply_sessions.id"), index=True
    )
    delivery_candidate_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_candidates.id"), index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    push_plan_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    push_plan_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    push_plan_approval_public_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    push_plan_approval_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    local_commit_public_id: Mapped[str] = mapped_column(String(80), index=True)
    local_commit_receipt_digest: Mapped[str] = mapped_column(String(64), index=True)
    commit_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    stage_digest: Mapped[str] = mapped_column(String(64), index=True)
    verification_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_digest: Mapped[str] = mapped_column(String(64), index=True)
    journal_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository_locator_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    sanitized_repository_identity: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str] = mapped_column(String(240), default="main")
    branch_ref: Mapped[str] = mapped_column(String(320), default="refs/heads/main")
    remote_name: Mapped[str] = mapped_column(String(80), default="origin")
    destination_ref: Mapped[str] = mapped_column(
        String(320), default="refs/heads/main"
    )
    approved_commit_oid: Mapped[str] = mapped_column(String(80), index=True)
    expected_parent_oid: Mapped[str] = mapped_column(String(80), index=True)
    subject: Mapped[str] = mapped_column(Text)
    subject_digest: Mapped[str] = mapped_column(String(64))
    remote_fetch_url_digest: Mapped[str] = mapped_column(String(64))
    remote_push_url_digest: Mapped[str] = mapped_column(String(64))
    remote_config_fingerprint: Mapped[str] = mapped_column(String(64))
    observed_remote_base_oid: Mapped[str] = mapped_column(String(80), default="")
    preflight_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    preflight_evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    confirmation_digest: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    refspec: Mapped[str] = mapped_column(Text)
    command_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    command_evidence_digest: Mapped[str] = mapped_column(String(64), index=True)
    command_output_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(32), index=True)
    command_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    command_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    command_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_remote_base_oid: Mapped[Optional[str]] = mapped_column(
        String(80), nullable=True
    )
    command_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    failure_category: Mapped[str] = mapped_column(String(80), default="")
    failure_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    post_push_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    recovery_reconciliation_json: Mapped[str] = mapped_column(Text, default="{}")
    recovery_reconciliation_digest: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    recovered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    receipt_digest: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CodexRunMonitor(Base):
    __tablename__ = "codex_run_monitors"
    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_codex_run_monitor_owner_run"),
        CheckConstraint(
            "monitor_state IN ("
            "'QUEUED','STARTING','RUNNING','VERIFYING','COMPLETED','FAILED',"
            "'CANCELLED','TIMED_OUT','PROCESS_LOST','RESULT_PENDING',"
            "'RESULT_AVAILABLE','RESULT_UNAVAILABLE','RESULT_INTEGRITY_BLOCKED'"
            ")",
            name="ck_codex_run_monitor_state",
        ),
        CheckConstraint(
            "recovery_state IN ("
            "'NONE','MONITORING_RESUMED','RESULT_RECOVERED','PROCESS_LOST',"
            "'RESULT_UNAVAILABLE','INTEGRITY_BLOCKED'"
            ")",
            name="ck_codex_run_monitor_recovery_state",
        ),
        CheckConstraint(
            "heartbeat_sequence >= 0",
            name="ck_codex_run_monitor_heartbeat_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    pack_version: Mapped[int] = mapped_column(Integer)
    coding_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    coding_assignment_version: Mapped[int] = mapped_column(Integer)
    verification_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    verification_assignment_version: Mapped[int] = mapped_column(Integer)
    routing_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("codex_runs.id"), unique=True, index=True
    )
    requested_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    actual_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    verification_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    process_start_identity: Mapped[str] = mapped_column(String(64), default="")
    verification_process_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    verification_process_start_identity: Mapped[str] = mapped_column(
        String(64), default=""
    )
    codex_session_identity: Mapped[str] = mapped_column(String(64), default="")
    executable_fingerprint: Mapped[str] = mapped_column(String(64))
    isolated_worktree_identity: Mapped[str] = mapped_column(String(64))
    execution_location_identity: Mapped[str] = mapped_column(String(64))
    result_locator_identity: Mapped[str] = mapped_column(String(64), default="")
    protected_result_locator: Mapped[str] = mapped_column(Text, default="")
    monitor_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    monitor_state: Mapped[str] = mapped_column(String(40), index=True)
    result_source: Mapped[str] = mapped_column(String(80), default="persisted_run")
    recovery_state: Mapped[str] = mapped_column(String(40), default="NONE", index=True)
    process_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heartbeat_sequence: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str] = mapped_column(String(80), default="")
    safe_summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CodexExecutionAttempt(Base):
    """Durable, versioned process/stream truth for one Run phase.

    A Run may have one Coding attempt and one separately-bound Verification
    attempt.  The row is deliberately a mutable projection of immutable spool
    evidence; ``reconciliation_version`` is SQLAlchemy's optimistic-lock/CAS
    column so two reconcilers cannot silently overwrite each other.
    """

    __tablename__ = "codex_execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "run_id",
            "phase",
            "attempt_number",
            name="uq_codex_execution_attempt_run_phase_number",
        ),
        CheckConstraint(
            "phase IN ('CODING','VERIFICATION')",
            name="ck_codex_execution_attempt_phase",
        ),
        CheckConstraint(
            "attempt_state IN ("
            "'QUEUED','STARTING','RUNNING','SETTLING','COMPLETED','FAILED',"
            "'CANCELLED','TIMED_OUT','PROCESS_LOST','RESULT_UNAVAILABLE',"
            "'RESULT_INTEGRITY_BLOCKED','VERIFICATION_ELIGIBLE'"
            ")",
            name="ck_codex_execution_attempt_state",
        ),
        CheckConstraint(
            "attempt_number >= 1 AND reconciliation_version >= 1",
            name="ck_codex_execution_attempt_versions",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    pack_version: Mapped[int] = mapped_column(Integer)
    coding_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    coding_assignment_version: Mapped[int] = mapped_column(Integer)
    verification_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True, index=True
    )
    verification_assignment_version: Mapped[int] = mapped_column(Integer)
    routing_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    source_snapshot_identity: Mapped[str] = mapped_column(String(64), index=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("codex_run_monitors.id"), index=True
    )
    phase: Mapped[str] = mapped_column(String(24), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    attempt_state: Mapped[str] = mapped_column(String(40), index=True)
    reconciliation_version: Mapped[int] = mapped_column(Integer, default=1)
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    process_start_identity: Mapped[str] = mapped_column(String(64), default="")
    sidecar_process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sidecar_process_start_identity: Mapped[str] = mapped_column(String(64), default="")
    process_live: Mapped[bool] = mapped_column(Boolean, default=False)
    process_exit_known: Mapped[bool] = mapped_column(Boolean, default=False)
    process_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    process_exit_signal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ticket_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    receipt_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    observation_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    executable_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    execution_location_identity: Mapped[str] = mapped_column(String(64), default="")
    spool_locator_identity: Mapped[str] = mapped_column(String(64), default="")
    protected_spool_locator: Mapped[str] = mapped_column(Text, default="")
    thread_identity: Mapped[str] = mapped_column(String(160), default="")
    turn_identity: Mapped[str] = mapped_column(String(160), default="")
    stdout_offset: Mapped[int] = mapped_column(Integer, default=0)
    stderr_offset: Mapped[int] = mapped_column(Integer, default=0)
    stdout_spool_bytes: Mapped[int] = mapped_column(Integer, default=0)
    stderr_spool_bytes: Mapped[int] = mapped_column(Integer, default=0)
    stdout_eof: Mapped[bool] = mapped_column(Boolean, default=False)
    stderr_eof: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_partial_line_present: Mapped[bool] = mapped_column(Boolean, default=False)
    trailing_partial_line_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    terminal_event_observed: Mapped[bool] = mapped_column(Boolean, default=False)
    terminal_event_type: Mapped[str] = mapped_column(String(120), default="")
    terminal_event_identity: Mapped[str] = mapped_column(String(64), default="")
    terminal_event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    event_histogram_json: Mapped[str] = mapped_column(Text, default="{}")
    last_event_type: Mapped[str] = mapped_column(String(120), default="")
    last_event_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sidecar_state: Mapped[str] = mapped_column(String(40), default="NOT_OBSERVED")
    sidecar_digest: Mapped[str] = mapped_column(String(64), default="")
    sidecar_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    jsonl_recovery_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    result_resolution_source: Mapped[str] = mapped_column(String(80), default="")
    repository_state_identity: Mapped[str] = mapped_column(String(64), default="")
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    blocker_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    safe_summary: Mapped[str] = mapped_column(Text, default="")
    verification_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    settlement_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __mapper_args__ = {"version_id_col": reconciliation_version}


class CodexLifecycleSnapshot(Base):
    """Single Owner-facing lifecycle projection shared by every Run surface."""

    __tablename__ = "codex_lifecycle_snapshots"
    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_codex_lifecycle_owner_run"),
        CheckConstraint(
            "snapshot_version >= 1", name="ck_codex_lifecycle_snapshot_version"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    monitor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_run_monitors.id"), nullable=True, index=True
    )
    current_attempt_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("codex_execution_attempts.id"), nullable=True, index=True
    )
    coding_attempt_identity: Mapped[str] = mapped_column(String(96), default="")
    verification_attempt_identity: Mapped[str] = mapped_column(String(96), default="")
    snapshot_version: Mapped[int] = mapped_column(Integer, default=1)
    lifecycle_state: Mapped[str] = mapped_column(String(40), index=True)
    phase: Mapped[str] = mapped_column(String(32), default="CODING")
    current_activity: Mapped[str] = mapped_column(Text, default="")
    next_owner_action: Mapped[str] = mapped_column(Text, default="")
    process_live: Mapped[bool] = mapped_column(Boolean, default=False)
    monitor_attached: Mapped[bool] = mapped_column(Boolean, default=False)
    terminal_evidence_observed: Mapped[bool] = mapped_column(Boolean, default=False)
    sidecar_state: Mapped[str] = mapped_column(String(40), default="NOT_OBSERVED")
    result_integrity_state: Mapped[str] = mapped_column(String(40), default="PENDING")
    blocker_code: Mapped[str] = mapped_column(String(120), default="", index=True)
    coding_started: Mapped[bool] = mapped_column(Boolean, default=False)
    process_exited: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_started: Mapped[bool] = mapped_column(Boolean, default=False)
    result_digest: Mapped[str] = mapped_column(String(64), default="", index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    coding_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settlement_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminal_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __mapper_args__ = {"version_id_col": snapshot_version}


class CodexActivityEvent(Base):
    """Bounded, privacy-safe observable lifecycle event (never raw deltas)."""

    __tablename__ = "codex_activity_events"
    __table_args__ = (
        UniqueConstraint("deduplication_identity", name="uq_codex_activity_dedup"),
        UniqueConstraint(
            "execution_attempt_id",
            "event_sequence",
            name="uq_codex_activity_attempt_sequence",
        ),
        CheckConstraint(
            "phase IN ('CODING','VERIFICATION','RESULT_SETTLEMENT')",
            name="ck_codex_activity_phase",
        ),
        CheckConstraint(
            "status IN ('STARTED','IN_PROGRESS','COMPLETED','FAILED','BLOCKED')",
            name="ck_codex_activity_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    execution_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("codex_execution_attempts.id"), index=True
    )
    phase: Mapped[str] = mapped_column(String(32), index=True)
    event_category: Mapped[str] = mapped_column(String(40), index=True)
    event_source: Mapped[str] = mapped_column(String(80))
    event_sequence: Mapped[int] = mapped_column(Integer)
    safe_summary: Mapped[str] = mapped_column(Text)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    repository_path: Mapped[str] = mapped_column(Text, default="")
    command_category: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(24), index=True)
    evidence_reference: Mapped[str] = mapped_column(String(64), default="")
    deduplication_identity: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CodexActivityAggregate(Base):
    """One bounded row for arbitrarily many related JSONL deltas."""

    __tablename__ = "codex_activity_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "execution_attempt_id",
            "aggregation_identity",
            name="uq_codex_activity_aggregate_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    execution_attempt_id: Mapped[int] = mapped_column(
        ForeignKey("codex_execution_attempts.id"), index=True
    )
    phase: Mapped[str] = mapped_column(String(32), index=True)
    event_category: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str] = mapped_column(String(120), default="")
    aggregation_identity: Mapped[str] = mapped_column(String(64), index=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    first_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    safe_first_sample: Mapped[str] = mapped_column(Text, default="")
    safe_last_sample: Mapped[str] = mapped_column(Text, default="")
    sample_digest: Mapped[str] = mapped_column(String(64), default="")
    final_observable_outcome: Mapped[str] = mapped_column(String(40), default="IN_PROGRESS")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CodexLifecycleNotification(Base):
    """Durable in-product notification projection; no external delivery."""

    __tablename__ = "codex_lifecycle_notifications"
    __table_args__ = (
        UniqueConstraint("deduplication_identity", name="uq_codex_lifecycle_notification_dedup"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    lifecycle_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("codex_lifecycle_snapshots.id"), index=True
    )
    notification_kind: Mapped[str] = mapped_column(String(80), index=True)
    terminal_state: Mapped[str] = mapped_column(String(40), default="")
    verification_result: Mapped[str] = mapped_column(String(40), default="UNAVAILABLE")
    safe_summary: Mapped[str] = mapped_column(Text)
    owner_action: Mapped[str] = mapped_column(Text)
    deduplication_identity: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CodexResultEnvelope(Base):
    __tablename__ = "codex_result_envelopes"
    __table_args__ = (
        UniqueConstraint("owner_id", "run_id", name="uq_codex_result_envelope_owner_run"),
        CheckConstraint(
            "integrity_state IN ('VERIFIED','BLOCKED')",
            name="ck_codex_result_envelope_integrity_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    envelope_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("codex_run_monitors.id"), unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("codex_runs.id"), unique=True, index=True
    )
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    pack_version: Mapped[int] = mapped_column(Integer)
    coding_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True
    )
    coding_assignment_version: Mapped[int] = mapped_column(Integer)
    verification_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_model_assignments.id"), nullable=True
    )
    verification_assignment_version: Mapped[int] = mapped_column(Integer)
    routing_snapshot_identity: Mapped[str] = mapped_column(String(64))
    source_snapshot_identity: Mapped[str] = mapped_column(String(64))
    approved_instruction_digest: Mapped[str] = mapped_column(String(64), default="")
    authorized_workspace_identity: Mapped[str] = mapped_column(String(64), default="")
    workspace_baseline_identity: Mapped[str] = mapped_column(String(64), default="")
    requested_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    actual_model_identifier: Mapped[str] = mapped_column(String(240), default="")
    terminal_status: Mapped[str] = mapped_column(String(40), index=True)
    process_exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_response: Mapped[str] = mapped_column(Text, default="")
    structured_handoff_json: Mapped[str] = mapped_column(Text, default="{}")
    structured_handoff_status: Mapped[str] = mapped_column(
        String(40), default="unavailable"
    )
    task_acceptance_json: Mapped[str] = mapped_column(Text, default="{}")
    tests_summary_json: Mapped[str] = mapped_column(Text, default="[]")
    changed_file_manifest_json: Mapped[str] = mapped_column(Text, default="[]")
    diff_identity: Mapped[str] = mapped_column(String(64), index=True)
    coding_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    verification_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    verification_verdict: Mapped[str] = mapped_column(String(40), default="unavailable")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    boundary_statements_json: Mapped[str] = mapped_column(Text, default="{}")
    process_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    workspace_evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    completion_classification: Mapped[str] = mapped_column(
        String(40), default="result_incomplete", index=True
    )
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    execution_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_source: Mapped[str] = mapped_column(String(80))
    result_source_identity: Mapped[str] = mapped_column(String(64))
    process_evidence_identity: Mapped[str] = mapped_column(String(64))
    result_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    integrity_state: Mapped[str] = mapped_column(String(24), index=True)
    integrity_findings_json: Mapped[str] = mapped_column(Text, default="[]")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    artifacts: Mapped[list["CodexResultArtifact"]] = relationship(
        back_populates="result_envelope",
        order_by="CodexResultArtifact.ordinal",
    )


class CodexResultArtifact(Base):
    __tablename__ = "codex_result_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "result_envelope_id",
            "ordinal",
            name="uq_codex_result_artifact_ordinal",
        ),
        UniqueConstraint(
            "result_envelope_id",
            "path_identity",
            name="uq_codex_result_artifact_path",
        ),
        CheckConstraint("ordinal >= 1", name="ck_codex_result_artifact_ordinal_positive"),
        CheckConstraint(
            "operation IN ('CREATE','MODIFY','DELETE','UNKNOWN')",
            name="ck_codex_result_artifact_operation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_envelope_id: Mapped[int] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    repository_path: Mapped[str] = mapped_column(Text)
    display_path: Mapped[str] = mapped_column(Text)
    path_identity: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(16))
    before_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    after_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    before_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    after_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_kind: Mapped[str] = mapped_column(String(40), default="unknown")
    unexpected: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_identity: Mapped[str] = mapped_column(String(64))
    artifact_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    result_envelope: Mapped[CodexResultEnvelope] = relationship(
        back_populates="artifacts"
    )


class HandoffReview(Base):
    __tablename__ = "handoff_reviews"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "result_envelope_id",
            name="uq_handoff_review_owner_envelope",
        ),
        CheckConstraint(
            "recommended_reconciliation IN ('PASS','BLOCKED')",
            name="ck_handoff_review_recommendation",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    result_envelope_id: Mapped[int] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    pack_id: Mapped[int] = mapped_column(
        ForeignKey("codex_instruction_packs.id"), index=True
    )
    run_outcome: Mapped[str] = mapped_column(String(40))
    coding_result: Mapped[str] = mapped_column(Text)
    verification_verdict: Mapped[str] = mapped_column(String(40))
    changed_files_json: Mapped[str] = mapped_column(Text, default="[]")
    tests_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    limitations_json: Mapped[str] = mapped_column(Text, default="[]")
    boundary_confirmation_json: Mapped[str] = mapped_column(Text, default="{}")
    current_phase_gate: Mapped[str] = mapped_column(Text)
    recommended_reconciliation: Mapped[str] = mapped_column(String(16), index=True)
    unresolved_blockers_json: Mapped[str] = mapped_column(Text, default="[]")
    review_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class HandoffInstructionDraft(Base):
    __tablename__ = "handoff_instruction_drafts"
    __table_args__ = (
        UniqueConstraint(
            "handoff_review_id",
            name="uq_handoff_instruction_draft_review",
        ),
        CheckConstraint("revision >= 1", name="ck_handoff_instruction_draft_revision"),
        CheckConstraint(
            "approval_state IN ('OWNER_APPROVAL_REQUIRED','APPROVED')",
            name="ck_handoff_instruction_draft_approval_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    handoff_review_id: Mapped[int] = mapped_column(
        ForeignKey("handoff_reviews.id"), unique=True, index=True
    )
    result_envelope_id: Mapped[int] = mapped_column(
        ForeignKey("codex_result_envelopes.id"), unique=True, index=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("codex_runs.id"), index=True)
    instruction_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    scope: Mapped[str] = mapped_column(Text)
    supersession: Mapped[str] = mapped_column(Text, default="")
    completion_gate_json: Mapped[str] = mapped_column(Text)
    required_handoff_json: Mapped[str] = mapped_column(Text)
    instruction_text: Mapped[str] = mapped_column(Text)
    draft_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    approval_state: Mapped[str] = mapped_column(
        String(40), default="OWNER_APPROVAL_REQUIRED", index=True
    )
    approved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def _reject_immutable_delivery_record_mutation(
    _mapper: object,
    _connection: object,
    target: object,
) -> None:
    raise RuntimeError(f"{type(target).__name__} records are append-only and immutable.")


for _immutable_delivery_model in (
    DeliveryCandidate,
    SourceDriftEvaluation,
    ApplyPlan,
    ApplyPlanEntry,
    ApplyPlanApproval,
    ApplySessionAudit,
    PostApplyVerification,
    CommitProposal,
    CommitProposalApproval,
    CommitPlan,
    PushPlan,
    PushPlanApproval,
    CodexResultEnvelope,
    CodexResultArtifact,
    HandoffReview,
):
    event.listen(
        _immutable_delivery_model,
        "before_update",
        _reject_immutable_delivery_record_mutation,
    )
    event.listen(
        _immutable_delivery_model,
        "before_delete",
        _reject_immutable_delivery_record_mutation,
    )


_OWNER_ACCEPTANCE_SET_ONCE_FIELDS = frozenset(
    {
        "owner_id",
        "result_envelope_id",
        "result_envelope_public_id",
        "result_digest",
        "result_task_version",
        "result_pack_id",
        "result_pack_version",
        "approved_instruction_digest",
        "delivery_candidate_id",
        "candidate_public_id",
        "candidate_version",
        "candidate_digest",
        "review_policy_version",
        "decision_version",
        "decision_digest",
    }
)


def _reject_owner_acceptance_rebinding(
    _mapper: object,
    _connection: object,
    target: OwnerAcceptanceSession,
) -> None:
    """Permit pending Result bindings to be filled once, never rebound."""
    state = sa_inspect(target)
    rebound: list[str] = []
    for field in _OWNER_ACCEPTANCE_SET_ONCE_FIELDS:
        history = state.attrs[field].history
        if not history.has_changes():
            continue
        old_values = list(history.deleted)
        old_value = old_values[0] if old_values else None
        if old_value not in {None, ""}:
            rebound.append(field)
    status_history = state.attrs.status.history
    if (
        not status_history.has_changes()
        and target.status in {"accepted", "rejected"}
        and (target.result_envelope_id is not None or target.decision_digest)
    ):
        rebound.append("terminal_result_decision")
    if status_history.has_changes():
        old_statuses = list(status_history.deleted)
        if old_statuses and old_statuses[0] in {"accepted", "rejected"}:
            result_history = state.attrs.result_envelope_id.history
            decision_history = state.attrs.decision_digest.history
            old_result_ids = list(result_history.deleted)
            old_decision_digests = list(decision_history.deleted)
            old_result_id = (
                old_result_ids[0]
                if old_result_ids
                else target.result_envelope_id
            )
            old_decision_digest = (
                old_decision_digests[0]
                if old_decision_digests
                else target.decision_digest
            )
            # A pre-19.1C acceptance was not a delivery decision.  Permit its
            # one-time reconciliation to pending only while it has neither a
            # Result binding nor decision evidence; a real Result decision is
            # terminal and cannot be rewritten.
            if old_result_id is not None or old_decision_digest:
                rebound.append("status")
    if rebound:
        raise RuntimeError(
            "Owner Acceptance Result, Candidate, and decision bindings may be set only once."
        )


event.listen(
    OwnerAcceptanceSession,
    "before_update",
    _reject_owner_acceptance_rebinding,
)
event.listen(
    OwnerAcceptanceSession,
    "before_delete",
    _reject_immutable_delivery_record_mutation,
)


_CODEX_RUN_MONITOR_IMMUTABLE_FIELDS = frozenset(
    {
        "monitor_id",
        "owner_id",
        "task_id",
        "task_version",
        "pack_id",
        "pack_version",
        "coding_assignment_id",
        "coding_assignment_version",
        "verification_assignment_id",
        "verification_assignment_version",
        "routing_snapshot_identity",
        "source_snapshot_identity",
        "run_id",
        "requested_model_identifier",
        "verification_model_identifier",
        "monitor_digest",
        "created_at",
    }
)
_HANDOFF_INSTRUCTION_DRAFT_IMMUTABLE_FIELDS = frozenset(
    {
        "draft_id",
        "owner_id",
        "handoff_review_id",
        "result_envelope_id",
        "run_id",
        "instruction_id",
        "revision",
        "scope",
        "supersession",
        "completion_gate_json",
        "required_handoff_json",
        "instruction_text",
        "draft_digest",
        "created_at",
    }
)
_CODEX_RUN_MONITOR_SET_ONCE_FIELDS = frozenset(
    {
        "process_id",
        "process_start_identity",
        "verification_process_id",
        "verification_process_start_identity",
        "codex_session_identity",
        "executable_fingerprint",
        "isolated_worktree_identity",
        "execution_location_identity",
        "result_locator_identity",
        "protected_result_locator",
    }
)

_CODEX_RUN_OWNER_START_SET_ONCE_FIELDS = frozenset(
    {
        "approved_instruction_digest",
        "start_idempotency_digest",
        "start_request_digest",
        "owner_start_confirmed_at",
        "cancellation_requested_at",
    }
)


def _reject_codex_run_owner_start_rebinding(
    _mapper: object,
    _connection: object,
    target: CodexRun,
) -> None:
    """Allow legacy rows to acquire start bindings once, never to rewrite them."""
    state = sa_inspect(target)
    rebound: list[str] = []
    for field in _CODEX_RUN_OWNER_START_SET_ONCE_FIELDS:
        history = state.attrs[field].history
        if not history.has_changes():
            continue
        old_values = list(history.deleted)
        old_value = old_values[0] if old_values else None
        if old_value not in {None, ""}:
            rebound.append(field)
    if rebound:
        raise RuntimeError(
            "CodexRun Owner action bindings may be set only once."
        )


event.listen(CodexRun, "before_update", _reject_codex_run_owner_start_rebinding)


def _reject_result_intake_core_mutation(
    _mapper: object,
    _connection: object,
    target: object,
) -> None:
    immutable_fields = (
        _CODEX_RUN_MONITOR_IMMUTABLE_FIELDS
        if isinstance(target, CodexRunMonitor)
        else _HANDOFF_INSTRUCTION_DRAFT_IMMUTABLE_FIELDS
    )
    state = sa_inspect(target)
    changed = [
        field
        for field in immutable_fields
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise RuntimeError(
            f"{type(target).__name__} immutable binding fields cannot change."
        )
    if isinstance(target, CodexRunMonitor):
        rebound = []
        for field in _CODEX_RUN_MONITOR_SET_ONCE_FIELDS:
            history = state.attrs[field].history
            if not history.has_changes():
                continue
            old_values = list(history.deleted)
            old_value = old_values[0] if old_values else None
            if old_value not in {None, ""}:
                rebound.append(field)
        if rebound:
            raise RuntimeError(
                "CodexRunMonitor process and location bindings may be set only once."
            )


for _result_intake_mutable_model in (CodexRunMonitor, HandoffInstructionDraft):
    event.listen(
        _result_intake_mutable_model,
        "before_update",
        _reject_result_intake_core_mutation,
    )
    event.listen(
        _result_intake_mutable_model,
        "before_delete",
        _reject_immutable_delivery_record_mutation,
    )


_APPLY_SESSION_IMMUTABLE_FIELDS = frozenset(
    {
        "session_id",
        "owner_id",
        "apply_plan_id",
        "apply_plan_public_id",
        "apply_plan_digest",
        "delivery_candidate_id",
        "candidate_public_id",
        "candidate_digest",
        "candidate_version",
        "result_envelope_id",
        "result_envelope_public_id",
        "result_digest",
        "owner_acceptance_id",
        "result_review_decision_digest",
        "apply_plan_approval_id",
        "apply_plan_approval_public_id",
        "apply_plan_approval_digest",
        "run_id",
        "task_id",
        "task_version",
        "pack_id",
        "pack_version",
        "source_snapshot_identity",
        "source_workspace_identity",
        "run_workspace_identity",
        "run_workspace_baseline_identity",
        "run_workspace_post_state_identity",
        "source_drift_evaluation_id",
        "repository_locator_fingerprint",
        "repository_fingerprint",
        "sanitized_repository_identity",
        "branch",
        "pre_apply_head",
        "pre_apply_index_fingerprint",
        "pre_apply_worktree_fingerprint",
        "included_path_count",
        "excluded_path_count",
        "blocked_path_count",
        "included_paths_json",
        "excluded_paths_json",
        "blocked_paths_json",
        "ordered_operations_json",
        "apply_confirmation_digest",
        "journal_digest",
        "before_evidence_json",
        "created_at",
        "started_at",
    }
)
_APPLY_SESSION_ENTRY_IMMUTABLE_FIELDS = frozenset(
    {
        "apply_session_id",
        "apply_plan_entry_id",
        "operation_ordinal",
        "repository_path",
        "path_identity",
        "operation",
        "reverse_operation",
        "before_present",
        "before_hash",
        "before_size",
        "before_mode",
        "before_file_type",
        "before_atime_ns",
        "before_mtime_ns",
        "before_material",
        "after_present",
        "after_hash",
        "after_size",
        "after_mode",
        "after_file_type",
        "after_atime_ns",
        "after_mtime_ns",
        "after_material",
        "temporary_material_identity",
        "parent_chain_json",
        "created_parent_dirs_json",
    }
)


def _reject_apply_journal_core_mutation(
    _mapper: object,
    _connection: object,
    target: object,
) -> None:
    immutable_fields = (
        _APPLY_SESSION_IMMUTABLE_FIELDS
        if isinstance(target, ApplySession)
        else _APPLY_SESSION_ENTRY_IMMUTABLE_FIELDS
    )
    state = sa_inspect(target)
    changed = [
        field
        for field in immutable_fields
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise RuntimeError(
            f"{type(target).__name__} immutable journal fields cannot change."
        )


for _apply_journal_model in (ApplySession, ApplySessionEntry):
    event.listen(
        _apply_journal_model,
        "before_update",
        _reject_apply_journal_core_mutation,
    )
    event.listen(
        _apply_journal_model,
        "before_delete",
        _reject_immutable_delivery_record_mutation,
    )


_STAGE_EXECUTION_IMMUTABLE_FIELDS = frozenset(
    {
        "stage_execution_id",
        "owner_id",
        "commit_plan_id",
        "commit_plan_public_id",
        "commit_plan_digest",
        "verification_digest",
        "repository_locator_fingerprint",
        "branch",
        "branch_ref",
        "base_head",
        "planned_entries_json",
        "planned_entries_digest",
        "pre_stage_evidence_json",
        "pre_stage_evidence_digest",
        "created_at",
        "started_at",
    }
)
_STAGE_EXECUTION_SET_ONCE_FIELDS = frozenset(
    {
        "post_stage_evidence_json",
        "staged_entries_json",
        "staged_entries_digest",
        "stage_digest",
        "finished_at",
    }
)
_LOCAL_COMMIT_EXECUTION_IMMUTABLE_FIELDS = frozenset(
    {
        "commit_execution_id",
        "owner_id",
        "commit_proposal_id",
        "commit_proposal_approval_id",
        "commit_plan_id",
        "stage_execution_id",
        "commit_plan_public_id",
        "commit_plan_digest",
        "stage_execution_public_id",
        "stage_digest",
        "repository_locator_fingerprint",
        "branch",
        "branch_ref",
        "base_head",
        "staged_entries_json",
        "staged_entries_digest",
        "subject_digest",
        "body_digest",
        "message_digest",
        "intent_digest",
        "pre_commit_evidence_json",
        "pre_commit_evidence_digest",
        "proposal_public_id",
        "proposal_digest",
        "proposal_approval_public_id",
        "proposal_approval_digest",
        "owner_commit_confirmation_digest",
        "owner_commit_confirmed_at",
        "result_envelope_id",
        "result_envelope_public_id",
        "result_digest",
        "owner_acceptance_id",
        "result_review_decision_digest",
        "candidate_version",
        "apply_plan_approval_id",
        "apply_plan_approval_public_id",
        "apply_plan_approval_digest",
        "source_workspace_identity",
        "run_workspace_identity",
        "author_identity_sanitized",
        "author_identity_digest",
        "created_at",
        "started_at",
    }
)
_LOCAL_COMMIT_EXECUTION_SET_ONCE_FIELDS = frozenset(
    {
        "tree_oid",
        "commit_oid",
        "parent_oid",
        "post_commit_evidence_json",
        "receipt_digest",
        "command_started_at",
        "command_finished_at",
        "command_exit_code",
        "command_output_json",
        "command_evidence_json",
        "command_evidence_digest",
        "hooks_evidence_json",
        "hooks_evidence_digest",
        "finished_at",
    }
)


def _reject_commit_execution_core_mutation(
    _mapper: object,
    _connection: object,
    target: object,
) -> None:
    if isinstance(target, StageExecution):
        immutable_fields = _STAGE_EXECUTION_IMMUTABLE_FIELDS
        set_once_fields = _STAGE_EXECUTION_SET_ONCE_FIELDS
    else:
        immutable_fields = _LOCAL_COMMIT_EXECUTION_IMMUTABLE_FIELDS
        set_once_fields = _LOCAL_COMMIT_EXECUTION_SET_ONCE_FIELDS
    state = sa_inspect(target)
    changed = [
        field
        for field in immutable_fields
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise RuntimeError(
            f"{type(target).__name__} immutable binding fields cannot change."
        )
    rebound = []
    for field in set_once_fields:
        history = state.attrs[field].history
        if not history.has_changes():
            continue
        old_values = list(history.deleted)
        old_value = old_values[0] if old_values else None
        if old_value not in {None, "", "{}", "[]"}:
            rebound.append(field)
    if rebound:
        raise RuntimeError(
            f"{type(target).__name__} transition evidence may be set only once."
        )


for _commit_execution_model in (StageExecution, LocalCommitExecution):
    event.listen(
        _commit_execution_model,
        "before_update",
        _reject_commit_execution_core_mutation,
    )
    event.listen(
        _commit_execution_model,
        "before_delete",
        _reject_immutable_delivery_record_mutation,
    )


_PUSH_EXECUTION_IMMUTABLE_FIELDS = frozenset(
    {
        "push_execution_id",
        "owner_id",
        "push_plan_id",
        "push_plan_approval_id",
        "local_commit_execution_id",
        "stage_execution_id",
        "commit_plan_id",
        "post_apply_verification_id",
        "apply_session_id",
        "delivery_candidate_id",
        "run_id",
        "task_id",
        "push_plan_public_id",
        "push_plan_digest",
        "push_plan_approval_public_id",
        "push_plan_approval_digest",
        "local_commit_public_id",
        "local_commit_receipt_digest",
        "commit_plan_digest",
        "stage_digest",
        "verification_digest",
        "candidate_digest",
        "journal_digest",
        "repository_locator_fingerprint",
        "sanitized_repository_identity",
        "branch",
        "branch_ref",
        "remote_name",
        "destination_ref",
        "approved_commit_oid",
        "expected_parent_oid",
        "subject",
        "subject_digest",
        "remote_fetch_url_digest",
        "remote_push_url_digest",
        "remote_config_fingerprint",
        "observed_remote_base_oid",
        "preflight_evidence_json",
        "preflight_evidence_digest",
        "confirmation_digest",
        "refspec",
        "command_evidence_json",
        "command_evidence_digest",
        "created_at",
    }
)
_PUSH_EXECUTION_SET_ONCE_FIELDS = frozenset(
    {
        "command_started_at",
        "command_finished_at",
        "execution_remote_base_oid",
        "command_exit_code",
        "command_output_json",
        "failure_category",
        "failure_evidence_json",
        "post_push_evidence_json",
        "recovery_reconciliation_json",
        "recovery_reconciliation_digest",
        "recovered_at",
        "receipt_digest",
        "finished_at",
    }
)
_PUSH_EXECUTION_TERMINAL_STATES = frozenset(
    {
        "PUSHED",
        "PUSH_BLOCKED",
        "REMOTE_MOVED",
        "PUSH_FAILED",
    }
)
_PUSH_EXECUTION_ALLOWED_TRANSITIONS = frozenset(
    {
        ("READY_TO_PUSH", "PUSHING"),
        ("READY_TO_PUSH", "PUSH_BLOCKED"),
        ("READY_TO_PUSH", "REMOTE_MOVED"),
        ("PUSHING", "PUSHED"),
        ("PUSHING", "REMOTE_MOVED"),
        ("PUSHING", "PUSH_FAILED"),
        ("PUSHING", "RECONCILIATION_BLOCKED"),
        ("RECONCILIATION_BLOCKED", "PUSHED"),
    }
)


def _reject_push_execution_mutation(
    _mapper: object,
    _connection: object,
    target: PushExecution,
) -> None:
    state = sa_inspect(target)
    state_history = state.attrs.state.history
    old_state = (
        str(list(state_history.deleted)[0])
        if state_history.deleted
        else str(target.state)
    )
    if old_state in _PUSH_EXECUTION_TERMINAL_STATES:
        raise RuntimeError("Terminal Push execution records are immutable.")
    changed = [
        field
        for field in _PUSH_EXECUTION_IMMUTABLE_FIELDS
        if state.attrs[field].history.has_changes()
    ]
    if changed:
        raise RuntimeError("Push execution binding and intent fields are immutable.")
    if state_history.has_changes() and (
        old_state,
        str(target.state),
    ) not in _PUSH_EXECUTION_ALLOWED_TRANSITIONS:
        raise RuntimeError("The Push execution state transition is invalid.")
    rebound = []
    for field in _PUSH_EXECUTION_SET_ONCE_FIELDS:
        history = state.attrs[field].history
        if not history.has_changes():
            continue
        old_values = list(history.deleted)
        old_value = old_values[0] if old_values else None
        if old_value not in {None, "", "{}", "[]"}:
            rebound.append(field)
    if rebound:
        raise RuntimeError("Push execution transition evidence may be set only once.")
    attempt_history = state.attrs.command_attempt_count.history
    if attempt_history.has_changes():
        old_values = list(attempt_history.deleted)
        old_value = int(old_values[0]) if old_values else 0
        if old_value != 0 or int(target.command_attempt_count) != 1:
            raise RuntimeError("A Push confirmation authorizes one attempt only.")


event.listen(PushExecution, "before_update", _reject_push_execution_mutation)
event.listen(
    PushExecution,
    "before_delete",
    _reject_immutable_delivery_record_mutation,
)


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
