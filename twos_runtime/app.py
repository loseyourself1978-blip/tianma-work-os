from __future__ import annotations

import json
import logging
import hashlib
import re
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .ai_orchestration import (
    compose_team,
    decode_capability_tags,
    has_complete_verified_codex_run_evidence,
    is_verified_real_invocation,
    latest_model_assignments,
    model_registry_snapshot,
    recompose_model_assignments,
    route_capability,
    verified_actual_model_identity,
)
from .codex_adapter import CodexExecutionManager
from .codex_connectivity import (
    codex_child_environment,
    connectivity_evidence_out,
    connectivity_status,
    verify_codex_connection,
)
from .config import Settings, get_settings
from .db import initialize_database, make_engine, make_session_factory, seed_ai_registry, seed_registry
from .delivery_candidates import (
    delivery_candidate_eligibility,
    delivery_candidate_out,
    evaluate_source_drift,
    find_owner_run,
    get_or_create_delivery_candidate,
    result_review_decision_digest,
    source_drift_out,
    validate_delivery_candidate,
)
from .apply_plans import (
    ApplyPlanError,
    apply_plan_approval_out,
    apply_plan_history,
    apply_plan_out,
    get_or_create_apply_plan_approval,
    get_or_create_apply_plan,
    latest_apply_plan,
)
from .apply_sessions import (
    ApplySessionError,
    apply_accepted_changes,
    apply_confirmation_out,
    apply_session_out,
    find_owned_apply_session,
    reconcile_incomplete_apply_sessions,
    revert_applied_changes,
    revert_confirmation_out,
)
from .post_apply_verifications import (
    PostApplyVerificationError,
    find_owned_post_apply_verification,
    get_or_create_post_apply_verification,
    post_apply_verification_review,
)
from .commit_builder import (
    CommitBuilderError,
    commit_builder_review,
    create_local_commit,
    find_owned_commit_plan,
    find_owned_stage_execution,
    get_or_create_commit_plan,
    stage_commit_plan,
)
from .owner_commit_delivery import (
    approve_commit_proposal,
    confirm_local_commit,
    create_commit_proposal,
    find_owned_commit_proposal,
    owner_commit_review,
)
from .push_delivery import (
    PushDeliveryError,
    approve_push_plan,
    confirm_approved_push_plan,
    confirm_push_to_origin_main,
    create_push_preflight,
    find_owned_local_commit_execution,
    find_owned_push_plan,
    find_owned_push_execution,
    get_or_create_push_plan,
    push_delivery_review,
    push_plan_review,
)
from .result_intake import (
    ResultIntakeError,
    ResultIntakeMonitor,
    approve_instruction_draft,
    ensure_run_monitor,
    get_or_create_handoff_review,
    get_or_create_instruction_draft,
    handoff_review_out,
    import_codex_result,
    instruction_draft_out,
    monitor_out,
    process_identity_matches,
    reconnect_run_monitor,
    result_envelope_out,
    source_snapshot_unavailable_for_run,
)
from .run_lifecycle import coding_timeout_receipt_persisted, lifecycle_snapshot_out
from .models import (
    AICapability,
    AIModel,
    AIModelAvailabilityEvidence,
    AIModelAssignment,
    AIModelInvocationEvidence,
    AITeamPlan,
    AITeamPlanItem,
    AcceptanceCheck,
    AuditEvent,
    CodexInstructionPack,
    CodexExecutionAttempt,
    CodexRun,
    DeliveryCandidate,
    ApplyPlan,
    ApplySession,
    CommitPlan,
    CommitProposal,
    CommitProposalApproval,
    PostApplyVerification,
    StageExecution,
    LocalCommitExecution,
    CodexResultEnvelope,
    CodexRunMonitor,
    HandoffInstructionDraft,
    HandoffReview,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    PushExecution,
    PushPlanApproval,
    Project,
    Provider,
    RoutingDecision,
    Schedule,
    Task,
    TaskRun,
    Tool,
    User,
    utc_now,
)
from .policy import ACTION_POLICIES, CONNECTOR_STATUSES, LIFECYCLE_STATES, evaluate_action
from .provider_gateway import ProviderGateway
from .scheduler import RuntimeScheduler, compute_next_run
from .security import (
    GENERIC_AUTH_MESSAGE,
    AuthFailureReason,
    AuthenticationError,
    authenticate,
    create_owner,
    normalize_username,
    owner_record_issue,
    revoke_token,
    user_for_token,
)
from .self_hosting import (
    accepted_compact_sync,
    assignment_snapshot_out,
    build_instruction_pack,
    codex_execution_target,
    development_task_digest,
    git_source_state,
    invalidate_approved_packs,
    model_routing_snapshot,
    pack_routing_binding_error,
    run_eligibility,
    verification_execution_target,
)
from .workers import parse_acceptance, run_task


SESSION_COOKIE = "twos_session"
OWNER_ACTIONS = ("Analyze", "Compact Sync", "Acceptance Review")
logger = logging.getLogger(__name__)

DERIVED_OBJECTIVE = "Complete the Development task exactly as specified."
DERIVED_SOURCE_CONTEXT = "None provided."
DERIVED_REQUIRED_OUTPUT = "The outputs explicitly requested by the Development task."
DERIVED_ACCEPTANCE_TARGET = "The Development task requirements and explicit boundaries are satisfied."
DERIVED_IMPLEMENTATION_SCOPE = "Only changes required by the Development task are permitted."
DERIVED_FORBIDDEN_SCOPE = (
    "No automatic commit, merge, push, force push, tag, Provider execution, or Codex execution."
)

AUTH_VALIDATION_MESSAGE = "Check the highlighted fields."
AUTH_CREDENTIAL_MESSAGE = GENERIC_AUTH_MESSAGE
AUTH_SERVICE_MESSAGE = "Something went wrong. Try again."
AUTH_ACCOUNT_EXISTS_MESSAGE = "An account already exists. Log in instead."
AUTH_REQUEST_PATHS = frozenset(
    {
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/logout",
        # Temporary compatibility endpoints use the same product-safe handling.
        "/api/auth/init",
    }
)


class AuthAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        super().__init__(message)


class OwnerInitIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("username")
    @classmethod
    def username_must_have_content(cls, value: str) -> str:
        if not normalize_username(value):
            raise ValueError("Username is required.")
        return value


class SignupIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("username")
    @classmethod
    def username_must_have_content(cls, value: str) -> str:
        if not normalize_username(value):
            raise ValueError("Username is required.")
        return value


class LoginIn(BaseModel):
    # The local CLI historically allowed longer credentials; keep a bounded
    # compatibility window while all new Owner creation stays at 80/200.
    username: str = Field(min_length=1, max_length=1024)
    password: str = Field(min_length=1, max_length=4096)

    @field_validator("username")
    @classmethod
    def username_must_have_content(cls, value: str) -> str:
        if not normalize_username(value):
            raise ValueError("Username is required.")
        return value


class ApplyAcceptedChangesIn(BaseModel):
    confirmation: Literal["APPLY_ACCEPTED_CHANGES"]
    expected_plan_digest: str = Field(min_length=64, max_length=64)
    expected_candidate_digest: str = Field(min_length=64, max_length=64)
    expected_plan_approval_digest: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )
    expected_result_digest: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )
    expected_result_review_decision_digest: Optional[str] = Field(
        default=None, min_length=64, max_length=64
    )


class ResultDeliveryDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal[
        "ACCEPT_RESULT_FOR_DELIVERY",
        "REJECT_RESULT_FOR_DELIVERY",
    ]
    expected_result_id: str = Field(min_length=1, max_length=80)
    expected_result_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_candidate_id: str = Field(min_length=1, max_length=80)
    expected_candidate_version: int = Field(ge=1)
    expected_candidate_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    note: str = Field(default="", max_length=2000)


class ApplyPlanApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["APPROVE_APPLY_PLAN"]
    expected_plan_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_candidate_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_result_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_result_review_decision_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class RevertAppliedChangesIn(BaseModel):
    confirmation: Literal["REVERT_APPLIED_CHANGES"]
    expected_journal_digest: str = Field(min_length=64, max_length=64)


class StartCodexRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["START_CODEX_RUN"]
    idempotency_key: str = Field(
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$",
    )
    pack_id: int = Field(ge=1)
    pack_version: int = Field(ge=1)


class PostApplyVerificationIn(BaseModel):
    expected_journal_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class ReviewCommitPlanIn(BaseModel):
    expected_verification_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=4_000)

    @field_validator("subject")
    @classmethod
    def commit_subject_is_bounded_one_line(cls, value: str) -> str:
        if (
            value != value.strip()
            or "\n" in value
            or "\r" in value
            or "\x00" in value
            or len(value.encode("utf-8")) > 200
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("Commit subject must be one bounded UTF-8 line.")
        return value

    @field_validator("body")
    @classmethod
    def commit_body_is_bounded_text(cls, value: str) -> str:
        if (
            len(value.encode("utf-8")) > 4_000
            or "\x00" in value
            or "\r" in value
            or any(
                ord(character) < 32 and character not in {"\n", "\t"}
                for character in value
            )
        ):
            raise ValueError("Commit body must be bounded UTF-8 text.")
        return value


class ReviewCommitProposalIn(ReviewCommitPlanIn):
    """Versioned, read-only Commit proposal review for the canonical 19.1D path."""

    model_config = ConfigDict(extra="forbid")


class ApproveCommitProposalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["APPROVE_COMMIT_PROPOSAL"]
    expected_proposal_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_proposal_version: int = Field(ge=1)


class ConfirmApprovedLocalCommitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["CREATE_LOCAL_COMMIT"]
    expected_proposal_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_approval_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class StageApprovedFilesIn(BaseModel):
    confirmation: Literal["STAGE_APPROVED_FILES"]
    expected_plan_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class CreateLocalCommitIn(BaseModel):
    confirmation: Literal["CREATE_LOCAL_COMMIT"]
    expected_plan_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_stage_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class CreatePushPreflightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmPushToOriginMainIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["PUSH_TO_ORIGIN_MAIN"]
    expected_confirmation_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class ApprovePushPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["APPROVE_PUSH_PLAN"]
    expected_plan_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_plan_version: int = Field(ge=1)


class ConfirmApprovedPushIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["PUSH_TO_ORIGIN_MAIN"]
    expected_plan_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    expected_approval_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    request_identity: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class CodexResultImportIn(BaseModel):
    result: Any


class InstructionDraftActionIn(BaseModel):
    action: Literal["review", "approve"] = "review"
    expected_digest: str = Field(default="", max_length=64)


class ProjectIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    status: str = "active"


class TaskIn(BaseModel):
    project_id: int
    development_task: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=240)
    action: Optional[str] = None
    task_type: Optional[str] = None
    source_sync_summary: str = ""
    required_output: str = ""
    boundary_risk: str = ""
    workflow_type: Literal["general", "product_development"] = "general"
    objective: str = ""
    implementation_scope: str = ""
    forbidden_scope: str = ""
    acceptance_target: str = ""


class TaskPatchIn(BaseModel):
    project_id: Optional[int] = None
    development_task: Optional[str] = None
    title: Optional[str] = None
    action: Optional[str] = None
    task_type: Optional[str] = None
    source_sync_summary: Optional[str] = None
    required_output: Optional[str] = None
    boundary_risk: Optional[str] = None
    workflow_type: Optional[Literal["general", "product_development"]] = None
    objective: Optional[str] = None
    implementation_scope: Optional[str] = None
    forbidden_scope: Optional[str] = None
    acceptance_target: Optional[str] = None
    status: Optional[str] = None


class RunIn(BaseModel):
    action: str = "compact_sync"


class ScheduleIn(BaseModel):
    task_id: int
    name: str = Field(min_length=1, max_length=160)
    interval_seconds: int = Field(default=3600, ge=1)


class SchedulePatchIn(BaseModel):
    paused: Optional[bool] = None
    run_now: bool = False
    interval_seconds: Optional[int] = Field(default=None, ge=1)


class TeamComposeIn(BaseModel):
    task_id: int
    risk_level: Literal["low", "medium", "high"] = "medium"
    urgency: Literal["normal", "high"] = "normal"
    capability_override: list[str] = Field(default_factory=list)


class RouteIn(BaseModel):
    task_id: int
    capability: str = Field(min_length=1, max_length=80)
    team_plan_id: Optional[int] = None
    urgency: Literal["normal", "high"] = "normal"
    cost_sensitivity: Literal["low", "balanced", "high"] = "balanced"
    latency_sensitivity: Literal["low", "balanced", "high"] = "balanced"


class CodexSetupIn(BaseModel):
    model_identifier: str = Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
    capability: Literal["coding", "verification"] = "coding"


class CodexAssignIn(BaseModel):
    model_id: int
    capability: Literal["coding", "verification"] = "coding"


class AcceptanceItemPatchIn(BaseModel):
    status: Literal["pass", "fail", "needs_review"]
    note: str = Field(default="", max_length=1000)


class AcceptanceDecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


def iso(value) -> str | None:
    return value.isoformat() + "Z" if value else None


def project_out(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "key": project.key,
        "name": project.name,
        "status": project.status,
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


def persisted_action(action: str | None, task_type: str | None) -> str:
    if action is not None:
        if action not in OWNER_ACTIONS:
            raise ValueError("Action must be Analyze, Compact Sync, or Acceptance Review.")
        return action
    return task_type or "Compact Sync"


def task_out(task: Task) -> dict[str, Any]:
    action = task.task_type if task.task_type in OWNER_ACTIONS else "Analyze"
    return {
        "id": task.id,
        "project_id": task.project_id,
        "project": project_out(task.project) if task.project else None,
        "title": task.title,
        "development_task": task.development_task or task.title,
        "task_type": task.task_type,
        "action": action,
        "source_sync_summary": task.source_sync_summary,
        "required_output": task.required_output,
        "boundary_risk": task.boundary_risk,
        "workflow_type": task.workflow_type,
        "objective": task.objective,
        "implementation_scope": task.implementation_scope,
        "forbidden_scope": task.forbidden_scope,
        "acceptance_target": task.acceptance_target,
        "objective_provenance": task.objective_provenance,
        "source_context_provenance": task.source_context_provenance,
        "required_output_provenance": task.required_output_provenance,
        "acceptance_target_provenance": task.acceptance_target_provenance,
        "implementation_scope_provenance": task.implementation_scope_provenance,
        "forbidden_scope_provenance": (
            "derived" if task.forbidden_scope == DERIVED_FORBIDDEN_SCOPE else "owner-edited"
        ),
        "provenance": {
            "objective": task.objective_provenance,
            "source_feedback_context": task.source_context_provenance,
            "required_output": task.required_output_provenance,
            "acceptance_target": task.acceptance_target_provenance,
            "implementation_scope": task.implementation_scope_provenance,
        },
        "repository_identity": task.repository_identity,
        "source_baseline_commit": task.source_baseline_commit,
        "task_version": task.task_version,
        "status": task.status,
        "acceptance_state": task.acceptance_state,
        "compact_sync_result": task.compact_sync_result,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def run_out(run: TaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "action": run.action,
        "status": run.status,
        "result": run.result,
        "error": run.error,
        "attempts": run.attempts,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }


def schedule_out(schedule: Schedule, run_count: int = 0) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "task_id": schedule.task_id,
        "name": schedule.name,
        "interval_seconds": schedule.interval_seconds,
        "paused": schedule.paused,
        "next_run_at": iso(schedule.next_run_at),
        "last_run_at": iso(schedule.last_run_at),
        "run_count": run_count,
        "created_at": iso(schedule.created_at),
        "updated_at": iso(schedule.updated_at),
    }


def registry_out(item: Provider | Tool) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "status": item.status,
        "enabled": item.enabled,
        "details": item.details,
        "last_checked_at": iso(item.last_checked_at),
    }


def provider_out(provider: Provider, health) -> dict[str, Any]:
    output = registry_out(provider)
    output.update(
        {
            "available": health.available,
            "health_reason": health.reason,
        }
    )
    return output


def capability_out(capability: AICapability) -> dict[str, Any]:
    return {
        "id": capability.id,
        "name": capability.name,
        "description": capability.description,
        "quality_requirement": capability.quality_requirement,
        "latency_sensitivity": capability.latency_sensitivity,
        "requires_tool_capability": capability.requires_tool_capability,
        "requires_verification": capability.requires_verification,
        "enabled": capability.enabled,
    }


def model_out(model: AIModel | None) -> dict[str, Any] | None:
    if not model:
        return None
    registry = model_registry_snapshot(model)
    provider = model.provider
    available = registry["availability_status"] == "available"
    activity_state = (
        "simulated"
        if registry["invocation_mode"] == "simulated"
        else "failed"
        if registry["last_invocation_outcome"] in {"failed", "cancelled", "timed_out", "blocked"}
        else "not_used"
    )
    return {
        "id": model.id,
        "stable_id": registry["stable_id"],
        "display_name": registry["display_name"],
        "provider": provider.name,
        "provider_status": provider.status,
        "provider_enabled": provider.enabled,
        "provider_model_id": registry["provider_model_id"],
        "execution_adapter": registry["execution_adapter"],
        "model_name": model.model_name,
        "capability_tags": decode_capability_tags(model),
        "context_limit": model.context_limit,
        "cost_metadata": model.cost_metadata,
        "latency_metadata": model.latency_metadata,
        "status": model.status,
        "routing_priority": model.routing_priority,
        "available": available,
        "configuration_status": registry["configuration_status"],
        "availability_status": registry["availability_status"],
        "invocation_mode": registry["invocation_mode"],
        "last_invocation_outcome": registry["last_invocation_outcome"],
        "evidence_status": registry["evidence_status"],
        "evidence_source": registry["evidence_source"],
        "last_verified_at": registry["last_verified_at"],
        "safe_diagnostic": registry["safe_diagnostic"],
        "activity_state": activity_state,
    }


def configured_model_record(model: AIModel) -> bool:
    """Exclude preserved vendor placeholders until explicit configuration exists."""
    return bool(
        model.configuration_status in {"configured", "disabled"}
        or str(model.provider_model_id or "").strip()
        or str(model.execution_adapter or "").strip()
    )


