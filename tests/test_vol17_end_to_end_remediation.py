from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pytest
from fastapi.testclient import TestClient

from tests.test_self_hosting import start_codex_run
import twos_runtime.self_hosting as self_hosting
from twos_runtime.app import create_app
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import (
    AIModelInvocationEvidence,
    AuditEvent,
    CodexInstructionPack,
    CodexRun,
)
from twos_runtime.self_hosting import (
    capture_source_snapshot,
    hydrate_source_snapshot,
    pack_routing_binding_error,
)


OWNER_PASSWORD = "owner-password-123"
SECRET_SENTINEL = "oa04-never-return-this-secret-value"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result


def make_source_repo(tmp_path: Path, *, tracked_secret: bool = False) -> Path:
    repo = tmp_path / "source-repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "vol17-test@example.invalid")
    run_git(repo, "config", "user.name", "Vol.17 Test")
    (repo / "src").mkdir()
    (repo / "src" / "service.py").write_text("VALUE = 'committed'\n")
    (repo / "README.md").write_text("# Vol.17 snapshot fixture\n")
    (repo / ".gitignore").write_text("*.ignored\n")
    if tracked_secret:
        (repo / "config").mkdir()
        (repo / "config" / "credentials.json").write_text(
            json.dumps({"credential": SECRET_SENTINEL}) + "\n"
        )
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", "fixture baseline")
    return repo


def make_client(tmp_path: Path, source_repo: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'vol17-targeted.sqlite3'}",
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "execution-worktrees",
        codex_executable=str(tmp_path / "codex-is-intentionally-not-invoked"),
    )
    return TestClient(create_app(settings=settings, start_scheduler=False))


def signup_and_project(client: TestClient) -> int:
    signed_up = client.post(
        "/api/auth/signup",
        json={"username": "owner", "password": OWNER_PASSWORD},
    )
    assert signed_up.status_code == 201, signed_up.text
    projects = client.get("/api/projects")
    assert projects.status_code == 200, projects.text
    return next(item["id"] for item in projects.json() if item["key"] == "twos")


def create_minimal_development_task(client: TestClient, project_id: int, text: str) -> dict:
    created = client.post(
        "/api/tasks",
        json={"project_id": project_id, "development_task": text},
    )
    assert created.status_code == 200, created.text
    return created.json()


def compose_and_generate_pack(client: TestClient, task_id: int) -> dict:
    composed = client.post("/api/ai/team-compose", json={"task_id": task_id})
    assert composed.status_code == 200, composed.text
    generated = client.post(f"/api/tasks/{task_id}/codex-packs")
    assert generated.status_code == 200, generated.text
    return generated.json()


def source_files_fingerprint(repo: Path) -> dict[str, str]:
    fingerprint: dict[str, str] = {}
    for candidate in sorted(repo.rglob("*")):
        if ".git" in candidate.relative_to(repo).parts or not candidate.is_file():
            continue
        relative = candidate.relative_to(repo).as_posix()
        fingerprint[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return fingerprint


def test_dirty_source_snapshot_hydrates_modified_and_untracked_with_zero_staged_files(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    (source_repo / "src" / "service.py").write_text("VALUE = 'owner-approved dirty state'\n")
    (source_repo / "tests").mkdir()
    (source_repo / "tests" / "test_owner_snapshot.py").write_text(
        "def test_owner_snapshot():\n    assert True\n"
    )

    assert run_git(source_repo, "diff", "--cached", "--name-only").stdout == ""
    status_before = run_git(
        source_repo, "status", "--porcelain", "--untracked-files=all"
    ).stdout
    files_before = source_files_fingerprint(source_repo)
    assert " M src/service.py" in status_before
    assert "?? tests/test_owner_snapshot.py" in status_before

    snapshot = capture_source_snapshot(source_repo)
    manifest = {item["path"]: item for item in snapshot["included_manifest"]}
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot["digest"])
    assert snapshot["source_repository_identity_method"] == (
        "git-common-dir-device-inode-sha256-v2"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", snapshot["source_repository_identity"])
    assert manifest["src/service.py"]["kind"] == "tracked_change"
    assert manifest["src/service.py"]["staged"] is False
    assert manifest["tests/test_owner_snapshot.py"]["kind"] == "untracked"

    isolated = tmp_path / "hydrated-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        hydrate_source_snapshot(isolated, snapshot)
        assert (isolated / "src" / "service.py").read_text() == (
            "VALUE = 'owner-approved dirty state'\n"
        )
        assert (isolated / "tests" / "test_owner_snapshot.py").read_text().startswith(
            "def test_owner_snapshot"
        )
        assert capture_source_snapshot(
            isolated,
            approved_source_branch=str(snapshot["source_branch"]),
        )["digest"] == snapshot["digest"]
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))

    assert run_git(
        source_repo, "status", "--porcelain", "--untracked-files=all"
    ).stdout == status_before
    assert source_files_fingerprint(source_repo) == files_before


