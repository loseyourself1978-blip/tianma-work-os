"""Local, explicit maintenance. Historical execution evidence is never replayed.

The journal is outside the replaceable database. A sealed backup is a directory,
not an archive: only enumerated regular files can be inspected or activated.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

FORMAT = "TWOS_BACKUP_V1"
TARGET_SCHEMA = "vol20.001"
SUPPORTED_SCHEMAS = ("vol19.003", "vol19.004", "vol19.005", TARGET_SCHEMA)
TERMINAL_OPERATIONS = {"BACKUP_COMPLETE", "BACKUP_FAILED", "RESTORE_COMPLETE",
    "RESTORE_FAILED", "MIGRATION_COMPLETE", "MIGRATION_FAILED", "RECOVERY_COMPLETE"}


class MaintenanceError(ValueError):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status_code = code, message, status
        super().__init__(message)


def fail(code, message, status=409):
    raise MaintenanceError(code, message, status)


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_path(value, *, exists=True, directory=False):
    raw = str(value)
    path = Path(raw).expanduser()
    if not path.is_absolute() or ".." in path.parts or any(ord(c) < 32 for c in raw):
        fail("UNSAFE_PATH", "Use an absolute local path without traversal or control characters.", 400)
    for part in (path, *path.parents):
        if part.is_symlink():
            fail("UNSAFE_PATH", "Symbolic links are not supported for maintenance storage.", 400)
    if not exists and path.exists():
        metadata = path.stat()
        if not (stat.S_ISDIR(metadata.st_mode) or (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1)):
            fail("UNSAFE_PATH", "Maintenance cannot replace a linked or special filesystem entry.", 400)
    if exists:
        try:
            metadata = path.stat()
        except OSError:
            fail("PATH_UNAVAILABLE", "The selected local maintenance path is unavailable.", 400)
        if directory:
            valid = stat.S_ISDIR(metadata.st_mode)
        else:
            valid = stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
        if not valid:
            fail("UNSAFE_PATH", "Maintenance requires a regular unlinked file or a local directory.", 400)
    return path


def private_directory(path):
    safe_path(path, exists=False)
    existed = path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not existed:
        fsync_directory(path.parent)
    safe_path(path, directory=True)
    if path.stat().st_mode & 0o077:
        fail("STORAGE_PERMISSIONS", "Maintenance storage must be private to the local user.")
    return path


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    safe_path(path, exists=False)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".writing")
    safe_path(temporary, exists=False)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def read_json(path):
    safe_path(path)
    if path.stat().st_size > 8_000_000:
        fail("INVALID_MANIFEST", "Maintenance metadata exceeds its supported size.", 400)
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError):
        fail("INVALID_MANIFEST", "Maintenance metadata is invalid. Select a complete sealed backup.", 400)
    if not isinstance(value, dict):
        fail("INVALID_MANIFEST", "Maintenance metadata must be an object.", 400)
    return value


def database_path(url):
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        fail("DATABASE_UNSUPPORTED", "Backup and recovery require a file-backed local SQLite installation.")
    return safe_path(Path(parsed.database).absolute(), exists=False)


def storage_root(db):
    return db.parent / ("." + db.name + ".maintenance")


def connection_lock_path(db):
    return db.parent / ("." + db.name + ".maintenance.lock")


def open_lock(db, *, exclusive=False):
    path = connection_lock_path(db)
    safe_path(path, exists=False)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        fail("INSTALLATION_BUSY", "Another connection or runtime is using this installation. Finish its action or stop that runtime, then retry.")
    return fd


def install_connection_barrier(engine):
    """Every normal SQLite connection holds a shared cross-process lease.

    Maintenance requires all pools disposed and an exclusive lease. The lease
    belongs to the DBAPI connection and closes with it, including error paths.
    """
    from sqlalchemy import event
    try:
        db = database_path(str(engine.url))
    except MaintenanceError as exc:
        if exc.code == "DATABASE_UNSUPPORTED":
            return
        raise

    @event.listens_for(engine, "connect")
    def connected(connection, record):
        try:
            record.info["maintenance_fd"] = open_lock(db)
        except BaseException:
            # SQLAlchemy cannot hand a rejected connection to its pool. Close
            # the DBAPI handle here, even while an exception traceback lives.
            connection.close()
            raise

    @event.listens_for(engine, "close")
    def closed(connection, record):
        fd = record.info.pop("maintenance_fd", None)
        if fd is not None:
            os.close(fd)


@contextmanager
def readonly(db):
    safe_path(db)
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        yield connection


def tables(connection):
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def inspect_database(db, *, allow_legacy=True):
    from .first_run import _CANONICAL_FRESH_SCHEMA_VERSIONS
    try:
        with readonly(db) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                fail("DATABASE_CORRUPT", "SQLite integrity verification failed.")
            names = tables(connection)
            if not {"schema_versions", "users", "tasks", "codex_runs", "codex_instruction_packs"} <= names:
                fail("SCHEMA_UNSUPPORTED", "This is not a supported historical TWOS database.")
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_versions")]
            if len(versions) != len(set(versions)) or set(versions) - _CANONICAL_FRESH_SCHEMA_VERSIONS:
                fail("SCHEMA_UNSUPPORTED", "Unknown or future schema history. Use a compatible TWOS version.")
            latest = next((v for v in reversed(SUPPORTED_SCHEMAS) if v in versions), None)
            if latest is None or (not allow_legacy and latest != TARGET_SCHEMA):
                fail("SCHEMA_UNSUPPORTED", "Supported migration sources are vol19.003 through vol19.005; restore requires vol20.001.")
            expected = set(_CANONICAL_FRESH_SCHEMA_VERSIONS) - {v for v in SUPPORTED_SCHEMAS if v > latest}
            if set(versions) != expected:
                fail("SCHEMA_UNSUPPORTED", "The schema history is incomplete; restore a verified recovery point.")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                fail("DATABASE_CORRUPT", "Database relationship verification failed.")
            owners = [dict(row) for row in connection.execute("SELECT id, username, password_hash, password_salt, is_active FROM users ORDER BY id")]
            installation = None
            if "installations" in names:
                records = [dict(row) for row in connection.execute("SELECT * FROM installations")]
                if len(records) > 1:
                    fail("INSTALLATION_INVALID", "More than one installation identity is present.")
                installation = records[0] if records else None
            return {"schema": latest, "versions": sorted(versions), "tables": sorted(names),
                    "installation": installation, "owners": owners,
                    "counts": {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
                        for name in ("users", "tasks", "codex_instruction_packs", "codex_runs", "codex_result_envelopes", "apply_sessions", "local_commit_executions", "push_executions") if name in names}}
    except sqlite3.Error:
        fail("DATABASE_CORRUPT", "The database cannot be inspected safely. The active installation was not changed.")


def safe_state(db):
    checks = {
        "codex_runs": ("status", ("queued", "starting", "running", "verifying", "settling")),
        "codex_execution_attempts": ("attempt_state", ("QUEUED", "STARTING", "RUNNING", "SETTLING", "VERIFICATION_ELIGIBLE")),
        "codex_run_monitors": ("monitor_state", ("QUEUED", "STARTING", "RUNNING", "VERIFYING", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "PROCESS_LOST", "RESULT_PENDING")),
        "task_runs": ("status", ("queued", "running")),
        "apply_sessions": ("state", ("APPLYING", "REVERTING", "APPLY_FAILED_PARTIAL", "REVERT_FAILED_PARTIAL")),
        "stage_executions": ("state", ("STAGING", "INTEGRITY_BLOCKED")),
        "local_commit_executions": ("state", ("COMMITTING",)),
        "push_executions": ("state", ("PUSHING", "RECONCILIATION_BLOCKED")),
    }
    with readonly(db) as connection:
        names = tables(connection)
        for table, (column, active) in checks.items():
            if table not in names:
                continue
            row = connection.execute(f'SELECT id, "{column}" FROM "{table}" WHERE "{column}" IN ({",".join("?" for _ in active)}) LIMIT 1', active).fetchone()
            if row:
                fail("ACTIVE_OPERATION", f"{table} #{row[0]} is {row[1]}. Complete or resolve that operation before maintenance.")
        if {"codex_run_monitors", "codex_runs", "codex_result_envelopes"} <= names:
            from .result_intake import PERSISTED_RESULT_SETTLEMENT_SECONDS, TERMINAL_RUN_STATES
            pending = connection.execute("SELECT m.id, COALESCE(m.terminal_at,r.finished_at) FROM codex_run_monitors m JOIN codex_runs r ON r.id=m.run_id LEFT JOIN codex_result_envelopes e ON e.run_id=r.id WHERE m.monitor_state IN ('RESULT_UNAVAILABLE','RESULT_INTEGRITY_BLOCKED','PROCESS_LOST') AND r.status IN ("+','.join('?' for _ in TERMINAL_RUN_STATES)+") AND r.structured_result NOT IN ('','{}') AND e.id IS NULL", tuple(TERMINAL_RUN_STATES)).fetchall()
            for row in pending:
                if row[1]:
                    anchor = datetime.fromisoformat(row[1])
                    if anchor.tzinfo is None:
                        anchor = anchor.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - anchor).total_seconds() <= PERSISTED_RESULT_SETTLEMENT_SECONDS:
                        fail("RESULT_SETTLING", f"Run monitor #{row[0]} still has terminal evidence awaiting Result settlement. Wait for its canonical Result before maintenance.")
        if "stage_executions" in names:
            row = connection.execute("SELECT s.id FROM stage_executions s WHERE s.state='STAGED' AND NOT EXISTS (SELECT 1 FROM local_commit_executions c WHERE c.stage_execution_id=s.id AND c.state='COMMITTED') LIMIT 1").fetchone()
            if row:
                fail("UNRESOLVED_STAGE", f"Stage #{row[0]} has no completed Commit. Resolve its existing delivery flow before maintenance.")


def snapshot(source, target, *, remove_sessions=False):
    safe_path(target, exists=False)
    with readonly(source) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy)
        if remove_sessions:
            copy.execute("DELETE FROM session_tokens")
            if "installations" in tables(copy):
                copy.execute("UPDATE installations SET setup_token_hash=NULL, setup_token_issued_at=NULL, setup_token_expires_at=NULL")
            copy.commit()
            copy.execute("VACUUM")
        copy.execute("PRAGMA journal_mode=DELETE")
    os.chmod(target, 0o600)
    with target.open("rb") as stream:
        os.fsync(stream.fileno())


def activate_database(staged, destination):
    """Call only under the exclusive lease and an activation/rollback journal."""
    safe_path(staged)
    safe_path(destination, exists=False)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(destination) + suffix)
        if sidecar.exists():
            safe_path(sidecar).unlink()
    os.replace(staged, destination)
    fsync_directory(destination.parent)


def reject_secret_value(value, component):
    from .codex_adapter import _PROVIDER_TOKEN, _COMMON_PROVIDER_TOKEN, _BEARER_TOKEN, _PRIVATE_KEY_BLOCK
    patterns = (_PROVIDER_TOKEN, _COMMON_PROVIDER_TOKEN, _BEARER_TOKEN, _PRIVATE_KEY_BLOCK)
    credential = re.compile(r'''(?i)\b(?:access_token|refresh_token|api_key|client_secret|password|cookie)\b["']?\s*[:=]\s*["']?([^\s,"';}]+)''')
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='ignore')
    if isinstance(value, str) and (any(pattern.search(value) for pattern in patterns) or any(
        match.group(1).lower() not in {'[redacted]', '<redacted>', 'null', 'none', 'false', 'true'}
        for match in credential.finditer(value)
    )):
        fail("STORED_CREDENTIAL_BLOCKED", f"Credential-like content in {component} cannot be included in a backup. Review that TWOS record; no credential value was returned or logged.")


def reject_external_secrets(db):
    """Refuse credential-bearing content rather than rewrite immutable evidence.

    Password hashes/salts are necessary account records. Sessions are removed
    from the snapshot. This check never reads external credential stores.
    """
    with readonly(db) as connection:
        for name in tables(connection) - {"sqlite_sequence"}:
            for row in connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"'):
                for value in row:
                    reject_secret_value(value, name)


class Maintenance:
    def __init__(self, settings, *, fault=None):
        self.settings = settings
        self.db = database_path(settings.database_url)
        self.root = storage_root(self.db)
        self.backups = self.root / "backups"
        self.journal_path = self.root / "operation.json"
        self.authority_path = self.root / "authority.json"
        self.fault = fault or (lambda boundary: None)

    def prepare(self):
        private_directory(self.root)
        private_directory(self.backups)

    def logical_installation_id(self, info, *, create=False):
        if info.get("installation"):
            return info["installation"]["public_id"]
        path = self.root / "logical-identity.json"
        if path.exists():
            value = read_json(path).get("installation_id", "")
            if not re.fullmatch(r"legacy-[0-9a-f]{32}", value):
                fail("INSTALLATION_INVALID", "The legacy logical installation identity is invalid.")
            return value
        if not create:
            return "Not recorded; first explicit backup establishes legacy identity"
        value = "legacy-" + uuid.uuid4().hex
        atomic_json(path, {"installation_id": value})
        return value

    @contextmanager
    def exclusive(self):
        self.prepare()
        fd = open_lock(self.db, exclusive=True)
        try:
            yield
        finally:
            os.close(fd)

    def journal(self):
        if not self.journal_path.exists():
            return {"state": "NONE"}
        value = read_json(self.journal_path)
        if (not re.fullmatch(r"[0-9a-f]{32}", str(value.get("operation_id", "")))
                or value.get("kind") not in {"BACKUP", "RESTORE", "MIGRATION"}
                or not isinstance(value.get("state"), str)):
            fail("RECOVERY_JOURNAL_INVALID", "The maintenance journal identity is invalid. Keep the workbench stopped and review its private recovery evidence; no filesystem cleanup was attempted.")
        return value

    def authority(self):
        journal = self.journal()
        expected = journal.get("authority", {})
        if journal["state"] in {"RESTORE_COMPLETE", "MIGRATION_COMPLETE", "RECOVERY_COMPLETE"}:
            expected = journal.get("new_authority", expected)
        elif journal["state"] in {"RESTORE_FAILED", "MIGRATION_FAILED"}:
            expected = journal.get("old_authority", expected)
        value = read_json(self.authority_path) if self.authority_path.exists() else expected
        if expected and digest(value) != digest(expected):
            fail("RECOVERY_AUTHORITY_INVALID", "Recovery authority does not match its durable receipt. Keep TWOS in Maintenance and review the recovery evidence.")
        if value and (not re.fullmatch(r"[0-9a-f]{32}", str(value.get("epoch", ""))) or value.get("workspace_status") not in {"REAUTHORIZATION_REQUIRED", "AUTHORIZED"}):
            fail("RECOVERY_AUTHORITY_INVALID", "Recovery authority is incomplete. Do not resume execution.")
        if value.get("archive") is not None and not re.fullmatch(r"[0-9a-f]{32}", str(value["archive"])):
            fail("RECOVERY_AUTHORITY_INVALID", "The recovered material archive identity is invalid.")
        cutoffs = value.get("historical_cutoffs", {})
        if not isinstance(cutoffs, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in cutoffs.items()):
            fail("RECOVERY_AUTHORITY_INVALID", "Historical recovery cutoffs are invalid. Do not resume execution.")
        return value

    def machine_context(self):
        directory = safe_path(self.db.parent, directory=True)
        metadata = directory.stat()
        return digest({"data_directory": str(directory), "device": metadata.st_dev, "inode": metadata.st_ino})

    def bind_recovered_workspace(self):
        """Rebuild machine-local authorization from a verified Owner receipt.

        A new Settings instance may still contain the pre-recovery operator
        path. Never let that override the Owner's persisted reauthorization.
        """
        authority = self.authority()
        if authority.get("workspace_status") != "AUTHORIZED" or self.journal()["state"] not in TERMINAL_OPERATIONS:
            return
        from .first_run import FirstRunError, validate_authorized_workspace
        binding = authority.get("workspace_binding", {})
        valid = False
        try:
            resolved, metadata, identity = validate_authorized_workspace(authority.get("workspace", ""), settings=self.settings, create_if_missing=False)
            valid = binding == {"path": str(resolved), "device": metadata.st_dev, "inode": metadata.st_ino,
                "identity": identity, "machine_context": self.machine_context()}
        except (FirstRunError, MaintenanceError, OSError, ValueError):
            valid = False
        if valid:
            object.__setattr__(self.settings, "source_repo", resolved)
            return
        with self.exclusive():
            authority.update(workspace_status="REAUTHORIZATION_REQUIRED",
                next_action="The workspace or local installation identity changed. Reauthorize the exact current workspace before continuing.")
            atomic_json(self.authority_path, authority)
            self.record(self.journal()["state"], authority=authority, new_authority=authority,
                workspace_revalidation="REAUTHORIZATION_REQUIRED", next_action=authority["next_action"])

    def record(self, state, **fields):
        previous = self.journal()
        value = {**previous, **fields, "state": state, "updated_at": now()}
        atomic_json(self.journal_path, value)
        if state in TERMINAL_OPERATIONS:
            receipt_root = private_directory(self.root / "receipts")
            atomic_json(receipt_root / (value["operation_id"] + ".json"), value)
        return value

    def begin(self, kind):
        old = self.journal()
        if old["state"] not in TERMINAL_OPERATIONS | {"NONE"}:
            fail("RECOVERY_REQUIRED", "Resolve the recorded maintenance operation before starting another.")
        value = {"operation_id": uuid.uuid4().hex, "kind": kind, "state": kind + "_STARTED", "started_at": now(), "authority": self.authority()}
        atomic_json(self.journal_path, value)
        return value

    def status(self):
        try:
            info = inspect_database(self.db)
        except MaintenanceError:
            journal = self.journal()
            if journal.get("compatibility") != "existing engine compatibility":
                raise
            with readonly(self.db) as connection:
                names = tables(connection)
                counts = {name: connection.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
                    for name in ("users", "tasks", "codex_runs") if name in names}
            prior = self.root / "prior.sqlite3"
            verified = prior.exists() and file_hash(prior) == journal.get("prior_hash")
            unchanged = logical_digest(self.db) == journal.get("original_identity")
            preserved = str(prior) if verified else str(self.db) if unchanged else "No verified recovery state"
            action = ("Keep the workbench stopped. Use the prior compatible runtime/operator recovery with the verified prior.sqlite3 shown in Advanced."
                if verified else "The active older database is unchanged. Keep the workbench stopped and use its prior compatible runtime; no completed snapshot exists."
                if unchanged else "Keep the workbench stopped. Supply a verified recovery point through operator recovery.")
            return {"app_version": __version__, "schema": journal.get("from_schema"), "target_schema": TARGET_SCHEMA,
                "backup_ready": False, "recovery_only": True, "blocker": action,
                "recovery": journal, "recovery_point_verified": verified, "active_unchanged": unchanged, "recovery_point": preserved,
                "database": str(self.db), "counts": counts, "authority": self.authority(),
                "next_action": action,
                "sensitive_content_warning": "The recovery point contains sensitive TWOS data.", "provider_request_performed": False}

        with readonly(self.db) as connection:
            workspace_row = connection.execute("SELECT canonical_path FROM authorized_workspaces LIMIT 1").fetchone() if "authorized_workspaces" in tables(connection) else None
        workspace_candidate = workspace_row[0] if workspace_row else str(self.settings.source_repo)
        blocker = None
        try:
            safe_state(self.db)
        except MaintenanceError as exc:
            blocker = exc.message
        authority = self.authority()
        journal = self.journal()
        unresolved = journal["state"] not in TERMINAL_OPERATIONS | {"NONE"}
        if unresolved:
            blocker = "Recovery is required. Restart into Maintenance to reconcile the journal."
        legacy = info["schema"] != TARGET_SCHEMA
        next_action = (blocker or ("Review Migration Plan." if legacy else
            "Reauthorize the current workspace." if authority.get("workspace_status") == "REAUTHORIZATION_REQUIRED" else "Create Backup."))
        return {"app_version": __version__, "schema": info["schema"], "target_schema": TARGET_SCHEMA,
            "installation_id": self.logical_installation_id(info),
            "backup_ready": not blocker and not legacy, "blocker": blocker,
            "backup_directory": str(self.backups), "format": FORMAT, "counts": info["counts"],
            "recovery": journal, "authority": authority, "next_action": next_action,
            "sensitive_content_warning": "Backups contain sensitive TWOS account and task content, including stored delivery evidence. Keep this private local directory secure.",
            "database": str(self.db), "workspace_candidate": workspace_candidate, "provider_request_performed": False}

    def _archive_results(self, target):
        """Copy exact attributed postimages only; never recursively copy a workspace."""
        archived = []
        with readonly(self.db) as connection:
            if "codex_result_artifacts" not in tables(connection):
                return archived
            rows = connection.execute("SELECT a.*, e.run_id, r.worktree_path, r.source_snapshot_digest, r.worktree_branch, (SELECT c.run_workspace_identity FROM delivery_candidates c WHERE c.result_envelope_id=e.id LIMIT 1) AS bound_workspace FROM codex_result_artifacts a JOIN codex_result_envelopes e ON e.id=a.result_envelope_id JOIN codex_runs r ON r.id=e.run_id ORDER BY a.id").fetchall()
            for row in rows:
                if row["operation"] not in ("CREATE", "MODIFY") or not row["after_hash"]:
                    continue
                relative = Path(row["repository_path"])
                if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
                    fail("RESULT_PATH_UNSAFE", "A Result artifact has an unsafe path. Review its evidence before backup.")
                material = None
                archive = self.authority().get("archive")
                if archive:
                    archive_root = safe_path(self.root / "archives" / archive, directory=True)
                    entry = archive_root / (str(row["id"]) + ".bin")
                    if entry.exists():
                        material = safe_path(entry).read_bytes()
                journal = connection.execute("SELECT e.after_material FROM apply_session_entries e JOIN apply_sessions s ON s.id=e.apply_session_id WHERE s.run_id=? AND e.repository_path=? AND e.after_hash=? LIMIT 1", (row["run_id"], str(relative), row["after_hash"])).fetchone()
                if journal and journal[0] is not None:
                    material = bytes(journal[0])
                elif material is None:
                    root = safe_path(row["worktree_path"], directory=True)
                    allowed = self.settings.worktree_root.resolve(strict=False)
                    if not root.is_relative_to(allowed):
                        fail("RESULT_PATH_UNSAFE", "Result material is outside TWOS-owned Run storage.")
                    metadata = root.stat()
                    observed = digest({"device": metadata.st_dev, "inode": metadata.st_ino,
                        "resolved_location": str(root), "source_snapshot_identity": row["source_snapshot_digest"],
                        "worktree_branch": row["worktree_branch"]})
                    if observed != row["bound_workspace"]:
                        fail("RESULT_WORKSPACE_CHANGED", "The Run workspace identity differs from the immutable Candidate. No substituted workspace was copied.")
                    candidate = safe_path(root / relative)
                    if not candidate.is_relative_to(root):
                        fail("RESULT_PATH_UNSAFE", "Result material escapes its Run storage.")
                    material = candidate.read_bytes()
                if hashlib.sha256(material).hexdigest() != row["after_hash"] or len(material) != row["after_size"]:
                    fail("RESULT_MATERIAL_CHANGED", f"Result artifact #{row['id']} no longer matches its captured evidence. Resolve it before backup.")
                reject_secret_value(material, "Result artifact #" + str(row["id"]))
                folder = private_directory(target / "result-material")
                dest = folder / (str(row["id"]) + ".bin")
                dest.write_bytes(material)
                dest.chmod(0o600)
                with dest.open("rb") as stream:
                    os.fsync(stream.fileno())
                fsync_directory(folder)
                archived.append({"artifact_id": row["id"], "run_id": row["run_id"], "repository_path": str(relative), "file": str(dest.relative_to(target)), "sha256": row["after_hash"]})
        return archived

    def create_backup(self):
        with self.exclusive():
            inspect_database(self.db, allow_legacy=False)
            safe_state(self.db)
            operation = self.begin("BACKUP")
            partial = self.backups / (operation["operation_id"] + ".partial")
            final = self.backups / (operation["operation_id"] + ".twos-backup")
            self.record("BACKUP_STARTED", partial=str(partial), destination=str(final))
            try:
                private_directory(partial)
                self.fault("backup_before_snapshot")
                snapshot(self.db, partial / "database.sqlite3", remove_sessions=True)
                reject_external_secrets(partial / "database.sqlite3")
                self.fault("backup_during_copy")
                artifacts = self._archive_results(partial)
                info = inspect_database(partial / "database.sqlite3", allow_legacy=False)
                installation = info["installation"] or {}
                metadata = {"installation_id": self.logical_installation_id(info, create=True),
                    "first_run_state": installation.get("first_run_state"), "owner_id": installation.get("owner_user_id"),
                    "tool_configuration": "preserved as evidence; explicit readiness required after restore",
                    "workspace": "authorization evidence only; source contents excluded",
                    "result_material": artifacts, "authority": self.authority()}
                atomic_json(partial / "logical-installation.json", metadata)
                files = {str(p.relative_to(partial)): {"sha256": file_hash(p), "size": p.stat().st_size}
                    for p in sorted(partial.rglob("*")) if p.is_file()}
                manifest = {"format": FORMAT, "application_version": __version__, "schema_version": info["schema"],
                    "created_at": now(), "source_installation_id": metadata["installation_id"],
                    "components": ["database", "accounts_without_sessions", "tasks_packs_runs_results_verification", "delivery_receipts_and_audit", "application_configuration", "inert_result_material"],
                    "files": files, "completion": "SEALED"}
                self.fault("backup_before_seal")
                manifest["integrity"] = digest(manifest)
                atomic_json(partial / "manifest.json", manifest)
                self.inspect_backup(str(partial), allow_partial=True)
                self.fault("backup_before_rename")
                os.replace(partial, final)
                fsync_directory(self.backups)
                return self.record("BACKUP_COMPLETE", backup=str(final), format=FORMAT, integrity_status="VERIFIED", integrity=manifest["integrity"], next_action="Inspect this backup before restoring it.")
            except Exception as exc:
                if partial.exists():
                    shutil.rmtree(partial)
                self.record("BACKUP_FAILED", error_code=getattr(exc, "code", "BACKUP_FAILED"), next_action="The active installation is unchanged. Resolve the failure and explicitly create a new backup.")
                raise

    def inspect_backup(self, value, *, allow_partial=False):
        bundle = safe_path(value, directory=True)
        if (bundle.name.endswith(".partial") and not allow_partial) or not bundle.name.endswith((".twos-backup", ".partial")):
            fail("INCOMPLETE_BACKUP", "Select a completed .twos-backup directory.", 400)
        manifest = read_json(bundle / "manifest.json")
        if manifest.get("format") != FORMAT:
            fail("BACKUP_FORMAT_UNSUPPORTED", "This backup format is unsupported. Use the TWOS version that created it.", 400)
        if manifest.get("completion") != "SEALED" or manifest.get("integrity") != digest({k: v for k, v in manifest.items() if k != "integrity"}):
            fail("MANIFEST_INTEGRITY_FAILED", "The backup is incomplete or its manifest integrity failed.", 400)
        if manifest.get("application_version") != __version__ or manifest.get("schema_version") != TARGET_SCHEMA:
            fail("BACKUP_INCOMPATIBLE", "Backup application/schema compatibility failed. Migrate a supported old installation before creating its backup.", 400)
        files = manifest.get("files")
        if not isinstance(files, dict) or not {"database.sqlite3", "logical-installation.json"} <= files.keys():
            fail("BACKUP_DATABASE_MISSING", "The backup is missing its database or logical installation metadata.", 400)
        actual = set()
        for path in bundle.rglob("*"):
            if path.is_symlink():
                fail("UNSAFE_PATH", "A backup contains a symbolic link.", 400)
            if path.is_file():
                actual.add(str(path.relative_to(bundle)))
            elif not path.is_dir():
                fail("UNSAFE_PATH", "A backup contains an unsupported filesystem entry.", 400)
        if actual != set(files) | {"manifest.json"}:
            fail("BACKUP_CONTENT_MISMATCH", "Backup files do not match the sealed manifest.", 400)
        for name, expected in files.items():
            if name not in {"database.sqlite3", "logical-installation.json"} and not re.fullmatch(r"result-material/[0-9]+\.bin", name):
                fail("UNSAFE_PATH", "The manifest contains an unsupported component path.", 400)
            path = safe_path(bundle / name)
            if not isinstance(expected, dict) or path.stat().st_size != expected.get("size") or file_hash(path) != expected.get("sha256"):
                fail("BACKUP_HASH_MISMATCH", "A required backup file failed hash verification. The active installation is unchanged.", 400)
        info = inspect_database(bundle / "database.sqlite3", allow_legacy=False)
        safe_state(bundle / "database.sqlite3")
        reject_external_secrets(bundle / "database.sqlite3")
        metadata = read_json(bundle / "logical-installation.json")
        installation_id = (info["installation"] or {}).get("public_id") or metadata.get("installation_id")
        if not installation_id or (not info["installation"] and not re.fullmatch(r"legacy-[0-9a-f]{32}", str(installation_id))):
            fail("INSTALLATION_MISMATCH", "Backup lacks a persisted logical installation identity.", 400)
        if manifest.get("source_installation_id") != installation_id or metadata.get("installation_id") != installation_id:
            fail("INSTALLATION_MISMATCH", "Backup logical installation identity does not match its database.", 400)
        expected_material = []
        with readonly(bundle / "database.sqlite3") as connection:
            if connection.execute("SELECT COUNT(*) FROM session_tokens").fetchone()[0]:
                fail("BACKUP_CREDENTIAL_BLOCKED", "Backup must not contain login sessions.", 400)
            if connection.execute("SELECT COUNT(*) FROM installations WHERE setup_token_hash IS NOT NULL").fetchone()[0]:
                fail("BACKUP_CREDENTIAL_BLOCKED", "Backup must not contain setup credentials.", 400)
            rows = connection.execute("SELECT a.*, e.run_id FROM codex_result_artifacts a JOIN codex_result_envelopes e ON e.id=a.result_envelope_id ORDER BY a.id").fetchall()
            for row in rows:
                if row["operation"] not in ("CREATE", "MODIFY") or not row["after_hash"]:
                    continue
                name = "result-material/" + str(row["id"]) + ".bin"
                if files.get(name) != {"sha256": row["after_hash"], "size": row["after_size"]}:
                    fail("RESULT_MATERIAL_MISSING", "Backup lacks exact Result material required by its database evidence.", 400)
                reject_secret_value(safe_path(bundle / name).read_bytes(), "Result material")
                expected_material.append({"artifact_id": row["id"], "run_id": row["run_id"], "repository_path": row["repository_path"], "file": name, "sha256": row["after_hash"]})
        if metadata.get("result_material") != expected_material or {n for n in files if n.startswith("result-material/")} != {m["file"] for m in expected_material}:
            fail("RESULT_MATERIAL_MISMATCH", "Backup Result material does not match its captured lineage.", 400)
        return {"backup": str(bundle), "manifest": manifest, "counts": info["counts"], "integrity_status": "VERIFIED"}

    def _stage_backup(self, inspected, destination):
        """Copy only approved bytes into private storage, then verify the copy.

        A mutable external bundle cannot supply different bytes between Owner
        review and activation. Every copied byte is checked against the approved
        manifest before the source database is ever used by SQLite.
        """
        private_directory(destination)
        source = Path(inspected["backup"])
        for name, expected in inspected["manifest"]["files"].items():
            target = destination / name
            if target.parent != destination:
                private_directory(target.parent)
            shutil.copyfile(safe_path(source / name), target)
            target.chmod(0o600)
            with target.open("rb") as stream:
                os.fsync(stream.fileno())
            fsync_directory(target.parent)
            if target.stat().st_size != expected["size"] or file_hash(target) != expected["sha256"]:
                fail("BACKUP_CHANGED", "Backup content changed after review. The active installation is unchanged; inspect a new complete backup.")
        atomic_json(destination / "manifest.json", inspected["manifest"])
        self.inspect_backup(str(destination), allow_partial=True)
        fsync_directory(destination)


    def restore_plan(self, value, owner_id):
        inspected = self.inspect_backup(value)
        safe_state(self.db)
        source = inspect_database(Path(inspected["backup"]) / "database.sqlite3", allow_legacy=False)
        current = inspect_database(self.db, allow_legacy=False)
        source_id = inspected["manifest"]["source_installation_id"]
        current_id = self.logical_installation_id(current)
        if source_id != current_id:
            fail("INSTALLATION_MISMATCH", "Restore must target the same logical installation identity. No current installation was replaced.")
        if not source["owners"] or not current["owners"] or source["owners"][0]["username"] != current["owners"][0]["username"]:
            fail("OWNER_MISMATCH", "The backup belongs to a different installation Owner.", 403)
        self.prepare()
        plan = {"plan_id": uuid.uuid4().hex, "kind": "RESTORE", "owner_id": owner_id,
            "backup": inspected["backup"], "backup_integrity": inspected["manifest"]["integrity"],
            "active_identity": logical_digest(self.db), "from_schema": current["schema"], "to_schema": TARGET_SCHEMA,
            "counts": inspected["counts"], "recovery_point": str(self.root / "prior.sqlite3"),
            "consequences": "Replace TWOS logical data with this backup. Changes after the backup disappear. Source workspace files are not restored. Log in again and reauthorize the workspace; tool readiness and new Packs require explicit action.",
            "confirmation": "RESTORE_TWOS", "created_at": now()}
        plan["digest"] = digest(plan)
        atomic_json(self.root / "plan.json", plan)
        return plan

    def migration_plan(self, owner_id):
        info = inspect_database(self.db)
        if info["schema"] == TARGET_SCHEMA:
            fail("MIGRATION_NOT_REQUIRED", "This installation already uses the current schema. No migration ran.")
        safe_state(self.db)
        self.prepare()
        plan = {"plan_id": uuid.uuid4().hex, "kind": "MIGRATION", "owner_id": owner_id,
            "active_identity": logical_digest(self.db), "from_schema": info["schema"], "to_schema": TARGET_SCHEMA,
            "recovery_point": str(self.root / "prior.sqlite3"), "counts": info["counts"],
            "consequences": "Migrate a staged copy with the existing TWOS engine. Preserve historical evidence and legacy ownership defaults. Activate only after verification; keep the prior database for recovery.",
            "confirmation": "MIGRATE_TWOS", "created_at": now()}
        plan["digest"] = digest(plan)
        atomic_json(self.root / "plan.json", plan)
        return plan

    def execute_plan(self, plan_id, owner_id, confirmation):
        with self.exclusive():
            plan = read_json(self.root / "plan.json")
            if plan.get("plan_id") != plan_id or plan.get("owner_id") != owner_id or plan.get("confirmation") != confirmation:
                fail("CONFIRMATION_REQUIRED", "Review and explicitly confirm this exact Owner-bound maintenance plan.", 403)
            if plan.get("digest") != digest({k: v for k, v in plan.items() if k != "digest"}):
                fail("PLAN_CHANGED", "The maintenance plan changed. Review a new plan.")
            approval_path = self.root / "approval.json"
            approval = read_json(approval_path) if approval_path.exists() else {}
            if approval.get("plan_id") != plan_id or approval.get("owner_id") != owner_id or approval.get("plan_digest") != plan["digest"]:
                fail("PLAN_APPROVAL_REQUIRED", "Approve this exact maintenance plan before final confirmation.", 403)
            if logical_digest(self.db) != plan["active_identity"]:
                fail("PLAN_STALE", "Installation data changed after review. Review a new maintenance plan.")
            return self._execute_bound_plan(plan)

    def _execute_bound_plan(self, plan, *, seed_default_projects=False, engine_compatibility=False):
        """Caller holds the exclusive lease and has established explicit or
        existing-startup authority. Both paths share one recovery engine.
        """
        safe_state(self.db)
        kind = plan["kind"]
        if kind == "RESTORE":
            inspected = self.inspect_backup(plan["backup"])
            if inspected["manifest"]["integrity"] != plan["backup_integrity"]:
                fail("PLAN_STALE", "The backup changed after review. Inspect it again.")
        self.begin(kind)
        self.record(kind + "_STARTED", original_identity=logical_digest(self.db),
            compatibility=plan.get("compatibility", "accepted 19.1/19.2A"),
            from_schema=plan["from_schema"], to_schema=TARGET_SCHEMA,
            initiator=plan.get("initiator", "OWNER_CONFIRMED"))
        prior = self.root / "prior.sqlite3"
        staged = self.root / "staged.sqlite3"
        old_authority = self.authority()
        restore_source = self.root / (self.journal()["operation_id"] + ".partial")
        try:
            self.fault(kind.lower() + "_before_snapshot")
            snapshot(self.db, prior)
            prior_hash = file_hash(prior)
            self.record(kind + "_STARTED", prior=str(prior), prior_hash=prior_hash,
                staged=str(staged), plan_id=plan["plan_id"], initiator=plan.get("initiator", "OWNER_CONFIRMED"), compatibility=plan.get("compatibility", "accepted 19.1/19.2A"), from_schema=plan["from_schema"], to_schema=TARGET_SCHEMA,
                old_authority=old_authority, next_action="Wait for local verification.")
            self.fault(kind.lower() + "_before_stage")
            if staged.exists():
                staged.unlink()
            if kind == "RESTORE":
                self._stage_backup(inspected, restore_source)
                snapshot(restore_source / "database.sqlite3", staged, remove_sessions=True)
                self._rebind_installation(staged)
            else:
                snapshot(self.db, staged)
                self.fault("migration_step")
                from .db import _initialize_database, make_engine
                staged_engine = make_engine("sqlite:///" + str(staged))
                try:
                    _initialize_database(staged_engine, seed_default_projects=seed_default_projects)
                finally:
                    staged_engine.dispose()
                self.fault("migration_after_step")
            info = inspect_database(staged, allow_legacy=False)
            safe_state(staged)
            if kind == "MIGRATION":
                if not engine_compatibility:
                    verify_preserved_data(prior, staged, allow_seed_rows=seed_default_projects)
            else:
                with closing(sqlite3.connect(staged)) as connection:
                    connection.execute("UPDATE schedules SET paused=1, next_run_at=NULL")
                    connection.commit()
            self.fault(kind.lower() + "_after_staged_verification")
            authority = old_authority if engine_compatibility else self._recovery_authority(staged, old_authority, kind)
            if kind == "RESTORE":
                archive_id = self.journal()["operation_id"]
                private_directory(self.root / "archives")
                archive_root = private_directory(self.root / "archives" / archive_id)
                for name in inspected["manifest"]["files"]:
                    if name.startswith("result-material/"):
                        target = archive_root / Path(name).name
                        target.write_bytes(safe_path(restore_source / name).read_bytes())
                        target.chmod(0o600)
                        with target.open("rb") as stream:
                            os.fsync(stream.fileno())
                fsync_directory(archive_root)
                fsync_directory(archive_root.parent)
                authority["archive"] = archive_id
            self.record(kind + "_STAGED", staged_hash=file_hash(staged), new_authority=authority)
            self.fault(kind.lower() + "_before_activation")
            self.record(kind + "_ACTIVATING")
            # A checkpointed SQLite snapshot replaces one file. No normal
            # DBAPI connection can exist while the exclusive lease is held.
            with closing(sqlite3.connect(self.db)) as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("PRAGMA journal_mode=DELETE")
            activate_database(staged, self.db)
            self.fault(kind.lower() + "_after_activation")
            self.record(kind + "_ACTIVATED")
            self.fault(kind.lower() + "_post_verify")
            inspect_database(self.db, allow_legacy=False)
            if file_hash(self.db) != self.journal()["staged_hash"]:
                fail("ACTIVATION_INTEGRITY_FAILED", "Activated database identity did not match the verified staged state.")
            atomic_json(self.authority_path, authority)
            receipt = self.record(kind + "_COMPLETE", active_healthy=True, recovery_point=str(prior),
                next_action="Log in again, then reauthorize the current workspace." if kind == "RESTORE" else "Restart TWOS and review the migrated data.")
            (self.root / "plan.json").unlink(missing_ok=True)
            if restore_source.exists():
                shutil.rmtree(restore_source)
            return receipt
        except Exception as exc:
            if restore_source.exists():
                shutil.rmtree(restore_source)
            journal = self.journal()
            if journal.get("prior_hash") and prior.exists() and file_hash(prior) == journal["prior_hash"]:
                snapshot(prior, staged)
                activate_database(staged, self.db)
                atomic_json(self.authority_path, old_authority)
                self.record(kind + "_FAILED", active_healthy=True, error_code=getattr(exc, "code", kind + "_FAILED"),
                    next_action="The prior installation is active. Review the failure and explicitly review a new plan; no retry runs automatically.")
            elif journal.get("original_identity") == logical_digest(self.db):
                self.record(kind + "_FAILED", active_healthy=True, old_authority=old_authority,
                    error_code=getattr(exc, "code", kind + "_FAILED"),
                    next_action="The operation failed before activation; the unchanged installation is healthy. Resolve the failure and explicitly review a new plan.")
            else:
                self.record("RECOVERY_REQUIRED", active_healthy=False,
                    next_action="Keep TWOS in Maintenance. Restore a verified recovery point before opening the workbench.")
            raise

    def approve_plan(self, plan_id, owner_id):
        plan = read_json(self.root / "plan.json")
        if plan.get("plan_id") != plan_id or plan.get("owner_id") != owner_id:
            fail("PLAN_APPROVAL_REQUIRED", "Review the plan as its installation Owner.", 403)
        if plan.get("digest") != digest({k: v for k, v in plan.items() if k != "digest"}):
            fail("PLAN_CHANGED", "The plan changed. Review it again.")
        if plan["active_identity"] != logical_digest(self.db):
            fail("PLAN_STALE", "Installation data changed. Review a new plan.")
        approval = {"plan_id": plan_id, "plan_digest": plan["digest"], "owner_id": owner_id, "approved_at": now()}
        atomic_json(self.root / "approval.json", approval)
        return approval

    def _rebind_installation(self, staged):
        current = inspect_database(self.db)["installation"]
        if not current:
            return
        fields = ("data_root", "database_path", "runtime_environment", "log_directory", "bind_host", "bind_port", "source_version")
        with closing(sqlite3.connect(staged)) as connection:
            connection.execute("UPDATE installations SET " + ",".join(name + "=?" for name in fields), [current[name] for name in fields])
            connection.commit()

    def _recovery_authority(self, db, previous, kind):
        with readonly(db) as connection:
            cutoffs = {name: connection.execute('SELECT COALESCE(MAX(id),0) FROM "' + name + '"').fetchone()[0]
                for name in ("codex_runs", "codex_instruction_packs", "guided_tool_configurations", "apply_plans",
                    "apply_sessions", "post_apply_verifications", "commit_proposals", "commit_plans",
                    "stage_executions", "local_commit_executions", "push_plans", "push_executions",
                    "owner_acceptance_sessions", "handoff_instruction_drafts") if name in tables(connection)}
        return {**previous, "epoch": uuid.uuid4().hex, "workspace_status": "REAUTHORIZATION_REQUIRED",
            "historical_cutoffs": cutoffs, "reason": kind,
            "next_action": "Reauthorize the current workspace. Historical delivery remains read-only; prepare a new Pack for future work."}

    def reconcile(self):
        if not self.journal_path.exists():
            return
        with self.exclusive():
            journal = self.journal()
            state = journal["state"]
            if state in TERMINAL_OPERATIONS | {"NONE"}:
                return
            if journal.get("kind") == "BACKUP":
                partial = self.backups / (journal["operation_id"] + ".partial")
                if partial.exists():
                    safe_path(partial, directory=True)
                    shutil.rmtree(partial)
                final = self.backups / (journal["operation_id"] + ".twos-backup")
                if final.exists():
                    self.inspect_backup(str(final))
                    self.record("BACKUP_COMPLETE", backup=str(final), format=FORMAT, integrity_status="VERIFIED", active_healthy=True, next_action="Inspect the completed backup.")
                else:
                    self.record("BACKUP_FAILED", active_healthy=True, next_action="Incomplete backup removed. The installation is unchanged; explicitly create a new backup.")
                return
            prior = self.root / "prior.sqlite3"
            staged = self.root / "staged.sqlite3"
            restore_source = self.root / (journal["operation_id"] + ".partial")
            if restore_source.exists():
                safe_path(restore_source, directory=True)
                shutil.rmtree(restore_source)
            if not journal.get("prior_hash") or not prior.exists() or file_hash(prior) != journal["prior_hash"]:
                if journal.get("original_identity") == logical_digest(self.db) and state.endswith("_STARTED"):
                    self.record(journal["kind"] + "_FAILED", active_healthy=True,
                        next_action="The operation stopped before staging. The unchanged installation is healthy; explicitly review a new plan.")
                    return
                self.record("RECOVERY_REQUIRED", active_healthy=False, next_action="Keep TWOS in Maintenance and supply a verified recovery point.")
                return
            if state.endswith(("_ACTIVATING", "_ACTIVATED")) and self.db.exists() and file_hash(self.db) == journal.get("staged_hash"):
                inspect_database(self.db, allow_legacy=False)
                recovered_authority = journal["new_authority"]
                atomic_json(self.authority_path, recovered_authority)
                outcome = "Verified the activated state; no external operation was replayed."
            else:
                snapshot(prior, staged)
                activate_database(staged, self.db)
                recovered_authority = journal.get("old_authority", {})
                atomic_json(self.authority_path, recovered_authority)
                outcome = "Restored the verified prior database; no migration or external operation was retried."
            staged.unlink(missing_ok=True)
            self.record("RECOVERY_COMPLETE", active_healthy=True, outcome=outcome, new_authority=recovered_authority,
                next_action="Log in to Maintenance and review the recovery receipt before continuing.")


def logical_digest(db):
    # Session churn is not a logical change and cannot stale a reviewed plan.
    # All other tables, including approvals and audit, remain in the binding.
    with readonly(db) as connection:
        rows = {}
        for name in sorted(tables(connection) - {"session_tokens", "sqlite_sequence"}):
            values = []
            for row in connection.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid'):
                values.append([{"blob_sha256": hashlib.sha256(v).hexdigest()} if isinstance(v, bytes) else v for v in row])
            rows[name] = values
    return digest(rows)


def verify_preserved_data(before, after, *, allow_seed_rows=False):
    with readonly(before) as old, readonly(after) as new:
        for name in tables(old) - {"sqlite_sequence", "schema_versions"}:
            columns = [row[1] for row in old.execute('PRAGMA table_info("' + name + '")')]
            selection = ','.join('"' + c + '"' for c in columns)
            original = [tuple(row) for row in old.execute(f'SELECT {selection} FROM "{name}" ORDER BY rowid')]
            migrated = [tuple(row) for row in new.execute(f'SELECT {selection} FROM "{name}" ORDER BY rowid')]
            if (any(row not in migrated for row in original) if allow_seed_rows else original != migrated):
                fail("MIGRATION_DATA_CHANGED", f"Migration changed existing {name} data. The prior installation is preserved.")


def recovery_epoch(settings):
    try:
        return Maintenance(settings).authority().get("epoch", "") if settings else ""
    except MaintenanceError as exc:
        if exc.code == "DATABASE_UNSUPPORTED":
            return ""
        raise


def protect_startup_migration(engine, *, seed_default_projects=True):
    """Protect every structural advance supported by the existing engine.

    Fresh Install still rejects old databases before this wrapper. The public
    migration matrix remains .003/.004. Earlier and partial database shapes
    retain their accepted low-level compatibility engine, behind the same
    recovery point and atomic activation contract. No Owner approval is claimed
    for the pre-existing automatic startup behavior.
    """
    from .config import Settings
    from .models import Base
    from .first_run import _CANONICAL_FRESH_SCHEMA_VERSIONS
    try:
        db = database_path(str(engine.url))
    except MaintenanceError as exc:
        if exc.code == "DATABASE_UNSUPPORTED":
            return False
        raise
    if not db.exists() or db.stat().st_size == 0:
        return False
    service = Maintenance(Settings(database_url=str(engine.url), source_repo=db.parent))
    pending = service.journal()
    if pending["state"] not in TERMINAL_OPERATIONS | {"NONE"}:
        engine.dispose()
        service.reconcile()
    if service.journal()["state"] in {"MIGRATION_FAILED", "RECOVERY_REQUIRED"}:
        fail("MIGRATION_CONFIRMATION_REQUIRED", "A previous migration was interrupted or failed. Keep the workbench stopped; review Maintenance recovery evidence or use the prior compatible runtime for unsupported engine-era data.")
    try:
        with readonly(db) as connection:
            names = tables(connection)
            if not names:
                return False
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                fail("DATABASE_CORRUPT", "The existing database failed integrity verification.")
            versions = {row[0] for row in connection.execute("SELECT version FROM schema_versions")} if "schema_versions" in names else set()
            if versions - _CANONICAL_FRESH_SCHEMA_VERSIONS:
                fail("SCHEMA_UNSUPPORTED", "Unknown or future schema history cannot be opened by this TWOS version.")
            current = versions == _CANONICAL_FRESH_SCHEMA_VERSIONS
            for name, table in Base.metadata.tables.items():
                columns = {row[1]: row for row in connection.execute('PRAGMA table_info("'+name+'")')}
                if name not in names or not {c.name for c in table.columns} <= columns.keys():
                    current = False
            if "delivery_candidates" in names:
                columns = {row[1]: row for row in connection.execute('PRAGMA table_info("delivery_candidates")')}
                for name in ("coding_assignment_id", "verification_assignment_id", "coding_evidence_id", "verification_evidence_id"):
                    if name in columns and columns[name][3]:
                        current = False
            if current:
                return False
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                fail("DATABASE_CORRUPT", "The existing database failed relationship verification.")
    except sqlite3.Error:
        fail("DATABASE_CORRUPT", "The existing database cannot be safely initialized.")
    engine.dispose()
    service = Maintenance(Settings(database_url=str(engine.url), source_repo=db.parent))
    service.reconcile()
    if service.journal()["state"] in {"MIGRATION_FAILED", "RECOVERY_REQUIRED", "RECOVERY_COMPLETE"}:
        fail("MIGRATION_CONFIRMATION_REQUIRED", "A previous migration was interrupted or failed. Open Maintenance and explicitly review a new migration plan.")
    strict = bool(set(SUPPORTED_SCHEMAS[:2]) & versions) and TARGET_SCHEMA not in versions
    if strict:
        info = inspect_database(db)
        from_schema = info["schema"]
    else:
        from_schema = ", ".join(sorted(versions)) or "unversioned existing engine database"
    with service.exclusive():
        safe_state(db)
        plan = {"plan_id": uuid.uuid4().hex, "kind": "MIGRATION", "from_schema": from_schema,
            "to_schema": TARGET_SCHEMA, "initiator": "EXISTING_STARTUP_ENGINE",
            "compatibility": "accepted 19.1/19.2A" if strict else "existing engine compatibility",
            "active_identity": logical_digest(db), "created_at": now()}
        return bool(service._execute_bound_plan(plan, seed_default_projects=seed_default_projects,
            engine_compatibility=not strict))
