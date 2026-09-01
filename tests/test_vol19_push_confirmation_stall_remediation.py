from __future__ import annotations

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session as ORMSession

from tests.test_vol18_push_delivery import (
    _confirm_payload as _legacy_confirm_payload,
    _confirm_url as _legacy_confirm_url,
    _preflight_url as _legacy_preflight_url,
    push_ready_fixture,
)
from tests.test_vol19_owner_commit_push_delivery import (
    _bare_ref,
    _bare_refs,
    _canonical_applied_delivery,
    _commit_delivery,
    _git,
)
from twos_runtime.apply_sessions import (
    _repository_mutation_lock,
    _repository_observation_lock,
)
from twos_runtime.models import AuditEvent, PushExecution, PushPlan, PushPlanApproval
from twos_runtime.push_delivery import PushDeliveryError
import twos_runtime.push_delivery as push_delivery_service


@pytest.fixture(autouse=True)
def _clear_inherited_git_process_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _review_and_approve_push(fixture, commit: dict) -> tuple[dict, dict]:
    reviewed = fixture.client.post(
        f"/api/local-commits/{commit['id']}/push-plans",
        headers=fixture.headers,
        json={},
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()["push_plan"]
    assert reviewed.json()["confirmation"]["state"] == "blocked"
    assert reviewed.json()["confirmation"]["reason"] == (
        "Approve this exact Push Plan before final confirmation."
    )
    assert reviewed.json()["confirmation"]["request_identity"] is None
    approved = fixture.client.post(
        f"/api/push-plans/{plan['id']}/approvals",
        headers=fixture.headers,
        json={
            "confirmation": "APPROVE_PUSH_PLAN",
            "expected_plan_digest": plan["advanced"]["plan_digest"],
            "expected_plan_version": plan["version"],
        },
    )
    assert approved.status_code == 200, approved.text
    approval = approved.json()["push_approval"]
    approval["request_identity"] = approved.json()["confirmation"][
        "request_identity"
    ]
    return plan, approval


def _confirm_payload(plan: dict, approval: dict) -> dict[str, str]:
    return {
        "confirmation": "PUSH_TO_ORIGIN_MAIN",
        "expected_plan_digest": plan["advanced"]["plan_digest"],
        "expected_approval_digest": approval["advanced"]["approval_digest"],
        "request_identity": approval["request_identity"],
    }


def test_shared_observations_coexist_and_final_push_waits_then_projects_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path, unrelated=True) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        delivery_commit = str(commit["commit_oid"])
        plan, approval = _review_and_approve_push(fixture, commit)
        mismatched_identity = _confirm_payload(plan, approval)
        mismatched_identity["request_identity"] = "0" * 64
        rejected_identity = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=mismatched_identity,
        )
        assert rejected_identity.status_code == 409, rejected_identity.text
        rejected_details = rejected_identity.json()["error"]["details"]
        assert rejected_details["code"] == "PUSH_REQUEST_IDENTITY_CHANGED"
        assert rejected_details["request_accepted"] is False
        assert rejected_details["remote_effect"] == "none"
        assert rejected_details["retry_safe"] is False
        with fixture.factory() as session:
            stored_plan = session.scalar(
                select(PushPlan).where(PushPlan.push_plan_id == plan["id"])
            )
            assert stored_plan is not None
            repository_fingerprint = stored_plan.repository_locator_fingerprint

        observation_acquired = threading.Event()
        release_observation = threading.Event()
        observation_errors: list[BaseException] = []

        def hold_observation() -> None:
            try:
                with _repository_observation_lock(repository_fingerprint):
                    observation_acquired.set()
                    assert release_observation.wait(timeout=10)
            except BaseException as exc:  # pragma: no cover - surfaced below
                observation_errors.append(exc)
                observation_acquired.set()

        holder = threading.Thread(target=hold_observation, daemon=True)
        holder.start()
        assert observation_acquired.wait(timeout=10)
        assert not observation_errors
        # A second read-only projection shares the repository observation
        # boundary instead of creating a false reader-vs-reader conflict.
        with _repository_observation_lock(repository_fingerprint):
            pass

        original_push = push_delivery_service._run_standard_push
        transport_started = threading.Event()
        release_transport = threading.Event()
        observed_refspecs: list[str] = []

        def held_push(root: Path, refspec: str):
            observed_refspecs.append(refspec)
            transport_started.set()
            assert release_transport.wait(timeout=10)
            return original_push(root, refspec)

        monkeypatch.setattr(push_delivery_service, "_run_standard_push", held_push)
        original_repository_lock = push_delivery_service._push_repository_lock
        original_session_rollback = ORMSession.rollback
        exclusive_admissions: list[tuple[int, str]] = []
        admission_transaction_states: list[bool] = []
        admission_counts: dict[int, int] = {}
        admissions_guard = threading.Lock()
        first_admission_entered = threading.Event()
        replay_admission_entered = threading.Event()
        rollback_sessions = threading.local()

        def track_request_rollback(db_session: ORMSession) -> None:
            original_session_rollback(db_session)
            rollback_sessions.latest = db_session

        monkeypatch.setattr(ORMSession, "rollback", track_request_rollback)

        @contextmanager
        def single_admission_lock(
            fingerprint: str,
            *,
            observation: bool = False,
            wait_timeout_seconds: float = 0.0,
        ):
            if not observation and wait_timeout_seconds > 0:
                assert wait_timeout_seconds == (
                    push_delivery_service.PUSH_FINAL_LOCK_WAIT_SECONDS
                )
                thread_id = threading.get_ident()
                request_session = getattr(rollback_sessions, "latest", None)
                assert request_session is not None, (
                    "Final Push admission must end its request transaction "
                    "before entering the repository lock."
                )
                admission_transaction_states.append(
                    request_session.in_transaction()
                )
                assert request_session.in_transaction() is False, (
                    "Final Push admission retained an active SQLAlchemy "
                    "transaction while entering the repository lock."
                )
                with admissions_guard:
                    exclusive_admissions.append((thread_id, fingerprint))
                    admission_counts[thread_id] = (
                        admission_counts.get(thread_id, 0) + 1
                    )
                    assert admission_counts[thread_id] == 1, (
                        "Each final request must hold one continuous exclusive "
                        "repository lock from admission through transport."
                    )
                    if len(exclusive_admissions) == 1:
                        first_admission_entered.set()
                    elif len(exclusive_admissions) == 2:
                        replay_admission_entered.set()
            with original_repository_lock(
                fingerprint,
                observation=observation,
                wait_timeout_seconds=wait_timeout_seconds,
            ):
                yield

        monkeypatch.setattr(
            push_delivery_service,
            "_push_repository_lock",
            single_admission_lock,
        )
        concurrent = TestClient(fixture.client.app)
        concurrent.cookies.update(fixture.client.cookies)
        observer = TestClient(fixture.client.app)
        observer.cookies.update(fixture.client.cookies)
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                push_future = executor.submit(
                    fixture.client.post,
                    f"/api/push-plans/{plan['id']}/push-attempts",
                    headers=fixture.headers,
                    json=_confirm_payload(plan, approval),
                )
                assert first_admission_entered.wait(timeout=10), (
                    "Final Push did not reach bounded repository admission."
                )
                assert not push_future.done(), (
                    "Final Push admission must wait briefly for an active "
                    "read-only observation instead of returning a false 409."
                )
                release_observation.set()
                assert transport_started.wait(timeout=10)

                running = observer.get(
                    f"/api/local-commits/{commit['id']}/push-plans",
                    headers=fixture.headers,
                )
                assert running.status_code == 200, running.text
                assert running.json()["push_execution"]["state"] == "PUSHING"
                assert running.json()["confirmation"] == {
                    "state": "running",
                    "in_progress": True,
                    "can_confirm": False,
                    "request_accepted": True,
                    "reason": None,
                    "progress": "Push execution is running independently of this dialog.",
                    "plan_id": plan["id"],
                    "request_identity": approval["request_identity"],
                    "execution_id": running.json()["push_execution"]["id"],
                }

                replay_future = executor.submit(
                    concurrent.post,
                    f"/api/push-plans/{plan['id']}/push-attempts",
                    headers=fixture.headers,
                    json=_confirm_payload(plan, approval),
                )
                assert replay_admission_entered.wait(timeout=10), (
                    "Concurrent replay did not reach repository admission."
                )
                assert not replay_future.done(), (
                    "A concurrent replay must wait behind the accepted Push "
                    "without holding SQLite's writer lock."
                )
                release_transport.set()
                pushed = push_future.result(timeout=20)
                concurrent_replay = replay_future.result(timeout=20)
        finally:
            release_observation.set()
            release_transport.set()
            holder.join(timeout=10)
            concurrent.close()
            observer.close()
            assert not holder.is_alive(), (
                "The shared repository-lock holder survived test teardown."
            )

        assert not observation_errors
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["confirmation"]["state"] == "succeeded"
        assert pushed.json()["push_execution"]["state"] == "PUSHED"
        assert pushed.json()["push_execution"]["remote_receipt_verified"] is True
        assert concurrent_replay.status_code == 200, concurrent_replay.text
        assert concurrent_replay.json()["push_replayed"] is True
        assert concurrent_replay.json()["confirmation"]["state"] == "succeeded"
        assert len(exclusive_admissions) == 2
        assert {fingerprint for _, fingerprint in exclusive_admissions} == {
            repository_fingerprint
        }
        assert sorted(admission_counts.values()) == [1, 1]
        assert admission_transaction_states == [False, False]
        assert observed_refspecs == [f"{delivery_commit}:refs/heads/main"]
        assert _bare_ref(fixture.origin) == delivery_commit
        assert _bare_refs(fixture.origin) == [f"refs/heads/main {delivery_commit}"]
        assert _git(fixture.source_repo, "tag", "--list") == ""

        monkeypatch.setattr(
            push_delivery_service,
            "_push_repository_lock",
            original_repository_lock,
        )
        replayed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["push_replayed"] is True
        assert replayed.json()["confirmation"]["state"] == "succeeded"
        assert observed_refspecs == [f"{delivery_commit}:refs/heads/main"]
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 1


