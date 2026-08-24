from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from tests.test_self_hosting import (
    approve_pack,
    create_executable_task,
    generate_pack,
    init_and_login,
    make_client,
    make_fake_codex,
    make_source_repo,
    start_codex_run,
    wait_for_run,
)
from tests.test_vol19_verification_truth_remediation import (
    _result_envelope,
    make_local_verifier,
)
from tests.test_vol18_result_intake import (
    _run as result_intake_run,
    result_intake_fixture,
    valid_result_payload,
)
from twos_runtime.models import (
    ApplyPlan,
    ApplyPlanApproval,
    ApplySession,
    CodexExecutionAttempt,
    CodexResultArtifact,
    CodexResultEnvelope,
    CodexRun,
    CodexRunMonitor,
    DeliveryCandidate,
    LocalCommitExecution,
    OwnerAcceptanceSession,
    PushExecution,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.delivery_candidates import materialize_result_delivery_candidate
from twos_runtime.result_intake import canonical_sha256, ingest_result_payload
from twos_runtime.security import hash_password, hash_token


def _run_verified_result(client, headers: dict[str, str]) -> tuple[int, dict, dict]:
    task_id = create_executable_task(
        client,
        headers,
        marker="FAKE_TEST_COMMAND FAKE_READ_ONLY_GIT_INSPECTION",
    )
    pack = generate_pack(client, headers, task_id)
    approve_pack(client, headers, task_id, pack["id"])
    started = start_codex_run(client, headers, task_id, pack)
    assert started.status_code == 200, started.text
    wait_for_run(
        client,
        headers,
        started.json()["id"],
        {"completed"},
        timeout=20,
    )
    envelope = _result_envelope(client, headers, started.json()["id"])
    terminal = client.get(
        f"/api/codex-runs/{started.json()['id']}", headers=headers
    ).json()
    assert terminal["exit_code"] == 0
    assert terminal["terminal_truth"]["coding"]["status"] == "succeeded"
    assert terminal["terminal_truth"]["verification"]["status"] == "passed"
    assert terminal["terminal_truth"]["workspace"]["state"] == "captured"
    return terminal["id"], terminal, envelope


def _decision_payload(
    envelope_response: dict,
    candidate: dict,
    *,
    confirmation: str,
    note: str = "",
) -> dict:
    result = envelope_response["result"]
    return {
        "confirmation": confirmation,
        "expected_result_id": result["id"],
        "expected_result_digest": result["advanced"]["result_digest"],
        "expected_candidate_id": candidate["id"],
        "expected_candidate_version": candidate["candidate_version"],
        "expected_candidate_digest": candidate["advanced"]["candidate_digest"],
        "note": note,
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _error_code(response) -> str:
    details = response.json()["error"]["details"]
    return str(details.get("type") or details.get("code") or "")


def _column_values(row, *, exclude: set[str]) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in exclude
    }


@pytest.fixture(scope="module")
def verified_result_readiness_matrix(tmp_path_factory):
    root = tmp_path_factory.mktemp("vol19-result-readiness-matrix")
    source_repo = make_source_repo(root)
    fake_codex = make_fake_codex(root)
    verifier = make_local_verifier(root)
    with make_client(
        root,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        headers = init_and_login(client)
        run_id, terminal, envelope_response = _run_verified_result(client, headers)
        yield {
            "client": client,
            "headers": headers,
            "run_id": run_id,
            "terminal": terminal,
            "envelope": envelope_response,
        }


def _materialize_scenario_candidate(
    client,
    *,
    baseline_run_id: int,
    scenario: str,
) -> DeliveryCandidate:
    factory = client.app.state.session_factory
    with factory() as session:
        baseline_run = session.get(CodexRun, baseline_run_id)
        baseline_monitor = session.scalar(
            select(CodexRunMonitor).where(CodexRunMonitor.run_id == baseline_run_id)
        )
        baseline_envelope = session.scalar(
            select(CodexResultEnvelope).where(
                CodexResultEnvelope.run_id == baseline_run_id
            )
        )
        baseline_attempts = list(
            session.scalars(
                select(CodexExecutionAttempt)
                .where(CodexExecutionAttempt.run_id == baseline_run_id)
                .order_by(CodexExecutionAttempt.id)
            ).all()
        )
        baseline_artifacts = list(
            session.scalars(
                select(CodexResultArtifact)
                .where(
                    CodexResultArtifact.result_envelope_id
                    == baseline_envelope.id
                )
                .order_by(CodexResultArtifact.ordinal)
            ).all()
        )
        assert baseline_run is not None
        assert baseline_monitor is not None
        assert baseline_envelope is not None
        assert {item.phase for item in baseline_attempts} == {
            "CODING",
            "VERIFICATION",
        }

        suffix = canonical_sha256(
            {
                "schema": "twos.result_delivery_readiness_test.v1",
                "scenario": scenario,
                "baseline_run_id": baseline_run_id,
            }
        )
        run_values = _column_values(baseline_run, exclude={"id"})
        run_values.update(
            {
                "start_idempotency_digest": None,
                "start_request_digest": None,
                "status": "failed" if scenario == "coding_failed" else "completed",
                "exit_code": 3 if scenario == "coding_failed" else 0,
            }
        )
        if scenario == "verification_not_required":
            run_values.update(
                {
                    "verification_assignment_id": None,
                    "verification_model_id": None,
                    "verification_provider_id": None,
                    "verification_connectivity_evidence_id": None,
                    "verification_model_identifier": "",
                    "verification_status": "not_required",
                    "verification_summary": "Independent Verification was not required.",
                    "verification_process_spawned": False,
                    "verification_exit_code": None,
                }
            )
        elif scenario == "verification_unavailable":
            run_values.update(
                {
                    "verification_status": "unavailable",
                    "verification_summary": "Independent Verification did not start.",
                    "verification_process_spawned": False,
                    "verification_exit_code": None,
                }
            )
        elif scenario == "verification_failed":
            run_values.update(
                {
                    "verification_status": "failed",
                    "verification_summary": "Independent Verification failed.",
                    "verification_exit_code": 2,
                }
            )
        cloned_run = CodexRun(**run_values)
        session.add(cloned_run)
        session.flush()

        monitor_values = _column_values(baseline_monitor, exclude={"id"})
        monitor_values.update(
            {
                "monitor_id": f"monitor-{suffix[:24]}",
                "monitor_digest": suffix,
                "run_id": cloned_run.id,
                "monitor_state": "RESULT_AVAILABLE",
                "process_exit_code": run_values["exit_code"],
            }
        )
        if scenario == "verification_not_required":
            monitor_values.update(
                {
                    "verification_assignment_id": None,
                    "verification_model_identifier": "",
                    "verification_process_id": None,
                    "verification_process_start_identity": "",
                }
            )
        cloned_monitor = CodexRunMonitor(**monitor_values)
        session.add(cloned_monitor)
        session.flush()

        cloned_attempts: dict[str, CodexExecutionAttempt] = {}
        for baseline_attempt in baseline_attempts:
            if (
                scenario == "verification_not_required"
                and baseline_attempt.phase == "VERIFICATION"
            ):
                continue
            attempt_values = _column_values(baseline_attempt, exclude={"id"})
            attempt_values.update(
                {
                    "attempt_id": f"attempt-{canonical_sha256({'scenario': scenario, 'phase': baseline_attempt.phase})[:32]}",
                    "run_id": cloned_run.id,
                    "monitor_id": cloned_monitor.id,
                }
            )
            if scenario == "verification_not_required":
                attempt_values["verification_assignment_id"] = None
            if scenario == "coding_failed" and baseline_attempt.phase == "CODING":
                attempt_values.update(
                    {
                        "attempt_state": "FAILED",
                        "process_exit_known": True,
                        "process_exit_code": 3,
                    }
                )
            if (
                scenario == "verification_unavailable"
                and baseline_attempt.phase == "VERIFICATION"
            ):
                attempt_values.update(
                    {
                        "attempt_state": "RESULT_UNAVAILABLE",
                        "process_exit_known": False,
                        "process_exit_code": None,
                        "receipt_digest": "",
                        "terminal_event_observed": False,
                    }
                )
            if (
                scenario == "verification_failed"
                and baseline_attempt.phase == "VERIFICATION"
            ):
                attempt_values.update(
                    {
                        "attempt_state": "FAILED",
                        "process_exit_known": True,
                        "process_exit_code": 2,
                    }
                )
            cloned_attempt = CodexExecutionAttempt(**attempt_values)
            session.add(cloned_attempt)
            session.flush()
            cloned_attempts[baseline_attempt.phase] = cloned_attempt

        result_digest = canonical_sha256(
            {
                "schema": "twos.controlled_result_scenario.v1",
                "scenario": scenario,
                "baseline_result_digest": baseline_envelope.result_digest,
            }
        )
        envelope_values = _column_values(baseline_envelope, exclude={"id"})
        envelope_values.update(
            {
                "envelope_id": f"result-{result_digest[:24]}",
                "monitor_id": cloned_monitor.id,
                "run_id": cloned_run.id,
                "result_digest": result_digest,
                "terminal_status": run_values["status"],
                "process_exit_code": run_values["exit_code"],
            }
        )
        workspace = json.loads(baseline_envelope.workspace_evidence_json)
        if scenario == "coding_failed":
            envelope_values["coding_evidence_json"] = json.dumps(
                {"outcome": "failed"}, sort_keys=True, separators=(",", ":")
            )
            envelope_values["completion_classification"] = "failed"
        elif scenario == "verification_unavailable":
            envelope_values["verification_verdict"] = "UNAVAILABLE"
            envelope_values["verification_evidence_json"] = json.dumps(
                {"outcome": "unavailable"},
                sort_keys=True,
                separators=(",", ":"),
            )
        elif scenario == "verification_failed":
            envelope_values["verification_verdict"] = "FAIL"
            envelope_values["verification_evidence_json"] = json.dumps(
                {"outcome": "failed"}, sort_keys=True, separators=(",", ":")
            )
        elif scenario == "integrity_invalid":
            envelope_values["integrity_state"] = "BLOCKED"
            envelope_values["integrity_findings_json"] = (
                '["CONTROLLED_INTEGRITY_FAILURE"]'
            )
        elif scenario == "workspace_conflict":
            workspace["boundary_violations"] = ["CONTROLLED_REPOSITORY_MISMATCH"]
            envelope_values["workspace_evidence_json"] = json.dumps(
                workspace, sort_keys=True, separators=(",", ":")
            )
            envelope_values["completion_classification"] = (
                "workspace_evidence_conflict"
            )
        elif scenario == "no_changes":
            workspace["attribution"] = {
                "baseline_preexisting": [],
                "run_produced": [],
                "origin_unproven": [],
            }
            workspace["boundary_violations"] = []
            envelope_values.update(
                {
                    "changed_file_manifest_json": "[]",
                    "workspace_evidence_json": json.dumps(
                        workspace, sort_keys=True, separators=(",", ":")
                    ),
                    "completion_classification": (
                        "succeeded_without_workspace_changes"
                    ),
                }
            )
        elif scenario == "verification_not_required":
            envelope_values.update(
                {
                    "verification_assignment_id": None,
                    "verification_verdict": "UNAVAILABLE",
                    "verification_evidence_json": "{}",
                }
            )
        cloned_envelope = CodexResultEnvelope(**envelope_values)
        session.add(cloned_envelope)
        session.flush()

        if scenario != "no_changes":
            for baseline_artifact in baseline_artifacts:
                artifact_values = _column_values(
                    baseline_artifact, exclude={"id", "result_envelope_id"}
                )
                artifact_payload = {
                    "result_digest": result_digest,
                    "ordinal": artifact_values["ordinal"],
                    "path": artifact_values["repository_path"],
                    "display_path": artifact_values["display_path"],
                    "path_identity": artifact_values["path_identity"],
                    "operation": artifact_values["operation"],
                    "before_hash": artifact_values["before_hash"],
                    "after_hash": artifact_values["after_hash"],
                    "before_size": artifact_values["before_size"],
                    "after_size": artifact_values["after_size"],
                    "before_mode": artifact_values["before_mode"],
                    "after_mode": artifact_values["after_mode"],
                    "content_kind": artifact_values["content_kind"],
                    "unexpected": artifact_values["unexpected"],
                    "evidence_identity": artifact_values["evidence_identity"],
                }
                artifact_values.update(
                    {
                        "result_envelope_id": cloned_envelope.id,
                        "artifact_digest": canonical_sha256(artifact_payload),
                    }
                )
                session.add(CodexResultArtifact(**artifact_values))
        session.flush()
        candidate, created, _ = materialize_result_delivery_candidate(
            session,
            owner_id=cloned_envelope.owner_id,
            envelope=cloned_envelope,
        )
        assert created is True
        session.commit()
        session.refresh(candidate)
        session.expunge(candidate)
        return candidate


@pytest.mark.parametrize(
    ("scenario", "expected_state", "expected_policy", "expected_blocker"),
    [
        ("coding_failed", "blocked", "required", "CODING_NOT_SUCCEEDED"),
        (
            "verification_unavailable",
            "blocked",
            "required",
            "VERIFICATION_GATE_NOT_PASSED",
        ),
        (
            "verification_failed",
            "blocked",
            "required",
            "VERIFICATION_GATE_NOT_PASSED",
        ),
        (
            "integrity_invalid",
            "blocked",
            "required",
            "RESULT_INTEGRITY_INVALID",
        ),
        (
            "workspace_conflict",
            "blocked",
            "required",
            "WORKSPACE_EVIDENCE_BLOCKED",
        ),
        ("no_changes", "no_changes", "required", None),
        ("verification_not_required", "ready", "not_required", None),
    ],
)
def test_result_candidate_readiness_matrix_uses_persisted_process_and_workspace_evidence(
    verified_result_readiness_matrix,
    scenario: str,
    expected_state: str,
    expected_policy: str,
    expected_blocker: str | None,
) -> None:
    candidate = _materialize_scenario_candidate(
        verified_result_readiness_matrix["client"],
        baseline_run_id=verified_result_readiness_matrix["run_id"],
        scenario=scenario,
    )
    blockers = json.loads(candidate.readiness_blockers_json)
    blocker_codes = {
        item.get("code") for item in blockers if isinstance(item, dict)
    }
    assert candidate.derivation_version == "twos.result_delivery_candidate.v1"
    assert candidate.readiness_state == expected_state
    assert candidate.verification_policy == expected_policy
    assert candidate.acceptance_status == "owner_review"
    if expected_blocker is None:
        assert blockers == []
    else:
        assert expected_blocker in blocker_codes
    if scenario == "verification_unavailable":
        assert candidate.verification_verdict == "unavailable"
        assert "VERIFICATION_ATTEMPT_UNAVAILABLE" in blocker_codes
    if scenario == "verification_failed":
        assert candidate.verification_verdict == "failed"
    if scenario == "no_changes":
        assert json.loads(candidate.file_manifest_json) == []
    if scenario == "verification_not_required":
        assert candidate.verification_verdict == "not_required"
        assert not any(str(code).startswith("VERIFICATION_") for code in blocker_codes)
    if expected_state in {"blocked", "no_changes"}:
        client = verified_result_readiness_matrix["client"]
        headers = verified_result_readiness_matrix["headers"]
        accepted = client.post(
            f"/api/codex-runs/{candidate.run_id}/delivery-review/accept",
            headers=headers,
            json={
                "confirmation": "ACCEPT_RESULT_FOR_DELIVERY",
                "expected_result_id": candidate.result_envelope_public_id,
                "expected_result_digest": candidate.result_digest,
                "expected_candidate_id": candidate.candidate_id,
                "expected_candidate_version": candidate.candidate_version,
                "expected_candidate_digest": candidate.candidate_digest,
                "note": f"Review controlled {scenario} evidence.",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["review"]["review_state"] == "accepted_for_delivery"
        plan = client.post(
            f"/api/codex-runs/{candidate.run_id}/apply-plans",
            headers=headers,
        )
        assert plan.status_code == 409, plan.text
        with client.app.state.session_factory() as session:
            assert session.scalar(
                select(ApplyPlan).where(ApplyPlan.run_id == candidate.run_id)
            ) is None


def test_automatic_result_candidate_preserves_exact_multi_operation_manifest(
    tmp_path: Path,
) -> None:
    with result_intake_fixture(tmp_path) as fixture:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = result_intake_run(session, fixture)
            payload = valid_result_payload(session, fixture)
            envelope = ingest_result_payload(
                session,
                fixture.owner_id,
                run,
                payload,
                result_source="controlled_vol19_multi_operation_test",
                require_explicit_identity=True,
            )
            session.flush()
            candidate = session.scalar(
                select(DeliveryCandidate).where(
                    DeliveryCandidate.run_id == fixture.run_id
                )
            )
            assert candidate is not None
            assert candidate.derivation_version == "twos.result_delivery_candidate.v1"
            assert candidate.result_envelope_id == envelope.id
            assert candidate.result_envelope_public_id == envelope.envelope_id
            assert candidate.result_digest == envelope.result_digest
            manifest = {
                item["path"]: item
                for item in json.loads(candidate.file_manifest_json)
            }
            assert {
                path: manifest[path]["operation"]
                for path in ("created.txt", "modify.txt", "delete.txt", "asset.bin")
            } == {
                "created.txt": "CREATE",
                "modify.txt": "MODIFY",
                "delete.txt": "DELETE",
                "asset.bin": "MODIFY",
            }
            assert manifest["created.txt"]["before_hash"] is None
            assert manifest["created.txt"]["after_hash"]
            assert manifest["modify.txt"]["before_hash"]
            assert manifest["modify.txt"]["after_hash"]
            assert manifest["delete.txt"]["before_hash"]
            assert manifest["delete.txt"]["after_hash"] is None
            binary = manifest["asset.bin"]
            assert binary["content_kind"] in {"binary", "binary_or_oversized"}
            assert binary["before_hash"] and binary["after_hash"]
            assert binary["before_size"] == 4
            assert binary["after_size"] == 5
            assert "content" not in binary
            assert all(len(item["evidence_identity"]) == 64 for item in manifest.values())
            envelope_id = envelope.id
            first_candidate_id = candidate.id
            first_candidate_digest = candidate.candidate_digest
            session.commit()

        with factory() as session:
            replayed = ingest_result_payload(
                session,
                fixture.owner_id,
                result_intake_run(session, fixture),
                payload,
                result_source="controlled_vol19_multi_operation_test",
                require_explicit_identity=True,
            )
            session.commit()
            candidates = list(
                session.scalars(
                    select(DeliveryCandidate).where(
                        DeliveryCandidate.run_id == fixture.run_id
                    )
                ).all()
            )
            assert replayed.id == envelope_id
            assert len(candidates) == 1
            assert candidates[0].id == first_candidate_id
            assert candidates[0].candidate_digest == first_candidate_digest


def test_result_settlement_materializes_one_exact_pending_candidate_and_reject_is_terminal(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    fake_codex = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        headers = init_and_login(client)
        run_id, terminal, envelope_response = _run_verified_result(client, headers)
        result = envelope_response["result"]

        first = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        )
        assert first.status_code == 200, first.text
        first_review = first.json()
        candidate = first_review["candidate"]
        assert candidate is not None
        assert candidate["readiness_state"] == "ready", candidate
        assert candidate["result_review_state"] == "pending"
        assert candidate["changed_files"] == [
            {
                "name": "codex-result.txt",
                "path": "codex-result.txt",
                "operation": "CREATE",
                "unexpected": False,
            }
        ]
        assert candidate["advanced"]["result_envelope_id"] == result["id"]
        assert (
            candidate["advanced"]["result_digest"]
            == result["advanced"]["result_digest"]
        )
        assert candidate["advanced"]["run_id"] == run_id
        assert candidate["advanced"]["task_id"] == terminal["task_id"]
        assert candidate["advanced"]["pack_id"] == terminal["pack_id"]
        assert candidate["verification_policy"] == "required"
        assert candidate["verification_status"] == "PASSED"
        with client.app.state.session_factory() as session:
            verification_attempt = session.scalar(
                select(CodexExecutionAttempt).where(
                    CodexExecutionAttempt.run_id == run_id,
                    CodexExecutionAttempt.phase == "VERIFICATION",
                )
            )
            assert verification_attempt is not None
            assert candidate["advanced"]["verification_attempt_identity"] == (
                verification_attempt.attempt_id
            )
            assert candidate["advanced"]["verification_receipt_identity"] == (
                verification_attempt.receipt_digest
            )
            assert len(verification_attempt.receipt_digest) == 64

        # Result settlement owns materialization; retrieval and the historical
        # review endpoint must only return the same immutable Candidate.
        retrieved = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        ).json()["candidate"]
        historical_post = client.post(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        )
        assert historical_post.status_code == 200, historical_post.text
        assert retrieved["id"] == candidate["id"]
        assert historical_post.json()["candidate"]["id"] == candidate["id"]
        assert (
            historical_post.json()["candidate"]["advanced"]["candidate_digest"]
            == candidate["advanced"]["candidate_digest"]
        )

        projection = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        )
        assert projection.status_code == 200, projection.text
        assert projection.json()["result_review"]["review_state"] == "pending"
        assert projection.json()["next_action"]["primary"] == {
            "code": "accept_result_for_delivery",
            "label": "Accept for Delivery",
        }
        exact_acceptance = client.get(
            f"/api/tasks/{terminal['task_id']}/owner-acceptance?run_id={run_id}",
            headers=headers,
        )
        assert exact_acceptance.status_code == 200, exact_acceptance.text
        assert exact_acceptance.json()["run_id"] == run_id
        assert (
            exact_acceptance.json()["acceptance"]["candidate_id"]
            == candidate["id"]
        )
        other_task_id = create_executable_task(
            client, headers, marker="CROSS_TASK_RESULT_REVIEW_SCOPE"
        )
        cross_task = client.get(
            f"/api/tasks/{other_task_id}/owner-acceptance?run_id={run_id}",
            headers=headers,
        )
        assert cross_task.status_code == 404

        payload = _decision_payload(
            envelope_response,
            candidate,
            confirmation="REJECT_RESULT_FOR_DELIVERY",
            note="Not the requested delivery.",
        )
        stale_bindings = {
            "expected_result_id": "result-transfer-stale",
            "expected_result_digest": "0" * 64,
            "expected_candidate_id": "candidate-transfer-stale",
            "expected_candidate_version": candidate["candidate_version"] + 1,
            "expected_candidate_digest": "0" * 64,
        }
        for field, replacement in stale_bindings.items():
            stale = client.post(
                f"/api/codex-runs/{run_id}/delivery-review/reject",
                headers=headers,
                json={**payload, field: replacement},
            )
            assert stale.status_code == 409, (field, stale.text)
            assert _error_code(stale) == "RESULT_REVIEW_BINDING_STALE"
            stale_accept = client.post(
                f"/api/codex-runs/{run_id}/delivery-review/accept",
                headers=headers,
                json={
                    **payload,
                    "confirmation": "ACCEPT_RESULT_FOR_DELIVERY",
                    field: replacement,
                },
            )
            assert stale_accept.status_code == 409, (field, stale_accept.text)
            assert _error_code(stale_accept) == "RESULT_REVIEW_BINDING_STALE"
        with client.app.state.session_factory() as session:
            pending = session.scalar(
                select(OwnerAcceptanceSession).where(
                    OwnerAcceptanceSession.codex_run_id == run_id
                )
            )
            assert pending is not None
            assert pending.status == "owner_review"
            assert pending.decision_digest == ""

        other_password = "other-owner-password-123"
        password_hash, password_salt = hash_password(other_password)
        other_token = "vol19-result-delivery-other-owner-session-0001"
        with client.app.state.session_factory() as session:
            other = User(
                username="other-owner",
                password_hash=password_hash,
                password_salt=password_salt,
                is_active=True,
            )
            session.add(other)
            session.flush()
            session.add(
                SessionToken(
                    user_id=other.id,
                    token_hash=hash_token(other_token),
                    expires_at=utc_now() + timedelta(hours=1),
                )
            )
            session.commit()
        cross_owner = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/reject",
            headers={"Authorization": f"Bearer {other_token}"},
            json=payload,
        )
        assert cross_owner.status_code == 404
        cross_owner_projection = client.get(
            f"/api/tasks/{terminal['task_id']}/owner-acceptance?run_id={run_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert cross_owner_projection.status_code == 404

        rejected = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/reject",
            headers=headers,
            json=payload,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["review"]["review_state"] == "rejected"
        assert rejected.json()["automatic_actions"] == []
        replay = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/reject",
            headers=headers,
            json=payload,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["decision_replayed"] is True
        opposite = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/accept",
            headers=headers,
            json={**payload, "confirmation": "ACCEPT_RESULT_FOR_DELIVERY"},
        )
        assert opposite.status_code == 409
        assert _error_code(opposite) == "RESULT_REVIEW_ALREADY_FINAL"
        blocked_plan = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert blocked_plan.status_code == 409

        with client.app.state.session_factory() as session:
            assert session.query(CodexResultEnvelope).count() == 1
            assert session.query(DeliveryCandidate).count() == 1
            acceptance = session.scalar(
                select(OwnerAcceptanceSession).where(
                    OwnerAcceptanceSession.codex_run_id == run_id
                )
            )
            assert acceptance is not None
            assert acceptance.status == "rejected"
            assert acceptance.result_digest == result["advanced"]["result_digest"]
            assert acceptance.candidate_digest == candidate["advanced"]["candidate_digest"]
            assert len(acceptance.decision_digest) == 64
            assert session.query(ApplyPlan).count() == 0
            assert session.query(ApplySession).count() == 0
        assert not (source_repo / "codex-result.txt").exists()
        assert _git(source_repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_explicit_result_acceptance_plan_approval_apply_and_revert_preserve_lineage(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    source_head = _git(source_repo, "rev-parse", "HEAD").strip()
    fake_codex = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)
    database_path = tmp_path / "result-owner-delivery.sqlite3"

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        headers = init_and_login(client)
        run_id, terminal, envelope_response = _run_verified_result(client, headers)
        run_worktree = Path(terminal["worktree_path"])
        candidate_review = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        ).json()
        candidate = candidate_review["candidate"]
        assert candidate["readiness_state"] == "ready"
        assert candidate["result_review_state"] == "pending"
        assert not (source_repo / "codex-result.txt").exists()
        assert (run_worktree / "codex-result.txt").read_text() == "isolated result\n"
        run_status_before = _git(
            run_worktree, "status", "--porcelain", "--untracked-files=all"
        )

        premature_plan = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert premature_plan.status_code == 409
        assert _error_code(premature_plan) == "OWNER_REVIEW_PENDING"

        accept_payload = _decision_payload(
            envelope_response,
            candidate,
            confirmation="ACCEPT_RESULT_FOR_DELIVERY",
            note="Accept the exact verified Result for delivery planning.",
        )
        accepted = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/accept",
            headers=headers,
            json=accept_payload,
        )
        assert accepted.status_code == 200, accepted.text
        review = accepted.json()["review"]
        assert review["review_state"] == "accepted_for_delivery"
        assert accepted.json()["automatic_actions"] == []
        decision_digest = review["advanced"]["decision_digest"]
        assert len(decision_digest) == 64
        assert client.get(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        ).json()["plan"] is None
        accepted_refresh = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        ).json()
        assert accepted_refresh["result"]["id"] == envelope_response["result"]["id"]
        assert accepted_refresh["result_review"]["review_state"] == (
            "accepted_for_delivery"
        )
        assert accepted_refresh["candidate"]["candidate"]["id"] == candidate["id"]
        assert accepted_refresh["apply_plan"] is None
        assert accepted_refresh["next_action"]["primary"]["code"] == (
            "review_apply_plan"
        )
        assert not (source_repo / "codex-result.txt").exists()

        plan_response = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        assert plan["approval_required"] is True
        assert plan["approval_state"] == "PENDING"
        assert plan["effective_state"] == "awaiting_owner_approval"
        assert plan["result_review_state"] == "accepted_for_delivery"
        assert plan["entries"] == [
            {
                **plan["entries"][0],
                "path": "codex-result.txt",
                "operation": "CREATE",
                "disposition": "INCLUDED",
            }
        ]
        assert plan["advanced"]["result_envelope_id"] == envelope_response["result"]["id"]
        assert plan["advanced"]["result_digest"] == envelope_response["result"]["advanced"]["result_digest"]
        assert plan["advanced"]["candidate_id"] == candidate["id"]
        assert plan["advanced"]["candidate_digest"] == candidate["advanced"]["candidate_digest"]
        assert plan["advanced"]["result_review_decision_digest"] == decision_digest
        plan_refresh = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        ).json()
        assert plan_refresh["apply_plan"]["id"] == plan["id"]
        assert plan_refresh["apply_plan"]["approval_state"] == "PENDING"
        assert plan_refresh["next_action"]["primary"]["code"] == (
            "approve_apply_plan"
        )
        with client.app.state.session_factory() as session:
            persisted_plan = session.scalar(
                select(ApplyPlan).where(ApplyPlan.plan_id == plan["id"])
            )
            assert persisted_plan is not None
            assert persisted_plan.run_id == run_id
            assert persisted_plan.task_id == terminal["task_id"]
            assert persisted_plan.task_version == candidate["advanced"]["task_version"]
            assert persisted_plan.pack_id == terminal["pack_id"]
            assert persisted_plan.pack_version == candidate["advanced"]["pack_version"]
            assert persisted_plan.result_envelope_public_id == (
                envelope_response["result"]["id"]
            )
            assert persisted_plan.result_digest == (
                envelope_response["result"]["advanced"]["result_digest"]
            )
            assert persisted_plan.candidate_public_id == candidate["id"]
            assert persisted_plan.candidate_version == candidate["candidate_version"]
            assert persisted_plan.candidate_digest == candidate["advanced"][
                "candidate_digest"
            ]
            assert persisted_plan.result_review_decision_digest == decision_digest
            assert persisted_plan.verification_receipt_identity == candidate[
                "advanced"
            ]["verification_receipt_identity"]
            assert persisted_plan.source_workspace_identity == candidate["advanced"][
                "source_workspace_identity"
            ]
            assert persisted_plan.run_workspace_identity == candidate["advanced"][
                "run_workspace_identity"
            ]

        apply_review_url = f"/api/apply-plans/{plan['id']}/apply-sessions"
        before_approval = client.get(apply_review_url, headers=headers)
        assert before_approval.status_code == 200, before_approval.text
        assert before_approval.json()["actions"]["can_apply"] is False
        assert before_approval.json()["apply_confirmation"]["approval_state"] == "PENDING"
        assert not (source_repo / "codex-result.txt").exists()

        stale_approval = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json={
                "confirmation": "APPROVE_APPLY_PLAN",
                "expected_plan_digest": "0" * 64,
                "expected_candidate_digest": plan["advanced"]["candidate_digest"],
                "expected_result_digest": plan["advanced"]["result_digest"],
                "expected_result_review_decision_digest": decision_digest,
            },
        )
        assert stale_approval.status_code == 409
        assert _error_code(stale_approval) == "EXPECTED_PLAN_DIGEST_MISMATCH"
        stale_candidate_approval = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json={
                "confirmation": "APPROVE_APPLY_PLAN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_candidate_digest": "0" * 64,
                "expected_result_digest": plan["advanced"]["result_digest"],
                "expected_result_review_decision_digest": decision_digest,
            },
        )
        assert stale_candidate_approval.status_code == 409
        assert _error_code(stale_candidate_approval) == (
            "EXPECTED_CANDIDATE_DIGEST_MISMATCH"
        )
        assert not (source_repo / "codex-result.txt").exists()

        approval_response = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json={
                "confirmation": "APPROVE_APPLY_PLAN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_candidate_digest": plan["advanced"]["candidate_digest"],
                "expected_result_digest": plan["advanced"]["result_digest"],
                "expected_result_review_decision_digest": decision_digest,
            },
        )
        assert approval_response.status_code == 200, approval_response.text
        approval = approval_response.json()["approval"]
        assert approval["state"] == "APPROVED"
        assert (
            approval_response.json()["plan"]["effective_state"]
            == "ready_for_owner_review"
        )
        assert approval_response.json()["automatic_actions"] == []
        replayed_approval = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json={
                "confirmation": "APPROVE_APPLY_PLAN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_candidate_digest": plan["advanced"]["candidate_digest"],
                "expected_result_digest": plan["advanced"]["result_digest"],
                "expected_result_review_decision_digest": decision_digest,
            },
        )
        assert replayed_approval.status_code == 200
        assert replayed_approval.json()["approval_replayed"] is True
        assert replayed_approval.json()["approval"]["id"] == approval["id"]
        assert not (source_repo / "codex-result.txt").exists()
        approval_refresh = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        ).json()
        assert approval_refresh["apply_plan"]["approval_state"] == "APPROVED"
        assert approval_refresh["apply_session"]["actions"]["can_apply"] is True
        assert approval_refresh["next_action"]["primary"]["code"] == (
            "apply_accepted_changes"
        )

        ready = client.get(apply_review_url, headers=headers).json()
        assert ready["actions"]["can_apply"] is True
        confirmation = ready["apply_confirmation"]
        assert confirmation["approval_state"] == "APPROVED"
        stale_candidate_apply = client.post(
            apply_review_url,
            headers=headers,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": "0" * 64,
                "expected_plan_approval_digest": confirmation[
                    "expected_plan_approval_digest"
                ],
                "expected_result_digest": confirmation["expected_result_digest"],
                "expected_result_review_decision_digest": confirmation[
                    "expected_result_review_decision_digest"
                ],
            },
        )
        assert stale_candidate_apply.status_code == 409
        assert _error_code(stale_candidate_apply) == (
            "APPLY_CONFIRMATION_BINDING_CHANGED"
        )
        assert not (source_repo / "codex-result.txt").exists()
        applied_response = client.post(
            apply_review_url,
            headers=headers,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": confirmation["expected_candidate_digest"],
                "expected_plan_approval_digest": confirmation[
                    "expected_plan_approval_digest"
                ],
                "expected_result_digest": confirmation["expected_result_digest"],
                "expected_result_review_decision_digest": confirmation[
                    "expected_result_review_decision_digest"
                ],
            },
        )
        assert applied_response.status_code == 200, applied_response.text
        applied = applied_response.json()
        assert applied["execution_state"] == "Applied"
        assert applied["changed_file_count"] == 1
        assert applied["session"]["state"] == "APPLIED"
        assert applied["actions"]["can_revert"] is True
        assert applied["revert_confirmation"]["eligible"] is True
        assert applied["session"]["result_lineage"] == {
            "result_envelope_id": envelope_response["result"]["id"],
            "owner_review": "accepted_for_delivery",
            "apply_plan_approval_id": approval["id"],
        }
        assert (source_repo / "codex-result.txt").read_text() == "isolated result\n"
        assert _git(source_repo, "diff", "--cached", "--name-only") == ""
        assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head
        assert (run_worktree / "codex-result.txt").read_text() == "isolated result\n"
        assert _git(
            run_worktree, "status", "--porcelain", "--untracked-files=all"
        ) == run_status_before
        applied_refresh = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        ).json()
        assert applied_refresh["result"]["id"] == envelope_response["result"]["id"]
        assert applied_refresh["result_review"]["review_state"] == (
            "accepted_for_delivery"
        )
        assert applied_refresh["candidate"]["candidate"]["id"] == candidate["id"]
        assert applied_refresh["apply_plan"]["id"] == plan["id"]
        assert applied_refresh["apply_plan"]["approval_state"] == "APPROVED"
        assert applied_refresh["apply_session"]["session"]["state"] == "APPLIED"
        assert applied_refresh["apply_session"]["actions"]["can_revert"] is True, (
            applied_refresh["apply_session"]
        )
        assert applied_refresh["next_action"]["primary"] == {
            "code": "revert_applied_changes",
            "label": "Revert Applied Changes",
        }, applied_refresh

        duplicate_apply = client.post(
            apply_review_url,
            headers=headers,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": confirmation["expected_candidate_digest"],
                "expected_plan_approval_digest": confirmation[
                    "expected_plan_approval_digest"
                ],
                "expected_result_digest": confirmation["expected_result_digest"],
                "expected_result_review_decision_digest": confirmation[
                    "expected_result_review_decision_digest"
                ],
            },
        )
        assert duplicate_apply.status_code == 200, duplicate_apply.text
        assert duplicate_apply.json()["session"]["id"] == applied["session"]["id"]
        assert duplicate_apply.json()["session"]["state"] == "APPLIED"

        reverted_response = client.post(
            f"/api/apply-sessions/{applied['session']['id']}/reverts",
            headers=headers,
            json={
                "confirmation": "REVERT_APPLIED_CHANGES",
                "expected_journal_digest": applied["session"]["journal_digest"],
            },
        )
        assert reverted_response.status_code == 200, reverted_response.text
        reverted = reverted_response.json()
        assert reverted["execution_state"] == "Reverted"
        assert reverted["session"]["state"] == "REVERTED"
        assert not (source_repo / "codex-result.txt").exists()
        reverted_refresh = client.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        ).json()
        assert reverted_refresh["apply_session"]["session"]["state"] == "REVERTED"
        assert reverted_refresh["apply_session"]["actions"]["can_revert"] is False
        assert reverted_refresh["next_action"]["primary"] is None
        assert reverted_refresh["next_action"]["message"] == (
            "Delivery is reverted; the immutable Run Result remains available."
        )
        duplicate_revert = client.post(
            f"/api/apply-sessions/{applied['session']['id']}/reverts",
            headers=headers,
            json={
                "confirmation": "REVERT_APPLIED_CHANGES",
                "expected_journal_digest": applied["session"]["journal_digest"],
            },
        )
        assert duplicate_revert.status_code == 200, duplicate_revert.text
        assert duplicate_revert.json()["session"]["state"] == "REVERTED"

        with client.app.state.session_factory() as session:
            assert session.query(DeliveryCandidate).count() == 1
            assert session.query(OwnerAcceptanceSession).count() == 1
            assert session.query(ApplyPlan).count() == 1
            assert session.query(ApplyPlanApproval).count() == 1
            assert session.query(ApplySession).count() == 1
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0
        assert _git(source_repo, "status", "--porcelain", "--untracked-files=all") == ""
        assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        database_path=database_path,
        timeout=20,
        local_verification_command=verifier,
    ) as restarted:
        headers = init_and_login(restarted)
        persisted = restarted.get(
            f"/api/codex-runs/{run_id}/delivery", headers=headers
        )
        assert persisted.status_code == 200, persisted.text
        projection = persisted.json()
        assert projection["run_id"] == run_id
        assert projection["result"]["id"] == envelope_response["result"]["id"]
        assert projection["result_review"]["review_state"] == "accepted_for_delivery"
        assert projection["candidate"]["candidate"]["id"] == candidate["id"]
        assert projection["apply_plan"]["id"] == plan["id"]
        assert projection["apply_plan"]["approval_state"] == "APPROVED"
        assert (
            projection["apply_session"]["session"]["id"]
            == applied["session"]["id"]
        )
        assert projection["apply_session"]["session"]["state"] == "REVERTED"
        assert projection["apply_session"]["actions"]["can_revert"] is False
        assert projection["next_action"]["primary"] is None
        assert projection["next_action"]["message"] == (
            "Delivery is reverted; the immutable Run Result remains available."
        )
        assert not (source_repo / "codex-result.txt").exists()
        assert (run_worktree / "codex-result.txt").read_text() == "isolated result\n"


