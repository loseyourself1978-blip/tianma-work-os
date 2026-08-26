from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from tests.test_self_hosting import (
    init_and_login,
    make_client,
    make_fake_codex,
    make_source_repo,
    run_command,
)
from tests.test_vol19_result_owner_delivery import (
    _decision_payload,
    _run_verified_result,
)
from tests.test_vol19_verification_truth_remediation import make_local_verifier
from twos_runtime.commit_builder import CommitBuilderError, _safe_message
from twos_runtime.models import (
    ApplySession,
    CommitProposal,
    CommitProposalApproval,
    LocalCommitExecution,
    PostApplyVerification,
    PushExecution,
    PushPlan,
    PushPlanApproval,
    SessionToken,
    User,
    utc_now,
)
from twos_runtime.owner_commit_delivery import _sanitize_output
from twos_runtime.security import hash_password, hash_token
import twos_runtime.push_delivery as push_delivery_service


COMMIT_SUBJECT = "feat: deliver the accepted Owner result"
COMMIT_BODY = "Commit only the exact file owned by the applied delivery."


@pytest.fixture(autouse=True)
def _clear_inherited_git_process_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> str:
    return run_command(repo, "git", *args).stdout.strip()


def _bare_ref(origin: Path, ref: str = "refs/heads/main") -> str:
    return run_command(
        origin.parent,
        "git",
        "--git-dir",
        str(origin),
        "rev-parse",
        ref,
    ).stdout.strip()


def _bare_refs(origin: Path) -> list[str]:
    output = run_command(
        origin.parent,
        "git",
        "--git-dir",
        str(origin),
        "for-each-ref",
        "--format=%(refname) %(objectname)",
    ).stdout
    return sorted(line for line in output.splitlines() if line)


def _error_code(response) -> str:
    payload = response.json()
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("code") or detail.get("type") or "")
    error = payload.get("error")
    if isinstance(error, dict):
        details = error.get("details")
        if isinstance(details, dict):
            return str(details.get("code") or details.get("type") or "")
        return str(error.get("code") or "")
    return ""


def _copy_objects(source_repo: Path, origin: Path) -> None:
    source = source_repo / ".git" / "objects"
    destination = origin / "objects"
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)


@dataclass(frozen=True)
class AppliedDelivery:
    client: object
    headers: dict[str, str]
    source_repo: Path
    run_worktree: Path
    origin: Path
    baseline_head: str
    run_id: int
    task_id: int
    result: dict[str, object]
    candidate: dict[str, object]
    plan: dict[str, object]
    applied: dict[str, object]
    verification: dict[str, object]

    @property
    def factory(self):
        return self.client.app.state.session_factory


