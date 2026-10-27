from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from tests.test_vol19_fresh_install_first_run import fresh_settings, start_owner_step, owner_payload, finish_setup, USERNAME, PASSWORD
from twos_runtime.app import create_app
from twos_runtime import artifact_verification, desktop
from scripts import build_macos

ROOT = Path(__file__).resolve().parents[1]


def settings_for(tmp_path):
    return replace(fresh_settings(tmp_path / "install"), managed_workspace_root=tmp_path / "projects")


def owner(client, settings):
    start_owner_step(client)
    response = client.post("/api/setup/owner", json=owner_payload(settings))
    assert response.status_code == 201, response.text


def test_managed_first_project_and_additional_project_restart(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        owner(client, settings)
        response = client.post("/api/setup/managed-workspace", json={"confirmed": True})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "optional_tools_pending"
        again = client.post("/api/setup/managed-workspace", json={"confirmed": True})
        assert again.status_code == 200, again.text
        finish_setup(client)
        project = client.post("/api/projects", json={"key": "DESKTOP", "name": "Desktop delivery"}).json()
        project_id = project["id"]
        assert not client.get(f"/api/projects/{project_id}/workspace").json()["authorized"]
        response = client.post(f"/api/projects/{project_id}/managed-workspace", json={"confirmed": True})
        assert response.status_code == 200, response.text
        workspace = Path(response.json()["workspace"])
        assert subprocess.check_output(["git", "status", "--porcelain"], cwd=workspace) == b""
        assert subprocess.check_output(["git", "rev-list", "--count", "HEAD"], cwd=workspace).strip() == b"1"
        assert not subprocess.check_output(["git", "remote"], cwd=workspace)
        assert client.post(f"/api/projects/{project_id}/managed-workspace", json={"confirmed": True}).status_code == 200
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        assert client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD}).status_code == 200
        saved = client.get(f"/api/projects/{project_id}/workspace").json()
        assert saved["authorized"] and saved["workspace"] == str(workspace)
        assert client.get("/api/setup/status").json()["state"] == "ready"


