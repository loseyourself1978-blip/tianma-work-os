from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AIModel,
    AIModelAssignment,
    AIModelAvailabilityEvidence,
    AITeamPlan,
    CodexInstructionPack,
    CodexRun,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    RoutingDecision,
    Task,
    utc_now,
)
from .ai_orchestration import (
    assignment_binding,
    has_complete_verified_codex_run_evidence,
    latest_model_assignments,
    model_registry_snapshot,
    provider_state_hash,
)


CAPABILITY_RESPONSIBILITIES = {
    "planning": "Requirements decomposition and staged planning",
    "coding": "Implementation and technical validation",
    "verification": "Independent review and acceptance evidence",
}


def development_task_digest(development_task: str) -> str:
    """Fingerprint the exact UTF-8 Development task without normalization."""
    return hashlib.sha256(development_task.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CodexExecutionTarget:
    assignment: AIModelAssignment
    model: AIModel
    requested_model_identifier: str
    fallback_selected: bool


def _eligible_codex_model(session: Session, model: AIModel | None) -> tuple[bool, str]:
    if model is None:
        return False, "No model is assigned."
    registry = model_registry_snapshot(model)
    provider = registry["provider"]
    model_identifier = str(registry["provider_model_id"] or "")
    if registry["execution_adapter"] != "codex_cli":
        return False, "The assigned model is not bound to the local Codex CLI adapter."
    if not model_identifier:
        return False, "The assigned model has no safe provider model identifier."
    if registry["configuration_status"] != "configured":
        return False, "The assigned model needs configuration."
    if registry["availability_status"] != "available":
        return False, "The assigned model is unavailable."
    if registry["invocation_mode"] != "real":
        return False, "The assigned model is not configured for real invocation."
    if not provider["enabled"] or provider["status"] not in {"healthy", "degraded"}:
        return False, "The assigned model provider is not ready."
    if model.status not in {"healthy", "degraded"}:
        return False, "The assigned model is not ready."
    evidence = session.scalar(
        select(AIModelAvailabilityEvidence)
        .where(AIModelAvailabilityEvidence.model_id == model.id)
        .order_by(AIModelAvailabilityEvidence.id.desc())
    )
    if (
        evidence is None
        or evidence.result != "available"
        or evidence.adapter != "codex_cli"
        or evidence.invocation_mode != "real"
        or evidence.configuration_identity != model.stable_id
    ):
        return False, "The assigned model has no current successful runtime availability evidence."
    return True, model_identifier


def codex_capability_target(
    session: Session,
    task: Task,
    pack: CodexInstructionPack,
    capability: str,
) -> CodexExecutionTarget:
    """Resolve one exact approved executable capability target."""
    rows = list(
        session.scalars(
            select(AIModelAssignment).where(
                AIModelAssignment.task_id == task.id,
                AIModelAssignment.assignment_version == pack.assignment_version,
                AIModelAssignment.task_version == pack.task_version,
                AIModelAssignment.routing_snapshot_hash == pack.routing_snapshot_hash,
                AIModelAssignment.capability == capability,
            )
        ).all()
    )
    if len(rows) != 1:
        raise ValueError(f"The approved Pack does not bind exactly one {capability} model assignment.")
    assignment = rows[0]
    primary_ok, primary_reason = _eligible_codex_model(session, assignment.assigned_model)
    if primary_ok and assignment.assigned_model is not None:
        return CodexExecutionTarget(
            assignment=assignment,
            model=assignment.assigned_model,
            requested_model_identifier=primary_reason,
            fallback_selected=False,
        )
    fallback_ok, fallback_reason = _eligible_codex_model(session, assignment.fallback_model)
    if assignment.fallback_allowed and fallback_ok and assignment.fallback_model is not None:
        return CodexExecutionTarget(
            assignment=assignment,
            model=assignment.fallback_model,
            requested_model_identifier=fallback_reason,
            fallback_selected=True,
        )
    reason = primary_reason
    if assignment.fallback_allowed:
        reason = f"{primary_reason} Approved fallback is not executable: {fallback_reason}"
    raise ValueError(f"{capability.title()} model assignment needs setup. {reason}")


def codex_execution_target(
    session: Session,
    task: Task,
    pack: CodexInstructionPack,
) -> CodexExecutionTarget:
    return codex_capability_target(session, task, pack, "coding")


def verification_execution_target(
    session: Session,
    task: Task,
    pack: CodexInstructionPack,
) -> CodexExecutionTarget:
    return codex_capability_target(session, task, pack, "verification")


def codex_run_execution_target(
    session: Session,
    run: CodexRun,
    source_repo: Path | None = None,
) -> CodexExecutionTarget:
    """Revalidate the queued immutable target and current approved snapshot before process spawn."""
    if run.pack is None or run.task is None:
        raise ValueError("Codex run is missing its Pack or task binding.")
    binding_error = pack_routing_binding_error(session, run.task, run.pack, source_repo)
    if binding_error:
        raise ValueError(binding_error)
    target = codex_execution_target(session, run.task, run.pack)
    if (
        run.execution_assignment_id != target.assignment.id
        or run.execution_model_id != target.model.id
        or run.execution_provider_id != target.model.provider_id
        or run.requested_model_identifier != target.requested_model_identifier
        or run.fallback_selected != target.fallback_selected
    ):
        raise ValueError("The queued Codex execution target no longer matches the approved routing snapshot.")
    verification = verification_execution_target(session, run.task, run.pack)
    if (
        run.verification_assignment_id != verification.assignment.id
        or run.verification_model_id != verification.model.id
        or run.verification_provider_id != verification.model.provider_id
        or run.verification_model_identifier != verification.requested_model_identifier
    ):
        raise ValueError("The queued Verification target no longer matches the approved routing snapshot.")
    return target


RUN_BLOCKER_MESSAGES = {
    "TASK_MISSING": ("Save a Development task before running Codex.", "Save Task", "Save Task"),
    "PACK_MISSING": ("Generate a Codex Pack before running.", "Generate Codex Pack", "Generate Codex Pack"),
    "PACK_STALE": ("The current Codex Pack is stale.", "Regenerate Codex Pack", "Regenerate Codex Pack"),
    "APPROVAL_REQUIRED": ("Approve the current Codex Pack before running.", "Approve Codex Pack", "Approve Codex Pack"),
    "APPROVAL_STALE": ("Approval no longer matches the current task or routing.", "Regenerate Codex Pack", "Regenerate Codex Pack"),
    "CODING_SETUP_REQUIRED": ("Coding needs setup.", "Set up Codex", "Set up Codex"),
    "CODING_RUNTIME_UNAVAILABLE": ("Coding runtime is unavailable.", "Check availability", "Manage Codex"),
    "VERIFICATION_SETUP_REQUIRED": ("Verification needs setup.", "Set up Verification", "Set up Verification"),
    "VERIFICATION_RUNTIME_UNAVAILABLE": ("Verification runtime is unavailable.", "Check availability", "Manage Codex"),
    "SOURCE_SNAPSHOT_MISSING": ("The Pack has no approved source snapshot.", "Regenerate Codex Pack", "Regenerate Codex Pack"),
    "SOURCE_CHANGED_SINCE_APPROVAL": ("Source changed since approval. Regenerate Codex Pack.", "Regenerate Codex Pack", "Regenerate Codex Pack"),
    "ACTIVE_RUN_EXISTS": ("A Codex Run is already active for this task.", "Wait or Cancel Run", "Cancel Run"),
}


def _run_blocker(code: str) -> dict[str, str]:
    message, next_action, control = RUN_BLOCKER_MESSAGES[code]
    return {"code": code, "message": message, "next_action": next_action, "control": control}


def run_eligibility(
    session: Session,
    task: Task | None,
    source_repo: Path,
) -> dict[str, Any]:
    """Single server-side truth for status rendering and atomic Run admission."""
    blockers: list[dict[str, str]] = []
    pack: CodexInstructionPack | None = None
    if task is None:
        blockers.append(_run_blocker("TASK_MISSING"))
    else:
        pack = session.scalar(
            select(CodexInstructionPack)
            .where(CodexInstructionPack.task_id == task.id)
            .order_by(CodexInstructionPack.version.desc())
        )
        current_assignments = latest_model_assignments(session, task.id)
        current_by_capability = {item.capability: item for item in current_assignments}
        for capability, setup_code, runtime_code in (
            ("coding", "CODING_SETUP_REQUIRED", "CODING_RUNTIME_UNAVAILABLE"),
            ("verification", "VERIFICATION_SETUP_REQUIRED", "VERIFICATION_RUNTIME_UNAVAILABLE"),
        ):
            assignment = current_by_capability.get(capability)
            if assignment is None or assignment.assigned_model is None:
                blockers.append(_run_blocker(setup_code))
                continue
            if pack is not None:
                try:
                    codex_capability_target(session, task, pack, capability)
                except ValueError:
                    blockers.append(_run_blocker(runtime_code))
            else:
                primary_ok, _ = _eligible_codex_model(session, assignment.assigned_model)
                fallback_ok, _ = _eligible_codex_model(session, assignment.fallback_model)
                if not primary_ok and not (assignment.fallback_allowed and fallback_ok):
                    blockers.append(_run_blocker(runtime_code))
        if pack is None:
            blockers.append(_run_blocker("PACK_MISSING"))
        else:
            if not pack.source_snapshot_digest or not pack.source_snapshot_json:
                blockers.append(_run_blocker("SOURCE_SNAPSHOT_MISSING"))
            binding_error = pack_routing_binding_error(session, task, pack, source_repo)
            if binding_error:
                code = (
                    "SOURCE_CHANGED_SINCE_APPROVAL"
                    if binding_error.startswith("Source changed")
                    else "PACK_STALE"
                )
                blocker = _run_blocker(code)
                if code == "PACK_STALE":
                    blocker["message"] = binding_error
                blockers.append(blocker)
            if pack.status != "approved" or pack.invalidated_at is not None:
                blockers.append(
                    _run_blocker("APPROVAL_STALE" if pack.invalidated_at else "APPROVAL_REQUIRED")
                )
            active = session.scalar(
                select(CodexRun).where(
                    CodexRun.task_id == task.id,
                    CodexRun.status.in_(["queued", "starting", "running", "verifying"]),
                )
            )
            if active is not None:
                blockers.append(_run_blocker("ACTIVE_RUN_EXISTS"))
    # Preserve stable order while removing duplicate codes.
    unique = {item["code"]: item for item in blockers}
    blockers = [unique[code] for code in unique]
    primary = blockers[0] if blockers else None
    return {
        "eligible": not blockers,
        "blockers": blockers,
        "primary_blocker": primary,
        "next_action": primary["next_action"] if primary else "Run Codex",
        "control": primary["control"] if primary else "Run Codex",
        "pack_id": pack.id if pack else None,
        "pack_version": pack.version if pack else None,
    }


def run_git(repo: Path, *args: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "Git command failed."
        raise RuntimeError(message)
    return result


def git_source_state(repo: Path) -> dict[str, object]:
    root = Path(run_git(repo, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    branch = run_git(root, "branch", "--show-current").stdout.strip()
    commit = run_git(root, "rev-parse", "HEAD").stdout.strip()
    status = run_git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    return {
        "repo": root,
        "identity": root.name,
        "branch": branch,
        "commit": commit,
        "clean": not status,
        "status": status,
    }


SOURCE_SNAPSHOT_SCHEMA = "twos.source_snapshot.v2"
SOURCE_SNAPSHOT_MAX_FILE_BYTES = 4_000_000
SOURCE_SNAPSHOT_MAX_TOTAL_BYTES = 24_000_000
_SECRET_PATH = re.compile(
    r"(^|/)(?:\.env(?:\..*)?|id_(?:rsa|dsa|ecdsa|ed25519)|credentials?|secrets?|tokens?)(?:$|[./_-])|"
    r"\.(?:pem|p12|pfx|key)$",
    re.IGNORECASE,
)
_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".phase63a-worktree",
}


def _snapshot_exclusion_reason(relative_path: str) -> str | None:
    normalized = relative_path.replace("\\", "/").strip("/")
    parts = tuple(part.casefold() for part in Path(normalized).parts)
    lowered = normalized.casefold()
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        return "unsafe_path"
    if any(part in _EXCLUDED_PARTS for part in parts):
        return "runtime_or_cache"
    if _SECRET_PATH.search(normalized):
        return "credential_or_secret"
    if lowered.endswith((".sqlite", ".sqlite3", ".db", ".log", ".pyc", ".pyo")):
        return "runtime_or_generated"
    if lowered.startswith(("worktrees/", ".twos-", "tmp/", "temp/")):
        return "runtime_or_generated"
    return None


def _nul_paths(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def _tracked_change_records(repo: Path) -> list[dict[str, Any]]:
    """Return content-safe Git change metadata, including detected renames."""
    tokens = _nul_paths(
        run_git(
            repo,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            "--find-copies",
            "HEAD",
        ).stdout
    )
    records: list[dict[str, Any]] = []
    index = 0
    labels = {
        "A": "added",
        "C": "copied",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "type_changed",
        "U": "unmerged",
        "X": "unknown",
    }
    while index < len(tokens):
        raw_status = tokens[index]
        index += 1
        code = raw_status[:1]
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise RuntimeError("Git returned incomplete rename metadata for the source snapshot.")
            previous_path = tokens[index]
            path = tokens[index + 1]
            index += 2
            records.append(
                {
                    "path": path,
                    "previous_path": previous_path,
                    "change_type": labels[code],
                    "similarity": raw_status[1:] or None,
                    "patch_paths": [previous_path, path],
                }
            )
            continue
        if index >= len(tokens):
            raise RuntimeError("Git returned incomplete change metadata for the source snapshot.")
        path = tokens[index]
        index += 1
        records.append(
            {
                "path": path,
                "change_type": labels.get(code, "unknown"),
                "patch_paths": [path],
            }
        )
    return records


def _source_snapshot_digest(snapshot: dict[str, Any]) -> str:
    digest_payload = json.loads(json.dumps(snapshot))
    digest_payload.pop("digest", None)
    digest_payload.pop("source_branch", None)
    # Excluded paths are review evidence, not executable source. They are
    # intentionally absent from the hydrated workspace, so they cannot form
    # part of its reproducible execution digest.
    digest_payload.pop("excluded_manifest", None)
    return hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def capture_source_snapshot(repo: Path) -> dict[str, Any]:
    """Capture the approval-bound dirty source state without secret material."""
    source = git_source_state(repo)
    root = Path(source["repo"])
    tracked = _nul_paths(run_git(root, "ls-files", "-z").stdout)
    untracked = _nul_paths(
        run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    )
    change_records = _tracked_change_records(root)
    staged = set(_nul_paths(run_git(root, "diff", "--cached", "--name-only", "-z").stdout))
    unstaged = set(_nul_paths(run_git(root, "diff", "--name-only", "-z").stdout))
    excluded: list[dict[str, str]] = []
    included_records: dict[str, dict[str, Any]] = {}
    included_patch_paths: set[str] = set()
    for record in change_records:
        record_paths = [str(item) for item in record.get("patch_paths", [])]
        exclusions = [
            (relative_path, _snapshot_exclusion_reason(relative_path))
            for relative_path in record_paths
        ]
        if any(reason for _, reason in exclusions):
            for relative_path, reason in exclusions:
                if reason:
                    excluded.append({"path": relative_path, "reason": reason})
            continue
        included_records[str(record["path"])] = record
        included_patch_paths.update(record_paths)
    for relative_path in sorted(set(tracked) - set(included_records)):
        reason = _snapshot_exclusion_reason(relative_path)
        if reason:
            excluded.append({"path": relative_path, "reason": reason})

    staged_patch_bytes = b""
    unstaged_patch_bytes = b""
    if included_patch_paths:
        staged_patch_result = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--find-renames",
                "--find-copies",
                "HEAD",
                "--",
                *sorted(included_patch_paths),
            ],
            cwd=root,
            capture_output=True,
            timeout=60,
        )
        unstaged_patch_result = subprocess.run(
            [
                "git",
                "diff",
                "--binary",
                "--full-index",
                "--find-renames",
                "--find-copies",
                "--",
                *sorted(included_patch_paths),
            ],
            cwd=root,
            capture_output=True,
            timeout=60,
        )
        if staged_patch_result.returncode != 0 or unstaged_patch_result.returncode != 0:
            raise RuntimeError("Approved source snapshot patch could not be captured.")
        staged_patch_bytes = staged_patch_result.stdout
        unstaged_patch_bytes = unstaged_patch_result.stdout

    untracked_rows: list[dict[str, Any]] = []
    total_bytes = len(staged_patch_bytes) + len(unstaged_patch_bytes)
    if total_bytes > SOURCE_SNAPSHOT_MAX_TOTAL_BYTES:
        raise RuntimeError("Source snapshot exceeds the bounded capture limit.")
    for relative_path in sorted(set(untracked)):
        reason = _snapshot_exclusion_reason(relative_path)
        if reason:
            excluded.append({"path": relative_path, "reason": reason})
            continue
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file() or candidate.is_symlink():
            excluded.append({"path": relative_path, "reason": "unsupported_file_type"})
            continue
        payload = candidate.read_bytes()
        if len(payload) > SOURCE_SNAPSHOT_MAX_FILE_BYTES:
            raise RuntimeError(f"Source snapshot file is too large: {relative_path}")
        total_bytes += len(payload)
        if total_bytes > SOURCE_SNAPSHOT_MAX_TOTAL_BYTES:
            raise RuntimeError("Source snapshot exceeds the bounded capture limit.")
        untracked_rows.append(
            {
                "path": relative_path,
                "mode": candidate.stat().st_mode & 0o777,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "content_b64": base64.b64encode(payload).decode("ascii"),
            }
        )

    tracked_manifest: list[dict[str, Any]] = []
    tracked_manifest_paths = sorted(set(tracked) | set(included_records))
    for path in tracked_manifest_paths:
        reason = _snapshot_exclusion_reason(path)
        if reason:
            continue
        candidate = (root / path).resolve()
        change = included_records.get(path, {})
        row: dict[str, Any] = {
            "path": path,
            "kind": "tracked_change" if change else "tracked",
            "staged": path in staged,
            "unstaged": path in unstaged,
            "deleted": not candidate.exists(),
        }
        if change:
            row["change_type"] = change.get("change_type", "modified")
            if change.get("previous_path"):
                row["previous_path"] = change["previous_path"]
            if change.get("similarity"):
                row["similarity"] = change["similarity"]
        if candidate.is_symlink():
            excluded.append({"path": path, "reason": "unsupported_file_type"})
            continue
        if candidate.exists() and candidate.is_file():
            payload = candidate.read_bytes()
            row.update(
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                mode=candidate.stat().st_mode & 0o777,
            )
        tracked_manifest.append(row)
    manifest = tracked_manifest + [
        {
            "path": row["path"],
            "kind": "untracked",
            "staged": False,
            "unstaged": True,
            "size": row["size"],
            "sha256": row["sha256"],
            "mode": row["mode"],
            "deleted": False,
        }
        for row in untracked_rows
    ]
    snapshot: dict[str, Any] = {
        "schema": SOURCE_SNAPSHOT_SCHEMA,
        "head_sha": source["commit"],
        "source_branch": source["branch"],
        "staged_patch_b64": base64.b64encode(staged_patch_bytes).decode("ascii"),
        "unstaged_patch_b64": base64.b64encode(unstaged_patch_bytes).decode("ascii"),
        "untracked_files": untracked_rows,
        "included_manifest": manifest,
        "excluded_manifest": sorted(excluded, key=lambda item: (item["path"], item["reason"])),
        "exclusion_policy": (
            "Exclude Git metadata, environments, caches, runtime databases/logs/worktrees, "
            "ignored files, credential-shaped paths, symlinks, and generated execution artifacts."
        ),
    }
    snapshot["digest"] = _source_snapshot_digest(snapshot)
    return snapshot


def public_source_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a content-free snapshot summary safe for UI, Pack, and audit output."""
    excluded_manifest = []
    for item in snapshot.get("excluded_manifest", []):
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason", "excluded"))
        excluded_manifest.append(
            {
                "path": (
                    "[credential-shaped path withheld]"
                    if reason == "credential_or_secret"
                    else str(item.get("path", ""))
                ),
                "reason": reason,
            }
        )
    return {
        "schema": snapshot.get("schema"),
        "head_sha": snapshot.get("head_sha"),
        "source_branch": snapshot.get("source_branch"),
        "digest": snapshot.get("digest"),
        "included_manifest": snapshot.get("included_manifest", []),
        "excluded_manifest": excluded_manifest,
        "exclusion_policy": snapshot.get("exclusion_policy", ""),
    }


def hydrate_source_snapshot(worktree: Path, snapshot: dict[str, Any]) -> None:
    if snapshot.get("schema") != SOURCE_SNAPSHOT_SCHEMA or not snapshot.get("digest"):
        raise RuntimeError("Approved source snapshot is missing or invalid.")
    if run_git(worktree, "rev-parse", "HEAD").stdout.strip() != snapshot.get("head_sha"):
        raise RuntimeError("Isolated workspace HEAD does not match the approved source snapshot.")
    for item in snapshot.get("excluded_manifest", []):
        relative_path = str(item.get("path", ""))
        candidate = (worktree / relative_path).resolve()
        if candidate.is_relative_to(worktree.resolve()) and candidate.exists() and candidate.is_file():
            candidate.unlink()
    staged_patch_bytes = base64.b64decode(
        str(snapshot.get("staged_patch_b64", "")), validate=True
    )
    unstaged_patch_bytes = base64.b64decode(
        str(snapshot.get("unstaged_patch_b64", "")), validate=True
    )

    def apply_patch(payload: bytes, *, update_index: bool) -> None:
        if not payload:
            return
        patch_path = worktree / ".twos-approved-source.patch"
        patch_path.write_bytes(payload)
        try:
            arguments = ["apply", "--binary", "--whitespace=nowarn"]
            if update_index:
                arguments.append("--index")
            arguments.append(str(patch_path))
            applied = run_git(
                worktree,
                *arguments,
                check=False,
                timeout=60,
            )
            if applied.returncode != 0:
                raise RuntimeError("Approved tracked source changes could not be hydrated.")
        finally:
            patch_path.unlink(missing_ok=True)

    apply_patch(staged_patch_bytes, update_index=True)
    apply_patch(unstaged_patch_bytes, update_index=False)
    for row in snapshot.get("untracked_files", []):
        relative_path = str(row.get("path", ""))
        if _snapshot_exclusion_reason(relative_path):
            raise RuntimeError("Approved untracked source manifest contains an excluded path.")
        candidate = (worktree / relative_path).resolve()
        if not candidate.is_relative_to(worktree.resolve()):
            raise RuntimeError("Approved untracked source path escapes the isolated workspace.")
        payload = base64.b64decode(str(row.get("content_b64", "")), validate=True)
        if hashlib.sha256(payload).hexdigest() != row.get("sha256"):
            raise RuntimeError("Approved untracked source content failed integrity validation.")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(payload)
        os.chmod(candidate, int(row.get("mode", 0o644)) & 0o777)
    hydrated = capture_source_snapshot(worktree)
    if hydrated.get("digest") != snapshot.get("digest"):
        raise RuntimeError("Hydrated source snapshot digest does not match Owner approval.")


def latest_ai_context(session: Session, task_id: int) -> tuple[AITeamPlan | None, list[RoutingDecision]]:
    plan = session.scalar(
        select(AITeamPlan).where(AITeamPlan.task_id == task_id).order_by(AITeamPlan.id.desc())
    )
    if not plan:
        return None, []
    routes = list(
        session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.team_plan_id == plan.id)
            .order_by(RoutingDecision.id)
        ).all()
    )
    return plan, routes


def _assigned_model_snapshot(assignment: AIModelAssignment, *, fallback: bool = False) -> dict[str, Any] | None:
    model = assignment.fallback_model if fallback else assignment.assigned_model
    if model is None:
        return None
    registry = model_registry_snapshot(model)
    return {
        "stable_id": registry["stable_id"],
        "display_name": registry["display_name"],
        "provider": registry["provider"]["name"],
        "provider_model_id": registry["provider_model_id"],
        "execution_adapter": registry["execution_adapter"],
        "provider_status": registry["provider"]["status"],
        "provider_enabled": registry["provider"]["enabled"],
        "configuration_status": registry["configuration_status"],
        "availability_status": registry["availability_status"],
        "invocation_mode": registry["invocation_mode"],
        "evidence_status": registry["evidence_status"],
        "evidence_source": registry["evidence_source"],
        "last_verified_at": registry["last_verified_at"],
        "safe_diagnostic": registry["safe_diagnostic"],
        "selection_state": "not_used" if fallback else "selected",
    }


def _assignment_readiness(assignment: AIModelAssignment) -> str:
    model = assignment.assigned_model
    if model is None:
        return "needs_setup"
    registry = model_registry_snapshot(model)
    if registry["configuration_status"] == "disabled" or registry["availability_status"] == "disabled":
        return "disabled"
    if registry["invocation_mode"] == "simulated":
        return "simulated"
    if assignment.independence_required and assignment.independence_status not in {
        "independent",
        "independent_fallback",
        "separate_invocation",
    }:
        return "needs_setup"
    if (
        registry["configuration_status"] != "configured"
        or registry["availability_status"] != "available"
        or not registry["provider"]["enabled"]
        or registry["provider"]["status"] not in {"healthy", "degraded"}
    ):
        return "needs_setup"
    if registry["invocation_mode"] == "manual":
        return "configured"
    if registry["invocation_mode"] != "real":
        return "needs_setup"
    if registry["evidence_status"] == "verified" and registry["last_verified_at"] is not None:
        return "ready"
    return "runtime_available_model_configured_not_invoked"


def assignment_snapshot_out(assignment: AIModelAssignment) -> dict[str, Any]:
    """Return the persisted, secret-free Owner review contract for one capability."""
    deterministic_non_invoking = (
        assignment.capability == "planning" and assignment.assigned_model is None
    )
    return {
        "id": assignment.id,
        "capability": assignment.capability,
        "responsibility": CAPABILITY_RESPONSIBILITIES.get(
            assignment.capability,
            "Task-specific capability responsibility",
        ),
        "assigned_model": _assigned_model_snapshot(assignment),
        "readiness": (
            "deterministic_no_model_invocation"
            if deterministic_non_invoking
            else _assignment_readiness(assignment)
        ),
        "invocation_mode": (
            assignment.assigned_model.invocation_mode
            if assignment.assigned_model is not None
            else "deterministic"
            if deterministic_non_invoking
            else "unavailable"
        ),
        "execution_kind": "deterministic" if deterministic_non_invoking else "model",
        "model_invocation_required": not deterministic_non_invoking,
        "is_executable_model_assignment": assignment.assigned_model is not None,
        "non_executing_label": (
            "Deterministic / No model invocation" if deterministic_non_invoking else ""
        ),
        "assignment_reason": assignment.assignment_reason,
        "routing_source": assignment.routing_source,
        "availability_at_composition": assignment.availability_at_composition,
        "fallback_allowed": assignment.fallback_allowed,
        "fallback_model": _assigned_model_snapshot(assignment, fallback=True),
        "fallback_reason": assignment.fallback_reason,
        "independence_required": assignment.independence_required,
        "independence_status": assignment.independence_status,
        "assignment_version": assignment.assignment_version,
        "task_version": assignment.task_version,
        "routing_snapshot_hash": assignment.routing_snapshot_hash,
        "created_at": assignment.created_at.isoformat() + "Z" if assignment.created_at else None,
    }


def model_routing_snapshot(session: Session, task_id: int) -> dict[str, Any]:
    assignments = latest_model_assignments(session, task_id)
    binding = assignment_binding(assignments)
    public_assignments = [assignment_snapshot_out(item) for item in assignments]
    capability_names = list(
        dict.fromkeys(str(item["capability"]) for item in public_assignments)
    )
    executable_assignment_count = sum(
        item["is_executable_model_assignment"] is True for item in public_assignments
    )
    non_executing_capabilities = [
        str(item["capability"])
        for item in public_assignments
        if item["is_executable_model_assignment"] is not True
    ]
    models = {
        model.id: model
        for assignment in assignments
        for model in (assignment.assigned_model, assignment.fallback_model)
        if model is not None
    }
    return {
        **binding,
        "provider_state_hash": provider_state_hash(models.values()),
        "assignments": public_assignments,
        "capability_count": len(capability_names),
        "executable_assignment_count": executable_assignment_count,
        "non_executing_capabilities": non_executing_capabilities,
    }


def pack_routing_binding_error(
    session: Session,
    task: Task,
    pack: CodexInstructionPack,
    source_repo: Path | None = None,
) -> str | None:
    if pack.task_id != task.id:
        return "The pack is bound to a different Task. Regenerate the pack."
    current = model_routing_snapshot(session, task.id)
    if not current["assignments"]:
        return "Recompose the AI Team before approval or execution."
    if pack.task_version != task.task_version:
        return "Task content changed after this pack was generated. Regenerate the pack."
    current_development_task = task.development_task
    current_task_digest = development_task_digest(current_development_task)
    if (
        not pack.development_task_digest
        or pack.development_task_digest != current_task_digest
        or pack.development_task != current_development_task
    ):
        return "Development task changed after this pack was generated. Regenerate the pack."
    if pack.assignment_version != current["assignment_version"]:
        return "Capability assignments changed after this pack was generated. Regenerate the pack."
    if pack.routing_snapshot_hash != current["routing_snapshot_hash"]:
        return "The model-routing snapshot changed after this pack was generated. Regenerate the pack."
    try:
        metadata = json.loads(pack.generation_metadata or "{}")
    except json.JSONDecodeError:
        return "The pack routing metadata is invalid. Regenerate the pack."
    if metadata.get("provider_state_hash") != current["provider_state_hash"]:
        return "Provider readiness affecting execution changed. Recompose the AI Team and regenerate the pack."
    if source_repo is not None:
        try:
            current_source = capture_source_snapshot(source_repo)
        except RuntimeError:
            return "Source snapshot could not be verified. Regenerate Codex Pack."
        if not pack.source_snapshot_digest or current_source["digest"] != pack.source_snapshot_digest:
            return "Source changed since approval. Regenerate Codex Pack."
    return None


def invalidate_approved_packs(session: Session, task_id: int) -> int:
    packs = session.scalars(
        select(CodexInstructionPack).where(
            CodexInstructionPack.task_id == task_id,
            CodexInstructionPack.status == "approved",
        )
    ).all()
    for pack in packs:
        pack.status = "invalidated"
        pack.invalidated_at = utc_now()
    return len(packs)


def _capability_names(plan: AITeamPlan | None) -> list[str]:
    if not plan:
        return []
    try:
        decoded = json.loads(plan.required_capabilities)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def build_instruction_pack(session: Session, task: Task, source_repo: Path) -> CodexInstructionPack:
    if task.workflow_type != "product_development":
        raise ValueError("Codex Instruction Packs require a product_development task.")
    frozen_development_task = task.development_task
    if not frozen_development_task.strip():
        raise ValueError("Save a complete Development task before generating a Codex Instruction Pack.")
    frozen_development_task_digest = development_task_digest(frozen_development_task)
    plan, routes = latest_ai_context(session, task.id)
    if not plan:
        raise ValueError("Compose the AI Team before generating a Codex Instruction Pack.")
    routing_snapshot = model_routing_snapshot(session, task.id)
    if not routing_snapshot["assignments"]:
        raise ValueError("Recompose the AI Team to persist model assignments before generating a pack.")

    source = git_source_state(source_repo)
    source_snapshot = capture_source_snapshot(source_repo)
    baseline = str(source_snapshot["head_sha"])
    version = int(
        session.scalar(
            select(func.max(CodexInstructionPack.version)).where(CodexInstructionPack.task_id == task.id)
        )
        or 0
    ) + 1
    previous = session.scalars(
        select(CodexInstructionPack).where(
            CodexInstructionPack.task_id == task.id,
            CodexInstructionPack.status.in_(["approval_required", "approved"]),
        )
    ).all()
    for pack in previous:
        pack.status = "superseded" if pack.status == "approval_required" else "invalidated"
        pack.invalidated_at = utc_now()

    capabilities = _capability_names(plan)
    route_states = [f"{route.capability.name}: {route.status}" for route in routes]
    assignment_states = [
        (
            f"{item['capability']}: "
            f"{item['assigned_model']['display_name'] if item['assigned_model'] else 'No model assigned'} "
            f"({item['readiness']}, {item['invocation_mode']})"
        )
        for item in routing_snapshot["assignments"]
    ]
    boundaries = "\n".join(
        [
            task.forbidden_scope or "No additional forbidden scope supplied.",
            "No automatic merge or push.",
            "No live trading or live betting execution.",
            "Codex execution requires explicit Owner approval for this exact pack version.",
        ]
    )
    stage_summary = (
        "A Inspect source and accepted behavior; B implement the scoped change; C verify product flow; "
        "D validate boundaries and regressions; E report Git-derived evidence."
    )
    content = f"""# TWOS Codex Instruction Pack v{version}

## Identity and Baseline
- Repository: {task.repository_identity or source['identity']}
- Source branch: {source['branch']}
- Source commit: {baseline}
- Approved source snapshot: {source_snapshot['digest']}
- Workflow: product_development
- Development task: {frozen_development_task}
- Development task SHA-256: {frozen_development_task_digest}

## Goal
{task.objective or task.development_task or task.title}

## Product Intent
{task.source_sync_summary or 'Use the persisted TWOS task context.'}

## AI Team Plan
- Capabilities: {', '.join(capabilities)}
- Team reason: {plan.explanation}
- Routing evaluation: {'; '.join(route_states) or 'No routing records.'}
- Model assignments: {'; '.join(assignment_states)}
- Assignment version: {routing_snapshot['assignment_version']}
- Task version: {routing_snapshot['task_version']}
- Execution must use this exact approved routing snapshot; availability alone is not authorization.

## Implementation Scope
{task.implementation_scope or task.required_output}

## Ordered Stages
### Stage A | Inspect
- Confirm the source commit and existing product behavior.
- Identify the smallest modules required by the implementation scope.
Self-check: accepted behavior and ownership boundaries are understood before editing.

### Stage B | Implement
- Implement the required output inside the stated implementation scope.
- Keep the existing stack and operation path intact.
Self-check: the requested capability has a backend path, Owner control, visible result, and persistence.

### Stage C | Product Verification
- Verify the Owner operation path and visible feedback.
- Keep default UI focused; place technical detail under Advanced.
Self-check: the Owner can complete the task without chat-only instructions.

### Stage D | Validation and Boundaries
- Run the validation commands below.
- Confirm forbidden scope remains closed.
Self-check: failures, dirty state, and policy boundaries are reported honestly.

### Stage E | Result
- Return changed files, completed work, tests, boundaries, and commit state.
- Do not merge or push.
Self-check: every claim is supported by Git or test evidence.

## Required Output
{task.required_output}

## Acceptance Target
{task.acceptance_target}

## Forbidden Scope
{boundaries}

## Validation Commands
- Use only validation proportionate to the approved task and available without installing dependencies.
- For application-code changes, run `.venv/bin/python -m pytest -q` and `.venv/bin/python -m compileall -q twos_runtime tests` when the existing environment provides them.
- For documentation-only work, verify the exact required artifact and run `git diff --check`.
- Never install or update dependencies as part of this run.

## Commit Policy
- Do not commit.
- Leave all changes uncommitted in the isolated worktree for Owner review.
- Do not merge to main.
- Do not push any branch.

## Final Response Format
- Overall status
- Changed files
- Stage results
- Tests
- Boundary confirmation
- Commit hash or uncommitted state
- Owner review needed

## Stop Conditions
- Stop if the approved source snapshot cannot be hydrated and verified in the isolated workspace.
- Stop if implementation requires forbidden scope, unsafe shell execution, automatic merge, or push.
- Stop if validation cannot be completed safely.

## Owner Acceptance Checklist
- Required output is visible in the Result surface.
- Git-derived changed files match the implementation scope.
- Validation evidence passes.
- Forbidden scope remains closed.
- Acceptance does not merge or push.
"""
    pack = CodexInstructionPack(
        task_id=task.id,
        version=version,
        status="approval_required",
        content=content,
        stage_summary=stage_summary,
        key_boundaries=boundaries,
        acceptance_target=task.acceptance_target,
        source_baseline_commit=baseline,
        development_task=frozen_development_task,
        development_task_digest=frozen_development_task_digest,
        assignment_version=routing_snapshot["assignment_version"],
        task_version=routing_snapshot["task_version"],
        routing_snapshot_hash=routing_snapshot["routing_snapshot_hash"],
        source_snapshot_digest=source_snapshot["digest"],
        source_snapshot_json=json.dumps(source_snapshot, sort_keys=True, separators=(",", ":")),
        ai_team_plan_id=plan.id,
        routing_decision_ids=json.dumps([route.id for route in routes], separators=(",", ":")),
        generation_metadata=json.dumps(
            {
                "builder": "deterministic_full_stage_pack_v2",
                "source_branch": source["branch"],
                "development_task_digest": frozen_development_task_digest,
                "source_snapshot": public_source_snapshot(source_snapshot),
                "provider_state_hash": routing_snapshot["provider_state_hash"],
                "model_routing_snapshot": routing_snapshot,
            },
            separators=(",", ":"),
        ),
    )
    session.add(pack)
    session.flush()
    task.status = "approval_required"
    return pack


def create_owner_acceptance(session: Session, task: Task, run: CodexRun) -> OwnerAcceptanceSession:
    existing = session.scalar(
        select(OwnerAcceptanceSession).where(OwnerAcceptanceSession.codex_run_id == run.id)
    )
    if existing:
        return existing
    try:
        result = json.loads(run.structured_result or "{}")
    except json.JSONDecodeError:
        result = {}
    validation = result.get("validation", {})
    model_evidence_verified = has_complete_verified_codex_run_evidence(session, run)
    session_row = OwnerAcceptanceSession(task_id=task.id, codex_run_id=run.id, status="owner_review")
    session.add(session_row)
    session.flush()
    items = [
        (
            "required_output",
            f'Required output for "{task.title}" is complete',
            task.required_output or task.objective,
            "Result -> What was completed",
            "The visible result directly addresses the persisted required output.",
            "pending",
        ),
        (
            "git_scope",
            "Git-derived changed files match Implementation scope",
            task.implementation_scope,
            "Result -> Changed files",
            "Every changed file is explained by the implementation scope and no unexpected file is present.",
            "pending",
        ),
        (
            "validation",
            "Validation evidence passes",
            "Codex process result and independent Git diff check",
            "Result -> Tests",
            "Process exit is successful and git diff --check passes.",
            "pending" if validation.get("diff_check") is True and run.exit_code == 0 else "fail",
        ),
        (
            "model_evidence",
            "Coding and Verification invocation evidence is separately verified",
            (
                "Both exact run assignments, requested model arguments, process/turn lifecycles, "
                "request delivery, and any independently exposed resolved-model identity"
            ),
            "Result -> Model evidence",
            (
                "Both Coding and Verification require separate, complete, persisted invocation proof "
                "bound to this run; a resolved model is claimed only when CLI evidence exposes it."
            ),
            "pending" if model_evidence_verified else "fail",
        ),
        (
            "forbidden_scope",
            "Forbidden scope remains closed",
            task.forbidden_scope,
            "Result -> Boundary confirmation",
            "No forbidden integration, merge, push, live trade, or live bet action occurred.",
            "pending",
        ),
        (
            "commit_state",
            "Worktree and commit state are reviewable",
            "Source baseline, worktree branch, commit list, and dirty state",
            "Result -> Commit state",
            "Git evidence identifies the isolated worktree state without relying on Codex prose.",
            "pending",
        ),
    ]
    for ordinal, (key, label, inspect_target, ui_path, pass_standard, status) in enumerate(items):
        session.add(
            OwnerAcceptanceItem(
                session_id=session_row.id,
                key=key,
                label=label,
                inspect_target=inspect_target,
                ui_path=ui_path,
                pass_standard=pass_standard,
                required=True,
                status=status,
                ordinal=ordinal,
            )
        )
    task.status = "owner_review"
    session.flush()
    return session_row


def accepted_compact_sync(task: Task, run: CodexRun, pack: CodexInstructionPack) -> str:
    try:
        result = json.loads(run.structured_result or "{}")
    except json.JSONDecodeError:
        result = {}
    changed_files = result.get("changed_files", [])
    validation = result.get("validation", {})
    plan_capabilities = _capability_names(pack.ai_team_plan)
    return "\n".join(
        [
            "Vol.17 Productization Sprint 2 Compact Sync",
            f"Task: {task.title}",
            f"Source baseline: {run.source_commit}",
            f"AI Team Plan: {', '.join(plan_capabilities) or 'Persisted plan'}",
            f"Codex Pack: v{pack.version}",
            f"Codex Run: #{run.id} / {run.status}",
            "Acceptance: Owner accepted all required items.",
            f"Changed files: {', '.join(changed_files) or 'None'}",
            f"Tests: {', '.join(result.get('tests_reported', [])) or 'No test lines reported'}",
            f"Git diff check: {'PASS' if validation.get('diff_check') else 'NEEDS REVIEW'}",
            f"Commit/worktree: {result.get('post_run_commit', run.source_commit)} / {result.get('working_tree_status', 'unknown')}",
            "Next action: review and merge manually if appropriate; nothing was merged or pushed by TWOS.",
            "Accepted in TWOS does not mean merged or pushed.",
        ]
    )
