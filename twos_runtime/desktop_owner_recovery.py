"""One-shot local maintenance over inherited pipes, never an HTTP reset API.

The native launcher requires fresh macOS user presence and personal confirmation.
As with the existing recover-owner CLI, the trust boundary is the local OS user
who already owns the database. No caller-supplied database path or Python runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import select
import sys
import time

from sqlalchemy import create_engine, select as sql_select, text
from sqlalchemy.orm import Session

from scripts import twos_bootstrap as bootstrap
from .desktop import directories, event
from .maintenance import (MaintenanceError, atomic_json, file_hash, inspect_database,
                          open_lock, private_directory, read_json, readonly,
                          safe_path, safe_state, snapshot)
from .models import AuditEvent, User
from .security import normalize_username, recover_owner_credentials


def fail(code):
    raise MaintenanceError(code, "Local account recovery did not complete.")


def read_request(fd, seconds=300):
    """Bound the entire frame, including a stalled partial line, without a worker."""
    deadline = time.monotonic() + seconds
    data = bytearray()
    while len(data) <= 8192:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            fail("RECOVERY_TIMEOUT")
        chunk = os.read(fd, 1)
        if not chunk:
            fail("RECOVERY_CANCELLED")
        if chunk == b"\n":
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                fail("RECOVERY_REQUEST_INVALID")
            if not isinstance(value, dict):
                fail("RECOVERY_REQUEST_INVALID")
            return value
        data.extend(chunk)
    fail("RECOVERY_REQUEST_INVALID")


def owner_binding(db):
    info = inspect_database(db, allow_legacy=False)
    installation_owner = (info.get('installation') or {}).get('owner_user_id')
    with readonly(db) as connection:
        verified = {r[0] for r in connection.execute('SELECT user_id FROM wb_email_identities')}
    owners = [u for u in info['owners'] if u['id'] == installation_owner or u['id'] not in verified or not u['username'].startswith('email_user_')]
    if len(owners) != 1:
        fail("RECOVERY_OWNER_UNAVAILABLE")
    owner = owners[0]
    if (not isinstance(owner["username"], str) or not normalize_username(owner["username"])
            or normalize_username(owner["username"]) != owner["username"]
            or len(owner["username"]) > 80 or not owner["is_active"]):
        fail("RECOVERY_OWNER_UNAVAILABLE")
    with readonly(db) as connection:
        if connection.execute("SELECT 1 FROM audit_events WHERE action='owner_recovered' LIMIT 1").fetchone():
            fail("RECOVERY_ALREADY_USED")
    return owner, hashlib.sha256(json.dumps(owner, sort_keys=True).encode()).hexdigest()


def recover(data: Path, request_fd: int, emit=event, *, seconds=300):
    # Never create a fresh installation or migrate an old database in recovery.
    safe_path(data, directory=True)
    if data.stat().st_uid != os.geteuid() or data.stat().st_mode & 0o077:
        fail("RECOVERY_STORAGE_UNSAFE")
    db = safe_path(data / "twos.sqlite3")
    for suffix in ("-wal", "-shm", "-journal"):
        sibling = db.with_name(db.name + suffix)
        safe_path(sibling, exists=sibling.exists())
    if db.stat().st_uid != os.geteuid() or db.stat().st_mode & 0o077:
        fail("RECOVERY_STORAGE_UNSAFE")
    installation = read_json(data / "installation.json")
    identity = installation.get("installation_id", "")
    if (not bootstrap.INSTALLATION_ID_RE.fullmatch(identity)
            or installation.get("database_path") != str(db)
            or installation.get("data_root") != str(data)):
        fail("RECOVERY_INSTALLATION_MISMATCH")
    startup_fd = bootstrap.acquire_startup_lock(data / "startup.lock")
    lease = None
    engine = None
    try:
        lease = open_lock(db, exclusive=True)
        safe_state(db)
        owner, binding = owner_binding(db)
        nonce = secrets.token_hex(32)
        emit("recovery_preview", nonce=nonce, installation_id=identity,
             owner_id=owner["id"], username=owner["username"])
        request = read_request(request_fd, seconds)
        if set(request) != {"nonce", "installation_id", "owner_id", "confirmation", "password", "password_confirmation"}:
            fail("RECOVERY_REQUEST_INVALID")
        if (not secrets.compare_digest(str(request["nonce"]), nonce)
                or request["installation_id"] != identity or type(request["owner_id"]) is not int
                or request["owner_id"] != owner["id"]
                or request["confirmation"] != "RESET_EXISTING_OWNER_PASSWORD"):
            fail("RECOVERY_CONFIRMATION_INVALID")
        password = request["password"]
        if not isinstance(password, str) or not 8 <= len(password) <= 200 or password != request["password_confirmation"]:
            fail("RECOVERY_PASSWORD_INVALID")
        safe_state(db)
        if owner_binding(db)[1] != binding:
            fail("RECOVERY_OWNER_CHANGED")
        # A private SQLite-consistent recovery point is durable before any write.
        backup_root = private_directory(data / "owner-credential-recovery")
        backup = private_directory(backup_root / secrets.token_hex(16))
        snapshot(db, backup / "before.sqlite3")
        atomic_json(backup / "receipt.json", {"state": "SNAPSHOT_ONLY", "installation_id": identity,
                    "owner_id": owner["id"], "snapshot_sha256": file_hash(backup / "before.sqlite3")})
        # Exclusive cross-process maintenance lease is held above. Deliberately
        # avoid make_engine's shared lease and initialize_database/migrations.
        engine = create_engine("sqlite:///" + str(db))
        with Session(engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            current = session.scalar(sql_select(User).where(User.id == owner["id"]))
            if (current is None or any(getattr(current, key) != owner[key] for key in
                    ("id", "username", "is_active", "password_hash", "password_salt"))
                    or session.scalar(sql_select(AuditEvent.id).where(AuditEvent.action == "owner_recovered").limit(1))):
                fail("RECOVERY_OWNER_CHANGED")
            updated = recover_owner_credentials(session, password, allow_valid_record=True)
            session.add(AuditEvent(actor_user_id=None, action="owner_recovered", entity_type="user",
                        entity_id=updated.id, request_id=None,
                        details="Explicit native local Owner credential recovery completed; prior sessions revoked."))
            session.commit()
        # The transaction audit is the authoritative completion receipt; no
        # post-commit disk write may misreport successful recovery as failure.
        emit("recovery_complete", installation_id=identity, owner_id=owner["id"], username=owner["username"])
    finally:
        if engine is not None:
            engine.dispose()
        if lease is not None:
            os.close(lease)
        os.close(startup_fd)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic-root", type=Path)
    parser.add_argument("--environment-id")
    args = parser.parse_args(argv)
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        if os.geteuid() == 0 or sys.stdin.isatty() or sys.stdout.isatty():
            fail("RECOVERY_NATIVE_PIPE_REQUIRED")
        data, _, _, _ = directories(Path.home().resolve(), args.diagnostic_root, args.environment_id)
        recover(data, sys.stdin.fileno())
        return 0
    except Exception as exc:
        allowed = {"ACTIVE_OPERATION", "RESULT_SETTLING", "UNRESOLVED_STAGE", "INSTALLATION_BUSY",
                   "SCHEMA_UNSUPPORTED", "DATABASE_CORRUPT", "UNSAFE_PATH", "PATH_UNAVAILABLE",
                   "RECOVERY_TIMEOUT", "RECOVERY_CANCELLED", "RECOVERY_REQUEST_INVALID",
                   "RECOVERY_OWNER_UNAVAILABLE", "RECOVERY_ALREADY_USED", "RECOVERY_STORAGE_UNSAFE",
                   "RECOVERY_INSTALLATION_MISMATCH", "RECOVERY_CONFIRMATION_INVALID",
                   "RECOVERY_PASSWORD_INVALID", "RECOVERY_OWNER_CHANGED", "RECOVERY_NATIVE_PIPE_REQUIRED"}
        code = ("INSTALLATION_BUSY" if isinstance(exc.__cause__, BlockingIOError)
                else getattr(exc, "code", "RECOVERY_FAILED"))
        event("recovery_error", code=code if code in allowed else "RECOVERY_FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