def test_legacy_confirmation_rejects_occupied_repository_lock_without_db_writer_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with push_ready_fixture(tmp_path) as fixture:
        preflight = fixture.client.post(_legacy_preflight_url(fixture))
        assert preflight.status_code == 200, preflight.text
        push_execution = preflight.json()["push_execution"]
        with fixture.factory() as session:
            stored = session.scalar(
                select(PushExecution).where(
                    PushExecution.push_execution_id == push_execution["id"]
                )
            )
            assert stored is not None
            repository_fingerprint = stored.repository_locator_fingerprint

        repository_held = threading.Event()
        release_repository = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_repository() -> None:
            try:
                with _repository_mutation_lock(repository_fingerprint):
                    repository_held.set()
                    assert release_repository.wait(timeout=10)
            except BaseException as exc:  # pragma: no cover - surfaced below
                holder_errors.append(exc)
                repository_held.set()

        holder = threading.Thread(target=hold_repository, daemon=True)
        holder.start()
        assert repository_held.wait(timeout=10)
        assert not holder_errors

        original_repository_lock = push_delivery_service._push_repository_lock
        legacy_admission_entered = threading.Event()
        legacy_admission_finished = threading.Event()
        observed_waits: list[float] = []

        @contextmanager
        def observe_legacy_admission(
            fingerprint: str,
            *,
            observation: bool = False,
            wait_timeout_seconds: float = 0.0,
        ):
            if not observation:
                observed_waits.append(wait_timeout_seconds)
                assert wait_timeout_seconds == 0.0, (
                    "Legacy confirmation must not wait for a repository lock "
                    "while its SQLite writer admission is active."
                )
                legacy_admission_entered.set()
            try:
                with original_repository_lock(
                    fingerprint,
                    observation=observation,
                    wait_timeout_seconds=wait_timeout_seconds,
                ):
                    yield
            finally:
                if not observation:
                    legacy_admission_finished.set()

        monkeypatch.setattr(
            push_delivery_service,
            "_push_repository_lock",
            observe_legacy_admission,
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                rejected_future = executor.submit(
                    fixture.client.post,
                    _legacy_confirm_url(push_execution["id"]),
                    json=_legacy_confirm_payload(push_execution),
                )
                assert legacy_admission_entered.wait(timeout=10), (
                    "Legacy confirmation did not reach repository admission."
                )
                assert legacy_admission_finished.wait(timeout=10), (
                    "Legacy confirmation waited behind the occupied repository "
                    "lock instead of rejecting immediately."
                )
                rejected = rejected_future.result(timeout=10)

            assert rejected.status_code == 409, rejected.text
            rejection_payload = rejected.json()
            rejection_detail = rejection_payload.get("detail") or (
                rejection_payload["error"]["details"]
            )
            assert rejection_detail["code"] == "REPOSITORY_MUTATION_ACTIVE"
            assert observed_waits == [0.0]

            # The rejected request has ended, so its historical BEGIN IMMEDIATE
            # admission must not retain SQLite's writer boundary while the
            # independent repository holder is still active.
            with fixture.factory() as writer:
                writer.execute(text("BEGIN IMMEDIATE"))
                writer.rollback()
            with fixture.factory() as session:
                stored = session.scalar(
                    select(PushExecution).where(
                        PushExecution.push_execution_id == push_execution["id"]
                    )
                )
                assert stored is not None
                assert stored.state == "READY_TO_PUSH"
                assert stored.command_attempt_count == 0
            assert _bare_ref(fixture.origin) == fixture.initial_remote_sha
        finally:
            release_repository.set()
            holder.join(timeout=10)
            assert not holder.is_alive(), (
                "The legacy repository-lock holder survived test teardown."
            )
        assert not holder_errors


def test_expired_approved_plan_can_be_renewed_and_lock_rejection_is_audited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        first_plan, _first_approval = _review_and_approve_push(fixture, commit)
        with fixture.factory() as session:
            stored = session.scalar(
                select(PushPlan).where(PushPlan.push_plan_id == first_plan["id"])
            )
            assert stored is not None and stored.expires_at is not None
            after_expiry = stored.expires_at + timedelta(seconds=1)

        monkeypatch.setattr(push_delivery_service, "utc_now", lambda: after_expiry)
        expired = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert expired.status_code == 200, expired.text
        assert expired.json()["push_plan"]["status"] == "EXPIRED"
        assert expired.json()["actions"]["can_review_push_plan"] is True
        assert expired.json()["actions"]["can_confirm_push"] is False
        assert expired.json()["confirmation"]["state"] == "blocked"
        assert "expired" in expired.json()["confirmation"]["reason"].lower()

        delivery = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/delivery",
            headers=fixture.headers,
        )
        assert delivery.status_code == 200, delivery.text
        assert delivery.json()["next_action"]["primary"] == {
            "code": "review_push_plan",
            "label": "Review Push Plan",
        }

        renewed = fixture.client.post(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
            json={},
        )
        assert renewed.status_code == 200, renewed.text
        second_plan = renewed.json()["push_plan"]
        assert second_plan["version"] == first_plan["version"] + 1
        assert second_plan["id"] != first_plan["id"]
        assert second_plan["approval_state"] == "PENDING"
        assert renewed.json()["actions"]["can_approve_push_plan"] is True
        second_approved = fixture.client.post(
            f"/api/push-plans/{second_plan['id']}/approvals",
            headers=fixture.headers,
            json={
                "confirmation": "APPROVE_PUSH_PLAN",
                "expected_plan_digest": second_plan["advanced"]["plan_digest"],
                "expected_plan_version": second_plan["version"],
            },
        )
        assert second_approved.status_code == 200, second_approved.text
        second_approval = second_approved.json()["push_approval"]
        second_approval["request_identity"] = second_approved.json()[
            "confirmation"
        ]["request_identity"]

        with fixture.factory() as session:
            current = session.scalar(
                select(PushPlan).where(PushPlan.push_plan_id == second_plan["id"])
            )
            assert current is not None
            fingerprint = current.repository_locator_fingerprint
            assert session.scalar(select(func.count()).select_from(PushPlan)) == 2
            assert (
                session.scalar(select(func.count()).select_from(PushPlanApproval))
                == 2
            )

        monkeypatch.setattr(
            push_delivery_service,
            "PUSH_FINAL_LOCK_WAIT_SECONDS",
            0.05,
        )
        with _repository_mutation_lock(fingerprint):
            rejected = fixture.client.post(
                f"/api/push-plans/{second_plan['id']}/push-attempts",
                headers=fixture.headers,
                json=_confirm_payload(second_plan, second_approval),
            )
        assert rejected.status_code == 409, rejected.text
        rejection_payload = rejected.json()
        rejection_detail = rejection_payload.get("detail") or rejection_payload[
            "error"
        ]["details"]
        assert rejection_detail == {
            "code": "REPOSITORY_MUTATION_ACTIVE",
            "message": "Another repository mutation is active.",
            "request_accepted": False,
            "remote_effect": "none",
            "retry_safe": True,
        }
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0
            audit_event = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "owner_push_attempt_rejected_pre_effect")
                .order_by(AuditEvent.id.desc())
            )
            assert audit_event is not None
            assert "request_accepted=false" in audit_event.details
            assert "remote_effect=none" in audit_event.details
            assert "password" not in audit_event.details.lower()

        (fixture.source_repo / "unrelated-modified.txt").write_text(
            "changed after approved push plan\n"
        )
        blocked_before_effect = fixture.client.post(
            f"/api/push-plans/{second_plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(second_plan, second_approval),
        )
        assert blocked_before_effect.status_code == 200, blocked_before_effect.text
        assert blocked_before_effect.json()["push_execution"]["state"] == (
            "PUSH_BLOCKED"
        )
        assert blocked_before_effect.json()["push_execution"][
            "command_attempt_count"
        ] == 0
        assert blocked_before_effect.json()["actions"]["can_confirm_push"] is False
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        safe_re_review = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert safe_re_review.status_code == 200, safe_re_review.text
        assert safe_re_review.json()["actions"]["can_review_push_plan"] is True
        third = fixture.client.post(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
            json={},
        )
        assert third.status_code == 200, third.text
        assert third.json()["push_plan"]["version"] == second_plan["version"] + 1
        assert third.json()["push_plan"]["approval_state"] == "PENDING"
        assert third.json()["actions"]["can_approve_push_plan"] is True


