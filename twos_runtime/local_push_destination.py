"""Owner-confirmed local test destination; never a remote Push or approval.

An append-only intent authorizes one exact missing-origin config transition.
The original Commit receipt is never rewritten. Other configuration drift still
fails the existing Push gates. No caller-supplied path or Git command is accepted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from sqlalchemy import select

from .models import AuditEvent, PushPlan, PushExecution, Project
from .repository_identity import _safe_paths
from .commit_builder import _run_git, _git_command, _git_environment
from .delivery_candidates import canonical_sha256

ACTION = "local_push_destination_intent_v1"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fail(code, message):
    from .push_delivery import _failure
    raise _failure(code, message)


def receipt(session, commit):
    events = list(session.scalars(select(AuditEvent).where(
        AuditEvent.action == ACTION, AuditEvent.actor_user_id == commit.owner_id,
        AuditEvent.entity_type == "local_commit", AuditEvent.entity_id == commit.id,
    )))
    if not events:
        return None
    if len(events) != 1:
        fail("LOCAL_DESTINATION_RECEIPT_INVALID", "Local test destination evidence is ambiguous. No destination was changed.")
    try:
        value = json.loads(events[0].details)
        material = {k: v for k, v in value.items() if k != "digest"}
        assert value["digest"] == canonical_sha256(material)
        assert value["commit_receipt"] == commit.receipt_digest
        assert value["repository_locator"] == commit.repository_locator_fingerprint
        assert value["commit_id"] == commit.commit_execution_id
        return value
    except (ValueError, KeyError, AssertionError, TypeError):
        fail("LOCAL_DESTINATION_RECEIPT_INVALID", "Local test destination evidence could not be verified.")


def authorized_baseline(session, commit, root):
    """Only exact saved bytes + exact local destination may extend the baseline."""
    from .push_delivery import _local_remote_identity, _one_remote_url
    original = json.loads(commit.post_commit_evidence_json)
    value = receipt(session, commit)
    if not value:
        return original
    _, config, _ = _safe_paths(root)
    if (value["before_local"] != original.get("local_config_fingerprint")
            or value["before_remote"] != original.get("remote_fingerprint")
            or digest(config.read_bytes()) != value["after_raw"]):
        return original
    target = value["destination"]
    if (_one_remote_url(root, push=False).decode() != target
            or _one_remote_url(root, push=True).decode() != target
            or _local_remote_identity(root, target)["identity"] != value["target_identity"]):
        fail("LOCAL_DESTINATION_CHANGED", "The authorized local test destination changed. Push remains blocked.")
    return {**original, "local_config_fingerprint": value["after_local"],
            "remote_fingerprint": value["after_remote"]}


def preview(session, settings, commit, *, allow_prepared_target=False):
    from .push_delivery import _bound_push_context, _local_observation, _dangerous_remote_configuration
    from scripts.twos_bootstrap import reject_symlink_components, BootstrapError
    context = _bound_push_context(session, owner_id=commit.owner_id, local_commit=commit, source_repo=settings.source_repo)
    if not settings.data_root:
        fail("LOCAL_DESTINATION_INSTALLATION_REQUIRED", "Local test destination setup requires an installed TWOS data directory.")
    target = settings.data_root / "local-push-tests" / (commit.commit_execution_id + ".git")
    try:
        reject_symlink_components(target)
    except BootstrapError:
        fail("LOCAL_DESTINATION_PATH_UNSAFE", "The local test destination contains a symbolic link. It was preserved; no configuration changed.")
    _, config, _ = _safe_paths(context.root)
    existing = receipt(session, commit)
    if existing and digest(config.read_bytes()) == existing["after_raw"]:
        authorized_baseline(session, commit, context.root)
        return {**existing["preview"], "configured": True}
    if session.scalar(select(PushPlan.id).where(PushPlan.local_commit_execution_id == commit.id)) or session.scalar(select(PushExecution.id).where(PushExecution.local_commit_execution_id == commit.id)):
        fail("LOCAL_DESTINATION_PLAN_EXISTS", "A Push review already exists. This limited setup cannot replace its destination.")
    # Fail closed on any inherited origin, transport rewrite or other remotes.
    remotes = _run_git(context.root, "remote").stdout.strip()
    if remotes or _dangerous_remote_configuration(context.root):
        fail("LOCAL_DESTINATION_ALREADY_CONFIGURED", "This setup only supports a repository with no remotes or transport rewrites. Existing configuration was preserved.")
    local = _local_observation(context)
    original = json.loads(commit.post_commit_evidence_json)
    if (local["head"] != commit.commit_oid or local["branch_ref"] != "refs/heads/main"
            or not local["worktree_clean"] or not local["index_clean"] or local["target_blocker"]
            or local["local_config_fingerprint"] != original.get("local_config_fingerprint")
            or local["remote_config_fingerprint"] != original.get("remote_fingerprint")
            or local["refs_excluding_main_fingerprint"] != original.get("refs_excluding_current_fingerprint")):
        fail("LOCAL_DESTINATION_SOURCE_CHANGED", "Repository state changed after the approved Commit. No test destination can be configured from this state.")
    project = session.get(Project, context.run.project_id) if hasattr(context.run, "project_id") else None
    from .models import Task
    task = session.get(Task, context.run.task_id)
    project = session.get(Project, task.project_id) if task else project
    result = {"commit_id": commit.commit_execution_id, "commit_sha": commit.commit_oid,
              "parent_sha": commit.parent_oid, "repository": str(context.root),
              "project": project.name if project else "", "task": task.title if task else "",
              "destination": str(target), "branch": "main", "configured": False,
              "config_digest": digest(config.read_bytes()), "repository_locator": commit.repository_locator_fingerprint}
    result["preview_digest"] = canonical_sha256(result)
    if target.exists() and not existing and not allow_prepared_target:
        fail("LOCAL_DESTINATION_PATH_EXISTS", "The local test path already exists without a matching setup receipt. It was preserved; open Diagnostics for this path.")
    return result


def _seed(root, target, parent):
    """Copy only the parent and reachable history, never the delivery Commit.

    This is disclosed local initialization, not an initial-empty-remote Push.
    No clone of credentials/config/hooks, no fetch, no network, no hardlinks.
    """
    _run_git(target, "init", "--bare", "--initial-branch=main", "--template=")
    with tempfile.TemporaryFile() as pack:
        subprocess.run(_git_command(["pack-objects", "--stdout", "--revs"]), cwd=root,
                       input=(parent + "\n").encode(), stdout=pack, stderr=subprocess.DEVNULL,
                       env=_git_environment(), check=True, timeout=60)
        if pack.tell() > 256 * 1024 * 1024:
            fail("LOCAL_DESTINATION_TOO_LARGE", "The parent history exceeds the 256 MB local test limit. The incomplete private target was preserved.")
        pack.seek(0)
        subprocess.run(_git_command(["index-pack", "--stdin"]), cwd=target, stdin=pack,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=_git_environment(), check=True, timeout=60)
    _run_git(target, "update-ref", "refs/heads/main", parent, "")


def configure(session, settings, commit, expected_digest, reauthorize):
    from .push_delivery import _push_repository_lock, _local_remote_identity
    from .commit_builder import _assert_unredirected_git_context
    from .managed_workspace import private_path
    from .apply_sessions import _repository_mutation_blocker
    _assert_unredirected_git_context()
    with _push_repository_lock(commit.repository_locator_fingerprint):
        reauthorize()
        current = preview(session, settings, commit)
        if current["preview_digest"] != expected_digest:
            fail("LOCAL_DESTINATION_REVIEW_CHANGED", "The setup changed. Close and reopen Local test destination before confirming.")
        if current["configured"]:
            return current
        if _repository_mutation_blocker(session, repository_locator_fingerprint=commit.repository_locator_fingerprint):
            fail("REPOSITORY_MUTATION_ACTIVE", "Finish the active repository operation before configuring a destination.")
        root, target = Path(current["repository"]), Path(current["destination"])
        git_dir, config, metadata = _safe_paths(root)
        original = config.read_bytes()
        directory = os.open(git_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        lock = None
        lock_identity = None
        try:
            try:
                lock = os.open("config.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            except FileExistsError:
                fail("GIT_CONFIG_LOCKED", "Another Git operation holds the configuration lock. Let it finish, then retry. Its lock was preserved.")
            info = os.fstat(lock)
            lock_identity = (info.st_dev, info.st_ino)
            with tempfile.TemporaryDirectory(prefix="twos-local-destination-") as folder:
                staged = Path(folder) / "config"
                staged.write_bytes(original)
                _run_git(root, "config", "--file", str(staged), "--add", "remote.origin.url", str(target))
                replacement = staged.read_bytes()
                before_parsed = _run_git(root, "config", "--local", "--null", "--list").stdout
                after_parsed = _run_git(root, "config", "--file", str(staged), "--null", "--list").stdout
                if after_parsed != before_parsed + b"remote.origin.url\n" + str(target).encode() + b"\0":
                    fail("LOCAL_DESTINATION_CONFIG_UNSAFE", "Configuration preservation check failed. Nothing was configured.")
                old_receipt = receipt(session, commit)
                from .first_run import FirstRunError
                try:
                    private_path(target.parent)
                except FirstRunError:
                    fail("LOCAL_DESTINATION_PERMISSIONS", "The local test directory must be private and owned by this macOS user. Nothing was configured.")
                if not old_receipt:
                    target.mkdir(mode=0o700)
                    _seed(root, target, commit.parent_oid)
                if (_run_git(target, "rev-parse", "--is-bare-repository").stdout.strip() != b"true"
                        or _run_git(target, "rev-parse", "refs/heads/main").stdout.decode().strip() != commit.parent_oid):
                    fail("LOCAL_DESTINATION_BASE_CHANGED", "The local test target is not at the approved parent. It was preserved.")
                original_baseline = json.loads(commit.post_commit_evidence_json)
                value = {"commit_id": commit.commit_execution_id, "commit_receipt": commit.receipt_digest,
                         "repository_locator": commit.repository_locator_fingerprint,
                         "destination": str(target), "target_identity": _local_remote_identity(root, str(target))["identity"],
                         "before_local": original_baseline["local_config_fingerprint"],
                         "before_remote": original_baseline["remote_fingerprint"],
                         "after_raw": digest(replacement), "after_local": digest(after_parsed),
                         "after_remote": digest(_run_git(root, "-c", "remote.origin.url=" + str(target), "remote", "-v").stdout),
                         "preview": current}
                value["digest"] = canonical_sha256(value)
                if old_receipt and old_receipt != value:
                    fail("LOCAL_DESTINATION_RECEIPT_INVALID", "The incomplete destination setup changed. Nothing was configured.")
                reauthorize()
                if preview(session, settings, commit, allow_prepared_target=True)["preview_digest"] != expected_digest:
                    fail("LOCAL_DESTINATION_REVIEW_CHANGED", "The repository changed during setup. Nothing was configured.")
                if not old_receipt:
                    session.add(AuditEvent(actor_user_id=commit.owner_id, action=ACTION, entity_type="local_commit", entity_id=commit.id, details=json.dumps(value)))
                    session.commit()
                with os.fdopen(os.dup(lock), "wb") as stream:
                    stream.write(replacement)
                    stream.flush()
                    os.fsync(stream.fileno())
                reauthorize()
                _safe_paths(root)
                now = config.stat()
                owned = os.stat("config.lock", dir_fd=directory, follow_symlinks=False)
                if ((now.st_dev, now.st_ino) != (metadata.st_dev, metadata.st_ino)
                        or config.read_bytes() != original
                        or (git_dir.stat().st_dev, git_dir.stat().st_ino) != (os.fstat(directory).st_dev, os.fstat(directory).st_ino)
                        or (owned.st_dev, owned.st_ino) != lock_identity):
                    fail("LOCAL_DESTINATION_REVIEW_CHANGED", "Repository configuration or lock changed. Nothing was configured.")
                os.fchmod(lock, stat.S_IMODE(metadata.st_mode))
                os.replace("config.lock", "config", src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            return preview(session, settings, commit)
        except (OSError, subprocess.SubprocessError) as exc:
            fail("LOCAL_DESTINATION_SETUP_FAILED", "Local test setup did not finish. Your Commit and any created private target were preserved. Reopen setup to inspect its status; no Push occurred.")
        finally:
            if lock is not None:
                os.close(lock)
            if lock_identity:
                try:
                    present = os.stat("config.lock", dir_fd=directory, follow_symlinks=False)
                    if (present.st_dev, present.st_ino) == lock_identity:
                        os.unlink("config.lock", dir_fd=directory)
                except FileNotFoundError:
                    pass
            os.close(directory)


def project_state(settings):
    """Passive authorized-Project destination summary; no remote contact or setup.

    Configuration is not proof of a reviewed plan or successful delivery. Network
    addresses remain redacted and no arbitrary target is probed by this view.
    """
    from .push_delivery import _one_remote_url, _dangerous_remote_configuration, PushDeliveryError
    from .commit_builder import CommitBuilderError
    root = settings.source_repo
    base = {"remote_contacted": False, "configuration_only": True, "destination": None}
    try:
        _safe_paths(root)
        if _dangerous_remote_configuration(root):
            return {**base, "status": "UNSUPPORTED", "message": "Existing transport configuration needs review. This screen will not replace it."}
        fetch = _one_remote_url(root, push=False)
        push = _one_remote_url(root, push=True)
        if fetch != push:
            return {**base, "status": "UNSUPPORTED", "message": "origin has distinct fetch and Push destinations. Review the existing configuration; no destination was contacted."}
        value = push.decode('utf-8')
        # Only product-managed local test paths are shown in full here. Other
        # configured addresses may contain credentials and are not exposed.
        folder = settings.data_root / 'local-push-tests' if settings.data_root else None
        candidate = Path(value)
        if folder and candidate.is_absolute() and candidate.parent == folder:
            return {**base, "status": "LOCAL_TEST_CONFIGURED", "destination": value,
                    "message": "Local test destination configured for this Project. Each Task still requires its own exact Push Plan and confirmation."}
        return {**base, "status": "EXISTING_DESTINATION", "message": "An existing origin is configured. Its address is withheld here; inspect its supported, exact destination during this Task's Push Plan review. No remote contact occurred."}
    except PushDeliveryError as exc:
        if exc.code == 'ORIGIN_UNAVAILABLE':
            return {**base, "status": "MISSING", "message": "No readable origin is configured. After an approved local Commit, explicitly preview and bind a local test destination here."}
        return {**base, "status": "UNSUPPORTED", "message": "The existing destination configuration cannot be summarized safely. Review its blocker before any Push; no target was contacted."}
    except (CommitBuilderError, OSError, ValueError):
        return {**base, "status": "UNAVAILABLE", "message": "The authorized repository configuration is unavailable. Restore access before reviewing a destination."}
