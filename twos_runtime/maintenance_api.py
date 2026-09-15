"""Owner-only maintenance surface, also usable before an old DB is migrated."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, closing
from pathlib import Path
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select

from .config import ROOT_DIR
from .maintenance import Maintenance, MaintenanceError, TARGET_SCHEMA, atomic_json, inspect_database, readonly, safe_state, tables, TERMINAL_OPERATIONS, open_lock
from .security import authenticate, hash_token


def owner_for_request(service, request):
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else request.cookies.get(service.settings.session_cookie_name)
    if not token:
        raise MaintenanceError("AUTH_REQUIRED", "Log in as this installation's Owner.", 401)
    with readonly(service.db) as connection:
        row = connection.execute("SELECT u.id, u.username, u.is_active FROM users u JOIN session_tokens s ON s.user_id=u.id WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at > datetime('now')", (hash_token(token),)).fetchone()
        first = connection.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        installation = connection.execute("SELECT owner_user_id FROM installations LIMIT 1").fetchone() if "installations" in tables(connection) else None
    if not row or not row["is_active"]:
        raise MaintenanceError("AUTH_REQUIRED", "Log in again; this session is unavailable.", 401)
    owner_id = installation[0] if installation and installation[0] else first[0] if first else None
    if row["id"] != owner_id:
        raise MaintenanceError("OWNER_REQUIRED", "Only this installation's Owner can use Maintenance.", 403)
    return dict(row)


def install_maintenance(app, settings, *, standalone=False):
    service = Maintenance(settings)
    app.state.maintenance = service
    app.state.maintenance_busy = False
    app.state.maintenance_requests = 0

    @app.exception_handler(MaintenanceError)
    async def maintenance_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}, "next_action": exc.message}, status_code=exc.status_code)

    @app.middleware("http")
    async def barrier(request, call_next):
        maintenance_route = request.url.path.startswith("/api/maintenance/")
        if app.state.maintenance_busy:
            return JSONResponse({"error": {"code": "MAINTENANCE_BUSY", "message": "Maintenance is running. Wait for its receipt."}}, status_code=409)
        if (not maintenance_route and request.url.path.startswith("/api/")
                and not request.url.path.startswith(("/api/auth/", "/api/health", "/api/version"))
                and service.journal()["state"] not in TERMINAL_OPERATIONS | {"NONE"}):
            return JSONResponse({"error": {"code": "RECOVERY_REQUIRED", "message": "Keep TWOS in Maintenance. Restart to reconcile the recorded operation; no normal action is available."}}, status_code=428)
        authority = service.authority()
        if not maintenance_route and request.url.path.startswith("/api/") and not request.url.path.startswith(("/api/auth/", "/api/health", "/api/version")):
            if authority.get("workspace_status") == "REAUTHORIZATION_REQUIRED":
                return JSONResponse({"error": {"code": "REAUTHORIZATION_REQUIRED", "message": "Open Backup & Recovery and reauthorize the current workspace."}}, status_code=428)
            # Historical paths and approval identities stay evidence, never an
            # authority to mutate a newly restored local filesystem.
            if authority.get("historical_cutoffs"):
                import re
                path = request.url.path
                run = re.search(r"/codex-runs/(\d+)", path)
                pack = re.search(r"/codex-packs/(\d+)", path)
                cutoffs = authority["historical_cutoffs"]
                old_run = run and int(run[1]) <= cutoffs["codex_runs"]
                old_pack = pack and int(pack[1]) <= cutoffs["codex_instruction_packs"]
                mapped = {"apply-plans":("apply_plans", "plan_id"), "apply-sessions":("apply_sessions", "session_id"),
                    "post-apply-verifications":("post_apply_verifications", "verification_id"), "commit-proposals":("commit_proposals", "proposal_id"),
                    "commit-plans":("commit_plans", "commit_plan_id"), "stage-sessions":("stage_executions", "stage_execution_id"),
                    "local-commits":("local_commit_executions", "commit_execution_id"), "push-plans":("push_plans", "push_plan_id"),
                    "push-preflights":("push_executions", "push_execution_id"), "owner-acceptance":("owner_acceptance_sessions", "id"),
                    "instruction-drafts":("handoff_instruction_drafts", "draft_id")}
                historical_delivery = False
                for segment, (table, public_id) in mapped.items():
                    match = re.search('/'+segment+r'/([^/]+)(?:/|$)', path)
                    if not match:
                        continue
                    try:
                        owner = owner_for_request(service, request)
                    except MaintenanceError as exc:
                        return await maintenance_error(request, exc)
                    with readonly(service.db) as connection:
                        if table == "owner_acceptance_sessions":
                            row = connection.execute("SELECT a.id FROM owner_acceptance_sessions a JOIN codex_runs r ON r.id=a.codex_run_id JOIN codex_instruction_packs p ON p.id=r.pack_id WHERE a.id=? AND p.approved_by_user_id=? AND (a.decided_by_user_id IS NULL OR a.decided_by_user_id=p.approved_by_user_id)", (match[1], owner["id"])).fetchone()
                        else:
                            row = connection.execute('SELECT id FROM "'+table+'" WHERE "'+public_id+'"=? AND owner_id=?', (match[1], owner["id"])).fetchone()
                        # Numeric keys are used by Owner Acceptance and some
                        # compatibility routes; public IDs remain authoritative.
                        if row is None and match[1].isdigit():
                            row = connection.execute('SELECT id FROM "'+table+'" WHERE id=? AND owner_id=?', (int(match[1]), owner["id"])).fetchone()
                    historical_delivery = bool(row and row[0] <= cutoffs.get(table, 0))
                    if historical_delivery:
                        break
                if request.method == "POST" and path.endswith("/codex-runs"):
                    try:
                        body = await request.json()
                        old_pack = old_pack or int(body.get("pack_id", 0)) <= cutoffs["codex_instruction_packs"]
                    except (ValueError, TypeError, AttributeError):
                        old_pack = True
                if request.method == "POST" and path.endswith("/codex-packs"):
                    with readonly(service.db) as connection:
                        checked = connection.execute("SELECT snapshot_json FROM guided_tool_configurations WHERE id>? AND confirmed_at IS NOT NULL ORDER BY id DESC LIMIT 1", (cutoffs["guided_tool_configurations"],)).fetchone()
                    if not checked or json.loads(checked[0]).get("recovery_epoch") != authority["epoch"]:
                        return JSONResponse({"error": {"code": "TOOL_RECHECK_REQUIRED", "message": "Explicitly check and save current Guided Tool Setup after recovery before preparing a new Pack."}}, status_code=428)
                if historical_delivery:
                    return JSONResponse({"error": {"code": "HISTORICAL_EVIDENCE_ONLY", "message": "Recovered delivery is archived evidence. Prepare a new Pack; old Apply, Stage, Commit and Push cannot be reactivated."}}, status_code=409)
                if (old_run and (request.method != "GET" or any(segment in path for segment in ("delivery", "apply", "commit", "push", "candidate")))) or (old_pack and request.method != "GET"):
                    return JSONResponse({"error": {"code": "HISTORICAL_EVIDENCE_ONLY", "message": "Recovered delivery is read-only evidence. Prepare and approve a new Pack for current work."}}, status_code=409)
        # A different Maintenance process must not replace the database while
        # this process is inspecting or reviewing it without an ORM connection.
        read_lease = None
        mutations = {"/api/maintenance/backups", "/api/maintenance/confirm", "/api/maintenance/workspace"}
        if request.url.path.startswith("/api/") and request.url.path not in mutations:
            try:
                read_lease = open_lock(service.db)
            except MaintenanceError as exc:
                return await maintenance_error(request, exc)
        app.state.maintenance_requests += 1
        try:
            return await call_next(request)
        finally:
            app.state.maintenance_requests -= 1
            if read_lease is not None:
                os.close(read_lease)

    async def mutate(request, action):
        owner = owner_for_request(service, request)
        if app.state.maintenance_busy or app.state.maintenance_requests > 1:
            raise MaintenanceError("INSTALLATION_BUSY", "Another request is active. Wait for it to finish before maintenance.")
        safe_state(service.db)
        manager = getattr(app.state, "codex_manager", None)
        if manager:
            with manager._lock:
                if any(t.is_alive() for t in manager._workers.values()) or any(p.poll() is None for p in manager._processes.values()):
                    raise MaintenanceError("ACTIVE_OPERATION", "A Codex worker is still active. Wait for terminal settlement before maintenance.")
        app.state.maintenance_busy = True
        monitor = getattr(app.state, "result_intake_monitor", None)
        scheduler = getattr(app.state, "runtime_scheduler", None)
        scheduler_running = bool(scheduler and scheduler._task and not scheduler._task.done())
        try:
            if scheduler:
                await scheduler.stop()
            if monitor:
                await asyncio.to_thread(monitor.shutdown, 5.0)
                if monitor._thread is not None and monitor._thread.is_alive():
                    raise MaintenanceError("INSTALLATION_BUSY", "Result monitoring has not stopped. Wait for settlement; no backup was created.")
            app.state.engine.dispose()
            result = await asyncio.to_thread(action, owner["id"])
            return result
        finally:
            app.state.engine.dispose()
            app.state.maintenance_busy = False
            # Restored schedules are paused. Read-only history cannot restart
            # work even when the ordinary runtime services are available again.
            journal_resolved = service.journal()["state"] in TERMINAL_OPERATIONS | {"NONE"}
            authorized = service.authority().get("workspace_status") != "REAUTHORIZATION_REQUIRED"
            if journal_resolved and authorized:
                if monitor:
                    monitor.start()
                if scheduler_running:
                    await scheduler.start()

    @app.get("/maintenance")
    def maintenance_page():
        return FileResponse(ROOT_DIR / "static_cockpit" / "maintenance.html", headers={"Cache-Control": "no-store"})

    @app.get("/maintenance.js")
    def maintenance_script():
        return FileResponse(ROOT_DIR / "static_cockpit" / "maintenance.js", media_type="text/javascript")

    @app.get("/api/maintenance/status")
    def status(request: Request):
        owner = owner_for_request(service, request)
        return {**service.status(), "owner": owner["username"], "standalone": standalone}

    @app.get("/api/maintenance/data")
    def data(request: Request):
        owner_for_request(service, request)
        with readonly(service.db) as connection:
            return {"tasks": [dict(row) for row in connection.execute("SELECT id,title,status FROM tasks ORDER BY id")], "counts": service.status()["counts"]}

    @app.post("/api/maintenance/backups")
    async def backup(request: Request):
        payload = await request.json()
        if payload != {"confirmation": "CREATE_BACKUP"}:
            raise MaintenanceError("CONFIRMATION_REQUIRED", "Explicitly confirm Create Backup. The destination is fixed private TWOS maintenance storage.", 400)
        return await mutate(request, lambda owner: service.create_backup())

    @app.post("/api/maintenance/inspect")
    async def inspect_backup(request: Request):
        owner_for_request(service, request)
        payload = await request.json()
        return service.inspect_backup(payload.get("backup", ""))

    @app.post("/api/maintenance/restore-plan")
    async def restore_plan(request: Request):
        owner = owner_for_request(service, request)
        payload = await request.json()
        return service.restore_plan(payload.get("backup", ""), owner["id"])

    @app.post("/api/maintenance/migration-plan")
    def migration_plan(request: Request):
        owner = owner_for_request(service, request)
        return service.migration_plan(owner["id"])

    @app.post("/api/maintenance/confirm")
    async def confirm(request: Request):
        payload = await request.json()
        return await mutate(request, lambda owner: service.execute_plan(payload.get("plan_id"), owner, payload.get("confirmation")))

    @app.post("/api/maintenance/approve-plan")
    async def approve(request: Request):
        owner = owner_for_request(service, request)
        payload = await request.json()
        if payload.get("confirmation") != "APPROVE_MAINTENANCE_PLAN":
            raise MaintenanceError("CONFIRMATION_REQUIRED", "Explicitly approve the displayed maintenance plan.", 400)
        return service.approve_plan(payload.get("plan_id"), owner["id"])

    @app.post("/api/maintenance/workspace")
    async def workspace(request: Request):
        owner_for_request(service, request)
        payload = await request.json()
        if payload.get("confirmation") != "REAUTHORIZE_WORKSPACE":
            raise MaintenanceError("CONFIRMATION_REQUIRED", "Explicitly confirm the exact current workspace.", 400)
        def reauthorize(owner):
            from .first_run import FirstRunError, validate_authorized_workspace
            with service.exclusive():
                authority = service.authority()
                if authority.get("workspace_status") != "REAUTHORIZATION_REQUIRED":
                    raise MaintenanceError("REAUTHORIZATION_NOT_REQUIRED", "Workspace reauthorization is not pending.")
                try:
                    resolved, metadata, identity = validate_authorized_workspace(payload.get("path", ""), settings=settings, create_if_missing=False)
                except FirstRunError as exc:
                    raise MaintenanceError(exc.code, exc.message, exc.status_code) from exc
                with closing(sqlite3.connect(service.db)) as connection:
                    old = connection.execute("SELECT canonical_path FROM authorized_workspaces").fetchone()
                    connection.execute("UPDATE authorized_workspaces SET canonical_path=?,device_id=?,inode=?,identity_digest=? WHERE owner_user_id=?", (str(resolved), metadata.st_dev, metadata.st_ino, identity, owner))
                    connection.commit()
                previous_workspace = old[0] if old else authority.get("workspace", str(settings.source_repo))
                # Every explicit reauthorization invalidates future use of old
                # configuration/Packs, even when a replacement keeps its path.
                authority = service._recovery_authority(service.db, authority, "WORKSPACE_REAUTHORIZATION")
                authority.update(workspace_status="AUTHORIZED", workspace=str(resolved), previous_workspace=previous_workspace,
                    workspace_binding={"path": str(resolved), "device": metadata.st_dev, "inode": metadata.st_ino,
                        "identity": identity, "machine_context": service.machine_context()},
                    next_action="Restart TWOS, then explicitly check Tool Setup and prepare a new Pack for future work.")
                atomic_json(service.authority_path, authority)
                service.record(service.journal()["state"], authority=authority, new_authority=authority,
                    workspace_reauthorized_by=owner, next_action=authority["next_action"])
                object.__setattr__(settings, "source_repo", resolved)
                return authority
        return await mutate(request, reauthorize)


def maintenance_app(settings):
    from .db import make_engine, make_session_factory
    service = Maintenance(settings)
    service.reconcile()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.settings = settings
    install_maintenance(app, settings, standalone=True)

    @app.get("/twos")
    def home():
        return RedirectResponse("/maintenance")

    @app.post("/api/auth/login")
    async def login(request: Request):
        from .security import AuthenticationError
        payload = await request.json()
        try:
            with factory() as session:
                user, token, _ = authenticate(session, payload.get("username", ""), payload.get("password", ""), settings.session_ttl_seconds)
                session.commit()
                response = JSONResponse({"username": user.username})
                response.set_cookie(settings.session_cookie_name, token, httponly=True, samesite="strict", max_age=settings.session_ttl_seconds)
                return response
        except (AuthenticationError, ValueError, TypeError):
            return JSONResponse({"error": {"message": "Incorrect username or password."}}, status_code=401)
        finally:
            engine.dispose()

    @app.get("/api/health")
    def health():
        return {"status": "maintenance", "provider_request_performed": False}

    return app