@contextmanager
def _canonical_applied_delivery(tmp_path: Path, *, unrelated: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_repo = make_source_repo(tmp_path)
    (source_repo / "unrelated-modified.txt").write_text("baseline modified\n")
    (source_repo / "unrelated-staged.txt").write_text("baseline staged\n")
    run_command(
        source_repo,
        "git",
        "add",
        "unrelated-modified.txt",
        "unrelated-staged.txt",
    )
    run_command(source_repo, "git", "commit", "-m", "add unrelated baselines")
    baseline_head = _git(source_repo, "rev-parse", "HEAD")

    origin = tmp_path / "origin.git"
    run_command(
        tmp_path,
        "git",
        "init",
        "--bare",
        "--initial-branch=main",
        str(origin),
    )
    run_command(source_repo, "git", "remote", "add", "origin", str(origin))
    run_command(
        source_repo,
        "git",
        "push",
        "--set-upstream",
        "origin",
        "HEAD:refs/heads/main",
    )
    assert _bare_ref(origin) == baseline_head

    if unrelated:
        (source_repo / "unrelated-modified.txt").write_text("preserve modified\n")
        (source_repo / "unrelated-untracked.txt").write_text("preserve untracked\n")

    fake_codex = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)
    database_path = tmp_path / "vol19-owner-commit-push.sqlite3"
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
        run_worktree = Path(str(terminal["worktree_path"]))
        candidate_review = client.get(
            f"/api/codex-runs/{run_id}/delivery-candidate", headers=headers
        )
        assert candidate_review.status_code == 200, candidate_review.text
        candidate = candidate_review.json()["candidate"]
        accepted = client.post(
            f"/api/codex-runs/{run_id}/delivery-review/accept",
            headers=headers,
            json=_decision_payload(
                envelope_response,
                candidate,
                confirmation="ACCEPT_RESULT_FOR_DELIVERY",
                note="Accept the exact verified result for the focused Commit/Push test.",
            ),
        )
        assert accepted.status_code == 200, accepted.text
        decision_digest = accepted.json()["review"]["advanced"]["decision_digest"]

        plan_response = client.post(
            f"/api/codex-runs/{run_id}/apply-plans", headers=headers
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()["plan"]
        approved = client.post(
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
        assert approved.status_code == 200, (approved.text, plan)
        apply_url = f"/api/apply-plans/{plan['id']}/apply-sessions"
        confirmation = client.get(apply_url, headers=headers).json()[
            "apply_confirmation"
        ]
        applied_response = client.post(
            apply_url,
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
        assert applied_response.status_code == 200, applied_response.text
        applied = applied_response.json()
        assert applied["session"]["state"] == "APPLIED"
        assert _git(source_repo, "rev-parse", "HEAD") == baseline_head
        assert _bare_ref(origin) == baseline_head

        verification_response = client.post(
            f"/api/apply-sessions/{applied['session']['id']}/post-apply-verifications",
            headers=headers,
            json={
                "expected_journal_digest": applied["session"]["journal_digest"]
            },
        )
        assert verification_response.status_code == 200, verification_response.text
        verification = verification_response.json()["verification"]
        assert verification["status"] == "PASSED"
        if unrelated:
            # Apply retains the accepted precondition that the real index is
            # initially clean. Exercise 19.1D's stronger index-preservation
            # boundary by introducing an unrelated staged entry only after
            # Apply and its post-Apply validation are complete.
            (source_repo / "unrelated-staged.txt").write_text("preserve staged\n")
            run_command(source_repo, "git", "add", "--", "unrelated-staged.txt")
        yield AppliedDelivery(
            client=client,
            headers=headers,
            source_repo=source_repo,
            run_worktree=run_worktree,
            origin=origin,
            baseline_head=baseline_head,
            run_id=run_id,
            task_id=int(terminal["task_id"]),
            result=envelope_response["result"],
            candidate=candidate,
            plan=plan,
            applied=applied,
            verification=verification,
        )


def _create_proposal(
    fixture: AppliedDelivery,
    *,
    subject: str = COMMIT_SUBJECT,
    body: str = COMMIT_BODY,
):
    return fixture.client.post(
        f"/api/post-apply-verifications/{fixture.verification['id']}/commit-proposals",
        headers=fixture.headers,
        json={
            "expected_verification_digest": fixture.verification["advanced"][
                "verification_digest"
            ],
            "subject": subject,
            "body": body,
        },
    )


def _approve_proposal(fixture: AppliedDelivery, proposal: dict[str, object]):
    return fixture.client.post(
        f"/api/commit-proposals/{proposal['id']}/approvals",
        headers=fixture.headers,
        json={
            "confirmation": "APPROVE_COMMIT_PROPOSAL",
            "expected_proposal_digest": proposal["proposal_digest"],
            "expected_proposal_version": proposal["version"],
        },
    )


def _confirm_commit(
    fixture: AppliedDelivery,
    proposal: dict[str, object],
    approval: dict[str, object],
):
    return fixture.client.post(
        f"/api/commit-proposals/{proposal['id']}/local-commits",
        headers=fixture.headers,
        json={
            "confirmation": "CREATE_LOCAL_COMMIT",
            "expected_proposal_digest": proposal["proposal_digest"],
            "expected_approval_digest": approval["approval_digest"],
        },
    )


def _commit_delivery(fixture: AppliedDelivery) -> tuple[dict, dict, dict]:
    proposed = _create_proposal(fixture)
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()["proposal"]
    approved = _approve_proposal(fixture, proposal)
    assert approved.status_code == 200, approved.text
    approval = approved.json()["proposal"]["approval"]
    committed = _confirm_commit(fixture, proposal, approval)
    assert committed.status_code == 200, committed.text
    commit = committed.json()["proposal"]["commit"]
    assert commit["state"] == "COMMITTED"
    return proposal, approval, commit


def test_owner_commit_and_push_real_end_to_end_preserves_unrelated_index_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path, unrelated=True) as fixture:
        target = fixture.source_repo / "codex-result.txt"
        assert target.read_text() == "isolated result\n"
        assert (fixture.run_worktree / "codex-result.txt").read_text() == (
            "isolated result\n"
        )
        staged_patch_before = _git(fixture.source_repo, "diff", "--cached", "--binary")
        modified_before = (fixture.source_repo / "unrelated-modified.txt").read_bytes()
        staged_before = (fixture.source_repo / "unrelated-staged.txt").read_bytes()
        untracked_before = (fixture.source_repo / "unrelated-untracked.txt").read_bytes()
        remote_refs_before = _bare_refs(fixture.origin)

        hook_marker = fixture.source_repo / ".git" / "twos-owner-hook-ran"
        hook = fixture.source_repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\nprintf ran > {hook_marker}\n")
        hook.chmod(0o755)

        first_response = _create_proposal(fixture, subject="feat: proposal version one")
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()["proposal"]
        assert first["version"] == 1
        assert first["files"] == [{"path": "codex-result.txt", "operation": "CREATE"}]
        excluded_paths = {
            item["path"] if isinstance(item, dict) else item
            for item in first["excluded_paths"]
        }
        assert {
            "unrelated-modified.txt",
            "unrelated-staged.txt",
            "unrelated-untracked.txt",
        }.issubset(excluded_paths)
        premature_commit = fixture.client.post(
            f"/api/commit-proposals/{first['id']}/local-commits",
            headers=fixture.headers,
            json={
                "confirmation": "CREATE_LOCAL_COMMIT",
                "expected_proposal_digest": first["proposal_digest"],
                "expected_approval_digest": "0" * 64,
            },
        )
        assert premature_commit.status_code == 409
        assert _error_code(premature_commit) == "COMMIT_APPROVAL_REQUIRED"
        assert _git(fixture.source_repo, "rev-parse", "HEAD") == fixture.baseline_head
        first_approved = _approve_proposal(fixture, first)
        assert first_approved.status_code == 200, first_approved.text
        first_approval = first_approved.json()["proposal"]["approval"]

        edited_response = _create_proposal(fixture, subject=COMMIT_SUBJECT)
        assert edited_response.status_code == 200, edited_response.text
        edited = edited_response.json()["proposal"]
        assert edited["version"] == 2
        assert edited["proposal_digest"] != first["proposal_digest"]
        stale_confirmation = _confirm_commit(fixture, first, first_approval)
        assert stale_confirmation.status_code == 409
        assert _error_code(stale_confirmation) == "COMMIT_PROPOSAL_SUPERSEDED"
        assert _git(fixture.source_repo, "rev-parse", "HEAD") == fixture.baseline_head

        approved_response = _approve_proposal(fixture, edited)
        assert approved_response.status_code == 200, approved_response.text
        approval = approved_response.json()["proposal"]["approval"]
        assert approved_response.json()["automatic_actions"] == []
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        committed_response = _confirm_commit(fixture, edited, approval)
        assert committed_response.status_code == 200, committed_response.text
        commit = committed_response.json()["proposal"]["commit"]
        delivery_commit = str(commit["commit_oid"])
        assert commit["state"] == "COMMITTED"
        assert commit["parent_oid"] == fixture.baseline_head
        assert commit["changed_file_count"] == 1
        assert delivery_commit == _git(fixture.source_repo, "rev-parse", "HEAD")
        assert hook_marker.read_text() == "ran"
        assert _git(
            fixture.source_repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            delivery_commit,
        ).splitlines() == ["codex-result.txt"]
        assert _git(fixture.source_repo, "diff", "--cached", "--binary") == staged_patch_before
        assert (fixture.source_repo / "unrelated-modified.txt").read_bytes() == modified_before
        assert (fixture.source_repo / "unrelated-staged.txt").read_bytes() == staged_before
        assert (fixture.source_repo / "unrelated-untracked.txt").read_bytes() == untracked_before
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        assert _bare_refs(fixture.origin) == remote_refs_before
        assert committed_response.json()["automatic_actions"] == []

        replayed_commit = _confirm_commit(fixture, edited, approval)
        assert replayed_commit.status_code == 200, replayed_commit.text
        assert replayed_commit.json()["commit_replayed"] is True
        assert replayed_commit.json()["proposal"]["commit"]["commit_oid"] == delivery_commit
        assert _git(fixture.source_repo, "rev-list", "--count", fixture.baseline_head + "..HEAD") == "1"

        reverted = fixture.client.post(
            f"/api/apply-sessions/{fixture.applied['session']['id']}/reverts",
            headers=fixture.headers,
            json={
                "confirmation": "REVERT_APPLIED_CHANGES",
                "expected_journal_digest": fixture.applied["session"]["journal_digest"],
            },
        )
        assert reverted.status_code == 409
        assert _error_code(reverted) == "REVERT_AFTER_COMMIT_BLOCKED"

        push_review = fixture.client.post(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
            json={},
        )
        assert push_review.status_code == 200, push_review.text
        push_plan = push_review.json()["push_plan"]
        assert push_plan["approval_state"] == "PENDING"
        assert push_plan["remote"] == "origin"
        assert push_plan["target_ref"] == "refs/heads/main"
        assert push_plan["remote_old_sha"] == fixture.baseline_head
        assert push_plan["remote_new_sha"] == delivery_commit
        assert push_plan["refspec"] == f"{delivery_commit}:refs/heads/main"
        assert push_plan["no_force"] is True
        assert push_plan["no_tags"] is True
        assert push_review.json()["actions"]["can_approve_push_plan"] is True
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        premature_push = fixture.client.post(
            f"/api/push-plans/{push_plan['id']}/push-attempts",
            headers=fixture.headers,
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_plan_digest": push_plan["advanced"]["plan_digest"],
                "expected_approval_digest": "0" * 64,
            },
        )
        assert premature_push.status_code == 409
        assert _error_code(premature_push) == "PUSH_APPROVAL_REQUIRED"
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        push_approved = fixture.client.post(
            f"/api/push-plans/{push_plan['id']}/approvals",
            headers=fixture.headers,
            json={
                "confirmation": "APPROVE_PUSH_PLAN",
                "expected_plan_digest": push_plan["advanced"]["plan_digest"],
                "expected_plan_version": push_plan["version"],
            },
        )
        assert push_approved.status_code == 200, push_approved.text
        push_approval = push_approved.json()["push_approval"]
        assert push_approved.json()["automatic_actions"] == []
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        original_push = push_delivery_service._run_standard_push
        observed_refspecs: list[str] = []

        def counted_push(root: Path, refspec: str):
            observed_refspecs.append(refspec)
            return original_push(root, refspec)

        monkeypatch.setattr(push_delivery_service, "_run_standard_push", counted_push)
        pushed = fixture.client.post(
            f"/api/push-plans/{push_plan['id']}/push-attempts",
            headers=fixture.headers,
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_plan_digest": push_plan["advanced"]["plan_digest"],
                "expected_approval_digest": push_approval["advanced"][
                    "approval_digest"
                ],
            },
        )
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()["push_execution"]["state"] == "PUSHED"
        assert pushed.json()["push_execution"]["remote_receipt_verified"] is True
        assert pushed.json()["delivery_result"]["status"] == "DELIVERED"
        assert pushed.json()["delivery_result"]["complete"] is True
        assert observed_refspecs == [f"{delivery_commit}:refs/heads/main"]
        assert _bare_ref(fixture.origin) == delivery_commit
        assert _bare_refs(fixture.origin) == [f"refs/heads/main {delivery_commit}"]
        assert _git(fixture.source_repo, "tag", "--list") == ""
        assert (fixture.source_repo / "unrelated-modified.txt").read_bytes() == modified_before
        assert (fixture.source_repo / "unrelated-staged.txt").read_bytes() == staged_before
        assert (fixture.source_repo / "unrelated-untracked.txt").read_bytes() == untracked_before

        replayed_push = fixture.client.post(
            f"/api/push-plans/{push_plan['id']}/push-attempts",
            headers=fixture.headers,
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_plan_digest": push_plan["advanced"]["plan_digest"],
                "expected_approval_digest": push_approval["advanced"][
                    "approval_digest"
                ],
            },
        )
        assert replayed_push.status_code == 200, replayed_push.text
        assert replayed_push.json()["push_replayed"] is True
        assert replayed_push.json()["push_execution"]["state"] == "PUSHED"
        assert observed_refspecs == [f"{delivery_commit}:refs/heads/main"]

        commit_refresh = fixture.client.get(
            f"/api/post-apply-verifications/{fixture.verification['id']}/commit-proposals",
            headers=fixture.headers,
        )
        push_refresh = fixture.client.get(
            f"/api/local-commits/{commit['id']}/push-plans", headers=fixture.headers
        )
        delivery_refresh = fixture.client.get(
            f"/api/codex-runs/{fixture.run_id}/delivery", headers=fixture.headers
        )
        assert commit_refresh.status_code == push_refresh.status_code == 200
        assert commit_refresh.json()["proposal"]["commit"]["commit_oid"] == delivery_commit
        assert push_refresh.json()["push_execution"]["state"] == "PUSHED"
        assert delivery_refresh.status_code == 200, delivery_refresh.text
        assert delivery_refresh.json()["commit_delivery"]["proposal"]["commit"][
            "commit_oid"
        ] == delivery_commit
        assert delivery_refresh.json()["push_delivery"]["push_execution"][
            "state"
        ] == "PUSHED"

        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(CommitProposal)) == 2
            assert session.scalar(select(func.count()).select_from(CommitProposalApproval)) == 2
            assert session.scalar(select(func.count()).select_from(LocalCommitExecution)) == 1
            assert session.scalar(select(func.count()).select_from(PushPlan)) == 1
            assert session.scalar(select(func.count()).select_from(PushPlanApproval)) == 1
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 1
            persisted_proposal = session.scalar(
                select(CommitProposal).where(
                    CommitProposal.proposal_id == edited["id"]
                )
            )
            persisted_commit = session.scalar(
                select(LocalCommitExecution).where(
                    LocalCommitExecution.commit_execution_id == commit["id"]
                )
            )
            persisted_push_plan = session.scalar(
                select(PushPlan).where(PushPlan.push_plan_id == push_plan["id"])
            )
            persisted_push = session.scalar(
                select(PushExecution).where(
                    PushExecution.push_execution_id
                    == pushed.json()["push_execution"]["id"]
                )
            )
            assert persisted_proposal is not None
            assert persisted_commit is not None
            assert persisted_push_plan is not None
            assert persisted_push is not None
            assert persisted_proposal.run_id == fixture.run_id
            assert persisted_proposal.task_id == fixture.task_id
            assert persisted_proposal.result_envelope_public_id == fixture.result["id"]
            assert persisted_proposal.candidate_public_id == fixture.candidate["id"]
            assert persisted_proposal.apply_plan_public_id == fixture.plan["id"]
            assert persisted_proposal.apply_session_public_id == fixture.applied[
                "session"
            ]["id"]
            assert persisted_commit.commit_proposal_id == persisted_proposal.id
            assert persisted_commit.result_envelope_public_id == fixture.result["id"]
            assert persisted_push_plan.local_commit_execution_id == persisted_commit.id
            assert persisted_push.push_plan_id == persisted_push_plan.id
            with pytest.raises(DBAPIError):
                session.execute(
                    text(
                        "UPDATE push_plans SET status_at_creation = status_at_creation "
                        "WHERE id = :id"
                    ),
                    {"id": persisted_push_plan.id},
                )
                session.flush()
            session.rollback()