def test_historical_v1_repository_identity_snapshot_recomputes_exactly(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    (source_repo / "src" / "service.py").write_text(
        "VALUE = 'historical v1 approved state'\n"
    )
    snapshot = capture_source_snapshot(
        source_repo,
        source_repository_identity_method=(
            self_hosting.SOURCE_REPOSITORY_IDENTITY_METHOD_V1
        ),
    )
    assert snapshot["source_repository_identity_method"] == (
        "git-common-dir-sha256-v1"
    )

    isolated = tmp_path / "historical-v1-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        hydrate_source_snapshot(isolated, snapshot)
        recomputed = capture_source_snapshot(
            isolated,
            approved_source_branch=str(snapshot["source_branch"]),
            source_repository_identity_method=(
                self_hosting.SOURCE_REPOSITORY_IDENTITY_METHOD_V1
            ),
        )
        assert recomputed["source_repository_identity"] == snapshot[
            "source_repository_identity"
        ]
        assert recomputed["digest"] == snapshot["digest"]
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_preserves_index_state_rename_and_executable_mode(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    (source_repo / "rename_me.py").write_text("RENAMED = False\n")
    run_git(source_repo, "add", "rename_me.py")
    run_git(source_repo, "commit", "-m", "add rename fixture")

    (source_repo / "src" / "service.py").write_text("VALUE = 'staged'\n")
    run_git(source_repo, "add", "src/service.py")
    (source_repo / "src" / "service.py").write_text("VALUE = 'staged plus unstaged'\n")
    run_git(source_repo, "mv", "rename_me.py", "renamed_service.py")
    (source_repo / "README.md").chmod(0o755)
    run_git(source_repo, "add", "README.md")

    status_before = run_git(
        source_repo, "status", "--porcelain", "--untracked-files=all"
    ).stdout
    snapshot = capture_source_snapshot(source_repo)
    manifest = {item["path"]: item for item in snapshot["included_manifest"]}
    assert snapshot["schema"] == "twos.source_snapshot.v2"
    assert manifest["src/service.py"]["staged"] is True
    assert manifest["src/service.py"]["unstaged"] is True
    assert manifest["renamed_service.py"]["change_type"] == "renamed"
    assert manifest["renamed_service.py"]["previous_path"] == "rename_me.py"
    assert manifest["README.md"]["mode"] & 0o111

    isolated = tmp_path / "staged-hydrated-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        hydrate_source_snapshot(isolated, snapshot)
        assert capture_source_snapshot(
            isolated,
            approved_source_branch=str(snapshot["source_branch"]),
        )["digest"] == snapshot["digest"]
        assert run_git(
            isolated, "status", "--porcelain", "--untracked-files=all"
        ).stdout == status_before
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_restores_approved_restrictive_tracked_mode(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    (source_repo / "README.md").chmod(0o600)
    snapshot = capture_source_snapshot(source_repo)
    manifest = {item["path"]: item for item in snapshot["included_manifest"]}
    assert manifest["README.md"]["mode"] == 0o600

    isolated = tmp_path / "restrictive-mode-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        (isolated / "README.md").chmod(0o644)
        hydrate_source_snapshot(isolated, snapshot)
        assert (isolated / "README.md").stat().st_mode & 0o777 == 0o600
        assert capture_source_snapshot(
            isolated,
            approved_source_branch=str(snapshot["source_branch"]),
        )["digest"] == snapshot["digest"]
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_blocks_missing_tracked_file(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    isolated = tmp_path / "missing-tracked-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        (isolated / "README.md").unlink()
        with pytest.raises(
            RuntimeError,
            match="Approved tracked source file is unavailable during hydration",
        ):
            hydrate_source_snapshot(isolated, snapshot)
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_blocks_digest_mismatch(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    snapshot["digest"] = "0" * 64
    isolated = tmp_path / "digest-mismatch-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="Approved source snapshot digest failed integrity validation",
        ):
            hydrate_source_snapshot(isolated, snapshot)
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_binds_recomputed_payload_to_approved_digest(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    approved_digest = str(snapshot["digest"])
    snapshot["exclusion_policy"] = str(snapshot["exclusion_policy"]) + " tampered"
    snapshot["digest"] = self_hosting._source_snapshot_digest(snapshot)
    assert snapshot["digest"] != approved_digest

    isolated = tmp_path / "approved-digest-binding-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="Source snapshot does not match the approved Pack and Run binding",
        ):
            hydrate_source_snapshot(
                isolated,
                snapshot,
                approved_digest=approved_digest,
            )
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_blocks_wrong_repository_head(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    (source_repo / "other.txt").write_text("different approved-repository HEAD\n")
    run_git(source_repo, "add", "other.txt")
    run_git(source_repo, "commit", "-m", "different fixture head")
    isolated = tmp_path / "wrong-repository-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        "HEAD",
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="Isolated workspace HEAD does not match the approved source snapshot",
        ):
            hydrate_source_snapshot(isolated, snapshot)
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_blocks_same_head_from_different_repository(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    other_repo = tmp_path / "same-head-other-repository"
    shutil.copytree(source_repo, other_repo, symlinks=True)
    assert run_git(other_repo, "rev-parse", "HEAD").stdout.strip() == snapshot["head_sha"]
    assert run_git(other_repo, "branch", "--show-current").stdout.strip() == "main"

    isolated = tmp_path / "same-head-other-worktree"
    run_git(
        other_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="workspace repository does not match the approved source snapshot",
        ):
            hydrate_source_snapshot(isolated, snapshot)
    finally:
        run_git(other_repo, "worktree", "remove", "--force", str(isolated))


def test_source_snapshot_hydration_binds_approval_branch_and_digest(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    isolated = tmp_path / "branch-bound-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="Source branch does not match the approved source snapshot",
        ):
            hydrate_source_snapshot(
                isolated,
                snapshot,
                approved_source_branch="same-head-other-branch",
            )

        tampered = dict(snapshot)
        tampered["source_branch"] = "same-head-other-branch"
        with pytest.raises(
            RuntimeError,
            match="Approved source snapshot digest failed integrity validation",
        ):
            hydrate_source_snapshot(isolated, tampered)
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_historical_v2_snapshot_hydrates_but_requires_regeneration_for_new_run(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    snapshot.pop("source_repository_identity_method")
    snapshot.pop("source_repository_identity")
    snapshot["digest"] = self_hosting._source_snapshot_digest(snapshot)

    isolated = tmp_path / "legacy-v2-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        hydrate_source_snapshot(isolated, snapshot, approved_digest=snapshot["digest"])
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))

    with make_client(tmp_path, source_repo) as client:
        project_id = signup_and_project(client)
        task = create_minimal_development_task(
            client,
            project_id,
            "Prove a legacy Pack cannot admit a new Run.",
        )
        pack = compose_and_generate_pack(client, task["id"])
        factory = client.app.state.session_factory
        with factory() as session:
            pack_row = session.get(CodexInstructionPack, pack["id"])
            assert pack_row is not None
            stored = json.loads(pack_row.source_snapshot_json)
            stored.pop("source_repository_identity_method")
            stored.pop("source_repository_identity")
            stored["digest"] = self_hosting._source_snapshot_digest(stored)
            pack_row.source_snapshot_json = json.dumps(
                stored,
                sort_keys=True,
                separators=(",", ":"),
            )
            pack_row.source_snapshot_digest = stored["digest"]
            session.commit()

        approval = client.post(
            f"/api/tasks/{task['id']}/codex-packs/{pack['id']}/approve"
        )
        assert approval.status_code == 409, approval.text
        assert approval.json()["error"]["details"] == (
            "The approved Pack predates repository identity binding. "
            "Regenerate Codex Pack."
        )


def test_source_snapshot_hydration_blocks_tracked_mode_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo = make_source_repo(tmp_path)
    snapshot = capture_source_snapshot(source_repo)
    isolated = tmp_path / "permission-error-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    real_chmod = os.chmod

    def deny_tracked_mode_restore(path: str | bytes | os.PathLike[str], mode: int) -> None:
        if Path(path).name == "README.md":
            raise PermissionError("fixture denied tracked mode restoration")
        real_chmod(path, mode)

    monkeypatch.setattr(self_hosting.os, "chmod", deny_tracked_mode_restore)
    try:
        with pytest.raises(
            PermissionError,
            match="fixture denied tracked mode restoration",
        ):
            hydrate_source_snapshot(isolated, snapshot)
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_pack_binds_dirty_snapshot_and_source_change_returns_regenerate_blocker(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    (source_repo / "src" / "service.py").write_text("VALUE = 'pack-approved dirty state'\n")
    (source_repo / "tests").mkdir()
    (source_repo / "tests" / "test_untracked_orchestration.py").write_text(
        "def test_untracked_orchestration():\n    assert True\n"
    )
    assert run_git(source_repo, "diff", "--cached", "--name-only").stdout == ""

    with make_client(tmp_path, source_repo) as client:
        project_id = signup_and_project(client)
        task = create_minimal_development_task(
            client,
            project_id,
            "Preserve the approved dirty source and produce one bounded smoke artifact.",
        )
        pack = compose_and_generate_pack(client, task["id"])
        public_snapshot = pack["source_snapshot"]
        included = {item["path"] for item in public_snapshot["included_manifest"]}
        assert pack["source_snapshot_digest"] == public_snapshot["digest"]
        assert {"src/service.py", "tests/test_untracked_orchestration.py"}.issubset(included)
        assert "tracked_patch_b64" not in public_snapshot
        assert "staged_patch_b64" not in public_snapshot
        assert "unstaged_patch_b64" not in public_snapshot
        assert "untracked_files" not in public_snapshot

        factory = client.app.state.session_factory
        with factory() as session:
            pack_row = session.get(CodexInstructionPack, pack["id"])
            assert pack_row is not None
            stored_snapshot = json.loads(pack_row.source_snapshot_json)
        assert stored_snapshot["digest"] == pack["source_snapshot_digest"]
        isolated = tmp_path / "pack-hydrated-worktree"
        run_git(
            source_repo,
            "worktree",
            "add",
            "--detach",
            str(isolated),
            str(stored_snapshot["head_sha"]),
        )
        try:
            hydrate_source_snapshot(isolated, stored_snapshot)
            assert (isolated / "src" / "service.py").read_text() == (
                "VALUE = 'pack-approved dirty state'\n"
            )
            assert (isolated / "tests" / "test_untracked_orchestration.py").exists()
        finally:
            run_git(source_repo, "worktree", "remove", "--force", str(isolated))

        approved = client.post(
            f"/api/tasks/{task['id']}/codex-packs/{pack['id']}/approve"
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["approved"] is True

        (source_repo / "src" / "service.py").write_text("VALUE = 'changed after approval'\n")
        eligibility = client.get(f"/api/tasks/{task['id']}/run-eligibility")
        assert eligibility.status_code == 200, eligibility.text
        payload = eligibility.json()
        source_blocker = next(
            item for item in payload["blockers"] if item["code"] == "SOURCE_CHANGED_SINCE_APPROVAL"
        )
        assert payload["eligible"] is False
        assert source_blocker == {
            "code": "SOURCE_CHANGED_SINCE_APPROVAL",
            "message": "Source changed since approval. Regenerate Codex Pack.",
            "next_action": "Regenerate Codex Pack",
            "control": "Regenerate Codex Pack",
        }

        rejected = start_codex_run(client, {}, task["id"], pack)
        assert rejected.status_code == 409, rejected.text
        details = rejected.json()["error"]["details"]
        assert details["type"] == "RUN_INELIGIBLE"
        assert any(
            item["code"] == "SOURCE_CHANGED_SINCE_APPROVAL"
            for item in details["blockers"]
        )
        assert client.get(f"/api/tasks/{task['id']}/codex-runs").json() == []


def test_run_admission_blocks_same_head_wrong_branch_and_different_repository(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    with make_client(tmp_path, source_repo) as client:
        project_id = signup_and_project(client)
        task = create_minimal_development_task(
            client,
            project_id,
            "Bind one approved Pack to the exact source repository and branch.",
        )
        pack = compose_and_generate_pack(client, task["id"])
        approved = client.post(
            f"/api/tasks/{task['id']}/codex-packs/{pack['id']}/approve"
        )
        assert approved.status_code == 200, approved.text

        approved_head = run_git(source_repo, "rev-parse", "HEAD").stdout.strip()
        run_git(source_repo, "switch", "-c", "same-head-other-branch")
        assert run_git(source_repo, "rev-parse", "HEAD").stdout.strip() == approved_head
        branch_eligibility = client.get(
            f"/api/tasks/{task['id']}/run-eligibility"
        )
        assert branch_eligibility.status_code == 200, branch_eligibility.text
        assert any(
            blocker["code"] == "SOURCE_CHANGED_SINCE_APPROVAL"
            for blocker in branch_eligibility.json()["blockers"]
        )
        rejected = start_codex_run(client, {}, task["id"], pack)
        assert rejected.status_code == 409, rejected.text
        assert client.get(f"/api/tasks/{task['id']}/codex-runs").json() == []
        run_git(source_repo, "switch", "main")

        other_repo = tmp_path / "same-head-admission-repository"
        shutil.copytree(source_repo, other_repo, symlinks=True)
        assert run_git(other_repo, "rev-parse", "HEAD").stdout.strip() == approved_head
        assert run_git(other_repo, "branch", "--show-current").stdout.strip() == "main"
        factory = client.app.state.session_factory
        with factory() as session:
            pack_row = session.get(CodexInstructionPack, pack["id"])
            assert pack_row is not None
            error = pack_routing_binding_error(
                session,
                pack_row.task,
                pack_row,
                other_repo,
            )
        assert error == "Source changed since approval. Regenerate Codex Pack."


def add_excluded_secret_and_runtime_files(source_repo: Path) -> None:
    (source_repo / "src" / "service.py").write_text("VALUE = 'safe source change'\n")
    (source_repo / "safe_untracked.py").write_text("SAFE = True\n")
    (source_repo / ".env.oa04").write_text(f"TOKEN={SECRET_SENTINEL}\n")
    (source_repo / "runtime.sqlite3").write_text(SECRET_SENTINEL)
    (source_repo / "runtime.log").write_text(SECRET_SENTINEL)
    (source_repo / ".venv").mkdir()
    (source_repo / ".venv" / "credential.txt").write_text(SECRET_SENTINEL)


def test_snapshot_exclusions_are_hydratable_without_secret_material(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path, tracked_secret=True)
    add_excluded_secret_and_runtime_files(source_repo)

    snapshot = capture_source_snapshot(source_repo)
    excluded = {item["path"]: item["reason"] for item in snapshot["excluded_manifest"]}
    assert excluded["config/credentials.json"] == "credential_or_secret"
    assert excluded[".env.oa04"] == "credential_or_secret"
    assert excluded["runtime.sqlite3"] == "runtime_or_generated"
    assert excluded["runtime.log"] == "runtime_or_generated"
    assert excluded[".venv/credential.txt"] == "runtime_or_cache"
    assert SECRET_SENTINEL not in json.dumps(snapshot)
    assert base64.b64encode(SECRET_SENTINEL.encode()).decode() not in json.dumps(snapshot)

    isolated = tmp_path / "secret-safe-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        hydrate_source_snapshot(isolated, snapshot)
        assert (isolated / "safe_untracked.py").exists()
        for relative in (
            "config/credentials.json",
            ".env.oa04",
            "runtime.sqlite3",
            "runtime.log",
            ".venv/credential.txt",
        ):
            assert not (isolated / relative).exists()
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_snapshot_hydration_unlinks_excluded_symlinks_without_touching_targets(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    external_target = tmp_path / "external-target.txt"
    external_target.write_text("outside must survive\n")
    (source_repo / "inside-link").symlink_to("README.md")
    (source_repo / "outside-link").symlink_to(external_target)
    snapshot = capture_source_snapshot(source_repo)
    excluded = {item["path"] for item in snapshot["excluded_manifest"]}
    assert {"inside-link", "outside-link"}.issubset(excluded)

    isolated = tmp_path / "excluded-symlink-worktree"
    run_git(
        source_repo,
        "worktree",
        "add",
        "--detach",
        str(isolated),
        str(snapshot["head_sha"]),
    )
    try:
        (isolated / "inside-link").symlink_to("README.md")
        (isolated / "outside-link").symlink_to(external_target)
        readme_before = (isolated / "README.md").read_bytes()

        hydrate_source_snapshot(isolated, snapshot)

        assert not (isolated / "inside-link").exists()
        assert not (isolated / "outside-link").exists()
        assert not (isolated / "inside-link").is_symlink()
        assert not (isolated / "outside-link").is_symlink()
        assert (isolated / "README.md").read_bytes() == readme_before
        assert external_target.read_text() == "outside must survive\n"
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))


def test_pack_apis_never_expose_excluded_secret_contents(tmp_path: Path) -> None:
    source_repo = make_source_repo(tmp_path, tracked_secret=True)
    add_excluded_secret_and_runtime_files(source_repo)
    snapshot = capture_source_snapshot(source_repo)
    assert SECRET_SENTINEL not in json.dumps(snapshot)
    assert base64.b64encode(SECRET_SENTINEL.encode()).decode() not in json.dumps(snapshot)

    with make_client(tmp_path, source_repo) as client:
        project_id = signup_and_project(client)
        task = create_minimal_development_task(client, project_id, "Create a secret-safe Pack.")
        pack = compose_and_generate_pack(client, task["id"])
        responses = [
            pack,
            client.get(f"/api/tasks/{task['id']}/codex-packs").json(),
            client.get(f"/api/tasks/{task['id']}/codex-packs/current").json(),
            client.get("/api/audit").json(),
        ]
        serialized = json.dumps(responses)
        assert SECRET_SENTINEL not in serialized
        assert base64.b64encode(SECRET_SENTINEL.encode()).decode() not in serialized
        assert "source_snapshot_json" not in serialized
        assert "tracked_patch_b64" not in serialized
        assert "staged_patch_b64" not in serialized
        assert "unstaged_patch_b64" not in serialized
        assert "untracked_files" not in serialized
        assert "config/credentials.json" not in serialized
        assert "[credential-shaped path withheld]" in serialized

        factory = client.app.state.session_factory
        with factory() as session:
            row = session.get(CodexInstructionPack, pack["id"])
            assert row is not None
            assert SECRET_SENTINEL not in row.source_snapshot_json
            assert all(SECRET_SENTINEL not in event.details for event in session.query(AuditEvent))


def test_twos_is_canonical_and_legacy_html_redirects_without_exposing_legacy_location(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    with make_client(tmp_path, source_repo) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code in {302, 303, 307, 308}
        assert root.headers["location"] == "/twos"

        canonical = client.get("/twos", follow_redirects=False)
        assert canonical.status_code == 200
        assert canonical.url.path == "/twos"
        assert "Set up Codex" in canonical.text
        assert "Manage Codex" in canonical.text
        assert "Check availability" in canonical.text
        assert "Save and assign" in canonical.text
        assert "Codex model identifier" not in canonical.text
        assert 'name="model_identifier"' not in canonical.text
        assert '<label for="setup-model-search">Model</label>' in canonical.text
        assert '<label for="setup-execution-target">Execution target</label>' in canonical.text
        assert 'id="setup-model-options"' in canonical.text
        assert 'role="listbox"' in canonical.text
        assert re.search(
            r'<input\s+id="setup-model-search"[^>]*role="combobox"[^>]*aria-controls="setup-model-options"',
            canonical.text,
        )
        assert re.search(
            r'<button\s+id="check-codex-availability"[^>]*class="button button-secondary"[^>]*disabled',
            canonical.text,
        )
        assert re.search(
            r'<button\s+id="verify-codex-connection"[^>]*class="button button-primary"[^>]*disabled',
            canonical.text,
        )
        assert re.search(
            r'<button\s+id="save-assign-codex"[^>]*class="button button-secondary"[^>]*disabled',
            canonical.text,
        )
        assert 'id="review-pack"' in canonical.text
        assert re.search(r'<a\s+id="view-result"[^>]*\shidden(?:\s|>)', canonical.text)
        assert re.search(r'<section\s+id="result-card"[^>]*\shidden(?:\s|>)', canonical.text)
        advanced = re.search(r"<details\s+id=\"advanced-panel\"([^>]*)>", canonical.text)
        assert advanced is not None
        assert "open" not in advanced.group(1).split()

        script_match = re.search(
            r'<script[^>]+src="([^"]*twos_command_center\.js[^"]*)"',
            canonical.text,
        )
        assert script_match is not None
        script_url = urljoin("http://testserver/twos", script_match.group(1))
        script = client.get(urlparse(script_url).path + (
            f"?{urlparse(script_url).query}" if urlparse(script_url).query else ""
        ))
        assert script.status_code == 200
        assert "No matching supported model" in script.text
        assert "Select a supported model from the list before checking availability." in script.text
        assert 'api("/api/model-catalog?adapter=codex_cli&capability="' in script.text
        assert "setupModelIdentifier" not in script.text
        assert "setCustomValidity(message)" not in script.text
        assert (
            "Provider connectivity and model availability remain unverified"
            in script.text
        )

        legacy = client.get(
            "/static_cockpit/vol12_static_mvp/twos_command_center.html",
            follow_redirects=False,
        )
        assert legacy.status_code in {302, 303, 307, 308}
        assert legacy.headers["location"] == "/twos"

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["version"] == "0.17.0"
        assert "v=0.17.0" in canonical.text


def test_minimal_development_task_derives_traceable_defaults_without_execution_side_effects(
    tmp_path: Path,
) -> None:
    source_repo = make_source_repo(tmp_path)
    development_task = (
        "Add a durable Owner-visible status panel.\n\n"
        "Keep the change bounded and preserve the complete submitted wording."
    )
    with make_client(tmp_path, source_repo) as client:
        project_id = signup_and_project(client)
        task = create_minimal_development_task(client, project_id, development_task)

        assert task["development_task"] == development_task
        assert task["title"] == "Add a durable Owner-visible status panel."
        assert task["workflow_type"] == "product_development"
        assert task["objective"] == "Complete the Development task exactly as specified."
        assert task["source_sync_summary"] == "None provided."
        assert task["required_output"] == (
            "The outputs explicitly requested by the Development task."
        )
        assert task["acceptance_target"] == (
            "The Development task requirements and explicit boundaries are satisfied."
        )
        assert task["implementation_scope"] == (
            "Only changes required by the Development task are permitted."
        )
        assert task["provenance"] == {
            "objective": "derived",
            "source_feedback_context": "derived",
            "required_output": "derived",
            "acceptance_target": "derived",
            "implementation_scope": "derived",
        }

        edited = client.patch(
            f"/api/tasks/{task['id']}",
            json={"objective": "Owner-reviewed objective."},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["objective"] == "Owner-reviewed objective."
        assert edited.json()["provenance"]["objective"] == "owner-edited"
        assert edited.json()["provenance"]["source_feedback_context"] == "derived"

        pack = compose_and_generate_pack(client, task["id"])
        assert pack["status"] == "approval_required"
        assert development_task in pack["content"]

        factory = client.app.state.session_factory
        with factory() as session:
            assert session.query(CodexRun).count() == 0
            assert session.query(AIModelInvocationEvidence).count() == 0