def test_managed_creation_requires_owner_and_explicit_confirmation(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        assert client.post("/api/setup/managed-workspace", json={"confirmed": True}).status_code in (401, 403)
        assert not settings.managed_workspace_root.exists()
        owner(client, settings)
        for body in ({}, {"confirmed": False}, {"confirmed": True, "path": "/tmp/escape"}):
            assert client.post("/api/setup/managed-workspace", json=body).status_code == 422
        assert not settings.managed_workspace_root.exists()


@pytest.mark.parametrize("unsafe", ["existing", "symlink", "permissions"])
def test_managed_workspace_does_not_adopt_or_overwrite_existing_data(tmp_path, unsafe):
    settings = settings_for(tmp_path)
    root = settings.managed_workspace_root
    if unsafe == "symlink":
        target = tmp_path / "foreign"
        target.mkdir()
        root.symlink_to(target, target_is_directory=True)
    else:
        root.mkdir(mode=0o700)
        if unsafe == "permissions":
            root.chmod(0o755)
        else:
            target = root / settings.installation_id / "My First Project"
            target.mkdir(parents=True)
            target.parent.chmod(0o700)
            (target / "Owner.txt").write_text("preserve")
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        owner(client, settings)
        response = client.post("/api/setup/managed-workspace", json={"confirmed": True})
        assert response.status_code in (400, 409), response.text
    if unsafe == "existing":
        assert (target / "Owner.txt").read_text() == "preserve"
        assert not (target / ".git").exists()


def test_frozen_builtin_has_closed_dispatch(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert artifact_verification.command() == (str(Path(sys.executable).resolve()), "--twos-verify")


def test_bundle_input_allowlist_excludes_owner_state(tmp_path):
    for name in ("twos_runtime/app.py", "static_cockpit/ui.html", "packaging/macos/service_entry.py"):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("fixture")
    (tmp_path / "auth.json").write_text("excluded")
    assert "auth.json" not in build_macos.source_inputs(tmp_path)


def test_executable_discovery_rejects_shared_writable_code(tmp_path):
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o777)
    assert not desktop.trusted_executable(executable)


def test_default_desktop_storage_is_separate_from_source_install():
    data, runtime, logs, projects = desktop.directories(Path("/Users/example"))
    assert data.name == runtime.name == logs.name == "Tianma Work OS Desktop"
    assert projects.name == "Tianma Work OS Projects"
    assert not runtime.is_relative_to(data)


def test_primary_docs_have_visual_installation_and_keep_advanced_source():
    current = (ROOT / "docs/OWNER_GUIDE.md").read_text()
    assert "双击 DMG" in current and "应用程序" in current
    assert "新建任务 / 会话" in current and "交付 Codex 执行" in current
    assert "LEGACY_OWNER_GUIDE.md" in current
    for command in ("./start-twos", "python3", "pip install", "venv", "git clone", "Terminal"):
        assert command not in current
    # The old project flow remains fully checked in its explicit historical guide.
    guide = (ROOT / "docs/LEGACY_OWNER_GUIDE.md").read_text()
    happy_path = guide.split("## 3. Fresh installation")[1].split("## 4.")[0]
    assert "Double-click" in happy_path and "Applications" in happy_path
    for command in ("./start-twos", "python3", "pip install", "venv", "git clone", "Terminal"):
        assert command not in guide
    troubleshooting = guide.split("## 24. Troubleshooting")[1].split("## 25.")[0]
    assert "Open Diagnostics" in troubleshooting and "Retry" in troubleshooting
    assert "Install trusted Python" not in troubleshooting
    assert "Only 1.0.1 backups" in guide
    assert "./start-twos" in (ROOT / "docs/ADVANCED_INSTALLATION.md").read_text()


def test_visual_error_catalog_and_setup_fragment_removed_before_requests():
    native = (ROOT / "packaging/macos/TianmaLauncher.swift").read_text()
    for code in ("DESKTOP_GIT_MISSING", "DESKTOP_GIT_LICENSE", "DESKTOP_PORT_OCCUPIED", "DESKTOP_RUNTIME_MISSING", "DESKTOP_STORAGE_UNAVAILABLE"):
        assert code in native
    js = (ROOT / "static_cockpit/vol12_static_mvp/twos_command_center.js").read_text()
    assert js.index('window.history.replaceState(null, ""') < js.index("  initializeSession();")
    assert "localStorage.setItem(\"setup" not in js
    assert "url.fragment = \"setup=\"" in native


def test_signing_rejects_wrong_certificate_before_mutation(tmp_path):
    out = tmp_path / "signed"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/sign_macos.py"), "--app", str(tmp_path / "absent.app"),
                             "--identity", "Apple Distribution: fixture", "--output", str(out)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Developer ID Application" in result.stderr
    assert not out.exists()


@pytest.mark.parametrize("fragment,accepted", [("setup=" + "fixture_" * 5, True), ("setup=invalid!", False), ("tab=projects", False)])
def test_desktop_setup_handoff_clears_history_and_never_uses_storage(fragment, accepted):
    script = (ROOT / "static_cockpit/vol12_static_mvp/twos_command_center.js").read_text()
    function = "function consumeDesktopSetupAuthorization()" + script.split("function consumeDesktopSetupAuthorization()", 1)[1].split("  consumeDesktopSetupAuthorization();", 1)[0]
    fixture = '''
const calls = []; const field = {hidden:false};
const elements = {firstRunSetupAuthorization:{value:"", closest:()=>field}};
const window = {location:{hash: FRAGMENT,pathname:"/twos",search:""},history:{replaceState:(...args)=>calls.push(args)}};
FUNCTION
consumeDesktopSetupAuthorization();
console.log(JSON.stringify({filled:!!elements.firstRunSetupAuthorization.value,hidden:field.hidden,calls}));
'''.replace("FRAGMENT", json.dumps("#" + fragment)).replace("FUNCTION", function)
    output = subprocess.check_output(["node", "-e", fixture], text=True)
    result = json.loads(output)
    assert result["filled"] is accepted and result["hidden"] is accepted
    assert result["calls"] == ([[None, "", "/twos"]] if fragment.startswith("setup=") else [])


def test_parallel_managed_authorization_is_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        owner(client, settings)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: client.post("/api/setup/managed-workspace", json={"confirmed": True}), range(2)))
        assert [response.status_code for response in replies] == [200, 200]
        assert len(list(settings.managed_workspace_root.rglob(".git"))) == 1