def test_owner_commit_requires_exact_owner_and_current_applied_evidence(
    tmp_path: Path,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        proposed = _create_proposal(fixture)
        assert proposed.status_code == 200, proposed.text
        proposal = proposed.json()["proposal"]
        assert proposal["status"] == "READY"

        other_password = "other-owner-password-19-1d"
        password_hash, password_salt = hash_password(other_password)
        token = "vol19-owner-commit-push-other-session-token"
        with fixture.factory() as session:
            other = User(
                username="other-owner-19-1d",
                password_hash=password_hash,
                password_salt=password_salt,
                is_active=True,
            )
            session.add(other)
            session.flush()
            session.add(
                SessionToken(
                    user_id=other.id,
                    token_hash=hash_token(token),
                    expires_at=utc_now() + timedelta(hours=1),
                )
            )
            session.commit()
        other_headers = {"Authorization": f"Bearer {token}"}
        hidden = fixture.client.get(
            f"/api/post-apply-verifications/{fixture.verification['id']}/commit-proposals",
            headers=other_headers,
        )
        hidden_approval = fixture.client.post(
            f"/api/commit-proposals/{proposal['id']}/approvals",
            headers=other_headers,
            json={
                "confirmation": "APPROVE_COMMIT_PROPOSAL",
                "expected_proposal_digest": proposal["proposal_digest"],
                "expected_proposal_version": proposal["version"],
            },
        )
        assert hidden.status_code == 404
        assert hidden_approval.status_code == 404

        (fixture.source_repo / "codex-result.txt").write_text("drifted after proposal\n")
        approved = _approve_proposal(fixture, proposal)
        assert approved.status_code == 200, approved.text
        approval = approved.json()["proposal"]["approval"]
        blocked = _confirm_commit(fixture, proposal, approval)
        assert blocked.status_code == 409, blocked.text
        assert _error_code(blocked) in {
            "COMMIT_PROPOSAL_EXPIRED",
            "POST_APPLY_TARGET_CHANGED",
            "TARGET_CONTENT_CHANGED",
            "APPLIED_PATH_CHANGED",
        }
        assert _git(fixture.source_repo, "rev-parse", "HEAD") == fixture.baseline_head
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(LocalCommitExecution)) == 0
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0


