from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from tests.test_self_hosting import init_and_login, make_client, make_source_repo, run_command
from twos_runtime.db import initialize_database
from twos_runtime.models import (
    AIModel,
    AIModelAssignment,
    AIModelInvocationEvidence,
    CodexInstructionPack,
    CodexRun,
    OwnerAcceptanceItem,
    OwnerAcceptanceSession,
    Project,
    Provider,
    SchemaVersion,
    SessionToken,
    Task,
    User,
    utc_now,
)
from twos_runtime.security import hash_password, hash_token
from twos_runtime.self_hosting import capture_source_snapshot


SHA256_ZERO = "0" * 64
ROUTING_SNAPSHOT = "1" * 64
CODING_MODEL_IDENTIFIER = "fixture-phase18-coding"
VERIFICATION_MODEL_IDENTIFIER = "fixture-phase18-verification"
PACK_CONTENT = "Deterministic Phase 18 fixture Pack."
def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CandidateFixture:
    client: TestClient
    database_path: Path
    source_repo: Path
    owner_id: int
    task_id: int
    pack_id: int
    run_id: int
    coding_assignment_id: int
    verification_assignment_id: int
    coding_evidence_id: int
    verification_evidence_id: int
    source_snapshot_digest: str
    before_modify_hash: str
    before_delete_hash: str
    after_create_hash: str
    after_modify_hash: str
    after_binary_hash: str


def _complete_process_evidence(*, verification: bool) -> dict[str, object]:
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
        "file_change_count": 0 if verification else 4,
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


def _manifest_records(fixture_hashes: dict[str, str]) -> list[dict[str, object]]:
    return [
        {
            "path": "created.txt",
            "change_type": "created",
            "before_sha256": None,
            "after_sha256": fixture_hashes["after_create"],
            "before_size": None,
            "after_size": len(b"created by run\n"),
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
            "before_sha256": fixture_hashes["before_modify"],
            "after_sha256": fixture_hashes["after_modify"],
            "before_size": len(b"before modify\n"),
            "after_size": len(b"after modify\n"),
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
            "before_sha256": fixture_hashes["before_delete"],
            "after_sha256": None,
            "before_size": len(b"delete baseline\n"),
            "after_size": None,
            "before_mode": 0o644,
            "after_mode": None,
            "content_kind": "text",
            "added_lines": 0,
            "removed_lines": 1,
            "changed_hunks": 1,
            "content_included": False,
        },
        {
            "path": "asset.bin",
            "change_type": "modified",
            "before_sha256": fixture_hashes["before_binary"],
            "after_sha256": fixture_hashes["after_binary"],
            "before_size": 4,
            "after_size": 5,
            "before_mode": 0o644,
            "after_mode": 0o644,
            "content_kind": "binary_or_oversized",
            "added_lines": None,
            "removed_lines": None,
            "changed_hunks": None,
            "content_included": False,
        },
    ]


