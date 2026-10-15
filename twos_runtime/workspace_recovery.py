"""Explicit recovery of legacy, mount-device-based workspace authorization.

No authority is inferred from an unchanged inode. The existing Owner first
confirms the exact preview. An APFS volume UUID may then survive renumbering;
path, inode, ownership, symlink and repository boundaries still apply.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
import sys
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, text

from .config import ROOT_DIR
from .models import AuditEvent, AuthorizedWorkspace, Installation, Project, Task, CodexRun, PushExecution

ACTION = "workspace_mount_identity_owner_confirmed"


def volume_identity(path):
    """Read one mounted APFS volume's stable identity; never inspect credentials."""
    if sys.platform != "darwin":
        return None
    try:
        before = path.stat()
        result = subprocess.run(["/bin/df", "-P", str(path)], capture_output=True, timeout=5, check=True)
        device = result.stdout.decode("utf-8").splitlines()[-1].split()[0]
        if not re.fullmatch(r"/dev/disk\d+s\d+(?:s\d+)?", device):
            return None
        result = subprocess.run(["/usr/sbin/diskutil", "info", "-plist", device], capture_output=True, timeout=5, check=True)
        value = plistlib.loads(result.stdout)
        identity = str(value.get("VolumeUUID", "")).upper()
        after = path.stat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            return None
        if value.get("FilesystemType") != "apfs" or not re.fullmatch(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}", identity):
            return None
        return identity
    except (OSError, ValueError, IndexError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return None


def latest(session, owner_id=None):
    query = select(AuditEvent).where(AuditEvent.action == ACTION)
    if owner_id is not None:
        query = query.where(AuditEvent.actor_user_id == owner_id)
    row = session.scalar(query.order_by(AuditEvent.id.desc()).limit(1))
    return json.loads(row.details) if row else None


def binding_matches(session, row, path, metadata, identity):
    receipt = latest(session, row.owner_user_id)
    scoped = receipt and receipt.get("workspace_id") == row.id and receipt.get("installation_id") == row.installation_id
    if (str(path), metadata.st_dev, metadata.st_ino, identity) == (
        row.canonical_path, row.device_id, row.inode, row.identity_digest
    ):
        return not (scoped and receipt.get("volume_uuid")) or receipt["volume_uuid"] == volume_identity(path)
    # This fallback exists only after an explicit authenticated Owner receipt.
    # A renamed/replaced directory, different volume, or malformed receipt fails.
    if str(path) != row.canonical_path or metadata.st_ino != row.inode:
        return False
    expected = hashlib.sha256(f"{row.canonical_path}\0{row.device_id}\0{row.inode}".encode()).hexdigest()
    return bool(receipt and receipt.get("workspace_id") == row.id
        and receipt.get("installation_id") == row.installation_id
        and receipt.get("after_digest") == row.identity_digest == expected
        and receipt.get("path") == str(path) and receipt.get("inode") == metadata.st_ino
        and receipt.get("volume_uuid") and receipt["volume_uuid"] == volume_identity(path))


def epoch(settings):
    if not settings or not settings.fresh_install:
        return ""
    from .maintenance import database_path, readonly, tables
    path = database_path(settings.database_url)
    if not path.exists():
        return ""
    with readonly(path) as connection:
        if "audit_events" not in tables(connection):
            return ""
        row = connection.execute("SELECT details FROM audit_events WHERE action=? ORDER BY id DESC LIMIT 1", (ACTION,)).fetchone()
    return json.loads(row[0])["epoch"] if row else ""


def guard_mutation(session, owner_id, method, path, *, pack_id=None):
    """A workspace confirmation never reactivates an old execution approval."""
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return
    from .first_run import FirstRunError
    receipt = latest(session, owner_id)
    if not receipt:
        return
    cutoffs = receipt['historical_cutoffs']
    blocked = pack_id is not None and pack_id <= cutoffs['codex_instruction_packs']
    for segment, table, key in (
        ('codex-runs','codex_runs','id'), ('codex-packs','codex_instruction_packs','id'),
        ('apply-plans','apply_plans','plan_id'), ('apply-sessions','apply_sessions','session_id'),
        ('post-apply-verifications','post_apply_verifications','verification_id'),
        ('commit-proposals','commit_proposals','proposal_id'), ('commit-plans','commit_plans','commit_plan_id'),
        ('stage-sessions','stage_executions','stage_execution_id'),
        ('local-commits','local_commit_executions','commit_execution_id'),
        ('push-plans','push_plans','push_plan_id'), ('push-preflights','push_executions','push_execution_id'),
        ('owner-acceptance','owner_acceptance_sessions','id'), ('instruction-drafts','handoff_instruction_drafts','draft_id')):
        match = re.search('/'+segment+r'/([^/]+)(?:/|$)', path)
        if match:
            # Authentication has already established the one installation Owner.
            row = session.execute(text('SELECT id FROM "'+table+'" WHERE "'+key+'"=:key'), {'key':match[1]}).first()
            blocked = blocked or bool(row and row[0] <= cutoffs.get(table, 0))
    if blocked:
        raise FirstRunError('HISTORICAL_EVIDENCE_ONLY', 'This saved delivery remains read-only after workspace recovery. Check Tool Setup and prepare a new Pack for future work.', 409)


def archived_push(session, owner_id, run_id):
    receipt = latest(session, owner_id)
    if not receipt or run_id > receipt['historical_cutoffs']['codex_runs']:
        return None
    from .models import PushPlan, PushPlanApproval, LocalCommitExecution
    from .push_delivery import _verified_push_receipt, _push_plan_out, _execution_out, _push_approval_out, _confirmation_state
    row = session.scalar(select(PushExecution).where(PushExecution.owner_id == owner_id,
        PushExecution.run_id == run_id).order_by(PushExecution.id.desc()))
    verified = _verified_push_receipt(row) if row else None
    if not verified:
        return None
    plan = session.get(PushPlan, row.push_plan_id)
    approval = session.get(PushPlanApproval, row.push_plan_approval_id)
    view = _push_plan_out(plan, approval, row)
    return {'local_commit_execution_id': session.get(LocalCommitExecution, row.local_commit_execution_id).commit_execution_id,
        'status': 'DELIVERED', 'action_state': 'DELIVERED',
        'push_plan': view, 'push_approval': _push_approval_out(approval), 'push_execution': _execution_out(row),
        'confirmation': _confirmation_state(plan=plan, approval=approval, execution=row,
            can_confirm=False, blockers=[], delivery_complete=True),
        'actions': {'can_review_push_plan': False, 'can_approve_push_plan': False,
            'can_confirm_push': False, 'can_view_delivery_result': True}, 'blockers': [], 'historical_evidence_only': True,
        'delivery_result': {'status': 'DELIVERED', 'status_label': 'DELIVERED', 'complete': True,
            'verified_remote_sha': verified['origin_main_sha'], 'reconciliation': verified,
            'next_action': 'Saved delivery verified at its recorded time. No new remote check or execution occurred.'},
        'next_action': 'View the saved delivery receipt. Use a new Task for future work.'}


def preview(session, settings):
    from .first_run import validate_authorized_workspace, FirstRunError
    installation = session.scalar(select(Installation))
    row = session.scalar(select(AuthorizedWorkspace).where(AuthorizedWorkspace.installation_id == installation.id))
    if row is None:
        raise FirstRunError("WORKSPACE_RECOVERY_UNAVAILABLE", "There is no existing workspace authorization to review.")
    path, metadata, identity = validate_authorized_workspace(row.canonical_path, settings=settings, create_if_missing=False)
    if (path / ".git").is_file() or (path / ".git" / "commondir").exists():
        raise FirstRunError("PROJECT_SHARED_GIT_UNSUPPORTED", "Linked worktrees cannot be confirmed as a standalone project.", 403)
    if path.stat().st_uid != os.getuid() or metadata.st_mode & 0o022:
        raise FirstRunError("WORKSPACE_RECOVERY_UNSAFE", "The current workspace is not private to this macOS account.")
    same_directory = metadata.st_ino == row.inode and str(path) == row.canonical_path
    volume = volume_identity(path)
    value = {"workspace_id": row.id, "installation_id": row.installation_id,
        "project_id": row.project_id, "project": session.get(Project, row.project_id).name,
        "path": str(path), "inode": metadata.st_ino, "before_device": row.device_id,
        "current_device": metadata.st_dev, "before_digest": row.identity_digest,
        "after_digest": identity, "volume_uuid": volume,
        "can_confirm": same_directory and not binding_matches(session, row, path, metadata, identity),
        "already_authorized": binding_matches(session, row, path, metadata, identity)}
    value["review_digest"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


def confirm(session, settings, owner_id, supplied):
    from .first_run import FirstRunError
    installation = session.scalar(select(Installation))
    if installation.owner_user_id != owner_id:
        raise FirstRunError("OWNER_REQUIRED", "Only this installation's Owner can confirm the current workspace.", 403)
    session.commit()
    session.execute(text("BEGIN IMMEDIATE"))
    value = preview(session, settings)
    prior = latest(session, owner_id)
    if value["already_authorized"] and prior and prior.get("review_digest") == supplied:
        session.rollback()
        return {"status": "ALREADY_CONFIRMED", "restart_required": True}
    if not value["can_confirm"] or value["review_digest"] != supplied:
        raise FirstRunError("WORKSPACE_REVIEW_CHANGED", "The workspace changed or is not the same directory. Reload the review; nothing was authorized.")
    from .maintenance import safe_state, database_path
    safe_state(database_path(settings.database_url))
    row = session.get(AuthorizedWorkspace, value["workspace_id"])
    row.device_id, row.inode, row.identity_digest = value["current_device"], value["inode"], value["after_digest"]
    cutoffs = {}
    for name in ("codex_runs", "codex_instruction_packs", "guided_tool_configurations", "apply_plans",
                 "apply_sessions", "post_apply_verifications", "commit_proposals", "commit_plans",
                 "stage_executions", "local_commit_executions", "push_plans", "push_executions",
                 "owner_acceptance_sessions", "handoff_instruction_drafts"):
        cutoffs[name] = session.execute(text('SELECT COALESCE(MAX(id),0) FROM "'+name+'"')).scalar()
    value.update(epoch=uuid.uuid4().hex, historical_cutoffs=cutoffs)
    session.add(AuditEvent(actor_user_id=owner_id, action=ACTION, entity_type="authorized_workspace",
        entity_id=row.id, details=json.dumps(value, sort_keys=True)))
    session.commit()
    return {"status": "CONFIRMED", "restart_required": True, "volume_identity_recorded": bool(value["volume_uuid"])}


def history(session, owner_id):
    """Stored evidence only. No filesystem payload or remote/provider request."""
    from .push_delivery import _verified_push_receipt
    tasks = session.scalars(select(Task).where(Task.owner_user_id == owner_id).order_by(Task.id)).all()
    result = []
    for task in tasks:
        runs = session.scalars(select(CodexRun).where(CodexRun.task_id == task.id).order_by(CodexRun.id)).all()
        receipts = []
        for row in session.scalars(select(PushExecution).where(PushExecution.task_id == task.id, PushExecution.owner_id == owner_id)):
            receipt = _verified_push_receipt(row)
            pre = json.loads(row.preflight_evidence_json or "{}")
            receipts.append({"status": "DELIVERED" if receipt else "UNVERIFIED_RECEIPT",
                "plan": row.push_plan_public_id, "commit": row.approved_commit_oid,
                "verified_target_sha": receipt.get("origin_main_sha") if receipt else None,
                "destination": pre.get("remote_display"), "branch": row.destination_ref,
                "attempt_count": row.command_attempt_count, "finished_at": str(row.finished_at) if row.finished_at else None})
        result.append({"project": session.get(Project, task.project_id).name, "task_id": task.id,
            "task": task.title, "runs": [{"id": r.id, "status": r.status, "output": r.owner_summary} for r in runs], "receipts": receipts})
    return result


def recovery_app(settings):
    """Healthy logical data with an unverified workspace can still be inspected.

    No scheduler, intake monitor, registry sync or execution routes are mounted.
    """
    from .db import make_engine, make_session_factory
    from .first_run import validate_fresh_database_before_initialization, FirstRunError
    from .maintenance import Maintenance, MaintenanceError
    from .maintenance_api import owner_for_request
    from .security import authenticate, AuthenticationError
    validate_fresh_database_before_initialization(settings)
    service = Maintenance(settings)
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

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin", "")
            if origin != str(request.base_url).rstrip("/") or request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"error": {"message": "Use this TWOS window and an explicit action."}}, status_code=403)
        try:
            return await call_next(request)
        except (FirstRunError, MaintenanceError) as exc:
            return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)
        except Exception:
            return JSONResponse({"error": {"code": "RECOVERY_REQUEST_FAILED", "message": "This recovery action could not complete. No delivery was started. Reload the review before retrying."}}, status_code=503)
        finally:
            # Release idle ORM connections and their shared maintenance leases.
            engine.dispose()

    @app.get("/twos")
    def home():
        return FileResponse(ROOT_DIR / "static_cockpit/workspace_recovery.html", headers={"Cache-Control": "no-store"})

    @app.get("/workspace-recovery.js")
    def script():
        return FileResponse(ROOT_DIR / "static_cockpit/workspace_recovery.js", headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health():
        from . import __version__
        return {"status": "workspace_review_required", "version": __version__, "provider_request_performed": False}

    @app.post("/api/auth/login")
    async def login(request: Request):
        payload = await request.json()
        try:
            with factory() as session:
                user, token, _ = authenticate(session, payload.get("username", ""), payload.get("password", ""), settings.session_ttl_seconds)
                if session.scalar(select(Installation)).owner_user_id != user.id:
                    raise AuthenticationError("Owner required")
                session.commit()
                response = JSONResponse({"authenticated": True})
                response.set_cookie(settings.session_cookie_name, token, httponly=True, samesite="strict", max_age=settings.session_ttl_seconds)
                return response
        except (AuthenticationError, ValueError, TypeError):
            return JSONResponse({"error": {"message": "Use the existing Owner account."}}, status_code=401)

    @app.get("/api/startup-recovery/review")
    def review(request: Request):
        owner = owner_for_request(service, request)
        with factory() as session:
            return {"review": preview(session, settings), "history": history(session, owner["id"])}

    @app.post("/api/startup-recovery/confirm")
    async def confirmation(request: Request):
        owner = owner_for_request(service, request)
        payload = await request.json()
        if set(payload) != {"confirmation", "review_digest"} or payload.get("confirmation") != "CONFIRM_CURRENT_WORKSPACE":
            raise FirstRunError("CONFIRMATION_REQUIRED", "Review and explicitly confirm this exact workspace.", 400)
        # The ORM connection holds the shared maintenance lease; BEGIN
        # IMMEDIATE serializes the exact authorization/audit transaction.
        # Do not acquire an exclusive file lease then deadlock our own ORM.
        with factory() as session:
            return confirm(session, settings, owner["id"], payload["review_digest"])

    return app