def test_push_remote_movement_and_exit_zero_without_receipt_never_claim_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        delivery_commit = str(commit["commit_oid"])
        reviewed = fixture.client.post(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
            json={},
        )
        assert reviewed.status_code == 200, reviewed.text
        plan = reviewed.json()["push_plan"]
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

        calls: list[str] = []

        def successful_without_remote_effect(root: Path, refspec: str):
            calls.append(refspec)
            return subprocess.CompletedProcess(
                ["git", "push"], returncode=0, stdout=b"ok\n", stderr=b""
            )

        monkeypatch.setattr(
            push_delivery_service,
            "_run_standard_push",
            successful_without_remote_effect,
        )
        attempted = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_approval_digest": approval["advanced"]["approval_digest"],
            },
        )
        assert attempted.status_code == 200, attempted.text
        assert calls == [f"{delivery_commit}:refs/heads/main"]
        execution = attempted.json()["push_execution"]
        assert execution["state"] == "RECONCILIATION_BLOCKED"
        assert execution["canonical_state"] == "NEEDS_REVIEW"
        assert execution["remote_receipt_verified"] is False
        assert attempted.json()["delivery_result"]["status"] == "NOT_DELIVERED"
        assert attempted.json()["delivery_result"]["complete"] is False
        assert _bare_ref(fixture.origin) == fixture.baseline_head

        retry = fixture.client.post(
            f"/api/push-plans/{plan['id']}/push-attempts",
            headers=fixture.headers,
            json={
                "confirmation": "PUSH_TO_ORIGIN_MAIN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_approval_digest": approval["advanced"]["approval_digest"],
            },
        )
        assert retry.status_code == 200, retry.text
        assert calls == [f"{delivery_commit}:refs/heads/main"]
        assert retry.json()["push_execution"]["canonical_state"] == "NEEDS_REVIEW"

    with _canonical_applied_delivery(tmp_path / "remote-moved") as fixture:
        _proposal, _approval, commit = _commit_delivery(fixture)
        reviewed = fixture.client.post(
            f"/api/local-commits/{commit['id']}/push-plans",
            headers=fixture.headers,
            json={},
        )
        assert reviewed.status_code == 200, reviewed.text
        plan = reviewed.json()["push_plan"]

        baseline_tree = _git(fixture.source_repo, "rev-parse", f"{fixture.baseline_head}^{{tree}}")
        moved_commit = _git(
            fixture.source_repo,
            "commit-tree",
            baseline_tree,
            "-p",
            fixture.baseline_head,
            "-m",
            "independent remote advance",
        )
        _copy_objects(fixture.source_repo, fixture.origin)
        run_command(
            fixture.origin.parent,
            "git",
            "--git-dir",
            str(fixture.origin),
            "update-ref",
            "refs/heads/main",
            moved_commit,
            fixture.baseline_head,
        )
        assert _bare_ref(fixture.origin) == moved_commit
        blocked = fixture.client.post(
            f"/api/push-plans/{plan['id']}/approvals",
            headers=fixture.headers,
            json={
                "confirmation": "APPROVE_PUSH_PLAN",
                "expected_plan_digest": plan["advanced"]["plan_digest"],
                "expected_plan_version": plan["version"],
            },
        )
        assert blocked.status_code == 409, blocked.text
        assert _error_code(blocked) in {"REMOTE_MOVED", "NON_FAST_FORWARD"}
        assert _bare_ref(fixture.origin) == moved_commit
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0


