"""19.2B setup and immutable preparation bindings around the accepted pipeline.

No import, projection, or configuration save performs a provider request. Only
the explicit readiness API invokes the existing connectivity service.
"""
from __future__ import annotations

import json
import os
import re
import stat
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .codex_connectivity import (
    _file_content_identity, codex_child_environment, executable_identity,
    connectivity_evidence_is_current,
    execution_context_identity,
)
from .models import (
    AICapability, AIModel, AuthorizedWorkspace, CodexConnectivityEvidence,
    CodexInstructionPack, GuidedToolConfiguration, Installation, Provider,
    RoutingDecision, Task, User, CodexRun, utc_now,
)
from .result_intake import canonical_sha256

MINIMUM_CLI_VERSION = "0.144.4"
DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_REASONING = "xhigh"
LOCAL_VERIFIER = "deterministic-local-verification"
GUIDE_STAGES = ("Tool Setup", "Task Ready", "Pack Ready", "Pack Approved", "Run",
                "Verification", "Result Review", "Apply", "Commit", "Push", "Delivered")


def require_setup_owner(session, user: User) -> None:
    installation = session.scalar(select(Installation).order_by(Installation.id))
    owner_id = installation.owner_user_id if installation else session.scalar(select(User.id).order_by(User.id))
    if user.id != owner_id:
        raise PermissionError("Only this installation's Owner can configure its local tool.")


def require_task_owner(session, task: Task, user: User, settings) -> None:
    require_setup_owner(session, user)
    if task.owner_user_id != user.id:
        raise PermissionError("This Task does not belong to the authenticated Owner.")
    if settings.fresh_install:
        workspace = session.scalar(select(AuthorizedWorkspace).where(
            AuthorizedWorkspace.owner_user_id == user.id,
            AuthorizedWorkspace.project_id == task.project_id,
        ))
        root = settings.source_repo.resolve(strict=True)
        if workspace is None or workspace.canonical_path != str(root):
            raise PermissionError("This Task is outside the authorized workspace.")
        details = root.stat()
        if (details.st_dev, details.st_ino) != (workspace.device_id, workspace.inode):
            raise PermissionError("The authorized workspace identity changed.")


def latest_configuration(session, owner_id: int, *, confirmed: bool = False):
    query = select(GuidedToolConfiguration).where(GuidedToolConfiguration.owner_id == owner_id)
    if confirmed:
        query = query.where(GuidedToolConfiguration.confirmed_at.is_not(None))
    return session.scalar(query.order_by(GuidedToolConfiguration.id.desc()))


def delivery_location(task, settings, delivery=None) -> dict[str, Any]:
    """Owner-scoped location hints; never list or read unrelated filesystem data.

    Before Apply, filenames explicitly mentioned in Task scope are requests,
    not a claim that they were changed. After Apply the journal is authoritative.
    The caller has already checked this Task's workspace authorization.
    """
    root = settings.source_repo.resolve(strict=True)
    delivery = delivery or {}
    applied = (delivery.get("apply_session") or {}).get("session") or {}
    verification = (delivery.get("post_apply_verification") or {}).get("verification") or {}
    entries = applied.get("files") or []
    basis = "Apply journal" if entries else "Requested in Task scope; review the Candidate before Apply"
    if not entries:
        entries = [{"path": name} for name in re.findall(
            r"(?<![\w./-])(?:[\w-]+/)*[\w-]+\.[\w.-]+(?![\w/-])",
            task.implementation_scope or "",
        )]
    targets = []
    for entry in entries:
        relative = str(entry.get("path") or "")
        path = Path(relative)
        if (not relative or path.is_absolute() or any(part in {"..", ".git"} for part in path.parts)
                or any(ord(char) < 32 for char in relative)):
            continue
        absolute = root / path
        try:
            if not absolute.resolve(strict=False).is_relative_to(root):
                continue
        except (OSError, RuntimeError):
            continue
        item = {"relative_path": relative, "source_target_path": str(absolute),
                "apply_result": entry.get("apply_result")}
        if item not in targets:
            targets.append(item)
    return {"authorized_workspace": str(root), "source_repository": str(root),
            "target_basis": basis, "targets": targets,
            "apply_state": applied.get("state") or "Not applied",
            "post_apply_validation": verification.get("status") or "Not verified"}


