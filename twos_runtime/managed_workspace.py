"""Explicit Owner creation of a new, private, initialized project directory.

Never adopts an existing unbound directory or changes global Git configuration.
The normal workspace authorization code remains the execution boundary.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import subprocess

from .first_run import FirstRunError, active_installation, authorize_workspace, _validate_workspace_boundaries
from .models import AuthorizedWorkspace, Project
from . import project_workspaces
from sqlalchemy import select, text


def private_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise FirstRunError("MANAGED_PATH_UNSAFE", "The managed project location is unsafe.")
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise FirstRunError("MANAGED_PATH_UNSAFE", "The managed project location contains a symbolic link.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise FirstRunError("MANAGED_PATH_PERMISSIONS", "The project location must be private to your macOS account.")


def create_managed_workspace(session, settings, owner, project_id=None):
    if not settings.fresh_install or not settings.data_root:
        raise FirstRunError("FRESH_INSTALL_REQUIRED", "Managed projects require an installed workspace.")
    installation = active_installation(session)
    if installation.owner_user_id != owner.id:
        raise FirstRunError("PROJECT_OWNER_REQUIRED", "Sign in as this installation's Owner.", 403)
    if session.get_bind().dialect.name == "sqlite":
        session.commit()
        session.execute(text("BEGIN IMMEDIATE"))
        session.expire_all()
        installation = active_installation(session)
    if project_id is None:
        existing = session.scalar(select(AuthorizedWorkspace).where(AuthorizedWorkspace.installation_id == installation.id))
        if existing:
            return authorize_workspace(session, settings, owner=owner, path=existing.canonical_path, create_if_missing=False)
        if installation.first_run_state != "workspace_pending":
            raise FirstRunError("SETUP_STEP_INVALID", "Complete Owner setup before creating the first project.", 409)
    else:
        if installation.first_run_state != "ready":
            raise FirstRunError("PROJECT_OWNER_REQUIRED", "Finish First Run before creating another workspace.", 403)
        if session.get(Project, project_id) is None:
            raise FirstRunError("PROJECT_NOT_FOUND", "Project not found.", 404)
        existing = project_workspaces.workspace_row(session, settings, project_id)
        if existing:
            return project_workspaces.authorize_project(session, settings, owner, project_id, existing.canonical_path, transaction_locked=True)[0]
    root = settings.managed_workspace_root or Path.home() / "Tianma Work OS Projects"
    _validate_workspace_boundaries(root.resolve(strict=False), settings)
    private_path(root)
    # The public installation identity, never a caller-supplied filesystem path.
    parent = root / str(settings.installation_id)
    private_path(parent)
    path = parent / ("My First Project" if project_id is None else f"Project-{project_id}")
    lock_path = settings.data_root / "managed-workspace.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            raise FirstRunError("MANAGED_DIRECTORY_EXISTS", "A directory already exists at the managed location. It was preserved. Use Advanced workspace authorization to inspect and authorize it.", 409)
        (path / "README.md").write_text("# Tianma Work OS project\n\nCreated with your explicit workspace authorization.\nNo remote, credentials, or execution authority is configured.\n", encoding="utf-8")
        environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        prefix = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Tianma Work OS", "-c", "user.email=local@twos.invalid"]
        try:
            for args in (["init", "--initial-branch=main", "--template="], ["add", "--", "README.md"], ["commit", "--no-gpg-sign", "-m", "Initialize Owner-authorized workspace"]):
                subprocess.run(prefix + args, cwd=path, env=environment, check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FirstRunError("MANAGED_GIT_FAILED", "Project initialization could not complete. Your directory was preserved. Open desktop Diagnostics and check the Git prerequisite.", 409) from exc
        if project_id is None:
            return authorize_workspace(session, settings, owner=owner, path=str(path), create_if_missing=False)
        return project_workspaces.authorize_project(session, settings, owner, project_id, str(path), transaction_locked=True)[0]
    finally:
        os.close(descriptor)