def test_commit_setup_validation_and_projection_do_not_create_side_effects(
    tmp_path: Path,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        invalid = fixture.client.post(
            f"/api/post-apply-verifications/{fixture.verification['id']}/commit-proposals",
            headers=fixture.headers,
            json={
                "expected_verification_digest": fixture.verification["advanced"][
                    "verification_digest"
                ],
                "subject": "\n",
                "body": "",
            },
        )
        assert invalid.status_code == 422

        # Empty local values override any developer-machine global identity and
        # exercise the production `git var` readiness check deterministically.
        run_command(fixture.source_repo, "git", "config", "user.name", "")
        run_command(fixture.source_repo, "git", "config", "user.email", "")
        reviewed = _create_proposal(fixture)
        assert reviewed.status_code in {200, 409}, reviewed.text
        if reviewed.status_code == 200:
            proposal = reviewed.json()["proposal"]
            assert proposal["status"] in {"BLOCKED", "EXPIRED"}
            assert reviewed.json()["author_readiness"]["status"] == "NEEDS_SETUP"
            assert reviewed.json()["author_readiness"]["ready"] is False
            assert {
                item.get("code") for item in proposal["blockers"] if isinstance(item, dict)
            } & {"GIT_IDENTITY_MISSING", "GIT_IDENTITY_NOT_READY"}
        else:
            assert _error_code(reviewed) in {
                "GIT_IDENTITY_MISSING",
                "GIT_IDENTITY_NOT_READY",
                "GIT_IDENTITY_INVALID",
            }
        assert _git(fixture.source_repo, "rev-parse", "HEAD") == fixture.baseline_head
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        with fixture.factory() as session:
            assert session.scalar(select(func.count()).select_from(LocalCommitExecution)) == 0
            assert session.scalar(select(func.count()).select_from(PushPlan)) == 0
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0


def test_commit_message_and_command_output_cover_common_secret_forms(
    tmp_path: Path,
) -> None:
    bearer_material = "A" * 32
    generic_token_material = "B" * 32
    sensitive_messages = (
        "Authorization: Bearer " + bearer_material,
        "token=" + generic_token_material,
    )
    error_codes: list[str] = []
    for message in sensitive_messages:
        try:
            _safe_message("safe subject", message)
        except CommitBuilderError as exc:
            error_codes.append(exc.code)
    assert error_codes == ["COMMIT_MESSAGE_SENSITIVE", "COMMIT_MESSAGE_SENSITIVE"]

    sanitized = _sanitize_output(
        (sensitive_messages[0] + "\n" + sensitive_messages[1]).encode("utf-8"),
        root=tmp_path / "source-repo",
    )
    leak_free = not any(value in sanitized for value in (
        bearer_material,
        generic_token_material,
    ))
    assert leak_free is True
    assert sanitized.count("<redacted>") == 2


def test_owner_ui_projects_author_readiness_status_instead_of_raw_object() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "static_cockpit"
        / "vol12_static_mvp"
        / "twos_command_center.js"
    ).read_text(encoding="utf-8")
    assert "const authorReadiness = objectRecord(parts.commitDelivery.author_readiness);" in script
    assert "authorReadiness.status_label || authorReadiness.status" in script
    assert (
        "parts.proposal.author_readiness || parts.commitDelivery.author_readiness"
        not in script
    )