def build_candidate_fixture(
    tmp_path: Path,
    *,
    run_status: str = "completed",
    verification_verdict: str = "passed",
    acceptance_status: str = "accepted",
    include_verification_evidence: bool = True,
    include_coding_evidence: bool = True,
    manifest_records: list[dict[str, object]] | None = None,
    unexpected_paths: list[str] | None = None,
) -> CandidateFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_repo = make_source_repo(tmp_path)
    (source_repo / "modify.txt").write_bytes(b"before modify\n")
    (source_repo / "delete.txt").write_bytes(b"delete baseline\n")
    (source_repo / "asset.bin").write_bytes(b"\x00\x01\x02\x03")
    run_command(source_repo, "git", "add", "modify.txt", "delete.txt", "asset.bin")
    run_command(source_repo, "git", "commit", "-m", "phase 18 fixture baseline")
    source_snapshot = capture_source_snapshot(source_repo)
    database_path = tmp_path / "vol18-delivery-candidate.sqlite3"
    not_invoked = tmp_path / "codex-must-not-be-invoked"
    client = make_client(
        tmp_path,
        source_repo,
        not_invoked,
        database_path=database_path,
    )
    client.__enter__()
    init_and_login(client)

    hashes = {
        "before_modify": sha256_bytes(b"before modify\n"),
        "after_modify": sha256_bytes(b"after modify\n"),
        "before_delete": sha256_bytes(b"delete baseline\n"),
        "before_binary": sha256_bytes(b"\x00\x01\x02\x03"),
        "after_binary": sha256_bytes(b"\x00\x10\x02\x03\x04"),
        "after_create": sha256_bytes(b"created by run\n"),
    }
    records = manifest_records if manifest_records is not None else _manifest_records(hashes)
    changed_files = [
        str(item.get("path"))
        for item in records
        if isinstance(item, dict) and item.get("path")
    ]
    result = {
        "changed_files": changed_files,
        "changed_file_evidence": [
            {
                "path": item.get("path"),
                "before_sha256": item.get("before_sha256"),
                "after_sha256": item.get("after_sha256"),
                "before_size": item.get("before_size"),
                "after_size": item.get("after_size"),
                "before_mode": item.get("before_mode"),
                "after_mode": item.get("after_mode"),
                "before_deleted": item.get("before_sha256") is None,
                "after_deleted": item.get("after_sha256") is None,
            }
            for item in records
            if isinstance(item, dict)
        ],
        "sanitized_diff_evidence": {
            "schema": "twos.sanitized_diff.v1",
            "content_included": False,
            "records": records,
            "record_count": len(records),
            "truncated": False,
        },
        "unexpected_excluded_artifacts": [],
        "source_snapshot_digest": source_snapshot["digest"],
        "post_run_snapshot_digest": "6" * 64,
        "coding_prompt_digest": sha256_bytes(PACK_CONTENT.encode()),
        "coding_process": {
            "status": "completed" if run_status == "completed" else run_status,
            "process_started": True,
            "exit_code": 0,
            "timed_out": run_status == "timed_out",
            "cancelled": run_status == "cancelled",
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
            "unexpected_files": list(unexpected_paths or []),
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
            "unexpected_files": list(unexpected_paths or []),
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
            "status": verification_verdict,
            "passed_checks": [
                "verification_verdict_observed",
                "workspace_unchanged_after_verification",
                "changed_files_checked",
                "unexpected_files_checked",
                "exact_content_checked",
                "test_evidence_checked",
                "git_boundary_checked",
                "remote_boundary_checked",
            ]
            if verification_verdict == "passed"
            else [],
            "failed_checks": [] if verification_verdict == "passed" else ["exact_content_checked"],
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

    factory = client.app.state.session_factory
    with factory() as session:
        owner = session.scalar(select(User))
        project = session.scalar(select(Project).where(Project.key == "twos"))
        assert owner is not None and project is not None
        task = Task(
            project_id=project.id,
            title="Phase 18 deterministic Candidate",
            development_task="Create, modify, delete, and safely describe one binary artifact.",
            workflow_type="product_development",
            objective="Review one immutable Delivery Candidate.",
            implementation_scope="Only repository-relative fixture files.",
            forbidden_scope="No apply, stage, commit, push, or Provider invocation.",
            required_output="An immutable Delivery Candidate and read-only Source Drift result.",
            acceptance_target="Owner accepted independently verified Run evidence.",
            repository_identity=source_repo.name,
            source_baseline_commit=str(source_snapshot["head_sha"]),
            task_version=1,
            status="accepted" if acceptance_status == "accepted" else "owner_review",
            acceptance_state=acceptance_status,
        )
        session.add(task)
        session.flush()

        provider = Provider(
            name="Phase 18 fixture provider",
            kind="model",
            status="healthy",
            enabled=True,
            details="Direct persistence fixture; never invoked.",
        )
        session.add(provider)
        session.flush()
        coding_model = AIModel(
            provider_id=provider.id,
            model_name="Phase 18 Coding fixture",
            stable_id="phase18.fixture.coding",
            display_name="Phase 18 Coding fixture",
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
            model_name="Phase 18 Verification fixture",
            stable_id="phase18.fixture.verification",
            display_name="Phase 18 Verification fixture",
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
            key_boundaries="No apply, stage, commit, or push.",
            acceptance_target=task.acceptance_target,
            source_baseline_commit=str(source_snapshot["head_sha"]),
            development_task=task.development_task,
            development_task_digest=sha256_bytes(task.development_task.encode()),
            assignment_version=1,
            task_version=1,
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            source_snapshot_digest=str(source_snapshot["digest"]),
            source_snapshot_json=json.dumps(
                source_snapshot,
                sort_keys=True,
                separators=(",", ":"),
            ),
            routing_decision_ids="[]",
            generation_metadata=json.dumps(
                {
                    "source_snapshot": {
                        "schema": source_snapshot["schema"],
                        "head_sha": source_snapshot["head_sha"],
                        "digest": source_snapshot["digest"],
                        "included_manifest": source_snapshot["included_manifest"],
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
            approved_by_user_id=owner.id,
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
        terminal = run_status not in {"queued", "starting", "running", "verifying"}
        run = CodexRun(
            task_id=task.id,
            pack_id=pack.id,
            status=run_status,
            executable_status="configured",
            source_repo=str(source_repo),
            source_branch="main",
            source_commit=str(source_snapshot["head_sha"]),
            development_task=task.development_task,
            development_task_digest=pack.development_task_digest,
            assignment_version=1,
            task_version=1,
            routing_snapshot_hash=ROUTING_SNAPSHOT,
            source_snapshot_digest=str(source_snapshot["digest"]),
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
            structured_result=json.dumps(result, sort_keys=True, separators=(",", ":")),
            owner_summary="Coding and independent Verification completed.",
            exit_code=0,
            timed_out=run_status == "timed_out",
            cancelled=run_status == "cancelled",
            started_at=utc_now(),
            finished_at=utc_now() if terminal else None,
        )
        session.add(run)
        session.flush()

        common_provider_evidence = {
            "provider_response_observed": False,
            "requested_model_identifier_match": True,
        }
        coding_evidence = AIModelInvocationEvidence(
            invocation_ref=f"phase18-run-{run.id}-coding",
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
            process_evidence=json.dumps(
                _complete_process_evidence(verification=False),
                sort_keys=True,
                separators=(",", ":"),
            ),
            provider_evidence=json.dumps(
                common_provider_evidence,
                sort_keys=True,
                separators=(",", ":"),
            ),
            request_fingerprint="8" * 64,
            response_fingerprint="9" * 64,
            duration_ms=4,
            diagnostic_code="coding_structured_evidence_verified",
            safe_summary="Controlled persisted Coding evidence.",
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        verification_evidence = AIModelInvocationEvidence(
            invocation_ref=f"phase18-run-{run.id}-verification",
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
            process_evidence=json.dumps(
                _complete_process_evidence(verification=True),
                sort_keys=True,
                separators=(",", ":"),
            ),
            provider_evidence=json.dumps(
                common_provider_evidence,
                sort_keys=True,
                separators=(",", ":"),
            ),
            request_fingerprint="a" * 64,
            response_fingerprint="b" * 64,
            duration_ms=4,
            diagnostic_code="verification_structured_evidence_verified",
            safe_summary="Controlled persisted independent Verification evidence.",
            started_at=utc_now(),
            completed_at=utc_now(),
        )
        if include_coding_evidence:
            session.add(coding_evidence)
        if include_verification_evidence:
            session.add(verification_evidence)
        session.flush()

        acceptance = OwnerAcceptanceSession(
            task_id=task.id,
            codex_run_id=run.id,
            status=acceptance_status,
            owner_note="Accepted deterministic evidence." if acceptance_status == "accepted" else "",
            compact_sync_result="Accepted; no merge or push." if acceptance_status == "accepted" else "",
            # Keep authorization identity distinct from the intentionally
            # invalid acceptance state exercised by blocker tests.
            decided_by_user_id=owner.id,
            decided_at=utc_now() if acceptance_status in {"accepted", "rejected"} else None,
        )
        session.add(acceptance)
        session.flush()
        session.add(
            OwnerAcceptanceItem(
                session_id=acceptance.id,
                key="phase18_fixture",
                label="Phase 18 fixture evidence",
                inspect_target="Persisted Run evidence",
                ui_path="Result",
                pass_standard="Exact Coding and Verification evidence is complete.",
                required=True,
                status="pass" if acceptance_status == "accepted" else "pending",
                ordinal=0,
            )
        )
        session.commit()
        return CandidateFixture(
            client=client,
            database_path=database_path,
            source_repo=source_repo,
            owner_id=owner.id,
            task_id=task.id,
            pack_id=pack.id,
            run_id=run.id,
            coding_assignment_id=coding_assignment.id,
            verification_assignment_id=verification_assignment.id,
            coding_evidence_id=coding_evidence.id if include_coding_evidence else -1,
            verification_evidence_id=(
                verification_evidence.id if include_verification_evidence else -1
            ),
            source_snapshot_digest=str(source_snapshot["digest"]),
            before_modify_hash=hashes["before_modify"],
            before_delete_hash=hashes["before_delete"],
            after_create_hash=hashes["after_create"],
            after_modify_hash=hashes["after_modify"],
            after_binary_hash=hashes["after_binary"],
        )


def close_candidate_fixture(fixture: CandidateFixture) -> None:
    fixture.client.__exit__(None, None, None)


def candidate_url(fixture: CandidateFixture) -> str:
    return f"/api/codex-runs/{fixture.run_id}/delivery-candidate"


def source_boundary(repo: Path) -> dict[str, str]:
    return {
        "head": run_command(repo, "git", "rev-parse", "HEAD").stdout,
        "branch": run_command(repo, "git", "branch", "--show-current").stdout,
        "status": run_command(
            repo,
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
        ).stdout,
        "index": run_command(repo, "git", "diff", "--cached", "--binary").stdout,
        "refs": run_command(repo, "git", "show-ref").stdout,
        "remotes": run_command(repo, "git", "remote", "-v").stdout,
    }


def delivery_candidate_row_snapshot(factory) -> dict[str, object]:
    from twos_runtime.models import DeliveryCandidate

    with factory() as session:
        candidate = session.scalar(select(DeliveryCandidate))
        assert candidate is not None
        return {
            column.name: getattr(candidate, column.name)
            for column in DeliveryCandidate.__table__.columns
        }


def mutate_run_result(fixture: CandidateFixture, mutation) -> None:
    factory = fixture.client.app.state.session_factory
    with factory() as session:
        run = session.get(CodexRun, fixture.run_id)
        assert run is not None
        result = json.loads(run.structured_result)
        mutation(result)
        run.structured_result = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        )
        session.commit()


def mutate_process_evidence(
    fixture: CandidateFixture,
    evidence_id: int,
    mutation,
) -> None:
    factory = fixture.client.app.state.session_factory
    with factory() as session:
        evidence = session.get(AIModelInvocationEvidence, evidence_id)
        assert evidence is not None
        process_evidence = json.loads(evidence.process_evidence)
        mutation(process_evidence)
        evidence.process_evidence = json.dumps(
            process_evidence,
            sort_keys=True,
            separators=(",", ":"),
        )
        session.commit()


def git_index_artifact(repo: Path) -> tuple[bytes, int]:
    raw_path = run_command(repo, "git", "rev-parse", "--git-path", "index").stdout.strip()
    index_path = Path(raw_path)
    if not index_path.is_absolute():
        index_path = repo / index_path
    return index_path.read_bytes(), index_path.stat().st_mtime_ns


def test_source_drift_git_allowlist_contains_only_read_only_operations() -> None:
    from twos_runtime.delivery_candidates import SOURCE_DRIFT_READ_ONLY_GIT_ALLOWLIST

    forbidden = {
        "add",
        "checkout",
        "clean",
        "commit",
        "config",
        "fetch",
        "merge",
        "pull",
        "push",
        "rebase",
        "remote",
        "reset",
        "restore",
        "stage",
        "switch",
        "tag",
    }
    assert SOURCE_DRIFT_READ_ONLY_GIT_ALLOWLIST
    for command in SOURCE_DRIFT_READ_ONLY_GIT_ALLOWLIST:
        assert forbidden.isdisjoint(command.split())


def test_vol18_migration_marker_and_tables_are_idempotent(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        engine = fixture.client.app.state.engine
        factory = fixture.client.app.state.session_factory
        tables = set(inspect(engine).get_table_names())
        assert {"delivery_candidates", "source_drift_evaluations"}.issubset(tables)
        with factory() as session:
            versions = session.scalars(
                select(SchemaVersion).where(SchemaVersion.version == "vol18.001")
            ).all()
            assert len(versions) == 1
            first_applied_at = versions[0].applied_at
        initialize_database(engine)
        with factory() as session:
            versions = session.scalars(
                select(SchemaVersion).where(SchemaVersion.version == "vol18.001")
            ).all()
            assert len(versions) == 1
            assert versions[0].applied_at == first_applied_at
    finally:
        close_candidate_fixture(fixture)


def test_review_change_candidate_creates_one_immutable_candidate(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        source_before_review = source_boundary(fixture.source_repo)
        not_invoked = fixture.source_repo.parent / "codex-must-not-be-invoked"
        assert not not_invoked.exists()
        initial = fixture.client.get(candidate_url(fixture))
        assert initial.status_code == 200
        assert initial.json() == {
            "run_id": fixture.run_id,
            "candidate": None,
            "drift": None,
            "blockers": [],
            "next_action": "Review Change Candidate",
        }

        first = fixture.client.post(candidate_url(fixture))
        assert first.status_code == 200, first.text
        first_body = first.json()
        candidate = first_body["candidate"]
        assert candidate["status_label"] == "Available"
        assert candidate["candidate_digest"]
        assert len(candidate["candidate_digest"]) == 64
        assert candidate["task_id"] == fixture.task_id
        assert candidate["pack_id"] == fixture.pack_id
        assert candidate["run_id"] == fixture.run_id
        assert candidate["coding_assignment_id"] == fixture.coding_assignment_id
        assert (
            candidate["verification_assignment_id"]
            == fixture.verification_assignment_id
        )
        assert candidate["source_snapshot_identity"] == fixture.source_snapshot_digest
        assert candidate["acceptance_status"] == "accepted"
        assert candidate["verification_status"] == "PASS"
        assert first_body["drift"]["status"] == "ready_to_apply"
        assert source_boundary(fixture.source_repo) == source_before_review
        assert not not_invoked.exists()

        repeated = fixture.client.post(candidate_url(fixture))
        assert repeated.status_code == 200, repeated.text
        repeated_candidate = repeated.json()["candidate"]
        assert repeated_candidate["id"] == candidate["id"]
        assert repeated_candidate["candidate_digest"] == candidate["candidate_digest"]
        assert repeated_candidate["created_at"] == candidate["created_at"]

        persisted = fixture.client.get(candidate_url(fixture))
        assert persisted.status_code == 200
        assert persisted.json()["candidate"] == repeated_candidate
        assert source_boundary(fixture.source_repo) == source_before_review
        assert not not_invoked.exists()
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("run_status", "expected_code"),
    [
        ("failed", "RUN_FAILED"),
        ("blocked", "RUN_BLOCKED"),
        ("cancelled", "RUN_CANCELLED"),
        ("timed_out", "RUN_TIMED_OUT"),
        ("queued", "RUN_NOT_TERMINAL"),
        ("starting", "RUN_NOT_TERMINAL"),
        ("running", "RUN_NOT_TERMINAL"),
        ("verifying", "RUN_NOT_TERMINAL"),
    ],
)
def test_ineligible_run_lifecycle_is_truthfully_blocked(
    tmp_path: Path,
    run_status: str,
    expected_code: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path, run_status=run_status)
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        body = response.json()
        assert body["candidate"] is None
        assert body["drift"]["status"] == "candidate_unavailable"
        assert expected_code in {item["code"] for item in body["blockers"]}
    finally:
        close_candidate_fixture(fixture)


def test_failed_run_with_failed_verification_reports_both_truthful_blockers(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(
        tmp_path,
        run_status="failed",
        verification_verdict="failed",
    )
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        codes = {item["code"] for item in response.json()["blockers"]}
        assert {"RUN_FAILED", "VERIFICATION_FAILED"}.issubset(codes)
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("fixture_options", "expected_code"),
    [
        ({"verification_verdict": "failed"}, "VERIFICATION_FAILED"),
        ({"include_verification_evidence": False}, "VERIFICATION_EVIDENCE_INCOMPLETE"),
        ({"include_coding_evidence": False}, "CODING_EVIDENCE_INCOMPLETE"),
        ({"acceptance_status": "owner_review"}, "ACCEPTANCE_INVALID"),
        ({"acceptance_status": "rejected"}, "RESULT_REJECTED"),
    ],
)
def test_ineligible_evidence_and_acceptance_are_truthfully_blocked(
    tmp_path: Path,
    fixture_options: dict[str, object],
    expected_code: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path, **fixture_options)
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        body = response.json()
        assert body["candidate"] is None
        assert expected_code in {item["code"] for item in body["blockers"]}
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("verification_missing", "VERIFICATION_MISSING"),
        ("verification_unavailable", "VERIFICATION_UNAVAILABLE"),
    ],
)
def test_missing_or_unavailable_verification_is_distinguished(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = session.get(CodexRun, fixture.run_id)
            assert run is not None
            result = json.loads(run.structured_result)
            if mutation == "verification_missing":
                result.pop("verification_process", None)
            else:
                run.verification_status = "failed"
            run.structured_result = json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
            )
            session.commit()
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert expected_code in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("coding_process_missing", "CODING_PROCESS_IDENTITY_INCOMPLETE"),
        ("verification_process_missing", "VERIFICATION_PROCESS_IDENTITY_INCOMPLETE"),
        ("process_equal", "PROCESS_IDENTITY_NOT_SEPARATE"),
        ("thread_equal", "THREAD_IDENTITY_NOT_SEPARATE"),
    ],
)
def test_coding_and_verification_persisted_processes_must_be_distinct(
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        if mutation == "coding_process_missing":
            mutate_process_evidence(
                fixture,
                fixture.coding_evidence_id,
                lambda value: value.pop("process_id_fingerprint", None),
            )
        elif mutation == "verification_process_missing":
            mutate_process_evidence(
                fixture,
                fixture.verification_evidence_id,
                lambda value: value.pop("process_id_fingerprint", None),
            )
        else:
            factory = fixture.client.app.state.session_factory
            with factory() as session:
                coding = session.get(
                    AIModelInvocationEvidence,
                    fixture.coding_evidence_id,
                )
                verification = session.get(
                    AIModelInvocationEvidence,
                    fixture.verification_evidence_id,
                )
                assert coding is not None and verification is not None
                coding_process = json.loads(coding.process_evidence)
                verification_process = json.loads(verification.process_evidence)
                key = (
                    "process_id_fingerprint"
                    if mutation == "process_equal"
                    else "thread_id_fingerprint"
                )
                verification_process[key] = coding_process[key]
                verification.process_evidence = json.dumps(
                    verification_process,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                session.commit()

        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert expected_code in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    "proof_field",
    [
        "read_only_sandbox",
        "verification_verdict_observed",
        "workspace_unchanged_after_verification",
        "changed_files_checked",
        "unexpected_files_checked",
        "exact_content_checked",
        "test_evidence_checked",
        "git_boundary_checked",
        "remote_boundary_checked",
    ],
)
@pytest.mark.parametrize("invalid_value", ["missing", False])
def test_every_verification_specific_proof_must_be_persisted_true(
    tmp_path: Path,
    proof_field: str,
    invalid_value: str | bool,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        def invalidate(proof: dict[str, object]) -> None:
            if invalid_value == "missing":
                proof.pop(proof_field, None)
            else:
                proof[proof_field] = False

        mutate_process_evidence(
            fixture,
            fixture.verification_evidence_id,
            invalidate,
        )
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "VERIFICATION_PROOF_INCOMPLETE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("task_id", 999_999),
        ("task_version", 2),
        ("development_task_digest", "0" * 64),
        ("pack_version", 2),
        ("source_snapshot_digest", "0" * 64),
        ("pre_run_commit", "0" * 40),
        ("coding_prompt_digest", "0" * 64),
    ],
)
def test_frozen_run_result_identity_mismatch_is_rejected(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        mutate_run_result(
            fixture,
            lambda result: result.__setitem__(field, invalid_value),
        )
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "RUN_RESULT_BINDING_STALE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize("binding", ["run_source_commit", "pack_source_baseline"])
def test_snapshot_head_must_match_run_and_pack_baseline(
    tmp_path: Path,
    binding: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            run = session.get(CodexRun, fixture.run_id)
            pack = session.get(CodexInstructionPack, fixture.pack_id)
            assert run is not None and pack is not None
            if binding == "run_source_commit":
                run.source_commit = "0" * 40
            else:
                pack.source_baseline_commit = "0" * 40
            session.commit()
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "SOURCE_SNAPSHOT_UNAVAILABLE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize("binding", ["task", "pack", "coding_assignment", "verification_assignment"])
def test_stale_exact_binding_is_rejected(tmp_path: Path, binding: str) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            task = session.get(Task, fixture.task_id)
            run = session.get(CodexRun, fixture.run_id)
            pack = session.get(CodexInstructionPack, fixture.pack_id)
            coding = session.get(AIModelAssignment, fixture.coding_assignment_id)
            verification = session.get(
                AIModelAssignment,
                fixture.verification_assignment_id,
            )
            assert task and run and pack and coding and verification
            if binding == "task":
                task.task_version += 1
            elif binding == "pack":
                pack.status = "invalidated"
                pack.invalidated_at = utc_now()
            elif binding == "coding_assignment":
                coding.routing_snapshot_hash = "c" * 64
            else:
                verification.assignment_version += 1
            session.commit()
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        blocker_codes = {item["code"] for item in response.json()["blockers"]}
        assert any(
            token in code
            for code in blocker_codes
            for token in ("TASK", "PACK", "ASSIGNMENT", "ROUTING")
        )
    finally:
        close_candidate_fixture(fixture)


def test_candidate_routes_require_authentication_and_have_no_mutators(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        fixture.client.cookies.clear()
        assert fixture.client.get(candidate_url(fixture)).status_code == 401
        assert fixture.client.post(candidate_url(fixture)).status_code == 401
        for method in ("put", "patch", "delete"):
            assert getattr(fixture.client, method)(candidate_url(fixture)).status_code == 405
    finally:
        close_candidate_fixture(fixture)


def test_cross_owner_access_is_indistinguishable_from_missing_run(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        raw_token = "phase18-second-owner-session"
        password_hash, password_salt = hash_password("second-owner-password")
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            second_owner = User(
                username="second-owner",
                password_hash=password_hash,
                password_salt=password_salt,
                is_active=True,
            )
            session.add(second_owner)
            session.flush()
            session.add(
                SessionToken(
                    user_id=second_owner.id,
                    token_hash=hash_token(raw_token),
                    created_at=utc_now(),
                    expires_at=utc_now() + timedelta(hours=1),
                )
            )
            session.commit()
        headers = {"Authorization": f"Bearer {raw_token}"}
        wrong_owner = fixture.client.get(candidate_url(fixture), headers=headers)
        missing = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id + 100_000}/delivery-candidate",
            headers=headers,
        )
        assert wrong_owner.status_code == missing.status_code == 404
        assert wrong_owner.json()["error"]["code"] == missing.json()["error"]["code"]
        assert wrong_owner.json()["error"]["message"] == missing.json()["error"]["message"]
        assert "run_id" not in wrong_owner.json()["error"]
    finally:
        close_candidate_fixture(fixture)


def test_cross_owner_audit_cannot_observe_phase18_candidate_run_or_digest(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        candidate = created.json()["candidate"]
        assert candidate is not None

        raw_token = "phase18-audit-isolation-session"
        password_hash, password_salt = hash_password("audit-isolation-password")
        factory = fixture.client.app.state.session_factory
        with factory() as session:
            second_owner = User(
                username="audit-isolation-owner",
                password_hash=password_hash,
                password_salt=password_salt,
                is_active=True,
            )
            session.add(second_owner)
            session.flush()
            second_owner_id = second_owner.id
            session.add(
                SessionToken(
                    user_id=second_owner.id,
                    token_hash=hash_token(raw_token),
                    created_at=utc_now(),
                    expires_at=utc_now() + timedelta(hours=1),
                )
            )
            session.commit()

        response = fixture.client.get(
            "/api/audit",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 200
        events = response.json()
        assert all(item["actor_user_id"] == second_owner_id for item in events)
        serialized = json.dumps(events, sort_keys=True)
        assert f"candidate={candidate['id']}" not in serialized
        assert f"digest={candidate['candidate_digest'][:12]}" not in serialized
        assert f"run={fixture.run_id}" not in serialized
        assert "delivery_candidate" not in serialized
        assert "source_drift_evaluated" not in serialized
    finally:
        close_candidate_fixture(fixture)


def test_database_triggers_block_candidate_update_and_delete(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        engine = fixture.client.app.state.engine
        factory = fixture.client.app.state.session_factory
        before = delivery_candidate_row_snapshot(factory)

        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE delivery_candidates "
                        "SET candidate_digest = :digest WHERE id = :candidate_id"
                    ),
                    {"digest": "f" * 64, "candidate_id": before["id"]},
                )
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM delivery_candidates WHERE id = :candidate_id"),
                    {"candidate_id": before["id"]},
                )

        assert delivery_candidate_row_snapshot(factory) == before
    finally:
        close_candidate_fixture(fixture)


def test_candidate_manifest_contains_create_modify_delete_and_binary_metadata(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200, response.text
        manifest = {
            item["path"]: item for item in response.json()["candidate"]["changed_files"]
        }
        assert {
            path: manifest[path]["operation"]
            for path in ("created.txt", "modify.txt", "delete.txt")
        } == {
            "created.txt": "CREATE",
            "modify.txt": "MODIFY",
            "delete.txt": "DELETE",
        }
        assert manifest["created.txt"]["before_hash"] is None
        assert manifest["created.txt"]["after_hash"] == fixture.after_create_hash
        assert manifest["modify.txt"]["before_hash"] == fixture.before_modify_hash
        assert manifest["modify.txt"]["after_hash"] == fixture.after_modify_hash
        assert manifest["delete.txt"]["before_hash"] == fixture.before_delete_hash
        assert manifest["delete.txt"]["after_hash"] is None
        assert manifest["asset.bin"]["content_kind"] == "binary"
        assert manifest["asset.bin"]["after_hash"] == fixture.after_binary_hash
        assert "content" not in manifest["asset.bin"]
    finally:
        close_candidate_fixture(fixture)


def test_manifest_marks_unexpected_files_without_rendering_content(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path, unexpected_paths=["created.txt"])
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200, response.text
        candidate = response.json()["candidate"]
        assert candidate is not None
        assert candidate["unexpected_file_count"] == 1
        created = next(
            item for item in candidate["changed_files"] if item["path"] == "created.txt"
        )
        assert created["unexpected"] is True
        assert "content" not in created
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    "unsafe_path",
    ["/absolute.txt", "../traversal.txt", "nested/../../escape.txt", ""],
)
def test_manifest_rejects_unsafe_or_malformed_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    hashes = {
        "before_sha256": SHA256_ZERO,
        "after_sha256": "f" * 64,
    }
    record = {
        "path": unsafe_path,
        "change_type": "modified",
        **hashes,
        "before_size": 1,
        "after_size": 1,
        "content_kind": "text",
        "content_included": False,
    }
    fixture = build_candidate_fixture(tmp_path, manifest_records=[record])
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        codes = {item["code"] for item in response.json()["blockers"]}
        assert any("MANIFEST" in code or "PATH" in code for code in codes)
    finally:
        close_candidate_fixture(fixture)


def test_manifest_rejects_duplicate_conflicting_operations(tmp_path: Path) -> None:
    records = [
        {
            "path": "same.txt",
            "change_type": "created",
            "before_sha256": None,
            "after_sha256": "1" * 64,
            "before_size": None,
            "after_size": 1,
            "content_kind": "text",
            "content_included": False,
        },
        {
            "path": "same.txt",
            "change_type": "deleted",
            "before_sha256": "2" * 64,
            "after_sha256": None,
            "before_size": 1,
            "after_size": None,
            "content_kind": "text",
            "content_included": False,
        },
    ]
    fixture = build_candidate_fixture(tmp_path, manifest_records=records)
    try:
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        codes = {item["code"] for item in response.json()["blockers"]}
        assert any("DUPLICATE" in code or "CONFLICT" in code for code in codes)
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("before_sha256", "0" * 64),
        ("after_sha256", "0" * 64),
        ("before_size", 999),
        ("after_size", 999),
        ("before_mode", 0o600),
        ("after_mode", 0o600),
    ],
)
def test_manifest_rejects_sanitized_diff_metadata_inconsistent_with_file_evidence(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        def corrupt_diff(result: dict[str, object]) -> None:
            diff = result["sanitized_diff_evidence"]
            assert isinstance(diff, dict)
            records = diff["records"]
            assert isinstance(records, list)
            modify = next(
                item
                for item in records
                if isinstance(item, dict) and item.get("path") == "modify.txt"
            )
            modify[field] = invalid_value

        mutate_run_result(fixture, corrupt_diff)
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "MANIFEST_UNAVAILABLE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("path", "field", "invalid_value"),
    [
        ("created.txt", "before_size", 0),
        ("created.txt", "before_mode", 0o644),
        ("delete.txt", "after_size", 0),
        ("delete.txt", "after_mode", 0o644),
    ],
)
def test_manifest_rejects_metadata_on_an_absent_file_side(
    tmp_path: Path,
    path: str,
    field: str,
    invalid_value: object,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        def add_absent_side_metadata(result: dict[str, object]) -> None:
            for collection_name in (
                "changed_file_evidence",
                "sanitized_diff_evidence",
            ):
                collection = result[collection_name]
                if collection_name == "sanitized_diff_evidence":
                    assert isinstance(collection, dict)
                    collection = collection["records"]
                assert isinstance(collection, list)
                record = next(
                    item
                    for item in collection
                    if isinstance(item, dict) and item.get("path") == path
                )
                record[field] = invalid_value

        mutate_run_result(fixture, add_absent_side_metadata)
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "MANIFEST_UNAVAILABLE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    "malformation",
    ["record_count_mismatch", "unrelated_record", "empty_records"],
)
def test_manifest_rejects_malformed_truncated_diff_metadata(
    tmp_path: Path,
    malformation: str,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        def corrupt_truncated_diff(result: dict[str, object]) -> None:
            diff = result["sanitized_diff_evidence"]
            assert isinstance(diff, dict)
            records = diff["records"]
            assert isinstance(records, list)
            diff["truncated"] = True
            if malformation == "record_count_mismatch":
                diff["record_count"] = len(records) + 1
            elif malformation == "unrelated_record":
                unrelated = dict(records[0])
                unrelated["path"] = "not-produced-by-this-run.txt"
                diff["records"] = [records[0], unrelated]
                diff["record_count"] = len(result["changed_files"])
            else:
                diff["records"] = []
                diff["record_count"] = len(result["changed_files"])

        mutate_run_result(fixture, corrupt_truncated_diff)
        response = fixture.client.post(candidate_url(fixture))
        assert response.status_code == 200
        assert response.json()["candidate"] is None
        assert "MANIFEST_UNAVAILABLE" in {
            item["code"] for item in response.json()["blockers"]
        }
    finally:
        close_candidate_fixture(fixture)


def test_source_drift_ready_unrelated_and_conflict_are_append_only_and_read_only(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        before = source_boundary(fixture.source_repo)
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        candidate = created.json()["candidate"]
        assert created.json()["drift"]["status"] == "ready_to_apply"
        factory = fixture.client.app.state.session_factory
        immutable_candidate_before = delivery_candidate_row_snapshot(factory)

        (fixture.source_repo / "README.md").write_text("# unrelated owner drift\n")
        unrelated_before = source_boundary(fixture.source_repo)
        unrelated = fixture.client.get(candidate_url(fixture))
        assert unrelated.status_code == 200
        assert unrelated.json()["candidate"] == candidate
        assert unrelated.json()["drift"]["status"] == "source_changed_since_run"
        assert source_boundary(fixture.source_repo) == unrelated_before

        (fixture.source_repo / "modify.txt").write_text("conflicting owner edit\n")
        conflict_before = source_boundary(fixture.source_repo)
        conflict = fixture.client.get(candidate_url(fixture))
        assert conflict.status_code == 200
        assert conflict.json()["candidate"] == candidate
        assert conflict.json()["drift"]["status"] == "conflict_detected"
        assert "modify.txt" in conflict.json()["drift"]["conflict_paths"]
        assert source_boundary(fixture.source_repo) == conflict_before

        after = source_boundary(fixture.source_repo)
        assert after["head"] == before["head"]
        assert after["branch"] == before["branch"]
        assert after["index"] == before["index"]
        assert after["refs"] == before["refs"]
        assert after["remotes"] == before["remotes"]
        assert after["status"] != before["status"]

        assert delivery_candidate_row_snapshot(factory) == immutable_candidate_before
        with factory() as session:
            from twos_runtime.models import DeliveryCandidate, SourceDriftEvaluation

            candidates = session.scalars(select(DeliveryCandidate)).all()
            evaluations = session.scalars(
                select(SourceDriftEvaluation).order_by(SourceDriftEvaluation.id)
            ).all()
            assert len(candidates) == 1
            assert len(evaluations) == 3
            assert [item.status for item in evaluations] == [
                "ready_to_apply",
                "source_changed_since_run",
                "conflict_detected",
            ]
    finally:
        close_candidate_fixture(fixture)


def test_source_drift_sets_no_optional_locks_and_preserves_index_bytes_and_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        index_before = git_index_artifact(fixture.source_repo)
        observed_git_environments: list[dict[str, str]] = []

        import twos_runtime.self_hosting as self_hosting_module

        original_run = self_hosting_module.subprocess.run

        def observe_run(*args, **kwargs):
            command = args[0] if args else kwargs.get("args")
            if (
                isinstance(command, (list, tuple))
                and command
                and command[0] == "git"
            ):
                observed_git_environments.append(dict(kwargs.get("env") or {}))
            return original_run(*args, **kwargs)

        with monkeypatch.context() as context:
            context.setattr(self_hosting_module.subprocess, "run", observe_run)
            response = fixture.client.get(candidate_url(fixture))

        assert response.status_code == 200, response.text
        assert response.json()["drift"]["status"] == "ready_to_apply"
        assert observed_git_environments
        assert all(
            environment.get("GIT_OPTIONAL_LOCKS") == "0"
            for environment in observed_git_environments
        )
        assert git_index_artifact(fixture.source_repo) == index_before
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("modify.txt", b"before modify\n"),
        ("delete.txt", b"delete baseline\n"),
    ],
)
def test_candidate_touched_symlink_is_always_a_conflict_even_if_target_bytes_match(
    tmp_path: Path,
    path: str,
    payload: bytes,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        assert created.json()["drift"]["status"] == "ready_to_apply"

        target = fixture.source_repo / f"{path}.same-bytes-target"
        target.write_bytes(payload)
        touched = fixture.source_repo / path
        touched.unlink()
        touched.symlink_to(target.name)

        response = fixture.client.get(candidate_url(fixture))
        assert response.status_code == 200, response.text
        assert response.json()["drift"]["status"] == "conflict_detected"
        assert path in response.json()["drift"]["conflict_paths"]
    finally:
        close_candidate_fixture(fixture)


def test_git_timeout_is_persisted_as_sanitized_repository_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        candidate = created.json()["candidate"]
        timeout_secret = "must-not-leak-timeout-stderr"

        import twos_runtime.delivery_candidates as delivery_module
        from twos_runtime.models import SourceDriftEvaluation

        def time_out_snapshot(_repo: Path, **_kwargs):
            raise subprocess.TimeoutExpired(
                cmd=["git", "status", str(fixture.source_repo)],
                timeout=30,
                output="private stdout",
                stderr=timeout_secret,
            )

        with monkeypatch.context() as context:
            context.setattr(
                delivery_module,
                "capture_source_snapshot",
                time_out_snapshot,
            )
            response = fixture.client.get(candidate_url(fixture))

        assert response.status_code == 200
        body = response.json()
        assert body["candidate"]["id"] == candidate["id"]
        assert body["drift"]["status"] == "repository_unavailable"
        serialized = json.dumps(body, sort_keys=True)
        assert timeout_secret not in serialized
        assert str(fixture.source_repo) not in serialized

        factory = fixture.client.app.state.session_factory
        with factory() as session:
            persisted = session.scalar(
                select(SourceDriftEvaluation).order_by(
                    SourceDriftEvaluation.id.desc()
                )
            )
            assert persisted is not None
            assert persisted.status == "repository_unavailable"
            assert timeout_secret not in persisted.diagnostics_json
            assert str(fixture.source_repo) not in persisted.diagnostics_json
    finally:
        close_candidate_fixture(fixture)


def test_hostile_git_hooks_and_external_diff_cannot_execute_during_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text

        sentinels: list[Path] = []

        def hostile_hook(name: str) -> Path:
            hook = tmp_path / name
            sentinel = tmp_path / f"{name}.invoked"
            sentinels.append(sentinel)
            quoted = "'" + str(sentinel).replace("'", "'\"'\"'") + "'"
            hook.write_text(f"#!/bin/sh\nprintf invoked > {quoted}\nexit 97\n")
            hook.chmod(0o755)
            return hook

        fsmonitor = hostile_hook("hostile-fsmonitor")
        repository_external = hostile_hook("hostile-repository-external-diff")
        environment_external = hostile_hook("hostile-environment-external-diff")
        run_command(
            fixture.source_repo,
            "git",
            "config",
            "core.fsmonitor",
            str(fsmonitor),
        )
        run_command(
            fixture.source_repo,
            "git",
            "config",
            "diff.external",
            str(repository_external),
        )
        (fixture.source_repo / "README.md").write_text("# unrelated drift\n")

        with monkeypatch.context() as context:
            context.setenv("GIT_EXTERNAL_DIFF", str(environment_external))
            response = fixture.client.get(candidate_url(fixture))

        assert response.status_code == 200, response.text
        assert response.json()["drift"]["status"] == "source_changed_since_run"
        assert all(not sentinel.exists() for sentinel in sentinels)
    finally:
        close_candidate_fixture(fixture)


def test_configured_repository_subdirectory_is_rejected_before_status_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        nested = fixture.source_repo / "configured-subdirectory"
        nested.mkdir()
        wrong_client = make_client(
            tmp_path / "wrong-root-client",
            nested,
            tmp_path / "codex-must-not-be-invoked",
            database_path=fixture.database_path,
        )

        import twos_runtime.self_hosting as self_hosting_module

        original_run = self_hosting_module.subprocess.run
        observed_git_commands: list[tuple[str, ...]] = []

        def observe_run(*args, **kwargs):
            command = args[0] if args else kwargs.get("args")
            if (
                isinstance(command, (list, tuple))
                and command
                and command[0] == "git"
            ):
                observed_git_commands.append(tuple(str(item) for item in command))
            return original_run(*args, **kwargs)

        with wrong_client:
            init_and_login(wrong_client)
            with monkeypatch.context() as context:
                context.setattr(self_hosting_module.subprocess, "run", observe_run)
                response = wrong_client.get(candidate_url(fixture))

        assert response.status_code == 200
        assert response.json()["drift"]["status"] == "repository_unavailable"
        assert observed_git_commands
        assert all("status" not in command for command in observed_git_commands)
        assert str(nested) not in json.dumps(response.json(), sort_keys=True)
    finally:
        close_candidate_fixture(fixture)


@pytest.mark.parametrize(
    "branch_command",
    [
        ("switch", "-c", "same-head-review-branch"),
        ("switch", "--detach"),
    ],
    ids=["different-branch", "detached-head"],
)
def test_same_head_and_files_on_wrong_or_detached_branch_are_not_ready(
    tmp_path: Path,
    branch_command: tuple[str, ...],
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        created = fixture.client.post(candidate_url(fixture))
        assert created.status_code == 200, created.text
        expected_head = run_command(
            fixture.source_repo,
            "git",
            "rev-parse",
            "HEAD",
        ).stdout
        run_command(fixture.source_repo, "git", *branch_command)
        assert (
            run_command(fixture.source_repo, "git", "rev-parse", "HEAD").stdout
            == expected_head
        )
        assert (
            run_command(
                fixture.source_repo,
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
            ).stdout
            == ""
        )

        response = fixture.client.get(candidate_url(fixture))
        assert response.status_code == 200, response.text
        assert response.json()["drift"]["status"] == "source_changed_since_run"
    finally:
        close_candidate_fixture(fixture)


def test_candidate_unavailable_and_repository_unavailable_drift_states(
    tmp_path: Path,
) -> None:
    ineligible = build_candidate_fixture(tmp_path / "ineligible", run_status="failed")
    try:
        unavailable = ineligible.client.post(candidate_url(ineligible))
        assert unavailable.status_code == 200
        assert unavailable.json()["drift"]["status"] == "candidate_unavailable"
    finally:
        close_candidate_fixture(ineligible)

    repository = build_candidate_fixture(tmp_path / "repository")
    try:
        created = repository.client.post(candidate_url(repository))
        assert created.status_code == 200
        assert created.json()["candidate"] is not None
        (repository.source_repo / ".git").rename(
            repository.source_repo / ".git-unavailable"
        )
        unavailable = repository.client.get(candidate_url(repository))
        assert unavailable.status_code == 200
        assert unavailable.json()["candidate"]["id"] == created.json()["candidate"]["id"]
        assert unavailable.json()["drift"]["status"] == "repository_unavailable"
    finally:
        close_candidate_fixture(repository)


def test_candidate_digest_and_identity_survive_process_restart(tmp_path: Path) -> None:
    fixture = build_candidate_fixture(tmp_path)
    response = fixture.client.post(candidate_url(fixture))
    assert response.status_code == 200, response.text
    candidate = response.json()["candidate"]
    close_candidate_fixture(fixture)

    not_invoked = tmp_path / "codex-must-not-be-invoked"
    restarted = make_client(
        tmp_path,
        fixture.source_repo,
        not_invoked,
        database_path=fixture.database_path,
    )
    with restarted:
        init_and_login(restarted)
        persisted = restarted.get(candidate_url(fixture))
        assert persisted.status_code == 200
        assert persisted.json()["candidate"]["id"] == candidate["id"]
        assert (
            persisted.json()["candidate"]["candidate_digest"]
            == candidate["candidate_digest"]
        )
        assert persisted.json()["candidate"]["created_at"] == candidate["created_at"]


def test_ui_contract_exposes_only_phase18_review_control_with_collapsed_advanced(
    tmp_path: Path,
) -> None:
    fixture = build_candidate_fixture(tmp_path)
    try:
        page = fixture.client.get("/twos")
        script = fixture.client.get(
            "/static_cockpit/vol12_static_mvp/twos_command_center.js"
        )
        stylesheet = fixture.client.get(
            "/static_cockpit/vol12_static_mvp/styles.css"
        )
        assert page.status_code == script.status_code == stylesheet.status_code == 200
        assert 'id="review-change-candidate"' in page.text
        assert "Review Change Candidate" in page.text
        assert 'id="candidate-review-section"' in page.text
        assert 'id="candidate-status"' in page.text
        assert 'id="candidate-files"' in page.text
        assert 'id="candidate-acceptance-status"' in page.text
        assert 'id="candidate-verification-status"' in page.text
        assert 'id="candidate-drift-status"' in page.text
        assert 'id="candidate-blockers"' in page.text
        assert 'id="candidate-next-action"' in page.text
        assert '<details id="advanced-panel"' in page.text
        advanced_tag = page.text.split('<details id="advanced-panel"', 1)[1].split(
            ">",
            1,
        )[0]
        assert " open" not in advanced_tag
        assert 'id="candidate-digest"' in page.text
        assert 'id="candidate-manifest-details"' in page.text
        assert 'id="candidate-drift-diagnostics"' in page.text
        assert "Apply Accepted Changes" in page.text
        assert "Revert Applied Changes" in page.text
        assert "Verify Applied Changes" in page.text
        push_button_tag = page.text.split(
            '<button id="push-to-origin-main"',
            1,
        )[1].split(">", 1)[0]
        assert " hidden" in push_button_tag
        assert " disabled" in push_button_tag
        candidate_action = script.text.split(
            "async function reviewChangeCandidate()",
            1,
        )[1].split("async function reviewApplyPlan()", 1)[0]
        assert '"/push-preflights"' not in candidate_action
        assert '"/push-attempts"' not in candidate_action
        assert "PUSH_TO_ORIGIN_MAIN" not in candidate_action

        assert 'TERMINAL_CODEX_RUN_STATUSES' in script.text
        assert 'method: "POST"' in script.text
        assert '"/delivery-candidate"' in script.text
        assert "candidateRelativePath" in script.text
        assert "sanitizedCandidateText" in script.text
        assert "@media (max-width: 760px)" in stylesheet.text
        assert "minmax(0, 1fr)" in stylesheet.text
        assert "overflow-wrap: anywhere" in stylesheet.text
        assert "candidate-file" in stylesheet.text
    finally:
        close_candidate_fixture(fixture)