def discovery(adapter) -> dict[str, Any]:
    """Local metadata only: version/help and the installed client's bundled list."""
    configured = adapter.settings.codex_executable or shutil.which("codex")
    try:
        supplied = Path(configured or "")
        resolved = supplied.resolve(strict=True)
        details = resolved.stat()
        trusted = bool(configured and supplied.is_absolute() and stat.S_ISREG(details.st_mode)
                       and os.access(resolved, os.X_OK) and not details.st_mode & stat.S_IWOTH
                       and not any(ord(c) < 32 for c in str(supplied)))
    except (OSError, ValueError, RuntimeError):
        trusted = False
    if not trusted:
        return {"status": "Needs Setup", "executable": None, "executable_identity": "",
                "cli_version": None, "minimum_supported_version": MINIMUM_CLI_VERSION,
                "models": [], "next_action": "Configure a safe installed Codex executable outside TWOS.",
                "provider_request_performed": False, "authentication": "Not checked",
                "catalogue_source": "installed_client_bundled_offline"}
    detected = adapter.detect()
    version_match = re.fullmatch(r"codex-cli (\d+)\.(\d+)\.(\d+)", detected.version or "")
    version = version_match.group(0) if version_match else None
    status, reason = "Needs Setup", "Install and authenticate Codex outside TWOS, then reopen Tool Setup."
    path = None
    identity = ""
    safe = False
    if detected.executable:
        try:
            candidate = Path(detected.executable)
            path = candidate.resolve(strict=True)
            details = path.stat()
            safe = (candidate.is_absolute() and stat.S_ISREG(details.st_mode)
                    and os.access(path, os.X_OK) and not details.st_mode & stat.S_IWOTH
                    and not any(ord(c) < 32 for c in str(path)))
        except (OSError, RuntimeError, ValueError):
            safe = False
    if safe and version_match:
        identity = executable_identity(str(path), cli_version=version)
        if tuple(map(int, version_match.groups())) < tuple(map(int, MINIMUM_CLI_VERSION.split('.'))):
            status, reason = "Needs Upgrade", f"Upgrade Codex explicitly to {MINIMUM_CLI_VERSION} or newer."
        elif detected.status == "configured":
            status, reason = "Not checked", "Select Check Codex Readiness. This makes one bounded provider request."
    models = []
    if status == "Not checked":
        try:
            result = subprocess.run([str(path), "debug", "models", "--bundled"],
                capture_output=True, timeout=20, env=codex_child_environment())
            if result.returncode != 0 or len(result.stdout) > 2_000_000:
                raise ValueError("Offline catalogue unavailable")
            raw = json.loads(result.stdout)
            for model in raw.get("models", [])[:256]:
                slug = model.get("slug")
                if model.get("visibility") != "list" or not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", slug):
                    continue
                efforts = [level.get("effort") for level in model.get("supported_reasoning_levels", [])
                    if isinstance(level, dict) and isinstance(level.get("effort"), str)
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", level["effort"])]
                # Ultra explicitly delegates automatically in the installed
                # client's catalogue. This guided single-Coding boundary does not.
                efforts = [effort for effort in efforts if effort != "ultra"]
                if efforts:
                    models.append({"model": slug, "reasoning_efforts": efforts})
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            reason = "Offline model metadata is unavailable. Repair the installed Codex client; no model fallback is allowed."
    return {"status": status, "executable": str(path) if safe else None,
            "executable_identity": identity, "cli_version": version,
            "minimum_supported_version": MINIMUM_CLI_VERSION, "models": models,
            "next_action": reason, "provider_request_performed": False,
            "authentication": "Not checked", "catalogue_source": "installed_client_bundled_offline"}


def verification_binding(settings) -> dict[str, Any]:
    """Seal operator-configured verifier files before approval, never UI argv."""
    command = tuple(settings.local_verification_command)
    if not command:
        raise ValueError("Configure an independent local Verification command for First Delivery.")
    executable = Path(command[0])
    if not executable.is_absolute() or not os.access(executable, os.X_OK):
        raise ValueError("The independent verifier needs an absolute executable path.")
    forbidden = tuple(Path(p).resolve(strict=False) for p in
        (settings.source_repo, settings.worktree_root, settings.codex_spool_root))
    files = []
    normalized = []
    for index, argument in enumerate(command):
        if not argument or any(ord(c) < 32 for c in argument) or len(argument) > 4096:
            raise ValueError("The independent verifier configuration is malformed.")
        path = Path(argument)
        if path.is_absolute() and path.exists():
            path = path.resolve(strict=True)
            if any(path.is_relative_to(root) for root in forbidden):
                raise ValueError("Verifier files must be outside mutable workspaces.")
            identity = _file_content_identity(path)
            if not identity:
                raise ValueError("Verifier files must be regular readable files.")
            files.append({"path": str(path), "identity": identity})
            normalized.append(str(path))
        elif index == 0:
            raise ValueError("The independent verifier is unavailable.")
        else:
            normalized.append(argument)
    return {"backend": LOCAL_VERIFIER, "argv": normalized, "files": files,
            "timeout_seconds": settings.local_verification_timeout_seconds,
            "output_limit": settings.local_verification_output_limit}


def configuration_snapshot(detected, model: str, effort: str, settings) -> dict[str, Any]:
    from .maintenance import recovery_epoch
    if detected["status"] != "Not checked":
        raise ValueError(detected["next_action"])
    entry = next((entry for entry in detected["models"] if entry["model"] == model), None)
    if entry is None:
        raise ValueError("Requested model is unavailable in the installed client's offline catalogue. No fallback is allowed.")
    if effort not in entry["reasoning_efforts"]:
        raise ValueError("Requested reasoning is not explicitly supported by the installed client.")
    return {"schema": "twos.guided_tool.v1", **({"recovery_epoch": epoch} if (epoch := recovery_epoch(settings)) else {}), "executable": detected["executable"],
            "executable_identity": detected["executable_identity"], "cli_version": detected["cli_version"],
            "requested_model": model, "reasoning_effort": effort,
            "workspace": str(settings.source_repo.resolve(strict=True)),
            "verification": verification_binding(settings),
            "execution_boundary": "isolated workspace-write; no Commit, Push, Force, tag, or delegation"}


def snapshot_is_current(snapshot: dict[str, Any], settings=None) -> bool:
    from .maintenance import recovery_epoch
    try:
        if settings is not None and snapshot.get("recovery_epoch", "") != recovery_epoch(settings):
            return False
        executable = str(snapshot["executable"])
        if executable_identity(executable) != snapshot["executable_identity"]:
            return False
        for entry in snapshot["verification"]["files"]:
            if _file_content_identity(Path(entry["path"])) != entry["identity"]:
                return False
        if settings is not None:
            detected_path = settings.codex_executable or shutil.which("codex")
            if not detected_path or str(Path(detected_path).resolve(strict=True)) != executable:
                return False
            if str(settings.source_repo.resolve(strict=True)) != snapshot["workspace"]:
                return False
            if verification_binding(settings) != snapshot["verification"]:
                return False
        return True
    except (KeyError, TypeError, OSError, ValueError, RuntimeError):
        return False


def pack_binding(pack) -> dict[str, Any] | None:
    try:
        return json.loads(pack.generation_metadata or "{}").get("guided_delivery")
    except (ValueError, TypeError):
        return None


def pack_configuration_error(session, pack, settings=None) -> str | None:
    binding = pack_binding(pack)
    if not binding:
        return None
    row = session.get(GuidedToolConfiguration, binding.get("configuration_id"))
    if row is None or row.confirmed_at is None:
        return "Tool Setup confirmation is missing. Regenerate the Pack."
    newest = latest_configuration(session, row.owner_id, confirmed=True)
    active = session.scalar(select(CodexRun.id).where(CodexRun.pack_id == pack.id,
        CodexRun.status.in_(["queued", "starting", "running", "verifying", "settling"])))
    if (row.configuration_digest != binding.get("configuration_digest")
            or newest is None or (not active and newest.configuration_digest != row.configuration_digest)
            or canonical_sha256(binding.get("snapshot")) != row.configuration_digest
            or not snapshot_is_current(binding["snapshot"], settings)):
        return "Tool configuration changed after this Pack was prepared. Regenerate and approve the Pack."
    return None


def configuration_out(session, row, *, settings=None) -> dict[str, Any] | None:
    if row is None:
        return None
    snapshot = json.loads(row.snapshot_json)
    model = session.get(AIModel, row.model_id)
    evidence = session.get(CodexConnectivityEvidence, row.connectivity_evidence_id) if row.connectivity_evidence_id else None
    current = bool(evidence and snapshot_is_current(snapshot, settings)
                   and evidence.executable_identity == snapshot["executable_identity"]
                   and evidence.execution_context_identity == execution_context_identity())
    ready = bool(current
                 and connectivity_evidence_is_current(session, owner_id=row.owner_id, model=model, evidence=evidence))
    return {"id": row.id, "model": snapshot["requested_model"], "reasoning_effort": snapshot["reasoning_effort"],
            "workspace": snapshot["workspace"],
            "confirmed": row.confirmed_at is not None, "ready": ready,
            "status": "Ready" if ready else (evidence.readiness_state if current and evidence.readiness_state != "READY_FOR_REAL_RUN" else "Needs Setup" if evidence else "Not checked"),
            "authentication": evidence.authentication_state if evidence else "Not checked",
            "last_successful_readiness_check": evidence.checked_at.isoformat() if evidence and evidence.readiness_state == "READY_FOR_REAL_RUN" else None,
            "next_action": "Save Tool Setup" if ready and row.confirmed_at is None else "Prepare First Delivery" if ready else
                evidence.safe_summary if current and evidence.readiness_state != "READY_FOR_REAL_RUN" else "Check Codex Readiness for the current configuration.",
            "advanced": {"configuration_digest": row.configuration_digest,
                         "connectivity_evidence_id": row.connectivity_evidence_id}}


def invalidate_future_packs(session, owner_id: int, digest: str) -> int:
    count = 0
    for pack in session.scalars(select(CodexInstructionPack).where(
        CodexInstructionPack.status.in_(["approval_required", "approved"]))):
        binding = pack_binding(pack)
        if binding and binding.get("owner_id") == owner_id and binding.get("configuration_digest") != digest:
            if session.scalar(select(CodexRun.id).where(CodexRun.pack_id == pack.id,
                CodexRun.status.in_(["queued", "starting", "running", "verifying", "settling"]))):
                continue
            pack.status = "invalidated"
            pack.invalidated_at = utc_now()
            count += 1
    return count


def prepare_delivery(session, task, user, settings):
    from .ai_orchestration import compose_team, recompose_model_assignments
    from .self_hosting import build_instruction_pack
    require_task_owner(session, task, user, settings)
    config = latest_configuration(session, user.id, confirmed=True)
    if config is None or not configuration_out(session, config, settings=settings)["ready"]:
        raise ValueError("Confirm Ready and Save Tool Setup before preparing First Delivery.")
    prior = session.scalar(select(CodexInstructionPack).where(CodexInstructionPack.task_id == task.id)
                           .order_by(CodexInstructionPack.version.desc()))
    if prior and prior.status in {"approved", "approval_required"} and pack_binding(prior):
        from .self_hosting import pack_routing_binding_error
        if not pack_routing_binding_error(session, task, prior, settings.source_repo):
            return prior
    if not task.development_task.strip():
        raise ValueError("Save a complete Task objective first.")
    if task.workflow_type != "product_development":
        task.workflow_type = "product_development"
        task.task_version += 1
    plan = compose_team(session, task, capability_override=["planning", "coding", "verification"])
    provider = session.scalar(select(Provider).where(Provider.name == "Independent local Verification"))
    if provider is None:
        provider = Provider(name="Independent local Verification", kind="local", enabled=True,
                            status="healthy", details="Deterministic local process; no model provider.")
        session.add(provider)
        session.flush()
    verifier = session.scalar(select(AIModel).where(AIModel.stable_id == LOCAL_VERIFIER))
    if verifier is None:
        verifier = AIModel(provider_id=provider.id, stable_id=LOCAL_VERIFIER,
            model_name="Independent local verifier", display_name="Independent local verifier (no model)",
            provider_model_id=LOCAL_VERIFIER, execution_adapter="local_verification",
            capability_tags='["verification"]', status="healthy", configuration_status="configured",
            availability_status="available", invocation_mode="real", evidence_status="unverified",
            safe_diagnostic="The approved local command verifies the result independently.")
        session.add(verifier)
        session.flush()
    routes = []
    for name in ("planning", "coding", "verification"):
        capability = session.scalar(select(AICapability).where(AICapability.name == name))
        route = RoutingDecision(task_id=task.id, team_plan_id=plan.id, capability_id=capability.id,
            requested_capabilities=plan.required_capabilities,
            selected_model_id=config.model_id if name == "coding" else verifier.id if name == "verification" else None,
            status="selected" if name != "planning" else "manual_required",
            reason="Owner-guided First Delivery; exact Coding tool and independent local Verification.",
            fallback_status="unavailable", fallback_reason="No fallback is authorized.", next_action="Review Instruction Pack")
        session.add(route)
        routes.append(route)
    session.flush()
    recompose_model_assignments(session, task, routes, team_plan=plan,
                                task_version=task.task_version, routing_source="owner_guided_delivery")
    pack = build_instruction_pack(session, task, settings.source_repo)
    snapshot = json.loads(config.snapshot_json)
    binding = {"owner_id": user.id, "configuration_id": config.id,
               "configuration_digest": config.configuration_digest, "snapshot": snapshot}
    metadata = json.loads(pack.generation_metadata)
    metadata["guided_delivery"] = binding
    pack.generation_metadata = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    pack.content += (f"\n## Guided First Delivery binding\n"
        f"- Task/version: {task.id}/{task.task_version}\n- Workspace: {snapshot['workspace']}\n"
        f"- Codex model: {snapshot['requested_model']}\n- Reasoning: {snapshot['reasoning_effort']}\n"
        f"- Tool configuration: {config.configuration_digest}\n"
        f"- Verification: independent deterministic local command; exact approved verification requirement.\n"
        f"- Execution boundary: {snapshot['execution_boundary']}\n"
        "- Do not start another agent or Verification process. TWOS runs independent Verification.\n"
        "- Leave the source repository untouched; write only inside the isolated Run workspace.\n")
    session.flush()
    return pack