def test_preexisting_run_workspace_and_excluded_decoys_are_never_attributed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_root = tmp_path / "ordinary-preexisting"
    blocked_root.mkdir()
    blocked_source = make_source_repo(blocked_root)
    blocked_codex = make_fake_codex(blocked_root)
    with make_client(blocked_root, blocked_source, blocked_codex, timeout=20) as client:
        manager = client.app.state.codex_manager
        original_create = manager.adapter.create_worktree

        def create_with_unapproved_path(run_id: int, source_commit: str):
            worktree, branch = original_create(run_id, source_commit)
            (worktree / "preexisting-run-workspace.txt").write_text(
                "not produced by Coding\n",
                encoding="utf-8",
            )
            return worktree, branch

        with monkeypatch.context() as context:
            context.setattr(
                manager.adapter,
                "create_worktree",
                create_with_unapproved_path,
            )
            headers = init_and_login(client)
            task_id = create_executable_task(client, headers)
            pack = generate_pack(client, headers, task_id)
            approve_pack(client, headers, task_id, pack["id"])
            started = start_codex_run(client, headers, task_id, pack)
            assert started.status_code == 200, started.text
            blocked = wait_for_run(
                client,
                headers,
                started.json()["id"],
                {"blocked"},
                timeout=20,
            )
        assert blocked["process_spawned"] is False
        assert blocked["exit_code"] is None
        with client.app.state.session_factory() as session:
            assert session.scalar(
                select(DeliveryCandidate).where(
                    DeliveryCandidate.run_id == blocked["id"]
                )
            ) is None
        assert not (blocked_source / "preexisting-run-workspace.txt").exists()

    excluded_root = tmp_path / "excluded-preexisting"
    excluded_root.mkdir()
    excluded_source = make_source_repo(excluded_root)
    excluded_codex = make_fake_codex(excluded_root)
    verifier = make_local_verifier(excluded_root)
    with make_client(
        excluded_root,
        excluded_source,
        excluded_codex,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        manager = client.app.state.codex_manager
        original_create = manager.adapter.create_worktree

        def create_with_excluded_decoys(run_id: int, source_commit: str):
            worktree, branch = original_create(run_id, source_commit)
            (worktree / "twos-runtime.log").write_text(
                "runtime-only evidence\n", encoding="utf-8"
            )
            spool = worktree / ".twos-spool"
            spool.mkdir()
            (spool / "receipt.json").write_text(
                '{"runtime":"only"}\n', encoding="utf-8"
            )
            (worktree / "credentials-owner.json").write_text(
                "credential-shaped decoy\n", encoding="utf-8"
            )
            assert (worktree / ".git").exists()
            return worktree, branch

        with monkeypatch.context() as context:
            context.setattr(
                manager.adapter,
                "create_worktree",
                create_with_excluded_decoys,
            )
            headers = init_and_login(client)
            task_id = create_executable_task(
                client,
                headers,
                marker="FAKE_TEST_COMMAND FAKE_READ_ONLY_GIT_INSPECTION",
            )
            pack = generate_pack(client, headers, task_id)
            approve_pack(client, headers, task_id, pack["id"])
            started = start_codex_run(client, headers, task_id, pack)
            assert started.status_code == 200, started.text
            terminal = wait_for_run(
                client,
                headers,
                started.json()["id"],
                {"completed", "failed", "blocked"},
                timeout=20,
            )
            envelope_response = _result_envelope(client, headers, terminal["id"])

        result_paths = terminal["result"]["changed_files"]
        assert result_paths == ["codex-result.txt"]
        assert all(
            not path.startswith(".git")
            and "spool" not in path
            and not path.endswith(".log")
            and "credential" not in path.casefold()
            for path in result_paths
        )
        exclusions = terminal["result"]["unexpected_excluded_artifacts"]
        assert {item["reason"] for item in exclusions} >= {
            "runtime_or_generated",
            "credential_or_secret",
        }
        assert "[credential-shaped path withheld]" in {
            item["path"] for item in exclusions
        }
        candidate_response = client.get(
            f"/api/codex-runs/{terminal['id']}/delivery-candidate",
            headers=headers,
        )
        assert candidate_response.status_code == 200, candidate_response.text
        candidate = candidate_response.json()["candidate"]
        assert candidate is not None
        assert [item["path"] for item in candidate["changed_files"]] == [
            "codex-result.txt"
        ]
        serialized = json.dumps(
            {"candidate": candidate, "result": envelope_response["result"]},
            sort_keys=True,
        )
        assert "credentials-owner.json" not in serialized
        with client.app.state.session_factory() as session:
            persisted_candidate = session.scalar(
                select(DeliveryCandidate).where(
                    DeliveryCandidate.run_id == terminal["id"]
                )
            )
            assert persisted_candidate is not None
            artifacts = list(
                session.scalars(
                    select(CodexResultArtifact).where(
                        CodexResultArtifact.result_envelope_id
                        == persisted_candidate.result_envelope_id
                    )
                ).all()
            )
            assert [item.repository_path for item in artifacts] == [
                "codex-result.txt"
            ]


def test_apply_blocks_same_path_standalone_run_workspace_substitution(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    source_head = _git(source_repo, "rev-parse", "HEAD").strip()
    fake_codex = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        headers = init_and_login(client)
        run_id, terminal, envelope_response = _run_verified_result(client, headers)
        run_worktree = Path(terminal["worktree_path"])
        run_branch = _git(run_worktree, "branch", "--show-current").strip()
        postimage = (run_worktree / "codex-result.txt").read_bytes()
        postimage_mode = (run_worktree / "codex-result.txt").stat().st_mode & 0o777
        candidate = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        ).json()["candidate"]
        accepted = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/accept",
            headers=headers,
            json=_decision_payload(
                envelope_response,
                candidate,
                confirmation="ACCEPT_RESULT_FOR_DELIVERY",
                note="Accept exact evidence before the substitution check.",
            ),
        )
        assert accepted.status_code == 200, accepted.text
        plan_response = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        decision_digest = accepted.json()["review"]["advanced"]["decision_digest"]
        approval_response = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json={
                "confirmation": "APPROVE_APPLY_PLAN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_candidate_digest": plan["advanced"]["candidate_digest"],
                "expected_result_digest": plan["advanced"]["result_digest"],
                "expected_result_review_decision_digest": decision_digest,
            },
        )
        assert approval_response.status_code == 200, approval_response.text
        confirmation = client.get(
            f"/api/apply-plans/{plan['id']}/apply-sessions", headers=headers
        ).json()["apply_confirmation"]

        # Replace the exact recorded location with a different standalone Git
        # repository at the same HEAD and with the same intended postimage.
        # Path, HEAD, branch, and file bytes alone must not substitute for the
        # immutable process-observed Run workspace identity.
        preserved_worktree = tmp_path / "preserved-original-run-worktree"
        run_worktree.rename(preserved_worktree)
        subprocess.run(
            ["git", "init", "--quiet", str(run_worktree)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(run_worktree), "fetch", "--quiet", str(source_repo), source_head],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(run_worktree),
                "checkout",
                "--quiet",
                "-b",
                run_branch,
                "FETCH_HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        (run_worktree / "codex-result.txt").write_bytes(postimage)
        (run_worktree / "codex-result.txt").chmod(postimage_mode)
        assert _git(run_worktree, "rev-parse", "HEAD").strip() == source_head
        assert _git(run_worktree, "branch", "--show-current").strip() == run_branch
        assert (run_worktree / "codex-result.txt").read_bytes() == postimage
        assert _git(run_worktree, "remote") == ""

        blocked_response = client.post(
            f"/api/apply-plans/{plan['id']}/apply-sessions",
            headers=headers,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": confirmation["expected_candidate_digest"],
                "expected_plan_approval_digest": confirmation[
                    "expected_plan_approval_digest"
                ],
                "expected_result_digest": confirmation["expected_result_digest"],
                "expected_result_review_decision_digest": confirmation[
                    "expected_result_review_decision_digest"
                ],
            },
        )
        assert blocked_response.status_code == 200, blocked_response.text
        blocked = blocked_response.json()
        assert blocked["session"]["state"] == "PREFLIGHT_BLOCKED"
        assert blocked["session"]["blockers"][0]["code"] == (
            "RUN_WORKSPACE_IDENTITY_MISMATCH"
        )
        assert not (source_repo / "codex-result.txt").exists()
        assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head
        assert _git(source_repo, "diff", "--cached", "--name-only") == ""
        with client.app.state.session_factory() as session:
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0


