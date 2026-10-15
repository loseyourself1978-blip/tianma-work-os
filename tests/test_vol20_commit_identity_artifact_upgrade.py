"""Same-path desktop build upgrade/rollback using only private synthetic data."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import sqlite3

import httpx
import pytest

from tests import test_vol20_macos_artifact as artifact

OLD = os.environ.get("TWOS_TEST_OLD_MACOS_APP")
NEW = os.environ.get("TWOS_TEST_MACOS_APP")
pytestmark = pytest.mark.skipif(not (OLD and NEW), reason="Requires both retained desktop artifacts")


def test_frozen_same_path_upgrade_backup_restart_and_rollback(tmp_path, monkeypatch):
    old_info = plistlib.loads((Path(OLD) / "Contents/Info.plist").read_bytes())
    new_info = plistlib.loads((Path(NEW) / "Contents/Info.plist").read_bytes())
    assert old_info["CFBundleVersion"] == "101.1"
    assert new_info["CFBundleVersion"] == "101.2"
    assert old_info["CFBundleShortVersionString"] == new_info["CFBundleShortVersionString"] == "1.0.1"
    fixed = tmp_path / "Applications/Tianma Work OS.app"
    fixed.parent.mkdir()
    shutil.copytree(OLD, fixed, symlinks=True)
    monkeypatch.setattr(artifact, "APP", str(fixed))
    root = tmp_path / "isolated-desktop"
    password = secrets.token_urlsafe(24)
    with artifact.service(root) as (_, ready):
        base = ready["url"].removesuffix("/projects").removesuffix("/twos")
        with httpx.Client(base_url=base, trust_env=False, headers={"Origin": base}, timeout=30) as client:
            post = lambda path, payload: artifact.post(client, path, payload)
            post("/api/setup/start", {"confirmation": "START_FIRST_RUN"})
            post("/api/setup/start", {"confirmation": "CONFIRM_INSTALLATION"})
            post("/api/setup/owner", {"username": "upgrade-fixture", "password": password,
                "password_confirmation": password, "setup_authorization": ready["setup"],
                "request_id": "commit-identity-upgrade-fixture-001"})
            post("/api/setup/managed-workspace", {"confirmed": True})
            post("/api/setup/optional-tools", {"decision": "skip"})
            post("/api/setup/finish", {"confirmation": "FINISH_FIRST_RUN"})
            project = post("/api/projects", {"key": "UPGRADE", "name": "Synthetic upgrade project"})
            workspace = post(f"/api/projects/{project['id']}/managed-workspace", {"confirmed": True})
            task = post("/api/tasks", {"project_id": project["id"], "title": "Retain my existing task",
                "workflow_type": "general", "development_task": "Preserve the synthetic persistence fixture."})
            contract = post(f"/api/tasks/{task['id']}/artifact-verification",
                {"path": "result.txt", "expected_text": "PERSISTED FIXTURE\n"})
    config = json.loads((root / "data/installation.json").read_text())
    shutil.copytree(root / "data", root / "data-backup", symlinks=True)
    source = Path(workspace["workspace"])
    (source / "result.txt").write_text("PERSISTED FIXTURE\n")
    shutil.copytree(source, root / "workspace-backup", symlinks=True)
    original_index = (source / ".git/index").read_bytes()
    original_config = (source / ".git/config").read_bytes()
    original_head = (source / ".git/refs/heads/main").read_bytes()
    retained_old = tmp_path / "retained-101.1.app"
    fixed.rename(retained_old)
    shutil.copytree(NEW, fixed, symlinks=True)
    for phase in ("upgrade", "restart", "rollback"):
        if phase == "rollback":
            fixed.rename(tmp_path / "retained-101.2.app")
            retained_old.rename(fixed)
        with artifact.service(root) as (_, ready):
            assert not ready["setup"]
            base = ready["url"].removesuffix("/projects").removesuffix("/twos")
            with httpx.Client(base_url=base, trust_env=False, headers={"Origin": base}, timeout=30) as client:
                artifact.post(client, "/api/auth/login", {"username": "upgrade-fixture", "password": password})
                assert client.get("/api/setup/status").json()["state"] == "ready"
                assert any(item["id"] == task["id"] for item in client.get("/api/tasks").json())
                assert client.get(f"/api/projects/{project['id']}/workspace").json()["workspace"] == str(source)
                assert client.get(f"/api/tasks/{task['id']}/artifact-verification").json()["contract"] == contract["contract"]
                page = client.get("/twos").text
                assert ('id="commit-identity-dialog"' in page) is (phase != "rollback")
                assert client.get("/api/health").json()["schema"] == "vol20.002"
        saved = json.loads((root / "data/installation.json").read_text())
        assert saved["installation_id"] == config["installation_id"]
        assert saved["runtime_environment"] == config["runtime_environment"]
        assert saved["port"] == config["port"]
        assert (source / "result.txt").read_text() == "PERSISTED FIXTURE\n"
        assert (source / ".git/index").read_bytes() == original_index
        assert (source / ".git/config").read_bytes() == original_config
        assert (source / ".git/refs/heads/main").read_bytes() == original_head
        with sqlite3.connect(root / "data/twos.sqlite3") as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # Verify backups remain intact and readable after both binaries opened live data.
    with sqlite3.connect(root / "data-backup/twos.sqlite3") as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT title FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == task["title"]
    assert (root / "workspace-backup/result.txt").read_text() == "PERSISTED FIXTURE\n"
