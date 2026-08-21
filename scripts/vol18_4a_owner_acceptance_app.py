from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from twos_runtime.app import create_app as create_product_app
from twos_runtime.config import Settings, get_settings
from twos_runtime.models import (
    AIModel,
    AIModelAssignment,
    AIModelInvocationEvidence,
    ApplyPlan,
    ApplySession,
    CodexInstructionPack,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
    CommitPlan,
    DeliveryCandidate,
    LocalCommitExecution,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    PostApplyVerification,
    Project,
    Provider,
    StageExecution,
    Task,
    User,
    utc_now,
)
from twos_runtime.result_intake import ingest_result_payload
from twos_runtime.self_hosting import capture_source_snapshot


TASK_TITLE = "[18.4A] Approved changes ready for Stage + Local Commit"
PACK_CONTENT = "Deterministic Phase 18.4A Owner Acceptance fixture Pack."
ROUTING_SNAPSHOT = "1" * 64
CODING_MODEL_IDENTIFIER = "fixture-phase18-4a-coding"
VERIFICATION_MODEL_IDENTIFIER = "fixture-phase18-4a-verification"
BASELINE_FILES = {
    "modify.txt": b"before modify\n",
    "delete.txt": b"delete baseline\n",
}
POSTIMAGES = {
    "created.txt": b"created by run\n",
    "modify.txt": b"after modify\n",
}


class AcceptanceFixtureError(RuntimeError):
    pass


def sanitize_acceptance_process_environment() -> tuple[str, ...]:
    """Remove inherited Git process overrides before product startup.

    The Commit Builder intentionally rejects every inherited ``GIT_*``
    variable before Stage or Commit.  Codex Desktop supplies ``GIT_PAGER``
    for its own shell, so a disposable acceptance server must start from an
    explicitly clean Git environment instead of weakening that product gate.
    """

    removed = tuple(sorted(name for name in os.environ if name.startswith("GIT_")))
    for name in removed:
        os.environ.pop(name, None)
    return removed


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _run_git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
        }
    )
    environment.pop("GIT_EXTERNAL_DIFF", None)
    command = ["git", "-c", "core.fsmonitor=false", *arguments]
    if arguments and arguments[0] == "diff":
        diff_index = command.index("diff") + 1
        command[diff_index:diff_index] = ["--no-ext-diff", "--no-textconv"]
    result = subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise AcceptanceFixtureError(result.stderr.strip() or "Fixture Git command failed.")
    return result.stdout.strip()


def _assert_no_remote(repository: Path) -> None:
    if _run_git(repository, "remote"):
        raise AcceptanceFixtureError("The acceptance fixture repository must not have a remote.")


def prepare_fixture_repository(source_repo: Path, worktree_root: Path) -> Path:
    source_repo.mkdir(parents=True, exist_ok=True)
    git_dir = source_repo / ".git"
    if not git_dir.exists():
        _run_git(source_repo, "init", "-b", "main")
        _run_git(source_repo, "config", "user.email", "twos-acceptance@example.invalid")
        _run_git(source_repo, "config", "user.name", "TWOS Acceptance")
        for relative, payload in BASELINE_FILES.items():
            (source_repo / relative).write_bytes(payload)
        (source_repo / "README.md").write_text(
            "# TWOS Phase 18.4A acceptance fixture\n",
            encoding="utf-8",
        )
        _run_git(source_repo, "add", "README.md", *sorted(BASELINE_FILES))
        _run_git(source_repo, "commit", "-m", "phase 18.4A acceptance baseline")
    if _run_git(source_repo, "branch", "--show-current") != "main":
        raise AcceptanceFixtureError("The acceptance fixture repository must remain on main.")
    if _run_git(source_repo, "status", "--porcelain", "--untracked-files=all"):
        raise AcceptanceFixtureError("The acceptance fixture baseline must be clean.")
    _assert_no_remote(source_repo)
    worktree_root.mkdir(parents=True, exist_ok=True)
    retained = worktree_root / "retained-run-worktree"
    if not retained.exists():
        _run_git(source_repo, "worktree", "add", "--detach", str(retained), "HEAD")
        (retained / "delete.txt").unlink()
        for relative, payload in POSTIMAGES.items():
            (retained / relative).write_bytes(payload)
    observed = _run_git(
        retained,
        "status",
        "--porcelain",
        "--untracked-files=all",
    ).splitlines()
    observed = [line.lstrip() for line in observed]
    expected = {"D delete.txt", "M modify.txt", "?? created.txt"}
    if set(observed) != expected:
        raise AcceptanceFixtureError(
            "The retained Run material does not contain the exact three-path fixture."
        )
    _assert_no_remote(retained)
    return retained


