from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import AuditEvent, Schedule, utc_now
from .workers import run_task


def compute_next_run(interval_seconds: int):
    return utc_now() + timedelta(seconds=max(interval_seconds, 1))


def run_due_schedules(session: Session) -> list[int]:
    now = utc_now()
    due = session.scalars(
        select(Schedule).where(Schedule.paused == False, Schedule.next_run_at != None, Schedule.next_run_at <= now)  # noqa: E711,E712
    ).all()
    run_ids: list[int] = []
    for schedule in due:
        try:
            run = run_task(session, schedule.task_id, "compact_sync", request_id="scheduler")
            run_ids.append(run.id)
            schedule.last_run_at = now
            schedule.next_run_at = compute_next_run(schedule.interval_seconds)
            session.add(
                AuditEvent(
                    action="schedule_run_completed",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    request_id="scheduler",
                    details=f"task_run={run.id}",
                )
            )
        except Exception as exc:
            schedule.last_run_at = now
            schedule.next_run_at = compute_next_run(schedule.interval_seconds)
            session.add(
                AuditEvent(
                    action="schedule_run_failed",
                    entity_type="schedule",
                    entity_id=schedule.id,
                    request_id="scheduler",
                    details=str(exc),
                )
            )
    session.flush()
    return run_ids


class RuntimeScheduler:
    def __init__(self, factory: sessionmaker[Session], poll_seconds: float = 1.0) -> None:
        self.factory = factory
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def _loop(self) -> None:
        while not self._stop.is_set():
            with self.factory() as session:
                run_due_schedules(session)
                session.commit()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