def decoded_list(value: str) -> list[Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def decoded_object(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def team_plan_out(session: Session, plan: AITeamPlan) -> dict[str, Any]:
    items = session.scalars(
        select(AITeamPlanItem).where(AITeamPlanItem.plan_id == plan.id).order_by(AITeamPlanItem.ordinal)
    ).all()
    required_capabilities = decoded_list(plan.required_capabilities)
    omitted_capabilities = decoded_list(plan.omitted_capabilities)
    return {
        "id": plan.id,
        "task_id": plan.task_id,
        "risk_level": plan.risk_level,
        "urgency": plan.urgency,
        "minimum_role_count": plan.minimum_role_count,
        "status": plan.status,
        "assignment_version": plan.assignment_version,
        "task_version": plan.task_version,
        "routing_snapshot_hash": plan.routing_snapshot_hash,
        "explanation": plan.explanation,
        "omission_explanation": plan.omission_explanation,
        "required_capabilities": required_capabilities,
        "omitted_capabilities": omitted_capabilities,
        "team": [
            {
                "capability": item.capability.name,
                "role_label": item.role_label,
                "selection_reason": item.selection_reason,
                "quality_requirement": item.capability.quality_requirement,
                "requires_tool_capability": item.capability.requires_tool_capability,
                "requires_verification": item.capability.requires_verification,
            }
            for item in items
        ],
        "created_at": iso(plan.created_at),
    }


def model_assignment_out(assignment: AIModelAssignment) -> dict[str, Any]:
    return assignment_snapshot_out(assignment)


def model_invocation_out(evidence: AIModelInvocationEvidence) -> dict[str, Any]:
    verified_real_invocation = is_verified_real_invocation(evidence)
    configured_model = model_out(evidence.configured_model)
    process_evidence = decoded_object(evidence.process_evidence)
    provider_evidence = decoded_object(evidence.provider_evidence)
    requested_model_identifier = str(evidence.configured_model.provider_model_id or "")
    if evidence.codex_run is not None:
        if evidence.capability == "coding":
            requested_model_identifier = evidence.codex_run.requested_model_identifier
        elif evidence.capability == "verification":
            requested_model_identifier = evidence.codex_run.verification_model_identifier
    actual_model, model_identity_source, connectivity_digest = (
        verified_actual_model_identity(evidence)
    )
    actual_model_identity_verified = bool(actual_model)
    actual_resolved_model_identifier = actual_model or None
    process_execution_verified = bool(
        verified_real_invocation
        and process_evidence.get("process_execution_verified") is True
    )
    codex_turn_verified = bool(
        verified_real_invocation
        and process_evidence.get("codex_turn_verified") is True
    )
    execution_state = (
        "invoked"
        if verified_real_invocation
        else "simulated"
        if evidence.invocation_mode == "simulated"
        else "failed"
        if evidence.outcome in {"failed", "cancelled", "timed_out", "blocked"}
        else "not_used"
    )
    return {
        "id": evidence.id,
        "task_id": evidence.task_id,
        "codex_run_id": evidence.codex_run_id,
        "capability": evidence.capability,
        "assignment_version": evidence.assignment_version,
        "configured_model": configured_model,
        "provider": evidence.configured_provider.name,
        "requested_model_identifier": requested_model_identifier,
        "actual_invoked_model_identifier": actual_resolved_model_identifier,
        "actual_resolved_model_identifier": actual_resolved_model_identifier,
        "actual_resolved_model_display": (
            actual_resolved_model_identifier
            if actual_resolved_model_identifier
            else "Not exposed by the current Codex CLI protocol."
            if verified_real_invocation
            else "Not verified"
        ),
        "actual_model_identity_verified": actual_model_identity_verified,
        "model_identity_source": model_identity_source or None,
        "connectivity_evidence_identity": connectivity_digest or None,
        "process_execution_verified": process_execution_verified,
        "codex_turn_verified": codex_turn_verified,
        "display_claim": (
            (
                f"Completed with connection-verified model {actual_resolved_model_identifier}"
                if model_identity_source == "owner_verified_connectivity_binding"
                else f"Ran with {actual_resolved_model_identifier}"
            )
            if verified_real_invocation and actual_resolved_model_identifier
            else (
                "Real Codex CLI invocation verified; "
                f"requested model {requested_model_identifier}; "
                "run-local effective model was not exposed by the current Codex CLI protocol"
            )
            if verified_real_invocation
            else f"Assigned to {configured_model['display_name']}"
        ),
        "verified_real_invocation": verified_real_invocation,
        "execution_state": execution_state,
        "invocation_mode": evidence.invocation_mode,
        "outcome": evidence.outcome,
        "process_evidence": process_evidence,
        "provider_evidence": provider_evidence,
        "timed_out": evidence.timed_out,
        "cancelled": evidence.cancelled,
        "output_truncated": evidence.output_truncated,
        "usage_metadata": decoded_object(evidence.usage_metadata),
        "error_category": evidence.error_category,
        "diagnostic_code": evidence.diagnostic_code,
        "safe_summary": evidence.safe_summary,
        "request_fingerprint": evidence.request_fingerprint,
        "response_fingerprint": evidence.response_fingerprint,
        "started_at": iso(evidence.started_at),
        "completed_at": iso(evidence.completed_at),
    }


def routing_out(decision: RoutingDecision) -> dict[str, Any]:
    requested_capabilities = decoded_list(decision.requested_capabilities)
    if not requested_capabilities and decision.team_plan:
        requested_capabilities = decoded_list(decision.team_plan.required_capabilities)
    fallback_status = decision.fallback_status or ("available" if decision.fallback_model else "unavailable")
    fallback_reason = decision.fallback_reason
    if not fallback_reason and decision.fallback_model:
        fallback_reason = (
            f"Fallback is {decision.fallback_model.provider.name} / {decision.fallback_model.model_name}."
        )
    elif not fallback_reason:
        fallback_reason = "No fallback is available because this persisted route has no eligible compatible model."
    next_action = decision.next_action or (
        "Configure and verify a compatible provider, then recompose the AI Team."
        if decision.status == "unavailable"
        else "Proceed under the task's approval and acceptance policies."
    )
    return {
        "id": decision.id,
        "task_id": decision.task_id,
        "team_plan_id": decision.team_plan_id,
        "capability": decision.capability.name,
        "urgency": decision.urgency,
        "cost_sensitivity": decision.cost_sensitivity,
        "latency_sensitivity": decision.latency_sensitivity,
        "requested_capabilities": requested_capabilities,
        "status": decision.status,
        "selected": model_out(decision.selected_model),
        "fallback": model_out(decision.fallback_model),
        "reason": decision.reason,
        "fallback_status": fallback_status,
        "fallback_reason": fallback_reason,
        "next_action": next_action,
        "created_at": iso(decision.created_at),
    }


def routing_summary_out(plan: AITeamPlan, routes: list[RoutingDecision]) -> dict[str, Any]:
    requested = decoded_list(plan.required_capabilities)
    selected_routes = [route for route in routes if route.status == "selected" and route.selected_model]
    completed = len(routes) == len(requested) and all(
        route.status in {"selected", "unavailable"} for route in routes
    )
    if completed and len(selected_routes) == len(requested):
        status = "ready"
    elif completed and not selected_routes:
        status = "unavailable"
    elif completed:
        status = "partial"
    else:
        status = "pending"

    primary = routes[0] if routes else None
    primary_output = routing_out(primary) if primary else None
    providers = sorted({route.selected_model.provider.name for route in selected_routes})
    models = sorted({route.selected_model.model_name for route in selected_routes})
    return {
        "status": status,
        "evaluation_completed": completed,
        "decision_count": len(routes),
        "requested_capabilities": requested,
        "selected_provider": ", ".join(providers) if providers else None,
        "selected_model": ", ".join(models) if models else None,
        "reason": primary.reason if primary else "Routing evaluation is pending for this plan.",
        "fallback_status": primary_output["fallback_status"] if primary_output else "pending",
        "fallback_reason": primary_output["fallback_reason"] if primary_output else "Routing evaluation has not completed.",
        "next_action": primary_output["next_action"] if primary_output else "Recompose the AI Team to evaluate routing.",
    }


def codex_pack_out(pack: CodexInstructionPack, include_raw: bool = False) -> dict[str, Any]:
    metadata = decoded_object(pack.generation_metadata)
    output = {
        "id": pack.id,
        "task_id": pack.task_id,
        "version": pack.version,
        "status": pack.status,
        "stage_summary": pack.stage_summary,
        "key_boundaries": pack.key_boundaries,
        "acceptance_target": pack.acceptance_target,
        "source_baseline_commit": pack.source_baseline_commit,
        "development_task": pack.development_task,
        "development_task_digest": pack.development_task_digest,
        "task_version": pack.task_version,
        "assignment_version": pack.assignment_version,
        "routing_snapshot_hash": pack.routing_snapshot_hash,
        "source_snapshot_digest": pack.source_snapshot_digest,
        "source_snapshot": metadata.get("source_snapshot"),
        "model_routing_snapshot": metadata.get("model_routing_snapshot"),
        "approved": pack.status == "approved" and pack.invalidated_at is None,
        "approved_at": iso(pack.approved_at),
        "invalidated_at": iso(pack.invalidated_at),
        "created_at": iso(pack.created_at),
    }
    if include_raw:
        output.update(
            {
                "content": pack.content,
                "ai_team_plan_id": pack.ai_team_plan_id,
                "routing_decision_ids": decoded_list(pack.routing_decision_ids),
                "generation_metadata": metadata,
            }
        )
    return output


def codex_approved_instruction_digest(pack: CodexInstructionPack) -> str:
    """Bind a Run to the exact approved Pack content without exposing it."""
    return hashlib.sha256((pack.content or "").encode("utf-8")).hexdigest()


def codex_start_idempotency_digest(
    owner_id: int,
    task_id: int,
    idempotency_key: str,
) -> str:
    material = json.dumps(
        {
            "owner_id": owner_id,
            "task_id": task_id,
            "idempotency_key": idempotency_key,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def codex_start_request_digest(
    owner_id: int,
    task_id: int,
    payload: StartCodexRunIn,
) -> str:
    material = json.dumps(
        {
            "owner_id": owner_id,
            "task_id": task_id,
            "pack_id": payload.pack_id,
            "pack_version": payload.pack_version,
            "idempotency_key": payload.idempotency_key,
            "confirmation": payload.confirmation,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def run_result_projection(
    run: CodexRun,
    result: dict[str, Any],
    *,
    coding_state: str | None = None,
) -> dict[str, Any]:
    """Stable public fields, not a persisted result or proof of settlement.

    Process truth can precede optional evidence collection. Never write this
    projection back to structured_result: an empty persisted result remains the
    recovery signal, and only actual envelope evidence establishes availability.
    The legacy process object describes Coding, not combined phase outcomes.
    """
    projected = dict(result)
    if run.timed_out:
        coding_status, failure = "timed_out", "Coding exceeded the configured timeout."
    elif run.cancelled:
        coding_status, failure = "cancelled", "Coding was cancelled by the Owner."
    elif type(run.exit_code) is int:
        coding_status = "completed" if run.exit_code == 0 else "failed"
        failure = "" if run.exit_code == 0 else f"Coding process exited with code {run.exit_code}."
    else:
        coding_status = str(run.status or "pending")
        if coding_status not in {"starting", "running", "blocked", "failed", "interrupted"}:
            coding_status = "pending"
        failure = ""
    if coding_state:
        coding_status = "completed" if coding_state == "succeeded" else coding_state
    if coding_status == "interrupted":
        failure = "Coding process evidence was interrupted."
    verification_started = bool(run.verification_process_spawned)
    verification_status = str(run.verification_status or "not_started")
    verification_summary = str(run.verification_summary or "")
    if not verification_summary and not verification_started:
        verification_summary = (
            "Verification was not started because Coding exceeded the configured timeout."
            if run.timed_out
            else "Verification has not started."
        )

    def object_with_defaults(key: str, defaults: dict[str, Any]) -> None:
        existing = projected.get(key)
        projected[key] = {**defaults, **(existing if isinstance(existing, dict) else {})}

    object_with_defaults("process", {
        "exit_code": run.exit_code,
        "timed_out": bool(run.timed_out),
        "cancelled": bool(run.cancelled),
        "runtime_interrupted": coding_status == "interrupted",
        "stderr_present": bool(run.stderr),
    })
    object_with_defaults("coding_process", {
        "status": coding_status,
        "process_started": bool(run.process_spawned),
        "exit_code": run.exit_code,
        "timed_out": bool(run.timed_out),
        "cancelled": bool(run.cancelled),
        "failure": failure,
    })
    object_with_defaults("verification", {
        "status": verification_status,
        "summary": verification_summary,
        "process_spawned": verification_started,
    })
    object_with_defaults("verification_process", {
        "status": verification_status,
        "process_started": verification_started,
        "exit_code": run.verification_exit_code,
        "timed_out": bool(run.verification_timed_out),
        "cancelled": bool(run.verification_cancelled),
        "failure": verification_summary if verification_status not in {"running", "completed"} else "",
    })
    object_with_defaults("verification_verdict", {
        "status": "not_reached", "passed_checks": [], "failed_checks": [],
    })
    for key in ("changed_files", "changed_file_evidence"):
        if not isinstance(projected.get(key), list):
            projected[key] = []
    return projected


def codex_run_out(
    run: CodexRun,
    include_raw: bool = False,
    session: Session | None = None,
) -> dict[str, Any]:
    # Sample lifecycle before process-proof normalization. Phase settlement may
    # commit between reads; never combine an older unverified invocation with
    # a newer completed lifecycle and publish that mixture as terminal truth.
    lifecycle = (
        lifecycle_snapshot_out(
            session, int(run.pack.approved_by_user_id), run, advanced=include_raw,
        )
        if session is not None
        and run.pack is not None
        and run.pack.approved_by_user_id is not None
        else None
    )
    result = decoded_object(run.structured_result)
    receipt_timeout = bool(
        session is not None and coding_timeout_receipt_persisted(session, run)
    )
    result["task_id"] = run.task_id
    result["task_version"] = run.task_version
    result["pack_version"] = run.pack.version if run.pack else None
    result["development_task"] = run.development_task
    result["frozen_development_task"] = run.development_task
    result["development_task_digest"] = run.development_task_digest

    canonical_state = {
        "approval_required": "pending",
        "queued": "pending",
        "starting": "starting",
        "running": "running",
        "verifying": "starting",
        "settling": "starting",
        "completed": "succeeded",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        "blocked": "blocked",
        "failed": "failed",
    }.get(str(run.status or "").lower(), "blocked")
    process_result = result.get("process")
    coding_process = result.get("coding_process")
    verification_process = result.get("verification_process")
    run_monitor = (
        session.scalar(
            select(CodexRunMonitor).where(CodexRunMonitor.run_id == run.id)
        )
        if session is not None
        else None
    )
    monitor_state = run_monitor.monitor_state if run_monitor is not None else None
    runtime_interrupted = bool(
        isinstance(process_result, dict)
        and process_result.get("runtime_interrupted") is True
    ) or bool(
        isinstance(coding_process, dict)
        and "interrupt" in str(coding_process.get("failure") or "").lower()
    ) or bool(
        isinstance(verification_process, dict)
        and (
            verification_process.get("runtime_interrupted") is True
            or "interrupt"
            in str(verification_process.get("failure") or "").lower()
        )
    ) or str(monitor_state or "").upper() == "PROCESS_LOST"
    coding_process_identity_verified = bool(
        run_monitor is not None
        and run_monitor.process_id
        and len(run_monitor.process_start_identity or "") == 64
        and process_identity_matches(
            int(run_monitor.process_id),
            run_monitor.process_start_identity,
        )
    )
    verification_process_identity_verified = bool(
        run_monitor is not None
        and run_monitor.verification_process_id
        and len(run_monitor.verification_process_start_identity or "") == 64
        and process_identity_matches(
            int(run_monitor.verification_process_id),
            run_monitor.verification_process_start_identity,
        )
    )
    if canonical_state == "running" and (
        str(monitor_state or "").upper() != "RUNNING"
        or not coding_process_identity_verified
    ):
        # A live PID is necessary but not sufficient for an Owner-visible
        # Running claim.  The durable monitor must still describe the exact
        # process as RUNNING; settlement/result-pending states stay Starting.
        canonical_state = "starting"
    if (
        str(run.status or "").lower() == "verifying"
        and run.verification_process_spawned
        and run.verification_status == "running"
        and str(monitor_state or "").upper() == "VERIFYING"
        and verification_process_identity_verified
    ):
        canonical_state = "running"
    if runtime_interrupted:
        canonical_state = "interrupted"
    elif (
        canonical_state == "blocked"
        and run.executable_status in {"needs_setup", "unconfigured"}
        and not run.process_spawned
    ):
        canonical_state = "needs_setup"

    result_envelope = (
        session.scalar(
            select(CodexResultEnvelope).where(CodexResultEnvelope.run_id == run.id)
        )
        if session is not None
        else None
    )
    changed_files = result.get("changed_files")
    changed_file_count = len(changed_files) if isinstance(changed_files, list) else 0
    structured_handoff = result.get("structured_handoff")
    workspace_evidence = result.get("workspace_evidence")
    exec_bridge = result.get("exec_bridge")
    preliminary_result_incomplete = bool(
        run.finished_at is not None
        and isinstance(coding_process, dict)
        and str(coding_process.get("status") or "").lower()
        in {"completed", "succeeded"}
        and coding_process.get("exit_code") == 0
        and (
            not isinstance(structured_handoff, dict)
            or not structured_handoff
            or not isinstance(workspace_evidence, dict)
            or not workspace_evidence
            or (
                isinstance(exec_bridge, dict)
                and str(exec_bridge.get("integrity_state") or "").lower()
                == "blocked"
            )
        )
    )
    completion_classification = (
        result_envelope.completion_classification
        if result_envelope is not None
        else "interrupted"
        if canonical_state == "interrupted"
        else "succeeded_with_changes"
        if canonical_state == "succeeded" and changed_file_count
        else "succeeded_without_workspace_changes"
        if canonical_state == "succeeded"
        else "result_incomplete"
        if preliminary_result_incomplete
        else canonical_state
        if canonical_state in {"failed", "cancelled", "timed_out"}
        else "result_incomplete"
        if run.finished_at is not None
        else "pending"
    )

    invocation_rows = (
        session.scalars(
            select(AIModelInvocationEvidence)
            .where(AIModelInvocationEvidence.codex_run_id == run.id)
            .order_by(AIModelInvocationEvidence.id)
        ).all()
        if session is not None
        else []
    )

    def invocation_for_capability(
        capability: str,
    ) -> AIModelInvocationEvidence | None:
        capability_rows = [
            row for row in invocation_rows if row.capability == capability
        ]
        return capability_rows[0] if len(capability_rows) == 1 else None

    def normalized_invocation_result(
        value: object,
        requested_model_identifier: str,
        evidence: AIModelInvocationEvidence | None,
    ) -> dict[str, Any]:
        proof = dict(value) if isinstance(value, dict) else {}
        if (
            evidence is None
            and proof.get("mode") == "local_command"
            and proof.get("model_provider_invoked") is False
        ):
            local_digest_shape_valid = all(
                re.fullmatch(r"[0-9a-f]{64}", str(proof.get(key) or ""))
                for key in (
                    "ticket_digest",
                    "command_digest",
                    "executable_fingerprint",
                )
            )
            local_attempt = (
                session.scalar(
                    select(CodexExecutionAttempt)
                    .where(
                        CodexExecutionAttempt.run_id == run.id,
                        CodexExecutionAttempt.phase == "VERIFICATION",
                    )
                    .order_by(CodexExecutionAttempt.id.desc())
                )
                if session is not None
                else None
            )
            local_binding_valid = bool(
                local_digest_shape_valid
                and local_attempt is not None
                and local_attempt.attempt_state == "COMPLETED"
                and local_attempt.ticket_digest == proof.get("ticket_digest")
                and re.fullmatch(
                    r"[0-9a-f]{64}", local_attempt.receipt_digest or ""
                )
                and local_attempt.executable_fingerprint
                == proof.get("command_digest")
                and type(local_attempt.process_id) is int
                and local_attempt.process_id > 0
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    local_attempt.process_start_identity or "",
                )
                and local_attempt.process_exit_known
                and local_attempt.process_exit_code == 0
                and local_attempt.terminal_event_observed
                and local_attempt.result_resolution_source
                in {
                    "FINAL_MESSAGE_SIDECAR",
                    "JSONL_FINAL_MESSAGE_RECOVERY",
                }
            )
            proof["requested_model"] = ""
            proof["requested_model_identifier"] = ""
            proof["configured_assignment_model"] = str(
                requested_model_identifier or ""
            )
            proof["actual_resolved_model"] = None
            proof["actual_resolved_model_identifier"] = None
            proof["actual_resolved_model_display"] = (
                "No model/provider invoked; deterministic local Verification."
            )
            proof["actual_model_identity_verified"] = False
            proof["model_identity_source"] = None
            proof["connectivity_evidence_identity"] = None
            proof["process_execution_verified"] = bool(
                local_binding_valid
                and proof.get("process_execution_verified") is True
            )
            proof["codex_turn_verified"] = False
            return proof
        requested = str(requested_model_identifier or "")
        actual_value, source, connectivity_digest = verified_actual_model_identity(
            evidence
        )
        actual = actual_value or None
        evidence_process = (
            decoded_object(evidence.process_evidence)
            if evidence is not None
            else {}
        )
        turn_verified = bool(
            evidence is not None
            and (
                evidence_process.get("codex_turn_verified") is True
                or (
                    evidence_process.get("codex_turn_completed") is True
                    and evidence_process.get("codex_lifecycle_conflict") is not True
                )
            )
        )
        process_verified = bool(
            evidence is not None
            and evidence_process.get("process_execution_verified") is True
        )
        proof["requested_model"] = requested
        proof["requested_model_identifier"] = requested
        proof["actual_resolved_model"] = actual
        proof["actual_resolved_model_identifier"] = actual
        proof["actual_resolved_model_display"] = (
            actual
            if actual
            else "Not exposed by the current Codex CLI protocol."
            if turn_verified
            else "Not verified"
        )
        proof["actual_model_identity_verified"] = bool(actual)
        proof["model_identity_source"] = source or None
        proof["connectivity_evidence_identity"] = connectivity_digest or None
        proof["process_execution_verified"] = process_verified
        proof["codex_turn_verified"] = turn_verified
        return proof

    result["coding_invocation"] = normalized_invocation_result(
        result.get("coding_invocation"),
        run.requested_model_identifier,
        invocation_for_capability("coding"),
    )
    result["verification_invocation"] = normalized_invocation_result(
        result.get("verification_invocation"),
        run.verification_model_identifier,
        invocation_for_capability("verification"),
    )
    output = {
        "id": run.id,
        "task_id": run.task_id,
        "pack_id": run.pack_id,
        "pack_version": run.pack.version if run.pack else None,
        "status": run.status,
        "canonical_status": canonical_state,
        "completion_classification": completion_classification,
        "changed_file_count": changed_file_count,
        "executable_status": run.executable_status,
        "owner_summary": run.owner_summary,
        "source_branch": run.source_branch,
        "source_commit": run.source_commit,
        "development_task": run.development_task,
        "development_task_digest": run.development_task_digest,
        "task_version": run.task_version,
        "assignment_version": run.assignment_version,
        "routing_snapshot_hash": run.routing_snapshot_hash,
        "source_snapshot_digest": run.source_snapshot_digest,
        "owner_start_confirmed": run.owner_start_confirmed_at is not None,
        "owner_start_confirmed_at": iso(run.owner_start_confirmed_at),
        "cancellation_requested_at": iso(run.cancellation_requested_at),
        "launch_intent_recorded": run.launch_intent_at is not None,
        "launch_intent_at": iso(run.launch_intent_at),
        "process_spawned": run.process_spawned,
        "execution_target": (
            {
                "assignment_id": run.execution_assignment_id,
                "model": model_out(run.execution_model),
                "requested_model_identifier": run.requested_model_identifier,
                "fallback_selected": run.fallback_selected,
            }
            if run.execution_assignment_id is not None
            else None
        ),
        "verification_target": (
            {
                "assignment_id": run.verification_assignment_id,
                "model": model_out(run.verification_model),
                "model_identifier": run.verification_model_identifier,
                "requested_model_identifier": run.verification_model_identifier,
                "status": run.verification_status,
                "summary": run.verification_summary,
                "process_spawned": run.verification_process_spawned,
                "exit_code": run.verification_exit_code,
                "duration_ms": run.verification_duration_ms,
                "timed_out": run.verification_timed_out,
                "cancelled": run.verification_cancelled,
                "output_truncated": run.verification_output_truncated,
            }
            if run.verification_assignment_id is not None
            else None
        ),
        "model_invocations": [model_invocation_out(item) for item in invocation_rows],
        "worktree_branch": run.worktree_branch,
        "exit_code": run.exit_code,
        "duration_ms": run.duration_ms,
        "timed_out": bool(run.timed_out or run.verification_timed_out),
        "cancelled": bool(run.cancelled or run.verification_cancelled),
        "result": result,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }
    if lifecycle is not None:
        output["lifecycle"] = lifecycle
        lifecycle_state = str(output["lifecycle"].get("state") or "").upper()
        verified_completion = bool(
            run.status == "completed"
            and result["coding_invocation"].get("process_execution_verified") is True
            and result["verification_invocation"].get("process_execution_verified") is True
        )
        if (
            str(run.status or "").lower()
            in {"completed", "failed", "blocked", "cancelled", "timed_out"}
            and not receipt_timeout
            and not verified_completion
            and lifecycle_state
            in {"QUEUED", "STARTING", "RUNNING", "VERIFYING", "SETTLING"}
        ):
            # Legacy/recovery rows may precede receipt-bound phase publication.
            # Do not promote unproven terminal metadata. Conversely, both
            # verified process outcomes are terminal independently of slower
            # envelope intake; SETTLING there describes result availability,
            # not a reversal of already-proven Coding/Verification completion.
            output["status"] = "settling"
            output["canonical_status"] = "starting"
            output["completion_classification"] = "pending"
        output["terminal_truth"] = terminal_truth_out(
            run,
            output["lifecycle"],
            (
                result_envelope_out(result_envelope, advanced=True)
                if result_envelope is not None
                else None
            ),
            session=session,
        )
    if include_raw:
        output.update(
            {
                "source_repo": run.source_repo,
                "worktree_path": run.worktree_path,
                "approved_instruction_digest": run.approved_instruction_digest,
                "start_request_digest": run.start_request_digest,
                "start_idempotency_digest": run.start_idempotency_digest,
                "stdout": run.stdout,
                "stderr": run.stderr,
                # Sanitized, bounded Codex JSONL is intentionally exposed only
                # on the authenticated raw/Advanced representation. It never
                # enters the default structured Result or Tests collection.
                "coding_jsonl_diagnostics": run.stdout,
                "output_truncated": run.output_truncated,
                "verification_stdout": run.verification_stdout,
                "verification_stderr": run.verification_stderr,
                "verification_jsonl_diagnostics": run.verification_stdout,
            }
        )
    # Apply defaults only after the canonical classifications above. Empty
    # collections mean no evidence is available yet, never a clean workspace.
    output["result"] = run_result_projection(
        run, result,
        coding_state=output.get("terminal_truth", {}).get("coding", {}).get("status"),
    )
    return output


def owner_acceptance_out(session: Session, acceptance: OwnerAcceptanceSession) -> dict[str, Any]:
    items = session.scalars(
        select(OwnerAcceptanceItem)
        .where(OwnerAcceptanceItem.session_id == acceptance.id)
        .order_by(OwnerAcceptanceItem.ordinal)
    ).all()
    required_complete = all(item.status == "pass" for item in items if item.required)
    result_delivery_review = bool(
        acceptance.result_envelope_id is not None
        or acceptance.delivery_candidate_id is not None
        or acceptance.result_digest
        or acceptance.candidate_digest
    )
    review_state = {
        "owner_review": "pending",
        "accepted": "accepted_for_delivery",
        "rejected": "rejected",
    }.get(acceptance.status, acceptance.status)
    exact_delivery_binding = bool(
        acceptance.owner_id is not None
        and acceptance.result_envelope_id is not None
        and acceptance.result_envelope_public_id
        and re.fullmatch(r"[0-9a-f]{64}", acceptance.result_digest or "")
        and acceptance.delivery_candidate_id is not None
        and acceptance.candidate_public_id
        and acceptance.candidate_version is not None
        and re.fullmatch(r"[0-9a-f]{64}", acceptance.candidate_digest or "")
    )
    return {
        "id": acceptance.id,
        "task_id": acceptance.task_id,
        "codex_run_id": acceptance.codex_run_id,
        "status": acceptance.status,
        "review_state": review_state,
        "review_kind": (
            "result_delivery" if result_delivery_review else "legacy_owner_acceptance"
        ),
        "result_id": acceptance.result_envelope_public_id or None,
        "candidate_id": acceptance.candidate_public_id or None,
        "candidate_version": acceptance.candidate_version,
        "owner_note": acceptance.owner_note,
        "compact_sync_result": acceptance.compact_sync_result,
        "can_accept": (
            acceptance.status == "owner_review" and exact_delivery_binding
            if result_delivery_review
            else bool(items) and required_complete
        ),
        "can_reject": acceptance.status == "owner_review",
        "items": [
            {
                "id": item.id,
                "key": item.key,
                "label": item.label,
                "inspect_target": item.inspect_target,
                "ui_path": item.ui_path,
                "pass_standard": item.pass_standard,
                "required": item.required,
                "status": item.status,
                "note": item.note,
            }
            for item in items
        ],
        "created_at": iso(acceptance.created_at),
        "updated_at": iso(acceptance.updated_at),
        "decided_at": iso(acceptance.decided_at),
        "advanced": {
            "review_policy_version": acceptance.review_policy_version,
            "decision_version": acceptance.decision_version,
            "decision_digest": acceptance.decision_digest or None,
            "result_digest": acceptance.result_digest or None,
            "candidate_digest": acceptance.candidate_digest or None,
            "approved_instruction_digest": (
                acceptance.approved_instruction_digest or None
            ),
            "task_version": acceptance.result_task_version,
            "pack_id": acceptance.result_pack_id,
            "pack_version": acceptance.result_pack_version,
        }
        if result_delivery_review
        else {},
    }


def audit_out(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "actor_user_id": event.actor_user_id,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "request_id": event.request_id,
        "details": event.details,
        "created_at": iso(event.created_at),
    }


def terminal_truth_out(
    run: CodexRun,
    lifecycle: dict[str, Any],
    envelope: dict[str, Any] | None,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    """Project one owner-safe terminal truth record for every Run surface."""
    state = str(lifecycle.get("state") or run.status or "queued").lower()
    receipt_timeout = bool(
        session is not None and coding_timeout_receipt_persisted(session, run)
    )
    if receipt_timeout:
        # Optional Result/workspace settlement cannot hide an exact exited
        # Coding timeout and its atomically persisted invocation evidence.
        state = "timed_out"
    raw_integrity = str(
        (envelope or {}).get("integrity_state")
        or lifecycle.get("result_integrity")
        or "pending"
    ).lower()
    integrity = (
        "verified"
        if raw_integrity == "verified"
        else "invalid"
        if raw_integrity in {"blocked", "invalid", "mismatch"}
        else "unverified"
    )
    envelope_verified = integrity == "verified" and bool(envelope)
    structured = decoded_object(run.structured_result)
    structured_coding_process = structured.get("coding_process")
    coding_process = (
        structured_coding_process
        if isinstance(structured_coding_process, dict)
        else {}
    )
    raw_coding_status = str(coding_process.get("status") or "").lower()
    reported_coding_exit_code = coding_process.get("exit_code")
    effective_coding_exit_code = (
        reported_coding_exit_code
        if type(reported_coding_exit_code) is int
        else run.exit_code
    )
    coding_exit_conflict = bool(
        type(reported_coding_exit_code) is int
        and type(run.exit_code) is int
        and reported_coding_exit_code != run.exit_code
    )
    coding_cancelled = bool(
        coding_process.get("cancelled") is True or raw_coding_status == "cancelled"
    )
    coding_timed_out = bool(
        receipt_timeout
        or coding_process.get("timed_out") is True
        or raw_coding_status == "timed_out"
    )
    coding_interrupted = bool(
        coding_process.get("runtime_interrupted") is True
        or raw_coding_status in {"interrupted", "process_lost"}
    )
    if not (run.process_spawned or run.started_at or run.exit_code is not None):
        coding_status = "pending"
    elif coding_cancelled:
        coding_status = "cancelled"
    elif coding_timed_out:
        coding_status = "timed_out"
    elif coding_interrupted:
        coding_status = "interrupted"
    elif raw_coding_status in {
        "failed",
        "error",
        "blocked",
        "integrity_blocked",
    } or coding_exit_conflict or (
        type(effective_coding_exit_code) is int
        and effective_coding_exit_code != 0
    ):
        coding_status = "failed"
    elif effective_coding_exit_code == 0:
        coding_status = "succeeded"
    elif state in {"queued", "starting"}:
        coding_status = state
    elif state in {"running", "coding", "verifying", "settling", "result_pending"}:
        coding_status = "running"
    elif state == "cancelled":
        coding_status = "cancelled"
    elif state == "timed_out":
        coding_status = "timed_out"
    elif state in {"interrupted", "process_lost"}:
        coding_status = "interrupted"
    else:
        coding_status = "failed"
    # The current immutable Pack architecture represents a required
    # independent phase with a persisted Verification assignment. Runs with
    # no such binding project Verification as not_required.
    verification_required = run.verification_assignment_id is not None
    verification_started = bool(
        lifecycle.get("verification_started")
        or getattr(run, "verification_process_spawned", False)
    )
    if not verification_required and not verification_started:
        verification_status = "not_required"
    elif not verification_started:
        verification_status = "unavailable" if state in {"completed", "failed", "cancelled", "timed_out", "interrupted", "result_available"} or str(run.status or "").lower() in {"completed", "failed", "cancelled", "timed_out", "blocked"} else "pending"
    else:
        structured_verification = structured.get("verification_verdict") or structured.get("verification_result") or {}
        structured_verification_process = structured.get("verification_process")
        envelope_verdict = (
            (envelope or {}).get("verification_result", {}).get("verdict")
            if envelope_verified
            else ""
        )
        raw_verdict = str(envelope_verdict or (structured_verification.get("verdict") if isinstance(structured_verification, dict) else structured_verification) or "").lower()
        raw_verification = raw_verdict if raw_verdict in {"pass", "passed", "verified", "succeeded", "success", "fail", "failed"} else str((structured_verification_process.get("status") if isinstance(structured_verification_process, dict) else "") or run.verification_status or raw_verdict).lower()
        verification_status = "passed" if raw_verification in {"pass", "passed", "verified", "succeeded", "success"} else "failed" if raw_verification in {"fail", "failed", "blocked", "integrity_blocked"} else "running" if raw_verification in {"running", "in_progress"} else "cancelled" if raw_verification == "cancelled" else "timed_out" if raw_verification == "timed_out" else "interrupted" if raw_verification in {"interrupted", "process_lost"} or state in {"interrupted", "process_lost"} else "unavailable"
    structured_verification_process = structured.get("verification_process")
    verification_reason = str(
        (
            structured_verification_process.get("failure")
            if isinstance(structured_verification_process, dict)
            else ""
        )
        or getattr(run, "verification_summary", None)
        or (
            "Independent Verification was not required."
            if verification_status == "not_required"
            else "Independent Verification has not produced evidence."
        )
    )
    # Availability belongs to the sealed envelope, not the legacy aggregate
    # Run label. A verified envelope remains reviewable even when a separate
    # phase or workspace dimension needs review.
    result_available = envelope_verified
    result_state = "available" if result_available else "incomplete" if envelope is not None else "unavailable"
    workspace = ((envelope or {}).get("workspace_evidence") or (envelope or {}).get("advanced", {}).get("workspace_evidence") or structured.get("workspace_evidence") or {})
    workspace_evidence_status = (
        str(workspace.get("status") or "").lower()
        if isinstance(workspace, dict)
        else ""
    )
    workspace_evidence_available = bool(
        isinstance(workspace, dict)
        and workspace
        and workspace_evidence_status
        not in {"unavailable", "incomplete", "missing", "not_captured"}
    )
    attribution = workspace.get("attribution") if isinstance(workspace, dict) else {}
    run_produced = (
        attribution.get("run_produced", [])
        if isinstance(attribution, dict)
        else []
    )
    workspace_conflict = bool(
        isinstance(workspace, dict)
        and (
            workspace_evidence_status == "conflict"
            or workspace.get("boundary_violations")
            or workspace.get("unexpected_files")
            or (
                isinstance(attribution, dict)
                and attribution.get("origin_unproven")
            )
        )
    )
    workspace_conflict_reasons = (
        [str(item) for item in workspace.get("boundary_violations", [])]
        if isinstance(workspace, dict)
        and isinstance(workspace.get("boundary_violations"), list)
        else []
    )
    if isinstance(workspace, dict):
        unexpected = workspace.get("unexpected_files")
        if isinstance(unexpected, list) and unexpected:
            workspace_conflict_reasons.append(
                "Unexpected workspace paths: " + ", ".join(str(item) for item in unexpected)
            )
        if isinstance(attribution, dict) and attribution.get("origin_unproven"):
            workspace_conflict_reasons.append(
                "The Run could not prove that all captured changes originated from this execution."
            )
        if workspace_evidence_status == "conflict" and not workspace_conflict_reasons:
            workspace_conflict_reasons.append(
                str(
                    workspace.get("conflict_reason")
                    or workspace.get("availability_reason")
                    or "Persisted workspace evidence is classified as conflict."
                )
            )
    workspace_state = (
        "conflict"
        if workspace_conflict
        else "captured"
        if workspace_evidence_available
        and (run_produced or structured.get("changed_files"))
        else "no_change"
        if workspace_evidence_available
        else "incomplete"
    )
    active_lifecycle_states = {
        "queued",
        "starting",
        "running",
        "coding",
        "verifying",
        "verification_eligible",
        "settling",
        "result_pending",
    }
    if state in active_lifecycle_states:
        # The process row can become terminal just before the lifecycle
        # transaction publishes its receipt-bound attempt, envelope, and
        # snapshot. During that narrow settlement window the authoritative
        # lifecycle remains active; do not let partial terminal dimensions
        # relabel the primary Owner status as Needs Review.
        primary_status = state
    elif coding_status in {"failed", "cancelled", "timed_out", "interrupted"}:
        primary_status = coding_status
    elif coding_status == "succeeded" and (
        verification_status
        in {"unavailable", "failed", "cancelled", "timed_out", "interrupted"}
        or workspace_state in {"conflict", "incomplete"}
    ):
        primary_status = "needs_review"
    elif result_available:
        primary_status = "result_available"
    else:
        primary_status = state
    return {
        "primary_status": primary_status,
        "primary_label": "Needs Review" if primary_status == "needs_review" else "Result Available" if primary_status == "result_available" else primary_status.replace("_", " ").title(),
        "terminal_state": state,
        "coding": {"status": coding_status, "exit_code": run.exit_code},
        "verification": {
            "status": verification_status,
            "required": verification_required,
            "started": verification_started,
            "reason": verification_reason,
        },
        "result": {
            "state": result_state,
            "available": result_available,
            "integrity": integrity,
            "envelope_present": envelope is not None,
        },
        "workspace": {
            "state": workspace_state,
            "conflict_reasons": workspace_conflict_reasons,
            "terminal_evidence_observed": bool(lifecycle.get("terminal_evidence_observed")),
            "process_exited": bool(lifecycle.get("process_exited")),
        },
        "owner_review": {
            "status": (
                "reviewed"
                if getattr(run, "acceptance_session", None) is not None
                and str(run.acceptance_session.status or "").lower()
                not in {"", "pending", "owner_review"}
                else "pending"
            ),
            "next_action": lifecycle.get("next_action") or "Review the persisted Run evidence.",
            "summary": (
                (
                    "Workspace evidence conflict: "
                    + ", ".join(workspace_conflict_reasons)
                )
                if workspace_conflict_reasons
                else verification_reason
                if verification_status
                in {"failed", "unavailable", "cancelled", "timed_out", "interrupted"}
                else "Run Result is available for Owner review."
                if result_available
                else "Verification has not started; review the persisted Run evidence."
                if not verification_started and state in {"completed", "failed"}
                else "Review the persisted Run evidence."
            ),
        },
    }


def acceptance_out(
    check: AcceptanceCheck | None,
    run: TaskRun | None,
    events: list[AuditEvent],
    record_count: int = 0,
) -> dict[str, Any]:
    if not check:
        return {
            "id": None,
            "run_id": None,
            "decision": "pending",
            "display_decision": "Waiting for execution",
            "automatic": False,
            "engine": None,
            "checks": [],
            "reason": "Run Compact Sync to create deterministic acceptance evidence.",
            "audit_created": False,
            "audit_events": [],
            "record_count": record_count,
            "created_at": None,
        }
    evidence = parse_acceptance(check.reason)
    automatic = bool(run and run.action == "compact_sync")
    return {
        "id": check.id,
        "run_id": check.run_id,
        "decision": check.status,
        "display_decision": (
            "Accepted automatically"
            if check.status == "accepted" and automatic
            else check.status.replace("_", " ").title()
        ),
        "automatic": automatic,
        "engine": evidence["engine"],
        "checks": evidence["checks"],
        "reason": evidence["reason"],
        "audit_created": bool(events),
        "audit_events": [audit_out(item) for item in events],
        "record_count": record_count,
        "created_at": iso(check.created_at),
    }


def error_response(status_code: int, code: str, message: str, request_id: str | None, details: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id, "details": details}},
        headers={"X-Request-ID": request_id or ""},
    )


def auth_error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: dict[str, str] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {"code": code, "message": message}
    if fields is not None:
        content["fields"] = fields
    return JSONResponse(status_code=status_code, content=content)


def auth_validation_fields(exc: RequestValidationError) -> dict[str, str]:
    """Convert framework validation into stable product fields without echoing input."""
    fields: dict[str, str] = {}
    for item in exc.errors():
        location = item.get("loc", ())
        field = location[-1] if location else None
        error_type = item.get("type", "")
        context = item.get("ctx") or {}
        submitted = item.get("input")
        if field == "username":
            fields.setdefault(
                "username",
                "Use 80 characters or fewer."
                if error_type == "string_too_long"
                else "Enter a username.",
            )
        elif field == "password":
            if error_type == "string_too_long":
                message = "Use 200 characters or fewer."
            elif (
                error_type == "string_too_short"
                and context.get("min_length", 1) >= 8
                and submitted not in ("", None)
            ):
                message = "Use at least 8 characters."
            elif (
                error_type == "string_too_short"
                or error_type in {"missing", "string_type"}
                or submitted in ("", None)
            ):
                message = "Enter a password."
            else:
                message = "Enter a valid password."
            fields.setdefault("password", message)
        else:
            fields.setdefault("request", "Enter a valid request.")
    return fields or {"request": "Enter a valid request."}


def validation_error_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Keep validation evidence useful without echoing request values such as passwords."""
    return [
        {
            "type": item.get("type"),
            "loc": list(item.get("loc", ())),
            "msg": item.get("msg"),
        }
        for item in exc.errors()
    ]


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    initialize_database(engine)
    factory = make_session_factory(engine)
    with factory() as recovery_session:
        reconcile_incomplete_apply_sessions(
            recovery_session,
            source_repo=settings.source_repo,
        )
    codex_manager = CodexExecutionManager(factory, settings)
    codex_manager.sync_local_model_registry()
    codex_manager.recover_interrupted_runs()
    result_intake_monitor = ResultIntakeMonitor(
        factory,
        poll_seconds=min(1.0, float(settings.scheduler_poll_seconds)),
        on_recovery_needed=codex_manager.resume_persisted_execution,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        result_intake_monitor.start()
        if start_scheduler:
            await app.state.runtime_scheduler.start()
        try:
            yield
        finally:
            await app.state.runtime_scheduler.stop()
            codex_manager.shutdown()
            # Stop and join the background intake loop before the final
            # synchronous pass. Running both reconcilers during teardown can
            # invert the lifecycle and SQLite writer locks.
            result_intake_monitor.shutdown()
            try:
                result_intake_monitor.reconcile_now()
            except Exception as exc:
                logger.warning(
                    "Final Codex result reconciliation deferred type=%s",
                    type(exc).__name__,
                )
            finally:
                # TestClient/app disposal is also the database-handle boundary;
                # do not retain pooled SQLite connections across app instances.
                engine.dispose()

    app = FastAPI(title="TWOS 1.0 Runtime", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.runtime_scheduler = RuntimeScheduler(factory, settings.scheduler_poll_seconds)
    app.state.codex_manager = codex_manager
    app.state.result_intake_monitor = result_intake_monitor

    if settings.static_cockpit_dir.exists():
        app.mount("/static_cockpit", StaticFiles(directory=settings.static_cockpit_dir), name="static_cockpit")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Callable):
        # Authentication audits and diagnostics must never persist caller-controlled
        # header material. Generate the correlation ID inside TWOS for every request.
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        if request.url.path == "/static_cockpit/vol12_static_mvp/twos_command_center.html":
            response = RedirectResponse("/twos", status_code=307)
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "Unhandled request failure type=%s request_id=%s",
                type(exc).__name__,
                request_id,
            )
            if request.url.path.startswith("/api/auth/"):
                return auth_error_response(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE)
            return error_response(500, "internal_error", "Request could not be completed.", request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AuthAPIError)
    async def auth_api_exception_handler(request: Request, exc: AuthAPIError):
        return auth_error_response(
            exc.status_code,
            exc.code,
            exc.message,
            fields=exc.fields,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if isinstance(exc.detail, str):
            message = exc.detail
        elif isinstance(exc.detail, dict):
            primary = exc.detail.get("primary_blocker")
            message = str(
                exc.detail.get("message")
                or (primary.get("message") if isinstance(primary, dict) else "")
                or "Request failed."
            )
        else:
            message = "Request failed."
        return error_response(
            exc.status_code,
            "http_error",
            message,
            getattr(request.state, "request_id", None),
            exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if request.url.path in AUTH_REQUEST_PATHS:
            return auth_error_response(
                400,
                "VALIDATION_ERROR",
                AUTH_VALIDATION_MESSAGE,
                fields=auth_validation_fields(exc),
            )
        return error_response(
            422,
            "validation_error",
            "Check the submitted fields.",
            getattr(request.state, "request_id", None),
            validation_error_details(exc),
        )

    def get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def current_user(request: Request, session: Session = Depends(get_db)) -> User:
        raw_token = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            raw_token = auth.split(" ", 1)[1].strip()
        raw_token = raw_token or request.cookies.get(SESSION_COOKIE)
        if not raw_token:
            raise HTTPException(status_code=401, detail="Authentication required.")
        user = user_for_token(session, raw_token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return user

    def audit(session: Session, request: Request, action: str, entity_type: str, entity_id: int | None, details: str, user: User | None = None) -> None:
        session.add(
            AuditEvent(
                actor_user_id=user.id if user else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                request_id=getattr(request.state, "request_id", None),
                details=details,
            )
        )

    def record_auth_failure(session: Session, request: Request, reason: AuthFailureReason) -> None:
        logger.warning(
            "Owner authentication failed reason=%s request_id=%s",
            reason.value,
            getattr(request.state, "request_id", None),
        )
        session.rollback()
        audit(
            session,
            request,
            "login_failed",
            "authentication",
            None,
            f"reason={reason.value}",
        )
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.error(
                "Owner authentication audit failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )

    def commit_auth_transaction(
        session: Session,
        request: Request,
        operation: str,
    ) -> None:
        try:
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "Owner authentication transaction failed operation=%s reason=database_read_failed request_id=%s",
                operation,
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc

    def session_user(request: Request, session: Session) -> User | None:
        raw_token = request.cookies.get(SESSION_COOKIE)
        if not raw_token:
            return None
        return user_for_token(session, raw_token)

    def set_session_cookie(response: Response, request: Request, raw_token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            raw_token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            max_age=settings.session_ttl_seconds,
            path="/",
        )

    def clear_session_cookie(response: Response, request: Request) -> None:
        response.delete_cookie(
            SESSION_COOKIE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )

    def perform_signup(
        payload: SignupIn | OwnerInitIn,
        request: Request,
        session: Session,
        *,
        audit_action: str = "signup",
        audit_details: str = "Account created.",
    ) -> tuple[User, str]:
        try:
            # TWOS is a single-account SQLite product. Acquire the write lock
            # before checking existence so concurrent Sign up requests serialize
            # and the losing request observes the committed account as a 409.
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            if session.scalar(select(User).order_by(User.id)) is not None:
                raise AuthAPIError(409, "ACCOUNT_EXISTS", AUTH_ACCOUNT_EXISTS_MESSAGE)
            user = create_owner(session, payload.username, payload.password)
            authenticated_user, raw_token, token = authenticate(
                session,
                payload.username,
                payload.password,
                settings.session_ttl_seconds,
            )
            audit(
                session,
                request,
                audit_action,
                "user",
                user.id,
                audit_details,
                authenticated_user,
            )
            audit(
                session,
                request,
                "login",
                "session",
                token.id,
                "Account session created.",
                authenticated_user,
            )
            commit_auth_transaction(session, request, "signup")
        except AuthAPIError:
            raise
        except ValueError as exc:
            session.rollback()
            try:
                if session.scalar(select(User).order_by(User.id)) is not None:
                    raise AuthAPIError(409, "ACCOUNT_EXISTS", AUTH_ACCOUNT_EXISTS_MESSAGE) from exc
            except SQLAlchemyError as lookup_exc:
                session.rollback()
                logger.error(
                    "Account signup conflict check failed reason=database_read_failed request_id=%s",
                    getattr(request.state, "request_id", None),
                )
                raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from lookup_exc
            logger.error(
                "Account signup failed reason=credential_state_invalid request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        except AuthenticationError as exc:
            session.rollback()
            logger.error(
                "Account signup failed reason=credential_state_invalid request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "Account signup failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        return authenticated_user, raw_token

    def perform_login(payload: LoginIn, request: Request, session: Session) -> tuple[User, str]:
        try:
            user, raw_token, token = authenticate(
                session,
                payload.username,
                payload.password,
                settings.session_ttl_seconds,
            )
        except AuthenticationError as exc:
            record_auth_failure(session, request, exc.reason)
            raise AuthAPIError(401, "INVALID_CREDENTIALS", AUTH_CREDENTIAL_MESSAGE) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "Account authentication failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        audit(session, request, "login", "session", token.id, "Account logged in.", user)
        commit_auth_transaction(session, request, "login")
        return user, raw_token

    def schedule_run_count(session: Session, schedule_id: int) -> int:
        return int(
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "schedule_run_completed",
                    AuditEvent.entity_type == "schedule",
                    AuditEvent.entity_id == schedule_id,
                )
            )
            or 0
        )

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse("/twos", status_code=307)

    @app.get("/twos")
    def twos_ui() -> FileResponse:
        if not settings.ui_path.exists():
            raise HTTPException(status_code=404, detail="TWOS UI entry not found.")
        return FileResponse(
            settings.ui_path,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    def health(session: Session = Depends(get_db)) -> dict[str, Any]:
        session.execute(text("select 1")).scalar_one()
        return {"status": "healthy", "database": "ok", "version": __version__}

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        return {"name": "TWOS Runtime", "version": __version__, "runtime": "local-fastapi-sqlite"}

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "lifecycle_states": LIFECYCLE_STATES,
            "action_policies": ACTION_POLICIES,
            "connector_statuses": CONNECTOR_STATUSES,
            "safe_worker_actions": ["compact_sync"],
            "hard_denials": ["live_trade", "live_bet", "broker_order", "betting_order"],
        }

    @app.get("/api/auth/session")
    def auth_session(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
        try:
            user = session_user(request, session)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "Account session lookup failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        return {
            "authenticated": user is not None,
            "user": {"username": normalize_username(user.username)} if user else None,
        }

    @app.post("/api/auth/signup", status_code=201)
    def signup(
        payload: SignupIn,
        response: Response,
        request: Request,
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user, raw_token = perform_signup(payload, request, session)
        set_session_cookie(response, request, raw_token)
        return {"authenticated": True, "user": {"username": user.username}}

    @app.get("/api/auth/status")
    def auth_status(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
        try:
            owner = session.scalar(select(User).order_by(User.id))
            issue = owner_record_issue(owner)
            valid_owner = owner if owner is not None and issue is None else None
            raw_token = request.cookies.get(SESSION_COOKIE)
            authenticated = user_for_token(session, raw_token) if raw_token and valid_owner else None
        except SQLAlchemyError as exc:
            logger.error(
                "Owner authentication status failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise HTTPException(status_code=503, detail="Authentication status is temporarily unavailable.") from exc
        recovery_required = owner is not None and valid_owner is None
        return {
            "owner_initialized": valid_owner is not None,
            "recovery_required": recovery_required,
            "authenticated": authenticated is not None,
            "mode": (
                "setup"
                if owner is None
                else "recovery_required"
                if recovery_required
                else "authenticated"
                if authenticated
                else "login"
            ),
            "owner": (
                {"id": authenticated.id, "username": authenticated.username}
                if authenticated
                else {"username": normalize_username(valid_owner.username)} if valid_owner else None
            ),
        }

    @app.post("/api/auth/init")
    def init_owner(
        payload: OwnerInitIn,
        response: Response,
        request: Request,
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        """Temporary compatibility route; canonical clients use /api/auth/signup."""
        user, raw_token = perform_signup(
            payload,
            request,
            session,
            audit_action="owner_initialized",
            audit_details="Account initialized through compatibility API.",
        )
        set_session_cookie(response, request, raw_token)
        return {"owner": {"id": user.id, "username": user.username}}

    @app.post("/api/auth/login")
    def login(
        payload: LoginIn,
        response: Response,
        request: Request,
        session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user, raw_token = perform_login(payload, request, session)
        set_session_cookie(response, request, raw_token)
        return {"authenticated": True, "user": {"username": user.username}}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, session: Session = Depends(get_db)) -> dict[str, Any]:
        authorization = request.headers.get("authorization", "")
        bearer_token = (
            authorization.split(" ", 1)[1].strip()
            if authorization.lower().startswith("bearer ")
            else None
        )
        raw_token = request.cookies.get(SESSION_COOKIE) or bearer_token
        try:
            user = user_for_token(session, raw_token) if raw_token else None
            if raw_token:
                revoke_token(session, raw_token)
                if user is not None:
                    audit(session, request, "logout", "user", user.id, "Account logged out.", user)
                commit_auth_transaction(session, request, "logout")
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error(
                "Account logout failed reason=database_read_failed request_id=%s",
                getattr(request.state, "request_id", None),
            )
            raise AuthAPIError(500, "AUTH_SERVICE_ERROR", AUTH_SERVICE_MESSAGE) from exc
        clear_session_cookie(response, request)
        return {"success": True}

    @app.get("/api/auth/me")
    def me(user: User = Depends(current_user)) -> dict[str, Any]:
        return {"owner": {"id": user.id, "username": user.username}}

    @app.get("/api/projects")
    def list_projects(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [project_out(item) for item in session.scalars(select(Project).order_by(Project.id)).all()]

    @app.post("/api/projects")
    def create_project(payload: ProjectIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        if session.scalar(select(Project).where(Project.key == payload.key)):
            raise HTTPException(status_code=409, detail="Project key already exists.")
        project = Project(key=payload.key, name=payload.name, status=payload.status)
        session.add(project)
        session.flush()
        audit(session, request, "project_created", "project", project.id, project.key, user)
        return project_out(project)

    @app.get("/api/tasks")
    def list_tasks(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [task_out(item) for item in session.scalars(select(Task).order_by(Task.id)).all()]

    @app.post("/api/tasks")
    def create_task(payload: TaskIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        if not session.get(Project, payload.project_id):
            raise HTTPException(status_code=404, detail="Project not found.")
        development_task = payload.development_task if payload.development_task is not None else payload.title
        if development_task is None or not development_task.strip():
            raise HTTPException(status_code=400, detail="Development task is required.")
        effective_workflow = payload.workflow_type
        if "development_task" in payload.model_fields_set and "workflow_type" not in payload.model_fields_set:
            effective_workflow = "product_development"
        try:
            action = persisted_action(payload.action, payload.task_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source_state: dict[str, object] = {}
        if effective_workflow == "product_development":
            try:
                source_state = git_source_state(
                    settings.source_repo,
                    hardened_read_only=True,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        def owner_value(value: str, default: str) -> tuple[str, str]:
            return (value, "owner-edited") if value.strip() else (default, "derived")

        objective, objective_provenance = owner_value(payload.objective, DERIVED_OBJECTIVE)
        source_context, source_context_provenance = owner_value(
            payload.source_sync_summary, DERIVED_SOURCE_CONTEXT
        )
        required_output, required_output_provenance = owner_value(
            payload.required_output, DERIVED_REQUIRED_OUTPUT
        )
        acceptance_target, acceptance_target_provenance = owner_value(
            payload.acceptance_target, DERIVED_ACCEPTANCE_TARGET
        )
        implementation_scope, implementation_scope_provenance = owner_value(
            payload.implementation_scope, DERIVED_IMPLEMENTATION_SCOPE
        )
        display_title = payload.title.strip() if payload.title and payload.title.strip() else next(
            (line.strip() for line in development_task.splitlines() if line.strip()),
            "Development task",
        )[:240]
        task = Task(
            project_id=payload.project_id,
            title=display_title,
            development_task=development_task,
            task_type=action,
            source_sync_summary=source_context,
            required_output=required_output,
            boundary_risk=payload.boundary_risk,
            workflow_type=effective_workflow,
            objective=objective,
            implementation_scope=implementation_scope,
            forbidden_scope=payload.forbidden_scope or DERIVED_FORBIDDEN_SCOPE,
            acceptance_target=acceptance_target,
            objective_provenance=objective_provenance,
            source_context_provenance=source_context_provenance,
            required_output_provenance=required_output_provenance,
            acceptance_target_provenance=acceptance_target_provenance,
            implementation_scope_provenance=implementation_scope_provenance,
            repository_identity=str(source_state.get("identity", "")),
            source_baseline_commit=str(source_state.get("commit", "")),
            status="draft" if effective_workflow == "product_development" else "queued",
        )
        session.add(task)
        session.flush()
        audit(session, request, "task_created", "task", task.id, task.title, user)
        return task_out(task)

    @app.patch("/api/tasks/{task_id}")
    def patch_task(task_id: int, payload: TaskPatchIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        was_product_development = task.workflow_type == "product_development"
        data = payload.model_dump(exclude_unset=True)
        updated_fields = list(data.keys())
        pack_sensitive_fields = {
            "project_id",
            "development_task",
            "title",
            "task_type",
            "source_sync_summary",
            "required_output",
            "boundary_risk",
            "workflow_type",
            "objective",
            "implementation_scope",
            "forbidden_scope",
            "acceptance_target",
        }
        if "action" in data:
            try:
                data["task_type"] = persisted_action(data.pop("action"), None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if "status" in data and data["status"] not in LIFECYCLE_STATES:
            raise HTTPException(status_code=400, detail="Unsupported task status.")
        material_changed = False
        if "project_id" in data:
            project_id = data.pop("project_id")
            project = session.get(Project, project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found.")
            material_changed = material_changed or task.project_id != project_id
            task.project = project
        derived_fields = {
            "objective": ("objective_provenance", DERIVED_OBJECTIVE),
            "source_sync_summary": ("source_context_provenance", DERIVED_SOURCE_CONTEXT),
            "required_output": ("required_output_provenance", DERIVED_REQUIRED_OUTPUT),
            "acceptance_target": ("acceptance_target_provenance", DERIVED_ACCEPTANCE_TARGET),
            "implementation_scope": ("implementation_scope_provenance", DERIVED_IMPLEMENTATION_SCOPE),
        }
        if "development_task" in data:
            submitted_task = data["development_task"]
            if submitted_task is None or not submitted_task.strip():
                raise HTTPException(status_code=400, detail="Development task is required.")
        for key, value in data.items():
            if key in pack_sensitive_fields and getattr(task, key) != value:
                material_changed = True
            if key in derived_fields:
                provenance_field, default = derived_fields[key]
                if value is None or not str(value).strip():
                    value = default
                    setattr(task, provenance_field, "derived")
                elif getattr(task, key) != value:
                    setattr(task, provenance_field, "owner-edited")
            setattr(task, key, value)
        if task.workflow_type == "product_development":
            if not task.source_baseline_commit:
                source_state = git_source_state(
                    settings.source_repo,
                    hardened_read_only=True,
                )
                task.repository_identity = str(source_state["identity"])
                task.source_baseline_commit = str(source_state["commit"])
        if material_changed:
            task.task_version += 1
        if material_changed and (was_product_development or task.workflow_type == "product_development"):
            invalidated = invalidate_approved_packs(session, task.id)
            if invalidated:
                task.status = "planned"
                audit(
                    session,
                    request,
                    "codex_pack_approval_invalidated",
                    "task",
                    task.id,
                    f"invalidated_packs={invalidated}; task context changed",
                    user,
                )
        audit(session, request, "task_updated", "task", task.id, ",".join(updated_fields), user)
        return task_out(task)

    @app.get("/api/ai/capabilities")
    def ai_capabilities(
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> list[dict[str, Any]]:
        seed_ai_registry(session)
        session.flush()
        capabilities = session.scalars(select(AICapability).order_by(AICapability.id)).all()
        return [capability_out(item) for item in capabilities]

    @app.get("/api/models")
    def models(
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> list[dict[str, Any]]:
        seed_ai_registry(session)
        session.flush()
        model_rows = [
            item
            for item in session.scalars(
                select(AIModel).order_by(AIModel.provider_id, AIModel.id)
            ).all()
            if configured_model_record(item)
        ]
        return [model_out(item) for item in model_rows]

    @app.post("/api/ai/team-compose")
    def compose_ai_team(
        payload: TeamComposeIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, payload.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        prior_assignments = latest_model_assignments(session, task.id)
        prior_snapshot_hash = prior_assignments[0].routing_snapshot_hash if prior_assignments else None
        try:
            plan = compose_team(
                session,
                task,
                risk_level=payload.risk_level,
                urgency=payload.urgency,
                capability_override=payload.capability_override,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit(
            session,
            request,
            "ai_team_composed",
            "ai_team_plan",
            plan.id,
            f"task={task.id}; capabilities={plan.required_capabilities}",
            user,
        )
        plan_output = team_plan_out(session, plan)
        routes: list[RoutingDecision] = []
        for capability_name in plan_output["required_capabilities"]:
            capability = session.scalar(
                select(AICapability).where(AICapability.name == capability_name, AICapability.enabled == True)  # noqa: E712
            )
            if not capability:
                raise HTTPException(status_code=409, detail=f"Composed capability is unavailable: {capability_name}.")
            decision = route_capability(
                session,
                task,
                capability,
                team_plan_id=plan.id,
                requested_capabilities=plan_output["required_capabilities"],
                urgency=payload.urgency,
                cost_sensitivity="balanced",
                latency_sensitivity="high" if payload.urgency == "high" else "balanced",
            )
            routes.append(decision)
            audit(
                session,
                request,
                "ai_route_decided",
                "routing_decision",
                decision.id,
                f"capability={capability.name}; status={decision.status}; automatic=true",
                user,
            )
        assignments = recompose_model_assignments(
            session,
            task,
            routes,
            team_plan=plan,
            task_version=task.task_version,
            routing_source="routing_decision",
        )
        current_snapshot_hash = assignments[0].routing_snapshot_hash if assignments else None
        routing_changed = prior_snapshot_hash != current_snapshot_hash
        invalidated = (
            invalidate_approved_packs(session, task.id)
            if task.workflow_type == "product_development" and routing_changed
            else 0
        )
        plan_output = team_plan_out(session, plan)
        plan_output["routes"] = [routing_out(item) for item in routes]
        plan_output["routing_summary"] = routing_summary_out(plan, routes)
        plan_output["assignments"] = [model_assignment_out(item) for item in assignments]
        if task.workflow_type == "product_development":
            task.status = "planned"
            if invalidated:
                audit(
                    session,
                    request,
                    "codex_pack_approval_invalidated",
                    "task",
                    task.id,
                    f"invalidated_packs={invalidated}; model-routing snapshot changed",
                    user,
                )
        return plan_output

    @app.post("/api/ai/route")
    def route_ai_capability(
        payload: RouteIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, payload.task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        capability = session.scalar(
            select(AICapability).where(AICapability.name == payload.capability, AICapability.enabled == True)  # noqa: E712
        )
        if not capability:
            raise HTTPException(status_code=404, detail="AI capability not found or disabled.")
        if payload.team_plan_id is not None:
            plan = session.get(AITeamPlan, payload.team_plan_id)
            if not plan or plan.task_id != task.id:
                raise HTTPException(status_code=400, detail="AI team plan does not belong to this task.")
        decision = route_capability(
            session,
            task,
            capability,
            team_plan_id=payload.team_plan_id,
            requested_capabilities=(
                decoded_list(plan.required_capabilities) if payload.team_plan_id is not None else [capability.name]
            ),
            urgency=payload.urgency,
            cost_sensitivity=payload.cost_sensitivity,
            latency_sensitivity=payload.latency_sensitivity,
        )
        audit(
            session,
            request,
            "ai_route_decided",
            "routing_decision",
            decision.id,
            f"capability={capability.name}; status={decision.status}",
            user,
        )
        return routing_out(decision)

    @app.get("/api/tasks/{task_id}/ai-plan")
    def latest_ai_plan(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        plan = session.scalar(
            select(AITeamPlan).where(AITeamPlan.task_id == task_id).order_by(AITeamPlan.id.desc())
        )
        if not plan:
            return {
                "task_id": task_id,
                "plan": None,
                "routes": [],
                "assignments": [],
                "routing_summary": None,
            }
        routes = session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.team_plan_id == plan.id)
            .order_by(RoutingDecision.id)
        ).all()
        assignments = latest_model_assignments(session, task_id)
        return {
            "task_id": task_id,
            "plan": team_plan_out(session, plan),
            "routes": [routing_out(item) for item in routes],
            "assignments": [model_assignment_out(item) for item in assignments],
            "routing_summary": routing_summary_out(plan, routes),
        }

    def local_codex_model(session: Session) -> AIModel | None:
        return session.scalar(
            select(AIModel)
            .where(
                AIModel.execution_adapter == "codex_cli",
                AIModel.configuration_status != "disabled",
            )
            .order_by(AIModel.updated_at.desc(), AIModel.id.desc())
        )

    def local_codex_models(session: Session) -> list[AIModel]:
        return list(
            session.scalars(
                select(AIModel)
                .where(
                    AIModel.execution_adapter == "codex_cli",
                    AIModel.configuration_status != "disabled",
                )
                .order_by(AIModel.updated_at.desc(), AIModel.id.desc())
            ).all()
        )

    def ensure_local_codex_configuration(
        session: Session,
        model_identifier: str,
        display_name: str | None = None,
    ) -> tuple[AIModel, bool]:
        provider = session.scalar(
            select(Provider).where(Provider.name == "Local Codex CLI", Provider.kind == "model")
        )
        if provider is None:
            provider = Provider(
                name="Local Codex CLI",
                kind="model",
                status="unconfigured",
                enabled=False,
                details="Local Codex CLI runtime; credentials remain in the CLI environment.",
            )
            session.add(provider)
            session.flush()
        model = session.scalar(
            select(AIModel).where(
                AIModel.provider_id == provider.id,
                AIModel.execution_adapter == "codex_cli",
                AIModel.provider_model_id == model_identifier,
            )
        )
        created = model is None
        if model is None:
            model = AIModel(
                provider_id=provider.id,
                model_name=model_identifier,
                stable_id=f"codex-cli.{hashlib.sha256(model_identifier.encode()).hexdigest()[:16]}",
                display_name=display_name or model_identifier,
                provider_model_id=model_identifier,
                execution_adapter="codex_cli",
                capability_tags='["coding","verification"]',
                status="unconfigured",
                configuration_status="configured",
                availability_status="unavailable",
                invocation_mode="real",
                evidence_status="unverified",
                evidence_source="none",
                safe_diagnostic="Check availability before assigning this target.",
                routing_priority=5,
            )
            session.add(model)
            session.flush()
        elif display_name:
            model.display_name = display_name
        model.configuration_status = "configured"
        model.invocation_mode = "real"
        return model, created

    def selected_catalog_model(model_identifier: str):
        catalog_model = codex_manager.adapter.catalog_model(model_identifier)
        if catalog_model is None:
            raise HTTPException(status_code=422, detail="No matching supported model.")
        return catalog_model

    @app.get("/api/model-catalog")
    def model_catalog(
        adapter: Literal["codex_cli"],
        capability: Literal["coding", "verification"] | None = None,
        task_id: int | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        current_assignment = None
        if task_id is not None:
            if session.get(Task, task_id) is None:
                raise HTTPException(status_code=404, detail="Task not found.")
            if capability is not None:
                current_assignment = next(
                    (
                        item
                        for item in latest_model_assignments(session, task_id)
                        if item.capability == capability
                    ),
                    None,
                )
        catalog = codex_manager.adapter.model_catalog()
        models = [
            model
            for model in catalog.models
            if capability is None or capability in model.supported_capabilities
        ]
        assigned_model = current_assignment.assigned_model if current_assignment is not None else None
        catalog_ids = {model.canonical_model_id for model in models}
        assigned_identifier = assigned_model.provider_model_id if assigned_model is not None else None
        currently_assigned_model = (
            {
                "canonical_model_id": assigned_identifier,
                "display_name": assigned_model.display_name or assigned_identifier,
                "catalog_listed": assigned_identifier in catalog_ids,
                "lifecycle_status": (
                    "current" if assigned_identifier in catalog_ids else "legacy"
                ),
                "assignment_version": current_assignment.assignment_version,
                "routing_snapshot_hash": current_assignment.routing_snapshot_hash,
            }
            if assigned_identifier
            else None
        )
        return {
            "adapter": {
                "id": "codex_cli",
                "display_name": "Local Codex CLI",
                "invocation_mode": "real",
            },
            "provider": {
                "id": "local_codex_cli",
                "display_name": "Local Codex CLI",
            },
            **catalog.as_dict(),
            "models": [model.as_dict() for model in models],
            "currently_assigned_model": currently_assigned_model,
        }

    @app.get("/api/codex/setup")
    def codex_setup(
        capability: Literal["coding", "verification"] = "coding",
        task_id: int | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        model = None
        if task_id is not None:
            task = session.get(Task, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found.")
            assignment = next(
                (
                    item
                    for item in latest_model_assignments(session, task_id)
                    if item.capability == capability
                ),
                None,
            )
            if assignment is not None:
                model = assignment.assigned_model
        else:
            model = local_codex_model(session)
        evidence = None
        if model is not None:
            evidence = session.scalar(
                select(AIModelAvailabilityEvidence)
                .where(AIModelAvailabilityEvidence.model_id == model.id)
                .order_by(AIModelAvailabilityEvidence.id.desc())
            )
        detection = codex_manager.adapter.detect()
        connectivity = connectivity_status(
            session,
            owner_id=user.id,
            model=model,
            detection=detection,
            environment=codex_child_environment(),
        )
        connectivity["configured_run_timeout_seconds"] = settings.codex_timeout_seconds
        connectivity["configured_connectivity_timeout_seconds"] = (
            settings.codex_connectivity_timeout_seconds
        )
        return {
            "target": {
                "adapter": "codex_cli",
                "display_name": "Local Codex CLI",
                "invocation_mode": "real",
                "credential_source": "Codex CLI local authentication",
                "credential_status": "managed outside TWOS",
            },
            "configuration": model_out(model),
            "configurations": [model_out(item) for item in local_codex_models(session)],
            "capability": capability,
            "availability_evidence": ({
                "configuration_identity": evidence.configuration_identity,
                "adapter": evidence.adapter,
                "invocation_mode": evidence.invocation_mode,
                "checked_at": iso(evidence.checked_at),
                "result": evidence.result,
                "evidence_type": evidence.evidence_type,
                "failure_classification": evidence.failure_classification,
                "runtime_identity": evidence.runtime_identity,
            } if evidence else None),
            "connectivity": connectivity,
        }

    @app.post("/api/codex/setup/check")
    def check_codex_setup(
        payload: CodexSetupIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        catalog_model = selected_catalog_model(payload.model_identifier)
        model, _ = ensure_local_codex_configuration(
            session,
            catalog_model.canonical_model_id,
            catalog_model.display_name,
        )
        provider = model.provider
        approved_before = set(
            session.scalars(
                select(CodexInstructionPack.id).where(
                    CodexInstructionPack.status == "approved"
                )
            ).all()
        )
        detection = codex_manager.adapter.detect()
        connectivity = connectivity_status(
            session,
            owner_id=user.id,
            model=model,
            detection=detection,
            environment=codex_child_environment(),
        )
        authentication = connectivity.get("authentication") or {}
        prerequisites_available = bool(
            detection.status == "configured"
            and authentication.get("authenticated") is True
            and authentication.get("credential_store_accessible") is True
        )
        if not prerequisites_available:
            codex_manager.reconcile_observed_local_readiness(
                session,
                detection,
                authenticated=False,
                authentication_reason=str(
                    connectivity.get("blocker")
                    or "Codex authentication is unavailable in the detached runtime context."
                ),
            )
            session.flush()
        # CLI/authentication inspection is not Provider/model connectivity proof.
        # Rechecking prerequisites must also not erase an exact, still-current
        # Owner-triggered Provider/model probe. Run readiness remains derived
        # from that immutable evidence, never from this request itself.
        available = connectivity.get("ready_for_real_run") is True
        if available:
            provider.enabled = True
            provider.status = "healthy"
            model.status = "healthy"
            model.availability_status = "available"
            model.evidence_status = "verified"
            model.evidence_source = "codex_connectivity_probe"
            failure = ""
            diagnostic = (
                "CLI and authentication prerequisites remain available. "
                "Real-Run readiness is preserved from the latest matching "
                "Owner-triggered connectivity probe; no Provider request was made."
            )
        elif detection.status != "configured":
            failure = "runtime_unavailable"
            diagnostic = detection.reason
        elif not prerequisites_available:
            failure = "authentication_unavailable"
            diagnostic = str(
                connectivity.get("blocker")
                or "Codex authentication is unavailable in the detached runtime context."
            )
        else:
            failure = "connectivity_not_verified"
            diagnostic = (
                "Codex CLI and authentication prerequisites are available. "
                "Provider connectivity and model availability are not verified."
            )
        evidence = AIModelAvailabilityEvidence(
            configuration_identity=model.stable_id or f"model-{model.id}",
            model_id=model.id,
            checked_by_user_id=user.id,
            adapter="codex_cli",
            invocation_mode="real",
            result="available" if available else "unavailable",
            evidence_type=(
                "non_inference_cli_health_with_persisted_connectivity"
                if available
                else "non_inference_cli_health"
            ),
            failure_classification=failure,
            runtime_identity=(detection.version or "")[:240],
        )
        session.add(evidence)
        invalidated = (
            int(
                session.scalar(
                    select(func.count(CodexInstructionPack.id)).where(
                        CodexInstructionPack.id.in_(approved_before),
                        CodexInstructionPack.status == "invalidated",
                    )
                )
                or 0
            )
            if approved_before
            else 0
        )
        audit(
            session, request, "codex_availability_checked", "ai_model", model.id,
            (
                f"adapter=codex_cli; capability={payload.capability}; "
                f"result={evidence.result}; evidence_type={evidence.evidence_type}; "
                "provider_probe_performed=false"
            ),
            user,
        )
        session.flush()
        return {
            "configuration": model_out(model),
            "availability_evidence": {
                "configuration_identity": evidence.configuration_identity,
                "adapter": evidence.adapter,
                "invocation_mode": evidence.invocation_mode,
                "checked_at": iso(evidence.checked_at),
                "result": evidence.result,
                "evidence_type": evidence.evidence_type,
                "failure_classification": evidence.failure_classification,
                "runtime_identity": evidence.runtime_identity,
            },
            "available": available,
            "execution_prerequisites_available": prerequisites_available,
            "readiness_state": connectivity.get("readiness_state"),
            "ready_for_real_run": available,
            "provider_probe_performed": False,
            "connectivity_evidence_id": connectivity.get("evidence_id"),
            "last_connectivity_check": connectivity.get("last_connectivity_check"),
            "invalidated_packs": invalidated,
        }

    @app.get("/api/codex/setup/connectivity")
    def get_codex_connectivity(
        model_identifier: str | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        model = None
        if model_identifier:
            model = session.scalar(
                select(AIModel).where(
                    AIModel.execution_adapter == "codex_cli",
                    AIModel.provider_model_id == model_identifier,
                    AIModel.configuration_status != "disabled",
                )
            )
        else:
            model = local_codex_model(session)
        detection = codex_manager.adapter.detect()
        # Read-only authentication inspection is allowed here; this GET never
        # performs a Provider request and never creates connectivity evidence.
        output = connectivity_status(
            session,
            owner_id=user.id,
            model=model,
            detection=detection,
            environment=codex_child_environment(),
        )
        output["configured_run_timeout_seconds"] = settings.codex_timeout_seconds
        output["configured_connectivity_timeout_seconds"] = (
            settings.codex_connectivity_timeout_seconds
        )
        return output

    @app.post("/api/codex/setup/verify-connection")
    def verify_codex_setup_connection(
        payload: CodexSetupIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        catalog_model = selected_catalog_model(payload.model_identifier)
        model, _ = ensure_local_codex_configuration(
            session,
            catalog_model.canonical_model_id,
            catalog_model.display_name,
        )
        provider = model.provider
        material_before = (
            provider.enabled,
            provider.status,
            model.status,
            model.availability_status,
            model.evidence_status,
            model.evidence_source,
        )
        detection = codex_manager.adapter.detect()
        evidence = verify_codex_connection(
            session,
            owner_id=user.id,
            model=model,
            detection=detection,
            command_for=codex_manager.adapter.command_for,
            timeout_seconds=settings.codex_connectivity_timeout_seconds,
        )
        ready = evidence.readiness_state == "READY_FOR_REAL_RUN"
        provider.enabled = evidence.provider_reachable
        provider.status = (
            "healthy"
            if ready
            else "degraded"
            if evidence.provider_reachable
            else "unconfigured"
        )
        provider.last_checked_at = utc_now()
        model.status = "healthy" if ready else "unconfigured"
        model.availability_status = "available" if ready else "unavailable"
        model.evidence_status = "verified" if ready else "unverified"
        model.evidence_source = "codex_connectivity_probe"
        model.last_verified_at = evidence.checked_at
        model.safe_diagnostic = evidence.safe_summary
        if not evidence.provider_reachable:
            # Provider/authentication loss invalidates every model sharing this
            # execution target. A later successful probe for one sibling must
            # not resurrect another sibling's older READY evidence.
            for sibling in provider.models:
                if sibling.id == model.id:
                    continue
                sibling.status = "unconfigured"
                sibling.availability_status = "unavailable"
                sibling.evidence_status = "unverified"
                sibling.evidence_source = "codex_connectivity_probe"
                sibling.last_verified_at = evidence.checked_at
                sibling.safe_diagnostic = (
                    "Provider connectivity is no longer verified for this model. "
                    "The Owner must run Verify Codex Connection again."
                )
        material_after = (
            provider.enabled,
            provider.status,
            model.status,
            model.availability_status,
            model.evidence_status,
            model.evidence_source,
        )
        invalidated = 0
        # Connectivity evidence provenance can advance from a prerequisite
        # check to an Owner-triggered real probe without changing the Pack's
        # routing material. Invalidate only when provider/model readiness
        # itself changed; Run admission still requires the new immutable
        # Owner-scoped connectivity evidence.
        if material_before[:4] != material_after[:4]:
            provider_state_changed = material_before[:2] != material_after[:2]
            affected_model_ids = (
                [item.id for item in provider.models]
                if provider_state_changed
                else [model.id]
            )
            assigned_task_ids = {
                assignment.task_id
                for assignment in session.scalars(
                    select(AIModelAssignment).where(
                        or_(
                            AIModelAssignment.assigned_model_id.in_(affected_model_ids),
                            AIModelAssignment.fallback_model_id.in_(affected_model_ids),
                        )
                    )
                ).all()
            }
            for assigned_task_id in assigned_task_ids:
                invalidated_for_task = invalidate_approved_packs(
                    session, assigned_task_id
                )
                invalidated += invalidated_for_task
                if invalidated_for_task:
                    assigned_task = session.get(Task, assigned_task_id)
                    if assigned_task is not None:
                        assigned_task.status = "planned"
        session.add(
            AIModelAvailabilityEvidence(
                configuration_identity=model.stable_id or f"model-{model.id}",
                model_id=model.id,
                checked_by_user_id=user.id,
                adapter="codex_cli",
                invocation_mode="real",
                result="available" if ready else "unavailable",
                evidence_type="owner_triggered_connectivity_probe",
                failure_classification=evidence.blocker_code,
                runtime_identity=(detection.version or "")[:240],
            )
        )
        audit(
            session,
            request,
            "codex_connection_verified",
            "codex_connectivity_evidence",
            evidence.id,
            (
                f"state={evidence.readiness_state}; authentication={evidence.authentication_state}; "
                f"provider_reachable={str(evidence.provider_reachable).lower()}; "
                f"model_available={str(evidence.model_available).lower()}; "
                f"invalidated_packs={invalidated}"
            ),
            user,
        )
        session.flush()
        output = connectivity_evidence_out(evidence) or {}
        output["configuration"] = model_out(model)
        output["configured_run_timeout_seconds"] = settings.codex_timeout_seconds
        output["configured_connectivity_timeout_seconds"] = (
            settings.codex_connectivity_timeout_seconds
        )
        output["invalidated_packs"] = invalidated
        return output

    @app.post("/api/tasks/{task_id}/codex/setup/assign")
    def assign_codex_setup(
        task_id: int,
        payload: CodexAssignIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, task_id)
        model = session.get(AIModel, payload.model_id)
        if not task or not model or model.execution_adapter != "codex_cli":
            raise HTTPException(status_code=404, detail="Local Codex configuration not found.")
        selected_catalog_model(model.provider_model_id or "")
        evidence = session.scalar(
            select(AIModelAvailabilityEvidence)
            .where(
                AIModelAvailabilityEvidence.model_id == model.id,
                AIModelAvailabilityEvidence.result == "available",
            )
            .order_by(AIModelAvailabilityEvidence.id.desc())
        )
        if evidence is None or model.availability_status != "available":
            raise HTTPException(
                status_code=409,
                detail="Verify Codex Connection successfully before Save and assign.",
            )
        plan = session.scalar(
            select(AITeamPlan).where(AITeamPlan.task_id == task.id).order_by(AITeamPlan.id.desc())
        )
        if plan is None:
            raise HTTPException(status_code=409, detail="Save the task and compose the AI Team first.")
        capability = session.scalar(
            select(AICapability).where(AICapability.name == payload.capability)
        )
        if capability is None:
            raise HTTPException(status_code=409, detail="Requested executable capability is unavailable.")
        current_assignments = latest_model_assignments(session, task.id)
        current_binding = next(
            (item for item in current_assignments if item.capability == payload.capability),
            None,
        )
        if current_binding is not None and current_binding.assigned_model_id == model.id:
            audit(
                session,
                request,
                f"{payload.capability}_model_assignment_unchanged",
                "task",
                task.id,
                (
                    f"capability={payload.capability}; model={model.stable_id}; "
                    f"assignment_version={current_binding.assignment_version}; invalidated_packs=0"
                ),
                user,
            )
            return {
                "capability": payload.capability,
                "assignments": [model_assignment_out(item) for item in current_assignments],
                "changed": False,
                "invalidated_packs": 0,
            }
        decision = RoutingDecision(
            task_id=task.id, team_plan_id=plan.id, capability_id=capability.id,
            requested_capabilities=plan.required_capabilities, selected_model_id=model.id,
            status="selected", reason=f"Owner selected the verified Local Codex CLI target for {payload.capability.title()}.",
            fallback_status="unavailable", fallback_reason="No fallback was configured.",
            next_action="Regenerate and approve the Codex Pack.",
        )
        session.add(decision)
        session.flush()
        latest_by_capability: dict[int, RoutingDecision] = {}
        for route in session.scalars(
            select(RoutingDecision).where(RoutingDecision.team_plan_id == plan.id).order_by(RoutingDecision.id)
        ).all():
            latest_by_capability[route.capability_id] = route
        assignments = recompose_model_assignments(
            session, task, latest_by_capability.values(), team_plan=plan,
            task_version=task.task_version, routing_source="owner_setup",
        )
        invalidated = invalidate_approved_packs(session, task.id)
        task.status = "planned"
        audit(
            session, request, f"{payload.capability}_model_assigned", "task", task.id,
            f"capability={payload.capability}; model={model.stable_id}; assignment_version={assignments[0].assignment_version}; invalidated_packs={invalidated}", user,
        )
        return {
            "capability": payload.capability,
            "assignments": [model_assignment_out(item) for item in assignments],
            "changed": True,
            "invalidated_packs": invalidated,
        }

    @app.get("/api/codex/status")
    def codex_status(
        task_id: int | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        configured = local_codex_model(session)
        detection = codex_manager.adapter.detect()
        connectivity = connectivity_status(
            session,
            owner_id=user.id,
            model=configured,
            detection=detection,
            environment=codex_child_environment(),
        )
        evidence = (
            session.scalar(
                select(AIModelAvailabilityEvidence)
                .where(AIModelAvailabilityEvidence.model_id == configured.id)
                .order_by(AIModelAvailabilityEvidence.id.desc())
            )
            if configured is not None
            else None
        )
        model_identifier = configured.provider_model_id if configured is not None else ""
        registry = model_registry_snapshot(configured) if configured is not None else None
        model_binding_ready = bool(
            registry
            and registry["configuration_status"] == "configured"
            and registry["availability_status"] == "available"
            and registry["invocation_mode"] == "real"
            and registry["provider"]["enabled"] is True
            and registry["provider"]["status"] in {"healthy", "degraded"}
            and evidence is not None
            and evidence.result == "available"
            and connectivity.get("ready_for_real_run") is True
        )
        output: dict[str, Any] = {
            "status": (
                "configured"
                if model_binding_ready
                else "check_required"
                if configured is not None
                else "unconfigured"
            ),
            "found": detection.found,
            "version": detection.version,
            "supported_command": "codex exec --model MODEL --json" if detection.found else None,
            "reason": (
                configured.safe_diagnostic
                if configured is not None
                else "No Local Codex CLI configuration has been saved."
            ),
            "next_action": "Run Codex" if model_binding_ready else "Verify Codex Connection",
        }
        output["readiness_state"] = (
            "Ready"
            if model_binding_ready
            else "Unavailable"
            if not detection.found
            else "Misconfigured"
            if detection.status == "needs_setup"
            else "Needs setup"
        )
        output["authentication_ready"] = bool(
            connectivity.get("authentication", {}).get("authenticated")
        )
        output["model_binding_ready"] = model_binding_ready
        output["execution_ready"] = model_binding_ready
        output["configuration_status"] = (
            configured.configuration_status if configured is not None else "needs_setup"
        )
        output["availability_status"] = (
            configured.availability_status if configured is not None else "unavailable"
        )
        output["run_timeout_seconds"] = settings.codex_timeout_seconds
        output["configured_run_timeout_seconds"] = settings.codex_timeout_seconds
        output["connectivity_timeout_seconds"] = settings.codex_connectivity_timeout_seconds
        output["authorized_workspace"] = str(
            settings.source_repo.resolve(strict=False)
        )
        output["isolated_worktree_root"] = str(
            settings.worktree_root.resolve(strict=False)
        )
        if not model_identifier:
            output["readiness_reason"] = (
                "Select a supported Local Codex CLI model before Owner-approved execution."
            )
        elif not model_binding_ready:
            output["readiness_reason"] = (
                "The selected Local Codex model binding is not currently available for execution."
            )
        else:
            output["readiness_reason"] = (
                "Local Codex CLI, authentication, Provider connectivity, and exact requested-model "
                "acceptance are verified for a real Run."
            )
        output["readiness_evidence"] = (
            {
                "checked_at": iso(evidence.checked_at),
                "result": evidence.result,
                "evidence_type": evidence.evidence_type,
                "failure_classification": evidence.failure_classification,
                "runtime_identity": evidence.runtime_identity,
            }
            if evidence is not None
            else None
        )
        output["connectivity"] = connectivity
        try:
            source = codex_manager.adapter.source_state()
            output["source"] = {
                "identity": source["identity"],
                "branch": source["branch"],
                "commit": source["commit"],
                "clean": source["clean"],
            }
        except RuntimeError as exc:
            output["source"] = {"clean": False, "reason": str(exc)}
        if task_id is not None:
            output["run_eligibility"] = run_eligibility(
                session,
                session.get(Task, task_id),
                settings.source_repo,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=codex_child_environment(),
            )
        return output

    @app.get("/api/tasks/{task_id}/run-eligibility")
    def task_run_eligibility(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        detection = codex_manager.adapter.detect()
        return run_eligibility(
            session,
            task,
            settings.source_repo,
            owner_id=user.id,
            codex_executable=detection.executable,
            child_environment=codex_child_environment(),
        )

    @app.get("/api/tasks/{task_id}/codex-packs")
    def list_codex_packs(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> list[dict[str, Any]]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        packs = session.scalars(
            select(CodexInstructionPack)
            .where(CodexInstructionPack.task_id == task_id)
            .order_by(CodexInstructionPack.version.desc())
        ).all()
        return [codex_pack_out(pack, include_raw=True) for pack in packs]

    @app.get("/api/tasks/{task_id}/codex-packs/current")
    def current_codex_pack(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        pack = session.scalar(
            select(CodexInstructionPack)
            .where(CodexInstructionPack.task_id == task_id)
            .order_by(CodexInstructionPack.version.desc())
        )
        return {"task_id": task_id, "pack": codex_pack_out(pack, include_raw=True) if pack else None}

    @app.post("/api/tasks/{task_id}/codex-packs")
    def generate_codex_pack(
        task_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        try:
            pack = build_instruction_pack(session, task, settings.source_repo)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit(
            session,
            request,
            "codex_pack_generated",
            "codex_instruction_pack",
            pack.id,
            f"task={task.id}; version={pack.version}; approval_required=true",
            user,
        )
        return codex_pack_out(pack, include_raw=True)

    @app.post("/api/tasks/{task_id}/codex-packs/{pack_id}/approve")
    def approve_codex_pack(
        task_id: int,
        pack_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, task_id)
        pack = session.get(CodexInstructionPack, pack_id)
        if not task or not pack or pack.task_id != task.id:
            raise HTTPException(status_code=404, detail="Codex Instruction Pack not found for this task.")
        current = session.scalar(
            select(CodexInstructionPack)
            .where(CodexInstructionPack.task_id == task.id)
            .order_by(CodexInstructionPack.version.desc())
        )
        if not current or current.id != pack.id or pack.status != "approval_required":
            raise HTTPException(status_code=409, detail="Only the current approval-required pack can be approved.")
        binding_error = pack_routing_binding_error(session, task, pack, settings.source_repo)
        if binding_error:
            pack.status = "invalidated"
            pack.invalidated_at = utc_now()
            task.status = "planned"
            audit(
                session,
                request,
                "codex_pack_approval_invalidated",
                "codex_instruction_pack",
                pack.id,
                binding_error,
                user,
            )
            session.commit()
            raise HTTPException(status_code=409, detail=binding_error)
        pack.status = "approved"
        pack.approved_by_user_id = user.id
        pack.approved_at = utc_now()
        pack.invalidated_at = None
        task.status = "pack_ready"
        audit(
            session,
            request,
            "codex_pack_approved",
            "codex_instruction_pack",
            pack.id,
            f"task={task.id}; version={pack.version}",
            user,
        )
        return codex_pack_out(pack, include_raw=True)

    @app.get("/api/tasks/{task_id}/codex-runs")
    def list_codex_runs(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> list[dict[str, Any]]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        possible_runs = session.scalars(
            select(CodexRun).where(CodexRun.task_id == task_id).order_by(CodexRun.id.desc())
        ).all()
        runs = [
            run
            for run in possible_runs
            if find_owner_run(session, user.id, run.id) is not None
        ]
        return [codex_run_out(run, include_raw=True, session=session) for run in runs]

    @app.post("/api/tasks/{task_id}/codex-runs")
    def start_codex_run(
        task_id: int,
        payload: StartCodexRunIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            # Authentication lookup has already opened a read transaction on
            # this request-scoped session. End it before taking the write lock.
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        idempotency_digest = codex_start_idempotency_digest(
            user.id,
            task.id,
            payload.idempotency_key,
        )
        request_digest = codex_start_request_digest(user.id, task.id, payload)
        existing = session.scalar(
            select(CodexRun).where(
                CodexRun.start_idempotency_digest == idempotency_digest
            )
        )
        if existing is not None:
            if (
                existing.start_request_digest != request_digest
                or find_owner_run(session, user.id, existing.id) is None
            ):
                session.rollback()
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": "IDEMPOTENCY_KEY_REUSED",
                        "message": (
                            "This Run start identity is already bound to a different "
                            "Owner-confirmed request. Review the current Run before retrying."
                        ),
                    },
                )
            session.commit()
            output = codex_run_out(existing, include_raw=True, session=session)
            output["start_request_replayed"] = True
            return output
        detection = codex_manager.adapter.detect()
        authenticated, authentication_reason = codex_manager.adapter.authentication_ready(detection)
        readiness_changed = codex_manager.reconcile_observed_local_readiness(
            session,
            detection,
            authenticated=authenticated,
            authentication_reason=authentication_reason,
        )
        child_environment = codex_child_environment()
        eligibility = run_eligibility(
            session,
            task,
            settings.source_repo,
            owner_id=user.id,
            codex_executable=detection.executable,
            child_environment=child_environment,
        )
        if not eligibility["eligible"]:
            material_blocker_codes = {
                item["code"]
                for item in eligibility["blockers"]
                if item["code"] in {"PACK_STALE", "SOURCE_CHANGED_SINCE_APPROVAL"}
            }
            invalidated = (
                invalidate_approved_packs(session, task.id)
                if material_blocker_codes
                else 0
            )
            if invalidated:
                task.status = "planned"
                audit(
                    session,
                    request,
                    "codex_pack_approval_invalidated",
                    "task",
                    task.id,
                    (
                        "Run admission detected a material approval binding change; "
                        f"blocker_codes={','.join(sorted(material_blocker_codes))}; "
                        f"invalidated_packs={invalidated}."
                    ),
                    user,
                )
                eligibility = run_eligibility(
                    session,
                    task,
                    settings.source_repo,
                    owner_id=user.id,
                    codex_executable=detection.executable,
                    child_environment=child_environment,
                )
            if readiness_changed or invalidated:
                session.commit()
            raise HTTPException(
                status_code=409,
                detail={"type": "RUN_INELIGIBLE", **eligibility},
            )
        pack = session.get(CodexInstructionPack, eligibility["pack_id"])
        if pack is None:
            raise HTTPException(status_code=409, detail={"type": "RUN_INELIGIBLE", **eligibility})
        if pack.id != payload.pack_id or pack.version != payload.pack_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RUN_CONFIRMATION_BINDING_CHANGED",
                    "message": (
                        "The confirmed Instruction Pack identity changed. "
                        "Review the current Pack and confirm Start Codex Run again."
                    ),
                    **eligibility,
                },
            )
        current_task_digest = development_task_digest(task.development_task)
        pack_task_digest = development_task_digest(pack.development_task)
        if (
            pack.task_id != task.id
            or pack.task_version != task.task_version
            or not pack.development_task_digest
            or pack.development_task_digest != pack_task_digest
            or pack.development_task_digest != current_task_digest
            or pack.development_task != task.development_task
        ):
            refreshed = run_eligibility(
                session,
                task,
                settings.source_repo,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=child_environment,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RUN_INELIGIBLE",
                    "message": (
                        "The approved Pack does not match the exact current Development task. "
                        "Regenerate Codex Pack."
                    ),
                    **refreshed,
                },
            )
        try:
            execution_target = codex_execution_target(
                session,
                task,
                pack,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=child_environment,
            )
            verification_target = verification_execution_target(
                session,
                task,
                pack,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=child_environment,
            )
        except ValueError as exc:
            refreshed = run_eligibility(
                session,
                task,
                settings.source_repo,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=child_environment,
            )
            raise HTTPException(
                status_code=409,
                detail={"type": "RUN_INELIGIBLE", "message": str(exc), **refreshed},
            ) from exc
        try:
            source = codex_manager.adapter.source_state()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=409,
                detail="Source repository state could not be verified. Inspect Advanced runtime status.",
            ) from exc
        if source["commit"] != pack.source_baseline_commit:
            refreshed = run_eligibility(
                session,
                task,
                settings.source_repo,
                owner_id=user.id,
                codex_executable=detection.executable,
                child_environment=child_environment,
            )
            raise HTTPException(
                status_code=409,
                detail={"type": "RUN_INELIGIBLE", **refreshed},
            )
        run = CodexRun(
            task_id=task.id,
            pack_id=pack.id,
            status="queued",
            executable_status=detection.status,
            source_repo=str(source["repo"]),
            source_branch=str(source["branch"]),
            source_commit=str(source["commit"]),
            development_task=pack.development_task,
            development_task_digest=pack.development_task_digest,
            task_version=pack.task_version,
            assignment_version=pack.assignment_version,
            routing_snapshot_hash=pack.routing_snapshot_hash,
            source_snapshot_digest=pack.source_snapshot_digest,
            approved_instruction_digest=codex_approved_instruction_digest(pack),
            start_idempotency_digest=idempotency_digest,
            start_request_digest=request_digest,
            owner_start_confirmed_at=utc_now(),
            execution_assignment_id=execution_target.assignment.id,
            execution_model_id=execution_target.model.id,
            execution_provider_id=execution_target.model.provider_id,
            execution_connectivity_evidence_id=execution_target.connectivity_evidence_id,
            requested_model_identifier=execution_target.requested_model_identifier,
            fallback_selected=execution_target.fallback_selected,
            verification_assignment_id=verification_target.assignment.id,
            verification_model_id=verification_target.model.id,
            verification_provider_id=verification_target.model.provider_id,
            verification_connectivity_evidence_id=(
                verification_target.connectivity_evidence_id
            ),
            verification_model_identifier=verification_target.requested_model_identifier,
            verification_status="not_started",
            owner_summary="Approved Codex run is queued for isolated execution.",
        )
        session.add(run)
        session.flush()
        ensure_run_monitor(session, user.id, run)
        task.status = "queued"
        audit(
            session,
            request,
            "codex_run_queued",
            "codex_run",
            run.id,
            (
                f"task={task.id}; pack_version={pack.version}; "
                "owner_confirmation=true; stable_request_identity=true"
            ),
            user,
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(CodexRun).where(
                    CodexRun.start_idempotency_digest == idempotency_digest
                )
            )
            if (
                existing is None
                or existing.start_request_digest != request_digest
                or find_owner_run(session, user.id, existing.id) is None
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": "RUN_START_CONFLICT",
                        "message": "A conflicting Run start was accepted concurrently.",
                    },
                )
            output = codex_run_out(existing, include_raw=True, session=session)
            output["start_request_replayed"] = True
            return output
        if not codex_manager.start(run.id):
            run.status = "blocked"
            run.finished_at = utc_now()
            run.owner_summary = "Blocked: runtime shutdown began before the Codex worker could start. Nothing ran."
            run.verification_status = "not_started"
            run.verification_summary = "Verification was not started because Coding did not start."
            task.status = "blocked"
            audit(
                session,
                request,
                "codex_run_blocked",
                "codex_run",
                run.id,
                "Runtime shutdown prevented process start.",
                user,
            )
            session.commit()
        result_intake_monitor.notify()
        output = codex_run_out(run, include_raw=True, session=session)
        output["start_request_replayed"] = False
        return output

    @app.get("/api/codex-runs/{run_id}")
    def get_codex_run(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        run = find_owner_run(session, user.id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Codex run not found.")
        return codex_run_out(run, include_raw=True, session=session)

    def result_intake_error(exc: ResultIntakeError) -> HTTPException:
        status_code = 404 if exc.code in {
            "RUN_NOT_FOUND",
            "HANDOFF_REVIEW_NOT_FOUND",
            "INSTRUCTION_DRAFT_NOT_FOUND",
        } else 409
        return HTTPException(
            status_code=status_code,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
                "monitor_state": exc.monitor_state,
            },
        )

    def owner_run_or_404(
        session: Session,
        owner_id: int,
        run_id: int,
    ) -> CodexRun:
        run = find_owner_run(session, owner_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Codex run not found.")
        return run

    def persisted_result_intake(
        session: Session,
        owner_id: int,
        run_id: int,
    ) -> tuple[CodexRunMonitor | None, CodexResultEnvelope | None]:
        monitor = session.scalar(
            select(CodexRunMonitor).where(
                CodexRunMonitor.owner_id == owner_id,
                CodexRunMonitor.run_id == run_id,
            )
        )
        envelope = session.scalar(
            select(CodexResultEnvelope).where(
                CodexResultEnvelope.owner_id == owner_id,
                CodexResultEnvelope.run_id == run_id,
            )
        )
        return monitor, envelope

    def run_activity_record(
        session: Session,
        owner_id: int,
        run: CodexRun,
    ) -> dict[str, Any]:
        monitor, envelope = persisted_result_intake(
            session,
            owner_id,
            run.id,
        )
        lifecycle = lifecycle_snapshot_out(
            session,
            owner_id,
            run,
            advanced=True,
        )
        snapshot_unavailable = source_snapshot_unavailable_for_run(
            session,
            run,
            monitor,
        )
        if snapshot_unavailable:
            # Snapshot hydration is a pre-launch product blocker, not a missing
            # terminal result. Keep the exact recovery action on every Run
            # Activity surface without manufacturing lifecycle evidence.
            lifecycle = {
                **lifecycle,
                "state": "RESULT_UNAVAILABLE",
                "current_activity": "Source snapshot unavailable",
                "next_action": "Regenerate Codex Pack",
                "blocker_code": "SOURCE_SNAPSHOT_UNAVAILABLE",
            }
        monitor_state = str(lifecycle.get("state") or "RESULT_UNAVAILABLE").upper()
        owner_action = str(
            lifecycle.get("next_action")
            or (
                "Open View Result, then Review Handoff."
                if envelope is not None
                else "Review the durable Run evidence."
            )
        )
        coding_summary: object = run.owner_summary
        verification_summary: object = run.verification_summary
        tests: object = []
        if envelope is not None:
            public_envelope = result_envelope_out(envelope)
            terminal_envelope = result_envelope_out(envelope, advanced=True)
            coding = public_envelope.get("coding_result", {})
            coding_summary = (
                coding.get("safe_summary")
                if isinstance(coding, dict)
                else coding
            ) or run.owner_summary
            verification = public_envelope.get("verification_result", {})
            verification_summary = (
                verification.get("verdict")
                if isinstance(verification, dict)
                else verification
            ) or run.verification_summary
            tests = public_envelope.get("tests", [])
        else:
            public_envelope = None
            terminal_envelope = None
        terminal_truth = terminal_truth_out(
            run, lifecycle, terminal_envelope, session=session
        )
        return {
            "run_id": run.id,
            "task_id": run.task_id,
            "task_name": run.task.title or run.development_task,
            "run_status": terminal_truth["terminal_state"],
            "monitor_state": monitor_state,
            "requested_model": run.requested_model_identifier,
            "actual_model": (
                public_envelope.get("actual_model")
                if public_envelope is not None
                else None
            ),
            "actual_model_verified": bool(
                public_envelope and public_envelope.get("actual_model_verified")
            ),
            "result_available": bool(
                public_envelope and public_envelope.get("result_available")
            ),
            "execution_successful": bool(
                public_envelope and public_envelope.get("execution_successful")
            ),
            "handoff_reconciliation": (
                public_envelope.get("handoff_reconciliation")
                if public_envelope
                else None
            ),
            "started_at": lifecycle.get("started_at") or iso(run.started_at),
            "finished_at": lifecycle.get("terminal_at") or iso(run.finished_at),
            "duration_ms": lifecycle.get("elapsed_ms") if lifecycle.get("terminal_at") else run.duration_ms,
            "coding_summary": coding_summary,
            "verification_summary": verification_summary,
            "tests": tests,
            "result_integrity": (
                envelope.integrity_state
                if envelope is not None
                else (
                    "BLOCKED"
                    if monitor_state == "RESULT_INTEGRITY_BLOCKED"
                    else "UNAVAILABLE"
                    if monitor_state in {"PROCESS_LOST", "RESULT_UNAVAILABLE"}
                    else "PENDING"
                )
            ),
            "owner_action": owner_action,
            "next_action": owner_action,
            "lifecycle": lifecycle,
            "terminal_truth": terminal_truth,
            "actions": {
                "next_action": owner_action,
                "can_reconnect": monitor_state in {
                    "PROCESS_LOST",
                    "RESULT_UNAVAILABLE",
                    "RESULT_PENDING",
                } and not snapshot_unavailable,
                "can_import": monitor_state in {
                    "PROCESS_LOST",
                    "RESULT_UNAVAILABLE",
                    "RESULT_INTEGRITY_BLOCKED",
                } and not snapshot_unavailable,
                "recovery_blocked": snapshot_unavailable,
            },
            "monitor": (
                monitor_out(monitor, envelope=envelope)
                if monitor is not None
                else None
            ),
            "envelope": (
                result_envelope_out(envelope)
                if envelope is not None
                else None
            ),
        }

    @app.get("/api/run-activity")
    def list_run_activity(
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        possible_runs = list(
            session.scalars(
                select(CodexRun).order_by(CodexRun.id.desc())
            ).all()
        )
        owned_runs = [
            run
            for run in possible_runs
            if find_owner_run(session, user.id, run.id) is not None
        ]
        return {
            "label": "Run Activity",
            "runs": [
                run_activity_record(session, user.id, run)
                for run in owned_runs
            ],
            "notification_count": sum(
                1
                for run in owned_runs
                if persisted_result_intake(session, user.id, run.id)[1] is not None
            ),
        }

    @app.get("/api/codex-runs/{run_id}/result-envelope")
    def get_result_envelope(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        monitor, envelope = persisted_result_intake(session, user.id, run_id)
        if envelope is None:
            raise HTTPException(
                status_code=404,
                detail="Run Result not found.",
            )
        public_result = result_envelope_out(envelope, advanced=True)
        run = owner_run_or_404(session, user.id, run_id)
        lifecycle = lifecycle_snapshot_out(session, user.id, run, advanced=True)
        return {
            "run_id": run_id,
            "result": public_result,
            "envelope": public_result,
            "lifecycle": lifecycle,
            "terminal_truth": terminal_truth_out(
                run, lifecycle, public_result, session=session
            ),
            "monitor": (
                monitor_out(monitor, envelope=envelope, advanced=True)
                if monitor is not None
                else None
            ),
        }

    @app.post("/api/codex-runs/{run_id}/refresh-status")
    def refresh_codex_run_status(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        session.commit()
        result_intake_monitor.reconcile_now([run_id])
        session.expire_all()
        run = owner_run_or_404(session, user.id, run_id)
        return {
            "run": run_activity_record(session, user.id, run),
            "duplicate_run_started": False,
        }

    @app.post("/api/codex-runs/{run_id}/reconnect")
    def reconnect_codex_run(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        try:
            monitor = reconnect_run_monitor(session, user.id, run_id)
        except ResultIntakeError as exc:
            raise result_intake_error(exc) from exc
        session.commit()
        result_intake_monitor.notify()
        _, envelope = persisted_result_intake(session, user.id, run_id)
        return {
            "run_id": run_id,
            "monitor": monitor_out(
                monitor,
                envelope=envelope,
                advanced=True,
            ),
            "duplicate_run_started": False,
        }

    @app.post("/api/codex-runs/{run_id}/import-result")
    def import_result_envelope(
        run_id: int,
        payload: CodexResultImportIn,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        try:
            envelope = import_codex_result(
                session,
                user.id,
                run_id,
                payload.result,
            )
        except ResultIntakeError as exc:
            raise result_intake_error(exc) from exc
        session.flush()
        result_intake_monitor.notify()
        public_result = result_envelope_out(envelope, advanced=True)
        return {
            "run_id": run_id,
            "result": public_result,
            "envelope": public_result,
        }

    @app.get("/api/codex-runs/{run_id}/handoff-review")
    def get_handoff_review(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        review = session.scalar(
            select(HandoffReview).where(
                HandoffReview.owner_id == user.id,
                HandoffReview.run_id == run_id,
            )
        )
        if review is None:
            raise HTTPException(status_code=404, detail="Handoff Review not found.")
        draft = session.scalar(
            select(HandoffInstructionDraft).where(
                HandoffInstructionDraft.owner_id == user.id,
                HandoffInstructionDraft.handoff_review_id == review.id,
            )
        )
        return {
            "run_id": run_id,
            "review": handoff_review_out(review),
            "draft": instruction_draft_out(draft) if draft is not None else None,
        }

    @app.post("/api/codex-runs/{run_id}/handoff-review")
    def review_codex_handoff(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        try:
            review = get_or_create_handoff_review(session, user.id, run_id)
        except ResultIntakeError as exc:
            raise result_intake_error(exc) from exc
        draft = session.scalar(
            select(HandoffInstructionDraft).where(
                HandoffInstructionDraft.owner_id == user.id,
                HandoffInstructionDraft.handoff_review_id == review.id,
            )
        )
        return {
            "run_id": run_id,
            "review": handoff_review_out(review),
            "draft": instruction_draft_out(draft) if draft is not None else None,
        }

    @app.get("/api/codex-runs/{run_id}/instruction-draft")
    def get_instruction_draft(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        draft = session.scalar(
            select(HandoffInstructionDraft).where(
                HandoffInstructionDraft.owner_id == user.id,
                HandoffInstructionDraft.run_id == run_id,
            )
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="Instruction draft not found.")
        return {"run_id": run_id, "draft": instruction_draft_out(draft)}

    @app.post("/api/codex-runs/{run_id}/instruction-draft")
    def review_or_approve_instruction_draft(
        run_id: int,
        payload: InstructionDraftActionIn = InstructionDraftActionIn(),
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        owner_run_or_404(session, user.id, run_id)
        review = session.scalar(
            select(HandoffReview).where(
                HandoffReview.owner_id == user.id,
                HandoffReview.run_id == run_id,
            )
        )
        if review is None:
            raise HTTPException(
                status_code=409,
                detail="Review Handoff before preparing an instruction draft.",
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        try:
            draft = get_or_create_instruction_draft(session, user.id, review)
            if payload.action == "approve":
                if (
                    not payload.expected_digest
                    or payload.expected_digest != draft.draft_digest
                ):
                    raise ResultIntakeError(
                        "INSTRUCTION_DRAFT_DIGEST_MISMATCH",
                        "The instruction draft changed. Review it again before approval.",
                    )
                draft = approve_instruction_draft(session, user.id, draft.id)
        except ResultIntakeError as exc:
            raise result_intake_error(exc) from exc
        return {"run_id": run_id, "draft": instruction_draft_out(draft)}

    @app.post("/api/instruction-drafts/{draft_id}/approve")
    def approve_instruction_draft_by_public_id(
        draft_id: str,
        payload: InstructionDraftActionIn,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        draft = session.scalar(
            select(HandoffInstructionDraft).where(
                HandoffInstructionDraft.draft_id == draft_id,
                HandoffInstructionDraft.owner_id == user.id,
            )
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="Instruction draft not found.")
        if (
            not payload.expected_digest
            or payload.expected_digest != draft.draft_digest
        ):
            raise HTTPException(
                status_code=409,
                detail="The instruction draft changed. Review it again before approval.",
            )
        try:
            draft = approve_instruction_draft(session, user.id, draft.id)
        except ResultIntakeError as exc:
            raise result_intake_error(exc) from exc
        return {"run_id": draft.run_id, "draft": instruction_draft_out(draft)}

    def delivery_candidate_review_response(
        run_id: int,
        request: Request,
        session: Session,
        user: User,
        *,
        create: bool,
    ) -> dict[str, Any]:
        run = find_owner_run(session, user.id, run_id)
        if run is None:
            # Deliberately do not distinguish an absent Run from a Run belonging
            # to another Owner.
            raise HTTPException(status_code=404, detail="Codex run not found.")
        candidate = session.scalar(
            select(DeliveryCandidate).where(
                DeliveryCandidate.owner_id == user.id,
                DeliveryCandidate.run_id == run.id,
            )
        )
        if candidate is None and not create:
            return {
                "run_id": run.id,
                "candidate": None,
                "drift": None,
                "blockers": [],
                "next_action": "Review Change Candidate",
            }
        created = False
        if create:
            candidate, created, eligibility = get_or_create_delivery_candidate(
                session,
                user.id,
                run,
            )
        else:
            assert candidate is not None
            eligibility = validate_delivery_candidate(
                session,
                user.id,
                run,
                candidate,
            )
        # A Result-derived Candidate remains reviewable while Owner acceptance
        # or another readiness gate is pending. Readiness and visibility are
        # intentionally separate; only later Plan creation uses eligibility.
        public_candidate = candidate
        candidate_reviewable = bool(
            candidate is not None
            and (eligibility.get("reviewable") is True or eligibility.get("eligible"))
        )
        evaluation = evaluate_source_drift(
            session,
            owner_id=user.id,
            run=run,
            candidate=candidate,
            source_repo=settings.source_repo,
            unavailable_blockers=(
                None if candidate_reviewable else eligibility["blockers"]
            ),
            unavailable_next_action=(
                None if candidate_reviewable else eligibility["next_action"]
            ),
        )
        if public_candidate is not None:
            audit(
                session,
                request,
                "delivery_candidate_created" if created else "delivery_candidate_retrieved",
                "delivery_candidate",
                public_candidate.id,
                (
                    f"run={run.id}; candidate={public_candidate.candidate_id}; "
                    f"digest={public_candidate.candidate_digest[:12]}"
                ),
                user,
            )
        audit(
            session,
            request,
            "source_drift_evaluated",
            "source_drift_evaluation",
            evaluation.id,
            (
                f"run={run.id}; status={evaluation.status}; "
                f"candidate_available={public_candidate is not None}"
            ),
            user,
        )
        serialized_drift = source_drift_out(evaluation)
        response_blockers = []
        seen_blocker_codes: set[str] = set()
        for blocker in list(eligibility.get("blockers") or []) + list(
            serialized_drift.get("blockers") or []
        ):
            if not isinstance(blocker, dict):
                continue
            code = str(blocker.get("code") or "CANDIDATE_BLOCKED")
            if code in seen_blocker_codes:
                continue
            seen_blocker_codes.add(code)
            response_blockers.append(blocker)
        response_next_action = (
            eligibility["next_action"]
            if not eligibility.get("eligible")
            else serialized_drift["next_action"]
        )
        return {
            "run_id": run.id,
            "candidate": (
                delivery_candidate_out(public_candidate)
                if public_candidate is not None
                else None
            ),
            "drift": serialized_drift,
            "blockers": response_blockers,
            "next_action": response_next_action,
        }

    @app.get("/api/codex-runs/{run_id}/delivery-candidate")
    def get_delivery_candidate(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        return delivery_candidate_review_response(
            run_id,
            request,
            session,
            user,
            create=False,
        )

    @app.post("/api/codex-runs/{run_id}/delivery-candidate")
    def review_change_candidate(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            # Serialize the idempotent owner/run uniqueness decision.
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        return delivery_candidate_review_response(
            run_id,
            request,
            session,
            user,
            create=True,
        )

    def owner_result_review_for_run(
        session: Session,
        *,
        owner_id: int,
        run: CodexRun,
    ) -> tuple[OwnerAcceptanceSession, CodexResultEnvelope, DeliveryCandidate]:
        acceptance = session.scalar(
            select(OwnerAcceptanceSession).where(
                OwnerAcceptanceSession.owner_id == owner_id,
                OwnerAcceptanceSession.codex_run_id == run.id,
                OwnerAcceptanceSession.task_id == run.task_id,
            )
        )
        if acceptance is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_NOT_READY",
                    "message": "The immutable Run Result is not ready for Owner delivery review.",
                },
            )
        envelope = (
            session.get(CodexResultEnvelope, acceptance.result_envelope_id)
            if acceptance.result_envelope_id is not None
            else None
        )
        candidate = (
            session.get(DeliveryCandidate, acceptance.delivery_candidate_id)
            if acceptance.delivery_candidate_id is not None
            else None
        )
        if (
            envelope is None
            or candidate is None
            or envelope.owner_id != owner_id
            or envelope.run_id != run.id
            or candidate.owner_id != owner_id
            or candidate.run_id != run.id
            or acceptance.result_envelope_public_id != envelope.envelope_id
            or acceptance.result_digest != envelope.result_digest
            or acceptance.candidate_public_id != candidate.candidate_id
            or acceptance.candidate_version != candidate.candidate_version
            or acceptance.candidate_digest != candidate.candidate_digest
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_BINDING_INVALID",
                    "message": "The Result review no longer binds one exact immutable Result and Candidate.",
                },
            )
        eligibility = validate_delivery_candidate(
            session,
            owner_id,
            run,
            candidate,
        )
        if eligibility.get("reviewable") is not True:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_INTEGRITY_INVALID",
                    "message": "The Result-derived Candidate failed its immutable review binding.",
                },
            )
        return acceptance, envelope, candidate

    def decide_result_delivery(
        run_id: int,
        payload: ResultDeliveryDecisionIn,
        request: Request,
        session: Session,
        user: User,
        *,
        decision: Literal["accepted", "rejected"],
    ) -> dict[str, Any]:
        run = owner_run_or_404(session, user.id, run_id)
        acceptance, envelope, candidate = owner_result_review_for_run(
            session,
            owner_id=user.id,
            run=run,
        )
        required_confirmation = (
            "ACCEPT_RESULT_FOR_DELIVERY"
            if decision == "accepted"
            else "REJECT_RESULT_FOR_DELIVERY"
        )
        if payload.confirmation != required_confirmation:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_CONFIRMATION_REQUIRED",
                    "message": "Use the exact explicit Owner Result-review confirmation.",
                },
            )
        stale = any(
            (
                payload.expected_result_id != envelope.envelope_id,
                payload.expected_result_digest != envelope.result_digest,
                payload.expected_candidate_id != candidate.candidate_id,
                payload.expected_candidate_version != candidate.candidate_version,
                payload.expected_candidate_digest != candidate.candidate_digest,
            )
        )
        if stale:
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_BINDING_STALE",
                    "message": "The Result or Candidate changed. Review the current immutable evidence before deciding.",
                },
            )
        if acceptance.status in {"accepted", "rejected"}:
            exact_replay = bool(
                acceptance.status == decision
                and acceptance.owner_note == payload.note
                and acceptance.decided_by_user_id == user.id
                and acceptance.decided_at is not None
                and re.fullmatch(r"[0-9a-f]{64}", acceptance.decision_digest or "")
                and acceptance.decision_digest
                == result_review_decision_digest(acceptance)
            )
            if not exact_replay:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": "RESULT_REVIEW_ALREADY_FINAL",
                        "message": "This exact Result already has a different final Owner decision.",
                    },
                )
            return {
                "run_id": run.id,
                "review": owner_acceptance_out(session, acceptance),
                "candidate": delivery_candidate_out(candidate),
                "decision_replayed": True,
                "automatic_actions": [],
            }
        if acceptance.status != "owner_review":
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "RESULT_REVIEW_STATE_INVALID",
                    "message": "The Result review is not pending an Owner decision.",
                },
            )
        acceptance.status = decision
        acceptance.owner_note = payload.note
        acceptance.decided_by_user_id = user.id
        acceptance.decided_at = utc_now()
        acceptance.decision_digest = result_review_decision_digest(acceptance)
        audit(
            session,
            request,
            (
                "owner_result_accepted_for_delivery"
                if decision == "accepted"
                else "owner_result_rejected_for_delivery"
            ),
            "owner_acceptance",
            acceptance.id,
            (
                f"run={run.id}; result={envelope.envelope_id}; "
                f"candidate={candidate.candidate_id}; no_downstream_action=true"
            ),
            user,
        )
        session.flush()
        return {
            "run_id": run.id,
            "review": owner_acceptance_out(session, acceptance),
            "candidate": delivery_candidate_out(candidate),
            "decision_replayed": False,
            "automatic_actions": [],
        }

    @app.post("/api/codex-runs/{run_id}/delivery-review/accept")
    def accept_result_for_delivery(
        run_id: int,
        payload: ResultDeliveryDecisionIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        return decide_result_delivery(
            run_id,
            payload,
            request,
            session,
            user,
            decision="accepted",
        )

    @app.post("/api/codex-runs/{run_id}/delivery-review/reject")
    def reject_result_for_delivery(
        run_id: int,
        payload: ResultDeliveryDecisionIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        return decide_result_delivery(
            run_id,
            payload,
            request,
            session,
            user,
            decision="rejected",
        )

    def owner_candidate_for_apply_plan(
        session: Session,
        *,
        owner_id: int,
        run: CodexRun,
    ) -> tuple[DeliveryCandidate | None, dict[str, Any]]:
        candidate = session.scalar(
            select(DeliveryCandidate).where(
                DeliveryCandidate.owner_id == owner_id,
                DeliveryCandidate.run_id == run.id,
            )
        )
        if candidate is None:
            return None, delivery_candidate_eligibility(session, owner_id, run)
        return candidate, validate_delivery_candidate(
            session,
            owner_id,
            run,
            candidate,
        )

    def apply_plan_review_response(
        run_id: int,
        request: Request,
        session: Session,
        user: User,
        *,
        create: bool,
    ) -> dict[str, Any]:
        run = find_owner_run(session, user.id, run_id)
        if run is None:
            # Missing and cross-Owner Runs are deliberately indistinguishable.
            raise HTTPException(status_code=404, detail="Codex run not found.")

        if not create:
            plan = latest_apply_plan(session, user.id, run.id)
            return {
                "run_id": run.id,
                "plan": (
                    apply_plan_out(
                        session,
                        plan,
                        source_repo=settings.source_repo,
                    )
                    if plan is not None
                    else None
                ),
                "history": apply_plan_history(
                    session,
                    owner_id=user.id,
                    run_id=run.id,
                    source_repo=settings.source_repo,
                ),
            }

        candidate, eligibility = owner_candidate_for_apply_plan(
            session,
            owner_id=user.id,
            run=run,
        )
        drift = evaluate_source_drift(
            session,
            owner_id=user.id,
            run=run,
            candidate=candidate,
            source_repo=settings.source_repo,
            unavailable_blockers=(
                None if eligibility["eligible"] else eligibility["blockers"]
            ),
            unavailable_next_action=(
                None if eligibility["eligible"] else eligibility["next_action"]
            ),
        )
        if candidate is not None and candidate.result_envelope_id is not None:
            canonical_blockers = list(eligibility.get("blockers") or []) + list(
                json.loads(drift.blockers_json or "[]")
            )
            if not eligibility.get("eligible") or drift.status not in {
                "ready_to_apply",
                "source_changed_since_run",
            }:
                first = next(
                    (
                        item
                        for item in canonical_blockers
                        if isinstance(item, dict) and item.get("message")
                    ),
                    {
                        "code": "RESULT_CANDIDATE_NOT_ELIGIBLE",
                        "message": "Accept an eligible immutable Result Candidate before preparing an Apply Plan.",
                    },
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": str(first.get("code") or "RESULT_CANDIDATE_NOT_ELIGIBLE"),
                        "message": str(first.get("message")),
                    },
                )
        plan, created = get_or_create_apply_plan(
            session,
            owner_id=user.id,
            run=run,
            candidate=candidate,
            candidate_eligibility=eligibility,
            drift=drift,
            source_repo=settings.source_repo,
        )
        audit(
            session,
            request,
            "source_drift_evaluated",
            "source_drift_evaluation",
            drift.id,
            (
                f"run={run.id}; status={drift.status}; "
                "purpose=review_apply_plan"
            ),
            user,
        )
        audit(
            session,
            request,
            "apply_plan_created" if created else "apply_plan_retrieved",
            "apply_plan",
            plan.id,
            (
                f"run={run.id}; plan={plan.plan_id}; version={plan.plan_version}; "
                f"status={plan.status_at_creation}; digest={plan.plan_digest[:12]}"
            ),
            user,
        )
        return {
            "run_id": run.id,
            "plan": apply_plan_out(
                session,
                plan,
                source_repo=settings.source_repo,
            ),
            "history": apply_plan_history(
                session,
                owner_id=user.id,
                run_id=run.id,
                source_repo=settings.source_repo,
            ),
        }

    @app.get("/api/codex-runs/{run_id}/apply-plans")
    def get_current_apply_plan(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        return apply_plan_review_response(
            run_id,
            request,
            session,
            user,
            create=False,
        )

    @app.post("/api/codex-runs/{run_id}/apply-plans")
    def review_apply_plan(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            # Serialize the latest-version/idempotency decision without changing Git.
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        return apply_plan_review_response(
            run_id,
            request,
            session,
            user,
            create=True,
        )

    @app.get("/api/apply-plans/{plan_id}")
    def get_historical_apply_plan(
        plan_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        plan = session.scalar(
            select(ApplyPlan).where(
                ApplyPlan.plan_id == plan_id,
                ApplyPlan.owner_id == user.id,
            )
        )
        if plan is None or find_owner_run(session, user.id, plan.run_id) is None:
            # Missing and cross-Owner Plans are deliberately indistinguishable.
            raise HTTPException(status_code=404, detail="Apply Plan not found.")
        return {
            "run_id": plan.run_id,
            "plan": apply_plan_out(
                session,
                plan,
                source_repo=settings.source_repo,
            ),
            "history": apply_plan_history(
                session,
                owner_id=user.id,
                run_id=plan.run_id,
                source_repo=settings.source_repo,
            ),
        }

    def owner_apply_plan(
        session: Session,
        *,
        owner_id: int,
        plan_id: str,
    ) -> ApplyPlan | None:
        plan = session.scalar(
            select(ApplyPlan).where(
                ApplyPlan.plan_id == plan_id,
                ApplyPlan.owner_id == owner_id,
            )
        )
        if plan is None or find_owner_run(session, owner_id, plan.run_id) is None:
            return None
        return plan

    @app.post("/api/apply-plans/{plan_id}/approve")
    def approve_apply_plan(
        plan_id: str,
        payload: ApplyPlanApprovalIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        plan = owner_apply_plan(
            session,
            owner_id=user.id,
            plan_id=plan_id,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Apply Plan not found.")
        try:
            approval, created = get_or_create_apply_plan_approval(
                session,
                owner_id=user.id,
                plan=plan,
                source_repo=settings.source_repo,
                confirmed=payload.confirmation == "APPROVE_APPLY_PLAN",
                approved_by_user_id=user.id,
                expected_plan_digest=payload.expected_plan_digest,
                expected_candidate_digest=payload.expected_candidate_digest,
                expected_result_digest=payload.expected_result_digest,
                expected_result_review_decision_digest=(
                    payload.expected_result_review_decision_digest
                ),
            )
        except ApplyPlanError as exc:
            raise HTTPException(
                status_code=409,
                detail={"type": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "apply_plan_approved" if created else "apply_plan_approval_replayed",
            "apply_plan_approval",
            approval.id,
            (
                f"plan={plan.plan_id}; candidate={plan.candidate_public_id}; "
                f"result={plan.result_envelope_public_id}; no_apply=true"
            ),
            user,
        )
        session.flush()
        return {
            "run_id": plan.run_id,
            "plan": apply_plan_out(
                session,
                plan,
                source_repo=settings.source_repo,
            ),
            "approval": apply_plan_approval_out(approval),
            "approval_replayed": not created,
            "automatic_actions": [],
        }

    def normalized_apply_confirmation(
        confirmation: dict[str, Any],
    ) -> dict[str, Any]:
        value = dict(confirmation)
        included = list(value.get("included_files") or [])
        excluded = list(value.get("excluded_files") or [])
        blocked = list(value.get("blocked_files") or [])
        unrelated = list(value.get("unrelated_source_changes") or [])
        index = (
            dict(value.get("index_boundary") or {})
            if isinstance(value.get("index_boundary"), dict)
            else {}
        )
        value.update(
            {
                "included_paths": included,
                "excluded_paths": excluded,
                "blocked_paths": blocked,
                "unrelated_paths": unrelated,
                "entries": [
                    {**item, "disposition": "INCLUDED"}
                    for item in included
                    if isinstance(item, dict)
                ]
                + [
                    {**item, "disposition": "EXCLUDED"}
                    for item in excluded
                    if isinstance(item, dict)
                ]
                + [
                    {**item, "disposition": "BLOCKED"}
                    for item in blocked
                    if isinstance(item, dict)
                ],
                "drift_status": value.get("drift_state"),
                "drift_status_label": {
                    "ready_to_apply": "Ready to apply",
                    "source_changed_since_run": "Source changed since Run",
                    "conflict_detected": "Conflict detected",
                    "candidate_unavailable": "Candidate unavailable",
                    "repository_unavailable": "Repository unavailable",
                }.get(str(value.get("drift_state") or ""), "Not evaluated"),
                "staged_path_count": index.get("staged_path_count"),
                "index_boundary": (
                    "Index observed · staged paths "
                    + str(index.get("staged_path_count"))
                    if index.get("staged_path_count") is not None
                    else "Index boundary unavailable"
                ),
            }
        )
        return value

    def normalized_revert_confirmation(
        confirmation: dict[str, Any],
    ) -> dict[str, Any]:
        value = dict(confirmation)
        paths = list(value.get("paths") or [])
        unrelated = list(value.get("unrelated_source_changes") or [])
        index = (
            dict(value.get("index_boundary") or {})
            if isinstance(value.get("index_boundary"), dict)
            else {}
        )
        value.update(
            {
                "paths": paths,
                "reverse_operations": [
                    {
                        "path": item.get("path"),
                        "message": (
                            f"{item.get('path')} — {item.get('reverse_operation')}"
                        ),
                    }
                    for item in paths
                    if isinstance(item, dict)
                ],
                "preconditions": (
                    "Every session path must match its exact captured Apply "
                    "after-state before any reverse mutation."
                ),
                "unrelated_paths": unrelated,
                "staged_path_count": index.get("staged_path_count"),
                "index_boundary": (
                    "Index observed · staged paths "
                    + str(index.get("staged_path_count"))
                    if index.get("staged_path_count") is not None
                    else "Index boundary unavailable"
                ),
            }
        )
        return value

    def normalized_apply_session(
        session: Session,
        row: ApplySession,
    ) -> dict[str, Any]:
        value = apply_session_out(session, row)
        advanced = (
            dict(value.get("advanced") or {})
            if isinstance(value.get("advanced"), dict)
            else {}
        )
        state = str(value.get("state") or row.state)
        if state in {"REVERTING", "REVERTED", "REVERT_BLOCKED", "REVERT_FAILED_PARTIAL"}:
            apply_state = "APPLIED"
            revert_state = state
        else:
            apply_state = state
            revert_state = "NOT_REQUESTED"
        journal_digest = str(
            value.get("journal_digest")
            or advanced.get("journal_digest")
            or ""
        )
        advanced.update(
            {
                "apply_plan_id": row.apply_plan_public_id,
                "apply_plan_digest": row.apply_plan_digest,
                "candidate_id": row.candidate_public_id,
                "candidate_digest": row.candidate_digest,
                "journal_digest": journal_digest or None,
                "pre_apply_head": advanced.get("pre_apply_head")
                or advanced.get("head"),
                "pre_apply_index_fingerprint": (
                    advanced.get("pre_apply_index_fingerprint")
                    or advanced.get("index_fingerprint")
                ),
                "integrity": {
                    "result": value.get("integrity_check_result"),
                },
            }
        )
        value.update(
            {
                "apply_state": apply_state,
                "revert_state": revert_state,
                "journal_digest": journal_digest,
                "apply_finished_at": value.get("finished_at"),
                "advanced": advanced,
            }
        )
        return value

    def apply_session_review_response(
        session: Session,
        *,
        owner_id: int,
        plan: ApplyPlan,
        apply_session: ApplySession | None = None,
    ) -> dict[str, Any]:
        row = apply_session or session.scalar(
            select(ApplySession).where(
                ApplySession.owner_id == owner_id,
                ApplySession.apply_plan_id == plan.id,
            )
        )
        try:
            apply_confirmation = normalized_apply_confirmation(
                apply_confirmation_out(
                    session,
                    owner_id=owner_id,
                    plan=plan,
                    source_repo=settings.source_repo,
                )
            )
        except ApplySessionError as exc:
            apply_confirmation = {
                "eligible": False,
                "included_paths": [],
                "excluded_paths": [],
                "blocked_paths": [],
                "entries": [],
                "operation_counts": {"CREATE": 0, "MODIFY": 0, "DELETE": 0},
                "unrelated_paths": [],
                "index_boundary": "Index boundary unavailable",
                "blockers": [{"code": exc.code, "message": exc.message}],
            }
        public_session = (
            normalized_apply_session(session, row) if row is not None else None
        )
        revert_confirmation: dict[str, Any] = {}
        if row is not None:
            try:
                revert_confirmation = normalized_revert_confirmation(
                    revert_confirmation_out(
                        session,
                        owner_id=owner_id,
                        apply_session=row,
                        source_repo=settings.source_repo,
                    )
                )
            except ApplySessionError as exc:
                revert_confirmation = {
                    "eligible": False,
                    "paths": [],
                    "blockers": [{"code": exc.code, "message": exc.message}],
                }
        can_apply = row is None and apply_confirmation.get("eligible") is True
        can_revert = (
            row is not None
            and revert_confirmation.get("eligible") is True
        )
        if public_session is not None:
            blockers = list(public_session.get("blockers") or [])
            if row is not None and row.state == "APPLIED":
                blockers = list(revert_confirmation.get("blockers") or [])
            next_action = str(
                public_session.get("next_action")
                or "Review the persisted Apply session."
            )
            readiness_label = str(public_session.get("status_label") or row.state)
        else:
            blockers = list(apply_confirmation.get("blockers") or [])
            if can_apply:
                next_action = (
                    "Select Apply Accepted Changes, review the final confirmation, "
                    "then explicitly confirm."
                )
            elif blockers:
                next_action = str(
                    blockers[0].get("message")
                    or "Resolve the Apply preflight blocker."
                )
            else:
                next_action = "Review Apply readiness."
            readiness_label = (
                "READY TO APPLY" if can_apply else "PREFLIGHT BLOCKED"
            )
        state = str(row.state if row is not None else "")
        execution_state = {
            "": "Pending",
            "APPLYING": "Running",
            "APPLIED": "Applied",
            "REVERTING": "Running",
            "REVERTED": "Reverted",
            "PREFLIGHT_BLOCKED": "Blocked",
            "REVERT_BLOCKED": "Blocked",
            "APPLY_FAILED_RECOVERED": "Failed",
            "APPLY_FAILED_PARTIAL": "Failed",
            "REVERT_FAILED_PARTIAL": "Failed",
        }.get(state, "Failed")
        changed_file_count = (
            sum(
                1
                for item in list(public_session.get("files") or [])
                if isinstance(item, dict)
                and str(item.get("apply_result") or "") == "APPLIED"
            )
            if public_session is not None
            else 0
        )
        validation_result = (
            str(public_session.get("integrity_check_result") or "NOT RUN")
            if public_session is not None
            else "NOT RUN"
        )
        result_summary = {
            "Pending": "Awaiting explicit Owner confirmation.",
            "Running": "The confirmed path-scoped operation is still running.",
            "Applied": f"Applied {changed_file_count} approved file(s).",
            "Reverted": f"Restored {changed_file_count} execution-owned file(s).",
            "Blocked": "No unsafe file overwrite was performed.",
            "Failed": "The operation failed; review recovery and blocker details.",
        }[execution_state]
        plan_approval_state = str(
            apply_confirmation.get("approval_state")
            or (
                "LEGACY_CONFIRMATION_ONLY"
                if plan.result_envelope_id is None
                else "PENDING"
            )
        )
        apply_confirmation_state = "CONFIRMED" if row is not None else "PENDING"
        return {
            "plan_id": plan.plan_id,
            "session": public_session,
            "actions": {
                "can_apply": can_apply,
                "can_revert": can_revert,
            },
            "readiness_label": readiness_label,
            "blockers": blockers,
            "next_action": next_action,
            # Preserve the historical 19.1A label for legacy Plans while the
            # canonical Result-bound path exposes Plan approval and the later
            # Apply confirmation as two independent Owner decisions.
            "approval_state": (
                plan_approval_state
                if plan.result_envelope_id is not None
                else "OWNER CONFIRMED"
                if row is not None
                else "AWAITING OWNER CONFIRMATION"
            ),
            "plan_approval_state": plan_approval_state,
            "apply_confirmation_state": apply_confirmation_state,
            "execution_state": execution_state,
            "result_summary": result_summary,
            "changed_file_count": changed_file_count,
            "validation_result": validation_result,
            "recovery_available": bool(
                public_session is not None
                and (
                    public_session.get("revert_available") is True
                    or state in {"APPLY_FAILED_RECOVERED", "REVERTED"}
                )
            ),
            "apply_confirmation": apply_confirmation,
            "revert_confirmation": revert_confirmation,
        }

    @app.get("/api/apply-plans/{plan_id}/apply-sessions")
    def get_apply_session_review(
        plan_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        plan = owner_apply_plan(
            session,
            owner_id=user.id,
            plan_id=plan_id,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Apply Plan not found.")
        return apply_session_review_response(
            session,
            owner_id=user.id,
            plan=plan,
        )

    @app.post("/api/apply-plans/{plan_id}/apply-sessions")
    def apply_plan_accepted_changes(
        plan_id: str,
        payload: ApplyAcceptedChangesIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        plan = owner_apply_plan(
            session,
            owner_id=user.id,
            plan_id=plan_id,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Apply Plan not found.")
        candidate = (
            session.get(DeliveryCandidate, plan.delivery_candidate_id)
            if plan.delivery_candidate_id is not None
            else None
        )
        if (
            payload.expected_plan_digest != plan.plan_digest
            or candidate is None
            or payload.expected_candidate_digest != candidate.candidate_digest
            or (
                plan.result_envelope_id is not None
                and (
                    payload.expected_result_digest != plan.result_digest
                    or payload.expected_result_review_decision_digest
                    != plan.result_review_decision_digest
                    or payload.expected_plan_approval_digest is None
                )
            )
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "APPLY_CONFIRMATION_BINDING_CHANGED",
                    "message": (
                        "The confirmed Plan or Candidate identity changed. "
                        "Review Apply readiness again."
                    ),
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        try:
            row, created = apply_accepted_changes(
                session,
                owner_id=user.id,
                plan=plan,
                source_repo=settings.source_repo,
                confirmed=payload.confirmation == "APPLY_ACCEPTED_CHANGES",
                expected_plan_digest=payload.expected_plan_digest,
                expected_candidate_digest=payload.expected_candidate_digest,
                expected_plan_approval_digest=(
                    payload.expected_plan_approval_digest
                ),
                expected_result_digest=payload.expected_result_digest,
                expected_result_review_decision_digest=(
                    payload.expected_result_review_decision_digest
                ),
            )
        except ApplySessionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "apply_session_created" if created else "apply_session_retrieved",
            "apply_session",
            row.id,
            (
                f"plan={plan.plan_id}; session={row.session_id}; "
                f"state={row.state}"
            ),
            user,
        )
        session.commit()
        return apply_session_review_response(
            session,
            owner_id=user.id,
            plan=plan,
            apply_session=row,
        )

    @app.get("/api/apply-sessions/{session_id}")
    def get_apply_session(
        session_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        row = find_owned_apply_session(
            session,
            owner_id=user.id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        plan = session.get(ApplyPlan, row.apply_plan_id)
        if plan is None or owner_apply_plan(
            session,
            owner_id=user.id,
            plan_id=plan.plan_id,
        ) is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        return apply_session_review_response(
            session,
            owner_id=user.id,
            plan=plan,
            apply_session=row,
        )

    @app.get("/api/codex-runs/{run_id}/delivery")
    def get_result_delivery_projection(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        """One refresh-safe Owner projection for the complete delivery lineage."""
        run = owner_run_or_404(session, user.id, run_id)
        envelope = session.scalar(
            select(CodexResultEnvelope).where(
                CodexResultEnvelope.owner_id == user.id,
                CodexResultEnvelope.run_id == run.id,
            )
        )
        candidate_review = delivery_candidate_review_response(
            run.id,
            request,
            session,
            user,
            create=False,
        )
        candidate = session.scalar(
            select(DeliveryCandidate).where(
                DeliveryCandidate.owner_id == user.id,
                DeliveryCandidate.run_id == run.id,
            )
        )
        acceptance = session.scalar(
            select(OwnerAcceptanceSession).where(
                OwnerAcceptanceSession.owner_id == user.id,
                OwnerAcceptanceSession.codex_run_id == run.id,
            )
        )
        plan = latest_apply_plan(session, user.id, run.id)
        plan_view = (
            apply_plan_out(session, plan, source_repo=settings.source_repo)
            if plan is not None
            else None
        )
        apply_view = (
            apply_session_review_response(
                session,
                owner_id=user.id,
                plan=plan,
            )
            if plan is not None
            else None
        )
        apply_row = (
            session.scalar(
                select(ApplySession).where(
                    ApplySession.owner_id == user.id,
                    ApplySession.apply_plan_id == plan.id,
                )
            )
            if plan is not None
            else None
        )
        verification = (
            session.scalar(
                select(PostApplyVerification)
                .where(
                    PostApplyVerification.owner_id == user.id,
                    PostApplyVerification.apply_session_id == apply_row.id,
                )
                .order_by(PostApplyVerification.id.desc())
                .limit(1)
            )
            if apply_row is not None
            else None
        )
        post_apply_view = (
            post_apply_verification_review(
                session,
                owner_id=user.id,
                apply_session=apply_row,
            )
            if apply_row is not None
            else None
        )
        commit_delivery = (
            owner_commit_api_review(
                session,
                owner_id=user.id,
                verification=verification,
            )
            if verification is not None and verification.status == "PASSED"
            else None
        )
        commit_execution_view = (
            ((commit_delivery.get("proposal") or {}).get("commit"))
            if isinstance(commit_delivery, dict)
            else None
        )
        local_commit = (
            find_owned_local_commit_execution(
                session,
                owner_id=user.id,
                commit_execution_id=str(commit_execution_view.get("id") or ""),
            )
            if isinstance(commit_execution_view, dict)
            and str(commit_execution_view.get("state") or "") == "COMMITTED"
            else None
        )
        push_delivery = (
            push_plan_api_review(
                session,
                owner_id=user.id,
                local_commit=local_commit,
            )
            if local_commit is not None
            else None
        )
        review_view = (
            owner_acceptance_out(session, acceptance)
            if acceptance is not None
            else None
        )
        candidate_view = candidate_review.get("candidate") or {}
        review_state = str(
            (review_view or {}).get("review_state") or "unavailable"
        )
        readiness_state = str(candidate_view.get("readiness_state") or "unavailable")
        drift_state = str(
            (candidate_review.get("drift") or {}).get("status") or "unavailable"
        )
        persisted_apply_state = str(
            ((apply_view or {}).get("session") or {}).get("state") or ""
        )
        primary_action: dict[str, Any] | None = None
        secondary_actions: list[dict[str, Any]] = []
        next_action = "Review the captured Run Result."
        if envelope is None or candidate is None or acceptance is None:
            next_action = "Wait for one immutable Run Result and Review Candidate."
        elif review_state == "pending":
            primary_action = {
                "code": "accept_result_for_delivery",
                "label": "Accept for Delivery",
            }
            secondary_actions = [
                {"code": "reject_result", "label": "Reject Result"}
            ]
            next_action = "Accept or reject this exact Result for delivery."
        elif review_state == "rejected":
            next_action = "This Result was rejected; start a new approved Run if needed."
        elif persisted_apply_state:
            # Once an Apply session exists it is the authoritative downstream
            # lifecycle.  In particular, the exact intended source mutation
            # makes a fresh Candidate-drift evaluation look plan-impacting;
            # that upstream observation must not hide an eligible Revert or
            # overwrite a persisted Reverted terminal state on refresh.
            if persisted_apply_state == "APPLIED":
                commit_proposal = (
                    commit_delivery.get("proposal")
                    if isinstance(commit_delivery, dict)
                    else None
                )
                commit_actions = (
                    commit_proposal.get("actions")
                    if isinstance(commit_proposal, dict)
                    else {}
                )
                commit_execution = (
                    commit_proposal.get("commit")
                    if isinstance(commit_proposal, dict)
                    else None
                )
                if verification is None:
                    # Preserve the accepted 19.1C Applied-state projection:
                    # working-tree Revert remains the primary recovery action
                    # until post-Apply validation exists.  Validation is the
                    # explicit secondary step that unlocks Commit review.
                    if (apply_view.get("actions") or {}).get("can_revert") is True:
                        primary_action = {
                            "code": "revert_applied_changes",
                            "label": "Revert Applied Changes",
                        }
                    secondary_actions = [
                        {
                            "code": "verify_applied_changes",
                            "label": "Validate Applied Changes",
                        }
                    ]
                    next_action = "Run the separate Post-Apply Validation before Commit review."
                elif verification.status != "PASSED":
                    next_action = "Resolve the Post-Apply Validation blocker before Commit review."
                elif commit_proposal is None:
                    primary_action = {
                        "code": "review_commit",
                        "label": "Review Commit",
                    }
                    next_action = "Review the exact local Commit proposal."
                elif commit_actions.get("can_approve") is True:
                    primary_action = {
                        "code": "approve_commit",
                        "label": "Approve Commit",
                    }
                    next_action = "Approve this exact Commit proposal version."
                elif commit_actions.get("can_commit") is True:
                    primary_action = {
                        "code": "confirm_local_commit",
                        "label": "Confirm Local Commit",
                    }
                    next_action = "Explicitly confirm one exact local Commit. Local Commit does not Push."
                elif isinstance(commit_execution, dict) and str(
                    commit_execution.get("state") or ""
                ) == "COMMITTED":
                    push_plan = (
                        push_delivery.get("push_plan")
                        if isinstance(push_delivery, dict)
                        else None
                    )
                    push_actions = (
                        push_delivery.get("actions")
                        if isinstance(push_delivery, dict)
                        else {}
                    )
                    push_execution = (
                        push_delivery.get("push_execution")
                        if isinstance(push_delivery, dict)
                        else None
                    )
                    delivery_result = (
                        push_delivery.get("delivery_result")
                        if isinstance(push_delivery, dict)
                        else None
                    )
                    if push_plan is None:
                        primary_action = {
                            "code": "review_push_plan",
                            "label": "Review Push Plan",
                        }
                        next_action = "Review the exact remote, branch, old SHA, and new SHA."
                    elif push_actions.get("can_review_push_plan") is True:
                        primary_action = {
                            "code": "review_push_plan",
                            "label": "Review Push Plan",
                        }
                        next_action = (
                            "Review a fresh Push Plan; the previous approved Plan "
                            "expired without an execution."
                        )
                    elif push_actions.get("can_approve_push_plan") is True:
                        primary_action = {
                            "code": "approve_push_plan",
                            "label": "Approve Push Plan",
                        }
                        next_action = "Approve this exact immutable Push Plan."
                    elif push_actions.get("can_confirm_push") is True:
                        primary_action = {
                            "code": "confirm_push",
                            "label": "Confirm Push",
                        }
                        next_action = "Explicitly confirm one exact non-force Push."
                    elif (
                        isinstance(delivery_result, dict)
                        and str(delivery_result.get("status") or "").lower()
                        in {"delivered", "already_delivered", "succeeded"}
                    ):
                        next_action = "Delivery is verified at the approved remote branch."
                    elif isinstance(push_execution, dict):
                        next_action = str(
                            (delivery_result or {}).get("next_action")
                            or "Review the persisted Push result."
                        )
                    else:
                        plan_blockers = list((push_plan or {}).get("blockers") or [])
                        next_action = str(
                            (
                                plan_blockers[0].get("message")
                                if plan_blockers
                                and isinstance(plan_blockers[0], dict)
                                else None
                            )
                            or "Review Push readiness."
                        )
                else:
                    commit_blockers = list(
                        (commit_proposal or {}).get("blockers") or []
                    )
                    next_action = str(
                        (
                            commit_blockers[0].get("message")
                            if commit_blockers
                            and isinstance(commit_blockers[0], dict)
                            else None
                        )
                        or (commit_delivery or {}).get("next_action")
                        or "Review the persisted Commit state."
                    )
                if (
                    verification is not None
                    and
                    not isinstance(commit_execution, dict)
                    and (apply_view.get("actions") or {}).get("can_revert") is True
                ):
                    secondary_actions = [
                        {
                            "code": "revert_applied_changes",
                            "label": "Revert Applied Changes",
                        }
                    ]
            elif persisted_apply_state == "REVERTED":
                next_action = (
                    "Delivery is reverted; the immutable Run Result remains available."
                )
            else:
                blockers = list(apply_view.get("blockers") or [])
                next_action = str(
                    (
                        blockers[0].get("message")
                        if blockers and isinstance(blockers[0], dict)
                        else None
                    )
                    or apply_view.get("next_action")
                    or "Review the persisted delivery state."
                )
        elif readiness_state == "no_changes":
            next_action = "No attributed deliverable change is available to apply."
        elif readiness_state != "ready" or drift_state in {
            "conflict_detected",
            "candidate_unavailable",
            "repository_unavailable",
        }:
            next_action = str(
                candidate_review.get("next_action")
                or "Resolve the Candidate or source-drift blocker."
            )
        elif plan is None:
            primary_action = {
                "code": "review_apply_plan",
                "label": "Review Apply Plan",
            }
            next_action = "Prepare the immutable Apply Plan from this accepted Candidate."
        elif str((plan_view or {}).get("approval_state")) == "PENDING":
            primary_action = {
                "code": "approve_apply_plan",
                "label": "Approve Apply Plan",
            }
            next_action = "Approve this exact current Apply Plan."
        elif apply_view and (apply_view.get("actions") or {}).get("can_apply") is True:
            primary_action = {
                "code": "apply_accepted_changes",
                "label": "Apply Accepted Changes",
            }
            next_action = "Review the final path scope and explicitly confirm Apply."
        elif apply_view:
            next_action = str(
                apply_view.get("next_action") or "Review the persisted delivery state."
            )
        return {
            "run_id": run.id,
            "result": (
                result_envelope_out(envelope, advanced=False)
                if envelope is not None
                else None
            ),
            "result_review": review_view,
            "candidate": candidate_review,
            "apply_plan": plan_view,
            "apply_session": apply_view,
            "post_apply_verification": post_apply_view,
            "commit_delivery": commit_delivery,
            "push_delivery": push_delivery,
            "next_action": {
                "primary": primary_action,
                "secondary": secondary_actions,
                "message": next_action,
            },
            "automatic_actions": [],
            "boundaries": [
                "Candidate materialization changes metadata only.",
                "Result acceptance and Apply Plan approval never mutate source.",
                "Apply and Revert require their own explicit confirmations.",
                "Commit proposal approval and local Commit confirmation are separate.",
                "Push Plan approval and Push confirmation are separate.",
                "No automatic Stage, Commit, Push, Run, or connector action occurs.",
            ],
        }

    @app.get("/api/apply-sessions/{session_id}/post-apply-verifications")
    def get_post_apply_verification_review(
        session_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        row = find_owned_apply_session(
            session,
            owner_id=user.id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        return post_apply_verification_review(
            session,
            owner_id=user.id,
            apply_session=row,
        )

    @app.post("/api/apply-sessions/{session_id}/post-apply-verifications")
    def verify_applied_changes(
        session_id: str,
        payload: PostApplyVerificationIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        row = find_owned_apply_session(
            session,
            owner_id=user.id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            row = find_owned_apply_session(
                session,
                owner_id=user.id,
                session_id=session_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Apply session not found.")
        try:
            verification, created = get_or_create_post_apply_verification(
                session,
                owner_id=user.id,
                apply_session=row,
                source_repo=settings.source_repo,
                expected_journal_digest=payload.expected_journal_digest,
            )
        except PostApplyVerificationError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            (
                "post_apply_verification_created"
                if created
                else "post_apply_verification_retrieved"
            ),
            "post_apply_verification",
            verification.id,
            (
                f"apply_session={row.session_id}; "
                f"verification={verification.verification_id}; "
                f"status={verification.status}"
            ),
            user,
        )
        session.commit()
        return post_apply_verification_review(
            session,
            owner_id=user.id,
            apply_session=row,
        )

    def commit_builder_api_review(
        session: Session,
        *,
        owner_id: int,
        verification: PostApplyVerification,
        effective_status_override: str | None = None,
    ) -> dict[str, Any]:
        try:
            review = commit_builder_review(
                session,
                owner_id=owner_id,
                post_apply_verification=verification,
                source_repo=settings.source_repo,
                effective_status_override=effective_status_override,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        plan = review.get("plan") if isinstance(review.get("plan"), dict) else None
        eligibility = (
            review.get("eligibility")
            if isinstance(review.get("eligibility"), dict)
            else {}
        )
        plan_actions = (
            plan.get("actions")
            if plan is not None and isinstance(plan.get("actions"), dict)
            else {}
        )
        stage = plan.get("stage") if plan is not None else None
        commit = plan.get("commit") if plan is not None else None
        stage_state = str((stage or {}).get("state") or "").upper()
        commit_state = str((commit or {}).get("state") or "").upper()
        plan_status = str((plan or {}).get("status") or "").upper()
        eligibility_status = str(eligibility.get("status") or "").upper()
        if commit_state == "COMMITTED":
            action_state = "COMMITTED"
        elif commit_state in {"BLOCKED", "FAILED", "INTEGRITY_BLOCKED", "COMMITTING"}:
            action_state = "COMMIT_BLOCKED"
        elif stage_state == "STAGED" and plan_actions.get("can_commit") is True:
            action_state = "READY_TO_COMMIT"
        elif plan_status in {"BLOCKED", "EXPIRED"} or eligibility_status in {"BLOCKED", "EXPIRED"}:
            action_state = "STAGING_BLOCKED"
        elif plan is not None and plan_actions.get("can_stage") is True:
            action_state = "READY_TO_STAGE"
        else:
            action_state = "REVIEW_REQUIRED"
        review.update(
            {
                "post_apply_verification_id": verification.verification_id,
                "verification_id": verification.verification_id,
                "stage": stage,
                "commit": commit,
                "action_state": action_state,
                "actions": {
                    "can_review_commit_plan": bool(
                        eligibility.get("can_review") is True
                        and action_state != "COMMITTED"
                    ),
                    "can_stage_approved_files": action_state == "READY_TO_STAGE",
                    "can_create_local_commit": action_state == "READY_TO_COMMIT",
                },
            }
        )
        return review

    def owner_commit_api_review(
        session: Session,
        *,
        owner_id: int,
        verification: PostApplyVerification,
    ) -> dict[str, Any]:
        try:
            review = owner_commit_review(
                session,
                owner_id=owner_id,
                post_apply_verification=verification,
                source_repo=settings.source_repo,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        review["post_apply_verification_id"] = verification.verification_id
        review["verification_id"] = verification.verification_id
        return review

    @app.get("/api/post-apply-verifications/{verification_id}/commit-proposals")
    def get_owner_commit_proposal(
        verification_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        verification = find_owned_post_apply_verification(
            session,
            owner_id=user.id,
            verification_id=verification_id,
        )
        if verification is None:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        return owner_commit_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )

    @app.post("/api/post-apply-verifications/{verification_id}/commit-proposals")
    def review_owner_commit_proposal(
        verification_id: str,
        payload: ReviewCommitProposalIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        verification = find_owned_post_apply_verification(
            session,
            owner_id=user.id,
            verification_id=verification_id,
        )
        if verification is None:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            verification = find_owned_post_apply_verification(
                session,
                owner_id=user.id,
                verification_id=verification_id,
            )
            if verification is None:
                raise HTTPException(status_code=404, detail="Commit delivery not found.")
        if payload.expected_verification_digest != verification.verification_digest:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "VERIFICATION_CHANGED",
                    "message": "The Post-Apply Verification identity changed.",
                },
            )
        try:
            proposal, created = create_commit_proposal(
                session,
                owner_id=user.id,
                post_apply_verification=verification,
                source_repo=settings.source_repo,
                subject=payload.subject,
                body=payload.body,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "commit_proposal_created" if created else "commit_proposal_retrieved",
            "commit_proposal",
            proposal.id,
            (
                f"verification={verification.verification_id}; "
                f"proposal={proposal.proposal_id}; version={proposal.version}"
            ),
            user,
        )
        session.commit()
        return owner_commit_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )

    @app.post("/api/commit-proposals/{proposal_id}/approvals")
    def approve_owner_commit_proposal(
        proposal_id: str,
        payload: ApproveCommitProposalIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        proposal = find_owned_commit_proposal(
            session,
            owner_id=user.id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            proposal = find_owned_commit_proposal(
                session,
                owner_id=user.id,
                proposal_id=proposal_id,
            )
            if proposal is None:
                raise HTTPException(status_code=404, detail="Commit delivery not found.")
        if payload.expected_proposal_version != proposal.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMMIT_PROPOSAL_CHANGED",
                    "message": "The Commit proposal version changed.",
                },
            )
        try:
            approval, created = approve_commit_proposal(
                session,
                owner_id=user.id,
                proposal=proposal,
                expected_proposal_digest=payload.expected_proposal_digest,
                confirmation=payload.confirmation,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        verification = session.get(PostApplyVerification, proposal.post_apply_verification_id)
        if verification is None or verification.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        audit(
            session,
            request,
            "commit_proposal_approved" if created else "commit_proposal_approval_replayed",
            "commit_proposal_approval",
            approval.id,
            f"proposal={proposal.proposal_id}; approval={approval.approval_id}",
            user,
        )
        session.commit()
        response = owner_commit_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )
        response["approval_replayed"] = not created
        response["automatic_actions"] = []
        return response

    @app.post("/api/commit-proposals/{proposal_id}/local-commits")
    def confirm_owner_approved_local_commit(
        proposal_id: str,
        payload: ConfirmApprovedLocalCommitIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        proposal = find_owned_commit_proposal(
            session,
            owner_id=user.id,
            proposal_id=proposal_id,
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        approval = session.scalar(
            select(CommitProposalApproval).where(
                CommitProposalApproval.owner_id == user.id,
                CommitProposalApproval.commit_proposal_id == proposal.id,
            )
        )
        if approval is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMMIT_APPROVAL_REQUIRED",
                    "message": "Approve this exact Commit proposal before confirmation.",
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            proposal = find_owned_commit_proposal(
                session,
                owner_id=user.id,
                proposal_id=proposal_id,
            )
            approval = (
                session.scalar(
                    select(CommitProposalApproval).where(
                        CommitProposalApproval.owner_id == user.id,
                        CommitProposalApproval.commit_proposal_id == proposal.id,
                    )
                )
                if proposal is not None
                else None
            )
            if proposal is None or approval is None:
                raise HTTPException(status_code=404, detail="Commit delivery not found.")
        try:
            execution, created = confirm_local_commit(
                session,
                owner_id=user.id,
                proposal=proposal,
                approval=approval,
                source_repo=settings.source_repo,
                expected_proposal_digest=payload.expected_proposal_digest,
                expected_approval_digest=payload.expected_approval_digest,
                confirmation=payload.confirmation,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        verification = session.get(PostApplyVerification, proposal.post_apply_verification_id)
        if verification is None or verification.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Commit delivery not found.")
        audit(
            session,
            request,
            "owner_local_commit_completed" if created else "owner_local_commit_retrieved",
            "local_commit_execution",
            execution.id,
            (
                f"proposal={proposal.proposal_id}; "
                f"commit={execution.commit_execution_id}; state={execution.state}"
            ),
            user,
        )
        session.commit()
        response = owner_commit_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )
        response["commit_replayed"] = not created
        response["automatic_actions"] = []
        return response

    def owned_commit_plan_verification(
        session: Session,
        *,
        owner_id: int,
        commit_plan_id: str,
    ) -> tuple[CommitPlan, PostApplyVerification]:
        plan = find_owned_commit_plan(
            session,
            owner_id=owner_id,
            commit_plan_id=commit_plan_id,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        verification = session.get(PostApplyVerification, plan.post_apply_verification_id)
        if verification is None or verification.owner_id != owner_id:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        return plan, verification

    def owned_stage_commit_context(
        session: Session,
        *,
        owner_id: int,
        stage_execution_id: str,
    ) -> tuple[StageExecution, CommitPlan, PostApplyVerification]:
        stage_execution = find_owned_stage_execution(
            session,
            owner_id=owner_id,
            stage_execution_id=stage_execution_id,
        )
        if stage_execution is None:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        plan = session.get(CommitPlan, stage_execution.commit_plan_id)
        if plan is None or plan.owner_id != owner_id:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        verification = session.get(PostApplyVerification, plan.post_apply_verification_id)
        if verification is None or verification.owner_id != owner_id:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        return stage_execution, plan, verification

    @app.get("/api/post-apply-verifications/{verification_id}/commit-plans")
    def get_commit_plan_review(
        verification_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        verification = find_owned_post_apply_verification(
            session,
            owner_id=user.id,
            verification_id=verification_id,
        )
        if verification is None:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )

    @app.post("/api/post-apply-verifications/{verification_id}/commit-plans")
    def review_commit_plan(
        verification_id: str,
        payload: ReviewCommitPlanIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        verification = find_owned_post_apply_verification(
            session,
            owner_id=user.id,
            verification_id=verification_id,
        )
        if verification is None:
            raise HTTPException(status_code=404, detail="Commit workflow not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            verification = find_owned_post_apply_verification(
                session,
                owner_id=user.id,
                verification_id=verification_id,
            )
            if verification is None:
                raise HTTPException(status_code=404, detail="Commit workflow not found.")
        if payload.expected_verification_digest != verification.verification_digest:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "VERIFICATION_CHANGED",
                    "message": "The Post-Apply Verification identity changed.",
                },
            )
        try:
            plan, created = get_or_create_commit_plan(
                session,
                owner_id=user.id,
                post_apply_verification=verification,
                source_repo=settings.source_repo,
                subject=payload.subject,
                body=payload.body,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "commit_plan_created" if created else "commit_plan_retrieved",
            "commit_plan",
            plan.id,
            f"verification={verification.verification_id}; plan={plan.commit_plan_id}",
            user,
        )
        session.commit()
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
            effective_status_override=(plan.status_at_creation if created else None),
        )

    @app.get("/api/commit-plans/{commit_plan_id}/stage-sessions")
    def get_stage_session_review(
        commit_plan_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        _plan, verification = owned_commit_plan_verification(
            session,
            owner_id=user.id,
            commit_plan_id=commit_plan_id,
        )
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )

    @app.post("/api/commit-plans/{commit_plan_id}/stage-sessions")
    def stage_approved_files(
        commit_plan_id: str,
        payload: StageApprovedFilesIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        plan, verification = owned_commit_plan_verification(
            session,
            owner_id=user.id,
            commit_plan_id=commit_plan_id,
        )
        bound_apply = session.get(ApplySession, plan.apply_session_id)
        if bound_apply is not None and bound_apply.result_envelope_id is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMMIT_PROPOSAL_APPROVAL_REQUIRED",
                    "message": (
                        "Result-bound delivery requires Review Commit, explicit "
                        "proposal approval, and a separate final Commit confirmation."
                    ),
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            plan, verification = owned_commit_plan_verification(
                session,
                owner_id=user.id,
                commit_plan_id=commit_plan_id,
            )
        try:
            stage_execution, created = stage_commit_plan(
                session,
                owner_id=user.id,
                plan=plan,
                source_repo=settings.source_repo,
                expected_plan_digest=payload.expected_plan_digest,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "stage_execution_created" if created else "stage_execution_retrieved",
            "stage_execution",
            stage_execution.id,
            f"plan={plan.commit_plan_id}; stage={stage_execution.stage_execution_id}",
            user,
        )
        session.commit()
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
            effective_status_override=("STAGED" if created else None),
        )

    @app.get("/api/stage-sessions/{stage_execution_id}/local-commits")
    def get_local_commit_review(
        stage_execution_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        _stage, _plan, verification = owned_stage_commit_context(
            session,
            owner_id=user.id,
            stage_execution_id=stage_execution_id,
        )
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
        )

    @app.post("/api/stage-sessions/{stage_execution_id}/local-commits")
    def create_owner_local_commit(
        stage_execution_id: str,
        payload: CreateLocalCommitIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        stage_execution, plan, verification = owned_stage_commit_context(
            session,
            owner_id=user.id,
            stage_execution_id=stage_execution_id,
        )
        bound_apply = session.get(ApplySession, plan.apply_session_id)
        if bound_apply is not None and bound_apply.result_envelope_id is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COMMIT_PROPOSAL_APPROVAL_REQUIRED",
                    "message": (
                        "Result-bound delivery requires the approved Commit "
                        "proposal confirmation route."
                    ),
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            stage_execution, plan, verification = owned_stage_commit_context(
                session,
                owner_id=user.id,
                stage_execution_id=stage_execution_id,
            )
        try:
            commit_execution, created = create_local_commit(
                session,
                owner_id=user.id,
                plan=plan,
                stage_execution=stage_execution,
                source_repo=settings.source_repo,
                expected_plan_digest=payload.expected_plan_digest,
                expected_stage_digest=payload.expected_stage_digest,
            )
        except CommitBuilderError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            (
                "local_commit_execution_created"
                if created
                else "local_commit_execution_retrieved"
            ),
            "local_commit_execution",
            commit_execution.id,
            (
                f"stage={stage_execution.stage_execution_id}; "
                f"commit={commit_execution.commit_execution_id}"
            ),
            user,
        )
        session.commit()
        return commit_builder_api_review(
            session,
            owner_id=user.id,
            verification=verification,
            effective_status_override=(
                "COMMITTED"
                if created and commit_execution.state == "COMMITTED"
                else None
            ),
        )

    def push_delivery_api_review(
        session: Session,
        *,
        owner_id: int,
        local_commit: LocalCommitExecution,
    ) -> dict[str, Any]:
        try:
            return push_delivery_review(
                session,
                owner_id=owner_id,
                local_commit=local_commit,
                source_repo=settings.source_repo,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    def push_plan_api_review(
        session: Session,
        *,
        owner_id: int,
        local_commit: LocalCommitExecution,
    ) -> dict[str, Any]:
        try:
            return push_plan_review(
                session,
                owner_id=owner_id,
                local_commit=local_commit,
                source_repo=settings.source_repo,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @app.get("/api/local-commits/{commit_execution_id}/push-plans")
    def get_owner_push_plan(
        commit_execution_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        local_commit = find_owned_local_commit_execution(
            session,
            owner_id=user.id,
            commit_execution_id=commit_execution_id,
        )
        if local_commit is None:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        return push_plan_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )

    @app.post("/api/local-commits/{commit_execution_id}/push-plans")
    def review_owner_push_plan(
        commit_execution_id: str,
        request: Request,
        payload: CreatePushPreflightIn | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        del payload
        local_commit = find_owned_local_commit_execution(
            session,
            owner_id=user.id,
            commit_execution_id=commit_execution_id,
        )
        if local_commit is None:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            local_commit = find_owned_local_commit_execution(
                session,
                owner_id=user.id,
                commit_execution_id=commit_execution_id,
            )
            if local_commit is None:
                raise HTTPException(status_code=404, detail="Push delivery not found.")
        try:
            push_plan, created = get_or_create_push_plan(
                session,
                owner_id=user.id,
                local_commit=local_commit,
                source_repo=settings.source_repo,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "push_plan_created" if created else "push_plan_retrieved",
            "push_plan",
            push_plan.id,
            (
                f"commit={local_commit.commit_execution_id}; "
                f"plan={push_plan.push_plan_id}; version={push_plan.version}"
            ),
            user,
        )
        session.commit()
        return push_plan_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )

    @app.post("/api/push-plans/{push_plan_id}/approvals")
    def approve_owner_push_plan(
        push_plan_id: str,
        payload: ApprovePushPlanIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        push_plan = find_owned_push_plan(
            session,
            owner_id=user.id,
            push_plan_id=push_plan_id,
        )
        if push_plan is None:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            push_plan = find_owned_push_plan(
                session,
                owner_id=user.id,
                push_plan_id=push_plan_id,
            )
            if push_plan is None:
                raise HTTPException(status_code=404, detail="Push delivery not found.")
        if payload.expected_plan_version != push_plan.version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PUSH_PLAN_CHANGED",
                    "message": "The Push Plan version changed.",
                },
            )
        try:
            approval, created = approve_push_plan(
                session,
                owner_id=user.id,
                push_plan=push_plan,
                source_repo=settings.source_repo,
                expected_plan_digest=payload.expected_plan_digest,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        local_commit = session.get(
            LocalCommitExecution, push_plan.local_commit_execution_id
        )
        if local_commit is None or local_commit.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        audit(
            session,
            request,
            "push_plan_approved" if created else "push_plan_approval_replayed",
            "push_plan_approval",
            approval.id,
            f"plan={push_plan.push_plan_id}; approval={approval.approval_id}",
            user,
        )
        session.commit()
        response = push_plan_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )
        response["approval_replayed"] = not created
        response["automatic_actions"] = []
        return response

    @app.post("/api/push-plans/{push_plan_id}/push-attempts")
    def confirm_owner_approved_push(
        push_plan_id: str,
        payload: ConfirmApprovedPushIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        push_plan = find_owned_push_plan(
            session,
            owner_id=user.id,
            push_plan_id=push_plan_id,
        )
        if push_plan is None:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        approval = session.scalar(
            select(PushPlanApproval).where(
                PushPlanApproval.owner_id == user.id,
                PushPlanApproval.push_plan_id == push_plan.id,
            )
        )
        local_commit = session.get(
            LocalCommitExecution, push_plan.local_commit_execution_id
        )
        if approval is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PUSH_APPROVAL_REQUIRED",
                    "message": "Approve this exact Push Plan before confirmation.",
                },
            )
        if local_commit is None or local_commit.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Push delivery not found.")
        if payload.expected_plan_digest != push_plan.plan_digest:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PUSH_PLAN_CHANGED",
                    "message": "The Push Plan identity changed.",
                },
            )
        plan_database_id = int(push_plan.id)
        plan_public_id = str(push_plan.push_plan_id)
        try:
            push_execution, attempted = confirm_approved_push_plan(
                session,
                owner_id=user.id,
                push_plan=push_plan,
                approval=approval,
                local_commit=local_commit,
                source_repo=settings.source_repo,
                confirmation=payload.confirmation,
                expected_approval_digest=payload.expected_approval_digest,
                request_identity=payload.request_identity,
            )
        except PushDeliveryError as exc:
            # Discard any uncommitted READY_TO_PUSH admission before deciding
            # whether the server durably accepted this request. A durable
            # PUSHING row is committed immediately before transport begins.
            session.rollback()
            existing_execution = session.scalar(
                select(PushExecution).where(
                    PushExecution.owner_id == user.id,
                    PushExecution.push_plan_id == plan_database_id,
                )
            )
            transient_pre_effect = bool(
                existing_execution is None
                and exc.code
                in {"REPOSITORY_MUTATION_ACTIVE", "REPOSITORY_LOCK_UNAVAILABLE"}
            )
            if existing_execution is None:
                # This is an audited pre-effect rejection, not a failed Push.
                # A PushExecution always precedes transport, so the absence of
                # that durable row proves no Git process or remote effect began.
                audit(
                    session,
                    request,
                    "owner_push_attempt_rejected_pre_effect",
                    "push_plan",
                    plan_database_id,
                    (
                        f"plan={plan_public_id}; code={exc.code}; "
                        "request_accepted=false; remote_effect=none"
                    ),
                    user,
                )
                session.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": exc.message,
                    "request_accepted": existing_execution is not None,
                    "remote_effect": (
                        "none" if existing_execution is None else "needs_review"
                    ),
                    "retry_safe": transient_pre_effect,
                },
            ) from exc
        audit(
            session,
            request,
            "owner_push_attempt_completed" if attempted else "owner_push_attempt_retrieved",
            "push_execution",
            push_execution.id,
            f"plan={push_plan.push_plan_id}; state={push_execution.state}",
            user,
        )
        session.commit()
        response = push_plan_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )
        response["push_replayed"] = not attempted
        response["automatic_actions"] = []
        return response

    @app.get("/api/local-commits/{commit_execution_id}/push-delivery")
    def get_push_delivery(
        commit_execution_id: str,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        local_commit = find_owned_local_commit_execution(
            session,
            owner_id=user.id,
            commit_execution_id=commit_execution_id,
        )
        if local_commit is None:
            raise HTTPException(status_code=404, detail="Push workflow not found.")
        return push_delivery_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )

    @app.post("/api/local-commits/{commit_execution_id}/push-preflights")
    def create_owner_push_preflight(
        commit_execution_id: str,
        request: Request,
        payload: CreatePushPreflightIn | None = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        # The optional empty body exists only to make FastAPI reject any
        # client-supplied commit, branch, ref, remote, or repository truth.
        del payload
        local_commit = find_owned_local_commit_execution(
            session,
            owner_id=user.id,
            commit_execution_id=commit_execution_id,
        )
        if local_commit is None:
            raise HTTPException(status_code=404, detail="Push workflow not found.")
        if local_commit.commit_proposal_id is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PUSH_PLAN_APPROVAL_REQUIRED",
                    "message": (
                        "Result-bound delivery requires Review Push Plan and a "
                        "separate explicit Push Plan approval."
                    ),
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            local_commit = find_owned_local_commit_execution(
                session,
                owner_id=user.id,
                commit_execution_id=commit_execution_id,
            )
            if local_commit is None:
                raise HTTPException(status_code=404, detail="Push workflow not found.")
        try:
            push_execution, created = create_push_preflight(
                session,
                owner_id=user.id,
                local_commit=local_commit,
                source_repo=settings.source_repo,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "push_preflight_created" if created else "push_preflight_retrieved",
            "push_execution",
            push_execution.id,
            (
                f"local_commit={local_commit.commit_execution_id}; "
                f"push={push_execution.push_execution_id}; state={push_execution.state}"
            ),
            user,
        )
        session.commit()
        return push_delivery_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )

    @app.post("/api/push-preflights/{push_execution_id}/push-attempts")
    def confirm_owner_push_to_origin_main(
        push_execution_id: str,
        payload: ConfirmPushToOriginMainIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        push_execution = find_owned_push_execution(
            session,
            owner_id=user.id,
            push_execution_id=push_execution_id,
        )
        if push_execution is None:
            raise HTTPException(status_code=404, detail="Push workflow not found.")
        if push_execution.push_plan_id is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CANONICAL_PUSH_CONFIRMATION_REQUIRED",
                    "message": (
                        "Use the approval-bound Push Plan confirmation for this delivery."
                    ),
                },
            )
        state_before = push_execution.state
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
            push_execution = find_owned_push_execution(
                session,
                owner_id=user.id,
                push_execution_id=push_execution_id,
            )
            if push_execution is None:
                raise HTTPException(status_code=404, detail="Push workflow not found.")
        try:
            push_execution, attempted = confirm_push_to_origin_main(
                session,
                owner_id=user.id,
                push_execution=push_execution,
                source_repo=settings.source_repo,
                confirmation=payload.confirmation,
                expected_confirmation_digest=payload.expected_confirmation_digest,
            )
        except PushDeliveryError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            (
                "push_attempt_completed"
                if attempted
                else (
                    "push_attempt_reconciled"
                    if state_before in {"PUSHING", "RECONCILIATION_BLOCKED"}
                    and push_execution.state == "PUSHED"
                    else "push_attempt_retrieved"
                )
            ),
            "push_execution",
            push_execution.id,
            f"push={push_execution.push_execution_id}; state={push_execution.state}",
            user,
        )
        session.commit()
        local_commit = session.get(
            LocalCommitExecution, push_execution.local_commit_execution_id
        )
        if local_commit is None or local_commit.owner_id != user.id:
            raise HTTPException(status_code=404, detail="Push workflow not found.")
        return push_delivery_api_review(
            session,
            owner_id=user.id,
            local_commit=local_commit,
        )

    @app.post("/api/apply-sessions/{session_id}/reverts")
    def revert_exact_apply_session(
        session_id: str,
        payload: RevertAppliedChangesIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        row = find_owned_apply_session(
            session,
            owner_id=user.id,
            session_id=session_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        plan = session.get(ApplyPlan, row.apply_plan_id)
        if plan is None or owner_apply_plan(
            session,
            owner_id=user.id,
            plan_id=plan.plan_id,
        ) is None:
            raise HTTPException(status_code=404, detail="Apply session not found.")
        public = normalized_apply_session(session, row)
        if payload.expected_journal_digest != public.get("journal_digest"):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REVERT_CONFIRMATION_BINDING_CHANGED",
                    "message": (
                        "The confirmed Apply journal identity changed. "
                        "Review Revert readiness again."
                    ),
                },
            )
        if session.get_bind().dialect.name == "sqlite":
            session.commit()
            session.execute(text("BEGIN IMMEDIATE"))
        try:
            row, changed = revert_applied_changes(
                session,
                owner_id=user.id,
                apply_session=row,
                source_repo=settings.source_repo,
                confirmed=payload.confirmation == "REVERT_APPLIED_CHANGES",
                expected_journal_digest=payload.expected_journal_digest,
            )
        except ApplySessionError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        audit(
            session,
            request,
            "apply_session_reverted" if changed else "apply_session_retrieved",
            "apply_session",
            row.id,
            f"plan={plan.plan_id}; session={row.session_id}; state={row.state}",
            user,
        )
        session.commit()
        return apply_session_review_response(
            session,
            owner_id=user.id,
            plan=plan,
            apply_session=row,
        )

    @app.post("/api/codex-runs/{run_id}/cancel")
    def cancel_codex_run(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        run = owner_run_or_404(session, user.id, run_id)
        if run.status == "cancelled":
            output = codex_run_out(run, include_raw=True, session=session)
            output["cancellation_request_replayed"] = True
            return output
        if run.status == "settling" and run.cancellation_requested_at is not None:
            # The Owner intent is already durable and terminal process
            # evidence is being projected. A repeated click is an idempotent
            # replay, not a new cancellation or a conflict.
            output = codex_run_out(run, include_raw=True, session=session)
            output["cancellation_request_replayed"] = True
            return output
        if run.status not in {"queued", "starting", "running", "verifying"}:
            raise HTTPException(status_code=409, detail="Only an active Codex Run can be cancelled.")
        requested_at = utc_now()
        cancellation_intent_created = bool(
            session.execute(
                update(CodexRun)
                .where(
                    CodexRun.id == run.id,
                    CodexRun.cancellation_requested_at.is_(None),
                )
                .values(cancellation_requested_at=requested_at)
            ).rowcount
        )
        if cancellation_intent_created:
            audit(
                session,
                request,
                "codex_cancel_requested",
                "codex_run",
                run.id,
                "Owner requested cancellation.",
                user,
            )
        session.commit()
        cancellation_outcome = codex_manager.cancel(run.id)
        if cancellation_outcome in {"unavailable", "terminal"}:
            refreshed = owner_run_or_404(session, user.id, run.id)
            session.refresh(refreshed)
            if refreshed.status == "cancelled":
                output = codex_run_out(refreshed, include_raw=True, session=session)
                output["cancellation_request_replayed"] = True
                return output
            if (
                not cancellation_intent_created
                and refreshed.cancellation_requested_at is not None
            ):
                output = codex_run_out(refreshed, include_raw=True, session=session)
                output["cancellation_request_replayed"] = True
                return output
            raise HTTPException(status_code=409, detail="Codex run was no longer cancellable.")
        refreshed = session.get(CodexRun, run.id)
        session.refresh(refreshed)
        output = codex_run_out(refreshed, include_raw=True, session=session)
        output["cancellation_request_replayed"] = not cancellation_intent_created
        return output

    @app.get("/api/tasks/{task_id}/owner-acceptance")
    def current_owner_acceptance(
        task_id: int,
        run_id: Optional[int] = None,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        owned_run = None
        if run_id is not None:
            owned_run = find_owner_run(session, user.id, run_id)
            if owned_run is None or owned_run.task_id != task_id:
                # A missing, cross-Owner, or cross-Task Run is deliberately
                # indistinguishable at this read-only projection boundary.
                raise HTTPException(status_code=404, detail="Task or Run not found.")
        conditions = [OwnerAcceptanceSession.task_id == task_id]
        if owned_run is not None:
            conditions.extend(
                [
                    OwnerAcceptanceSession.codex_run_id == owned_run.id,
                ]
            )
        acceptance = session.scalar(
            select(OwnerAcceptanceSession)
            .where(*conditions)
            .order_by(OwnerAcceptanceSession.id.desc())
        )
        if acceptance is not None and find_owner_run(
            session, user.id, acceptance.codex_run_id
        ) is None:
            acceptance = None
        return {
            "task_id": task_id,
            "run_id": owned_run.id if owned_run is not None else None,
            "acceptance": owner_acceptance_out(session, acceptance) if acceptance else None,
        }

    @app.patch("/api/owner-acceptance/{acceptance_id}/items/{item_id}")
    def patch_owner_acceptance_item(
        acceptance_id: int,
        item_id: int,
        payload: AcceptanceItemPatchIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        acceptance = session.get(OwnerAcceptanceSession, acceptance_id)
        item = session.get(OwnerAcceptanceItem, item_id)
        if (
            not acceptance
            or not item
            or item.session_id != acceptance.id
            or find_owner_run(session, user.id, acceptance.codex_run_id) is None
        ):
            raise HTTPException(status_code=404, detail="Owner Acceptance item not found.")
        if acceptance.status in {"accepted", "rejected"}:
            raise HTTPException(status_code=409, detail="Decided Owner Acceptance cannot be edited.")
        item.status = payload.status
        item.note = payload.note
        audit(
            session,
            request,
            "owner_acceptance_item_updated",
            "owner_acceptance_item",
            item.id,
            f"status={item.status}",
            user,
        )
        session.flush()
        return owner_acceptance_out(session, acceptance)

    @app.post("/api/owner-acceptance/{acceptance_id}/accept")
    def accept_owner_result(
        acceptance_id: int,
        payload: AcceptanceDecisionIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        acceptance = session.get(OwnerAcceptanceSession, acceptance_id)
        if not acceptance or find_owner_run(
            session, user.id, acceptance.codex_run_id
        ) is None:
            raise HTTPException(status_code=404, detail="Owner Acceptance not found.")
        if acceptance.status != "owner_review":
            raise HTTPException(status_code=409, detail="Owner Acceptance decision is already final.")
        items = session.scalars(
            select(OwnerAcceptanceItem).where(OwnerAcceptanceItem.session_id == acceptance.id)
        ).all()
        if not items or any(item.required and item.status != "pass" for item in items):
            raise HTTPException(status_code=409, detail="All required Owner Acceptance items must pass.")
        if not has_complete_verified_codex_run_evidence(session, acceptance.codex_run):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Separately verified Coding and Verification invocation evidence is required "
                    "before acceptance."
                ),
            )
        if acceptance.result_envelope_id is not None:
            # A Result-bound review must use the immutable Result/Candidate
            # decision endpoint.  Keep the historical checklist and evidence
            # gates ahead of this migration boundary so an older Owner review
            # still receives its precise safety failure instead of a
            # misleading route-selection error.
            raise HTTPException(
                status_code=409,
                detail="Use the exact Result-bound Accept for Delivery action.",
            )
        acceptance.status = "accepted"
        acceptance.owner_note = payload.note
        acceptance.decided_by_user_id = user.id
        acceptance.decided_at = utc_now()
        acceptance.task.status = "accepted"
        acceptance.task.acceptance_state = "accepted"
        sync = accepted_compact_sync(acceptance.task, acceptance.codex_run, acceptance.codex_run.pack)
        acceptance.compact_sync_result = sync
        acceptance.task.compact_sync_result = sync
        audit(
            session,
            request,
            "owner_result_accepted",
            "owner_acceptance",
            acceptance.id,
            "All required items passed; Compact Sync generated; no merge or push performed.",
            user,
        )
        session.flush()
        return owner_acceptance_out(session, acceptance)

    @app.post("/api/owner-acceptance/{acceptance_id}/reject")
    def reject_owner_result(
        acceptance_id: int,
        payload: AcceptanceDecisionIn,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        acceptance = session.get(OwnerAcceptanceSession, acceptance_id)
        if not acceptance or find_owner_run(
            session, user.id, acceptance.codex_run_id
        ) is None:
            raise HTTPException(status_code=404, detail="Owner Acceptance not found.")
        if acceptance.result_envelope_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Use the exact Result-bound Reject Result action.",
            )
        if acceptance.status != "owner_review":
            raise HTTPException(status_code=409, detail="Owner Acceptance decision is already final.")
        acceptance.status = "rejected"
        acceptance.owner_note = payload.note
        acceptance.decided_by_user_id = user.id
        acceptance.decided_at = utc_now()
        acceptance.task.status = "rejected"
        acceptance.task.acceptance_state = "rejected"
        audit(
            session,
            request,
            "owner_result_rejected",
            "owner_acceptance",
            acceptance.id,
            payload.note or "Owner rejected the result.",
            user,
        )
        session.flush()
        return owner_acceptance_out(session, acceptance)

    @app.get("/api/runs")
    def list_runs(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [run_out(item) for item in session.scalars(select(TaskRun).order_by(TaskRun.id.desc())).all()]

    @app.get("/api/tasks/{task_id}/acceptance")
    def latest_acceptance(task_id: int, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        checks = list(
            session.scalars(
                select(AcceptanceCheck)
                .where(AcceptanceCheck.task_id == task_id)
                .order_by(AcceptanceCheck.id.desc())
            ).all()
        )
        check = checks[0] if checks else None
        run = session.get(TaskRun, check.run_id) if check and check.run_id else None
        events: list[AuditEvent] = []
        if run:
            events = list(
                session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.entity_type == "task_run", AuditEvent.entity_id == run.id)
                    .order_by(AuditEvent.id.desc())
                ).all()
            )
        return acceptance_out(check, run, events, len(checks))

    @app.post("/api/tasks/{task_id}/run")
    def run_task_now(task_id: int, payload: RunIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        decision = evaluate_action(payload.action)
        if not decision.allowed:
            audit(session, request, "policy_denied", "task", task_id, decision.reason, user)
            raise HTTPException(status_code=403, detail=decision.reason)
        try:
            run = run_task(session, task_id, payload.action, actor_user_id=user.id, request_id=getattr(request.state, "request_id", None))
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return run_out(run)

    @app.get("/api/schedules")
    def list_schedules(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        schedules = session.scalars(select(Schedule).order_by(Schedule.id)).all()
        return [schedule_out(item, schedule_run_count(session, item.id)) for item in schedules]

    @app.post("/api/schedules")
    def create_schedule(payload: ScheduleIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        if not session.get(Task, payload.task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        schedule = Schedule(
            task_id=payload.task_id,
            name=payload.name,
            interval_seconds=payload.interval_seconds,
            paused=False,
            next_run_at=compute_next_run(payload.interval_seconds),
        )
        session.add(schedule)
        session.flush()
        audit(session, request, "schedule_created", "schedule", schedule.id, schedule.name, user)
        return schedule_out(schedule, 0)

    @app.patch("/api/schedules/{schedule_id}")
    def patch_schedule(schedule_id: int, payload: SchedulePatchIn, request: Request, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        schedule = session.get(Schedule, schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found.")
        if payload.interval_seconds is not None:
            schedule.interval_seconds = payload.interval_seconds
            schedule.next_run_at = compute_next_run(payload.interval_seconds)
        if payload.paused is not None:
            schedule.paused = payload.paused
            if payload.paused:
                schedule.next_run_at = None
            else:
                schedule.next_run_at = compute_next_run(schedule.interval_seconds)
        if payload.run_now:
            run = run_task(session, schedule.task_id, "compact_sync", actor_user_id=user.id, request_id=getattr(request.state, "request_id", None))
            schedule.last_run_at = utc_now()
            schedule.next_run_at = compute_next_run(schedule.interval_seconds)
            audit(session, request, "schedule_run_now", "schedule", schedule.id, f"task_run={run.id}", user)
        audit(session, request, "schedule_updated", "schedule", schedule.id, f"paused={schedule.paused}", user)
        return schedule_out(schedule, schedule_run_count(session, schedule.id))

    @app.get("/api/providers")
    def providers(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        seed_registry(session)
        session.flush()
        gateway = ProviderGateway.from_session(session)
        health = gateway.health_snapshot()
        configured_provider_ids = {
            item.provider_id
            for item in session.scalars(select(AIModel).order_by(AIModel.id)).all()
            if configured_model_record(item)
        }
        provider_rows = [
            item
            for item in session.scalars(
                select(Provider).where(Provider.kind == "model").order_by(Provider.id)
            ).all()
            if item.id in configured_provider_ids or item.enabled or item.status != "unconfigured"
        ]
        return [provider_out(item, health[item.name]) for item in provider_rows]

    @app.get("/api/tools")
    def tools(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        seed_registry(session)
        tool_rows = [
            item
            for item in session.scalars(select(Tool).order_by(Tool.id)).all()
            if not (
                item.name == "Codex"
                and item.kind == "developer_tool"
                and item.status == "unconfigured"
                and not item.enabled
            )
        ]
        return [registry_out(item) for item in tool_rows]

    @app.get("/api/audit")
    def audit_events(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        primary_owner_id = session.scalar(
            select(User.id)
            .where(User.is_active == True)  # noqa: E712
            .order_by(User.id)
            .limit(1)
        )
        owner_scope = AuditEvent.actor_user_id == user.id
        if primary_owner_id == user.id:
            # Legacy scheduler/CLI evidence predates actor attribution. It is
            # visible only to the canonical fresh-database Owner, never to a
            # later account.
            owner_scope = or_(owner_scope, AuditEvent.actor_user_id.is_(None))
        rows = session.scalars(
            select(AuditEvent)
            .where(owner_scope)
            .order_by(AuditEvent.id.desc())
            .limit(200)
        ).all()
        return [audit_out(item) for item in rows]

    return app