def _process_evidence(*, verification: bool) -> dict[str, object]:
    evidence: dict[str, object] = {
        "process_observed": True,
        "process_execution_verified": True,
        "exit_code": 0,
        "duration_ms": 4,
        "isolated_worktree": True,
        "read_only_sandbox": verification,
        "stdout_present": True,
        "stderr_present": False,
        "codex_jsonl_observed": True,
        "codex_thread_started": True,
        "codex_turn_started": True,
        "codex_turn_completed": True,
        "codex_turn_failed": False,
        "codex_turn_verified": True,
        "model_argument_observed": True,
        "model_identity_observed": False,
        "actual_model_identity_verified": False,
        "model_reroute_observed": False,
        "unsupported_model_routing_observed": False,
        "final_agent_message_observed": True,
        "approved_pack_stdin_complete": True,
        "runtime_interrupted": False,
        "jsonl_malformed_lines": 0,
        "jsonl_event_count": 4,
        "command_execution_count": 1,
        "file_change_count": 0 if verification else 3,
        "command_shape": (
            "codex exec --model <requested-model> --json --sandbox read-only"
            if verification
            else "codex exec --model <requested-model> --json --sandbox workspace-write"
        ),
        "executable_identity_fingerprint": "2" * 64,
        "process_id_fingerprint": ("d" if verification else "3") * 64,
        "thread_id_fingerprint": ("e" if verification else "4") * 64,
        "turn_id_fingerprint": ("f" if verification else "5") * 64,
    }
    if verification:
        evidence.update(
            {
                "verification_verdict_observed": True,
                "workspace_unchanged_after_verification": True,
                "changed_files_checked": True,
                "unexpected_files_checked": True,
                "exact_content_checked": True,
                "test_evidence_checked": True,
                "git_boundary_checked": True,
                "remote_boundary_checked": True,
            }
        )
    return evidence


def _manifest() -> list[dict[str, object]]:
    return [
        {
            "path": "created.txt",
            "change_type": "created",
            "before_sha256": None,
            "after_sha256": _sha256(POSTIMAGES["created.txt"]),
            "before_size": None,
            "after_size": len(POSTIMAGES["created.txt"]),
            "before_mode": None,
            "after_mode": 0o644,
            "content_kind": "text",
            "added_lines": 1,
            "removed_lines": 0,
            "changed_hunks": 1,
            "content_included": False,
        },
        {
            "path": "modify.txt",
            "change_type": "modified",
            "before_sha256": _sha256(BASELINE_FILES["modify.txt"]),
            "after_sha256": _sha256(POSTIMAGES["modify.txt"]),
            "before_size": len(BASELINE_FILES["modify.txt"]),
            "after_size": len(POSTIMAGES["modify.txt"]),
            "before_mode": 0o644,
            "after_mode": 0o644,
            "content_kind": "text",
            "added_lines": 1,
            "removed_lines": 1,
            "changed_hunks": 1,
            "content_included": False,
        },
        {
            "path": "delete.txt",
            "change_type": "deleted",
            "before_sha256": _sha256(BASELINE_FILES["delete.txt"]),
            "after_sha256": None,
            "before_size": len(BASELINE_FILES["delete.txt"]),
            "after_size": None,
            "before_mode": 0o644,
            "after_mode": None,
            "content_kind": "text",
            "added_lines": 0,
            "removed_lines": 1,
            "changed_hunks": 1,
            "content_included": False,
        },
    ]


