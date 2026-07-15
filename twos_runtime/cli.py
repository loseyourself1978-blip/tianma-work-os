from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings
from .db import initialize_database, make_engine, make_session_factory
from .models import AuditEvent, User
from .security import create_owner, normalize_username, owner_record_issue, recover_owner_credentials


def cmd_init_db() -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    initialize_database(engine)
    print(f"TWOS database initialized: {settings.database_url}")
    return 0


def cmd_init_owner(username: str) -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    initialize_database(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        existing = session.scalar(select(User).order_by(User.id))
        if existing is not None:
            message = (
                "Owner recovery is required."
                if owner_record_issue(existing) is not None
                else "Owner account already exists."
            )
            print(message, file=sys.stderr)
            return 1
        password = getpass.getpass("Owner password: ")
        confirm = getpass.getpass("Confirm owner password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            owner = create_owner(session, username, password)
            session.commit()
        except ValueError as exc:
            session.rollback()
            print(str(exc), file=sys.stderr)
            return 1
        except SQLAlchemyError:
            session.rollback()
            print("Owner account could not be initialized.", file=sys.stderr)
            return 1
    print(f"Owner account initialized for {owner.username}.")
    return 0


def cmd_recover_owner(confirm_local_recovery: bool) -> int:
    if not confirm_local_recovery:
        print(
            "Owner recovery is disabled. Re-run with --confirm-local-recovery after reviewing the local database.",
            file=sys.stderr,
        )
        return 2
    settings = get_settings()
    engine = make_engine(settings.database_url)
    initialize_database(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        users = session.scalars(select(User).order_by(User.id).limit(2)).all()
        recovered_before = session.scalar(
            select(AuditEvent.id).where(AuditEvent.action == "owner_recovered").limit(1)
        )
        if len(users) != 1 or recovered_before is not None:
            print("Owner recovery is unavailable.", file=sys.stderr)
            return 1
        recovery_username = None
        if (
            not isinstance(users[0].username, str)
            or not normalize_username(users[0].username)
            or len(normalize_username(users[0].username)) > 80
        ):
            recovery_username = input("Owner username: ")
        password = getpass.getpass("New Owner password: ")
        confirm = getpass.getpass("Confirm new Owner password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            owner = recover_owner_credentials(
                session,
                password,
                recovery_username,
                allow_valid_record=True,
            )
            session.add(
                AuditEvent(
                    actor_user_id=None,
                    action="owner_recovered",
                    entity_type="user",
                    entity_id=owner.id,
                    request_id=None,
                    details="Explicit local Owner credential recovery completed.",
                )
            )
            session.commit()
        except (ValueError, SQLAlchemyError):
            session.rollback()
            print("Owner recovery could not be completed.", file=sys.stderr)
            return 1
    print("Owner credentials recovered. Recovery is now unavailable for this valid Owner.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m twos_runtime.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    owner = sub.add_parser("init-owner")
    owner.add_argument("--username", required=True)
    recovery = sub.add_parser("recover-owner")
    recovery.add_argument("--confirm-local-recovery", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "init-db":
        return cmd_init_db()
    if args.command == "init-owner":
        return cmd_init_owner(args.username)
    if args.command == "recover-owner":
        return cmd_recover_owner(args.confirm_local_recovery)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