def test_plan_approval_and_apply_block_same_path_source_repository_substitution(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    source_head = _git(source_repo, "rev-parse", "HEAD").strip()
    source_status = _git(
        source_repo, "status", "--porcelain", "--untracked-files=all"
    )
    fake_codex = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)

    with make_client(
        tmp_path,
        source_repo,
        fake_codex,
        timeout=20,
        local_verification_command=verifier,
    ) as client:
        headers = init_and_login(client)
        run_id, _terminal, envelope_response = _run_verified_result(client, headers)
        candidate = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        ).json()["candidate"]
        accepted = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/accept",
            headers=headers,
            json=_decision_payload(
                envelope_response,
                candidate,
                confirmation="ACCEPT_RESULT_FOR_DELIVERY",
                note="Accept exact evidence before the source substitution check.",
            ),
        )
        assert accepted.status_code == 200, accepted.text
        decision_digest = accepted.json()["review"]["advanced"]["decision_digest"]
        plan_response = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        approval_payload = {
            "confirmation": "APPROVE_APPLY_PLAN",
            "expected_plan_digest": plan["advanced"]["plan_digest"],
            "expected_candidate_digest": plan["advanced"]["candidate_digest"],
            "expected_result_digest": plan["advanced"]["result_digest"],
            "expected_result_review_decision_digest": decision_digest,
        }

        preserved_source = tmp_path / "preserved-original-source-repository"

        def substitute_source_repository() -> None:
            source_repo.rename(preserved_source)
            shutil.copytree(preserved_source, source_repo, symlinks=True)
            assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head
            assert (
                _git(
                    source_repo,
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                )
                == source_status
            )
            assert _git(source_repo, "remote") == ""

        def restore_source_repository() -> None:
            shutil.rmtree(source_repo)
            preserved_source.rename(source_repo)

        # The substitute has the same locator, branch, HEAD, index bytes, and
        # source bytes, but a different Git common-dir filesystem identity.
        # Approval must therefore expire rather than approving the substitute.
        substitute_source_repository()
        blocked_approval = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json=approval_payload,
        )
        assert blocked_approval.status_code == 409, blocked_approval.text
        assert _error_code(blocked_approval) == "REPOSITORY_BINDING_CHANGED"
        assert not (source_repo / "codex-result.txt").exists()
        restore_source_repository()

        approved = client.post(
            f"/api/apply-plans/{plan['id']}/approve",
            headers=headers,
            json=approval_payload,
        )
        assert approved.status_code == 200, approved.text
        confirmation = client.get(
            f"/api/apply-plans/{plan['id']}/apply-sessions", headers=headers
        ).json()["apply_confirmation"]

        # Replacing the approved source afterward must also fail the direct
        # Apply source-identity proof before any Run postimage is opened.
        substitute_source_repository()
        blocked_apply = client.post(
            f"/api/apply-plans/{plan['id']}/apply-sessions",
            headers=headers,
            json={
                "confirmation": "APPLY_ACCEPTED_CHANGES",
                "expected_plan_digest": confirmation["expected_plan_digest"],
                "expected_candidate_digest": confirmation[
                    "expected_candidate_digest"
                ],
                "expected_plan_approval_digest": confirmation[
                    "expected_plan_approval_digest"
                ],
                "expected_result_digest": confirmation["expected_result_digest"],
                "expected_result_review_decision_digest": confirmation[
                    "expected_result_review_decision_digest"
                ],
            },
        )
        assert blocked_apply.status_code == 200, blocked_apply.text
        blocked = blocked_apply.json()
        assert blocked["session"]["state"] == "PREFLIGHT_BLOCKED"
        assert blocked["session"]["blockers"][0]["code"] == (
            "SOURCE_WORKSPACE_IDENTITY_MISMATCH"
        )
        assert not (source_repo / "codex-result.txt").exists()
        assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head
        assert _git(source_repo, "diff", "--cached", "--name-only") == ""
        with client.app.state.session_factory() as session:
            assert session.query(LocalCommitExecution).count() == 0
            assert session.query(PushExecution).count() == 0
        restore_source_repository()
        assert _git(source_repo, "rev-parse", "HEAD").strip() == source_head
        assert _git(
            source_repo, "status", "--porcelain", "--untracked-files=all"
        ) == source_status


