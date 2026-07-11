from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .models import AcceptanceCheck, AuditEvent, SyncEntry, Task, TaskRun, utc_now
from .policy import evaluate_action


ACCEPTANCE_ENGINE = "deterministic_compact_sync_v1"


def build_compact_sync(task: Task) -> str:
    project_name = task.project.name if task.project else f"project:{task.project_id}"
    return "\n".join(
        [
            "Vol.15 MVP-14 Sync: compact_sync executed by TWOS local runtime.",
            f"Project: {project_name}",
            f"Task: {task.title}",
            f"Action: {task.task_type}",
            f"Source Sync: {task.source_sync_summary}",
            f"Required Output: {task.required_output}",
            f"Boundary Risk: {task.boundary_risk}",
            "Policy: backend/API/auth/scheduler/persistence are active local runtime foundations; external providers/tools remain unconfigured until verified.",
            "Blocked: live_trade, live_bet, broker_order, and betting_order.",
        ]
    )


def deterministic_checks(task: Task, result: str) -> list[dict[str, str | bool]]:
    blocked_tokens = ["live_trade", "live_bet", "broker_order", "betting_order"]
    boundary_passed = all(token in result for token in blocked_tokens)
    boundary_passed = boundary_passed and "order placed" not in result.lower() and "wager placed" not in result.lower()
    return [
        {
            "id": "required_output_generated",
            "label": "Required output generated",
            "passed": bool(task.required_output.strip()) and task.required_output in result,
        },
        {
            "id": "boundary_check_passed",
            "label": "Boundary check passed",
            "passed": boundary_passed,
        },
        {
            "id": "result_persisted",
            "label": "Result persisted",
            "passed": bool(result) and task.compact_sync_result == result,
        },
    ]


def deterministic_acceptance(task: Task, result: str) -> tuple[str, str, list[dict[str, str | bool]]]:
    checks = deterministic_checks(task, result)
    failed = [str(check["id"]) for check in checks if not check["passed"]]
    if failed:
        return "needs_review", "Deterministic checks failed: " + ", ".join(failed), checks
    return "accepted", "All deterministic checks passed.", checks


def serialize_acceptance(reason: str, checks: list[dict[str, str | bool]]) -> str:
    return json.dumps(
        {"engine": ACCEPTANCE_ENGINE, "reason": reason, "checks": checks},
        ensure_ascii=True,
        separators=(",", ":"),
    )


def parse_acceptance(reason: str) -> dict[str, object]:
    try:
        payload = json.loads(reason)
    except (TypeError, json.JSONDecodeError):
        return {"engine": "legacy_deterministic_compact_sync", "reason": reason, "checks": []}
    if not isinstance(payload, dict):
        return {"engine": "legacy_deterministic_compact_sync", "reason": reason, "checks": []}
    return {
        "engine": payload.get("engine", ACCEPTANCE_ENGINE),
        "reason": payload.get("reason", reason),
        "checks": payload.get("checks", []),
    }


def run_task(session: Session, task_id: int, action: str = "compact_sync", actor_user_id: int | None = None, request_id: str | None = None) -> TaskRun:
    decision = evaluate_action(action)
    if not decision.allowed:
        session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                action="policy_denied",
                entity_type="task",
                entity_id=task_id,
                request_id=request_id,
                details=decision.reason,
            )
        )
        session.flush()
        raise PermissionError(decision.reason)

    task = session.get(Task, task_id)
    if not task:
        raise LookupError("Task not found.")

    now = utc_now()
    task.status = "queued"
    run = TaskRun(task_id=task.id, action=action, status="queued", created_at=now)
    session.add(run)
    session.flush()

    try:
        task.status = "running"
        run.status = "running"
        run.started_at = utc_now()
        result = build_compact_sync(task)
        run.result = result
        task.compact_sync_result = result
        task.status = "review"
        session.add(SyncEntry(project_id=task.project_id, summary=f"compact_sync for task {task.id}", result=result))

        acceptance_status, reason, checks = deterministic_acceptance(task, result)
        task.acceptance_state = acceptance_status
        task.status = "accepted" if acceptance_status == "accepted" else "needs_review"
        run.status = task.status
        run.finished_at = utc_now()
        session.add(
            AcceptanceCheck(
                task_id=task.id,
                run_id=run.id,
                status=acceptance_status,
                reason=serialize_acceptance(reason, checks),
            )
        )
        session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                action="task_run_completed",
                entity_type="task_run",
                entity_id=run.id,
                request_id=request_id,
                details=f"{action}: {acceptance_status}; {reason}",
            )
        )
    except Exception as exc:
        task.status = "failed"
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utc_now()
        session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                action="task_run_failed",
                entity_type="task_run",
                entity_id=run.id,
                request_id=request_id,
                details=str(exc),
            )
        )
        raise
    finally:
        session.flush()
    return run