def test_durable_admission_and_stranded_pushing_reconcile_without_transport_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_standard_push = push_delivery_service._run_standard_push
    with _canonical_applied_delivery(tmp_path / "remote-old") as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        plan, approval = _review_and_approve_push(fixture, commit)
        payload = _confirm_payload(plan, approval)
        original_confirm = push_delivery_service.confirm_push_to_origin_main

        def crash_after_durable_admission(*args, **kwargs):
            assert kwargs.get("_repository_lock_held") is True
            raise RuntimeError("simulated loss after durable admission")

        monkeypatch.setattr(
            push_delivery_service,
            "confirm_push_to_origin_main",
            crash_after_durable_admission,
        )
        admission_lost = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=payload,
        )
        assert admission_lost.status_code == 500, admission_lost.text
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0

        resumable = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert resumable.status_code == 200, resumable.text
        assert resumable.json()["actions"]["can_confirm_push"] is True
        assert resumable.json()["confirmation"]["state"] == (
            "ready_for_confirmation"
        )
        assert resumable.json()["confirmation"]["request_accepted"] is False
        assert resumable.json()["confirmation"]["request_identity"] == approval[
            "request_identity"
        ]

        monkeypatch.setattr(
            push_delivery_service,
            "confirm_push_to_origin_main",
            original_confirm,
        )
        transport_calls: list[str] = []

        def crash_before_remote_effect(_root: Path, refspec: str):
            transport_calls.append(refspec)
            raise RuntimeError("simulated process loss before remote effect")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            crash_before_remote_effect,
        )
        process_lost = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=payload,
        )
        assert process_lost.status_code == 500, process_lost.text
        with fixture.factory() as session:
            stranded = session.scalar(select(PushExecution))
            assert stranded is not None
            assert stranded.state == "PUSHING"
            assert stranded.command_attempt_count == 1

        reconciled_old = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert reconciled_old.status_code == 200, reconciled_old.text
        assert reconciled_old.json()["push_execution"]["state"] == (
            "RECONCILIATION_BLOCKED"
        )
        assert reconciled_old.json()["push_execution"]["canonical_state"] == (
            "NEEDS_REVIEW"
        )
        assert reconciled_old.json()["confirmation"]["state"] == "needs_review"
        assert reconciled_old.json()["actions"]["can_confirm_push"] is False
        assert reconciled_old.json()["push_execution"]["post_push"][
            "origin_main_sha"
        ] == fixture.baseline_head
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        assert len(transport_calls) == 1

        delivery = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/delivery",
            headers=fixture.headers,
        )
        assert delivery.status_code == 200, delivery.text
        assert delivery.json()["next_action"]["primary"] is None
        assert delivery.json()["push_delivery"]["push_execution"]["post_push"][
            "origin_main_sha"
        ] == fixture.baseline_head

        _git(
            fixture.source_repo,
            "push",
            "--porcelain",
            "--no-follow-tags",
            "--",
            "origin",
            f"{commit['commit_oid']}:refs/heads/main",
        )
        delayed_remote_receipt = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert delayed_remote_receipt.status_code == 200, delayed_remote_receipt.text
        assert delayed_remote_receipt.json()["push_execution"]["state"] == "PUSHED"
        assert delayed_remote_receipt.json()["push_execution"][
            "remote_receipt_verified"
        ] is True
        assert len(transport_calls) == 1
        with fixture.factory() as session:
            recovery_actions = list(
                session.scalars(
                        select(AuditEvent.action).where(
                        AuditEvent.action.in_(
                            {
                                "push_execution_recovery_needs_review",
                                "push_execution_recovered_delivered",
                                }
                            )
                        ).order_by(AuditEvent.id)
                    )
            )
            assert recovery_actions == [
                "push_execution_recovery_needs_review",
                "push_execution_recovered_delivered",
            ]

        # This test creates a second, independent canonical app below. Restore
        # the process-global transport callable before the first TestClient and
        # app lifespan are torn down so neither teardown nor the next fixture's
        # Coding/Verification lifecycle can inherit this fixture's simulated
        # Push-process failure.
        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            real_standard_push,
        )
        assert push_delivery_service._run_standard_push is real_standard_push

    with _canonical_applied_delivery(tmp_path / "remote-new") as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        plan, approval = _review_and_approve_push(fixture, commit)
        transport_calls: list[str] = []

        def push_then_lose_response(root: Path, refspec: str):
            transport_calls.append(refspec)
            real_standard_push(root, refspec)
            raise RuntimeError("simulated response loss after remote effect")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            push_then_lose_response,
        )
        response_lost = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert response_lost.status_code == 500, response_lost.text
        assert _bare_ref(fixture.origin) == commit["commit_oid"]
        with fixture.factory() as session:
            stranded = session.scalar(select(PushExecution))
            assert stranded is not None and stranded.state == "PUSHING"

        def forbidden_retry(_root: Path, _refspec: str):
            raise AssertionError("GET reconciliation must never invoke Push transport")

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            forbidden_retry,
        )
        reconciled_new = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert reconciled_new.status_code == 200, reconciled_new.text
        assert reconciled_new.json()["push_execution"]["state"] == "PUSHED"
        assert reconciled_new.json()["push_execution"][
            "remote_receipt_verified"
        ] is True
        assert reconciled_new.json()["confirmation"]["state"] == "succeeded"
        assert reconciled_new.json()["actions"]["can_confirm_push"] is False
        assert transport_calls == [
            f"{commit['commit_oid']}:refs/heads/main"
        ]
        with fixture.factory() as session:
            recovered = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "push_execution_recovered_delivered"
                )
            )
            assert recovered is not None
            assert "transport_retried=false" in recovered.details