def test_owner_delivery_ui_keeps_one_ordered_primary_flow_and_mobile_reachability() -> None:
    ui_root = Path(__file__).parents[1] / "static_cockpit" / "vol12_static_mvp"
    html = (ui_root / "twos_command_center.html").read_text(encoding="utf-8")
    javascript = (ui_root / "twos_command_center.js").read_text(encoding="utf-8")
    css = (ui_root / "styles.css").read_text(encoding="utf-8")

    result_index = html.index('id="result-intake-summary"')
    review_index = html.index('id="acceptance-card"')
    candidate_index = html.index('id="candidate-review-section"')
    plan_index = html.index('id="apply-plan-review-section"')
    apply_index = html.index('id="apply-session-section"')
    assert result_index < review_index < candidate_index < plan_index < apply_index

    for control in (
        '<button id="accept-result"',
        '<button id="reject-result"',
        '<button id="review-apply-plan"',
        '<button id="approve-apply-plan"',
        '<button id="apply-accepted-changes"',
        '<button id="revert-applied-changes"',
    ):
        assert control in html
    assert html.index('id="accept-result"') < html.index('id="approve-apply-plan"')
    assert html.index('id="approve-apply-plan"') < html.index(
        'id="apply-accepted-changes"'
    )
    assert '<details class="result-review-evidence-details">' in html
    assert '<summary>Review evidence checklist</summary>' in html
    assert '<details class="result-review-evidence-details" open' not in html
    assert "produced by this accepted and independently verified Run" not in html
    candidate_advanced_index = html.index('id="candidate-advanced-card"')
    source_run_record_index = html.index('id="candidate-source-run"')
    assert candidate_advanced_index < source_run_record_index
    assert "Captured Result " not in javascript
    assert " is bound to Candidate " not in javascript
    assert (
        "Exact Result, Candidate, and Run record identifiers remain under Advanced."
        in javascript
    )

    for route in (
        "/apply-plans/",
        "/approve",
        "/apply-sessions",
        "/reverts",
    ):
        assert route in javascript
    assert '+ "/delivery-review/" + routeDecision' in javascript
    assert "ACCEPT_RESULT_FOR_DELIVERY" in javascript
    assert "REJECT_RESULT_FOR_DELIVERY" in javascript
    assert '"/owner-acceptance?run_id="' in javascript
    assert "async function decideAcceptance" in javascript
    assert "async function approveApplyPlan" in javascript
    assert 'elements.acceptResult.addEventListener("click"' in javascript
    assert 'elements.rejectResult.addEventListener("click"' in javascript
    assert 'elements.approveApplyPlan.addEventListener("click"' in javascript
    assert 'elements.applyAcceptedChanges.addEventListener("click"' in javascript

    assert "@media (max-width: 420px)" in css
    assert "@media (max-width: 520px)" in css
    assert ".result-delivery-review-controls .button" in css
    assert ".apply-plan-review-heading .button" in css
    assert ".apply-session-controls .button" in css
    assert "width: 100%" in css
    assert "overflow-wrap: anywhere" in css