def test_git_hook_failure_is_a_commit_failure_and_never_starts_push(
    tmp_path: Path,
) -> None:
    with _canonical_applied_delivery(tmp_path) as fixture:
        proposed = _create_proposal(fixture)
        assert proposed.status_code == 200, proposed.text
        proposal = proposed.json()["proposal"]
        approved = _approve_proposal(fixture, proposal)
        assert approved.status_code == 200, approved.text
        approval = approved.json()["proposal"]["approval"]

        hook_marker = fixture.source_repo / ".git" / "twos-owner-hook-failed"
        hook = fixture.source_repo / ".git" / "hooks" / "pre-commit"
        bearer_material = "C" * 32
        generic_token_material = "D" * 32
        hook.write_text(
            "#!/bin/sh\n"
            f"printf attempted > {hook_marker}\n"
            f"printf '%s\\n' 'Authorization: Bearer {bearer_material}' >&2\n"
            f"printf '%s\\n' 'token={generic_token_material}' >&2\n"
            "exit 17\n"
        )
        hook.chmod(0o755)
        wrong_literal = fixture.client.post(
            f"/api/commit-proposals/{proposal['id']}/local-commits",
            headers=fixture.headers,
            json={
                "confirmation": "NOT_A_COMMIT_CONFIRMATION",
                "expected_proposal_digest": proposal["proposal_digest"],
                "expected_approval_digest": approval["approval_digest"],
            },
        )
        assert wrong_literal.status_code == 422
        failed = _confirm_commit(fixture, proposal, approval)
        assert failed.status_code == 409, failed.text
        assert _error_code(failed) in {
            "GIT_COMMIT_FAILED",
            "COMMIT_COMMAND_FAILED",
            "COMMIT_HOOK_FAILED",
        }
        assert hook_marker.read_text() == "attempted"
        assert _git(fixture.source_repo, "rev-parse", "HEAD") == fixture.baseline_head
        assert _bare_ref(fixture.origin) == fixture.baseline_head
        with fixture.factory() as session:
            executions = list(
                session.scalars(select(LocalCommitExecution).order_by(LocalCommitExecution.id))
            )
            assert len(executions) == 1
            assert executions[0].state == "FAILED"
            # Git reports the failed Commit process as nonzero; hook-specific
            # exit codes are not guaranteed to be propagated verbatim.
            assert executions[0].command_exit_code not in {None, 0}
            assert json.loads(executions[0].hooks_evidence_json)["hooks_enabled"] is True
            stored_output = executions[0].command_output_json
            leak_free = not any(value in stored_output for value in (
                bearer_material,
                generic_token_material,
            ))
            assert leak_free is True
            assert stored_output.count("<redacted>") >= 2
            assert session.scalar(select(func.count()).select_from(PushPlan)) == 0
            assert session.scalar(select(func.count()).select_from(PushExecution)) == 0
