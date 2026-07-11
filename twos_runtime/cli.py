from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .db import initialize_database, make_engine, make_session_factory
from .models import User
from .security import create_owner


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
        if session.scalar(select(User)):
            print("Owner account already exists.", file=sys.stderr)
            return 1
        password = getpass.getpass("Owner password: ")
        confirm = getpass.getpass("Confirm owner password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        try:
            create_owner(session, username, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        session.commit()
    print(f"Owner account initialized for {username}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m twos_runtime.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    owner = sub.add_parser("init-owner")
    owner.add_argument("--username", required=True)
    args = parser.parse_args(argv)
    if args.command == "init-db":
        return cmd_init_db()
    if args.command == "init-owner":
        return cmd_init_owner(args.username)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
