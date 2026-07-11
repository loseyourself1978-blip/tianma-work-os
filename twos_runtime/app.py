from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .config import Settings, get_settings
from .db import initialize_database, make_engine, make_session_factory, seed_registry
from .models import AcceptanceCheck, AuditEvent, Project, Provider, Schedule, Task, TaskRun, Tool, User, utc_now
from .policy import ACTION_POLICIES, CONNECTOR_STATUSES, LIFECYCLE_STATES, evaluate_action
from .scheduler import RuntimeScheduler, compute_next_run
from .security import authenticate, create_owner, revoke_token, user_for_token
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


class TaskPatchIn(BaseModel):
    title: Optional[str] = None
    action: Optional[str] = None
    task_type: Optional[str] = None
    source_sync_summary: Optional[str] = None
    required_output: Optional[str] = None
    boundary_risk: Optional[str] = None
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
    def twos_ui() -> FileResponse:
        if not settings.ui_path.exists():
            raise HTTPException(status_code=404, detail="TWOS UI entry not found.")
        return FileResponse(settings.ui_path)

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
        task = Task(
            project_id=payload.project_id,
            title=payload.title,
            task_type=action,
            source_sync_summary=payload.source_sync_summary,
            required_output=payload.required_output,
            boundary_risk=payload.boundary_risk,
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
        if "action" in data:
            try:
                data["task_type"] = persisted_action(data.pop("action"), None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if "status" in data and data["status"] not in LIFECYCLE_STATES:
            raise HTTPException(status_code=400, detail="Unsupported task status.")
        for key, value in data.items():
            setattr(task, key, value)
        audit(session, request, "task_updated", "task", task.id, ",".join(data.keys()), user)
        return task_out(task)

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
        return [registry_out(item) for item in session.scalars(select(Provider).order_by(Provider.id)).all()]

    @app.get("/api/tools")
    def tools(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        seed_registry(session)
        return [registry_out(item) for item in session.scalars(select(Tool).order_by(Tool.id)).all()]

    @app.get("/api/audit")
    def audit_events(session: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [audit_out(item) for item in session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200)).all()]

    return app
