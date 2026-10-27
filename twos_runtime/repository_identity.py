"""Explicit Owner-only, atomic repository-local Commit attribution setup.

No runtime identity is inferred and no global/system configuration is written.
Durable intent receipts authorize an exact config transition, not arbitrary drift.
They also permanently invalidate proposals even after an A -> B -> A change.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from sqlalchemy import func, select

from .models import AuditEvent, CommitProposal

ACTION = "repository_git_identity_save_intent"


def receipts(session, locator, owner_id):
    for event in session.scalars(select(AuditEvent).where(
        AuditEvent.action == ACTION, AuditEvent.actor_user_id == owner_id,
        AuditEvent.entity_type == "repository_git_identity",
    ).order_by(AuditEvent.id)):
        try:
            value = json.loads(event.details)
        except (ValueError, TypeError):
            continue
        if value.get("repository_locator") == locator:
            yield event, value


def proposal_identity_invalidated(session, proposal):
    return any(int(value.get("invalidates_through", 0)) >= proposal.id
               for _event, value in receipts(session, proposal.repository_locator_fingerprint,
                                             proposal.owner_id))


def authorized_config_baseline(session, applied, fingerprint, observed):
    """Follow only exact Owner-confirmed transitions; never rewrite Apply evidence."""
    reachable = {fingerprint}
    for event, value in receipts(session, applied.repository_locator_fingerprint, applied.owner_id):
        if event.created_at.replace(tzinfo=None) < applied.created_at.replace(tzinfo=None):
            continue
        if value.get("before") in reachable and value.get("changed_keys") == ["user.name", "user.email"]:
            reachable.add(value["after"])
    return observed if observed in reachable else fingerprint


def _error(code, message):
    from .commit_builder import _failure
    return _failure(code, message)


def validate_identity(name, email):
    for value in (name, email):
        try:
            encoded_length = len(value.encode("utf-8")) if isinstance(value, str) else 0
        except UnicodeError as exc:
            raise _error("GIT_IDENTITY_INPUT_INVALID", "Commit name and email must be valid UTF-8 text.") from exc
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or encoded_length > 512
                or any(ord(c) < 32 or ord(c) == 127 or c in "<>" for c in value)):
            raise _error("GIT_IDENTITY_INPUT_INVALID", "Enter a name and email without surrounding whitespace, control characters or angle brackets (maximum 512 UTF-8 bytes each).")
    if email.count("@") != 1 or any(c.isspace() for c in email) or any(not p for p in email.split("@")):
        raise _error("GIT_IDENTITY_INPUT_INVALID", "Enter your Commit email address, including a name and domain separated by @.")


def _git(root, *args):
    from .commit_builder import _run_git
    return _run_git(root, "config", *args, timeout=15).stdout


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _safe_paths(root):
    from scripts.twos_bootstrap import reject_symlink_components
    try:
        reject_symlink_components(root)
        git_dir = root / ".git"
        if not stat.S_ISDIR(git_dir.lstat().st_mode) or (git_dir / "commondir").exists():
            raise OSError("standalone repository required")
        config = git_dir / "config"
        metadata = config.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > 1048576:
            raise OSError("unsafe config")
        return git_dir, config, metadata
    except Exception as exc:
        raise _error("GIT_CONFIG_PATH_UNSAFE", "The authorized repository configuration must be a regular file in its own Git directory. No configuration was changed.") from exc


def configuration_state(root):
    _git_dir, config, _metadata = _safe_paths(root)
    from .commit_builder import _run_git
    fields = {}
    for key in ("user.name", "user.email"):
        local = _run_git(root, "config", "--local", "--get", key, check=False)
        effective = _run_git(root, "config", "--get", key, check=False)
        fields[key] = ("repository_local" if local.returncode == 0 and local.stdout.strip()
                       else "inherited_only" if effective.returncode == 0 and effective.stdout.strip()
                       else "missing")
    return {"config_digest": _digest(config.read_bytes()), "configuration_scope": "repository_local",
            "fields": fields}


def save_identity(session, *, root, applied, name, email, expected_digest, reauthorize):
    from .commit_builder import _commit_builder_repository_lock, _assert_unredirected_git_context
    from .apply_sessions import _repository_mutation_blocker
    validate_identity(name, email)
    _assert_unredirected_git_context()
    with _commit_builder_repository_lock(applied.repository_locator_fingerprint):
        reauthorize()
        if _repository_mutation_blocker(session, repository_locator_fingerprint=applied.repository_locator_fingerprint):
            raise _error("REPOSITORY_MUTATION_ACTIVE", "Finish the active repository operation before changing Commit identity.")
        git_dir, config, metadata = _safe_paths(root)
        original = config.read_bytes()
        if _digest(original) != expected_digest:
            raise _error("GIT_CONFIG_CHANGED", "Repository configuration changed. Close and reopen Commit identity settings before saving.")
        original_stat = (metadata.st_dev, metadata.st_ino)
        directory_stat = git_dir.stat()
        directory_id = (directory_stat.st_dev, directory_stat.st_ino)
        fd = os.open(git_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        lock_fd = None
        lock_id = None
        try:
            if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != directory_id:
                raise _error("GIT_CONFIG_PATH_UNSAFE", "Repository directory changed; reopen settings.")
            try:
                lock_fd = os.open("config.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=fd)
                lock_stat = os.fstat(lock_fd)
                lock_id = (lock_stat.st_dev, lock_stat.st_ino)
            except FileExistsError as exc:
                raise _error("GIT_CONFIG_LOCKED", "Another Git operation holds the configuration lock. Let it finish, then retry. TWOS did not remove its lock.") from exc
            # Git's parser edits a private copy. Both keys must succeed before publication.
            with tempfile.TemporaryDirectory(prefix="twos-git-identity-") as folder:
                staged = Path(folder) / "config"
                staged.write_bytes(original)
                before = _git(root, "--file", str(staged), "--null", "--list")
                for key, value in (("user.name", name), ("user.email", email)):
                    _git(root, "--file", str(staged), "--replace-all", "--", key, value)
                after = _git(root, "--file", str(staged), "--null", "--list")
                replacement = staged.read_bytes()
                def other_keys(raw):
                    return [r for r in raw.split(b"\0") if r and r.split(b"\n", 1)[0] not in (b"user.name", b"user.email")]
                if other_keys(before) != other_keys(after):
                    raise _error("GIT_CONFIG_WRITE_FAILED", "Configuration preservation check failed; nothing was saved.")
                if before == after:
                    return False
                reauthorize()
                _safe_paths(root)
                now = config.stat()
                if (now.st_dev, now.st_ino) != original_stat or config.read_bytes() != original or (git_dir.stat().st_dev, git_dir.stat().st_ino) != directory_id:
                    raise _error("GIT_CONFIG_CHANGED", "Repository configuration changed while saving. Reopen settings.")
                watermark = session.scalar(select(func.max(CommitProposal.id)).where(
                    CommitProposal.repository_locator_fingerprint == applied.repository_locator_fingerprint,
                    CommitProposal.owner_id == applied.owner_id)) or 0
                session.add(AuditEvent(actor_user_id=applied.owner_id, action=ACTION,
                    entity_type="repository_git_identity", entity_id=applied.id,
                    details=json.dumps({"repository_locator": applied.repository_locator_fingerprint,
                        "before": _digest(before), "after": _digest(after),
                        "changed_keys": ["user.name", "user.email"], "invalidates_through": watermark})))
                # Intent is durable before the atomic write, including a crash/failure.
                # It authorizes only these exact two-key bytes and revokes old reviews.
                session.commit()
                with os.fdopen(os.dup(lock_fd), "wb") as stream:
                    stream.write(replacement)
                    stream.flush()
                    os.fsync(stream.fileno())
                reauthorize()
                _safe_paths(root)
                now = config.stat()
                if ((now.st_dev, now.st_ino) != original_stat or config.read_bytes() != original
                        or (git_dir.stat().st_dev, git_dir.stat().st_ino) != directory_id):
                    raise _error("GIT_CONFIG_CHANGED", "Repository changed before saving. Reopen settings.")
                owned = os.stat("config.lock", dir_fd=fd, follow_symlinks=False)
                if (owned.st_dev, owned.st_ino) != lock_id:
                    raise _error("GIT_CONFIG_LOCKED", "Configuration lock ownership changed; nothing was published.")
                os.fchmod(lock_fd, stat.S_IMODE(metadata.st_mode))
                os.replace("config.lock", "config", src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
                return True
        except (OSError, subprocess.SubprocessError) as exc:
            raise _error("GIT_CONFIG_WRITE_FAILED", "Commit identity could not be saved completely. Close and reopen settings to inspect current readiness; no Commit was created.") from exc
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            if lock_id is not None:
                try:
                    present = os.stat("config.lock", dir_fd=fd, follow_symlinks=False)
                    if (present.st_dev, present.st_ino) == lock_id:
                        os.unlink("config.lock", dir_fd=fd)
                except FileNotFoundError:
                    pass
            os.close(fd)
