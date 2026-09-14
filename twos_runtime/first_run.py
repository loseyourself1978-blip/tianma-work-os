from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .config import ROOT_DIR, Settings
from .db import (
    DEFAULT_AI_CAPABILITIES,
    DEFAULT_TOOLS,
    VOL17_END_TO_END_SCHEMA_VERSION,
    VOL17_MODEL_SETUP_SCHEMA_VERSION,
    VOL17_REAL_EVIDENCE_SCHEMA_VERSION,
    VOL17_SCHEMA_VERSION,
    VOL18_APPLY_REVERT_SCHEMA_VERSION,
    VOL18_CODEX_CONNECTIVITY_SCHEMA_VERSION,
    VOL18_DELIVERY_CANDIDATE_SCHEMA_VERSION,
    VOL18_EXEC_LIFECYCLE_SCHEMA_VERSION,
    VOL18_LOCAL_COMMIT_BUILDER_SCHEMA_VERSION,
    VOL18_POST_APPLY_VERIFICATION_SCHEMA_VERSION,
    VOL18_PUSH_DELIVERY_SCHEMA_VERSION,
    VOL18_RESULT_INTAKE_SCHEMA_VERSION,
    VOL18_REVIEW_APPLY_PLAN_SCHEMA_VERSION,
    VOL19_CODEX_RUN_RESULT_SCHEMA_VERSION,
    VOL19_FRESH_INSTALL_SCHEMA_VERSION,
    VOL19_GUIDED_DELIVERY_SCHEMA_VERSION,
    VOL19_OWNER_COMMIT_PUSH_SCHEMA_VERSION,
    VOL19_RESULT_DELIVERY_LOOP_SCHEMA_VERSION,
)
from .models import (
    AuthorizedWorkspace,
    Base,
    Installation,
    Project,
    Task,
    User,
    utc_now,
)
from .security import authenticate, create_owner, normalize_username, owner_record_issue, verify_password


FIRST_RUN_STATES = frozenset(
    {
        "uninitialized",
        "setup_authorization_pending",
        "installation_confirmation_pending",
        "owner_creation_pending",
        "workspace_pending",
        "optional_tools_pending",
        "completion_pending",
        "ready",
        "failed",
    }
)
SETUP_TOKEN_TTL = timedelta(hours=24)
_INSTALLATION_ID_PATTERN = re.compile(r"^install_[a-f0-9]{24,64}$")
_COOKIE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CANONICAL_FRESH_SCHEMA_VERSIONS = frozenset(
    {
        "mvp14.001",
        "mvp15.001",
        "mvp15.002",
        "vol16.001",
        VOL17_SCHEMA_VERSION,
        VOL17_MODEL_SETUP_SCHEMA_VERSION,
        VOL17_END_TO_END_SCHEMA_VERSION,
        VOL17_REAL_EVIDENCE_SCHEMA_VERSION,
        VOL18_DELIVERY_CANDIDATE_SCHEMA_VERSION,
        VOL18_REVIEW_APPLY_PLAN_SCHEMA_VERSION,
        VOL18_APPLY_REVERT_SCHEMA_VERSION,
        VOL18_RESULT_INTAKE_SCHEMA_VERSION,
        VOL18_CODEX_CONNECTIVITY_SCHEMA_VERSION,
        VOL18_EXEC_LIFECYCLE_SCHEMA_VERSION,
        VOL18_POST_APPLY_VERIFICATION_SCHEMA_VERSION,
        VOL18_LOCAL_COMMIT_BUILDER_SCHEMA_VERSION,
        VOL18_PUSH_DELIVERY_SCHEMA_VERSION,
        VOL19_CODEX_RUN_RESULT_SCHEMA_VERSION,
        VOL19_RESULT_DELIVERY_LOOP_SCHEMA_VERSION,
        VOL19_OWNER_COMMIT_PUSH_SCHEMA_VERSION,
        VOL19_FRESH_INSTALL_SCHEMA_VERSION,
        VOL19_GUIDED_DELIVERY_SCHEMA_VERSION,
    }
)
_MAX_PRIVATE_CONFIGURATION_BYTES = 64 * 1024
_VOL_SCHEMA_VERSION_PATTERN = re.compile(r"^vol([0-9]+)\.([0-9]+)$")


class FirstRunError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _vol_schema_version_key(version: str) -> tuple[int, int] | None:
    matched = _VOL_SCHEMA_VERSION_PATTERN.fullmatch(version)
    if not matched:
        return None
    return int(matched.group(1)), int(matched.group(2))


def sqlite_database_path(database_url: str) -> Path:
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        raise FirstRunError(
            "DATABASE_UNSUPPORTED",
            "Fresh Install requires one explicit local SQLite database.",
        )
    path = Path(parsed.database).expanduser()
    if not path.is_absolute():
        raise FirstRunError(
            "DATABASE_PATH_UNSAFE",
            "The Fresh Install database path must be absolute.",
        )
    return path


def _has_unsafe_text(value: str) -> bool:
    return "\x00" in value or any(ord(character) < 32 for character in value)


def _contains_path(parent: Path, child: Path) -> bool:
    return child == parent or parent in child.parents


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise FirstRunError(
                "PATH_SYMLINK_UNSAFE",
                "The selected path contains a symbolic-link boundary.",
            )


