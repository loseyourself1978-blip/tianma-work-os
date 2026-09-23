"""Declarative exact-file checks for the supported first-delivery product path."""
from __future__ import annotations

import base64
import json
from pathlib import Path, PurePosixPath
import sys

from sqlalchemy import select

from .models import TaskArtifactContract
from .result_intake import canonical_sha256


def command():
    return (str(Path(sys.executable).resolve()), "-I", str(Path(__file__).with_name("builtin_verifier.py").resolve()))


def uses_builtin(settings):
    return settings.fresh_install and not settings.local_verification_command or tuple(settings.local_verification_command) == command()


def effective_command(settings):
    return tuple(settings.local_verification_command) or (command() if settings.fresh_install else ())


def specification(path, expected_text):
    if not isinstance(path, str):
        raise ValueError("Choose one relative artifact file.")
    target = PurePosixPath(path)
    if (not path or not target.parts or target.is_absolute() or str(target) != path
        or any(part in {"..", ".git", ".env", ".ssh", ".codex"} for part in target.parts)
        or "\\" in path or any(ord(c) < 32 for c in path) or len(path) > 200):
        raise ValueError("Choose one relative artifact file outside credentials and Git metadata.")
    if not isinstance(expected_text, str) or not expected_text or "\0" in expected_text:
        raise ValueError("Enter the exact expected UTF-8 file contents, including the final newline if required.")
    value = {"schema": "twos.exact_artifact.v1", "path": path, "expected_text": expected_text}
    if len(json.dumps(value, ensure_ascii=False).encode()) > 2800:
        raise ValueError("The first-delivery exact artifact contract must fit within 2800 UTF-8 bytes.")
    return value


def latest(session, task_id):
    return session.scalar(select(TaskArtifactContract).where(TaskArtifactContract.task_id == task_id)
                          .order_by(TaskArtifactContract.id.desc()))


def save_contract(session, task, owner_id, path, expected_text):
    from .self_hosting import invalidate_approved_packs
    value = specification(path, expected_text)
    digest = canonical_sha256(value)
    previous = latest(session, task.id)
    if previous and previous.specification_digest == digest:
        return previous
    row = TaskArtifactContract(task_id=task.id, owner_id=owner_id,
                              specification_json=json.dumps(value, ensure_ascii=False, sort_keys=True),
                              specification_digest=digest)
    session.add(row)
    task.task_version += 1
    invalidate_approved_packs(session, task.id)
    session.flush()
    return row


def contract_out(row):
    return None if row is None else {"id": row.id, "digest": row.specification_digest,
                                    **json.loads(row.specification_json),
                                    "scope": "Exact declared file and Git boundaries only; no semantic, clinical, or release acceptance."}


def sealed_contract(session, task):
    row = latest(session, task.id)
    if row is None:
        raise ValueError("Configure this Task's built-in artifact verification before Prepare First Delivery.")
    return {"id": row.id, "digest": row.specification_digest,
            "specification": json.loads(row.specification_json)}


def runtime_command(binding, source, commit):
    value = binding["specification"]
    if canonical_sha256(value) != binding["digest"] or specification(value["path"], value["expected_text"]) != value:
        raise ValueError("The approved artifact contract is invalid.")
    payload = {"specification": value, "source": str(source), "commit": commit}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    if len(encoded) > 4096:
        raise ValueError("The artifact contract and workspace path exceed the safe command size.")
    return (*command(), "--contract", encoded)
