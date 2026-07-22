from __future__ import annotations

import json
import logging
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
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
)
from .codex_adapter import CodexExecutionManager
from .config import Settings, get_settings
from .db import initialize_database, make_engine, make_session_factory, seed_ai_registry, seed_registry
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
    CodexRun,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
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
    actual_model_identity_verified = bool(
        process_evidence.get("actual_model_identity_verified") is True
        and process_evidence.get("model_identity_observed") is True
        and evidence.actual_invoked_model_identifier
    )
    actual_resolved_model_identifier = (
        evidence.actual_invoked_model_identifier if actual_model_identity_verified else None
    )
    process_execution_verified = process_evidence.get("process_execution_verified") is True
    codex_turn_verified = process_evidence.get("codex_turn_verified") is True
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
            else "Not independently exposed by available CLI evidence"
            if verified_real_invocation
            else "Not verified"
        ),
        "actual_model_identity_verified": actual_model_identity_verified,
        "process_execution_verified": process_execution_verified,
        "codex_turn_verified": codex_turn_verified,
        "display_claim": (
            f"Ran with {actual_resolved_model_identifier}"
            if verified_real_invocation and actual_resolved_model_identifier
            else (
                "Real Codex CLI invocation verified; "
                f"requested model {requested_model_identifier}; "
                "actual resolved model not independently exposed by available CLI evidence"
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


def codex_run_out(
    run: CodexRun,
    include_raw: bool = False,
    session: Session | None = None,
) -> dict[str, Any]:
    result = decoded_object(run.structured_result)
    result["task_id"] = run.task_id
    result["task_version"] = run.task_version
    result["pack_version"] = run.pack.version if run.pack else None
    result["development_task"] = run.development_task
    result["frozen_development_task"] = run.development_task
    result["development_task_digest"] = run.development_task_digest

    def normalized_invocation_result(
        value: object,
        requested_model_identifier: str,
    ) -> dict[str, Any]:
        proof = dict(value) if isinstance(value, dict) else {}
        requested = str(
            proof.get("requested_model_identifier")
            or proof.get("requested_model")
            or requested_model_identifier
            or ""
        )
        actual_model_identity_verified = proof.get("actual_model_identity_verified") is True
        candidate = proof.get("actual_resolved_model_identifier") or proof.get(
            "actual_resolved_model"
        )
        actual = str(candidate) if actual_model_identity_verified and candidate else None
        turn_verified = proof.get("codex_turn_verified") is True
        process_verified = proof.get("process_execution_verified") is True
        proof["requested_model"] = requested
        proof["requested_model_identifier"] = requested
        proof["actual_resolved_model"] = actual
        proof["actual_resolved_model_identifier"] = actual
        proof["actual_resolved_model_display"] = (
            actual
            if actual
            else "Not independently exposed by available CLI evidence"
            if turn_verified
            else "Not verified"
        )
        proof["actual_model_identity_verified"] = bool(actual)
        proof["process_execution_verified"] = process_verified
        proof["codex_turn_verified"] = turn_verified
        return proof

    result["coding_invocation"] = normalized_invocation_result(
        result.get("coding_invocation"),
        run.requested_model_identifier,
    )
    result["verification_invocation"] = normalized_invocation_result(
        result.get("verification_invocation"),
        run.verification_model_identifier,
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
    output = {
        "id": run.id,
        "task_id": run.task_id,
        "pack_id": run.pack_id,
        "pack_version": run.pack.version if run.pack else None,
        "status": run.status,
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
        "timed_out": run.timed_out,
        "cancelled": run.cancelled,
        "result": result,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }
    if include_raw:
        output.update(
            {
                "source_repo": run.source_repo,
                "worktree_path": run.worktree_path,
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
    return output


def owner_acceptance_out(session: Session, acceptance: OwnerAcceptanceSession) -> dict[str, Any]:
    items = session.scalars(
        select(OwnerAcceptanceItem)
        .where(OwnerAcceptanceItem.session_id == acceptance.id)
        .order_by(OwnerAcceptanceItem.ordinal)
    ).all()
    required_complete = all(item.status == "pass" for item in items if item.required)
    return {
        "id": acceptance.id,
        "task_id": acceptance.task_id,
        "codex_run_id": acceptance.codex_run_id,
        "status": acceptance.status,
        "owner_note": acceptance.owner_note,
        "compact_sync_result": acceptance.compact_sync_result,
        "can_accept": bool(items) and required_complete,
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
    codex_manager = CodexExecutionManager(factory, settings)
    codex_manager.sync_local_model_registry()
    codex_manager.recover_interrupted_runs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_scheduler:
            await app.state.runtime_scheduler.start()
        try:
            yield
        finally:
            codex_manager.shutdown()
            await app.state.runtime_scheduler.stop()

    app = FastAPI(title="TWOS 1.0 Runtime", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.runtime_scheduler = RuntimeScheduler(factory, settings.scheduler_poll_seconds)
    app.state.codex_manager = codex_manager

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
                source_state = git_source_state(settings.source_repo)
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
                source_state = git_source_state(settings.source_repo)
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
        material_before = (
            provider.enabled,
            provider.status,
            model.status,
            model.configuration_status,
            model.availability_status,
            model.invocation_mode,
        )
        detection = codex_manager.adapter.detect()
        authenticated, authentication_reason = codex_manager.adapter.authentication_ready(detection)
        available = detection.status == "configured" and authenticated
        provider.enabled = available
        provider.status = "healthy" if available else "unconfigured"
        provider.last_checked_at = utc_now()
        model.status = "healthy" if available else "unconfigured"
        model.availability_status = "available" if available else "unavailable"
        model.evidence_status = "runtime_check" if available else "unverified"
        model.evidence_source = "local_cli_readiness"
        model.last_verified_at = utc_now()
        if detection.status != "configured":
            failure = "runtime_unavailable"
            diagnostic = detection.reason
        elif not authenticated:
            failure = "authentication_unavailable"
            diagnostic = authentication_reason
        else:
            failure = ""
            diagnostic = "Local Codex CLI executable, command surface, and authentication are available."
        model.safe_diagnostic = diagnostic
        evidence = AIModelAvailabilityEvidence(
            configuration_identity=model.stable_id or f"model-{model.id}",
            model_id=model.id,
            checked_by_user_id=user.id,
            adapter="codex_cli",
            invocation_mode="real",
            result="available" if available else "unavailable",
            evidence_type="non_inference_cli_health",
            failure_classification=failure,
            runtime_identity=(detection.version or "")[:240],
        )
        session.add(evidence)
        invalidated = 0
        material_after = (
            provider.enabled,
            provider.status,
            model.status,
            model.configuration_status,
            model.availability_status,
            model.invocation_mode,
        )
        if material_before != material_after:
            provider_state_changed = material_before[:2] != material_after[:2]
            affected_model_ids = (
                [item.id for item in model.provider.models]
                if provider_state_changed
                else [model.id]
            )
            assigned_task_ids = {
                assignment.task_id
                for assignment in session.scalars(
                    select(AIModelAssignment).where(
                        AIModelAssignment.assigned_model_id.in_(affected_model_ids)
                    )
                ).all()
            }
            for assigned_task_id in assigned_task_ids:
                invalidated_for_task = invalidate_approved_packs(session, assigned_task_id)
                invalidated += invalidated_for_task
                if invalidated_for_task:
                    assigned_task = session.get(Task, assigned_task_id)
                    if assigned_task is not None:
                        assigned_task.status = "planned"
        audit(
            session, request, "codex_availability_checked", "ai_model", model.id,
            f"adapter=codex_cli; capability={payload.capability}; result={evidence.result}; evidence_type=non_inference_cli_health", user,
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
            "invalidated_packs": invalidated,
        }

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
            raise HTTPException(status_code=409, detail="Check availability successfully before Save and assign.")
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
        )
        output: dict[str, Any] = {
            "status": (
                "configured"
                if model_binding_ready
                else "check_required"
                if configured is not None
                else "unconfigured"
            ),
            "found": evidence is not None,
            "version": evidence.runtime_identity if evidence is not None else None,
            "supported_command": "codex exec --model MODEL --json" if evidence is not None else None,
            "reason": (
                configured.safe_diagnostic
                if configured is not None
                else "No Local Codex CLI configuration has been saved."
            ),
            "next_action": "Run Codex" if model_binding_ready else "Check availability",
        }
        output["authentication_ready"] = bool(model_binding_ready)
        output["model_binding_ready"] = model_binding_ready
        output["execution_ready"] = model_binding_ready
        output["configuration_status"] = (
            configured.configuration_status if configured is not None else "needs_setup"
        )
        output["availability_status"] = (
            configured.availability_status if configured is not None else "unavailable"
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
                "Local Codex CLI, authentication, and the selected model binding are ready. "
                "Exact model access is verified only by an Owner-approved run."
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
        return run_eligibility(session, task, settings.source_repo)

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
        runs = session.scalars(
            select(CodexRun).where(CodexRun.task_id == task_id).order_by(CodexRun.id.desc())
        ).all()
        return [codex_run_out(run, include_raw=True, session=session) for run in runs]

    @app.post("/api/tasks/{task_id}/codex-runs")
    def start_codex_run(
        task_id: int,
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
        detection = codex_manager.adapter.detect()
        authenticated, authentication_reason = codex_manager.adapter.authentication_ready(detection)
        readiness_changed = codex_manager.reconcile_observed_local_readiness(
            session,
            detection,
            authenticated=authenticated,
            authentication_reason=authentication_reason,
        )
        eligibility = run_eligibility(session, task, settings.source_repo)
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
                eligibility = run_eligibility(session, task, settings.source_repo)
            if readiness_changed or invalidated:
                session.commit()
            raise HTTPException(
                status_code=409,
                detail={"type": "RUN_INELIGIBLE", **eligibility},
            )
        pack = session.get(CodexInstructionPack, eligibility["pack_id"])
        if pack is None:
            raise HTTPException(status_code=409, detail={"type": "RUN_INELIGIBLE", **eligibility})
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
            refreshed = run_eligibility(session, task, settings.source_repo)
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
            execution_target = codex_execution_target(session, task, pack)
            verification_target = verification_execution_target(session, task, pack)
        except ValueError as exc:
            refreshed = run_eligibility(session, task, settings.source_repo)
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
            refreshed = run_eligibility(session, task, settings.source_repo)
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
            execution_assignment_id=execution_target.assignment.id,
            execution_model_id=execution_target.model.id,
            execution_provider_id=execution_target.model.provider_id,
            requested_model_identifier=execution_target.requested_model_identifier,
            fallback_selected=execution_target.fallback_selected,
            verification_assignment_id=verification_target.assignment.id,
            verification_model_id=verification_target.model.id,
            verification_provider_id=verification_target.model.provider_id,
            verification_model_identifier=verification_target.requested_model_identifier,
            verification_status="not_started",
            owner_summary="Approved Codex run is queued for isolated execution.",
        )
        session.add(run)
        session.flush()
        task.status = "queued"
        audit(
            session,
            request,
            "codex_run_queued",
            "codex_run",
            run.id,
            f"task={task.id}; pack_version={pack.version}",
            user,
        )
        session.commit()
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
        return codex_run_out(run, include_raw=True, session=session)

    @app.get("/api/codex-runs/{run_id}")
    def get_codex_run(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        run = session.get(CodexRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Codex run not found.")
        return codex_run_out(run, include_raw=True, session=session)

    @app.post("/api/codex-runs/{run_id}/cancel")
    def cancel_codex_run(
        run_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        run = session.get(CodexRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Codex run not found.")
        if run.status not in {"queued", "starting", "running", "verifying"}:
            raise HTTPException(status_code=409, detail="Only an active Codex Run can be cancelled.")
        audit(session, request, "codex_cancel_requested", "codex_run", run.id, "Owner requested cancellation.", user)
        session.commit()
        if not codex_manager.cancel(run.id):
            raise HTTPException(status_code=409, detail="Codex run was no longer cancellable.")
        refreshed = session.get(CodexRun, run.id)
        session.refresh(refreshed)
        return codex_run_out(refreshed, include_raw=True, session=session)

    @app.get("/api/tasks/{task_id}/owner-acceptance")
    def current_owner_acceptance(
        task_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        if not session.get(Task, task_id):
            raise HTTPException(status_code=404, detail="Task not found.")
        acceptance = session.scalar(
            select(OwnerAcceptanceSession)
            .where(OwnerAcceptanceSession.task_id == task_id)
            .order_by(OwnerAcceptanceSession.id.desc())
        )
        return {
            "task_id": task_id,
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
        if not acceptance or not item or item.session_id != acceptance.id:
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
        if not acceptance:
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
        if not acceptance:
            raise HTTPException(status_code=404, detail="Owner Acceptance not found.")
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
        return [audit_out(item) for item in session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200)).all()]

    return app
