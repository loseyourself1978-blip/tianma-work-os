from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .ai_orchestration import compose_team, decode_capability_tags, route_capability
from .codex_adapter import CodexExecutionManager
from .config import Settings, get_settings
from .db import initialize_database, make_engine, make_session_factory, seed_ai_registry, seed_registry
from .models import (
    AICapability,
    AIModel,
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
from .security import authenticate, create_owner, revoke_token, user_for_token
from .self_hosting import (
    accepted_compact_sync,
    build_instruction_pack,
    git_source_state,
    invalidate_approved_packs,
)
from .workers import parse_acceptance, run_task


SESSION_COOKIE = "twos_session"
OWNER_ACTIONS = ("Analyze", "Compact Sync", "Acceptance Review")


class OwnerInitIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    username: str
    password: str


class ProjectIn(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    status: str = "active"


class TaskIn(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=240)
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
        "repository_identity": task.repository_identity,
        "source_baseline_commit": task.source_baseline_commit,
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
    provider = model.provider
    available = bool(
        provider.enabled
        and provider.status in {"healthy", "degraded"}
        and model.status in {"healthy", "degraded"}
    )
    return {
        "id": model.id,
        "provider": provider.name,
        "provider_status": provider.status,
        "model_name": model.model_name,
        "capability_tags": decode_capability_tags(model),
        "context_limit": model.context_limit,
        "cost_metadata": model.cost_metadata,
        "latency_metadata": model.latency_metadata,
        "status": model.status,
        "routing_priority": model.routing_priority,
        "available": available,
    }


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
    output = {
        "id": pack.id,
        "task_id": pack.task_id,
        "version": pack.version,
        "status": pack.status,
        "stage_summary": pack.stage_summary,
        "key_boundaries": pack.key_boundaries,
        "acceptance_target": pack.acceptance_target,
        "source_baseline_commit": pack.source_baseline_commit,
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
                "generation_metadata": decoded_object(pack.generation_metadata),
            }
        )
    return output


def codex_run_out(run: CodexRun, include_raw: bool = False) -> dict[str, Any]:
    result = decoded_object(run.structured_result)
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
                "output_truncated": run.output_truncated,
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


def create_app(settings: Settings | None = None, start_scheduler: bool = True) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    initialize_database(engine)
    factory = make_session_factory(engine)
    codex_manager = CodexExecutionManager(factory, settings)
    codex_manager.recover_interrupted_runs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_scheduler:
            await app.state.runtime_scheduler.start()
        try:
            yield
        finally:
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
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception as exc:
            return error_response(500, "internal_error", str(exc), request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, "http_error", detail, getattr(request.state, "request_id", None), exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return error_response(422, "validation_error", "Request validation failed.", getattr(request.state, "request_id", None), exc.errors())

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
        return RedirectResponse("/static_cockpit/vol12_static_mvp/twos_command_center.html")

    @app.get("/twos")
    def twos_ui() -> RedirectResponse:
        if not settings.ui_path.exists():
            raise HTTPException(status_code=404, detail="TWOS UI entry not found.")
        return RedirectResponse("/static_cockpit/vol12_static_mvp/twos_command_center.html")

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

    @app.get("/api/auth/status")
    def auth_status(request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
        owner = session.scalar(select(User).order_by(User.id))
        raw_token = request.cookies.get(SESSION_COOKIE)
        authenticated = user_for_token(session, raw_token) if raw_token else None
        return {
            "owner_initialized": owner is not None,
            "authenticated": authenticated is not None,
            "mode": "setup" if owner is None else "authenticated" if authenticated else "login",
            "owner": (
                {"id": authenticated.id, "username": authenticated.username}
                if authenticated
                else {"username": owner.username} if owner else None
            ),
        }

    @app.post("/api/auth/init")
    def init_owner(payload: OwnerInitIn, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
        if session.scalar(select(User)):
            raise HTTPException(status_code=409, detail="Owner account already initialized.")
        try:
            user = create_owner(session, payload.username, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        audit(session, request, "owner_initialized", "user", user.id, "Owner account initialized.", user)
        return {"owner": {"id": user.id, "username": user.username}}

    @app.post("/api/auth/login")
    def login(payload: LoginIn, response: Response, request: Request, session: Session = Depends(get_db)) -> dict[str, Any]:
        try:
            user, raw_token, token = authenticate(session, payload.username, payload.password, settings.session_ttl_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response.set_cookie(SESSION_COOKIE, raw_token, httponly=True, samesite="strict", max_age=settings.session_ttl_seconds)
        audit(session, request, "login", "session", token.id, "Owner logged in.", user)
        return {"token": raw_token, "owner": {"id": user.id, "username": user.username}, "expires_at": iso(token.expires_at)}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, session: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
        raw_token = request.cookies.get(SESSION_COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if raw_token:
            revoke_token(session, raw_token)
        response.delete_cookie(SESSION_COOKIE)
        audit(session, request, "logout", "user", user.id, "Owner logged out.", user)
        return {"status": "logged_out"}

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
        try:
            action = persisted_action(payload.action, payload.task_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        source_state: dict[str, object] = {}
        if payload.workflow_type == "product_development":
            required = {
                "objective": payload.objective,
                "implementation_scope": payload.implementation_scope,
                "forbidden_scope": payload.forbidden_scope,
                "acceptance_target": payload.acceptance_target,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product-development task requires: {', '.join(missing)}.",
                )
            try:
                source_state = git_source_state(settings.source_repo)
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        task = Task(
            project_id=payload.project_id,
            title=payload.title,
            task_type=action,
            source_sync_summary=payload.source_sync_summary,
            required_output=payload.required_output,
            boundary_risk=payload.boundary_risk,
            workflow_type=payload.workflow_type,
            objective=payload.objective or payload.title,
            implementation_scope=payload.implementation_scope,
            forbidden_scope=payload.forbidden_scope,
            acceptance_target=payload.acceptance_target,
            repository_identity=str(source_state.get("identity", "")),
            source_baseline_commit=str(source_state.get("commit", "")),
            status="draft" if payload.workflow_type == "product_development" else "queued",
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
        data = payload.model_dump(exclude_unset=True)
        updated_fields = list(data.keys())
        pack_sensitive_fields = {
            "project_id",
            "title",
            "action",
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
        if "project_id" in data:
            project = session.get(Project, data.pop("project_id"))
            if not project:
                raise HTTPException(status_code=404, detail="Project not found.")
            task.project = project
        for key, value in data.items():
            setattr(task, key, value)
        if task.workflow_type == "product_development":
            required_values = {
                "objective": task.objective,
                "implementation_scope": task.implementation_scope,
                "forbidden_scope": task.forbidden_scope,
                "acceptance_target": task.acceptance_target,
            }
            missing = [name for name, value in required_values.items() if not value.strip()]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product-development task requires: {', '.join(missing)}.",
                )
            if not task.source_baseline_commit:
                source_state = git_source_state(settings.source_repo)
                task.repository_identity = str(source_state["identity"])
                task.source_baseline_commit = str(source_state["commit"])
        if task.workflow_type == "product_development" and pack_sensitive_fields.intersection(updated_fields):
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
        model_rows = session.scalars(select(AIModel).order_by(AIModel.provider_id, AIModel.id)).all()
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
        invalidated = invalidate_approved_packs(session, task.id) if task.workflow_type == "product_development" else 0
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
        plan_output["routes"] = [routing_out(item) for item in routes]
        plan_output["routing_summary"] = routing_summary_out(plan, routes)
        if task.workflow_type == "product_development":
            task.status = "planned"
            if invalidated:
                audit(
                    session,
                    request,
                    "codex_pack_approval_invalidated",
                    "task",
                    task.id,
                    f"invalidated_packs={invalidated}; AI Team changed",
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
            return {"task_id": task_id, "plan": None, "routes": [], "routing_summary": None}
        routes = session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.team_plan_id == plan.id)
            .order_by(RoutingDecision.id)
        ).all()
        return {
            "task_id": task_id,
            "plan": team_plan_out(session, plan),
            "routes": [routing_out(item) for item in routes],
            "routing_summary": routing_summary_out(plan, routes),
        }

    @app.get("/api/codex/status")
    def codex_status(user: User = Depends(current_user)) -> dict[str, Any]:
        detection = codex_manager.adapter.detect()
        output = detection.as_dict(include_path=False)
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
        return output

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
        return [codex_run_out(run, include_raw=True) for run in runs]

    @app.post("/api/tasks/{task_id}/codex-runs")
    def start_codex_run(
        task_id: int,
        request: Request,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found.")
        pack = session.scalar(
            select(CodexInstructionPack)
            .where(CodexInstructionPack.task_id == task.id)
            .order_by(CodexInstructionPack.version.desc())
        )
        if not pack or pack.status != "approved" or pack.invalidated_at is not None:
            raise HTTPException(status_code=409, detail="Approve the current Codex Instruction Pack before execution.")
        detection = codex_manager.adapter.detect()
        if detection.status != "configured":
            raise HTTPException(status_code=409, detail=f"Codex status is {detection.status}: {detection.reason}")
        try:
            source = codex_manager.adapter.source_state()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not source["clean"]:
            raise HTTPException(status_code=409, detail="Source repository must be clean before Codex execution.")
        if source["commit"] != pack.source_baseline_commit:
            raise HTTPException(status_code=409, detail="Source HEAD differs from the approved pack baseline.")
        run = CodexRun(
            task_id=task.id,
            pack_id=pack.id,
            status="queued",
            executable_status=detection.status,
            source_repo=str(source["repo"]),
            source_branch=str(source["branch"]),
            source_commit=str(source["commit"]),
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
        codex_manager.start(run.id)
        return codex_run_out(run, include_raw=True)

    @app.get("/api/codex-runs/{run_id}")
    def get_codex_run(
        run_id: int,
        session: Session = Depends(get_db),
        user: User = Depends(current_user),
    ) -> dict[str, Any]:
        run = session.get(CodexRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Codex run not found.")
        return codex_run_out(run, include_raw=True)

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
        if run.status not in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="Only a queued or running Codex run can be cancelled.")
        audit(session, request, "codex_cancel_requested", "codex_run", run.id, "Owner requested cancellation.", user)
        session.commit()
        if not codex_manager.cancel(run.id):
            raise HTTPException(status_code=409, detail="Codex run was no longer cancellable.")
        refreshed = session.get(CodexRun, run.id)
        session.refresh(refreshed)
        return codex_run_out(refreshed, include_raw=True)

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
        acceptance = session.get(OwnerAcceptanceSession, acceptance_id)
        if not acceptance:
            raise HTTPException(status_code=404, detail="Owner Acceptance not found.")
        items = session.scalars(
            select(OwnerAcceptanceItem).where(OwnerAcceptanceItem.session_id == acceptance.id)
        ).all()
        if not items or any(item.required and item.status != "pass" for item in items):
            raise HTTPException(status_code=409, detail="All required Owner Acceptance items must pass.")
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
        acceptance = session.get(OwnerAcceptanceSession, acceptance_id)
        if not acceptance:
            raise HTTPException(status_code=404, detail="Owner Acceptance not found.")
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
        provider_rows = session.scalars(select(Provider).where(Provider.kind == "model").order_by(Provider.id)).all()
        return [provider_out(item, health[item.name]) for item in provider_rows]

    @app.get("/api/tools")
    def tools(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        seed_registry(session)
        return [registry_out(item) for item in session.scalars(select(Tool).order_by(Tool.id)).all()]

    @app.get("/api/audit")
    def audit_events(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [audit_out(item) for item in session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200)).all()]

    return app
