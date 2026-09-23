"""Owner-authorized project directories, resolved without changing global Settings.

First Run retains its original installation workspace. Additional projects have
their own persisted authorization and never inherit that first directory.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from sqlalchemy import select, text

from .config import Settings
from .first_run import FirstRunError, active_installation, validate_authorized_workspace
from .maintenance import recovery_epoch
from .models import (
    AuthorizedWorkspace, ProjectWorkspaceAuthorization, Project, Task, CodexRun,
    CommitPlan, LocalCommitExecution, StageExecution, GuidedToolConfiguration,
)


def workspace_row(session, settings, project_id):
    if not settings.fresh_install:
        return None
    installation = active_installation(session)
    for model in (AuthorizedWorkspace, ProjectWorkspaceAuthorization):
        row = session.scalar(select(model).where(
            model.installation_id == installation.id, model.project_id == project_id))
        if row is not None:
            return row
    return None


def _validate_row(row, settings):
    path, metadata, identity = validate_authorized_workspace(
        row.canonical_path, settings=settings, create_if_missing=False)
    if (path / ".git").is_file() or (path / ".git" / "commondir").exists():
        raise FirstRunError("PROJECT_SHARED_GIT_UNSUPPORTED", "Authorize a standalone repository; linked worktrees share Git state.", 403)
    if (str(path), metadata.st_dev, metadata.st_ino, identity) != (
        row.canonical_path, row.device_id, row.inode, row.identity_digest
    ):
        raise FirstRunError("PROJECT_WORKSPACE_CHANGED", "The authorized project directory identity changed.", 403)
    if isinstance(row, ProjectWorkspaceAuthorization) and row.recovery_epoch != recovery_epoch(settings):
        raise FirstRunError("PROJECT_REAUTHORIZATION_REQUIRED", "Authorize this project again after recovery before execution.", 403)
    return path


def project_settings(session, settings: Settings, project_id: int, owner_id: int, *, required=True):
    if not settings.fresh_install:
        return settings
    installation = active_installation(session)
    if installation.owner_user_id != owner_id:
        raise FirstRunError("PROJECT_OWNER_REQUIRED", "Only this installation's Owner can authorize or execute projects.", 403)
    if session.get(Project, project_id) is None:
        raise FirstRunError("PROJECT_NOT_FOUND", "Project not found.", 404)
    row = workspace_row(session, settings, project_id)
    if row is None:
        if not required:
            return None
        raise FirstRunError("PROJECT_WORKSPACE_UNAUTHORIZED", "Authorize this Project's workspace before Prepare or Run.", 403)
    if row.owner_user_id != owner_id:
        raise FirstRunError("PROJECT_OWNER_REQUIRED", "The project workspace belongs to a different Owner.", 403)
    roots = tuple(Path(item.canonical_path) for model in (AuthorizedWorkspace, ProjectWorkspaceAuthorization)
                  for item in session.scalars(select(model).where(model.installation_id == installation.id)))
    return replace(settings, source_repo=_validate_row(row, settings), authorized_workspace_roots=roots)


def task_settings(session, settings, task_id, owner_id=None, *, required=True):
    if not settings.fresh_install:
        return settings
    task = session.get(Task, task_id)
    if task is None or (owner_id is not None and task.owner_user_id != owner_id):
        raise FirstRunError("TASK_NOT_FOUND", "Task not found.", 404)
    return project_settings(session, settings, task.project_id,
                            owner_id if owner_id is not None else task.owner_user_id,
                            required=required)


def run_settings(session, settings, run_id, owner_id=None):
    if not settings.fresh_install:
        return settings
    run = session.get(CodexRun, run_id)
    if run is None:
        raise FirstRunError("RUN_NOT_FOUND", "Run not found.", 404)
    scoped = task_settings(session, settings, run.task_id, owner_id)
    if str(scoped.source_repo.resolve(strict=True)) != run.source_repo:
        raise FirstRunError("RUN_WORKSPACE_MISMATCH", "The Run does not belong to this authorized project directory.", 403)
    return scoped


def record_settings(session, settings, record, owner_id=None):
    """Follow persisted delivery lineage, never a caller-supplied filesystem path."""
    if not settings.fresh_install:
        return settings
    if record is None or (owner_id is not None and getattr(record, "owner_id", None) != owner_id):
        raise FirstRunError("DELIVERY_NOT_FOUND", "Delivery not found.", 404)
    if isinstance(record, (StageExecution, LocalCommitExecution)):
        record = session.get(CommitPlan, record.commit_plan_id)
    return run_settings(session, settings, record.run_id, owner_id)


def authorize_project(session, settings, owner, project_id, path, *, create_if_missing=False):
    if not settings.fresh_install:
        raise FirstRunError("FRESH_INSTALL_REQUIRED", "Project workspace authorization requires a canonical installation.")
    installation = active_installation(session)
    if installation.owner_user_id != owner.id or installation.first_run_state != "ready":
        raise FirstRunError("PROJECT_OWNER_REQUIRED", "Finish First Run and sign in as its Owner.", 403)
    if session.get(Project, project_id) is None:
        raise FirstRunError("PROJECT_NOT_FOUND", "Project not found.", 404)
    # Serialize the authorization identity check and insert. No provider or
    # other long-running work occurs inside this short transaction.
    if session.get_bind().dialect.name == "sqlite":
        session.commit()
        session.execute(text("BEGIN IMMEDIATE"))
    resolved, metadata, identity = validate_authorized_workspace(
        path, settings=settings, create_if_missing=create_if_missing)
    if (resolved / ".git").is_file() or (resolved / ".git" / "commondir").exists():
        raise FirstRunError("PROJECT_SHARED_GIT_UNSUPPORTED", "Choose a standalone repository; linked worktrees share Git state and are not separate project scopes.", 400)
    existing = workspace_row(session, settings, project_id)
    if existing:
        if (existing.canonical_path, existing.device_id, existing.inode, existing.identity_digest) != (
            str(resolved), metadata.st_dev, metadata.st_ino, identity
        ):
            raise FirstRunError("PROJECT_WORKSPACE_ALREADY_BOUND", "This Project is already bound to another directory identity. Create a separate Project.")
        if isinstance(existing, ProjectWorkspaceAuthorization):
            existing.recovery_epoch = recovery_epoch(settings)
        return existing, False
    for model in (AuthorizedWorkspace, ProjectWorkspaceAuthorization):
        for other in session.scalars(select(model).where(model.installation_id == installation.id)):
            other_path = Path(other.canonical_path)
            if resolved == other_path or resolved.is_relative_to(other_path) or other_path.is_relative_to(resolved):
                raise FirstRunError("PROJECT_WORKSPACE_OVERLAP", "Use separate, non-overlapping directories for different projects.", 409)
    for config in session.scalars(select(GuidedToolConfiguration).where(GuidedToolConfiguration.owner_id == owner.id)):
        for item in json.loads(config.snapshot_json).get("verification", {}).get("files", []):
            if Path(item["path"]).is_relative_to(resolved):
                raise FirstRunError("PROJECT_CONTAINS_VERIFIER", "A project cannot contain a previously approved independent verifier.", 409)
    row = ProjectWorkspaceAuthorization(installation_id=installation.id, owner_user_id=owner.id,
        project_id=project_id, canonical_path=str(resolved), device_id=metadata.st_dev,
        inode=metadata.st_ino, identity_digest=identity, recovery_epoch=recovery_epoch(settings))
    session.add(row)
    session.flush()
    return row, True


def workspace_out(session, settings, project_id, owner_id):
    row = workspace_row(session, settings, project_id)
    result = {"project_id": project_id, "authorized": False, "workspace": None,
              "next_action": "Authorize Project Workspace", "permissions": []}
    if row is None:
        return result
    try:
        scoped = project_settings(session, settings, project_id, owner_id)
    except FirstRunError as exc:
        result.update(blocker={"code": exc.code, "message": exc.message})
        return result
    result.update(authorized=True, workspace=str(scoped.source_repo), owner_id=row.owner_user_id,
                  authorization_id=row.id, next_action="Configure Tool and Verification",
                  permissions=["read_context", "prepare", "isolated_run", "explicitly_approved_apply"],
                  commit_requires_separate_approval=True, push_requires_separate_approval=True)
    return result