def test_successful_transport_with_invalid_receipt_needs_review_and_never_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        plan, approval = _review_and_approve_push(fixture, commit)
        delivery_commit = str(commit["commit_oid"])
        original_push = push_delivery_service._run_standard_push
        original_receipt_digest = push_delivery_service._push_receipt_digest
        transport_calls: list[str] = []
        receipt_digest_calls = 0

        def counted_push(root: Path, refspec: str):
            transport_calls.append(refspec)
            return original_push(root, refspec)

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            counted_push,
        )

        def mismatched_receipt_digest(row: PushExecution, reconciliation: dict) -> str:
            nonlocal receipt_digest_calls
            receipt_digest_calls += 1
            if receipt_digest_calls == 1:
                return "0" * 64
            return original_receipt_digest(row, reconciliation)

        monkeypatch.setattr(
            push_delivery_service,
            "_push_receipt_digest",
            mismatched_receipt_digest,
        )
        pushed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert pushed.status_code == 200, pushed.text
        payload = pushed.json()
        assert payload["push_execution"]["state"] == "PUSHED"
        assert payload["push_execution"]["canonical_state"] == "NEEDS_REVIEW"
        assert payload["push_execution"]["remote_receipt_verified"] is False
        assert payload["push_execution"]["verified_remote_sha"] is None
        assert payload["confirmation"]["state"] == "needs_review"
        assert payload["action_state"] == "NEEDS_REVIEW"
        assert payload["delivery_result"]["status"] == "NOT_DELIVERED"
        assert payload["delivery_result"]["complete"] is False
        assert payload["delivery_result"]["verified_remote_sha"] is None
        assert "PUSH_RECEIPT_UNAVAILABLE" in {
            item["code"] for item in payload["delivery_result"]["blockers"]
        }
        assert _bare_ref(fixture.origin) == delivery_commit

        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row is not None
            assert row.receipt_digest == "0" * 64
            recovery = push_delivery_service._decoded_object(
                row.post_push_evidence_json
            )
            session.expunge(row)
            row.receipt_digest = original_receipt_digest(row, recovery)
            row.recovery_reconciliation_json = row.post_push_evidence_json
            row.recovery_reconciliation_digest = "0" * 64
            assert push_delivery_service._verified_push_receipt(row) is None

        replayed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["push_replayed"] is True
        assert replayed.json()["confirmation"]["state"] == "needs_review"
        assert replayed.json()["delivery_result"]["complete"] is False
        assert transport_calls == [f"{delivery_commit}:refs/heads/main"]
        with fixture.factory() as session:
            rows = list(session.scalars(select(PushExecution)))
            assert len(rows) == 1
            assert rows[0].command_attempt_count == 1
            assert rows[0].receipt_digest == "0" * 64