def seed_unbound_acceptance_fixture(
    factory,
    source_repo: Path,
    retained: Path,
    *,
    task_title: str = TASK_TITLE,
) -> None:
    baseline = capture_source_snapshot(source_repo, hardened_read_only=True)
    post_run = capture_source_snapshot(retained, hardened_read_only=True)
    records = _manifest()
    changed_files = [str(record["path"]) for record in records]
    result: dict[str, Any] = {
        "changed_files": changed_files,
        "changed_file_evidence": [
            {
                "path": record["path"],
                "before_sha256": record["before_sha256"],
                "after_sha256": record["after_sha256"],
                "before_size": record["before_size"],
                "after_size": record["after_size"],
                "before_mode": record["before_mode"],
                "after_mode": record["after_mode"],
                "before_deleted": record["before_sha256"] is None,
                "after_deleted": record["after_sha256"] is None,
            }
            for record in records
        ],
        "sanitized_diff_evidence": {
            "schema": "twos.sanitized_diff.v1",
            "content_included": False,
            "records": records,
            "record_count": 3,
            "truncated": False,
        },
        "unexpected_excluded_artifacts": [],
        "source_snapshot_digest": baseline["digest"],
        "post_run_snapshot_digest": post_run["digest"],
        "coding_prompt_digest": _sha256(PACK_CONTENT.encode()),
        "coding_process": {
            "status": "completed",
            "process_started": True,
            "exit_code": 0,
            "timed_out": False,
            "cancelled": False,
            "failure": "",
        },
        "coding_invocation": {
            "process_execution_verified": True,
            "codex_turn_verified": True,
            "approved_prompt_delivery_complete": True,
            "requested_model": CODING_MODEL_IDENTIFIER,
            "actual_resolved_model": None,
            "actual_model_identity_verified": False,
            "failure": "",
        },
        "run_produced_changes": {
            "status": "changes",
            "changed_files": changed_files,
            "unexpected_files": [],
        },
        "git_evidence": {"status": "passed", "failure": ""},
        "task_acceptance": {
            "status": "passed",
            "reason": "The independent Verification verdict passed.",
        },
        "verification_process": {
            "status": "completed",
            "process_started": True,
            "process_exit": 0,
            "turn_terminal_state": "completed",
            "failure": "",
        },
        "verification": {
            "status": "completed",
            "summary": "Independent Verification completed.",
            "unexpected_files": [],
        },
        "verification_invocation": {
            "process_execution_verified": True,
            "codex_turn_verified": True,
            "requested_model": VERIFICATION_MODEL_IDENTIFIER,
            "actual_resolved_model": None,
            "actual_model_identity_verified": False,
            "failure": "",
        },
        "verification_verdict": {
            "status": "passed",
            "passed_checks": [
                "verification_verdict_observed",
                "workspace_unchanged_after_verification",
                "changed_files_checked",
                "unexpected_files_checked",
                "exact_content_checked",
                "test_evidence_checked",
                "git_boundary_checked",
                "remote_boundary_checked",
            ],
            "failed_checks": [],
        },
        "validation": {"diff_check": True, "no_excluded_artifacts": True},
        "boundary_confirmation": {
            "isolated_worktree": True,
            "source_main_unchanged": True,
            "merge_commits_created": False,
            "remote_state_observed": True,
            "remote_state_unchanged": True,
            "git_transport_protocols_allowed": False,
            "codex_tool_network_access_allowed": False,
            "automatic_merge": False,
            "automatic_push": False,
        },
        "commits": [],
    }
    with factory() as session:
        if session.scalar(select(Task).where(Task.title == task_title)) is not None:
            return
        if session.scalar(select(func.count()).select_from(User)) != 0:
            raise AcceptanceFixtureError("Acceptance fixture must be seeded before Sign up.")
        project = session.scalar(select(Project).where(Project.key == "twos"))
        if project is None:
            raise AcceptanceFixtureError("The TWOS project seed is unavailable.")
        task = Task(
            project_id=project.id,
            title=task_title,
            development_task="Create, modify, and delete the three approved fixture paths.",
            workflow_type="product_development",
            objective="Complete the explicit Review, Stage, and Local Commit Owner journey.",
            implementation_scope="Only created.txt, modify.txt, and delete.txt.",
            forbidden_scope="No Push, merge, rebase, tag, remote change, trading, or betting.",
            required_output="One immutable Commit Plan, exact Stage, and one local Commit.",
            acceptance_target="Three explicit Owner actions with no Push.",
            repository_identity=source_repo.name,
            source_baseline_commit=str(baseline["head_sha"]),
            task_version=1,
            status="accepted",
            acceptance_state="accepted",
        )
        session.add(task)
        session.flush()
        provider = Provider(
            name="Phase 18.4A acceptance fixture provider",
            kind="model",
            status="healthy",
            enabled=True,
            details="Persisted local acceptance evidence; never invoked.",
        )
        session.add(provider)
        session.flush()
        coding_model = AIModel(
            provider_id=provider.id,
            model_name="Phase 18.4A Coding fixture",
            stable_id="phase18.4a.fixture.coding",
            display_name="Phase 18.4A Coding fixture",
            provider_model_id=CODING_MODEL_IDENTIFIER,
            execution_adapter="codex_cli",
            capability_tags='["coding"]',
            status="healthy",
            configuration_status="configured",
            availability_status="available",
            invocation_mode="real",
            last_invocation_outcome="succeeded",
            evidence_status="verified",
            evidence_source="invocation_evidence",
            routing_priority=10,
        )
        verification_model = AIModel(
            provider_id=provider.id,
            model_name="Phase 18.4A Verification fixture",
            stable_id="phase18.4a.fixture.verification",
            display_name="Phase 18.4A Verification fixture",
            provider_model_id=VERIFICATION_MODEL_IDENTIFIER,
            execution_adapter="codex_cli",
            capability_tags='["verification"]',
            status="healthy",
            configuration_status="configured",
            availability_status="available",
            invocation_mode="real",
            last_invocation_outcome="succeeded",
            evidence_status="verified",
            evidence_source="invocation_evidence",
            routing_priority=20,
        )
        session.add_all([coding_model, verification_model])
        session.flush()
        coding_assignment = AIModelAssignment(
            task_id=task.id,
            task_version=1,
            assignment_version=1,
            role="coding",
            capability="coding",
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            assigned_model_id=coding_model.id,
            availability_at_composition="available",
            independence_required=False,
            independence_status="not_required",
        )
        verification_assignment = AIModelAssignment(
            task_id=task.id,
            task_version=1,
            assignment_version=1,
            role="verification",
            capability="verification",
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            assigned_model_id=verification_model.id,
            availability_at_composition="available",
            independence_required=True,
            independence_status="independent",
            independent_from_roles='["coding"]',
        )
        session.add_all([coding_assignment, verification_assignment])
        session.flush()
        pack = CodexInstructionPack(
            task_id=task.id,
            version=1,
            status="approved",
            content=PACK_CONTENT,
            stage_summary="Coding then independent Verification.",
            key_boundaries="No automatic Apply, Stage, Commit, or Push.",
            acceptance_target=task.acceptance_target,
            source_baseline_commit=str(baseline["head_sha"]),
            development_task=task.development_task,
            development_task_digest=_sha256(task.development_task.encode()),
            assignment_version=1,
            task_version=1,
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            source_snapshot_digest=str(baseline["digest"]),
            source_snapshot_json=json.dumps(baseline, sort_keys=True, separators=(",", ":")),
            routing_decision_ids="[]",
            generation_metadata=json.dumps(
                {
                    "source_snapshot": {
                        "schema": baseline["schema"],
                        "head_sha": baseline["head_sha"],
                        "digest": baseline["digest"],
                        "included_manifest": baseline["included_manifest"],
                    },
                    "model_routing_snapshot": {
                        "routing_snapshot_hash": ROUTING_SNAPSHOT,
                        "assignment_version": 1,
                        "task_version": 1,
                        "assignments": [
                            {"capability": "coding"},
                            {"capability": "verification"},
                        ],
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            approved_by_user_id=None,
            approved_at=utc_now(),
        )
        session.add(pack)
        session.flush()
        result.update(
            {
                "task_id": task.id,
                "task_version": task.task_version,
                "development_task_digest": pack.development_task_digest,
                "pack_version": pack.version,
                "source_snapshot_digest": pack.source_snapshot_digest,
                "pre_run_commit": pack.source_baseline_commit,
            }
        )
        run = CodexRun(
            task_id=task.id,
            pack_id=pack.id,
            status="completed",
            executable_status="configured",
            source_repo=str(source_repo),
            source_branch="main",
            source_commit=str(baseline["head_sha"]),
            development_task=task.development_task,
            development_task_digest=pack.development_task_digest,
            assignment_version=1,
            task_version=1,
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            source_snapshot_digest=str(baseline["digest"]),
            execution_assignment_id=coding_assignment.id,
            execution_model_id=coding_model.id,
            execution_provider_id=provider.id,
            requested_model_identifier=CODING_MODEL_IDENTIFIER,
            verification_assignment_id=verification_assignment.id,
            verification_model_id=verification_model.id,
            verification_provider_id=provider.id,
            verification_model_identifier=VERIFICATION_MODEL_IDENTIFIER,
            verification_status="completed",
            verification_summary="Independent Verification passed.",
            verification_process_spawned=True,
            verification_exit_code=0,
            process_spawned=True,
            worktree_path=str(retained),
            worktree_branch="twos/run-phase18-4a-acceptance-fixture",
            structured_result=json.dumps(result, sort_keys=True, separators=(",", ":")),
            owner_summary="Coding and independent Verification completed.",
            exit_code=0,
            started_at=utc_now(),
            finished_at=utc_now(),
        )
        session.add(run)
        session.flush()
        result["identity"] = {
            "run_id": run.id,
            "task_id": run.task_id,
            "task_version": run.task_version,
            "pack_id": run.pack_id,
            "pack_version": pack.version,
            "coding_assignment_id": run.execution_assignment_id,
            "coding_assignment_version": coding_assignment.assignment_version,
            "verification_assignment_id": run.verification_assignment_id,
            "verification_assignment_version": (
                verification_assignment.assignment_version
            ),
            "routing_snapshot_identity": run.routing_snapshot_hash,
            "source_snapshot_identity": run.source_snapshot_digest,
        }
        run.structured_result = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        )
        common_provider_evidence = {
            "provider_response_observed": False,
            "requested_model_identifier_match": True,
        }
        coding_evidence = AIModelInvocationEvidence(
            invocation_ref=f"phase18-4a-run-{run.id}-coding",
            capability="coding",
            assignment_version=1,
            configured_model_id=coding_model.id,
            configured_provider_id=provider.id,
            assignment_id=coding_assignment.id,
            task_id=task.id,
            codex_run_id=run.id,
            actual_invoked_model_identifier="",
            invocation_mode="real",
            outcome="succeeded",
            process_evidence=json.dumps(_process_evidence(verification=False), sort_keys=True, separators=(",", ":")),
            provider_evidence=json.dumps(common_provider_evidence, sort_keys=True, separators=(",", ":")),
            request_fingerprint="8" * 64,
            response_fingerprint="9" * 64,
            duration_ms=4,
            diagnostic_code="coding_structured_evidence_verified",
            safe_summary="Controlled persisted Coding evidence.",
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        verification_evidence = AIModelInvocationEvidence(
            invocation_ref=f"phase18-4a-run-{run.id}-verification",
            capability="verification",
            assignment_version=1,
            configured_model_id=verification_model.id,
            configured_provider_id=provider.id,
            assignment_id=verification_assignment.id,
            task_id=task.id,
            codex_run_id=run.id,
            actual_invoked_model_identifier="",
            invocation_mode="real",
            outcome="succeeded",
            process_evidence=json.dumps(_process_evidence(verification=True), sort_keys=True, separators=(",", ":")),
            provider_evidence=json.dumps(common_provider_evidence, sort_keys=True, separators=(",", ":")),
            request_fingerprint="a" * 64,
            response_fingerprint="b" * 64,
            duration_ms=4,
            diagnostic_code="verification_structured_evidence_verified",
            safe_summary="Controlled persisted independent Verification evidence.",
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        session.add_all([coding_evidence, verification_evidence])
        session.flush()
        acceptance = OwnerAcceptanceSession(
            task_id=task.id,
            codex_run_id=run.id,
            status="accepted",
            owner_note="Accepted deterministic prerequisite evidence.",
            compact_sync_result="Accepted; no merge or Push.",
            decided_by_user_id=None,
            decided_at=utc_now(),
        )
        session.add(acceptance)
        session.flush()
        session.add(
            OwnerAcceptanceItem(
                session_id=acceptance.id,
                key="phase18_4a_fixture",
                label="Phase 18.4A prerequisite evidence",
                inspect_target="Persisted Run evidence",
                ui_path="Result",
                pass_standard="Exact Coding and Verification evidence is complete.",
                required=True,
                status="pass",
                ordinal=0,
            )
        )
        session.commit()


def bind_fixture_to_owner(factory, *, task_title: str = TASK_TITLE) -> None:
    with factory() as session:
        owner = session.scalar(select(User).order_by(User.id))
        task = session.scalar(select(Task).where(Task.title == task_title))
        if owner is None or task is None:
            raise AcceptanceFixtureError("Owner or acceptance Task is unavailable.")
        pack = session.scalar(
            select(CodexInstructionPack).where(CodexInstructionPack.task_id == task.id)
        )
        acceptance = session.scalar(
            select(OwnerAcceptanceSession).where(OwnerAcceptanceSession.task_id == task.id)
        )
        run = session.scalar(select(CodexRun).where(CodexRun.task_id == task.id))
        if pack is None or acceptance is None or run is None:
            raise AcceptanceFixtureError("Acceptance prerequisites are incomplete.")
        if pack.approved_by_user_id not in {None, owner.id}:
            raise AcceptanceFixtureError("Acceptance Pack is bound to another Owner.")
        if acceptance.decided_by_user_id not in {None, owner.id}:
            raise AcceptanceFixtureError("Acceptance evidence is bound to another Owner.")
        pack.approved_by_user_id = owner.id
        acceptance.decided_by_user_id = owner.id
        try:
            payload = json.loads(run.structured_result)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AcceptanceFixtureError(
                "The terminal acceptance result is unavailable."
            ) from exc
        ingest_result_payload(
            session,
            owner.id,
            run,
            payload,
            result_source="acceptance_fixture",
            require_explicit_identity=True,
        )
        session.commit()


def fixture_health(factory, source_repo: Path, retained: Path) -> dict[str, Any]:
    with factory() as session:
        task = session.scalar(select(Task).where(Task.title == TASK_TITLE))
        counts = {
            "owners": session.scalar(select(func.count()).select_from(User)),
            "result_monitors": session.scalar(
                select(func.count()).select_from(CodexRunMonitor)
            ),
            "result_envelopes": session.scalar(
                select(func.count()).select_from(CodexResultEnvelope)
            ),
            "candidates": session.scalar(select(func.count()).select_from(DeliveryCandidate)),
            "apply_plans": session.scalar(select(func.count()).select_from(ApplyPlan)),
            "apply_sessions": session.scalar(select(func.count()).select_from(ApplySession)),
            "verifications": session.scalar(
                select(func.count()).select_from(PostApplyVerification)
            ),
            "commit_plans": session.scalar(select(func.count()).select_from(CommitPlan)),
            "stage_records": session.scalar(select(func.count()).select_from(StageExecution)),
            "commit_records": session.scalar(
                select(func.count()).select_from(LocalCommitExecution)
            ),
        }
    branch = _run_git(source_repo, "branch", "--show-current")
    staged = [
        item
        for item in _run_git(
            source_repo, "diff", "--cached", "--name-only"
        ).splitlines()
        if item
    ]
    remotes = [item for item in _run_git(source_repo, "remote").splitlines() if item]
    retained_status = {
        item.lstrip()
        for item in _run_git(
            retained, "status", "--porcelain", "--untracked-files=all"
        ).splitlines()
        if item
    }
    expected_status = {"D delete.txt", "M modify.txt", "?? created.txt"}
    ready = bool(
        task is not None
        and branch == "main"
        and not staged
        and not remotes
        and retained_status == expected_status
    )
    return {
        "status": "healthy" if ready else "blocked",
        "ready": ready,
        "task": {"title": task.title if task is not None else None},
        "counts": counts,
        "repository": {
            "branch": branch,
            "staged_paths": staged,
            "remote_count": len(remotes),
            "approved_operations": {"CREATE": 1, "MODIFY": 1, "DELETE": 1},
        },
        "scheduler": "disabled",
        "automatic_actions": {
            "plan": False,
            "apply": False,
            "stage": False,
            "commit": False,
        },
    }


def create_app(settings: Settings | None = None, start_scheduler: bool = False):
    removed_git_environment = sanitize_acceptance_process_environment()
    settings = settings or get_settings()
    retained = prepare_fixture_repository(settings.source_repo, settings.worktree_root)
    app = create_product_app(settings=settings, start_scheduler=start_scheduler)
    seed_unbound_acceptance_fixture(
        app.state.session_factory,
        settings.source_repo,
        retained,
    )

    @app.get("/fixture-health")
    def acceptance_fixture_health() -> dict[str, Any]:
        health = fixture_health(
            app.state.session_factory,
            settings.source_repo,
            retained,
        )
        health["process_environment"] = {
            "inherited_git_overrides_removed": list(removed_git_environment),
            "git_overrides_present": sorted(
                name for name in os.environ if name.startswith("GIT_")
            ),
        }
        return health

    @app.middleware("http")
    async def bind_owner_acceptance_fixture(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/api/auth/signup" and response.status_code == 201:
            try:
                bind_fixture_to_owner(app.state.session_factory)
            except AcceptanceFixtureError:
                return JSONResponse(
                    status_code=500,
                    content={
                        "code": "OWNER_ACCEPTANCE_FIXTURE_BIND_FAILED",
                        "message": "The Owner Acceptance fixture could not be prepared.",
                    },
                )
        return response

    return app
