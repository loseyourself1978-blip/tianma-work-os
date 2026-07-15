from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AITeamPlan,
    CodexInstructionPack,
    CodexRun,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    RoutingDecision,
    Task,
    utc_now,
)


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
    plan, routes = latest_ai_context(session, task.id)
    if not plan:
        raise ValueError("Compose the AI Team before generating a Codex Instruction Pack.")

    source = git_source_state(source_repo)
    baseline = task.source_baseline_commit or str(source["commit"])
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
- Workflow: product_development
- Task: {task.title}

## Goal
{task.objective or task.title}

## Product Intent
{task.source_sync_summary or 'Use the persisted TWOS task context.'}

## AI Team Plan
- Capabilities: {', '.join(capabilities)}
- Team reason: {plan.explanation}
- Routing evaluation: {'; '.join(route_states) or 'No routing records.'}

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
- Stop if the source baseline differs or the configured execution source is dirty before worktree creation.
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
        ai_team_plan_id=plan.id,
        routing_decision_ids=json.dumps([route.id for route in routes], separators=(",", ":")),
        generation_metadata=json.dumps(
            {
                "builder": "deterministic_full_stage_pack_v1",
                "source_branch": source["branch"],
                "source_clean": source["clean"],
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
            "Vol.16 Productization Sprint 1 Compact Sync",
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