def test_delivered_receipt_with_later_remote_drift_projects_needs_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        plan, approval = _review_and_approve_push(fixture, commit)
        delivery_commit = str(commit["commit_oid"])
        original_push = push_delivery_service._run_standard_push
        transport_calls: list[str] = []

        def counted_push(root: Path, refspec: str):
            transport_calls.append(refspec)
            return original_push(root, refspec)

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            counted_push,
        )
        pushed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["confirmation"]["state"] == "succeeded"
        assert (
            pushed.json()["delivery_result"]["verified_remote_sha"]
            == delivery_commit
        )

        _git(
            fixture.origin,
            "update-ref",
            "refs/heads/main",
            fixture.baseline_head,
            delivery_commit,
        )
        drifted = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
        )
        assert drifted.status_code == 200, drifted.text
        payload = drifted.json()
        assert payload["push_execution"]["state"] == "PUSHED"
        assert payload["push_execution"]["remote_receipt_verified"] is True
        assert payload["action_state"] == "NEEDS_REVIEW"
        assert payload["confirmation"]["state"] == "needs_review"
        assert "Live origin/main does not equal" in payload["confirmation"]["reason"]
        assert payload["delivery_result"]["status"] == "NOT_DELIVERED"
        assert payload["delivery_result"]["verified_remote_sha"] is None
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        replayed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["confirmation"]["state"] == "needs_review"
        assert transport_calls == [f"{delivery_commit}:refs/heads/main"]
        assert _bare_refs(fixture.origin) == [
            f"refs/heads/main {fixture.baseline_head}"
        ]


