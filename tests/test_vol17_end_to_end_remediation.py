from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse

from fastapi.testclient import TestClient

from twos_runtime.app import create_app
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import (
    AIModelInvocationEvidence,
    AuditEvent,
    CodexInstructionPack,
    CodexRun,
)
from twos_runtime.self_hosting import capture_source_snapshot, hydrate_source_snapshot


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
        assert capture_source_snapshot(isolated)["digest"] == snapshot["digest"]
    finally:
        run_git(source_repo, "worktree", "remove", "--force", str(isolated))

    assert run_git(
        source_repo, "status", "--porcelain", "--untracked-files=all"
    ).stdout == status_before
    assert source_files_fingerprint(source_repo) == files_before


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
        assert capture_source_snapshot(isolated)["digest"] == snapshot["digest"]
        assert run_git(
            isolated, "status", "--porcelain", "--untracked-files=all"
        ).stdout == status_before
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

        rejected = client.post(f"/api/tasks/{task['id']}/codex-runs")
        assert rejected.status_code == 409, rejected.text
        details = rejected.json()["error"]["details"]
        assert details["type"] == "RUN_INELIGIBLE"
        assert any(
            item["code"] == "SOURCE_CHANGED_SINCE_APPROVAL"
            for item in details["blockers"]
        )
        assert client.get(f"/api/tasks/{task['id']}/codex-runs").json() == []


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
            r'<button\s+id="check-codex-availability"[^>]*class="button button-primary"[^>]*disabled',
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
        assert "support and resolution remain unverified" in script.text

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