def validate_data_root(path: Path, *, source_root: Path = ROOT_DIR) -> Path:
    raw = str(path)
    if not path.is_absolute() or _has_unsafe_text(raw) or ".." in path.parts:
        raise FirstRunError(
            "DATA_ROOT_UNSAFE",
            "Choose an absolute data-root path without traversal components.",
        )
    _reject_symlink_components(path)
    resolved = path.resolve(strict=True)
    source = source_root.resolve(strict=True)
    if (
        _contains_path(source, resolved)
        or _contains_path(resolved, source)
        or ".git" in resolved.parts
    ):
        raise FirstRunError(
            "DATA_ROOT_IN_SOURCE",
            "The TWOS data root must remain outside the source repository.",
        )
    if not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
        raise FirstRunError(
            "DATA_ROOT_NOT_WRITABLE",
            "The TWOS data root must be a writable local directory.",
        )
    return resolved


def validate_fresh_database_before_initialization(settings: Settings) -> Path:
    """Reject legacy, newer, or unrelated databases before create_all can write."""
    if not settings.data_root:
        raise FirstRunError(
            "INSTALLATION_PATHS_MISSING",
            "The canonical launcher did not provide a TWOS data root.",
        )
    data_root = validate_data_root(settings.data_root)
    database_path = sqlite_database_path(settings.database_url)
    if database_path.parent.resolve(strict=True) != data_root:
        raise FirstRunError(
            "DATABASE_PATH_UNSAFE",
            "The Fresh Install database must remain directly inside its data root.",
        )
    if database_path.is_symlink():
        raise FirstRunError(
            "DATABASE_SYMLINK_UNSAFE",
            "The Fresh Install database cannot be a symbolic link.",
        )
    if not database_path.exists():
        return database_path
    metadata = database_path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise FirstRunError(
            "DATABASE_PATH_UNSAFE",
            "The Fresh Install database must be an unlinked regular local file.",
        )
    if metadata.st_size == 0:
        return database_path
    try:
        connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "schema_versions" not in tables:
                raise FirstRunError(
                    "DATABASE_INCOMPATIBLE",
                    "Existing data is not a supported TWOS Fresh Install database.",
                )
            version_rows = [
                str(row[0])
                for row in connection.execute("SELECT version FROM schema_versions").fetchall()
            ]
            versions = set(version_rows)
            if "installations" not in tables:
                raise FirstRunError(
                    "DATABASE_INCOMPATIBLE",
                    "Existing data is not a canonical TWOS Fresh Install database.",
                )
            installations = connection.execute(
                "SELECT public_id, data_root, database_path FROM installations"
            ).fetchall()
            expected_tables = set(Base.metadata.tables)
            application_tables = {
                table_name
                for table_name in tables
                if not table_name.startswith("sqlite_")
            }
            provisioned_registry_tables = {"ai_capabilities", "tools"}
            non_registry_tables = (
                application_tables - provisioned_registry_tables - {"schema_versions"}
            )
            tool_rows = {
                tuple(row)
                for row in connection.execute(
                    "SELECT name, kind, status, enabled, details, last_checked_at "
                    "FROM tools"
                ).fetchall()
            }
            expected_tool_rows = {
                (name, kind, status, 0, details, None)
                for name, kind, status, details in DEFAULT_TOOLS
            }
            capability_rows = {
                tuple(row)
                for row in connection.execute(
                    "SELECT name, description, quality_requirement, latency_sensitivity, "
                    "requires_tool_capability, requires_verification, enabled "
                    "FROM ai_capabilities"
                ).fetchall()
            }
            expected_capability_rows = {
                (name, description, quality, latency, int(requires_tool), int(requires_verification), 1)
                for (
                    name,
                    description,
                    quality,
                    latency,
                    requires_tool,
                    requires_verification,
                ) in DEFAULT_AI_CAPABILITIES
            }
            empty_provisioned_database = (
                not installations
                and application_tables == expected_tables
                and len(version_rows) == len(_CANONICAL_FRESH_SCHEMA_VERSIONS)
                and versions == _CANONICAL_FRESH_SCHEMA_VERSIONS
                and tool_rows == expected_tool_rows
                and capability_rows == expected_capability_rows
                and all(
                    connection.execute(
                        'SELECT COUNT(*) FROM "' + table_name.replace('"', '""') + '"'
                    ).fetchone()[0]
                    == 0
                    for table_name in non_registry_tables
                )
            )
        finally:
            connection.close()
    except FirstRunError:
        raise
    except sqlite3.Error as exc:
        raise FirstRunError(
            "DATABASE_INCOMPATIBLE",
            "The existing database could not be validated safely.",
        ) from exc
    current_schema_key = _vol_schema_version_key(VOL19_GUIDED_DELIVERY_SCHEMA_VERSION)
    assert current_schema_key is not None
    newer = sorted(
        version
        for version in versions
        if (key := _vol_schema_version_key(version)) is not None
        and key > current_schema_key
    )
    if newer:
        raise FirstRunError(
            "NEWER_SCHEMA_UNSUPPORTED",
            "This database was created by a newer TWOS schema and cannot be opened safely.",
        )
    if VOL19_GUIDED_DELIVERY_SCHEMA_VERSION not in versions:
        raise FirstRunError(
            "OLDER_INSTALL_MIGRATION_REQUIRED",
            "This database predates the current Fresh Install schema. Older-install migration is not part of this phase.",
        )
    if (
        len(version_rows) != len(_CANONICAL_FRESH_SCHEMA_VERSIONS)
        or versions != _CANONICAL_FRESH_SCHEMA_VERSIONS
    ):
        raise FirstRunError(
            "DATABASE_INCOMPATIBLE",
            "The existing database schema history is not the exact supported Fresh Install set.",
        )
    expected_binding = (
        settings.installation_id,
        str(data_root),
        str(database_path),
    )
    if not installations and empty_provisioned_database:
        # SQLite DDL is not transactional. A process can stop after the exact
        # canonical schema is provisioned but before the Installation row is
        # committed. Only that structurally complete, otherwise-empty shape
        # is safe to resume; arbitrary or populated databases remain blocked.
        return database_path
    if not installations:
        raise FirstRunError(
            "DATABASE_INCOMPATIBLE",
            "Existing data is not the exact interrupted TWOS Fresh Install database shape.",
        )
    if len(installations) != 1 or tuple(installations[0]) != expected_binding:
        raise FirstRunError(
            "DATABASE_INSTALLATION_MISMATCH",
            "The existing database does not belong to this exact Fresh Install configuration.",
        )
    return database_path