@pytest.mark.parametrize("transport_outcome", ["timeout", "nonzero"])
def test_attempted_push_without_remote_sha_needs_review_and_never_auto_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transport_outcome: str,
) -> None:
    with _canonical_applied_delivery(tmp_path / transport_outcome) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        plan, approval = _review_and_approve_push(fixture, commit)
        calls: list[str] = []

        def uncertain_transport(_root: Path, refspec: str):
            calls.append(refspec)
            if transport_outcome == "timeout":
                raise PushDeliveryError(
                    "REMOTE_TIMEOUT",
                    "The remote Git operation timed out.",
                    timed_out=True,
                )
            return subprocess.CompletedProcess(
                ["git", "push"],
                returncode=1,
                stdout=b"",
                stderr=b"transport ended without a receipt\n",
            )

        def unavailable_remote_evidence(_context, row: PushExecution):
            return {
                "status": "RECONCILIATION_BLOCKED",
                "complete": False,
                "local_head": row.approved_commit_oid,
                "origin_main_sha": None,
                "approved_commit_sha": row.approved_commit_oid,
                "ahead": None,
                "behind": None,
                "worktree_clean": True,
                "index_clean": True,
                "staged_path_count": 0,
                "blockers": [
                    {
                        "code": "REMOTE_EVIDENCE_UNAVAILABLE",
                        "message": "Exact origin/main evidence is unavailable.",
                    }
                ],
            }

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            uncertain_transport,
        )
        monkeypatch.setattr(
            push_delivery_service,
            "_reconciliation_locked",
            unavailable_remote_evidence,
        )
        attempted = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert attempted.status_code == 200, attempted.text
        assert attempted.json()["push_execution"]["state"] == (
            "RECONCILIATION_BLOCKED"
        )
        assert attempted.json()["push_execution"]["canonical_state"] == (
            "NEEDS_REVIEW"
        )
        assert attempted.json()["confirmation"]["state"] == "needs_review"
        assert attempted.json()["actions"]["can_confirm_push"] is False
        assert attempted.json()["push_execution"]["advanced"][
            "failure_category"
        ] == "REMOTE_EFFECT_UNCONFIRMED"
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        replayed = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json=_confirm_payload(plan, approval),
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["push_replayed"] is True
        assert replayed.json()["confirmation"]["state"] == "needs_review"
        assert calls == [f"{commit['commit_oid']}:refs/heads/main"]