def _private_regular_metadata(
    path: Path,
    *,
    code: str,
    message: str,
) -> os.stat_result | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise FirstRunError(code, message)
    return metadata


def _write_descriptor(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("The private file write did not make progress.")
        remaining = remaining[written:]


def _write_private_text(path: Path, content: str, *, exclusive: bool = False) -> None:
    existing = _private_regular_metadata(
        path,
        code="PRIVATE_FILE_UNSAFE",
        message="A private Fresh Install file path is not an unlinked regular file.",
    )
    if exclusive and existing is not None:
        raise FirstRunError(
            "PRIVATE_FILE_EXISTS",
            "The private Fresh Install file already exists.",
        )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".setup-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_descriptor(descriptor, content.encode("utf-8"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if exclusive:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError as exc:
                raise FirstRunError(
                    "PRIVATE_FILE_EXISTS",
                    "The private Fresh Install file already exists.",
                ) from exc
        else:
            # Replace the directory entry rather than truncating an existing
            # target. This cannot follow a hard link or special file even if a
            # same-user process changes the entry after the lstat check.
            os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_private_json(path: Path) -> dict[str, Any]:
    before = _private_regular_metadata(
        path,
        code="INSTALLATION_CONFIG_UNSAFE",
        message="The installation configuration path is not an unlinked regular file.",
    )
    if before is None:
        return {}
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size > _MAX_PRIVATE_CONFIGURATION_BYTES
        ):
            raise FirstRunError(
                "INSTALLATION_CONFIG_UNSAFE",
                "The installation configuration changed or exceeded its private-file boundary.",
            )
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(8192, _MAX_PRIVATE_CONFIGURATION_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_PRIVATE_CONFIGURATION_BYTES:
                raise FirstRunError(
                    "INSTALLATION_CONFIG_UNSAFE",
                    "The installation configuration exceeded its private-file boundary.",
                )
    except FirstRunError:
        raise
    except OSError as exc:
        raise FirstRunError(
            "INSTALLATION_CONFIG_UNSAFE",
            "The installation configuration could not be read safely.",
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        decoded = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_regular_metadata(
        path,
        code="INSTALLATION_CONFIG_UNSAFE",
        message="The installation configuration path is not an unlinked regular file.",
    )
    descriptor, temporary_name = tempfile.mkstemp(prefix=".installation-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        _write_descriptor(descriptor, serialized.encode("utf-8"))
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _configuration_payload(settings: Settings, installation: Installation) -> dict[str, Any]:
    path = settings.installation_config_path
    existing = _read_private_json(path) if path else {}
    existing.update(
        {
            "installation_id": installation.public_id,
            "source_version": installation.source_version,
            "data_root": installation.data_root,
            "database_path": installation.database_path,
            "runtime_environment": installation.runtime_environment,
            "log_directory": installation.log_directory,
            "bind_host": installation.bind_host,
            "port": installation.bind_port,
            "first_run_state": installation.first_run_state,
            "setup_completed_at": (
                installation.completed_at.isoformat() + "Z"
                if installation.completed_at
                else None
            ),
        }
    )
    return existing


def sync_installation_configuration(settings: Settings, installation: Installation) -> None:
    path = settings.installation_config_path
    if not path:
        return
    data_root = Path(installation.data_root).resolve(strict=True)
    candidate_parent = path.parent.resolve(strict=True)
    try:
        existing_metadata = path.lstat()
    except FileNotFoundError:
        existing_metadata = None
    if (
        not _contains_path(data_root, candidate_parent)
        or (existing_metadata is not None and not stat.S_ISREG(existing_metadata.st_mode))
    ):
        raise FirstRunError(
            "INSTALLATION_CONFIG_UNSAFE",
            "The installation configuration must remain inside the TWOS data root.",
        )
    _atomic_private_json(path, _configuration_payload(settings, installation))


def _issue_setup_authorization(
    session: Session,
    settings: Settings,
    installation: Installation,
) -> str:
    path = settings.setup_authorization_path
    if not path:
        raise FirstRunError(
            "SETUP_AUTHORIZATION_PATH_MISSING",
            "The canonical launcher did not provide a setup-authorization path.",
        )
    data_root = Path(installation.data_root).resolve(strict=True)
    if path.parent.resolve(strict=True) != data_root or path.is_symlink():
        raise FirstRunError(
            "SETUP_AUTHORIZATION_PATH_UNSAFE",
            "The setup authorization must remain in the private TWOS data root.",
        )
    raw_token = secrets.token_urlsafe(24)
    installation.setup_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    installation.setup_token_issued_at = utc_now()
    installation.setup_token_expires_at = utc_now() + SETUP_TOKEN_TTL
    installation.setup_token_used_at = None
    installation.first_run_state = "setup_authorization_pending"
    session.flush()
    _write_private_text(path, raw_token + "\n")
    return raw_token


def initialize_fresh_installation(
    settings: Settings,
    factory: sessionmaker[Session],
) -> Installation | None:
    if not settings.fresh_install:
        return None
    if settings.bind_host != "127.0.0.1":
        raise FirstRunError(
            "BIND_HOST_UNSAFE",
            "Fresh Install may bind only to 127.0.0.1.",
        )
    if settings.bind_port is None or not 1 <= settings.bind_port <= 65535:
        raise FirstRunError("BIND_PORT_INVALID", "The configured localhost port is invalid.")
    if not settings.installation_id or not _INSTALLATION_ID_PATTERN.fullmatch(
        settings.installation_id
    ):
        raise FirstRunError(
            "INSTALLATION_ID_INVALID",
            "The canonical launcher did not provide a valid installation identity.",
        )
    if not _COOKIE_NAME_PATTERN.fullmatch(settings.session_cookie_name):
        raise FirstRunError(
            "SESSION_COOKIE_NAME_INVALID",
            "The installation session-cookie identity is invalid.",
        )
    expected_cookie_name = f"twos_session_{settings.installation_id}"
    if settings.session_cookie_name != expected_cookie_name:
        raise FirstRunError(
            "SESSION_COOKIE_BINDING_MISMATCH",
            "Fresh Install requires an installation-scoped session cookie.",
        )
    if not settings.data_root or not settings.log_directory:
        raise FirstRunError(
            "INSTALLATION_PATHS_MISSING",
            "The canonical launcher did not provide complete installation paths.",
        )
    data_root = validate_data_root(settings.data_root)
    database_path = sqlite_database_path(settings.database_url).resolve(strict=False)
    if database_path.parent.resolve(strict=True) != data_root or database_path.is_symlink():
        raise FirstRunError(
            "DATABASE_PATH_UNSAFE",
            "The Fresh Install database must remain directly inside its data root.",
        )
    log_directory = settings.log_directory.resolve(strict=True)
    if _contains_path(data_root, log_directory):
        # A dedicated logs directory within the private data root is an
        # intentional boundary; it may not alias the root itself.
        if log_directory == data_root:
            raise FirstRunError(
                "LOG_PATH_UNSAFE", "The runtime log directory must be distinct from the data root."
            )
    with factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        installations = session.scalars(select(Installation).order_by(Installation.id)).all()
        if len(installations) > 1:
            raise FirstRunError(
                "INSTALLATION_STATE_INVALID",
                "More than one installation record exists in this data root.",
            )
        installation = installations[0] if installations else None
        if installation is None:
            if (
                session.scalar(select(func.count(User.id)))
                or session.scalar(select(func.count(Project.id)))
                or session.scalar(select(func.count(Task.id)))
            ):
                raise FirstRunError(
                    "INSTALLATION_STATE_INVALID",
                    "Existing Owner or task data cannot be adopted as a Fresh Install.",
                )
            installation = Installation(
                public_id=settings.installation_id,
                source_version=__version__,
                data_root=str(data_root),
                database_path=str(database_path),
                runtime_environment=str(settings.runtime_environment or ""),
                log_directory=str(log_directory),
                bind_host=settings.bind_host,
                bind_port=settings.bind_port,
                first_run_state="uninitialized",
            )
            session.add(installation)
            session.flush()
            _issue_setup_authorization(session, settings, installation)
        else:
            expected = {
                "public_id": settings.installation_id,
                "source_version": __version__,
                "data_root": str(data_root),
                "database_path": str(database_path),
                "runtime_environment": str(settings.runtime_environment or ""),
                "log_directory": str(log_directory),
                "bind_host": settings.bind_host,
                "bind_port": settings.bind_port,
            }
            mismatched = [
                field for field, value in expected.items() if getattr(installation, field) != value
            ]
            if mismatched:
                raise FirstRunError(
                    "INSTALLATION_BINDING_MISMATCH",
                    "The runtime does not match the persisted installation configuration.",
                )
            if installation.first_run_state not in FIRST_RUN_STATES:
                raise FirstRunError(
                    "INSTALLATION_STATE_INVALID",
                    "The persisted First Run state is not supported.",
                )
            token_path = settings.setup_authorization_path
            token_expired = bool(
                installation.setup_token_expires_at
                and installation.setup_token_expires_at <= utc_now()
            )
            if installation.owner_user_id is None and (
                token_expired or not token_path or not token_path.exists()
            ):
                preserved_state = installation.first_run_state
                _issue_setup_authorization(session, settings, installation)
                if preserved_state in {
                    "installation_confirmation_pending",
                    "owner_creation_pending",
                }:
                    installation.first_run_state = preserved_state
            elif installation.owner_user_id is not None and token_path and token_path.exists():
                consume_setup_authorization_file(settings)
        workspace = session.scalar(
            select(AuthorizedWorkspace).where(
                AuthorizedWorkspace.installation_id == installation.id
            )
        )
        if workspace:
            workspace_path, workspace_metadata, workspace_identity = validate_authorized_workspace(
                workspace.canonical_path,
                settings=settings,
                create_if_missing=False,
            )
            if (
                workspace.identity_digest != workspace_identity
                or workspace.device_id != int(workspace_metadata.st_dev)
                or workspace.inode != int(workspace_metadata.st_ino)
            ):
                raise FirstRunError(
                    "WORKSPACE_IDENTITY_CHANGED",
                    "The authorized workspace identity changed. Review is required before TWOS can resume.",
                )
            object.__setattr__(settings, "source_repo", workspace_path)
        _validate_installation_invariants(session, settings, installation)
        session.commit()
        sync_installation_configuration(settings, installation)
        return installation


def _validate_installation_invariants(
    session: Session,
    settings: Settings,
    installation: Installation,
) -> AuthorizedWorkspace | None:
    users = session.scalars(select(User).order_by(User.id).limit(2)).all()
    workspace = session.scalar(
        select(AuthorizedWorkspace).where(
            AuthorizedWorkspace.installation_id == installation.id
        )
    )
    if installation.owner_user_id is None:
        if users or workspace is not None:
            raise FirstRunError(
                "INSTALLATION_LINEAGE_INVALID",
                "Fresh Install Owner state does not match the persisted installation.",
            )
        if installation.first_run_state not in {
            "uninitialized",
            "setup_authorization_pending",
            "installation_confirmation_pending",
            "owner_creation_pending",
            "failed",
        }:
            raise FirstRunError(
                "INSTALLATION_LINEAGE_INVALID",
                "First Run advanced without a valid Owner.",
            )
        return None
    if (
        len(users) != 1
        or users[0].id != installation.owner_user_id
        or owner_record_issue(users[0]) is not None
    ):
        raise FirstRunError(
            "INSTALLATION_OWNER_INVALID",
            "The persisted first Owner is missing, disabled, or invalid.",
        )
    if workspace is None:
        if installation.first_run_state not in {"workspace_pending", "failed"}:
            raise FirstRunError(
                "INSTALLATION_LINEAGE_INVALID",
                "First Run advanced without an authorized workspace.",
            )
        return None
    if workspace.owner_user_id != installation.owner_user_id or session.get(Project, workspace.project_id) is None:
        raise FirstRunError(
            "WORKSPACE_BINDING_INVALID",
            "The authorized workspace binding is incomplete.",
        )
    if installation.first_run_state not in {
        "optional_tools_pending",
        "completion_pending",
        "ready",
        "failed",
    }:
        raise FirstRunError(
            "INSTALLATION_LINEAGE_INVALID",
            "The authorized workspace does not match the First Run step.",
        )
    current_path, metadata, identity = validate_authorized_workspace(
        workspace.canonical_path,
        settings=settings,
        create_if_missing=False,
    )
    if (
        str(current_path) != workspace.canonical_path
        or int(metadata.st_dev) != workspace.device_id
        or int(metadata.st_ino) != workspace.inode
        or identity != workspace.identity_digest
    ):
        raise FirstRunError(
            "WORKSPACE_IDENTITY_CHANGED",
            "The authorized workspace identity changed. Review is required before TWOS can resume.",
        )
    if settings.source_repo.resolve(strict=False) != current_path:
        raise FirstRunError(
            "WORKSPACE_RUNTIME_BINDING_MISMATCH",
            "The running TWOS process is not bound to the authorized workspace.",
        )
    if installation.first_run_state == "ready" and installation.completed_at is None:
        raise FirstRunError(
            "INSTALLATION_LINEAGE_INVALID",
            "First Run completion evidence is missing.",
        )
    return workspace


def active_installation(session: Session) -> Installation:
    rows = session.scalars(select(Installation).order_by(Installation.id).limit(2)).all()
    if len(rows) != 1:
        raise FirstRunError(
            "INSTALLATION_STATE_INVALID",
            "The First Run installation record is unavailable.",
        )
    return rows[0]


def _display_path(path_text: str, *, reveal: bool) -> str:
    path = Path(path_text)
    home = Path.home()
    try:
        relative = path.relative_to(home)
    except ValueError:
        if reveal:
            return str(path)
        return f"Local directory: {path.name or 'TWOS data'}"
    return "~" if str(relative) == "." else str(Path("~") / relative)


def _optional_tool_state(installation: Installation) -> dict[str, str]:
    try:
        decoded = json.loads(installation.optional_tools_state or "{}")
    except json.JSONDecodeError:
        decoded = {}
    codex = str(decoded.get("codex") or "not_checked").casefold()
    if codex not in {"ready", "needs_setup", "unavailable", "not_checked", "skipped"}:
        codex = "not_checked"
    return {"codex": codex}


def first_run_status(
    session: Session,
    settings: Settings,
    *,
    authenticated_user: User | None = None,
) -> dict[str, Any]:
    if not settings.fresh_install:
        return {"enabled": False, "state": "ready", "current_step": "complete"}
    installation = active_installation(session)
    invariant_failure: FirstRunError | None = None
    try:
        _validate_installation_invariants(session, settings, installation)
    except FirstRunError as exc:
        invariant_failure = exc
    owner = session.get(User, installation.owner_user_id) if installation.owner_user_id else None
    workspace = session.scalar(
        select(AuthorizedWorkspace).where(
            AuthorizedWorkspace.installation_id == installation.id
        )
    )
    state = "failed" if invariant_failure else installation.first_run_state
    progress_state = effective_setup_state(installation)
    authenticated_owner = bool(
        authenticated_user and owner and authenticated_user.id == owner.id
    )
    task_count = int(session.scalar(select(func.count(Task.id))) or 0)
    completed: list[str] = []
    if progress_state not in {"uninitialized", "setup_authorization_pending"}:
        completed.append("welcome")
    if progress_state not in {
        "uninitialized",
        "setup_authorization_pending",
        "installation_confirmation_pending",
    }:
        completed.append("installation")
    if owner:
        completed.append("owner")
    if workspace:
        completed.append("workspace")
    if progress_state in {"completion_pending", "ready"}:
        completed.append("optional_tools")
    if progress_state == "ready":
        completed.append("finish")
        if task_count:
            completed.append("first_task")
    step_map = {
        "uninitialized": "welcome",
        "setup_authorization_pending": "welcome",
        "installation_confirmation_pending": "installation",
        "owner_creation_pending": "owner",
        "workspace_pending": "workspace",
        "optional_tools_pending": "optional_tools",
        "completion_pending": "finish",
        "ready": "complete" if task_count else "first_task",
        "failed": "failed",
    }
    next_map = {
        "uninitialized": "Start First Run setup.",
        "setup_authorization_pending": "Start First Run setup.",
        "installation_confirmation_pending": "Confirm the local installation and data-root boundary.",
        "owner_creation_pending": "Create the first Owner with the one-time setup authorization.",
        "workspace_pending": "Authorize one local workspace.",
        "optional_tools_pending": "Review or skip optional tool readiness.",
        "completion_pending": "Review the summary and explicitly finish setup.",
        "ready": (
            "Reopen the saved first task in the Owner workbench."
            if task_count
            else "Create and save the first task. Saving does not start a Run or contact a provider."
        ),
        "failed": "Review the setup blocker before retrying.",
    }
    tool_state = _optional_tool_state(installation)
    authorization_expired = bool(
        installation.setup_token_expires_at
        and installation.setup_token_expires_at <= utc_now()
        and installation.setup_token_used_at is None
    )
    return {
        "enabled": True,
        "state": state,
        "current_step": step_map[progress_state] if state == "failed" and not invariant_failure else step_map[state],
        "completed_steps": completed,
        "next_action": (
            "Correct the blocker, then explicitly retry this step. " + next_map[progress_state]
            if state == "failed" and not invariant_failure
            else next_map[state]
        ),
        "blocking_reason": (
            invariant_failure.message
            if invariant_failure
            else installation.failure_reason if state == "failed" else None
        ),
        "owner_exists": owner is not None,
        "authenticated": authenticated_owner,
        "owner": {"username": owner.username} if owner and authenticated_user else None,
        "installation": {
            "source_version": installation.source_version,
            "data_root_summary": _display_path(
                installation.data_root, reveal=authenticated_owner
            ),
            "database_initialized": True,
            "bind_host": installation.bind_host,
            "port": installation.bind_port,
            "localhost_only": installation.bind_host == "127.0.0.1",
            "isolated_runtime": bool(
                installation.runtime_environment
                and Path(installation.runtime_environment).resolve(strict=False)
                == Path(sys.prefix).resolve(strict=False)
            ),
            "workspace_summary": (
                _display_path(workspace.canonical_path, reveal=authenticated_owner)
                if workspace
                else None
            ),
        },
        "setup_authorization": {
            "required": owner is None,
            "available": bool(
                installation.setup_token_hash
                and installation.setup_token_used_at is None
                and not authorization_expired
            ),
            "expired": authorization_expired,
            "single_use": True,
            "method": "Enter the one-time code created by the local launcher.",
        },
        "optional_tools": [
            {
                "name": "Codex",
                "status": tool_state["codex"],
                "external_request_performed": False,
            }
        ],
        "external_action_will_occur": False,
        "first_task_created": task_count > 0,
        "task_count": task_count if authenticated_owner else None,
    }


def start_first_run(
    session: Session,
    settings: Settings,
    *,
    confirmation: str,
) -> Installation:
    installation = active_installation(session)
    if confirmation == "START_FIRST_RUN" and installation.first_run_state in {
        "setup_authorization_pending", "uninitialized"
    }:
        installation.first_run_state = "installation_confirmation_pending"
        session.flush()
        return installation
    if (
        confirmation == "CONFIRM_INSTALLATION"
        and installation.first_run_state == "installation_confirmation_pending"
    ):
        installation.first_run_state = "owner_creation_pending"
        session.flush()
        return installation
    if (
        confirmation == "START_FIRST_RUN"
        and installation.first_run_state == "installation_confirmation_pending"
    ) or (
        confirmation == "CONFIRM_INSTALLATION"
        and installation.first_run_state == "owner_creation_pending"
    ):
        return installation
    raise FirstRunError(
        "SETUP_STEP_ALREADY_COMPLETED",
        "First Run has already advanced beyond the Welcome step.",
    )


def create_first_owner(
    session: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    password_confirmation: str,
    setup_authorization: str,
    request_id: str,
) -> tuple[User, str | None, bool]:
    installation = active_installation(session)
    normalized = normalize_username(username)
    supplied_hash = hashlib.sha256(setup_authorization.encode("utf-8")).hexdigest()
    # The idempotency receipt contains only non-secret request identity. The
    # canonical password verifier below proves a replay's credential without
    # persisting a fast password-derived digest beside the PBKDF2 record.
    request_digest = hashlib.sha256(
        f"first-owner-v1\0{request_id}\0{normalized}".encode("utf-8")
    ).hexdigest()
    existing_owner = (
        session.get(User, installation.owner_user_id)
        if installation.owner_user_id
        else session.scalar(select(User).order_by(User.id))
    )
    if existing_owner is not None:
        if (
            installation.owner_setup_request_id == request_id
            and installation.owner_setup_request_digest == request_digest
            and normalize_username(existing_owner.username) == normalized
        ):
            if owner_record_issue(existing_owner) or not verify_password(
                password, existing_owner.password_hash, existing_owner.password_salt
            ):
                raise FirstRunError("FIRST_OWNER_LOGIN_REQUIRED", "Log in as the first Owner to resume setup.", 401)
            # Replay returns the existing creation receipt. It neither reuses
            # setup authorization nor mints a new session. A lost original
            # cookie is recovered through the normal login route.
            return existing_owner, None, False
        raise FirstRunError(
            "FIRST_OWNER_EXISTS",
            "The first Owner already exists. Log in to resume setup.",
        )
    if installation.first_run_state != "owner_creation_pending":
        raise FirstRunError(
            "SETUP_STEP_NOT_READY",
            "Start First Run before creating the first Owner.",
        )
    if password != password_confirmation:
        raise FirstRunError(
            "PASSWORD_CONFIRMATION_MISMATCH",
            "The password confirmation does not match.",
            400,
        )
    if (
        not installation.setup_token_hash
        or installation.setup_token_used_at is not None
        or installation.setup_token_expires_at is None
        or installation.setup_token_expires_at <= utc_now()
        or not secrets.compare_digest(installation.setup_token_hash, supplied_hash)
    ):
        raise FirstRunError(
            "SETUP_AUTHORIZATION_INVALID",
            "The one-time setup authorization is invalid or expired.",
            403,
        )
    owner = create_owner(session, username, password)
    user, raw_token, _ = authenticate(
        session, username, password, settings.session_ttl_seconds
    )
    installation.owner_user_id = owner.id
    installation.setup_token_used_at = utc_now()
    installation.setup_token_hash = None
    installation.owner_setup_request_id = request_id
    installation.owner_setup_request_digest = request_digest
    installation.first_run_state = "workspace_pending"
    session.flush()
    return user, raw_token, True


def consume_setup_authorization_file(settings: Settings) -> None:
    path = settings.setup_authorization_path
    if not path:
        return
    metadata = _private_regular_metadata(
        path,
        code="SETUP_AUTHORIZATION_PATH_UNSAFE",
        message="The setup-authorization file boundary changed unexpectedly.",
    )
    if metadata is None:
        return
    # Recheck the directory entry immediately before removal. Unlink never
    # follows a target, and a changed entry is rejected rather than consumed.
    current = _private_regular_metadata(
        path,
        code="SETUP_AUTHORIZATION_PATH_UNSAFE",
        message="The setup-authorization file boundary changed unexpectedly.",
    )
    if current is None:
        return
    if current.st_dev != metadata.st_dev or current.st_ino != metadata.st_ino:
        raise FirstRunError(
            "SETUP_AUTHORIZATION_PATH_UNSAFE",
            "The setup-authorization file boundary changed unexpectedly.",
        )
    try:
        path.unlink()
    except FileNotFoundError:
        # Concurrent reconciliation may already have retired the consumed
        # one-time file. Database truth remains authoritative.
        return


def validate_authorized_workspace(
    raw_path: str,
    *,
    settings: Settings,
    create_if_missing: bool,
) -> tuple[Path, os.stat_result, str]:
    if not isinstance(raw_path, str) or not raw_path or _has_unsafe_text(raw_path):
        raise FirstRunError("WORKSPACE_INVALID", "Enter a valid local workspace path.", 400)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise FirstRunError(
            "WORKSPACE_TRAVERSAL",
            "Choose an absolute workspace without traversal components.",
            400,
        )
    _reject_symlink_components(candidate)
    prospective = candidate.resolve(strict=False)
    _validate_workspace_boundaries(prospective, settings)
    if not candidate.exists():
        if not create_if_missing:
            raise FirstRunError(
                "WORKSPACE_MISSING",
                "The workspace does not exist. Choose Create directory explicitly or select an existing folder.",
                400,
            )
        parent = candidate.parent
        _reject_symlink_components(parent)
        if not parent.exists() or not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            raise FirstRunError(
                "WORKSPACE_PARENT_NOT_WRITABLE",
                "The workspace parent is not a writable directory.",
                400,
            )
        candidate.mkdir(mode=0o700)
    resolved = candidate.resolve(strict=True)
    if candidate.is_symlink() or not resolved.is_dir():
        raise FirstRunError("WORKSPACE_NOT_DIRECTORY", "The workspace must be a directory.", 400)
    mode = resolved.stat().st_mode
    if not stat.S_ISDIR(mode) or not os.access(resolved, os.W_OK | os.X_OK):
        raise FirstRunError(
            "WORKSPACE_NOT_WRITABLE",
            "The workspace must be writable by the current Owner account.",
            400,
        )
    _validate_workspace_boundaries(resolved, settings)
    metadata = resolved.stat()
    identity = hashlib.sha256(
        f"{resolved}\0{metadata.st_dev}\0{metadata.st_ino}".encode("utf-8")
    ).hexdigest()
    return resolved, metadata, identity


def _validate_workspace_boundaries(resolved: Path, settings: Settings) -> None:
    home = Path.home().resolve(strict=True)
    distribution_root = ROOT_DIR.resolve(strict=True)
    data_root = settings.data_root.resolve(strict=True) if settings.data_root else None
    if resolved == home:
        raise FirstRunError(
            "WORKSPACE_SCOPE_TOO_BROAD",
            "Choose a dedicated workspace rather than authorizing the entire home directory.",
            400,
        )
    if _contains_path(distribution_root, resolved) or _contains_path(resolved, distribution_root):
        raise FirstRunError(
            "WORKSPACE_IS_TWOS_SOURCE",
            "Choose a workspace outside the TWOS source repository.",
            400,
        )
    if data_root and (_contains_path(data_root, resolved) or _contains_path(resolved, data_root)):
        raise FirstRunError(
            "WORKSPACE_IS_DATA_ROOT",
            "Choose a workspace separate from the TWOS data root.",
            400,
        )
    protected_roots = [
        settings.runtime_environment,
        settings.log_directory,
        settings.worktree_root,
        settings.codex_spool_root,
    ]
    for protected in protected_roots:
        if not protected:
            continue
        protected_resolved = protected.resolve(strict=False)
        if _contains_path(protected_resolved, resolved) or _contains_path(
            resolved, protected_resolved
        ):
            raise FirstRunError(
                "WORKSPACE_IS_RUNTIME_ROOT",
                "Choose a workspace separate from TWOS runtime, log, and process-data directories.",
                400,
            )
    # Downstream Git operations always resolve to a repository top level. Do
    # not let an apparently narrow subdirectory authorization expand later.
    for ancestor in (resolved, *resolved.parents):
        git_boundary = ancestor / ".git"
        if git_boundary.is_symlink():
            raise FirstRunError(
                "WORKSPACE_GIT_BOUNDARY_UNSAFE",
                "The workspace contains an unsafe Git boundary.",
                400,
            )
        if git_boundary.exists():
            if ancestor != resolved:
                raise FirstRunError(
                    "WORKSPACE_NOT_REPOSITORY_ROOT",
                    "Choose the repository root rather than a directory inside it.",
                    400,
                )
            break


def authorize_workspace(
    session: Session,
    settings: Settings,
    *,
    owner: User,
    path: str,
    create_if_missing: bool,
) -> AuthorizedWorkspace:
    installation = active_installation(session)
    if installation.owner_user_id != owner.id:
        raise FirstRunError("OWNER_SCOPE_MISMATCH", "The setup Owner does not match this installation.", 403)
    existing = session.scalar(
        select(AuthorizedWorkspace).where(
            AuthorizedWorkspace.installation_id == installation.id
        )
    )
    if existing:
        if not isinstance(path, str) or not path or _has_unsafe_text(path):
            raise FirstRunError("WORKSPACE_INVALID", "Enter a valid local workspace path.", 400)
        requested = Path(path).expanduser()
        requested_resolved = requested.resolve(strict=False) if requested.is_absolute() else requested
        if str(requested_resolved) == existing.canonical_path:
            resolved, metadata, identity = validate_authorized_workspace(
                existing.canonical_path,
                settings=settings,
                create_if_missing=False,
            )
            if existing.identity_digest == identity and existing.canonical_path == str(resolved):
                return existing
        raise FirstRunError(
            "WORKSPACE_ALREADY_AUTHORIZED",
            "This installation already has a different authorized workspace.",
        )
    if effective_setup_state(installation) != "workspace_pending":
        raise FirstRunError("SETUP_STEP_NOT_READY", "Workspace authorization is not the current setup step.")
    resolved, metadata, identity = validate_authorized_workspace(
        path, settings=settings, create_if_missing=create_if_missing
    )
    clear_setup_failure(installation)
    project = Project(
        key=f"workspace-{identity[:16]}",
        name=resolved.name or "Owner workspace",
        status="active",
    )
    session.add(project)
    session.flush()
    workspace = AuthorizedWorkspace(
        installation_id=installation.id,
        owner_user_id=owner.id,
        project_id=project.id,
        canonical_path=str(resolved),
        device_id=int(metadata.st_dev),
        inode=int(metadata.st_ino),
        identity_digest=identity,
    )
    session.add(workspace)
    installation.first_run_state = "optional_tools_pending"
    session.flush()
    return workspace


def review_optional_tools(
    session: Session,
    settings: Settings,
    *,
    owner: User,
    decision: str,
) -> Installation:
    installation = active_installation(session)
    if installation.owner_user_id != owner.id:
        raise FirstRunError("OWNER_SCOPE_MISMATCH", "The setup Owner does not match this installation.", 403)
    _validate_installation_invariants(session, settings, installation)
    if effective_setup_state(installation) not in {"optional_tools_pending", "completion_pending"}:
        raise FirstRunError("SETUP_STEP_NOT_READY", "Optional tool review is not the current setup step.")
    if decision == "skip":
        codex_state = "skipped"
    elif decision == "review":
        # This is deliberately passive. Executable/authentication/provider
        # probes remain behind the Owner's separate explicit Check action.
        codex_state = "needs_setup"
    else:
        raise FirstRunError("OPTIONAL_TOOL_DECISION_INVALID", "Choose Review or Skip.", 400)
    clear_setup_failure(installation)
    installation.optional_tools_state = json.dumps(
        {"codex": codex_state}, separators=(",", ":"), sort_keys=True
    )
    installation.first_run_state = "completion_pending"
    session.flush()
    return installation


def finish_first_run(
    session: Session,
    settings: Settings,
    *,
    owner: User,
) -> Installation:
    installation = active_installation(session)
    workspace = session.scalar(
        select(AuthorizedWorkspace).where(
            AuthorizedWorkspace.installation_id == installation.id,
            AuthorizedWorkspace.owner_user_id == owner.id,
        )
    )
    if installation.owner_user_id != owner.id or workspace is None:
        raise FirstRunError("SETUP_INCOMPLETE", "Owner and workspace setup must be complete.")
    _validate_installation_invariants(session, settings, installation)
    if effective_setup_state(installation) == "ready":
        return installation
    if effective_setup_state(installation) != "completion_pending":
        raise FirstRunError("SETUP_STEP_NOT_READY", "Review optional tools before finishing setup.")
    clear_setup_failure(installation)
    installation.first_run_state = "ready"
    installation.completed_at = utc_now()
    session.flush()
    return installation


def effective_setup_state(installation: Installation) -> str:
    if installation.first_run_state == "failed":
        return installation.resume_state or "failed"
    return installation.first_run_state


def clear_setup_failure(installation: Installation) -> None:
    if installation.first_run_state == "failed" and installation.resume_state:
        installation.first_run_state = installation.resume_state
    installation.failure_code = None
    installation.failure_reason = None
    installation.resume_state = None


def persist_setup_failure(session: Session, settings: Settings, error: FirstRunError) -> None:
    """Retain a failed explicit setup step without undoing earlier progress."""
    installation = active_installation(session)
    current = effective_setup_state(installation)
    if current not in {"workspace_pending", "optional_tools_pending", "completion_pending"}:
        return
    installation.resume_state = current
    installation.first_run_state = "failed"
    installation.failure_code = error.code
    installation.failure_reason = error.message
    session.commit()


def normal_api_available(session: Session, settings: Settings) -> bool:
    if not settings.fresh_install:
        return True
    try:
        installation = active_installation(session)
        _validate_installation_invariants(session, settings, installation)
        return installation.first_run_state == "ready"
    except FirstRunError:
        return False
